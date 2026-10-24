"""Unit tests for backend/geocode.py (synthetic data only). Run from the repo root:

    .venv/bin/python -W error -m unittest discover -s backend/tests -v

Every place, photo and home below is invented; nothing here is anyone's real data.
"""

import contextlib
import io
import math
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import geocode  # noqa: E402
import segment  # noqa: E402

KM_PER_DEG = 6371.0088 * math.pi / 180.0  # one degree of latitude / of longitude on the equator
SENTINEL_NAME = "SENTINEL_SECRET_NAME_123.HEIC"

# Invented towns on the equator / prime meridian, ~111 km apart.
ALPHA = (0.0, 0.0)
BETA = (1.0, 0.0)
GAMMA = (2.0, 0.0)
DELTA = (3.0, 0.0)
SAO = (4.0, 0.0)
# Photos sit a few hundred metres off the town centres; these strings must never be printed.
PHOTO_OFFSET = (0.001234, 0.000567)
HOME_POINT = (0.012345, 0.023456)   # ~2.6 km from ALPHA
FAR_HOME_POINT = (50.123456, 50.654321)

COUNTRY_INFO = (
    "# GeoNames country info (synthetic)\n"
    "US\tUSA\t840\tUS\tUnited States\tWashington\n"
    "BR\tBRA\t076\tBR\tBrazil\tBrasilia\n"
)


def north(lat, km):
    """Latitude `km` north of `lat` (on the same meridian)."""
    return lat + km / KM_PER_DEG


def place(geonameid, name, lat, lng, pop=100000, code="PPL", cc="US", admin1="MA", ascii_name=None):
    return {"geonameid": str(geonameid), "name": name, "asciiname": ascii_name or name,
            "lat": lat, "lng": lng, "code": code, "cc": cc, "admin1": admin1, "pop": str(pop)}


def write_geonames(root, places, country_info=COUNTRY_INFO):
    folder = Path(root) / "data" / "geonames"
    folder.mkdir(parents=True, exist_ok=True)
    lines = []
    for p in places:
        fields = [p["geonameid"], p["name"], p["asciiname"], "", f"{p['lat']:.6f}",
                  f"{p['lng']:.6f}", "P", p["code"], p["cc"], "", p["admin1"], "", "", "",
                  p["pop"], "", "", "UTC", "2020-01-01"]
        assert len(fields) == 19
        lines.append("\t".join(fields))
    (folder / "cities5000.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (folder / "countryInfo.txt").write_text(country_info, encoding="utf-8")


def gazetteer_for(places, **overrides):
    """Load a gazetteer built from `places` in a throwaway folder; return (gaz, finder)."""
    params = geocode.resolve_params(overrides)
    with tempfile.TemporaryDirectory() as tmp:
        write_geonames(tmp, places)
        gaz = geocode.load_gazetteer(tmp, params)
    return gaz, geocode.CityFinder(gaz, params)


def city_of(gaz, finder, lat, lng):
    idx, dist = finder.find([lat], [lng])
    if idx[0] < 0:
        return None, None
    return gaz["name"].iat[idx[0]], float(dist[0])


class Photos:
    def __init__(self):
        self.rows = []

    def add(self, day, hour, spot, offset=True):
        """Add a photo at local `day` `hour`:00 (UTC-05:00); spot=None means no GPS."""
        local = datetime.fromisoformat(f"{day}T{hour:02d}:00:00")
        pid = f"p_{len(self.rows):010d}"
        if spot is not None and offset:
            spot = (spot[0] + PHOTO_OFFSET[0], spot[1] + PHOTO_OFFSET[1])
        self.rows.append({
            "photo_id": pid, "person": "tester", "file_name": SENTINEL_NAME,
            "taken_at": local.strftime("%Y-%m-%dT%H:%M:%S") + "-05:00",
            "taken_utc": (local + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "date": day,
            "lat": "" if spot is None else f"{spot[0]:.6f}",
            "lng": "" if spot is None else f"{spot[1]:.6f}",
            "has_gps": "false" if spot is None else "true",
        })
        return pid

    def frame(self):
        return pd.DataFrame(self.rows, columns=segment_clean_columns())


def segment_clean_columns():
    return ["photo_id", "person", "file_name", "taken_at", "taken_utc", "date", "lat", "lng",
            "has_gps"]


TRIP_COLUMNS = segment.TRIP_COLUMNS


def trip_row(trip_id, start, end, photo_count, cities=""):
    return {"person": "tester", "trip_id": trip_id, "start_date": start, "end_date": end,
            "days": 3, "max_distance_km": 120, "photo_count": photo_count, "n_stays": 2,
            "cities": cities}


class World:
    """A complete synthetic repo root with photos, trips for several radii and homes."""

    PLACES = [
        place(1, "Alpha", *ALPHA, pop=500000, admin1="MA"),
        place(2, "Beta", *BETA, pop=400000, admin1="NY"),
        place(3, "Gamma", *GAMMA, pop=300000, admin1="CA"),
        place(4, "Delta", *DELTA, pop=200000, admin1="TX"),
        place(5, "São Paulo", *SAO, pop=12000000, cc="BR", admin1="27", ascii_name="Sao Paulo"),
    ]

    def __init__(self, root, radii=None, default=True):
        self.root = Path(root)
        photos = Photos()
        link = []  # (photo_id, trip_id)

        def visit(trip, day, hour, spot):
            link.append((photos.add(day, hour, spot), trip))

        # T1: file order is NOT time order; Beta is visited first, Alpha has the most photos,
        # Gamma (2 photos) is dropped by min_city_photos. A no-GPS photo is ignored.
        for hour in (9, 10, 11, 12):
            visit("trip_20240103", f"2024-01-0{hour - 6}", hour, ALPHA)   # 01-03..01-06
        visit("trip_20240103", "2024-01-06", 20, GAMMA)
        visit("trip_20240103", "2024-01-07", 8, GAMMA)
        visit("trip_20240103", "2024-01-03", 7, None)
        for hour in (9, 10, 11):
            visit("trip_20240103", f"2024-01-0{hour - 8}", hour, BETA)    # 01-01..01-03
        # T2: only city has one photo -> kept.
        visit("trip_20240110", "2024-01-10", 9, DELTA)
        # T3: two cities with 2 photos each -> only the main (earliest first visit) is kept.
        for day in ("2024-01-20", "2024-01-21"):
            visit("trip_20240120", day, 9, ALPHA)
        for day in ("2024-01-22", "2024-01-23"):
            visit("trip_20240120", day, 9, BETA)
        # T4: tie on photo count among kept cities -> title is the earliest first visit.
        for day in ("2024-02-01", "2024-02-02", "2024-02-03"):
            visit("trip_20240201", day, 9, GAMMA)
        for day in ("2024-02-04", "2024-02-05", "2024-02-06"):
            visit("trip_20240201", day, 9, DELTA)
        # T5: no GPS photo with a city at all.
        visit("trip_20240301", "2024-03-01", 9, None)
        visit("trip_20240301", "2024-03-02", 9, (40.0, 40.0))  # nothing within 50 km
        # T6: accented name and a non-US country.
        for day in ("2024-04-01", "2024-04-02", "2024-04-03"):
            visit("trip_20240401", day, 9, SAO)
        # Photos outside any trip, and one far from every town.
        photos.add("2024-05-01", 9, ALPHA)
        self.photos = photos.frame()
        self.link = link

        self.trip_ids = ["trip_20240103", "trip_20240110", "trip_20240120", "trip_20240201",
                         "trip_20240301", "trip_20240401"]
        trips = [trip_row("trip_20240103", "2024-01-01", "2024-01-07", 9, "stale"),
                 trip_row("trip_20240110", "2024-01-10", "2024-01-10", 1),
                 trip_row("trip_20240120", "2024-01-20", "2024-01-23", 4),
                 trip_row("trip_20240201", "2024-02-01", "2024-02-06", 6),
                 trip_row("trip_20240301", "2024-03-01", "2024-03-02", 2),
                 trip_row("trip_20240401", "2024-04-01", "2024-04-03", 3)]
        self.trips = pd.DataFrame(trips, columns=TRIP_COLUMNS)
        self.photo_trips = pd.DataFrame(link, columns=["photo_id", "trip_id"])

        write_geonames(self.root, self.PLACES)
        processed = self.root / "data" / "processed"
        processed.mkdir(parents=True, exist_ok=True)
        self.photos.to_csv(processed / "photos_clean.csv", index=False)
        pd.DataFrame([
            {"from_date": "2024-01-01", "to_date": "2024-03-31",
             "lat": f"{HOME_POINT[0]:.6f}", "lng": f"{HOME_POINT[1]:.6f}"},
            {"from_date": "2024-04-01", "to_date": "2024-05-31",
             "lat": f"{FAR_HOME_POINT[0]:.6f}", "lng": f"{FAR_HOME_POINT[1]:.6f}"},
        ]).to_csv(processed / "homes.csv", index=False)
        suffixes = [f"_r{r}" for r in (segment.RADIUS_OPTIONS_KM if radii is None else radii)]
        if default:
            suffixes.insert(0, "")
        for suffix in suffixes:
            self.trips.to_csv(processed / f"trips_pred{suffix}.csv", index=False)
            self.photo_trips.to_csv(processed / f"photo_trips{suffix}.csv", index=False)

    def read(self, name):
        return pd.read_csv(self.root / "data" / "processed" / name, dtype=str,
                           keep_default_na=False, encoding="utf-8")

    def raw(self, name):
        return (self.root / "data" / "processed" / name).read_bytes()


def run_main(root, argv=None):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        geocode.main([] if argv is None else argv, root=root)
    return buffer.getvalue()


class ParamsTests(unittest.TestCase):
    def test_defaults_and_override(self):
        params = geocode.resolve_params({"max_city_km": 10.0})
        self.assertEqual(params["max_city_km"], 10.0)
        self.assertEqual(params["prefer_radius_km"], 15.0)
        self.assertEqual(params["min_city_photos"], 3)
        self.assertEqual(params["exclude_feature_codes"], ["PPLX", "PPLH", "PPLQ", "PPLW"])

    def test_defaults_are_not_mutated(self):
        params = geocode.resolve_params({"max_city_km": 10.0})
        params["exclude_feature_codes"].append("PPL")
        self.assertEqual(geocode.DEFAULT_PARAMS["exclude_feature_codes"],
                         ["PPLX", "PPLH", "PPLQ", "PPLW"])
        self.assertEqual(geocode.DEFAULT_PARAMS["max_city_km"], 50.0)

    def test_unknown_key_raises(self):
        with self.assertRaises(ValueError):
            geocode.resolve_params({"nope": 1})


class CityLookupTests(unittest.TestCase):
    def test_excluded_feature_codes_are_never_chosen(self):
        origin = (10.0, 20.0)
        places = [place(1, "District", north(10.0, 1), 20.0, pop=900000, code="PPLX"),
                  place(2, "Old Town", north(10.0, 2), 20.0, pop=900000, code="PPLH"),
                  place(3, "Ghost", north(10.0, 3), 20.0, pop=900000, code="PPLQ"),
                  place(4, "Drowned", north(10.0, 4), 20.0, pop=900000, code="PPLW"),
                  place(5, "Main City", north(10.0, 9), 20.0, pop=1000, code="PPLA")]
        gaz, finder = gazetteer_for(places)
        self.assertEqual(list(gaz["name"]), ["Main City"])
        name, dist = city_of(gaz, finder, *origin)
        self.assertEqual(name, "Main City")
        self.assertAlmostEqual(dist, 9.0, places=2)

    def test_prefers_big_city_within_radius_over_nearer_suburb(self):
        places = [place(1, "Suburb", north(10.0, 2), 20.0, pop=20000),
                  place(2, "Big City", north(10.0, -10), 20.0, pop=2000000)]
        gaz, finder = gazetteer_for(places)
        name, dist = city_of(gaz, finder, 10.0, 20.0)
        self.assertEqual(name, "Big City")
        self.assertAlmostEqual(dist, 10.0, places=2)  # distance to the CHOSEN centre

    def test_big_city_outside_prefer_radius_loses_to_close_suburb(self):
        places = [place(1, "Suburb", north(10.0, 2), 20.0, pop=20000),
                  place(2, "Big City", north(10.0, -20), 20.0, pop=2000000)]
        gaz, finder = gazetteer_for(places)
        name, dist = city_of(gaz, finder, 10.0, 20.0)
        self.assertEqual(name, "Suburb")
        self.assertAlmostEqual(dist, 2.0, places=2)

    def test_population_tie_goes_to_nearest_then_smallest_id(self):
        places = [place(30, "Far Twin", north(10.0, 8), 20.0, pop=50000),
                  place(20, "Near Twin", north(10.0, -3), 20.0, pop=50000)]
        gaz, finder = gazetteer_for(places)
        self.assertEqual(city_of(gaz, finder, 10.0, 20.0)[0], "Near Twin")
        same = [place(30, "Id Thirty", north(10.0, 5), 20.0, pop=50000),
                place(20, "Id Twenty", north(10.0, -5), 20.0, pop=50000)]
        gaz, finder = gazetteer_for(same)
        self.assertEqual(city_of(gaz, finder, 10.0, 20.0)[0], "Id Twenty")

    def test_max_city_km(self):
        places = [place(1, "Lonely", north(10.0, 40), 20.0, pop=1000)]
        gaz, finder = gazetteer_for(places)
        name, dist = city_of(gaz, finder, 10.0, 20.0)   # 40 km: nearest city is used
        self.assertEqual(name, "Lonely")
        self.assertAlmostEqual(dist, 40.0, places=2)
        far = [place(1, "Lonely", north(10.0, 80), 20.0, pop=1000)]
        gaz, finder = gazetteer_for(far)
        self.assertEqual(city_of(gaz, finder, 10.0, 20.0), (None, None))   # 80 km: no city

    def test_params_change_the_rule(self):
        places = [place(1, "Suburb", north(10.0, 2), 20.0, pop=20000),
                  place(2, "Big City", north(10.0, -10), 20.0, pop=2000000)]
        gaz, finder = gazetteer_for(places, prefer_radius_km=5.0)
        self.assertEqual(city_of(gaz, finder, 10.0, 20.0)[0], "Suburb")


class CityIdTests(unittest.TestCase):
    def ids(self, places):
        gaz, _ = gazetteer_for(places)
        return dict(zip(gaz["geonameid"], gaz["city_id"]))

    def test_slug_and_accents(self):
        ids = self.ids([place(1, "New York City", 40.7, -74.0, cc="US", admin1="NY"),
                        place(2, "São Paulo", -23.5, -46.6, cc="BR", admin1="27",
                              ascii_name="Sao Paulo"),
                        place(3, "Saint-Étienne d'Or", 45.4, 4.4, cc="FR", admin1="84",
                              ascii_name="Saint-Etienne d'Or")])
        self.assertEqual(ids["1"], "city_newyorkcity_us")
        self.assertEqual(ids["2"], "city_saopaulo_br")
        self.assertEqual(ids["3"], "city_saintetiennedor_fr")

    def test_same_name_in_different_countries_is_not_a_collision(self):
        ids = self.ids([place(1, "Salem", 44.9, -123.0, cc="US", admin1="OR"),
                        place(2, "Salem", 11.6, 78.1, cc="IN", admin1="25")])
        self.assertEqual(ids, {"1": "city_salem_us", "2": "city_salem_in"})

    def test_collision_adds_admin1_to_all(self):
        ids = self.ids([place(1, "Springfield", 42.1, -72.5, admin1="MA"),
                        place(2, "Springfield", 39.8, -89.6, admin1="IL"),
                        place(3, "Springfield", 37.2, -93.3, admin1="MO"),
                        place(4, "Boston", 42.3, -71.0, admin1="MA")])
        self.assertEqual(ids, {"1": "city_springfield_us_ma", "2": "city_springfield_us_il",
                               "3": "city_springfield_us_mo", "4": "city_boston_us"})

    def test_admin1_collision_adds_geonameid_to_all_still_colliding(self):
        ids = self.ids([place(11, "Salem", 44.9, -123.0, admin1="OR"),
                        place(12, "Salem", 44.0, -122.0, admin1="OR"),
                        place(13, "Salem", 42.5, -71.0, admin1="MA")])
        self.assertEqual(ids, {"11": "city_salem_us_or_11", "12": "city_salem_us_or_12",
                               "13": "city_salem_us_ma"})

    def test_ids_are_unique(self):
        gaz, _ = gazetteer_for(World.PLACES + [place(9, "Alpha", 5.0, 5.0, admin1="MA")])
        self.assertEqual(len(set(gaz["city_id"])), len(gaz))

    def test_excluded_places_do_not_cause_collisions(self):
        ids = self.ids([place(1, "Springfield", 42.1, -72.5, admin1="MA"),
                        place(2, "Springfield", 42.2, -72.6, admin1="MA", code="PPLX")])
        self.assertEqual(ids, {"1": "city_springfield_us"})


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.world = World(self._tmp.name)
        self.stdout = run_main(self._tmp.name)

    def test_photo_cities(self):
        table = self.world.read("photo_cities.csv")
        self.assertEqual(list(table.columns), ["photo_id", "city_id", "distance_km"])
        gps = self.world.photos[self.world.photos["has_gps"] == "true"]
        self.assertEqual(list(table["photo_id"]), list(gps["photo_id"]))  # photos_clean order
        by_id = table.set_index("photo_id")
        alpha_photo = self.world.photos[self.world.photos["date"] == "2024-05-01"]["photo_id"].iat[0]
        self.assertEqual(by_id.loc[alpha_photo, "city_id"], "city_alpha_us")
        self.assertEqual(by_id.loc[alpha_photo, "distance_km"], "0.2")
        lost = self.world.photos[self.world.photos["lat"] == "40.001234"]["photo_id"].iat[0]
        self.assertEqual(by_id.loc[lost, "city_id"], "")
        self.assertEqual(by_id.loc[lost, "distance_km"], "")

    def test_trip_cities_columns_and_values(self):
        table = self.world.read("trip_cities.csv")
        self.assertEqual(list(table.columns), geocode.TRIP_CITY_COLUMNS)
        rows = [tuple(r) for r in table[["trip_id", "name", "arrive", "leave",
                                          "photo_count"]].itertuples(index=False)]
        self.assertEqual(rows, [
            # T1: Alpha (home city) dropped, Gamma (2 photos) below min_city_photos.
            ("trip_20240103", "Beta", "2024-01-01", "2024-01-03", "3"),
            ("trip_20240110", "Delta", "2024-01-10", "2024-01-10", "1"),
            # T3: Alpha dropped; Beta (2 photos) is the main outside city.
            ("trip_20240120", "Beta", "2024-01-22", "2024-01-23", "2"),
            ("trip_20240201", "Gamma", "2024-02-01", "2024-02-03", "3"),
            ("trip_20240201", "Delta", "2024-02-04", "2024-02-06", "3"),
            # T5: no city near the only photo -> nearest place at any distance.
            ("trip_20240301", "São Paulo", "2024-03-02", "2024-03-02", "1"),
            ("trip_20240401", "São Paulo", "2024-04-01", "2024-04-03", "3"),
        ])
        first = table.iloc[0]
        self.assertEqual((first["city_id"], first["country"], first["country_code"],
                          first["lat"], first["lng"]),
                         ("city_beta_us", "United States", "US", "1.0000", "0.0000"))
        last = table.iloc[-1]
        self.assertEqual((last["city_id"], last["country"], last["country_code"],
                          last["lat"], last["lng"]),
                         ("city_saopaulo_br", "Brazil", "BR", "4.0000", "0.0000"))

    def test_trips_pred_rewritten_with_cities_and_title(self):
        trips = self.world.read("trips_pred.csv")
        original = self.world.trips.astype(str)
        self.assertEqual(list(trips.columns), TRIP_COLUMNS + ["title"])
        for column in TRIP_COLUMNS:
            if column != "cities":
                self.assertEqual(list(trips[column]), list(original[column]), column)
        self.assertEqual(list(trips["cities"]),
                         ["Beta", "Delta", "Beta", "Gamma;Delta", "São Paulo", "São Paulo"])
        self.assertEqual(list(trips["title"]),
                         ["Beta", "Delta", "Beta", "Gamma", "Near São Paulo", "São Paulo"])
        self.assertEqual(list(trips["trip_id"]), self.world.trip_ids)

    def test_rerun_is_idempotent(self):
        before = {name: self.world.raw(name) for name in
                  ("trips_pred.csv", "trip_cities.csv", "photo_cities.csv", "homes_city.csv",
                   "trips_pred_r10.csv", "trip_cities_r10.csv")}
        again = run_main(self._tmp.name)
        self.assertEqual(again, self.stdout)
        for name, content in before.items():
            self.assertEqual(self.world.raw(name), content, name)
        self.assertEqual(list(self.world.read("trips_pred.csv").columns).count("title"), 1)

    def test_every_radius_pair_and_the_default_pair_are_written(self):
        for radius in segment.RADIUS_OPTIONS_KM:
            trips = self.world.read(f"trips_pred_r{radius}.csv")
            self.assertEqual(list(trips.columns), TRIP_COLUMNS + ["title"])
            # Beta is ~111 km from the home city: inside the 200 km circle, outside the others.
            expected = (["Gamma", "Delta", "Alpha", "Gamma", "Near São Paulo", "São Paulo"]
                        if radius == 200 else
                        ["Beta", "Delta", "Beta", "Gamma", "Near São Paulo", "São Paulo"])
            self.assertEqual(list(trips["title"]), expected, radius)
            cities = self.world.read(f"trip_cities_r{radius}.csv")
            self.assertEqual(list(cities.columns), geocode.TRIP_CITY_COLUMNS)
            self.assertEqual(len(cities), 7)
        self.assertTrue((Path(self._tmp.name) / "data/processed/trip_cities.csv").exists())

    def test_console_shape_and_privacy(self):
        gps = int((self.world.photos["has_gps"] == "true").sum())
        with_city = gps - 1
        expected = "\n".join([
            f"GPS photos with a city: {with_city} of {gps}",
            "Radii geocoded: 10, 25, 50, 100, 200 (+ default)",
            "Trips at default radius (50 km): 6",
            "  2024-01-01 -> 2024-01-07  Beta (US)",
            "  2024-01-10 -> 2024-01-10  Delta (US)",
            "  2024-01-20 -> 2024-01-23  Beta (US)",
            "  2024-02-01 -> 2024-02-06  Gamma (US); Delta (US)",
            "  2024-03-01 -> 2024-03-02  Near São Paulo (BR)",
            "  2024-04-01 -> 2024-04-03  São Paulo (BR)",
            "Home cities:",
            "  2024-01-01 -> 2024-03-31  Alpha (US)",
            "  2024-04-01 -> 2024-05-31  no city",
        ]) + "\n"
        self.assertEqual(self.stdout, expected)
        for sentinel in ("0.001234", "0.000567", "1.001234", "40.001234", SENTINEL_NAME,
                         "0.012345", "0.023456", "50.123456"):
            self.assertNotIn(sentinel, self.stdout)


class MissingRadiusTests(unittest.TestCase):
    def test_missing_radius_is_skipped_and_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp, radii=[10, 50, 200], default=True)
            # r25 has only one of its two files: still counts as missing.
            (Path(tmp) / "data/processed/trips_pred_r25.csv").write_text("x", encoding="utf-8")
            out = run_main(tmp)
            lines = out.splitlines()
            self.assertEqual(lines[1], "Radii geocoded: 10, 50, 200 (+ default)")
            self.assertEqual(lines[2], "Radii skipped (files missing): 25, 100")
            self.assertTrue((Path(tmp) / "data/processed/trip_cities_r50.csv").exists())
            self.assertFalse((Path(tmp) / "data/processed/trip_cities_r25.csv").exists())
            self.assertFalse((Path(tmp) / "data/processed/trip_cities_r100.csv").exists())
            self.assertEqual(world.read("trips_pred_r25.csv").columns.tolist(), ["x"])

    def test_missing_default_pair_falls_back_to_default_radius_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            World(tmp, default=False)
            lines = run_main(tmp).splitlines()
            self.assertEqual(lines[1], "Radii geocoded: 10, 25, 50, 100, 200")
            self.assertEqual(lines[2], "Radii skipped (files missing): default")
            self.assertEqual(lines[3], "Trips at default radius (50 km): 6")


class HomeTests(unittest.TestCase):
    def test_homes_city_uses_centre_and_never_the_home_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            out = run_main(tmp)
            homes = world.read("homes_city.csv")
            self.assertEqual(list(homes.columns), geocode.HOME_CITY_COLUMNS)
            self.assertEqual(homes.iloc[0].tolist(),
                             ["2024-01-01", "2024-03-31", "city_alpha_us", "Alpha", "US",
                              "0.0000", "0.0000"])
            self.assertEqual(homes.iloc[1].tolist(),
                             ["2024-04-01", "2024-05-31", "", "", "", "", ""])
            text = world.raw("homes_city.csv").decode("utf-8") + out
            for sentinel in ("0.012345", "0.023456", "50.123456", "50.654321"):
                self.assertNotIn(sentinel, text)

    def test_home_uses_the_populous_city_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            places = World.PLACES + [place(6, "Suburb", north(0.0, 2.6), 0.0, pop=1000)]
            write_geonames(tmp, places)   # Suburb is nearer to the home point than Alpha
            run_main(tmp)
            self.assertEqual(world.read("homes_city.csv")["name"].tolist(), ["Alpha", ""])


class ErrorTests(unittest.TestCase):
    def run_failing(self, root):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), self.assertRaises(SystemExit) as raised:
            geocode.main([], root=root)
        return buffer.getvalue(), raised.exception.code

    def test_missing_geonames_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            World(tmp)
            for name in ("cities5000.txt", "countryInfo.txt"):
                path = Path(tmp) / "data" / "geonames" / name
                path.rename(path.with_suffix(".bak"))
                out, code = self.run_failing(tmp)
                self.assertEqual(out, "error: GeoNames files not found in data/geonames/\n")
                self.assertEqual(code, 1)
                path.with_suffix(".bak").rename(path)

    def test_missing_photos_and_homes(self):
        with tempfile.TemporaryDirectory() as tmp:
            World(tmp)
            (Path(tmp) / "data/processed/photos_clean.csv").unlink()
            out, code = self.run_failing(tmp)
            self.assertEqual(out, "error: could not read data/processed/photos_clean.csv\n")
            self.assertEqual(code, 1)
        with tempfile.TemporaryDirectory() as tmp:
            World(tmp)
            (Path(tmp) / "data/processed/homes.csv").unlink()
            out, code = self.run_failing(tmp)
            self.assertEqual(out, "error: could not read data/processed/homes.csv\n")
            self.assertEqual(code, 1)

    def test_unexpected_exception_is_one_generic_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            World(tmp)
            (Path(tmp) / "data/processed/trips_pred.csv").write_text("", encoding="utf-8")
            out, code = self.run_failing(tmp)
            self.assertEqual(out, "error: geocoding failed\n")
            self.assertEqual(code, 1)


class CliTests(unittest.TestCase):
    def test_cli_flags_change_the_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            world = World(tmp)
            run_main(tmp, ["--min_city_photos", "1"])
            trips = world.read("trips_pred.csv")
            self.assertEqual(trips["cities"].tolist()[0], "Beta;Gamma")
            run_main(tmp, ["--min_city_photos", "3", "--max_city_km", "1"])
            self.assertEqual(world.read("trips_pred.csv")["cities"].tolist()[0], "Beta")


# --- home-area filtering (task 6b): a straight line of towns north of an invented home ---------

MINI_HOME = (0.004321, 0.005678)        # sentinel strings: must never be written or printed
MINI_PHOTO_SENTINEL = (north(0.0, -120), 0.012346)
HOMEVILLE = (north(0.0, 12), 0.0)       # the home city (home point is ~11.5 km from it)
SUBURB = (north(0.0, 30), 0.0)
JUSTIN = (north(0.0, 46), 0.0)          # inside a 50 km circle
JUSTOUT = (north(0.0, 63), 0.0)         # outside a 50 km circle, inside 100 km
FARTON = (north(0.0, 130), 0.0)
SOUTHPORT = (north(0.0, -200), 0.0)
EDGE = (north(0.0, 45), 0.0)
MINI_PLACES = [
    place(1, "Homeville", *HOMEVILLE, pop=1000000),
    place(2, "Suburb", *SUBURB, pop=50000),
    place(3, "Justin", *JUSTIN, pop=80000),
    place(4, "Justout", *JUSTOUT, pop=100000),
    place(5, "Farton", *FARTON, pop=300000),
    place(6, "Southport", *SOUTHPORT, pop=20000),
]
ONE_HOME = [("2024-01-01", "2024-12-31", MINI_HOME)]


def day(n):
    return f"2024-03-{n:02d}"


def build_mini(tmp, visits, trips, homes=None, places=None, radii=(None,)):
    """Write a repo root. visits: [(trip_id, day, spot)], trips: [(trip_id, start, end)]."""
    root = Path(tmp)
    write_geonames(root, MINI_PLACES if places is None else places)
    photos = Photos()
    link = []
    for trip_id, when, spot in visits:
        link.append((photos.add(when, 9, spot, offset=False), trip_id))
    processed = root / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    photos.frame().to_csv(processed / "photos_clean.csv", index=False)
    rows = [{"from_date": a, "to_date": b, "lat": f"{pt[0]:.6f}", "lng": f"{pt[1]:.6f}"}
            for a, b, pt in (ONE_HOME if homes is None else homes)]
    pd.DataFrame(rows).to_csv(processed / "homes.csv", index=False)
    trips_df = pd.DataFrame([trip_row(t, a, b, sum(1 for v in visits if v[0] == t))
                             for t, a, b in trips], columns=TRIP_COLUMNS)
    for radius in radii:
        suffix = "" if radius is None else f"_r{radius}"
        trips_df.to_csv(processed / f"trips_pred{suffix}.csv", index=False)
        pd.DataFrame(link, columns=["photo_id", "trip_id"]).to_csv(
            processed / f"photo_trips{suffix}.csv", index=False)
    return root


def read_processed(root, name):
    return pd.read_csv(Path(root) / "data" / "processed" / name, dtype=str,
                       keep_default_na=False, encoding="utf-8")


class HomeAreaTests(unittest.TestCase):
    TRIP = "trip_20240301"

    def visits_all(self):
        out = [(self.TRIP, day(1), HOMEVILLE), (self.TRIP, day(1), HOMEVILLE)]
        for n, spot in ((2, SUBURB), (3, SUBURB), (4, SUBURB),
                        (5, JUSTIN), (6, JUSTIN), (7, JUSTIN),
                        (8, JUSTOUT), (9, JUSTOUT), (10, JUSTOUT),
                        (11, FARTON), (12, FARTON), (13, FARTON)):
            out.append((self.TRIP, day(n), spot))
        return out

    def test_home_city_and_inside_cities_dropped_and_radius_dependence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_mini(tmp, self.visits_all(), [(self.TRIP, day(1), day(13))],
                              radii=(None, 10, 50))
            run_main(tmp)
            for suffix, cities, title in (
                    ("", "Justout;Farton", "Justout"),      # default pair = 50 km
                    ("_r50", "Justout;Farton", "Justout"),
                    ("_r10", "Suburb;Justin;Justout;Farton", "Suburb")):
                trips = read_processed(root, f"trips_pred{suffix}.csv")
                self.assertEqual((trips["cities"].iat[0], trips["title"].iat[0]), (cities, title),
                                 suffix)
            # Justin (46 km) is inside 50 km, Justout (63 km) just outside; counts and dates.
            rows = read_processed(root, "trip_cities.csv")
            self.assertEqual(rows[["name", "arrive", "leave", "photo_count"]].values.tolist(),
                             [["Justout", day(8), day(10), "3"], ["Farton", day(11), day(13), "3"]])
            small = read_processed(root, "trip_cities_r10.csv")
            self.assertEqual(small["name"].tolist(), ["Suburb", "Justin", "Justout", "Farton"])

    def test_default_pair_uses_default_radius(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_mini(tmp, self.visits_all(), [(self.TRIP, day(1), day(13))],
                              radii=(None, 25, 50))
            run_main(tmp)
            default = read_processed(root, "trips_pred.csv")
            self.assertEqual(segment.DEFAULT_RADIUS_KM, 50)
            self.assertEqual(default.to_csv(index=False),
                             read_processed(root, "trips_pred_r50.csv").to_csv(index=False))
            self.assertEqual(read_processed(root, "trips_pred_r25.csv")["cities"].iat[0],
                             "Suburb;Justin;Justout;Farton")
            self.assertEqual(default["cities"].iat[0], "Justout;Farton")

    def test_fallback_main_outside_city_when_all_are_below_min_photos(self):
        visits = [(self.TRIP, day(n), HOMEVILLE) for n in (1, 2, 3, 4, 5)]
        visits += [(self.TRIP, day(6), JUSTOUT), (self.TRIP, day(7), FARTON),
                   (self.TRIP, day(8), FARTON)]
        with tempfile.TemporaryDirectory() as tmp:
            root = build_mini(tmp, visits, [(self.TRIP, day(1), day(8))])
            run_main(tmp)
            trips = read_processed(root, "trips_pred.csv")
            self.assertEqual((trips["cities"].iat[0], trips["title"].iat[0]), ("Farton", "Farton"))
            rows = read_processed(root, "trip_cities.csv")
            self.assertEqual(rows[["name", "arrive", "leave", "photo_count"]].values.tolist(),
                             [["Farton", day(7), day(8), "2"]])

    def test_fallback_near_nearest_city_to_farthest_outside_photo(self):
        # Outside photos have no city within max_city_km; the farthest one decides.
        visits = [(self.TRIP, day(1), HOMEVILLE), (self.TRIP, day(2), HOMEVILLE),
                  (self.TRIP, day(3), (north(0.0, -80), 0.0)),     # nearest place: Homeville
                  (self.TRIP, day(4), MINI_PHOTO_SENTINEL)]        # farthest: nearest = Southport
        with tempfile.TemporaryDirectory() as tmp:
            root = build_mini(tmp, visits, [(self.TRIP, day(1), day(4))])
            out = run_main(tmp)
            trips = read_processed(root, "trips_pred.csv")
            self.assertEqual((trips["cities"].iat[0], trips["title"].iat[0]),
                             ("Southport", "Near Southport"))
            rows = read_processed(root, "trip_cities.csv")
            self.assertEqual(rows.iloc[0].tolist(),
                             [self.TRIP, "city_southport_us", "Southport", "United States", "US",
                              f"{SOUTHPORT[0]:.4f}", "0.0000", day(3), day(4), "2"])
            self.assertIn(f"  {day(1)} -> {day(4)}  Near Southport (US)\n", out)

    def test_fallback_near_when_outside_photos_only_map_to_inside_cities(self):
        places = [place(1, "Homeville", *HOMEVILLE, pop=1000000),
                  place(2, "Edge", *EDGE, pop=200000)]
        outside = north(0.0, 52)    # ~51.5 km from home: outside, yet its city (Edge) is inside
        visits = [(self.TRIP, day(1), HOMEVILLE), (self.TRIP, day(2), (outside, 0.0)),
                  (self.TRIP, day(3), (outside, 0.0)), (self.TRIP, day(4), (north(0.0, 49), 0.0))]
        with tempfile.TemporaryDirectory() as tmp:
            root = build_mini(tmp, visits, [(self.TRIP, day(1), day(4))], places=places)
            run_main(tmp)
            trips = read_processed(root, "trips_pred.csv")
            self.assertEqual((trips["cities"].iat[0], trips["title"].iat[0]),
                             ("Edge", "Near Edge"))
            rows = read_processed(root, "trip_cities.csv")
            self.assertEqual(rows[["name", "arrive", "leave", "photo_count"]].values.tolist(),
                             [["Edge", day(2), day(3), "2"]])

    def test_fallback_home_city_when_nothing_is_outside(self):
        visits = [(self.TRIP, day(1), HOMEVILLE), (self.TRIP, day(2), HOMEVILLE),
                  (self.TRIP, day(3), SUBURB), (self.TRIP, day(4), JUSTIN),
                  ("trip_20240320", day(20), None)]
        trips = [(self.TRIP, day(1), day(4)), ("trip_20240320", day(20), day(21)),
                 ("trip_20240325", day(25), day(26))]
        with tempfile.TemporaryDirectory() as tmp:
            root = build_mini(tmp, visits, trips)
            run_main(tmp)
            table = read_processed(root, "trips_pred.csv")
            self.assertEqual(table["cities"].tolist(), ["Homeville", "Homeville", "Homeville"])
            self.assertEqual(table["title"].tolist(), ["Homeville", "Homeville", "Homeville"])
            rows = read_processed(root, "trip_cities.csv")
            self.assertEqual(rows[["trip_id", "arrive", "leave", "photo_count"]].values.tolist(),
                             [[self.TRIP, day(1), day(2), "2"],
                              ["trip_20240320", day(20), day(21), "0"],
                              ["trip_20240325", day(25), day(26), "0"]])

    def test_no_city_at_all_when_home_has_no_city_and_nothing_is_outside(self):
        far_home = [("2024-01-01", "2024-12-31", (60.123456, 60.654321))]
        visits = [(self.TRIP, day(1), (60.123456, 60.654321))]
        with tempfile.TemporaryDirectory() as tmp:
            root = build_mini(tmp, visits, [(self.TRIP, day(1), day(2))], homes=far_home)
            out = run_main(tmp)
            table = read_processed(root, "trips_pred.csv")
            self.assertEqual((table["cities"].iat[0], table["title"].iat[0]), ("", ""))
            self.assertEqual(len(read_processed(root, "trip_cities.csv")), 0)
            self.assertIn(f"  {day(1)} -> {day(2)}  no city\n", out)

    def test_each_trip_uses_its_own_home_period(self):
        other = (north(0.0, 130), 0.003456)                    # home point next to Farton
        homes = [("2024-01-01", "2024-03-15", MINI_HOME), ("2024-03-16", "2024-12-31", other)]
        visits = [("trip_a", day(1), FARTON), ("trip_a", day(2), FARTON),
                  ("trip_a", day(3), FARTON), ("trip_a", day(4), HOMEVILLE),
                  ("trip_a", day(5), HOMEVILLE), ("trip_a", day(6), HOMEVILLE),
                  ("trip_b", day(20), FARTON), ("trip_b", day(21), FARTON),
                  ("trip_b", day(22), FARTON), ("trip_b", day(23), HOMEVILLE),
                  ("trip_b", day(24), HOMEVILLE), ("trip_b", day(25), HOMEVILLE)]
        trips = [("trip_a", day(1), day(6)), ("trip_b", day(20), day(25))]
        with tempfile.TemporaryDirectory() as tmp:
            root = build_mini(tmp, visits, trips, homes=homes)
            run_main(tmp)
            table = read_processed(root, "trips_pred.csv")
            self.assertEqual(table["cities"].tolist(), ["Farton", "Homeville"])
            self.assertEqual(table["title"].tolist(), ["Farton", "Homeville"])
            homes_city = read_processed(root, "homes_city.csv")
            self.assertEqual(homes_city["name"].tolist(), ["Homeville", "Farton"])

    def test_trip_without_home_period_is_not_filtered_and_is_counted(self):
        homes = [("2024-03-10", "2024-12-31", MINI_HOME)]       # March 1-9 has no home period
        visits = [("trip_a", day(1), HOMEVILLE), ("trip_a", day(2), HOMEVILLE),
                  ("trip_a", day(3), HOMEVILLE), ("trip_a", day(4), FARTON),
                  ("trip_a", day(5), FARTON), ("trip_a", day(6), FARTON)]
        with tempfile.TemporaryDirectory() as tmp:
            root = build_mini(tmp, visits, [("trip_a", day(1), day(6))], homes=homes)
            out = run_main(tmp)
            table = read_processed(root, "trips_pred.csv")
            self.assertEqual((table["cities"].iat[0], table["title"].iat[0]),
                             ("Homeville;Farton", "Homeville"))
            self.assertIn("Trips without a home period (not filtered): 1\n", out)
            self.assertIn("  2024-03-01 -> 2024-03-06  Homeville (US); Farton (US)\n", out)

    def test_privacy_no_home_point_or_photo_coordinates_anywhere(self):
        visits = self.visits_all() + [(self.TRIP, day(14), MINI_PHOTO_SENTINEL)]
        with tempfile.TemporaryDirectory() as tmp:
            build_mini(tmp, visits, [(self.TRIP, day(1), day(14))], radii=(None, 10, 50))
            out = run_main(tmp)
            texts = [out]
            for name in ("trips_pred.csv", "trips_pred_r10.csv", "trip_cities.csv",
                         "trip_cities_r10.csv", "homes_city.csv", "photo_cities.csv"):
                texts.append((Path(tmp) / "data" / "processed" / name).read_text(encoding="utf-8"))
            for text in texts:
                for sentinel in ("0.004321", "0.005678", "0.012346"):
                    self.assertNotIn(sentinel, text)


if __name__ == "__main__":
    unittest.main()
