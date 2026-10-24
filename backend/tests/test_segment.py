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
from datetime import datetime, timedelta
from pathlib import Path

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
PVD = (41.8240, -71.4128)       # ~66 km (between home_radius_km and trip_min_km)
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

    def test_one_day_trip_dropped_unless_min_days_1(self):
        p = with_home()
        p.visit("2026-01-20", NYC)
        p.add("2026-01-21", 12, HOME)
        self.assertEqual(len(segment.detect_trips(p.frame())[0]), 0)
        trips = segment.detect_trips(p.frame(), {"min_days": 1})[0]
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-20")])

    def test_mid_distance_days_are_not_a_trip_unless_threshold_lowered(self):
        p = with_home()
        for day in ["2026-01-20", "2026-01-21", "2026-01-22"]:
            p.visit(day, PVD)
        self.assertEqual(len(segment.detect_trips(p.frame())[0]), 0)
        trips = segment.detect_trips(p.frame(), {"trip_min_km": 50.0})[0]
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-22")])
        self.assertEqual(list(trips["max_distance_km"]), [66])

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
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-21")])  # 1-day part dropped
        trips = segment.detect_trips(p.frame(), {"min_days": 1})[0]
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-21"),
                                        ("2026-01-25", "2026-01-25")])

    def test_home_day_ends_trip(self):
        p = with_home()
        for day in ["2026-01-20", "2026-01-21", "2026-01-23", "2026-01-24"]:
            p.visit(day, NYC)
        p.add("2026-01-22", 12, HOME)
        trips = segment.detect_trips(p.frame())[0]
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-21"),
                                        ("2026-01-23", "2026-01-24")])
        self.assertEqual(list(trips["trip_id"]), ["trip_20260120", "trip_20260123"])

    def test_mid_distance_day_bridged_but_never_an_endpoint(self):
        p = with_home()
        p.visit("2026-01-19", PVD)
        p.visit("2026-01-20", NYC)
        p.visit("2026-01-21", PVD)
        p.visit("2026-01-22", NYC)
        p.visit("2026-01-23", PVD)
        trips = segment.detect_trips(p.frame())[0]
        self.assertEqual(spans(trips), [("2026-01-20", "2026-01-22")])
        self.assertEqual(list(trips["photo_count"]), [6])
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


class TestParams(unittest.TestCase):
    def test_unknown_key_raises(self):
        with self.assertRaises(ValueError):
            segment.detect_trips(with_home().frame(), {"trip_min_kms": 50})

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
        segment.detect_trips(df, {"min_days": 1, "trip_min_km": 50.0, "home_mode": "fixed"})
        self.assertEqual(segment.DEFAULT_PARAMS, before)
        pd.testing.assert_frame_equal(df, snapshot)

    def test_partial_params_merge(self):
        merged = segment.resolve_params({"min_days": 1})
        self.assertEqual(merged["min_days"], 1)
        self.assertEqual(merged["trip_min_km"], 100.0)


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
            "Trips: 1 (3 days, 7 photos assigned)",
            "  trip_20260120  2026-01-20 -> 2026-01-22  3 days  306 km",
            "Ground truth (2 trips):",
            "  2026-01-20 -> 2026-01-23  best: trip_20260120 (75%)  matched",
            "  2026-03-01 -> 2026-03-03  best: none (0%)  not matched",
            "Matched: 1 of 2",
        ])
        for secret in ["42.3601", "-71.0589", "40.7128", SENTINEL_NAME, SENTINEL_CITY]:
            self.assertNotIn(secret, out)

        processed = self.root / "data" / "processed"
        trips = pd.read_csv(processed / "trips_pred.csv", dtype=str, keep_default_na=False)
        stays = pd.read_csv(processed / "stays.csv", dtype=str, keep_default_na=False)
        photo_trips = pd.read_csv(processed / "photo_trips.csv", dtype=str,
                                  keep_default_na=False)
        self.assertEqual(list(trips.columns), segment.TRIP_COLUMNS)
        self.assertEqual(list(stays.columns), segment.STAY_COLUMNS)
        self.assertEqual(list(photo_trips.columns), ["photo_id", "trip_id"])
        self.assertEqual(trips.iloc[0].to_dict(), {
            "person": "tester", "trip_id": "trip_20260120", "start_date": "2026-01-20",
            "end_date": "2026-01-22", "days": "3", "max_distance_km": "306",
            "photo_count": "7", "n_stays": "3", "cities": ""})
        self.assertEqual(len(stays), 19)
        self.assertEqual(len(photo_trips), 7)

    def test_missing_ground_truth(self):
        self.write_photos(self.scenario())
        code, out = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines()[-1], "Ground truth: not found")

    def test_cli_override(self):
        self.write_photos(self.scenario())
        code, out = self.run_main(["--min_days", "1"])
        self.assertEqual(code, 0)
        self.assertIn("Trips: 2 (4 days, 9 photos assigned)", out)
        self.assertIn("  trip_20260210  2026-02-10 -> 2026-02-10  1 days  403 km", out)

    def test_cli_fixed_mode(self):
        self.write_photos(self.scenario())
        code, out = self.run_main(["--home_mode", "fixed", "--trip_min_km", "500"])
        self.assertEqual(code, 0)
        self.assertIn("Quarters: fixed home", out.splitlines())
        self.assertIn("Trips: 0 (0 days, 0 photos assigned)", out.splitlines())

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
