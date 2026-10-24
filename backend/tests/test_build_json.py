"""Unit tests for backend/build_json.py (synthetic data only). Run from the repo root:

    .venv/bin/python -W error -m unittest discover -s backend/tests -v

Every place, photo and home below is invented. REAL_HOME_TEXT stands for the real home point
in homes.csv; it must never appear in anything build_json writes or prints.
"""

import contextlib
import io
import json
import math
import re
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_json  # noqa: E402
import segment  # noqa: E402

KM_PER_DEG = 6371.0088 * math.pi / 180.0
REAL_HOME_TEXT = "12.3456789"       # sentinel: latitude text of home period 1 (and 2)
REAL_HOME_1 = (12.3456789, 34.5678901)
REAL_HOME_3 = (-20.1234567, 50.7654321)
REAL_HOME_4 = (45.5, -60.5)
CENTRE_A = (12.5, 34.5)             # city centre for periods 1 and 2 (one city, merged)
CENTRE_B = (45.6, -60.4)            # city centre for period 4
TRIP_IDS = {"A": "trip_20251110", "B": "trip_20260505", "C": "trip_20260720",
            "D": "trip_20260810", "E": "trip_20260901"}

CITIES = {  # id -> (name, country, code, lat, lng)
    "city_alpha_xl": ("Alpha", "Landia", "XL", 10.0, 20.0),
    "city_beta_xl": ("Beta", "Landia", "XL", 11.0, 20.0),
    "city_delta_xm": ("Delta", "Mland", "XM", -5.0, 100.0),
    "city_epsilon_xl": ("Epsilon", "Landia", "XL", 30.0, -40.0),
    "city_epsb_xl": ("Epsb", "Landia", "XL", 31.0, -40.0),
    "city_zeta_xm": ("Zeta", "Mland", "XM", 50.0, 10.0),
    "city_eta_xm": ("Eta", "Mland", "XM", 51.0, 10.0),
}
TRIP_ROWS = {  # key -> (start, end, days, title)
    "A": ("2025-11-10", "2025-11-12", 3, "Alpha"),
    "B": ("2026-05-05", "2026-05-05", 1, "Near Delta"),
    "C": ("2026-07-20", "2026-07-21", 2, "Epsilon"),
    "D": ("2026-08-10", "2026-08-12", 3, "Multi Stop"),
    "E": ("2026-09-01", "2026-09-01", 1, "Zeta"),
}
TRIP_CITY_ROWS = {  # key -> [(city_id, photo_count)]
    "A": [("city_alpha_xl", 3), ("city_beta_xl", 1)],
    "B": [("city_delta_xm", 2)],
    "C": [("city_epsilon_xl", 1), ("city_epsb_xl", 1)],
    "D": [("city_zeta_xm", 1), ("city_eta_xm", 5)],
    "E": [("city_zeta_xm", 3)],
}
RADIUS_TRIPS = {10: "ABCDE", 25: "ABCD", 50: "BACDE", 100: "AB", 200: "A"}  # r50 is deliberately unsorted

# photo key -> (id, trip, taken_at, taken_utc, lat, lng, city per photo_cities)
def north(point, km):
    return (point[0] + km / KM_PER_DEG, point[1])

PHOTOS = [
    ("a1", "p_a000000001", "A", "2025-11-10T10:00:00+01:00", "2025-11-10T09:00:00Z", (10.001, 20.001), "city_alpha_xl"),
    ("a2", "p_a000000002", "A", "2025-11-10T11:00:00+01:00", "2025-11-10T10:00:00Z", None, ""),
    ("a3", "p_a000000003", "A", "2025-11-10T12:00:00+01:00", "2025-11-10T11:00:00Z", (10.002, 20.002), "city_gamma_xl"),
    ("a4", "p_a000000004", "A", "2025-11-10T13:00:00+01:00", "2025-11-10T12:00:00Z", north(REAL_HOME_1, 3.0), "city_alpha_xl"),
    ("a5", "p_a000000005", "A", "2025-11-10T14:00:00+01:00", "2025-11-10T13:00:00Z", north(CENTRE_A, 40.0), "city_alpha_xl"),
    ("a7", "p_a000000007", "A", "2025-11-10T14:30:00+01:00", "2025-11-10T13:30:00Z", north(REAL_HOME_1, -8.0), "city_alpha_xl"),
    ("a8", "p_a000000008", "A", "2025-11-10T14:45:00+01:00", "2025-11-10T13:45:00Z", north(CENTRE_A, 5.0), "city_alpha_xl"),
    ("a6", "p_a000000006", "A", "2025-11-11T08:00:00", "", (11.0005, 20.0005), "city_beta_xl"),
    ("b1", "p_b000000001", "B", "2026-05-05T10:00:00-04:00", "2026-05-05T14:00:00Z", (-5.001, 100.001), "city_delta_xm"),
    ("b2", "p_b000000002", "B", "2026-05-05T11:00:00-04:00", "2026-05-05T15:00:00Z", None, ""),
    ("b3", "p_b000000003", "B", "2026-05-05T12:00:00-04:00", "2026-05-05T16:00:00Z", (-5.002, 100.002), "city_delta_xm"),
    ("b4", "p_b000000004", "B", "2026-05-05T13:00:00-04:00", "2026-05-05T17:00:00Z", north(REAL_HOME_4, 3.0), "city_delta_xm"),
    ("b5", "p_b000000005", "B", "2026-05-05T14:00:00-04:00", "2026-05-05T18:00:00Z", north(REAL_HOME_3, 3.0), "city_delta_xm"),
    ("c1", "p_c000000001", "C", "2026-07-20T10:00:00+00:00", "2026-07-20T10:00:00Z", north(REAL_HOME_3, 3.0), "city_epsilon_xl"),
    ("c2", "p_c000000002", "C", "2026-07-20T11:00:00+00:00", "2026-07-20T11:00:00Z", None, ""),
    ("d1", "p_d000000001", "D", "2026-08-10T10:00:00+02:00", "2026-08-10T08:00:00Z", (50.001, 10.001), "city_zeta_xm"),
    ("d2", "p_d000000002", "D", "2026-08-10T11:00:00+02:00", "2026-08-10T09:00:00Z", (51.001, 10.001), "city_eta_xm"),
    ("d3", "p_d000000003", "D", "2026-08-10T12:00:00+02:00", "2026-08-10T10:00:00Z", (51.002, 10.002), "city_eta_xm"),
    ("e1", "p_e000000001", "E", "2026-09-01T10:00:00+02:00", "2026-09-01T08:00:00Z", (50.003, 10.003), "city_gamma_xl"),
    ("e2", "p_e000000002", "E", "2026-09-01T11:00:00+02:00", "2026-09-01T09:00:00Z", north(REAL_HOME_4, 2.0), "city_gamma_xl"),
    ("e3", "p_e000000003", "E", "2026-09-01T12:00:00+02:00", "2026-09-01T10:00:00Z", (50.005, 10.005), "city_gamma_xl"),
]
PHOTO_ID = {key: pid for key, pid, *_ in PHOTOS}
# Scrambled order inside photo_trips so that sorting is really exercised.
SCRAMBLED_A = ["a6", "a8", "a1", "a5", "a2", "a7", "a4", "a3"]


def disc_radius(real, centre):
    return max(10.0, haversine(real, centre) + 10.0)


def haversine(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    h = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2)
    return 2 * 6371.0088 * math.asin(math.sqrt(h))


def city_point(city_id):
    return CITIES[city_id][3], CITIES[city_id][4]


def expected_distance(centre, city_ids):
    points = ([centre] if centre else []) + [city_point(c) for c in city_ids]
    return int(round(sum(haversine(a, b) for a, b in zip(points, points[1:]))))


def write_csv(path, columns, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False)


def photo_members(trip_key):
    keys = [k for k, _, t, *_ in PHOTOS if t == trip_key]
    return SCRAMBLED_A if trip_key == "A" else keys


def make_root(root, with_thumb=True):
    root = Path(root)
    processed = root / "data" / "processed"
    for radius, trips in RADIUS_TRIPS.items():
        write_csv(processed / f"trips_pred_r{radius}.csv",
                  ["person", "trip_id", "start_date", "end_date", "days", "max_distance_km",
                   "photo_count", "n_stays", "cities", "title"],
                  [["tester", TRIP_IDS[k], TRIP_ROWS[k][0], TRIP_ROWS[k][1], TRIP_ROWS[k][2], 999,
                    99, 1, "x", TRIP_ROWS[k][3]] for k in trips])
        write_csv(processed / f"trip_cities_r{radius}.csv",
                  ["trip_id", "city_id", "name", "country", "country_code", "lat", "lng",
                   "arrive", "leave", "photo_count"],
                  [[TRIP_IDS[k], cid, CITIES[cid][0], CITIES[cid][1], CITIES[cid][2],
                    f"{CITIES[cid][3]:.4f}", f"{CITIES[cid][4]:.4f}", TRIP_ROWS[k][0],
                    TRIP_ROWS[k][1], count]
                   for k in trips for cid, count in TRIP_CITY_ROWS[k]])
        write_csv(processed / f"photo_trips_r{radius}.csv", ["photo_id", "trip_id"],
                  [[PHOTO_ID[m], TRIP_IDS[k]] for k in trips for m in photo_members(k)])
    write_csv(processed / "photo_cities.csv", ["photo_id", "city_id", "distance_km"],
              [[pid, city, "1.0"] for _, pid, _, _, _, point, city in PHOTOS if point and city])
    write_csv(processed / "photos_clean.csv",
              ["photo_id", "person", "file_name", "taken_at", "taken_utc", "date", "lat", "lng",
               "has_gps"],
              [[pid, "tester", f"{key}.HEIC", at, utc, at[:10],
                "" if point is None else repr(point[0]), "" if point is None else repr(point[1]),
                "false" if point is None else "true"]
               for key, pid, _, at, utc, point, _ in PHOTOS])
    homes = [("2025-01-01", "2025-12-31", REAL_HOME_1), ("2026-01-01", "2026-06-30", REAL_HOME_1),
             ("2026-07-01", "2026-07-31", REAL_HOME_3), ("2026-08-01", "2026-12-31", REAL_HOME_4)]
    write_csv(processed / "homes.csv", ["from_date", "to_date", "lat", "lng"],
              [[f, t, repr(p[0]), repr(p[1])] for f, t, p in homes])
    write_csv(processed / "homes_city.csv",
              ["from_date", "to_date", "city_id", "name", "country_code", "lat", "lng"],
              [["2025-01-01", "2025-12-31", "city_homea_xl", "Homea", "XL", "12.5000", "34.5000"],
               ["2026-01-01", "2026-06-30", "city_homea_xl", "Homea", "XL", "12.5000", "34.5000"],
               ["2026-07-01", "2026-07-31", "", "", "", "", ""],
               ["2026-08-01", "2026-12-31", "city_homeb_xm", "Homeb", "XM", "45.6000", "-60.4000"]])
    geonames = root / "data" / "geonames"
    geonames.mkdir(parents=True, exist_ok=True)
    (geonames / "countryInfo.txt").write_text(
        "# synthetic\nXL\tXLD\t001\tXL\tLandia\tCapital\nXM\tXMD\t002\tXM\tMland\tCapital\n",
        encoding="utf-8")
    raw_rows = [  # FileName, DateTimeOriginal, ImageWidth, ImageHeight
        ["a3.HEIC", "2025:11:10 12:00:00", "4000", "3000"],   # scaled down to 1600x1200
        ["a6.HEIC", "2025:11:11 08:00:00", "3000", "4000"],   # portrait -> 1200x1600
        ["a5.HEIC", "2025:11:10 14:00:00", "800", "600"],     # small: never upscaled
        ["a1.HEIC", "2025:11:10 10:00:00", "4000", "3000"],   # overridden by the real _l.webp
    ]
    write_csv(root / "data" / "raw" / "photos_raw_tester_all.csv",
              ["FileName", "DateTimeOriginal", "ImageWidth", "ImageHeight"], raw_rows)
    if with_thumb:
        thumbs = root / "frontend" / "public" / "data" / "thumbs"
        thumbs.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (800, 600)).save(thumbs / f"{PHOTO_ID['a1']}_l.webp", "WEBP")
        Image.new("RGB", (400, 300)).save(thumbs / f"{PHOTO_ID['a1']}_s.webp", "WEBP")


def run_main(root, argv=None):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = build_json.main(argv or [], root=root)
    return code, out.getvalue()


class BuiltCase(unittest.TestCase):
    """Run build_json once on the synthetic root; individual tests only read the results."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls._tmp.name)
        make_root(cls.root)
        cls.code, cls.stdout = run_main(cls.root)
        out = cls.root / "frontend" / "public" / "data"
        cls.trips_text = (out / "trips.json").read_text(encoding="utf-8")
        cls.stats_text = (out / "stats.json").read_text(encoding="utf-8")
        cls.trips = json.loads(cls.trips_text)
        cls.stats = json.loads(cls.stats_text)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def trip(self, key, radius="50"):
        return next(t for t in self.trips["trips_by_radius"][radius] if t["id"] == TRIP_IDS[key])

    def photo(self, key, trip_key=None, radius="50"):
        trip = self.trip(trip_key or PHOTOS[[k for k, *_ in PHOTOS].index(key)][2], radius)
        return next(p for p in trip["photos"] if p["id"] == PHOTO_ID[key])


class StructureTests(BuiltCase):
    def test_run_succeeded(self):
        self.assertEqual(self.code, 0)

    def test_top_level_keys_and_versions(self):
        self.assertEqual(self.trips["schema_version"], "1.1")
        self.assertEqual(self.stats["schema_version"], "1.1")
        self.assertEqual(self.trips["default_radius_km"], 50)
        self.assertEqual(self.trips["radius_options_km"], [10, 25, 50, 100, 200])
        self.assertEqual(list(self.trips["trips_by_radius"]), ["10", "25", "50", "100", "200"])
        self.assertRegex(self.trips["generated_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$")

    def test_trips_per_radius_sorted_and_indexed(self):
        expected = {"10": "ABCDE", "25": "ABCD", "50": "ABCDE", "100": "AB", "200": "A"}
        for radius, keys in expected.items():
            trips = self.trips["trips_by_radius"][radius]
            self.assertEqual([t["id"] for t in trips], [TRIP_IDS[k] for k in keys], radius)
            self.assertEqual([t["index"] for t in trips], list(range(len(keys))), radius)

    def test_trips_equals_default_radius_list_as_a_copy(self):
        self.assertEqual(self.trips["trips"], self.trips["trips_by_radius"]["50"])

    def test_title_days_and_cities_come_from_the_csvs(self):
        trip = self.trip("A")
        self.assertEqual((trip["title"], trip["start_date"], trip["end_date"], trip["days"]),
                         ("Alpha", "2025-11-10", "2025-11-12", 3))
        self.assertEqual(trip["tags"], [])
        self.assertEqual(trip["cities"], [
            {"id": "city_alpha_xl", "name": "Alpha", "country": "Landia", "country_code": "XL",
             "lat": 10.0, "lng": 20.0, "arrive": "2025-11-10", "leave": "2025-11-12", "photo_count": 3},
            {"id": "city_beta_xl", "name": "Beta", "country": "Landia", "country_code": "XL",
             "lat": 11.0, "lng": 20.0, "arrive": "2025-11-10", "leave": "2025-11-12", "photo_count": 1}])
        self.assertEqual(self.trip("B")["title"], "Near Delta")
        self.assertEqual([c["id"] for c in self.trip("D")["cities"]], ["city_zeta_xm", "city_eta_xm"])

    def test_photo_count_is_the_number_of_photos(self):
        for key, count in (("A", 8), ("B", 5), ("C", 2), ("D", 3), ("E", 3)):
            trip = self.trip(key)
            self.assertEqual((trip["photo_count"], len(trip["photos"])), (count, count))

    def test_output_is_compact_utf8_with_trailing_newline(self):
        for text in (self.trips_text, self.stats_text):
            self.assertTrue(text.endswith("}\n"))
            self.assertNotIn(": ", text.split('"title"')[0])


class PhotoTests(BuiltCase):
    def test_photos_sorted_by_utc_then_naive_local_time(self):
        ids = [p["id"] for p in self.trip("A")["photos"]]
        self.assertEqual(ids, [PHOTO_ID[k] for k in ("a1", "a2", "a3", "a4", "a5", "a7", "a8", "a6")])

    def test_photo_paths_and_fields(self):
        photo = self.photo("a1")
        self.assertEqual(photo["thumb"], f"thumbs/{PHOTO_ID['a1']}_s.webp")
        self.assertEqual(photo["full"], f"thumbs/{PHOTO_ID['a1']}_l.webp")
        self.assertEqual((photo["taken_at"], photo["date"], photo["tags"]),
                         ("2025-11-10T10:00:00+01:00", "2025-11-10", []))
        self.assertEqual((photo["lat"], photo["lng"], photo["has_gps"], photo["city_id"]),
                         (10.001, 20.001, True, "city_alpha_xl"))

    def test_no_gps_photo_has_nulls(self):
        photo = self.photo("a2")
        self.assertEqual((photo["has_gps"], photo["lat"], photo["lng"], photo["city_id"]),
                         (False, None, None, None))

    def test_city_id_nulled_when_not_in_trip_cities(self):
        photo = self.photo("a3")
        self.assertTrue(photo["has_gps"])
        self.assertEqual((photo["lat"], photo["lng"]), (10.002, 20.002))
        self.assertIsNone(photo["city_id"])

    def test_photo_near_real_home_snaps_to_home_city_centre(self):
        photo = self.photo("a4")
        self.assertEqual((photo["lat"], photo["lng"], photo["has_gps"], photo["city_id"]),
                         (12.5, 34.5, True, "city_alpha_xl"))   # coordinates snapped, city kept

    def test_snap_disc_is_centred_on_the_city_centre_and_grown_by_the_home_offset(self):
        # Preconditions of the geometry used below (haversine in the test, not in the code).
        disc = disc_radius(REAL_HOME_1, CENTRE_A)
        self.assertGreater(disc, 20.0)
        for key, near_real in (("a4", True), ("a7", True), ("a8", False)):
            point = next(pt for k, _, _, _, _, pt, _ in PHOTOS if k == key)
            self.assertLess(haversine(point, CENTRE_A), disc)
            self.assertEqual(haversine(point, REAL_HOME_1) <= 10.0, near_real, key)
        self.assertGreater(haversine(north(CENTRE_A, 40.0), CENTRE_A), disc)

    def test_photo_8_km_from_real_home_on_the_far_side_is_snapped(self):
        photo = self.photo("a7")
        self.assertEqual((photo["lat"], photo["lng"], photo["has_gps"], photo["city_id"]),
                         (12.5, 34.5, True, "city_alpha_xl"))

    def test_photo_inside_enlarged_disc_but_far_from_real_home_is_snapped(self):
        photo = self.photo("a8")
        self.assertEqual((photo["lat"], photo["lng"], photo["has_gps"], photo["city_id"]),
                         (12.5, 34.5, True, "city_alpha_xl"))

    def test_photo_outside_the_disc_keeps_its_coordinates(self):
        lat, lng = north(CENTRE_A, 40.0)
        photo = self.photo("a5")
        self.assertEqual((photo["lat"], photo["lng"]), (round(lat, 4), round(lng, 4)))
        self.assertEqual(photo["city_id"], "city_alpha_xl")

    def test_snapping_is_identical_in_every_radius_list(self):
        for radius in ("10", "25", "50", "100", "200"):
            self.assertEqual((self.photo("a7", "A", radius)["lat"], self.photo("a8", "A", radius)["lat"]),
                             (12.5, 12.5), radius)

    def test_disc_radius_never_appears_in_any_output(self):
        disc = disc_radius(REAL_HOME_1, CENTRE_A)
        for text in (self.trips_text, self.stats_text, self.stdout):
            self.assertNotIn(repr(disc), text)
            self.assertNotIn(f"{disc:.4f}", text)
        self.assertNotIn(f"{disc:.1f}", self.stdout)

    def test_photo_near_another_periods_home_inside_a_trip_is_snapped_to_that_centre(self):
        # b4 lies 3 km from the home of period 4 but belongs to a trip of period 2.
        photo = self.photo("b4")
        self.assertEqual((photo["lat"], photo["lng"], photo["has_gps"], photo["city_id"]),
                         (CENTRE_B[0], CENTRE_B[1], True, "city_delta_xm"))

    def test_photo_near_a_home_without_city_inside_another_periods_trip_is_hidden(self):
        photo = self.photo("b5")
        self.assertEqual((photo["has_gps"], photo["lat"], photo["lng"], photo["city_id"]),
                         (False, None, None, None))

    def test_period_without_home_city_hides_the_gps_of_a_near_home_photo(self):
        photo = self.photo("c1")
        self.assertEqual((photo["has_gps"], photo["lat"], photo["lng"], photo["city_id"]),
                         (False, None, None, None))

    def test_real_home_never_appears_in_any_output(self):
        for text in (self.trips_text, self.stats_text, self.stdout):
            self.assertNotIn(REAL_HOME_TEXT, text)
            for point in (REAL_HOME_1, REAL_HOME_3, REAL_HOME_4):
                self.assertNotIn(repr(point[0]), text)
                self.assertNotIn(repr(point[1]), text)
        self.assertNotIn("45.5,", self.trips_text)

    def test_width_height_from_existing_full_image(self):
        photo = self.photo("a1")
        self.assertEqual((photo["width"], photo["height"]), (800, 600))

    def test_width_height_from_raw_sizes_scaled_without_upscaling(self):
        self.assertEqual((self.photo("a3")["width"], self.photo("a3")["height"]), (1600, 1200))
        self.assertEqual((self.photo("a6")["width"], self.photo("a6")["height"]), (1200, 1600))
        self.assertEqual((self.photo("a5")["width"], self.photo("a5")["height"]), (800, 600))

    def test_width_height_default_when_nothing_is_known(self):
        self.assertEqual((self.photo("b1")["width"], self.photo("b1")["height"]), (1600, 1200))


class TripTests(BuiltCase):
    def test_distance_runs_from_home_city_centre_through_cities(self):
        self.assertEqual(self.trip("A")["distance_km"],
                         expected_distance(CENTRE_A, ["city_alpha_xl", "city_beta_xl"]))
        self.assertEqual(self.trip("B")["distance_km"], expected_distance(CENTRE_A, ["city_delta_xm"]))
        self.assertEqual(self.trip("D")["distance_km"],
                         expected_distance(CENTRE_B, ["city_zeta_xm", "city_eta_xm"]))

    def test_distance_without_home_city_starts_at_the_first_city(self):
        self.assertEqual(self.trip("C")["distance_km"],
                         expected_distance(None, ["city_epsilon_xl", "city_epsb_xl"]))

    def test_cover_is_middle_photo_of_the_main_city(self):
        self.assertEqual(self.trip("A")["cover_photo_id"], PHOTO_ID["a5"])   # candidates a1, a5

    def test_cover_for_near_trip_uses_the_single_listed_city(self):
        self.assertEqual(self.trip("B")["cover_photo_id"], PHOTO_ID["b3"])   # candidates b1, b3

    def test_cover_falls_back_to_most_photographed_city_when_title_does_not_match(self):
        self.assertEqual(self.trip("D")["cover_photo_id"], PHOTO_ID["d3"])   # eta: d2, d3

    def test_cover_falls_back_to_middle_unsnapped_gps_photo(self):
        # e2 is the middle GPS photo but is snapped to the home centre, so e3 is chosen.
        self.assertTrue(self.photo("e2")["has_gps"])
        self.assertEqual(self.photo("e2")["lat"], 45.6)
        self.assertEqual(self.trip("E")["cover_photo_id"], PHOTO_ID["e3"])

    def test_cover_falls_back_to_middle_photo_without_gps(self):
        self.assertEqual(self.trip("C")["cover_photo_id"], PHOTO_ID["c2"])


def synthetic_periods():
    """Two home periods with nearby centres (5 km apart) and real homes close to their centres."""
    first_centre = (20.0, 20.0)
    second_centre = north(first_centre, 5.0)
    periods = []
    for centre in (first_centre, second_centre):
        real = north(centre, 1.0)
        periods.append({"from": "", "to": "", "real": real, "centre": centre,
                        "disc_km": build_json.disc_radius_km(real, centre)})
    return periods, first_centre, second_centre


class DecidePrivacyTests(unittest.TestCase):
    def test_photo_near_a_former_home_snaps_to_that_periods_centre(self):
        periods, first, second = synthetic_periods()
        far_second = north(second, 200.0)
        periods[1]["real"] = far_second          # make the two discs disjoint
        periods[1]["centre"] = north(far_second, 0.5)
        periods[1]["disc_km"] = build_json.disc_radius_km(far_second, periods[1]["centre"])
        action, centre = build_json.decide_privacy(*north(periods[0]["real"], 2.0), periods)
        self.assertEqual((action, centre), ("snap", first))

    def test_overlapping_discs_pick_the_nearest_centre(self):
        periods, first, second = synthetic_periods()
        near_second = north(second, 1.0)
        near_first = north(first, -1.0)
        self.assertEqual(build_json.decide_privacy(*near_second, periods), ("snap", second))
        self.assertEqual(build_json.decide_privacy(*near_first, periods), ("snap", first))

    def test_far_photo_is_kept(self):
        periods, _, _ = synthetic_periods()
        self.assertEqual(build_json.decide_privacy(*north((20.0, 20.0), 100.0), periods), ("keep", None))

    def test_period_without_city_hides_nearby_photos(self):
        periods, _, _ = synthetic_periods()
        periods.append({"from": "", "to": "", "real": (-30.0, -30.0), "centre": None, "disc_km": None})
        self.assertEqual(build_json.decide_privacy(*north((-30.0, -30.0), 4.0), periods), ("hide", None))
        self.assertEqual(build_json.decide_privacy(*north((-30.0, -30.0), 15.0), periods), ("keep", None))


class PickCoverTests(unittest.TestCase):
    @staticmethod
    def photo(pid, gps=True, city=None):
        return {"id": pid, "has_gps": gps, "city_id": city}

    def test_near_trip_whose_photos_have_no_matching_city_uses_middle_unsnapped_gps_photo(self):
        cities = [{"id": "city_x_xl", "name": "X", "photo_count": 5}]
        photos = [self.photo("p1", city=None), self.photo("p2", city=None),
                  self.photo("p3", city=None), self.photo("p4", city=None)]
        self.assertEqual(build_json.pick_cover("Near X", cities, photos, {"p3"}), "p2")  # [p1, p2, p4][1]

    def test_snapped_photo_is_skipped_in_the_main_city_choice(self):
        cities = [{"id": "city_x_xl", "name": "X", "photo_count": 3}]
        photos = [self.photo("p1", city="city_x_xl"), self.photo("p2", city="city_x_xl"),
                  self.photo("p3", city="city_x_xl")]
        self.assertEqual(build_json.pick_cover("X", cities, photos, {"p2"}), "p3")

    def test_all_snapped_or_no_gps_falls_back_to_the_middle_photo(self):
        cities = [{"id": "city_x_xl", "name": "X", "photo_count": 3}]
        photos = [self.photo("p1", gps=False), self.photo("p2"), self.photo("p3", gps=False)]
        self.assertEqual(build_json.pick_cover("X", cities, photos, {"p2"}), "p2")

    def test_no_photos_gives_none(self):
        self.assertIsNone(build_json.pick_cover("X", [], [], set()))


class HomesTests(BuiltCase):
    def test_same_city_periods_are_merged_and_city_less_periods_dropped(self):
        self.assertEqual(self.trips["homes"], [
            {"from_date": "2025-01-01", "to_date": "2026-06-30", "city": "Homea",
             "country_code": "XL", "lat": 12.5, "lng": 34.5},
            {"from_date": "2026-08-01", "to_date": "2026-12-31", "city": "Homeb",
             "country_code": "XM", "lat": 45.6, "lng": -60.4}])

    def test_home_is_the_last_homes_entry_with_country_name(self):
        self.assertEqual(self.trips["home"], {"city": "Homeb", "country": "Mland",
                                              "country_code": "XM", "lat": 45.6, "lng": -60.4})


class StatsTests(BuiltCase):
    def test_radius_100_stats(self):
        dist_a = expected_distance(CENTRE_A, ["city_alpha_xl", "city_beta_xl"])
        dist_b = expected_distance(CENTRE_A, ["city_delta_xm"])
        stats = self.stats["by_radius"]["100"]
        self.assertEqual(stats["all_time"], {
            "trips": 2, "cities": 3, "countries": 2, "days_away": 4, "distance_km": dist_a + dist_b,
            "photos_total": 13, "photos_with_gps": 10, "top_tags": [], "persona": None})
        self.assertEqual(list(stats["by_year"]), ["2025", "2026"])
        self.assertEqual(stats["by_year"]["2025"], {
            "trips": 1, "cities": 2, "countries": 1, "days_away": 3, "distance_km": dist_a,
            "photos_total": 8, "photos_with_gps": 7, "top_tags": [], "persona": None})
        self.assertEqual(stats["by_year"]["2026"]["trips"], 1)
        self.assertEqual(stats["by_year"]["2026"]["photos_with_gps"], 3)
        self.assertEqual(stats["by_year"]["2026"]["photos_total"], 5)

    def test_radius_200_and_top_level_match_default_radius(self):
        self.assertEqual(self.stats["by_radius"]["200"]["all_time"]["trips"], 1)
        self.assertEqual(self.stats["by_radius"]["10"]["all_time"]["trips"], 5)
        self.assertEqual(self.stats["all_time"], self.stats["by_radius"]["50"]["all_time"])
        self.assertEqual(self.stats["by_year"], self.stats["by_radius"]["50"]["by_year"])
        self.assertEqual(list(self.stats["by_radius"]), ["10", "25", "50", "100", "200"])

    def test_photos_with_gps_counts_snapped_photos_but_not_hidden_ones(self):
        # r50: A 7 (snapped a4, a7, a8 still GPS), B 3 (b4 snapped, b5 hidden), C 0, D 3, E 3
        self.assertEqual(self.stats["all_time"]["photos_with_gps"], 16)
        self.assertEqual(self.stats["all_time"]["photos_total"], 21)


class ConsoleAndContractTests(BuiltCase):
    def test_stdout_has_exactly_the_documented_shape(self):
        lines = self.stdout.strip().splitlines()
        self.assertEqual(lines[:5], ["r=10 km: 5 trips, 21 photos", "r=25 km: 4 trips, 18 photos",
                                     "r=50 km: 5 trips, 21 photos", "r=100 km: 2 trips, 13 photos",
                                     "r=200 km: 1 trips, 8 photos"])
        self.assertRegex(lines[5], r"^trips\.json: \d+\.\d KB, stats\.json: \d+\.\d KB$")
        self.assertEqual(lines[6], "Missing thumbnails: 20 of 21 photos")
        self.assertEqual(lines[7], "Privacy check: OK")
        self.assertRegex(lines[8], r"^Contract 1\.1 \(data\): OK \(\d+ checks\), 7 warnings$")
        self.assertEqual(len(lines), 9)

    def test_output_passes_the_contract_checker_in_data_mode(self):
        import check_contract
        result = check_contract.check(self.root / "frontend" / "public" / "data", "data")
        self.assertEqual(result.errors, [])
        # a6 has no UTC offset; trip C (r10, r25, r50) lists two cities and has no GPS photo to give them
        self.assertEqual(len(result.warnings), 7)
        self.assertEqual(sum("has no photos" in w for w in result.warnings), 6)
        self.assertEqual(result.missing_thumbs, 40)     # 20 photos x (_s, _l)
        self.assertEqual(result.total_thumbs, 42)


# ---- every trip city gets photos -----------------------------------------------------------

def city_point_dict(city_id, lat, lng):
    return {"id": city_id, "lat": lat, "lng": lng}


def synthetic_photo(pid, city=None, gps=True):
    return {"id": pid, "has_gps": gps, "city_id": city}


class EnsureCityPhotosTests(unittest.TestCase):
    CITIES = [city_point_dict("c_x", 0.0, 0.0), city_point_dict("c_y", 0.0, 10.0)]

    def run_ensure(self, photos, points, cities=None, snapped=frozenset()):
        build_json.ensure_city_photos(self.CITIES if cities is None else cities, photos, points,
                                      snapped)
        return {p["id"]: p["city_id"] for p in photos}

    def test_nothing_changes_when_every_city_has_a_photo(self):
        photos = [synthetic_photo("a", "c_x"), synthetic_photo("b", "c_y"), synthetic_photo("n")]
        got = self.run_ensure(photos, {"a": (0.0, 0.0), "b": (0.0, 10.0), "n": (0.0, 9.0)})
        self.assertEqual(got, {"a": "c_x", "b": "c_y", "n": None})

    def test_step_a_gives_each_unlabelled_gps_photo_its_nearest_city(self):
        photos = [synthetic_photo("a"), synthetic_photo("b"), synthetic_photo("c")]
        got = self.run_ensure(photos, {"a": (0.0, 1.0), "b": (0.0, 9.0), "c": (0.0, 2.0)})
        self.assertEqual(got, {"a": "c_x", "b": "c_y", "c": "c_x"})

    def test_step_a_runs_when_only_one_city_is_empty_and_leaves_labelled_photos_alone(self):
        photos = [synthetic_photo("a", "c_x"), synthetic_photo("n1"), synthetic_photo("n2")]
        got = self.run_ensure(photos, {"a": (0.0, 9.0), "n1": (0.0, 8.0), "n2": (0.0, 1.0)})
        self.assertEqual(got, {"a": "c_x", "n1": "c_y", "n2": "c_x"})

    def test_step_b_moves_the_nearest_candidate_to_an_empty_city(self):
        # All three unlabelled photos are nearest to c_y; c_x takes the one closest to it.
        photos = [synthetic_photo("a"), synthetic_photo("b"), synthetic_photo("c")]
        got = self.run_ensure(photos, {"a": (0.0, 6.0), "b": (0.0, 8.0), "c": (0.0, 9.0)})
        self.assertEqual(got, {"a": "c_x", "b": "c_y", "c": "c_y"})

    def test_step_b_never_empties_another_city(self):
        photos = [synthetic_photo("a")]
        got = self.run_ensure(photos, {"a": (0.0, 9.0)})
        self.assertEqual(got, {"a": "c_y"})     # c_x stays empty: c_y would lose its only photo

    def test_step_b_only_moves_photos_that_were_unlabelled_before(self):
        photos = [synthetic_photo("keep", "c_y"), synthetic_photo("n")]
        got = self.run_ensure(photos, {"keep": (0.0, 0.0), "n": (0.0, 9.0)})
        # c_x is empty; step a gives n to c_y; step b moves n (c_y still has keep).
        self.assertEqual(got, {"keep": "c_y", "n": "c_x"})
        photos = [synthetic_photo("keep", "c_y")]
        self.assertEqual(self.run_ensure(photos, {"keep": (0.0, 0.0)}), {"keep": "c_y"})

    def test_step_b_runs_in_visit_order_for_several_empty_cities(self):
        cities = self.CITIES + [city_point_dict("c_z", 0.0, 20.0)]
        photos = [synthetic_photo(k) for k in "abcd"]
        points = {"a": (0.0, 11.0), "b": (0.0, 12.0), "c": (0.0, 13.0), "d": (0.0, 14.0)}
        got = self.run_ensure(photos, points, cities)
        # step a: all four nearest to c_y; step b: c_x takes a (nearest to it), c_z takes d
        self.assertEqual(got, {"a": "c_x", "b": "c_y", "c": "c_y", "d": "c_z"})

    def test_step_a_leaves_a_snapped_unlabelled_photo_without_a_city(self):
        photos = [synthetic_photo("r1"), synthetic_photo("r2"), synthetic_photo("snap")]
        got = self.run_ensure(photos, {"r1": (0.0, 1.0), "r2": (0.0, 9.0), "snap": (0.0, 8.0)},
                              snapped={"snap"})
        self.assertEqual(got, {"r1": "c_x", "r2": "c_y", "snap": None})

    def test_step_b_prefers_an_unsnapped_candidate_over_a_nearer_snapped_one(self):
        # c_x is nearest to the snapped photo "s" (km 1), but "a" (km 6) is a real-position
        # photo that was given c_y in step a and c_y keeps "b".
        photos = [synthetic_photo("s"), synthetic_photo("a"), synthetic_photo("b")]
        got = self.run_ensure(photos, {"s": (0.0, 1.0), "a": (0.0, 6.0), "b": (0.0, 9.0)},
                              snapped={"s"})
        self.assertEqual(got, {"s": None, "a": "c_x", "b": "c_y"})

    def test_step_b_uses_a_snapped_still_unlabelled_photo_when_it_is_the_only_way(self):
        photos = [synthetic_photo("real"), synthetic_photo("s1"), synthetic_photo("s2")]
        points = {"real": (0.0, 9.0), "s1": (0.0, 8.0), "s2": (0.0, 2.0)}
        got = self.run_ensure(photos, points, snapped={"s1", "s2"})
        # "real" goes to c_y and cannot leave it; the nearer snapped photo s2 fills c_x.
        self.assertEqual(got, {"real": "c_y", "s1": None, "s2": "c_x"})

    def test_snapped_photos_alone_can_fill_an_empty_trip(self):
        photos = [synthetic_photo("s1"), synthetic_photo("s2")]
        got = self.run_ensure(photos, {"s1": (0.0, 1.0), "s2": (0.0, 9.0)}, snapped={"s1", "s2"})
        self.assertEqual(got, {"s1": "c_x", "s2": "c_y"})

    def test_photos_without_gps_never_get_a_city(self):
        photos = [synthetic_photo("n", gps=False), synthetic_photo("g")]
        got = self.run_ensure(photos, {"g": (0.0, 1.0)})
        self.assertEqual(got, {"n": None, "g": "c_x"})

    def test_no_cities_or_no_photos_is_a_no_op(self):
        self.assertEqual(self.run_ensure([], {}), {})
        photos = [synthetic_photo("g")]
        self.assertEqual(self.run_ensure(photos, {"g": (0.0, 0.0)}, cities=[]), {"g": None})


class CityCoverageTests(BuiltCase):
    def city_counts(self, trip):
        counts = {c["id"]: 0 for c in trip["cities"]}
        for photo in trip["photos"]:
            if photo["city_id"] is not None:
                counts[photo["city_id"]] += 1
        return counts

    def test_snapped_photos_keep_their_trip_city_with_snapped_coordinates(self):
        for key, trip_key, city in (("a4", "A", "city_alpha_xl"), ("b4", "B", "city_delta_xm")):
            for radius in ("10", "25", "50", "100"):
                try:
                    photo = self.photo(key, trip_key, radius)
                except StopIteration:
                    continue
                self.assertEqual(photo["city_id"], city, (key, radius))
                self.assertIn((photo["lat"], photo["lng"]), (CENTRE_A, CENTRE_B), (key, radius))

    def test_hidden_photos_keep_a_null_city(self):
        for key in ("b5", "c1"):
            photo = self.photo(key)
            self.assertEqual((photo["has_gps"], photo["city_id"]), (False, None), key)

    def test_trip_with_unlabelled_photos_and_an_empty_city_gets_the_nearest_city(self):
        # Trip E lists only Zeta; its photos carry a city that is not a trip city, so the two
        # real-position photos are given Zeta and the snapped e2 stays without a city.
        trip = self.trip("E")
        self.assertEqual([p["city_id"] for p in trip["photos"]],
                         ["city_zeta_xm", None, "city_zeta_xm"])
        self.assertEqual(self.city_counts(trip), {"city_zeta_xm": 2})

    def test_trip_with_no_unlabelled_gps_photo_keeps_its_empty_cities(self):
        trip = self.trip("C")
        self.assertEqual(self.city_counts(trip), {"city_epsilon_xl": 0, "city_epsb_xl": 0})
        self.assertTrue(all(p["city_id"] is None for p in trip["photos"]))

    def test_checker_reports_empty_cities_as_warnings_not_errors(self):
        import check_contract
        result = check_contract.check(self.root / "frontend" / "public" / "data", "data")
        self.assertEqual(result.errors, [])
        messages = [w for w in result.warnings if "has no photos" in w]
        self.assertIn(f"trip {TRIP_IDS['C']} city city_epsilon_xl has no photos", messages)
        self.assertIn(f"trip {TRIP_IDS['C']} city city_epsb_xl has no photos", messages)
        self.assertEqual(len(messages), 6)

    def test_every_city_of_the_other_trips_has_a_photo(self):
        for radius, trip_list in self.trips["trips_by_radius"].items():
            for trip in trip_list:
                if trip["id"] == TRIP_IDS["C"]:
                    continue
                self.assertTrue(all(n > 0 for n in self.city_counts(trip).values()), (radius, trip["id"]))

    def test_city_photo_count_comes_from_the_csv_and_is_not_recomputed(self):
        self.assertEqual([c["photo_count"] for c in self.trip("E")["cities"]], [3])
        self.assertEqual([c["photo_count"] for c in self.trip("C")["cities"]], [1, 1])
        self.assertEqual([c["photo_count"] for c in self.trip("D")["cities"]], [1, 5])

    def test_trips_whose_cities_are_all_covered_are_identical_without_the_step(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            make_root(tmp)
            with mock.patch.object(build_json, "ensure_city_photos", lambda *args: None):
                code, _ = run_main(tmp)
            plain = json.loads((Path(tmp) / "frontend" / "public" / "data" / "trips.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        for radius, trip_list in self.trips["trips_by_radius"].items():
            others = {t["id"]: t for t in plain["trips_by_radius"][radius]}
            for trip in trip_list:
                if trip["id"] in (TRIP_IDS["B"], TRIP_IDS["E"]):
                    continue
                self.assertEqual(json.dumps(trip, sort_keys=True),
                                 json.dumps(others[trip["id"]], sort_keys=True), (radius, trip["id"]))


class CityCoverageVariantTests(unittest.TestCase):
    """Edit the synthetic inputs, rebuild, and look at the resulting trip."""

    def build_variant(self, edit):
        with tempfile.TemporaryDirectory() as tmp:
            make_root(tmp, with_thumb=False)
            processed = Path(tmp) / "data" / "processed"
            edit(processed)
            code, text = run_main(tmp)
            doc = json.loads((Path(tmp) / "frontend" / "public" / "data" / "trips.json").read_text(encoding="utf-8"))
            trips_text = (Path(tmp) / "frontend" / "public" / "data" / "trips.json").read_text(encoding="utf-8")
        self.assertEqual(code, 0)
        self.assertIn("Privacy check: OK", text.splitlines())
        for sentinel in (REAL_HOME_TEXT, repr(REAL_HOME_3[0]), repr(REAL_HOME_4[0])):
            self.assertNotIn(sentinel, text + trips_text)
        return doc

    @staticmethod
    def edit_csv(path, function):
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        function(frame).to_csv(path, index=False)

    def trip(self, doc, key, radius="50"):
        return next(t for t in doc["trips_by_radius"][radius] if t["id"] == TRIP_IDS[key])

    def city_of(self, trip, key):
        return next(p for p in trip["photos"] if p["id"] == PHOTO_ID[key])["city_id"]

    def test_snapped_photo_whose_city_is_not_a_trip_city_gets_null(self):
        def edit(processed):
            self.edit_csv(processed / "photo_cities.csv",
                          lambda f: f.assign(city_id=f["city_id"].where(f["photo_id"] != PHOTO_ID["a4"],
                                                                        "city_gamma_xl")))
        doc = self.build_variant(edit)
        trip = self.trip(doc, "A")
        photo = next(p for p in trip["photos"] if p["id"] == PHOTO_ID["a4"])
        self.assertEqual((photo["lat"], photo["lng"], photo["city_id"]), (12.5, 34.5, None))
        self.assertEqual(self.city_of(trip, "a7"), "city_alpha_xl")   # trip A was already covered

    def test_near_trip_gives_its_city_to_every_unlabelled_unsnapped_gps_photo(self):
        def edit(processed):
            self.edit_csv(processed / "photo_cities.csv",
                          lambda f: f[~f["photo_id"].isin([PHOTO_ID[k] for k in ("b1", "b3", "b4", "b5")])])
        doc = self.build_variant(edit)
        for radius in ("10", "25", "50", "100"):
            trip = self.trip(doc, "B", radius)
            by_key = {k: self.city_of(trip, k) for k in ("b1", "b2", "b3", "b4", "b5")}
            self.assertEqual(by_key, {"b1": "city_delta_xm", "b2": None, "b3": "city_delta_xm",
                                      "b4": None, "b5": None}, radius)   # b4 is snapped
            snapped = next(p for p in trip["photos"] if p["id"] == PHOTO_ID["b4"])
            self.assertEqual((snapped["lat"], snapped["lng"]), CENTRE_B)

    def trip_a_with_only(self, keep):
        """Trip A (cities Alpha at 10,20 and Beta at 11,20) with every photo unlabelled."""
        def edit(processed):
            drop = {PHOTO_ID[k] for k, _, t, *_ in PHOTOS if t == "A" and k not in keep}
            self.edit_csv(processed / "photo_cities.csv",
                          lambda f: f[~f["photo_id"].str.startswith("p_a")])
            for radius in RADIUS_TRIPS:
                self.edit_csv(processed / f"photo_trips_r{radius}.csv",
                              lambda f: f[~f["photo_id"].isin(drop)])
        return edit

    def test_main_city_without_labelled_photos_is_given_the_nearest_photo(self):
        # a5 and a6 are both nearer to Beta than to Alpha; a6 is the one nearest to Alpha.
        # a4, a7, a8 are snapped: they stay without a city.
        doc = self.build_variant(self.trip_a_with_only({"a2", "a4", "a5", "a6", "a7", "a8"}))
        trip = self.trip(doc, "A")
        got = {k: self.city_of(trip, k) for k in ("a2", "a4", "a5", "a6", "a7", "a8")}
        self.assertEqual(got, {"a2": None, "a4": None, "a5": "city_beta_xl",
                               "a6": "city_alpha_xl", "a7": None, "a8": None})
        photo = next(p for p in trip["photos"] if p["id"] == PHOTO_ID["a4"])
        self.assertEqual((photo["lat"], photo["lng"]), CENTRE_A)       # still snapped

    def test_snapped_photo_fills_an_empty_city_only_when_no_unsnapped_photo_can_move(self):
        # a6 is the only real-position photo (goes to Beta and cannot leave); snapped a4 (still
        # without a city) fills Alpha, as the nearest snapped candidate.
        doc = self.build_variant(self.trip_a_with_only({"a2", "a4", "a6"}))
        trip = self.trip(doc, "A")
        got = {k: self.city_of(trip, k) for k in ("a2", "a4", "a6")}
        self.assertEqual(got, {"a2": None, "a4": "city_alpha_xl", "a6": "city_beta_xl"})
        photo = next(p for p in trip["photos"] if p["id"] == PHOTO_ID["a4"])
        self.assertEqual((photo["lat"], photo["lng"]), CENTRE_A)

    def test_city_stays_empty_when_giving_it_a_photo_would_empty_another(self):
        doc = self.build_variant(self.trip_a_with_only({"a2", "a6"}))
        trip = self.trip(doc, "A")
        self.assertEqual(self.city_of(trip, "a6"), "city_beta_xl")
        self.assertEqual([p["city_id"] for p in trip["photos"] if p["id"] == PHOTO_ID["a2"]], [None])
        self.assertEqual(sorted(c["id"] for c in trip["cities"]), ["city_alpha_xl", "city_beta_xl"])


class PrivacySelfCheckTests(unittest.TestCase):
    def test_self_check_fails_and_writes_nothing_when_the_snap_is_disabled(self):
        from unittest import mock
        with tempfile.TemporaryDirectory() as tmp:
            make_root(tmp, with_thumb=False)
            with mock.patch.object(build_json, "decide_privacy", lambda lat, lng, periods: ("keep", None)):
                code, text = run_main(tmp)
            out = Path(tmp) / "frontend" / "public" / "data"
            self.assertEqual(code, 1)
            self.assertEqual(text.strip(), "error: privacy check failed")
            self.assertFalse((out / "trips.json").exists())
            self.assertFalse((out / "stats.json").exists())
            for sentinel in (REAL_HOME_TEXT, repr(REAL_HOME_3[0]), repr(REAL_HOME_4[0])):
                self.assertNotIn(sentinel, text)

    def test_self_check_passes_on_the_normal_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_root(tmp, with_thumb=False)
            code, text = run_main(tmp)
        self.assertEqual(code, 0)
        self.assertIn("Privacy check: OK", text.splitlines())


class FailureTests(unittest.TestCase):
    def test_trip_city_without_coordinates_fails_with_one_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_root(tmp)
            path = Path(tmp) / "data" / "processed" / "trip_cities_r25.csv"
            frame = pd.read_csv(path, dtype=str, keep_default_na=False)
            frame.loc[0, "lat"] = ""
            frame.to_csv(path, index=False)
            code, text = run_main(tmp)
        self.assertEqual(code, 1)
        self.assertEqual(len(text.strip().splitlines()), 1)

    def test_period_matched_strictly_on_dates_never_by_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_root(tmp)
            path = Path(tmp) / "data" / "processed" / "homes_city.csv"
            frame = pd.read_csv(path, dtype=str, keep_default_na=False)
            frame.loc[3, "to_date"] = "2026-12-30"       # no longer matches homes.csv row 4
            frame.to_csv(path, index=False)
            code, _ = run_main(tmp)
            doc = json.loads((Path(tmp) / "frontend" / "public" / "data" / "trips.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        trip = next(t for t in doc["trips"] if t["id"] == TRIP_IDS["E"])
        e2 = next(p for p in trip["photos"] if p["id"] == PHOTO_ID["e2"])
        self.assertEqual((e2["has_gps"], e2["lat"], e2["lng"], e2["city_id"]), (False, None, None, None))
        trip_d = next(t for t in doc["trips"] if t["id"] == TRIP_IDS["D"])
        self.assertEqual(trip_d["distance_km"], expected_distance(None, ["city_zeta_xm", "city_eta_xm"]))

    def test_missing_input_prints_one_line_and_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_root(tmp)
            (Path(tmp) / "data" / "processed" / "trips_pred_r100.csv").unlink()
            code, text = run_main(tmp)
        self.assertEqual(code, 1)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertNotIn("Traceback", text)

    def test_missing_raw_file_is_not_fatal_and_uses_default_sizes(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_root(tmp, with_thumb=False)
            (Path(tmp) / "data" / "raw" / "photos_raw_tester_all.csv").unlink()
            code, text = run_main(tmp)
            doc = json.loads((Path(tmp) / "frontend" / "public" / "data" / "trips.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        self.assertIn("Missing thumbnails: 21 of 21 photos", text)
        photo = doc["trips"][0]["photos"][0]
        self.assertEqual((photo["width"], photo["height"]), (1600, 1200))

    def test_person_option_selects_the_raw_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_root(tmp, with_thumb=False)
            raw = Path(tmp) / "data" / "raw"
            (raw / "photos_raw_tester_all.csv").rename(raw / "photos_raw_other_all.csv")
            code, _ = run_main(tmp, ["--person", "other"])
            doc = json.loads((Path(tmp) / "frontend" / "public" / "data" / "trips.json").read_text(encoding="utf-8"))
        self.assertEqual(code, 0)
        photo = next(p for t in doc["trips"] for p in t["photos"] if p["id"] == PHOTO_ID["a3"])
        self.assertEqual((photo["width"], photo["height"]), (1600, 1200))
        photo = next(p for t in doc["trips"] for p in t["photos"] if p["id"] == PHOTO_ID["a6"])
        self.assertEqual((photo["width"], photo["height"]), (1200, 1600))


if __name__ == "__main__":
    unittest.main()
