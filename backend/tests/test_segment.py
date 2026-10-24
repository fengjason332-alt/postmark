"""Unit tests for backend/segment.py (synthetic data only). Run from the repo root:

    .venv/bin/python -W error -m unittest discover -s backend/tests -v

All coordinates below are invented city-centre points, not anyone's real data.
"""

import contextlib
import copy
import io
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import segment  # noqa: E402

CLEAN_COLUMNS = ["photo_id", "person", "file_name", "taken_at", "taken_utc",
                 "date", "lat", "lng", "has_gps"]
SENTINEL_NAME = "SENTINEL_SECRET_NAME_123.HEIC"
SENTINEL_CITY = "SENTINEL_CITY_XYZ"

HOME = (42.3601, -71.0589)      # Boston
CAMBRIDGE = (42.4101, -71.0589)  # ~5.6 km north of HOME
NYC = (40.7128, -74.0060)       # ~306 km
PVD = (41.8240, -71.4128)       # ~66 km (outside the default 50 km circle, inside 100 km)
MTL = (45.5017, -73.5673)       # ~403 km
CHI = (41.8781, -87.6298)


class Photos:
    """Builds a synthetic photos_clean frame (all values strings, like read_csv dtype=str)."""

    def __init__(self, person="tester"):
        self.rows = []
        self.person = person

    def add(self, day, hour, place=None, minute=0, utc=True):
        """Add one photo at local `day` `hour`:`minute` (UTC-05:00); place=None -> no GPS."""
        local = datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00")
        pid = f"p_{len(self.rows):010d}"
        self.rows.append({
            "photo_id": pid, "person": self.person, "file_name": SENTINEL_NAME,
            "taken_at": local.strftime("%Y-%m-%dT%H:%M:%S") + "-05:00",
            "taken_utc": (local + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
            if utc else "",
            "date": day,
            "lat": "" if place is None else f"{place[0]:.6f}",
            "lng": "" if place is None else f"{place[1]:.6f}",
            "has_gps": "false" if place is None else "true",
        })
        return pid

    def nights(self, first_day, count, place=HOME, hour=23):
        start = datetime.fromisoformat(first_day)
        return [self.add((start + timedelta(days=i)).strftime("%Y-%m-%d"), hour, place)
                for i in range(count)]

    def visit(self, day, place):
        """Two photos one hour apart (one stay)."""
        return [self.add(day, 12, place), self.add(day, 13, place)]

    def frame(self):
        return pd.DataFrame(self.rows, columns=CLEAN_COLUMNS, dtype=str)


def with_home():
    """12 home nights in January 2026 (quarter 2026Q1)."""
    photos = Photos()
    photos.nights("2026-01-01", 12)
    return photos


def spans(trips_df):
    return list(zip(trips_df["start_date"], trips_df["end_date"]))


NORTH_KM = 111.19508  # km per degree of latitude on the sphere used by haversine_km


def north_of_home(km):
    """A point `km` kilometres due north of HOME (6-decimal precision, like the CSV)."""
    return (round(HOME[0] + km / NORTH_KM, 6), HOME[1])


def homes_for(photos, **params):
    prepared = segment.prepare_photos(photos.frame())
    return segment.detect_homes(prepared, segment.resolve_params(params))


class TestHaversine(unittest.TestCase):
    def test_known_distances(self):
        self.assertEqual(round(float(segment.haversine_km(*HOME, *NYC))), 306)
        self.assertEqual(round(float(segment.haversine_km(*HOME, *PVD))), 66)
        self.assertEqual(float(segment.haversine_km(*HOME, *HOME)), 0.0)

    def test_vectorised(self):
        out = segment.haversine_km([HOME[0], HOME[0]], [HOME[1], HOME[1]],
                                   [NYC[0], MTL[0]], [NYC[1], MTL[1]])
        self.assertEqual([round(float(v)) for v in out], [306, 403])


class TestStays(unittest.TestCase):
    def stays(self, photos, **params):
        prepared = segment.prepare_photos(photos.frame())
        return segment.find_stays(prepared[prepared["has_gps"]],
                                  segment.resolve_params(params))

    def test_split_by_distance(self):
        p = Photos()
        p.add("2026-01-05", 12, HOME)
        p.add("2026-01-05", 12, (HOME[0] + 0.005, HOME[1]), minute=10)   # ~0.56 km
        p.add("2026-01-05", 12, (HOME[0] + 0.03, HOME[1]), minute=20)    # ~3.3 km
        self.assertEqual([len(s["photo_ids"]) for s in self.stays(p)], [2, 1])

    def test_running_centroid_not_last_photo(self):
        p = Photos()
        p.add("2026-01-05", 12, HOME)
        p.add("2026-01-05", 12, (HOME[0] + 0.008, HOME[1]), minute=10)   # 0.89 km: joins
        # 0.89 km from the previous photo but 1.33 km from the stay centroid: new stay
        p.add("2026-01-05", 12, (HOME[0] + 0.016, HOME[1]), minute=20)
        self.assertEqual([len(s["photo_ids"]) for s in self.stays(p)], [2, 1])

    def test_split_by_gap(self):
        p = Photos()
        p.add("2026-01-05", 9, HOME)
        p.add("2026-01-05", 12, HOME)              # exactly 3 h: joins
        p.add("2026-01-05", 14, HOME, minute=59)   # 2 h 59 m: joins
        p.add("2026-01-05", 18, HOME)              # 3 h 01 m: new stay
        self.assertEqual([len(s["photo_ids"]) for s in self.stays(p)], [3, 1])

    def test_gap_parameter(self):
        p = Photos()
        p.add("2026-01-05", 9, HOME)
        p.add("2026-01-05", 11, HOME)
        self.assertEqual(len(self.stays(p, stay_gap_hours=1.0)), 2)

    def test_centroid_count_and_times(self):
        p = Photos()
        p.add("2026-01-05", 12, (42.0, -71.0))
        p.add("2026-01-05", 13, (42.004, -71.002))
        (stay,) = self.stays(p)
        self.assertAlmostEqual(stay["lat"], 42.002, places=9)
        self.assertAlmostEqual(stay["lng"], -71.001, places=9)
        self.assertEqual(len(stay["photo_ids"]), 2)
        self.assertEqual(stay["start"], "2026-01-05T12:00:00-05:00")
        self.assertEqual(stay["end"], "2026-01-05T13:00:00-05:00")

    def test_stay_ids_in_time_order_and_no_gps_skipped(self):
        p = Photos()
        late = p.add("2026-01-07", 12, NYC)
        p.add("2026-01-06", 12)  # no GPS: not part of any stay
        early = p.add("2026-01-05", 12, HOME)
        p.rows.reverse()
        stays = self.stays(p)
        self.assertEqual([s["stay_id"] for s in stays], ["stay_00001", "stay_00002"])
        self.assertEqual([s["photo_ids"] for s in stays], [[early], [late]])

    def test_missing_utc_falls_back_to_local_time(self):
        p = Photos()
        # local 18:00 without UTC is ordered as 18:00Z; local 12:00-05:00 is 17:00Z
        a = p.add("2026-01-05", 18, HOME, utc=False)
        b = p.add("2026-01-05", 12, HOME)
        stays = self.stays(p)
        self.assertEqual(stays[0]["photo_ids"], [b, a])


class TestHome(unittest.TestCase):
    def assertNear(self, point, expected):
        self.assertLess(float(segment.haversine_km(*point, *expected)), 0.01)

    def test_biggest_night_cluster_wins_daytime_ignored(self):
        p = with_home()                        # 12 night photos at HOME
        p.nights("2026-02-01", 5, CAMBRIDGE)   # smaller night cluster
        for i in range(20):                    # many daytime photos elsewhere
            p.add("2026-02-10", 9 + i % 10, CAMBRIDGE, minute=i)
        homes, info = homes_for(p)
        self.assertEqual(list(homes), [(2026, 1)])
        self.assertNear(homes[(2026, 1)], HOME)
        self.assertEqual(info, {"mode": "quarterly", "own": 1, "reused": 0})

    def test_early_morning_counts_as_night(self):
        p = Photos()
        p.nights("2026-01-01", 12, CAMBRIDGE, hour=3)
        p.nights("2026-01-01", 5, HOME, hour=23)
        homes, _ = homes_for(p)
        self.assertNear(homes[(2026, 1)], CAMBRIDGE)

    def test_size_tie_goes_to_earliest_cluster(self):
        p = Photos()
        p.nights("2026-01-01", 6, CHI)
        p.nights("2026-01-07", 6, HOME)
        homes, _ = homes_for(p)
        self.assertNear(homes[(2026, 1)], CHI)

    def test_small_quarter_reuses_previous_home(self):
        p = with_home()
        p.nights("2026-04-01", 5, CHI)   # Q2: clustered but < min_night_photos
        homes, info = homes_for(p)
        self.assertNear(homes[(2026, 2)], HOME)
        self.assertEqual(info, {"mode": "quarterly", "own": 1, "reused": 1})
        homes, info = homes_for(p, min_night_photos=5)
        self.assertNear(homes[(2026, 2)], CHI)
        self.assertEqual(info["own"], 2)

    def test_first_quarter_backfills_from_next(self):
        p = Photos()
        p.nights("2026-01-01", 3, CHI)       # Q1: too few night photos
        p.nights("2026-04-01", 12, HOME)     # Q2: own home
        homes, info = homes_for(p)
        self.assertNear(homes[(2026, 1)], HOME)
        self.assertNear(homes[(2026, 2)], HOME)
        self.assertEqual(info, {"mode": "quarterly", "own": 1, "reused": 1})

    def test_every_spanned_quarter_gets_a_home(self):
        p = with_home()
        p.add("2026-11-02", 12, NYC)
        homes, info = homes_for(p)
        self.assertEqual(list(homes), [(2026, 1), (2026, 2), (2026, 3), (2026, 4)])
        for quarter in homes:
            self.assertNear(homes[quarter], HOME)
        self.assertEqual(info, {"mode": "quarterly", "own": 1, "reused": 3})

    def test_fixed_mode_one_home(self):
        p = with_home()
        p.nights("2026-04-01", 15, CHI)
        homes, info = homes_for(p)
        self.assertNear(homes[(2026, 1)], HOME)
        self.assertNear(homes[(2026, 2)], CHI)
        homes, info = homes_for(p, home_mode="fixed")
        self.assertNear(homes[(2026, 1)], CHI)
        self.assertNear(homes[(2026, 2)], CHI)
        self.assertEqual(info["mode"], "fixed")

    def test_quarterly_falls_back_to_fixed_when_no_quarter_qualifies(self):
        p = Photos()
        p.nights("2026-01-01", 5)
        p.nights("2026-04-01", 5)
        homes, info = homes_for(p)
        self.assertEqual(info["mode"], "fixed")
        self.assertNear(homes[(2026, 1)], HOME)
        self.assertNear(homes[(2026, 2)], HOME)

    def test_no_cluster_raises(self):
        p = Photos()
        for i in range(12):  # night photos ~11 km apart: all noise
            p.add(f"2026-01-{i + 1:02d}", 23, (HOME[0] + 0.1 * i, HOME[1]))
        with self.assertRaisesRegex(ValueError, "^no home could be detected$"):
            segment.detect_trips(p.frame())

    def test_no_night_photos_raises(self):
        p = Photos()
        for i in range(12):
            p.add(f"2026-01-{i + 1:02d}", 12, HOME)
        with self.assertRaisesRegex(ValueError, "^no home could be detected$"):
            segment.detect_trips(p.frame())


class TestTrips(unittest.TestCase):
    def test_nyc_trip_exact(self):
        p = with_home()
        p.add("2026-01-19", 12, HOME)
        nyc = []
        for day in ["2026-01-20", "2026-01-21", "2026-01-22"]:
            nyc += p.visit(day, NYC)
        no_gps_in = p.add("2026-01-21", 15)
        no_gps_out = p.add("2026-01-25", 15)
        p.add("2026-01-23", 12, HOME)
        trips, stays, photo_trips = segment.detect_trips(p.frame())
        self.assertEqual(list(trips.columns), segment.TRIP_COLUMNS)
        self.assertEqual(trips.to_dict("records"), [{
            "person": "tester", "trip_id": "trip_20260120", "start_date": "2026-01-20",
            "end_date": "2026-01-22", "days": 3, "max_distance_km": 306, "photo_count": 7,
            "n_stays": 3, "cities": ""}])
        expected_ids = nyc[:4] + [no_gps_in] + nyc[4:]
        self.assertEqual(list(photo_trips["photo_id"]), expected_ids)
        self.assertEqual(set(photo_trips["trip_id"]), {"trip_20260120"})
        self.assertNotIn(no_gps_out, set(photo_trips["photo_id"]))

    def test_one_day_trip_outside_circle_is_kept_by_default(self):
        p = with_home()
        p.visit("2026-01-20", NYC)
        p.add("2026-01-21", 12, HOME)
        trips = segment.detect_trips(p.frame())[0]
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-20")])
        self.assertEqual(list(trips["days"]), [1])
        self.assertEqual(len(segment.detect_trips(p.frame(), {"min_days": 2})[0]), 0)

    def test_larger_radius_removes_day_trip_but_keeps_long_trip(self):
        p = with_home()
        p.visit("2026-01-20", PVD)          # ~66 km day trip
        p.add("2026-01-21", 12, HOME)
        for day in ["2026-02-10", "2026-02-11", "2026-02-12"]:
            p.visit(day, NYC)               # ~306 km
        p.add("2026-02-13", 12, HOME)
        trips = segment.detect_trips(p.frame(), {"radius_km": 50.0})[0]
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-20"),
                                        ("2026-02-10", "2026-02-12")])
        self.assertEqual(list(trips["max_distance_km"]), [66, 306])
        trips = segment.detect_trips(p.frame(), {"radius_km": 100.0})[0]
        self.assertEqual(spans(trips), [("2026-02-10", "2026-02-12")])
        self.assertEqual(list(trips["max_distance_km"]), [306])

    def test_one_empty_day_bridged(self):
        p = with_home()
        for day in ["2026-01-20", "2026-01-21", "2026-01-23"]:
            p.visit(day, NYC)
        trips = segment.detect_trips(p.frame())[0]
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-23")])
        self.assertEqual(list(trips["days"]), [4])

    def test_two_empty_days_bridged(self):
        p = with_home()
        for day in ["2026-01-20", "2026-01-23"]:
            p.visit(day, NYC)
        trips = segment.detect_trips(p.frame())[0]
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-23")])

    def test_three_empty_days_split(self):
        p = with_home()
        for day in ["2026-01-20", "2026-01-21", "2026-01-25"]:
            p.visit(day, NYC)
        trips = segment.detect_trips(p.frame())[0]
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-21"),
                                        ("2026-01-25", "2026-01-25")])
        trips = segment.detect_trips(p.frame(), {"min_days": 2})[0]
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-21")])  # 1-day part dropped

    def test_no_gps_days_between_travel_days_bridge_up_to_max_gap(self):
        p = with_home()
        p.visit("2026-01-20", NYC)
        no_gps = [p.add(day, 15) for day in ["2026-01-21", "2026-01-22"]]  # 2 no-GPS days
        p.visit("2026-01-23", NYC)
        trips, _, photo_trips = segment.detect_trips(p.frame())
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-23")])
        self.assertEqual(list(trips["photo_count"]), [6])
        self.assertTrue(set(no_gps) <= set(photo_trips["photo_id"]))

    def test_three_no_gps_days_split_and_max_gap_days_widens(self):
        p = with_home()
        p.visit("2026-01-20", NYC)
        for day in ["2026-01-21", "2026-01-22", "2026-01-23"]:
            p.add(day, 15)                  # 3 no-GPS days
        p.visit("2026-01-24", NYC)
        trips = segment.detect_trips(p.frame())[0]
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-20"),
                                        ("2026-01-24", "2026-01-24")])
        trips = segment.detect_trips(p.frame(), {"max_gap_days": 3})[0]
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-24")])

    def test_home_day_ends_trip(self):
        p = with_home()
        for day in ["2026-01-20", "2026-01-21", "2026-01-23", "2026-01-24"]:
            p.visit(day, NYC)
        p.add("2026-01-22", 12, HOME)
        trips = segment.detect_trips(p.frame())[0]
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-21"),
                                        ("2026-01-23", "2026-01-24")])
        self.assertEqual(list(trips["trip_id"]), ["trip_20260120", "trip_20260123"])

    def test_mixed_first_and_last_days_are_full_travel_days(self):
        p = with_home()
        p.add("2026-01-20", 8, HOME)       # morning at home, then the trip starts
        p.visit("2026-01-20", NYC)
        p.visit("2026-01-21", NYC)
        p.visit("2026-01-22", NYC)
        p.visit("2026-01-23", NYC)
        p.add("2026-01-23", 20, HOME)      # evening back home
        trips, _, photo_trips = segment.detect_trips(p.frame())
        self.assertEqual(trips.to_dict("records"), [{
            "person": "tester", "trip_id": "trip_20260120", "start_date": "2026-01-20",
            "end_date": "2026-01-23", "days": 4, "max_distance_km": 306, "photo_count": 10,
            "n_stays": 6, "cities": ""}])
        self.assertEqual(len(photo_trips), 10)  # includes the 2 home-area photos

    def test_home_only_day_in_the_middle_still_ends_trip(self):
        p = with_home()
        p.visit("2026-01-20", NYC)
        p.visit("2026-01-21", NYC)
        p.add("2026-01-22", 9, HOME)       # every photo of the date is within 25 km
        p.add("2026-01-22", 12, CAMBRIDGE)
        p.visit("2026-01-23", NYC)
        p.visit("2026-01-24", NYC)
        trips = segment.detect_trips(p.frame())[0]
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-21"),
                                        ("2026-01-23", "2026-01-24")])
        self.assertEqual(list(trips["photo_count"]), [4, 4])

    def test_home_only_day_splits_trip_and_min_days_drops_short_parts(self):
        p = with_home()
        p.visit("2026-01-20", NYC)
        p.visit("2026-01-21", NYC)
        p.add("2026-01-22", 9, HOME)
        p.add("2026-01-22", 12, CAMBRIDGE)
        p.visit("2026-01-23", NYC)
        trips = segment.detect_trips(p.frame())[0]
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-21"),
                                        ("2026-01-23", "2026-01-23")])
        trips = segment.detect_trips(p.frame(), {"min_days": 2})[0]
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-21")])

    def test_day_with_photos_inside_and_outside_circle_is_a_travel_day(self):
        p = with_home()
        p.visit("2026-01-20", NYC)
        p.add("2026-01-21", 9, HOME)       # inside the circle ...
        p.add("2026-01-21", 12, PVD)       # ... plus a photo outside (66 km > 50 km): away
        p.visit("2026-01-22", NYC)
        trips = segment.detect_trips(p.frame())[0]
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-22")])
        self.assertEqual(list(trips["days"]), [3])
        self.assertEqual(list(trips["photo_count"]), [6])

    def test_outside_circle_days_at_both_ends_belong_to_the_trip(self):
        p = with_home()
        p.visit("2026-01-19", PVD)
        p.visit("2026-01-20", NYC)
        p.visit("2026-01-21", PVD)
        p.visit("2026-01-22", NYC)
        p.visit("2026-01-23", PVD)
        trips = segment.detect_trips(p.frame())[0]
        self.assertEqual(spans(trips), [("2026-01-19", "2026-01-23")])
        self.assertEqual(list(trips["photo_count"]), [10])
        self.assertEqual(list(trips["max_distance_km"]), [306])

    def test_two_trips_sorted_and_photo_trips_grouped(self):
        p = with_home()
        mtl = p.visit("2026-02-10", MTL) + p.visit("2026-02-11", MTL)
        p.add("2026-02-01", 12, HOME)
        nyc = p.visit("2026-01-20", NYC) + p.visit("2026-01-21", NYC)
        trips, _, photo_trips = segment.detect_trips(p.frame())
        self.assertEqual(list(trips["trip_id"]), ["trip_20260120", "trip_20260210"])
        self.assertEqual(list(trips["max_distance_km"]), [306, 403])
        self.assertEqual(list(photo_trips["photo_id"]), nyc + mtl)

    def test_stays_include_non_trip_stays(self):
        p = with_home()
        p.visit("2026-01-20", NYC)
        p.visit("2026-01-21", NYC)
        _, stays, _ = segment.detect_trips(p.frame())
        self.assertEqual(list(stays.columns), segment.STAY_COLUMNS)
        self.assertEqual(len(stays), 14)
        self.assertEqual(list(stays["trip_id"]), [""] * 12 + ["trip_20260120"] * 2)
        self.assertEqual(list(stays["stay_id"]), [f"stay_{i:05d}" for i in range(1, 15)])
        self.assertEqual(list(stays["photo_count"]), [1] * 12 + [2, 2])

    def test_no_trips_gives_empty_frames_with_columns(self):
        trips, stays, photo_trips = segment.detect_trips(with_home().frame())
        self.assertEqual(list(trips.columns), segment.TRIP_COLUMNS)
        self.assertEqual(len(trips), 0)
        self.assertEqual(list(photo_trips.columns), ["photo_id", "trip_id"])
        self.assertEqual(len(photo_trips), 0)
        self.assertEqual(len(stays), 12)


class TestDayClasses(unittest.TestCase):
    def classes(self, photos, **params):
        params = segment.resolve_params(params)
        prepared = segment.prepare_photos(photos.frame())
        homes, _ = segment.detect_homes(prepared, params)
        classes, _ = segment.classify_days(prepared, homes, params)
        return dict(classes)

    def test_each_day_class(self):
        p = with_home()
        p.add("2026-01-20", 8, HOME)       # one photo outside the circle makes the date away
        p.add("2026-01-20", 12, NYC)
        p.add("2026-01-21", 9, HOME)       # all photos inside the 50 km circle: home
        p.add("2026-01-21", 10, CAMBRIDGE)
        p.add("2026-01-22", 12, PVD)       # 66 km > 50 km: away
        p.add("2026-01-23", 9, HOME)       # inside plus outside: away
        p.add("2026-01-23", 12, PVD)
        p.add("2026-01-24", 12)            # no GPS photo: neutral
        classes = self.classes(p)
        self.assertEqual(
            [classes[date.fromisoformat(f"2026-01-{d}")] for d in range(20, 25)],
            [segment.DAY_AWAY, segment.DAY_HOME, segment.DAY_AWAY, segment.DAY_AWAY,
             segment.DAY_NEUTRAL])
        self.assertEqual(classes[date(2026, 1, 1)], segment.DAY_HOME)
        classes = self.classes(p, radius_km=100.0)  # PVD (66 km) is now inside
        self.assertEqual(classes[date(2026, 1, 22)], segment.DAY_HOME)
        self.assertEqual(classes[date(2026, 1, 23)], segment.DAY_HOME)
        self.assertEqual(classes[date(2026, 1, 20)], segment.DAY_AWAY)

    def test_just_inside_and_just_outside_the_circle(self):
        for km, expected in ((49.9, segment.DAY_HOME), (50.1, segment.DAY_AWAY)):
            p = with_home()
            p.add("2026-01-20", 12, north_of_home(km))
            self.assertEqual(self.classes(p)[date(2026, 1, 20)], expected, km)

    def test_exactly_on_the_circle_is_inside(self):
        p = with_home()
        point = north_of_home(50.0)
        p.add("2026-01-20", 12, point)
        prepared = segment.prepare_photos(p.frame())
        homes, _ = segment.detect_homes(prepared, segment.resolve_params({}))
        exact = float(segment.haversine_km(*homes[(2026, 1)], *point))
        self.assertAlmostEqual(exact, 50.0, delta=0.01)
        day = date(2026, 1, 20)
        self.assertEqual(self.classes(p, radius_km=exact)[day], segment.DAY_HOME)
        self.assertEqual(self.classes(p, radius_km=float(np.nextafter(exact, 0.0)))[day],
                         segment.DAY_AWAY)
        self.assertEqual(self.classes(p, radius_km=float(np.nextafter(exact, 1e9)))[day],
                         segment.DAY_HOME)


class TestParams(unittest.TestCase):
    def test_unknown_key_raises(self):
        with self.assertRaises(ValueError):
            segment.detect_trips(with_home().frame(), {"radius_kms": 50})

    def test_old_parameter_names_raise(self):
        for old in ("trip_min_km", "home_radius_km"):
            with self.assertRaisesRegex(ValueError, old):
                segment.detect_trips(with_home().frame(), {old: 50.0})
            self.assertNotIn(old, segment.DEFAULT_PARAMS)

    def test_invalid_home_mode_raises(self):
        with self.assertRaises(ValueError):
            segment.detect_trips(with_home().frame(), {"home_mode": "monthly"})

    def test_defaults_and_input_unchanged(self):
        before = copy.deepcopy(segment.DEFAULT_PARAMS)
        p = with_home()
        p.visit("2026-01-20", NYC)
        p.add("2026-01-21", 15)
        df = p.frame()
        snapshot = df.copy(deep=True)
        segment.detect_trips(df, {"min_days": 2, "radius_km": 25.0, "home_mode": "fixed"})
        self.assertEqual(segment.DEFAULT_PARAMS, before)
        pd.testing.assert_frame_equal(df, snapshot)

    def test_radius_constants_and_defaults(self):
        self.assertEqual(segment.RADIUS_OPTIONS_KM, [10, 25, 50, 100, 200])
        self.assertEqual(segment.DEFAULT_RADIUS_KM, 50)
        self.assertEqual(segment.DEFAULT_PARAMS["radius_km"], 50.0)
        self.assertEqual(segment.DEFAULT_PARAMS["min_days"], 1)

    def test_partial_params_merge(self):
        merged = segment.resolve_params({"radius_km": 25})
        self.assertEqual(merged["radius_km"], 25)
        self.assertEqual(merged["min_days"], 1)
        self.assertEqual(merged["max_gap_days"], 2)


class TestHomesTable(unittest.TestCase):
    def homes_table(self, photos, **params):
        return segment.run_segmentation(photos.frame(), params)["homes"]

    def assertHome(self, row, expected):
        self.assertLess(float(segment.haversine_km(row["lat"], row["lng"], *expected)), 0.01)

    def test_same_home_in_every_quarter_is_one_period(self):
        p = with_home()
        p.add("2026-11-02", 12, NYC)
        table = self.homes_table(p)
        self.assertEqual(list(table.columns), segment.HOME_COLUMNS)
        self.assertEqual(len(table), 1)
        row = table.iloc[0]
        # first data date (not the quarter start 2026-01-01 clipped) .. last data date
        self.assertEqual((row["from_date"], row["to_date"]), ("2026-01-01", "2026-11-02"))
        self.assertHome(row, HOME)

    def test_home_change_splits_periods_at_quarter_edges(self):
        p = with_home()
        p.nights("2026-04-01", 15, CHI)
        p.nights("2026-07-01", 12, HOME)
        table = self.homes_table(p)
        self.assertEqual(list(zip(table["from_date"], table["to_date"])), [
            ("2026-01-01", "2026-03-31"), ("2026-04-01", "2026-06-30"),
            ("2026-07-01", "2026-07-12")])
        for (_, row), expected in zip(table.iterrows(), [HOME, CHI, HOME]):
            self.assertHome(row, expected)

    def test_consecutive_quarters_with_same_home_merge(self):
        p = Photos()
        p.nights("2025-11-20", 12, CHI)       # 2025Q4: CHI
        p.nights("2026-01-05", 12, HOME)      # 2026Q1: HOME
        p.nights("2026-04-05", 12, HOME)      # 2026Q2: same HOME (identical coordinates)
        table = self.homes_table(p)
        self.assertEqual(list(zip(table["from_date"], table["to_date"])), [
            ("2025-11-20", "2025-12-31"), ("2026-01-01", "2026-04-16")])
        self.assertHome(table.iloc[1], HOME)

    def test_homes_a_few_metres_apart_merge_into_one_period(self):
        p = Photos()
        p.nights("2026-01-01", 12, HOME)
        shifted = (HOME[0] + 0.0003, HOME[1])      # ~33 m north
        self.assertLess(float(segment.haversine_km(*HOME, *shifted)), 0.04)
        p.nights("2026-04-01", 12, shifted)
        result = segment.run_segmentation(p.frame())
        self.assertEqual(result["home_info"], {"mode": "quarterly", "own": 2, "reused": 0})
        table = result["homes"]
        self.assertEqual(len(table), 1)
        self.assertEqual((table.iloc[0]["from_date"], table.iloc[0]["to_date"]),
                         ("2026-01-01", "2026-04-12"))
        # period position = mean of the two quarter homes (~16.5 m from each)
        self.assertLess(float(segment.haversine_km(table.iloc[0]["lat"], table.iloc[0]["lng"],
                                                   HOME[0] + 0.00015, HOME[1])), 0.001)

    def test_homes_further_apart_than_home_eps_km_stay_separate(self):
        p = Photos()
        p.nights("2026-01-01", 12, HOME)
        p.nights("2026-04-01", 12, (HOME[0] + 0.02, HOME[1]))      # ~2.2 km > 1 km
        table = self.homes_table(p)
        self.assertEqual(list(zip(table["from_date"], table["to_date"])),
                         [("2026-01-01", "2026-03-31"), ("2026-04-01", "2026-04-12")])
        table = self.homes_table(p, home_eps_km=3.0)               # eps wide enough to merge
        self.assertEqual(len(table), 1)

    def test_move_away_and_back_gives_three_periods(self):
        p = Photos()
        p.nights("2026-01-01", 12, HOME)
        p.nights("2026-04-01", 12, CHI)
        p.nights("2026-07-01", 12, (HOME[0] + 0.0003, HOME[1]))    # back, ~33 m from HOME
        table = self.homes_table(p)
        self.assertEqual(list(zip(table["from_date"], table["to_date"])), [
            ("2026-01-01", "2026-03-31"), ("2026-04-01", "2026-06-30"),
            ("2026-07-01", "2026-07-12")])
        self.assertHome(table.iloc[0], HOME)
        self.assertHome(table.iloc[1], CHI)
        self.assertHome(table.iloc[2], (HOME[0] + 0.0003, HOME[1]))

    def test_fixed_mode_gives_one_period(self):
        p = with_home()
        p.nights("2026-04-01", 15, CHI)
        table = self.homes_table(p, home_mode="fixed")
        self.assertEqual(len(table), 1)
        self.assertEqual((table.iloc[0]["from_date"], table.iloc[0]["to_date"]),
                         ("2026-01-01", "2026-04-15"))
        self.assertHome(table.iloc[0], CHI)

    def test_detect_trips_signature_unchanged(self):
        self.assertEqual(len(segment.detect_trips(with_home().frame())), 3)


def predicted(*spans_):
    return pd.DataFrame([{"trip_id": "trip_" + s.replace("-", ""), "start_date": s,
                          "end_date": e} for s, e in spans_],
                        columns=["trip_id", "start_date", "end_date"])


def ground_truth(*rows):
    return pd.DataFrame([{"person": person, "start_date": s, "end_date": e,
                          "cities": SENTINEL_CITY} for person, s, e in rows], dtype=str)


class TestMatchGroundTruth(unittest.TestCase):
    def test_partial_overlap_jaccard(self):
        out = segment.match_ground_truth(predicted(("2026-01-22", "2026-01-25")),
                                         ground_truth(("me", "2026-01-20", "2026-01-23")), "me")
        self.assertEqual(list(out.columns), segment.MATCH_COLUMNS)
        row = out.iloc[0]
        self.assertEqual(row["pred_trip_id"], "trip_20260122")
        self.assertEqual(int(row["overlap_pct"]), 33)  # 2 shared / 6 in union
        self.assertFalse(bool(row["matched"]))

    def test_best_of_two(self):
        preds = predicted(("2026-01-18", "2026-01-20"), ("2026-01-22", "2026-01-25"))
        out = segment.match_ground_truth(preds, ground_truth(("me", "2026-01-20", "2026-01-25")),
                                         "me")
        row = out.iloc[0]
        self.assertEqual(row["pred_trip_id"], "trip_20260122")  # 4/6 beats 1/8
        self.assertEqual((row["pred_start"], row["pred_end"]), ("2026-01-22", "2026-01-25"))
        self.assertEqual(int(row["overlap_pct"]), 67)
        self.assertTrue(bool(row["matched"]))

    def test_tie_goes_to_earliest_prediction(self):
        preds = predicted(("2026-01-23", "2026-01-24"), ("2026-01-19", "2026-01-20"))
        out = segment.match_ground_truth(preds, ground_truth(("me", "2026-01-20", "2026-01-23")),
                                         "me")
        self.assertEqual(out.iloc[0]["pred_trip_id"], "trip_20260119")
        self.assertEqual(int(out.iloc[0]["overlap_pct"]), 20)

    def test_no_overlap_row(self):
        out = segment.match_ground_truth(predicted(("2026-01-22", "2026-01-25")),
                                         ground_truth(("me", "2026-03-01", "2026-03-02")), "me")
        self.assertEqual(out.iloc[0].to_dict(), {
            "gt_start": "2026-03-01", "gt_end": "2026-03-02", "pred_trip_id": "",
            "pred_start": "", "pred_end": "", "overlap_pct": 0, "matched": False})

    def test_fifty_percent_is_matched(self):
        out = segment.match_ground_truth(predicted(("2026-01-21", "2026-01-21")),
                                         ground_truth(("me", "2026-01-20", "2026-01-21")), "me")
        self.assertEqual(int(out.iloc[0]["overlap_pct"]), 50)
        self.assertTrue(bool(out.iloc[0]["matched"]))

    def test_filters_person_and_sorts(self):
        gt = ground_truth(("me", "2026-05-01", "2026-05-02"), ("you", "2026-01-01", "2026-01-02"),
                          ("me", "2026-02-01", "2026-02-02"))
        out = segment.match_ground_truth(predicted(), gt, "me")
        self.assertEqual(list(out["gt_start"]), ["2026-02-01", "2026-05-01"])
        self.assertNotIn("cities", out.columns)


class TestMain(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "data" / "processed").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def write_photos(self, photos):
        photos.frame().to_csv(self.root / "data" / "processed" / "photos_clean.csv", index=False)

    def write_ground_truth(self):
        gt = ground_truth(("tester", "2026-01-20", "2026-01-23"),
                          ("other", "2026-01-20", "2026-01-23"),
                          ("tester", "2026-03-01", "2026-03-03"))
        gt.to_csv(self.root / "data" / "ground_truth.csv", index=False)

    def scenario(self):
        p = with_home()
        p.add("2026-01-19", 12, HOME)
        for day in ["2026-01-20", "2026-01-21", "2026-01-22"]:
            p.visit(day, NYC)
        p.add("2026-01-21", 15)          # no GPS, inside the trip
        p.add("2026-01-25", 15)          # no GPS, outside
        p.add("2026-01-23", 12, HOME)
        p.visit("2026-02-10", MTL)       # 1-day trip: dropped by default
        p.add("2026-02-12", 12, HOME)
        return p

    def run_main(self, argv=None):
        buffer = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(buffer):
            try:
                segment.main(argv or [], root=self.root)
            except SystemExit as exc:
                code = exc.code
        return code, buffer.getvalue()

    def test_end_to_end(self):
        self.write_photos(self.scenario())
        self.write_ground_truth()
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), [
            "GPS photos: 23",
            "Stays: 19",
            "Quarters: 1 with own home, 0 reused",
            "Trips: 2 (4 days, 9 photos assigned)",
            "  trip_20260120  2026-01-20 -> 2026-01-22  3 days  306 km",
            "  trip_20260210  2026-02-10 -> 2026-02-10  1 days  403 km",
            "Ground truth (2 trips):",
            "  2026-01-20 -> 2026-01-23  best: trip_20260120 (75%)  matched",
            "  2026-03-01 -> 2026-03-03  best: none (0%)  not matched",
            "Matched: 1 of 2",
        ])
        self.assertNoSecrets(out)

        processed = self.root / "data" / "processed"
        self.assertEqual(sorted(f.name for f in processed.iterdir()), [
            "homes.csv", "photo_trips.csv", "photos_clean.csv", "stays.csv", "trips_pred.csv"])
        trips = pd.read_csv(processed / "trips_pred.csv", dtype=str, keep_default_na=False)
        stays = pd.read_csv(processed / "stays.csv", dtype=str, keep_default_na=False)
        photo_trips = pd.read_csv(processed / "photo_trips.csv", dtype=str,
                                  keep_default_na=False)
        homes = pd.read_csv(processed / "homes.csv", dtype=str, keep_default_na=False)
        self.assertEqual(list(trips.columns), segment.TRIP_COLUMNS)
        self.assertEqual(list(stays.columns), segment.STAY_COLUMNS)
        self.assertEqual(list(photo_trips.columns), ["photo_id", "trip_id"])
        self.assertEqual(list(homes.columns), ["from_date", "to_date", "lat", "lng"])
        self.assertEqual(trips.iloc[0].to_dict(), {
            "person": "tester", "trip_id": "trip_20260120", "start_date": "2026-01-20",
            "end_date": "2026-01-22", "days": "3", "max_distance_km": "306",
            "photo_count": "7", "n_stays": "3", "cities": ""})
        self.assertEqual(len(trips), 2)
        self.assertEqual(len(stays), 19)
        self.assertEqual(len(photo_trips), 9)
        self.assertEqual(len(homes), 1)
        self.assertEqual((homes.iloc[0]["from_date"], homes.iloc[0]["to_date"]),
                         ("2026-01-01", "2026-02-12"))
        self.assertLess(float(segment.haversine_km(float(homes.iloc[0]["lat"]),
                                                   float(homes.iloc[0]["lng"]), *HOME)), 0.01)

    def assertNoSecrets(self, out):
        for secret in ["42.3601", "-71.0589", "40.7128", "45.5017", "41.8240", SENTINEL_NAME,
                       SENTINEL_CITY]:
            self.assertNotIn(secret, out)

    def test_missing_ground_truth(self):
        self.write_photos(self.scenario())
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[-1], "Ground truth: not found")

    def test_cli_override(self):
        self.write_photos(self.scenario())
        code, out = self.run_main(["--min_days", "2"])
        self.assertEqual(code, 0)
        self.assertIn("Trips: 1 (3 days, 7 photos assigned)", out.splitlines())
        self.assertNotIn("  trip_20260210  2026-02-10 -> 2026-02-10  1 days  403 km",
                         out.splitlines())

    def test_cli_radius_changes_result(self):
        self.write_photos(self.scenario())
        code, out = self.run_main(["--radius_km", "350"])
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[3], "Trips: 1 (1 days, 2 photos assigned)")
        self.assertIn("  trip_20260210  2026-02-10 -> 2026-02-10  1 days  403 km",
                      out.splitlines())

    def test_cli_fixed_mode(self):
        self.write_photos(self.scenario())
        code, out = self.run_main(["--home_mode", "fixed", "--radius_km", "500"])
        self.assertEqual(code, 0)
        self.assertIn("Quarters: fixed home", out.splitlines())
        self.assertIn("Trips: 0 (0 days, 0 photos assigned)", out.splitlines())

    def test_old_cli_flags_are_gone(self):
        self.write_photos(self.scenario())
        for flag in ("--trip_min_km", "--home_radius_km"):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                segment.main([flag, "50"], root=self.root)

    def all_radii_photos(self):
        p = self.scenario()
        # Day trips at ~66 / 15 / 40 / 150 / 250 km, each followed by a home day, so the trip
        # count differs at every step of RADIUS_OPTIONS_KM (NYC 306 km and MTL 403 km always
        # count): r=10 -> 7, 25 -> 6, 50 -> 5, 100 -> 4, 200 -> 3.
        for day, place in (("2026-03-10", PVD), ("2026-03-14", north_of_home(15)),
                           ("2026-03-18", north_of_home(40)), ("2026-03-22", north_of_home(150)),
                           ("2026-03-26", north_of_home(250))):
            p.visit(day, place)
            p.add(f"2026-03-{int(day[-2:]) + 1:02d}", 12, HOME)
        return p

    def test_all_radii_writes_fifteen_files_and_five_lines(self):
        self.write_photos(self.all_radii_photos())
        self.write_ground_truth()
        code, out = self.run_main(["--all-radii"])
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), [
            "r=10 km: 7 trips, matched 1 of 2",
            "r=25 km: 6 trips, matched 1 of 2",
            "r=50 km: 5 trips, matched 1 of 2",
            "r=100 km: 4 trips, matched 1 of 2",
            "r=200 km: 3 trips, matched 1 of 2",
        ])
        self.assertNoSecrets(out)
        processed = self.root / "data" / "processed"
        expected = {"photos_clean.csv", "homes.csv"}
        for radius in segment.RADIUS_OPTIONS_KM:
            expected |= {f"trips_pred_r{radius}.csv", f"stays_r{radius}.csv",
                         f"photo_trips_r{radius}.csv"}
        self.assertEqual({f.name for f in processed.iterdir()}, expected)
        self.assertEqual(len(expected), 17)
        for radius, count in zip(segment.RADIUS_OPTIONS_KM, [7, 6, 5, 4, 3]):
            trips = pd.read_csv(processed / f"trips_pred_r{radius}.csv", dtype=str,
                                keep_default_na=False)
            self.assertEqual(list(trips.columns), segment.TRIP_COLUMNS)
            self.assertEqual(len(trips), count)

    def test_all_radii_ignores_radius_km_and_default_files_equal_r50(self):
        self.write_photos(self.all_radii_photos())
        code, out_all = self.run_main(["--all-radii", "--radius_km", "10"])
        self.assertEqual(code, 0)
        self.assertEqual(len(out_all.splitlines()), 5)
        processed = self.root / "data" / "processed"
        self.assertFalse((processed / "trips_pred.csv").exists())
        code, out = self.run_main([])
        self.assertEqual(code, 0)
        self.assertEqual((processed / "trips_pred.csv").read_text(),
                         (processed / "trips_pred_r50.csv").read_text())
        self.assertEqual((processed / "stays.csv").read_text(),
                         (processed / "stays_r50.csv").read_text())
        self.assertEqual((processed / "photo_trips.csv").read_text(),
                         (processed / "photo_trips_r50.csv").read_text())

    def test_all_radii_without_ground_truth(self):
        self.write_photos(self.all_radii_photos())
        code, out = self.run_main(["--all-radii"])
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), [
            "r=10 km: 7 trips, ground truth: not found",
            "r=25 km: 6 trips, ground truth: not found",
            "r=50 km: 5 trips, ground truth: not found",
            "r=100 km: 4 trips, ground truth: not found",
            "r=200 km: 3 trips, ground truth: not found",
        ])

    def test_all_radii_errors_stay_generic(self):
        code, out = self.run_main(["--all-radii"])
        self.assertEqual((code, out), (1, "error: could not read data/processed/photos_clean.csv\n"))
        p = Photos()
        p.add("2026-01-01", 12, HOME)
        self.write_photos(p)
        code, out = self.run_main(["--all-radii"])
        self.assertEqual((code, out), (1, "error: no home could be detected\n"))

    def test_parser_types(self):
        args = segment.build_parser().parse_args(["--stay_radius_km", "1.5", "--min_days", "3"])
        self.assertEqual(args.stay_radius_km, 1.5)
        self.assertIsInstance(args.min_days, int)
        self.assertEqual(args.home_mode, "quarterly")

    def test_missing_input(self):
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(out, "error: could not read data/processed/photos_clean.csv\n")

    def test_no_home(self):
        p = Photos()
        p.add("2026-01-01", 12, HOME)
        self.write_photos(p)
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(out, "error: no home could be detected\n")

    def test_bad_ground_truth_fails_generically(self):
        self.write_photos(self.scenario())
        (self.root / "data" / "ground_truth.csv").write_text(
            "person,start_date,end_date,cities\ntester,2026-01-23,2026-01-20,X\n")
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(out, "error: could not read data/ground_truth.csv\n")

    def test_bad_rows_fail_generically(self):
        p = self.scenario()
        p.rows[0]["taken_at"] = "garbage"
        self.write_photos(p)
        code, out = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(out, "error: segmentation failed\n")


if __name__ == "__main__":
    unittest.main()
