"""Offline reverse geocoding: GeoNames city names for photos, trips (every radius) and homes.

Pipeline order (run from the repo root, after the photos are cleaned):
  1. python backend/segment.py --all-radii    -> trips_pred_r{R}.csv, photo_trips_r{R}.csv, homes.csv
  2. python backend/segment.py                -> trips_pred.csv, photo_trips.csv (default radius)
  3. python backend/geocode.py                -> city names (this script)
segment.py rewrites trips_pred*.csv WITHOUT cities and title, so geocode.py must run after it.

Reads (git-ignored, local only):
  data/geonames/cities5000.txt, data/geonames/countryInfo.txt   (GeoNames, no network access)
  data/processed/photos_clean.csv, homes.csv
  data/processed/trips_pred[_r{R}].csv, photo_trips[_r{R}].csv  for the default pair and every
  R in segment.RADIUS_OPTIONS_KM; a pair with a missing file is skipped and reported.
Writes under data/processed/:
  photo_cities.csv         photo_id, city_id, distance_km for every GPS photo
  trip_cities[_r{R}].csv   trip_id, city_id, name, country, country_code, lat, lng, arrive, leave,
                           photo_count (lat/lng = GeoNames city centre)
  trips_pred[_r{R}].csv    rewritten in place: `cities` = kept city names joined by ";" in visit
                           order, and a `title` column (main city name) appended; idempotent
  homes_city.csv           from_date, to_date, city_id, name, country_code, lat, lng (city centre
                           only; the real home coordinates are never written)

Algorithm (parameters in DEFAULT_PARAMS):
  1. Gazetteer = cities5000 minus exclude_feature_codes (PPLX city sections, PPLH historical,
     PPLQ abandoned, PPLW destroyed). city_id = city_<ascii slug>_<cc>; places that share a slug
     within a country get the admin1 code appended, and still-colliding ones the geonameid.
  2. City of a point: among places within prefer_radius_km pick the most populous (ties: nearest,
     then smallest geonameid), so a trip is named after Chengdu and not one of its districts;
     with none, take the nearest place if it is within max_city_km, else no city.
  3. Per trip: group its GPS photos by city. Radius R of a file pair = the R in
     trips_pred_r{R}.csv; the default pair (trips_pred.csv) uses segment.DEFAULT_RADIUS_KM.
     The trip's home = the homes.csv period containing its start_date (the real point is used
     in memory only); its home city = the matching homes_city.csv row. Cities whose GeoNames
     centre is within R km of that home, and the home city itself, are dropped. Then:
       a. Keep the remaining cities with at least min_city_photos photos, in first-visit order.
          Main city = most photos, ties to the earliest first visit; title = main city name.
       b. None kept but some remain: keep only the main one (title = its name).
       c. No city remains but a photo lies more than R km from home: take the farthest such
          photo, the nearest gazetteer place at any distance (no prefer rule, no max_city_km)
          becomes the single city (photo_count = photos outside the circle) and
          title = "Near <name>"; the console shows "Near <name> (CC)".
       d. No photo outside the circle: keep the home city (title = its name).
     A trip whose start_date is in no home period is not home-filtered (a count is printed).
     arrive / leave = earliest / latest photo date in that city.

Cities are named from GeoNames (https://www.geonames.org/), licensed CC BY 4.0.
Only counts, dates, city names and country codes are printed; never coordinates or file names.

Run from the repo root:  python backend/geocode.py [--<param> value ...]
"""

import argparse
import csv
import re
import sys
from collections import namedtuple
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

from segment import (DEFAULT_RADIUS_KM, EARTH_RADIUS_KM, RADIUS_OPTIONS_KM, haversine_km,
                     prepare_photos)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Per-photo lookups: time-order rank, ISO date, gazetteer index (or -1), (lat, lng) in memory.
PhotoIndex = namedtuple("PhotoIndex", "rank date city xy")

DEFAULT_PARAMS = {
    "exclude_feature_codes": ["PPLX", "PPLH", "PPLQ", "PPLW"],
    "prefer_radius_km": 15.0,
    "max_city_km": 50.0,
    "min_city_photos": 3,
}

GEONAMES_COLUMNS = ["geonameid", "name", "asciiname", "alternatenames", "latitude", "longitude",
                    "feature_class", "feature_code", "country_code", "cc2", "admin1_code",
                    "admin2_code", "admin3_code", "admin4_code", "population", "elevation",
                    "dem", "timezone", "modification_date"]

PHOTO_CITY_COLUMNS = ["photo_id", "city_id", "distance_km"]
TRIP_CITY_COLUMNS = ["trip_id", "city_id", "name", "country", "country_code", "lat", "lng",
                     "arrive", "leave", "photo_count"]
HOME_CITY_COLUMNS = ["from_date", "to_date", "city_id", "name", "country_code", "lat", "lng"]

CITIES_REL = Path("data") / "geonames" / "cities5000.txt"
COUNTRIES_REL = Path("data") / "geonames" / "countryInfo.txt"
PHOTOS_REL = Path("data") / "processed" / "photos_clean.csv"
HOMES_REL = Path("data") / "processed" / "homes.csv"
TRIPS_REL = Path("data") / "processed" / "trips_pred.csv"
PHOTO_TRIPS_REL = Path("data") / "processed" / "photo_trips.csv"
PHOTO_CITIES_REL = Path("data") / "processed" / "photo_cities.csv"
TRIP_CITIES_REL = Path("data") / "processed" / "trip_cities.csv"
HOMES_CITY_REL = Path("data") / "processed" / "homes_city.csv"

GEONAMES_MISSING_MESSAGE = "GeoNames files not found in data/geonames/"


def resolve_params(params=None):
    """Merge a partial params dict over a copy of DEFAULT_PARAMS and validate it."""
    merged = dict(DEFAULT_PARAMS)
    if params:
        unknown = sorted(set(params) - set(DEFAULT_PARAMS))
        if unknown:
            raise ValueError("unknown parameter(s): " + ", ".join(unknown))
        merged.update(params)
    merged["exclude_feature_codes"] = list(merged["exclude_feature_codes"])  # never alias
    return merged


def with_suffix(rel, suffix):
    """data/processed/trips_pred.csv + "_r50" -> data/processed/trips_pred_r50.csv."""
    return rel.with_name(rel.stem + suffix + rel.suffix)


def slugify(text):
    """Lower-case and keep only [a-z0-9]."""
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def assign_city_ids(gaz):
    """Return the unique city_id list for a gazetteer frame (see module docstring)."""
    base = []
    for ascii_name, name, country_code in zip(gaz["asciiname"], gaz["name"], gaz["country_code"]):
        slug = slugify(ascii_name) or slugify(name) or "place"
        base.append(f"city_{slug}_{slugify(country_code)}")
    ids = pd.Series(base, index=gaz.index, dtype=object)
    # A slug shared by two or more places gets the admin1 code on ALL of them; places that
    # still collide after that get their geonameid on ALL of them. Deterministic by design.
    shared = ids.duplicated(keep=False)
    admin1 = gaz["admin1_code"].map(slugify)
    ids = ids.where(~shared, ids + admin1.map(lambda a: "_" + a if a else ""))
    shared = ids.duplicated(keep=False)
    ids = ids.where(~shared, ids + "_" + gaz["geonameid"].astype(str))
    if not ids.is_unique:
        raise ValueError("city ids are not unique")
    return ids.tolist()


def load_gazetteer(root, params):
    """Read cities5000, drop excluded feature codes and attach unique city ids."""
    raw = pd.read_csv(Path(root) / CITIES_REL, sep="\t", header=None, names=GEONAMES_COLUMNS,
                      dtype=str, quoting=csv.QUOTE_NONE, keep_default_na=False,
                      encoding="utf-8")
    gaz = raw[~raw["feature_code"].isin(params["exclude_feature_codes"])].reset_index(drop=True)
    gaz = gaz.assign(
        geonameid_int=gaz["geonameid"].astype(int),
        lat=gaz["latitude"].astype(float),
        lng=gaz["longitude"].astype(float),
        pop=[int(p) if p.strip() else 0 for p in gaz["population"]],
    )
    gaz["city_id"] = assign_city_ids(gaz)
    return gaz


def load_countries(root):
    """{ISO alpha-2: country name} from countryInfo.txt."""
    names = {}
    with open(Path(root) / COUNTRIES_REL, encoding="utf-8") as handle:
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) > 4:
                names[fields[0]] = fields[4]
    return names


class CityFinder:
    """Most populous nearby / nearest GeoNames place for points, via a haversine BallTree."""

    def __init__(self, gaz, params):
        self.gaz = gaz
        self.prefer_km = float(params["prefer_radius_km"])
        self.max_km = float(params["max_city_km"])
        self.tree = BallTree(np.radians(gaz[["lat", "lng"]].to_numpy()), metric="haversine")
        self.pop = gaz["pop"].to_numpy()
        self.geonameid = gaz["geonameid_int"].to_numpy()

    def find(self, lats, lngs):
        """Return (index into gaz or -1, distance_km to the chosen centre or nan) arrays."""
        points = np.radians(np.column_stack([np.asarray(lats, dtype=float),
                                             np.asarray(lngs, dtype=float)]))
        count = len(points)
        chosen = np.full(count, -1, dtype=int)
        dist = np.full(count, np.nan)
        if count == 0:
            return chosen, dist
        near_idx, near_dist = self.tree.query_radius(
            points, r=self.prefer_km / EARTH_RADIUS_KM, return_distance=True)
        nearest_dist, nearest_idx = self.tree.query(points, k=1)
        for i in range(count):
            if len(near_idx[i]):
                cand, cand_km = near_idx[i], near_dist[i] * EARTH_RADIUS_KM
                # most populous first, then nearest, then smallest geonameid
                order = np.lexsort((self.geonameid[cand], cand_km, -self.pop[cand]))
                chosen[i], dist[i] = cand[order[0]], cand_km[order[0]]
            else:
                km = float(nearest_dist[i][0]) * EARTH_RADIUS_KM
                if km <= self.max_km:
                    chosen[i], dist[i] = int(nearest_idx[i][0]), km
        return chosen, dist

    def nearest(self, lat, lng):
        """Index of the nearest place at any distance (no prefer rule, no max_city_km)."""
        _, idx = self.tree.query(np.radians([[lat, lng]]), k=1)
        return int(idx[0][0])


def city_centre(gaz, index):
    """(lat, lng) strings with 4 decimals of the gazetteer place at `index`."""
    return f"{gaz['lat'].iat[index]:.4f}", f"{gaz['lng'].iat[index]:.4f}"


def geocode_photos(photos_df, finder):
    """photo_cities frame (GPS photos only, photos_clean order) plus per-photo lookups.

    Also returns {photo_id: gaz index or -1} and {photo_id: (lat, lng)}; the coordinates stay
    in memory for distance calculations and are never written or printed.
    """
    gps = photos_df[photos_df["has_gps"].astype(str).str.lower() == "true"]
    lats, lngs = gps["lat"].astype(float), gps["lng"].astype(float)
    chosen, dist = finder.find(lats, lngs)
    rows = []
    for photo_id, idx, km in zip(gps["photo_id"], chosen, dist):
        if idx < 0:
            rows.append({"photo_id": photo_id, "city_id": "", "distance_km": ""})
        else:
            rows.append({"photo_id": photo_id, "city_id": finder.gaz["city_id"].iat[idx],
                         "distance_km": f"{km:.1f}"})
    frame = pd.DataFrame(rows, columns=PHOTO_CITY_COLUMNS)
    xy = {pid: (float(a), float(b)) for pid, a, b in zip(gps["photo_id"], lats, lngs)}
    return frame, dict(zip(gps["photo_id"], chosen.tolist())), xy


def period_home(periods, day):
    """(lat, lng, city index or -1) of the home period containing `day`, or None."""
    for start, end, lat, lng, idx in periods:
        if start <= day <= end:
            return lat, lng, idx
    return None


def plan_trip(trip_id, members, span, home, photos, finder, countries, params, radius_km):
    """Choose the cities of one trip. Returns (trip_cities rows, title, near flag).

    members: time-ordered [(rank, photo_id)] of the trip's GPS photos; span = (start, end);
    home = period_home(...) or None (no home period: no home-area filtering).
    Steps (see module docstring): drop home-area cities, apply min_city_photos, then the
    fallbacks "main outside city", "Near <city>" and "home city".
    """
    gaz = finder.gaz
    visits = {}
    for rank, pid in members:
        idx = photos.city.get(pid, -1)
        if idx >= 0:
            entry = visits.setdefault(idx, {"first": rank, "dates": []})
            entry["dates"].append(photos.date[pid])
    ordered = sorted(visits.items(), key=lambda kv: kv[1]["first"])

    def city_row(idx, count, arrive, leave):
        lat, lng = city_centre(gaz, idx)
        code = gaz["country_code"].iat[idx]
        return {"trip_id": trip_id, "city_id": gaz["city_id"].iat[idx],
                "name": gaz["name"].iat[idx], "country": countries.get(code, ""),
                "country_code": code, "lat": lat, "lng": lng, "arrive": arrive,
                "leave": leave, "photo_count": count}

    def visit_row(kv):
        return city_row(kv[0], len(kv[1]["dates"]), min(kv[1]["dates"]), max(kv[1]["dates"]))

    def main_of(items):  # most photos, ties to the earliest first visit
        return max(items, key=lambda kv: (len(kv[1]["dates"]), -kv[1]["first"]))

    if home is None:
        candidates = ordered
    else:
        home_lat, home_lng, home_idx = home
        candidates = [kv for kv in ordered if kv[0] != home_idx and float(haversine_km(
            gaz["lat"].iat[kv[0]], gaz["lng"].iat[kv[0]], home_lat, home_lng)) > radius_km]
    if candidates:
        kept = [kv for kv in candidates if len(kv[1]["dates"]) >= params["min_city_photos"]]
        if not kept:
            kept = [main_of(candidates)]
        return ([visit_row(kv) for kv in kept], gaz["name"].iat[main_of(kept)[0]], False)
    if home is None:
        return [], "", False

    if members:
        coords = np.array([photos.xy[pid] for _, pid in members])
        dist = haversine_km(coords[:, 0], coords[:, 1], home_lat, home_lng)
        outside = [i for i in range(len(members)) if dist[i] > radius_km]
    else:
        outside = []
    if outside:
        far = max(outside, key=lambda i: (dist[i], -i))   # farthest photo, ties -> earliest
        idx = finder.nearest(*photos.xy[members[far][1]])
        dates = [photos.date[members[i][1]] for i in outside]
        return ([city_row(idx, len(outside), min(dates), max(dates))],
                "Near " + gaz["name"].iat[idx], True)
    if home_idx < 0:
        return [], "", False
    dates = [photos.date[pid] for _, pid in members if photos.city.get(pid, -1) == home_idx]
    row = city_row(home_idx, len(dates), min(dates) if dates else span[0],
                   max(dates) if dates else span[1])
    return [row], gaz["name"].iat[home_idx], False


def geocode_pair(root, suffix, photos, finder, countries, params, periods, radius_km):
    """Write trip_cities{suffix}.csv and rewrite trips_pred{suffix}.csv in place.

    Returns ([(start_date, end_date, [(display name, country_code), ...])] in trips_pred
    order, number of trips without a matching home period).
    """
    root = Path(root)
    trips_path = root / with_suffix(TRIPS_REL, suffix)
    trips = pd.read_csv(trips_path, dtype=str, keep_default_na=False)
    photo_trips = pd.read_csv(root / with_suffix(PHOTO_TRIPS_REL, suffix), dtype=str,
                              keep_default_na=False)
    by_trip = {}
    for pid, trip in zip(photo_trips["photo_id"], photo_trips["trip_id"]):
        if pid in photos.xy and pid in photos.rank:
            by_trip.setdefault(trip, []).append((photos.rank[pid], pid))

    city_rows, summary, cities_text, titles, unmatched = [], [], [], [], 0
    for trip_id, start, end in zip(trips["trip_id"], trips["start_date"], trips["end_date"]):
        home = period_home(periods, start)
        unmatched += home is None
        rows, title, near = plan_trip(trip_id, sorted(by_trip.get(trip_id, [])), (start, end),
                                      home, photos, finder, countries, params, radius_km)
        city_rows.extend(rows)
        cities_text.append(";".join(r["name"] for r in rows))
        titles.append(title)
        summary.append([(("Near " + r["name"]) if near else r["name"], r["country_code"])
                        for r in rows])
    trips["cities"] = cities_text
    trips["title"] = titles  # assigned by name: appended once, overwritten on a re-run
    trips.to_csv(trips_path, index=False)
    pd.DataFrame(city_rows, columns=TRIP_CITY_COLUMNS).to_csv(
        root / with_suffix(TRIP_CITIES_REL, suffix), index=False)
    return list(zip(trips["start_date"], trips["end_date"], summary)), unmatched


def geocode_homes(homes_df, finder):
    """Return (homes_city frame, home periods).

    The frame holds the city centre of every home period (never the home point). The periods
    [(from_date, to_date, lat, lng, city index or -1)] keep the real point for in-memory
    distance calculations only.
    """
    gaz = finder.gaz
    lats, lngs = homes_df["lat"].astype(float), homes_df["lng"].astype(float)
    chosen, _ = finder.find(lats, lngs)
    rows = []
    for start, end, idx in zip(homes_df["from_date"], homes_df["to_date"], chosen):
        row = {"from_date": start, "to_date": end, "city_id": "", "name": "",
               "country_code": "", "lat": "", "lng": ""}
        if idx >= 0:
            lat, lng = city_centre(gaz, idx)
            row.update({"city_id": gaz["city_id"].iat[idx], "name": gaz["name"].iat[idx],
                        "country_code": gaz["country_code"].iat[idx], "lat": lat, "lng": lng})
        rows.append(row)
    periods = [(s, e, float(a), float(b), int(i)) for s, e, a, b, i in
               zip(homes_df["from_date"], homes_df["to_date"], lats, lngs, chosen)]
    return pd.DataFrame(rows, columns=HOME_CITY_COLUMNS), periods


def build_parser():
    parser = argparse.ArgumentParser(description="Reverse-geocode trips with offline GeoNames.")
    for key, default in DEFAULT_PARAMS.items():
        if key == "exclude_feature_codes":
            continue  # list-valued: not exposed on the command line
        parser.add_argument(f"--{key}", type=type(default), default=default)
    return parser


def _fail(message):
    print(f"error: {message}")
    sys.exit(1)


def city_label(name, country_code):
    return f"{name} ({country_code})" if country_code else name


def format_report(photo_count, with_city, done, skipped, default_trips, homes_city,
                  unmatched=0):
    """Console lines: counts, trip dates, city names and country codes only."""
    lines = [f"GPS photos with a city: {with_city} of {photo_count}"]
    radii = [str(r) for r in done if r is not None]
    text = "Radii geocoded: " + (", ".join(radii) if radii else "none")
    if None in done:
        text += " (+ default)"
    lines.append(text)
    if skipped:
        lines.append("Radii skipped (files missing): " + ", ".join(skipped))
    if unmatched:
        lines.append(f"Trips without a home period (not filtered): {unmatched}")
    lines.append(f"Trips at default radius ({DEFAULT_RADIUS_KM} km): "
                 + (str(len(default_trips)) if default_trips is not None else "n/a"))
    for start, end, cities in default_trips or []:
        label = "; ".join(city_label(n, c) for n, c in cities) or "no city"
        lines.append(f"  {start} -> {end}  {label}")
    lines.append("Home cities:")
    for row in homes_city.itertuples(index=False):
        label = city_label(row.name, row.country_code) if row.city_id else "no city"
        lines.append(f"  {row.from_date} -> {row.to_date}  {label}")
    return lines


def run(root, params):
    """Do the work and return the console lines; exits through _fail on known input errors."""
    root = Path(root)
    if not (root / CITIES_REL).exists() or not (root / COUNTRIES_REL).exists():
        _fail(GEONAMES_MISSING_MESSAGE)
    try:
        photos = pd.read_csv(root / PHOTOS_REL, dtype=str, keep_default_na=False)
    except Exception:
        _fail(f"could not read {PHOTOS_REL.as_posix()}")
    try:
        homes = pd.read_csv(root / HOMES_REL, dtype=str, keep_default_na=False)
    except Exception:
        _fail(f"could not read {HOMES_REL.as_posix()}")

    gaz = load_gazetteer(root, params)
    countries = load_countries(root)
    finder = CityFinder(gaz, params)

    photo_cities, photo_city_index, photo_xy = geocode_photos(photos, finder)
    photo_cities.to_csv(root / PHOTO_CITIES_REL, index=False)

    prepared = prepare_photos(photos)
    photo_rank = {pid: rank for rank, pid in enumerate(prepared["photo_id"])}
    photo_date = {pid: day.isoformat() for pid, day in zip(prepared["photo_id"], prepared["day"])}
    index = PhotoIndex(photo_rank, photo_date, photo_city_index, photo_xy)

    homes_city, periods = geocode_homes(homes, finder)
    homes_city.to_csv(root / HOMES_CITY_REL, index=False)

    done, skipped, default_trips, unmatched = [], [], None, 0
    for radius in [None] + list(RADIUS_OPTIONS_KM):
        suffix = "" if radius is None else f"_r{radius}"
        if not ((root / with_suffix(TRIPS_REL, suffix)).exists()
                and (root / with_suffix(PHOTO_TRIPS_REL, suffix)).exists()):
            skipped.append("default" if radius is None else str(radius))
            continue
        radius_km = DEFAULT_RADIUS_KM if radius is None else radius  # the default pair = R 50
        trips, missing = geocode_pair(root, suffix, index, finder, countries, params, periods,
                                      radius_km)
        done.append(radius)
        if radius is None or (default_trips is None and radius == DEFAULT_RADIUS_KM):
            default_trips, unmatched = trips, missing  # the default pair wins; r50 stands in

    with_city = int((photo_cities["city_id"] != "").sum())
    return format_report(len(photo_cities), with_city, done, skipped, default_trips, homes_city,
                         unmatched)


def main(argv=None, root=REPO_ROOT):
    args = build_parser().parse_args(argv)
    try:
        params = resolve_params({key: getattr(args, key) for key in DEFAULT_PARAMS
                                 if key != "exclude_feature_codes"})
        lines = run(Path(root), params)
    except SystemExit:
        raise
    except Exception:
        _fail("geocoding failed")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
