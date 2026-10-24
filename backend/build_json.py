"""Build the frontend data files (contract 1.1, AGENTS.md section 6) from the processed CSVs.

Reads (data/processed/, all git-ignored; local only)
  trips_pred_r{R}.csv, trip_cities_r{R}.csv, photo_trips_r{R}.csv   for every R in RADIUS_OPTIONS_KM
  photo_cities.csv, photos_clean.csv, homes_city.csv, homes.csv
  data/geonames/countryInfo.txt                                      country names
  data/raw/photos_raw_<person>_all.csv                               optional: raw image sizes
and writes (git-ignored)
  frontend/public/data/trips.json, frontend/public/data/stats.json
then checks them with check_contract in "data" mode.

Privacy: homes.csv holds the REAL home points. They are used only to decide which GPS photos
get snapped to the home CITY CENTRE; they are never written out. For every home period the
snap disc is centred on the public city centre with radius max(R, d(real home, centre) + R),
R = PRIVACY_RADIUS_KM, so it covers every photo within R of that real home without revealing
where home is inside it. A photo is checked against the discs of ALL periods (not just the
period of its trip), so former and later homes are protected too; it snaps to the nearest
containing disc centre. Photos near the real home of a period without a home city are hidden
(has_gps false). A built-in self-check refuses to write anything if a published GPS photo
still lies within R of any real home.
Trip distances also start at the home city centre. Only counts and sizes are printed.

Run from the repo root:  python backend/build_json.py [--person NAME]
"""

import argparse
import copy
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
from PIL import Image

import check_contract
import geocode
import segment

REPO_ROOT = Path(__file__).resolve().parent.parent

SCHEMA_VERSION = "1.1"
PRIVACY_RADIUS_KM = 10.0
THUMB_LONG_EDGE = 1600
FALLBACK_SIZE = (1600, 1200)
DEFAULT_PERSON = "jason"

PROCESSED_REL = Path("data") / "processed"
RAW_REL = Path("data") / "raw"
OUT_REL = Path("frontend") / "public" / "data"


class PrivacyError(Exception):
    """Raised when the self-check finds a published GPS photo near a real home point."""


class BuildError(Exception):
    """Raised for missing or unusable inputs; the message is never shown (it may be sensitive)."""


def read_csv(path):
    return pd.read_csv(path, dtype=str, keep_default_na=False)


def number(text):
    """float for a numeric string, else None."""
    try:
        return float(text)
    except (TypeError, ValueError):
        return None


def round4(value):
    return None if value is None else round(float(value), 4)


def digits(text):
    return re.sub(r"\D", "", str(text))[:14]


# ---- loading -------------------------------------------------------------------------------

def load_inputs(root, person_override=None):
    processed = root / PROCESSED_REL
    radii = {}
    for radius in segment.RADIUS_OPTIONS_KM:
        radii[radius] = {name: read_csv(processed / f"{name}_r{radius}.csv")
                         for name in ("trips_pred", "trip_cities", "photo_trips")}
    data = {
        "radii": radii,
        "photo_cities": read_csv(processed / "photo_cities.csv"),
        "photos": read_csv(processed / "photos_clean.csv"),
        "homes_city": read_csv(processed / "homes_city.csv"),
        "homes": read_csv(processed / "homes.csv"),
        "countries": geocode.load_countries(root),
    }
    person = person_override
    if not person:
        persons = radii[segment.DEFAULT_RADIUS_KM]["trips_pred"].get("person")
        person = str(persons.iloc[0]) if persons is not None and len(persons) else DEFAULT_PERSON
    data["person"] = person or DEFAULT_PERSON
    raw_path = root / RAW_REL / f"photos_raw_{data['person']}_all.csv"
    data["raw"] = read_csv(raw_path) if raw_path.exists() else None
    return data


def raw_size_lookup(raw):
    """{(FileName, digits of DateTimeOriginal[:19]): (width, height)} from the raw metadata."""
    sizes = {}
    if raw is None or not {"FileName", "DateTimeOriginal", "ImageWidth", "ImageHeight"} <= set(raw.columns):
        return sizes
    for name, taken, width, height in zip(raw["FileName"], raw["DateTimeOriginal"],
                                          raw["ImageWidth"], raw["ImageHeight"]):
        w, h = number(width), number(height)
        if w and h and w > 0 and h > 0:
            sizes[(name, digits(taken))] = (int(w), int(h))
    return sizes


# ---- homes ---------------------------------------------------------------------------------

def merge_homes(homes_city, countries):
    """(homes list, home dict) from homes_city rows: no-city rows dropped, same-city runs merged."""
    homes, last_city = [], None
    for row in homes_city.to_dict("records"):
        city_id = row["city_id"]
        lat, lng = number(row["lat"]), number(row["lng"])
        if not city_id or lat is None or lng is None:
            last_city = None
            continue
        if last_city == city_id:
            homes[-1]["to_date"] = row["to_date"]
        else:
            homes.append({"from_date": row["from_date"], "to_date": row["to_date"],
                          "city": row["name"], "country_code": row["country_code"],
                          "lat": round4(lat), "lng": round4(lng)})
        last_city = city_id
    if not homes:
        raise BuildError("no home city")
    homes.sort(key=lambda h: h["from_date"])
    last = homes[-1]
    home = {"city": last["city"],
            "country": countries.get(last["country_code"]) or last["country_code"],
            "country_code": last["country_code"], "lat": last["lat"], "lng": last["lng"]}
    return homes, home


def build_periods(homes, homes_city):
    """Home periods: dicts with from/to, REAL point (internal) and city centre (or None)."""
    # Strict (from_date, to_date) match; a period without a match has no home city (never by index).
    centres = {(r["from_date"], r["to_date"]): r for r in homes_city.to_dict("records")}
    periods = []
    for row in homes.to_dict("records"):
        centre = centres.get((row["from_date"], row["to_date"]))
        has_city = bool(centre and centre["city_id"] and number(centre["lat"]) is not None
                        and number(centre["lng"]) is not None)
        real = (number(row["lat"]), number(row["lng"]))
        centre_point = (number(centre["lat"]), number(centre["lng"])) if has_city else None
        periods.append({"from": row["from_date"], "to": row["to_date"], "real": real,
                        "centre": centre_point, "disc_km": disc_radius_km(real, centre_point)})
    if not periods:
        raise BuildError("no home periods")
    return periods


def disc_radius_km(real, centre):
    """Snap-disc radius around the home city centre; None when there is no usable centre."""
    if centre is None or real[0] is None or real[1] is None:
        return None
    gap = float(segment.haversine_km(real[0], real[1], centre[0], centre[1]))
    return max(PRIVACY_RADIUS_KM, gap + PRIVACY_RADIUS_KM)


def period_for(periods, day):
    """Period containing `day` (ISO string); the most recent period if none contains it."""
    for period in periods:
        if period["from"] <= day <= period["to"]:
            return period
    return max(periods, key=lambda p: p["from"])


# ---- trips ---------------------------------------------------------------------------------

def path_distance_km(centre, cities):
    """Rounded one-way km from the home city centre through each city centre in visit order."""
    points = [(c["lat"], c["lng"]) for c in cities]
    if centre is not None:
        points.insert(0, centre)
    total = sum(float(segment.haversine_km(a[0], a[1], b[0], b[1]))
                for a, b in zip(points, points[1:]))
    return int(round(total))


def pick_cover(title, cities, photos, snapped=frozenset()):
    """cover_photo_id: middle non-snapped GPS photo of the main city, else of the trip, else any.

    Photos snapped to the home city centre never become the cover (their position is not real).
    """
    if not photos:
        return None
    main_id = None
    if title.startswith("Near ") and len(cities) == 1:
        main_id = cities[0]["id"]
    else:
        named = [c for c in cities if c["name"] == title]
        if named:
            main_id = named[0]["id"]
        elif cities:
            main_id = max(cities, key=lambda c: c["photo_count"])["id"]
    real_gps = [p for p in photos if p["has_gps"] and p["id"] not in snapped]
    candidates = [p for p in real_gps if p["city_id"] == main_id] if main_id else []
    if not candidates:
        candidates = real_gps
    if not candidates:
        candidates = photos
    return candidates[len(candidates) // 2]["id"]


class SizeResolver:
    """Photo width/height: real _l.webp size if generated, else scaled raw size, else default."""

    def __init__(self, thumbs_dir, raw_sizes):
        self.thumbs_dir = thumbs_dir
        self.raw_sizes = raw_sizes
        self.cache = {}

    def resolve(self, photo_id, file_name, taken_at):
        if photo_id in self.cache:
            return self.cache[photo_id]
        size = None
        full = self.thumbs_dir / f"{photo_id}_l.webp"
        if full.exists():
            try:
                with Image.open(full) as image:
                    size = image.size
            except Exception:
                size = None
        if size is None:
            raw = self.raw_sizes.get((file_name, digits(taken_at)))
            if raw:
                scale = min(THUMB_LONG_EDGE, max(raw)) / max(raw)
                size = (max(1, int(round(raw[0] * scale))), max(1, int(round(raw[1] * scale))))
        self.cache[photo_id] = (int(size[0]), int(size[1])) if size else FALLBACK_SIZE
        return self.cache[photo_id]


def sort_key(row):
    return ((row["taken_utc"] or row["taken_at"])[:19], row["photo_id"])


def decide_privacy(lat, lng, periods):
    """("keep", None), ("hide", None) or ("snap", (centre_lat, centre_lng)) for a GPS photo.

    Hide: within PRIVACY_RADIUS_KM of the real home of a period that has no home city.
    Snap: inside the privacy disc of any period with a home city; nearest centre wins.
    """
    for period in periods:
        real = period["real"]
        if (period["centre"] is None and real[0] is not None and real[1] is not None
                and float(segment.haversine_km(lat, lng, real[0], real[1])) <= PRIVACY_RADIUS_KM):
            return "hide", None
    best, best_km = None, None
    for period in periods:
        centre = period["centre"]
        if centre is None or period["disc_km"] is None:
            continue
        km = float(segment.haversine_km(lat, lng, centre[0], centre[1]))
        if km <= period["disc_km"] and (best_km is None or km < best_km):
            best, best_km = centre, km
    return ("snap", best) if best is not None else ("keep", None)


def build_photo(row, trip_city_ids, periods, photo_city, sizes):
    pid = row["photo_id"]
    lat, lng = number(row["lat"]), number(row["lng"])
    has_gps = row["has_gps"].lower() == "true" and lat is not None and lng is not None
    out_lat = out_lng = city_id = None
    snapped = False
    if has_gps:
        action, centre = decide_privacy(lat, lng, periods)
        if action == "hide":
            has_gps = False
        elif action == "snap":
            out_lat, out_lng = round4(centre[0]), round4(centre[1])
            snapped = True
        else:
            out_lat, out_lng = round4(lat), round4(lng)
            candidate = photo_city.get(pid, "")
            city_id = candidate if candidate in trip_city_ids else None
    width, height = sizes.resolve(pid, row["file_name"], row["taken_at"])
    return ({"id": pid, "taken_at": row["taken_at"], "date": row["date"],
             "lat": out_lat, "lng": out_lng, "has_gps": has_gps, "city_id": city_id,
             "thumb": f"thumbs/{pid}_s.webp", "full": f"thumbs/{pid}_l.webp",
             "width": width, "height": height, "tags": []}, snapped)


def build_radius(frames, photo_rows, photo_city, periods, sizes):
    cities_by_trip = defaultdict(list)
    for row in frames["trip_cities"].to_dict("records"):
        if number(row["lat"]) is None or number(row["lng"]) is None:
            raise BuildError("trip city without coordinates")
        cities_by_trip[row["trip_id"]].append({
            "id": row["city_id"], "name": row["name"], "country": row["country"],
            "country_code": row["country_code"], "lat": round4(number(row["lat"])),
            "lng": round4(number(row["lng"])), "arrive": row["arrive"], "leave": row["leave"],
            "photo_count": int(number(row["photo_count"]) or 0)})
    photos_by_trip = defaultdict(list)
    for row in frames["photo_trips"].to_dict("records"):
        if row["photo_id"] in photo_rows:
            photos_by_trip[row["trip_id"]].append(photo_rows[row["photo_id"]])

    trips = []
    ordered = sorted(frames["trips_pred"].to_dict("records"),
                     key=lambda r: (r["start_date"], r["trip_id"]))
    for index, row in enumerate(ordered):
        trip_id = row["trip_id"]
        period = period_for(periods, row["start_date"])
        cities = cities_by_trip.get(trip_id, [])
        city_ids = {c["id"] for c in cities}
        members = sorted(photos_by_trip.get(trip_id, []), key=sort_key)
        built = [build_photo(m, city_ids, periods, photo_city, sizes) for m in members]
        photos = [photo for photo, _ in built]
        snapped = {photo["id"] for photo, was_snapped in built if was_snapped}
        trips.append({
            "id": trip_id, "index": index, "title": row["title"],
            "start_date": row["start_date"], "end_date": row["end_date"],
            "days": int(number(row["days"]) or 0),
            "distance_km": path_distance_km(period["centre"], cities),
            "photo_count": len(photos), "cover_photo_id": pick_cover(row["title"], cities, photos, snapped),
            "tags": [], "cities": cities, "photos": photos})
    return trips


def privacy_violations(trips_doc, photo_rows, periods):
    """Number of published GPS photos at their real position within R of any real home point."""
    homes = [p["real"] for p in periods if p["real"][0] is not None and p["real"][1] is not None]
    count = 0
    for trip_list in trips_doc["trips_by_radius"].values():
        for trip in trip_list:
            for photo in trip["photos"]:
                if not photo["has_gps"]:
                    continue
                row = photo_rows[photo["id"]]
                lat, lng = float(row["lat"]), float(row["lng"])
                if (photo["lat"], photo["lng"]) != (round4(lat), round4(lng)):
                    continue  # not at its real position: snapped to the city centre
                if any(float(segment.haversine_km(lat, lng, h[0], h[1])) <= PRIVACY_RADIUS_KM
                       for h in homes):
                    count += 1
    return count


# ---- stats ---------------------------------------------------------------------------------

def summarize(trip_list):
    photos = [p for t in trip_list for p in t["photos"]]
    return {"trips": len(trip_list),
            "cities": len({c["id"] for t in trip_list for c in t["cities"]}),
            "countries": len({c["country_code"] for t in trip_list for c in t["cities"]}),
            "days_away": sum(t["days"] for t in trip_list),
            "distance_km": sum(t["distance_km"] for t in trip_list),
            "photos_total": sum(t["photo_count"] for t in trip_list),
            "photos_with_gps": sum(1 for p in photos if p["has_gps"]),
            "top_tags": [], "persona": None}


def stats_for(trip_list):
    years = sorted({t["start_date"][:4] for t in trip_list})
    return {"all_time": summarize(trip_list),
            "by_year": {y: summarize([t for t in trip_list if t["start_date"][:4] == y])
                        for y in years}}


# ---- build + write -------------------------------------------------------------------------

def build(root, person=None, now=None):
    """Return (trips_doc, stats_doc) for the processed data under `root`."""
    root = Path(root)
    data = load_inputs(root, person)
    homes, home = merge_homes(data["homes_city"], data["countries"])
    periods = build_periods(data["homes"], data["homes_city"])
    photo_rows = {r["photo_id"]: r for r in data["photos"].to_dict("records")}
    photo_city = dict(zip(data["photo_cities"]["photo_id"], data["photo_cities"]["city_id"]))
    sizes = SizeResolver(root / OUT_REL / "thumbs", raw_size_lookup(data["raw"]))

    by_radius = {str(r): build_radius(data["radii"][r], photo_rows, photo_city, periods, sizes)
                 for r in segment.RADIUS_OPTIONS_KM}
    default = str(segment.DEFAULT_RADIUS_KM)
    generated = (now or datetime.now().astimezone()).isoformat(timespec="seconds")
    trips_doc = {"schema_version": SCHEMA_VERSION, "generated_at": generated, "home": home,
                 "homes": homes, "default_radius_km": segment.DEFAULT_RADIUS_KM,
                 "radius_options_km": list(segment.RADIUS_OPTIONS_KM),
                 "trips": copy.deepcopy(by_radius[default]), "trips_by_radius": by_radius}
    if privacy_violations(trips_doc, photo_rows, periods) > 0:
        raise PrivacyError("published photo near a real home")
    per_radius = {r: stats_for(tl) for r, tl in by_radius.items()}
    stats_doc = {"schema_version": SCHEMA_VERSION, "all_time": per_radius[default]["all_time"],
                 "by_year": per_radius[default]["by_year"], "by_radius": per_radius}
    return trips_doc, stats_doc


def dump(path, document):
    text = json.dumps(document, ensure_ascii=False, separators=(",", ":")) + "\n"
    path.write_bytes(text.encode("utf-8"))
    return path.stat().st_size


def missing_thumbnail_counts(trips_doc, out_dir):
    ids = {p["id"] for tl in trips_doc["trips_by_radius"].values() for t in tl for p in t["photos"]}
    missing = sum(1 for pid in ids if not ((out_dir / "thumbs" / f"{pid}_s.webp").exists()
                                           and (out_dir / "thumbs" / f"{pid}_l.webp").exists()))
    return missing, len(ids)


def build_parser():
    parser = argparse.ArgumentParser(description="Build trips.json and stats.json (contract 1.1).")
    parser.add_argument("--person", default=None,
                        help="owner of data/raw/photos_raw_<person>_all.csv (default: from trips_pred)")
    return parser


def main(argv=None, root=REPO_ROOT):
    args = build_parser().parse_args(argv)
    root = Path(root)
    out_dir = root / OUT_REL
    try:
        trips_doc, stats_doc = build(root, args.person)
        out_dir.mkdir(parents=True, exist_ok=True)
        trips_size = dump(out_dir / "trips.json", trips_doc)
        stats_size = dump(out_dir / "stats.json", stats_doc)
    except PrivacyError:
        print("error: privacy check failed")
        return 1
    except Exception:
        print("error: could not build trips.json (check data/processed/ and run the pipeline first)")
        return 1

    lines = []
    for radius in segment.RADIUS_OPTIONS_KM:
        trip_list = trips_doc["trips_by_radius"][str(radius)]
        lines.append(f"r={radius} km: {len(trip_list)} trips, "
                     f"{sum(t['photo_count'] for t in trip_list)} photos")
    lines.append(f"trips.json: {trips_size / 1024:.1f} KB, stats.json: {stats_size / 1024:.1f} KB")
    missing, total = missing_thumbnail_counts(trips_doc, out_dir)
    lines.append(f"Missing thumbnails: {missing} of {total} photos")
    lines.append("Privacy check: OK")
    result = check_contract.check(out_dir, "data")
    lines += check_contract.format_result(result, "data")
    print("\n".join(lines))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
