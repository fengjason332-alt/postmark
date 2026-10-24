"""Check a trips.json / stats.json pair against data contract 1.1 (AGENTS.md section 6).

Usage (from the repo root):
  python backend/check_contract.py [--folder mock|data]

The folder is frontend/public/<folder>/ (default: mock). Two modes, chosen by the folder:
  mock  invented data: every thumbnail must exist with exact sizes (_s 400 px wide,
        _l 1600 px long edge) and the mock trips must satisfy distance_km > radius.
  data  real data: missing thumbnails are only COUNTED; existing ones must be WEBP and no
        larger than the contract sizes; a taken_at without a UTC offset is a warning.

Error messages never contain coordinate values or file names, only ids and counts.
Exit code 0 = OK, 1 = at least one error.
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent.parent

SCHEMA_VERSION = "1.1"
RADIUS_OPTIONS = [10, 25, 50, 100, 200]
DEFAULT_RADIUS = 50
THUMB_WIDTH = 400
FULL_LONG_EDGE = 1600
MODES = ("mock", "data")
MAX_ERROR_LINES = 20

TRIPS_TOP_KEYS = ["schema_version", "generated_at", "home", "homes", "default_radius_km",
                  "radius_options_km", "trips", "trips_by_radius"]
STATS_TOP_KEYS = ["schema_version", "all_time", "by_year", "by_radius"]
HOME_KEYS = ["city", "country", "country_code", "lat", "lng"]
HOMES_ENTRY_KEYS = ["from_date", "to_date", "city", "country_code", "lat", "lng"]
TRIP_KEYS = ["id", "index", "title", "start_date", "end_date", "days", "distance_km",
             "photo_count", "cover_photo_id", "tags", "cities", "photos"]
CITY_KEYS = ["id", "name", "country", "country_code", "lat", "lng", "arrive", "leave",
             "photo_count"]
PHOTO_KEYS = ["id", "taken_at", "date", "lat", "lng", "has_gps", "city_id", "thumb", "full",
              "width", "height", "tags"]
STAT_KEYS = ["trips", "cities", "countries", "days_away", "distance_km", "photos_total",
             "photos_with_gps", "top_tags", "persona"]
STAT_INT_KEYS = STAT_KEYS[:7]

TRIP_ID = re.compile(r"trip_\d{8}(_[a-z0-9]+)*")
CITY_ID = re.compile(r"city_[a-z0-9]+_[a-z]{2}(_[a-z0-9]+)*")
PHOTO_ID = re.compile(r"p_[0-9a-f]{10}")


@dataclass
class CheckResult:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    n_checks: int = 0
    missing_thumbs: int = 0   # thumbnail files referenced by the JSON that do not exist (data mode)
    total_thumbs: int = 0     # distinct thumbnail files referenced by the JSON

    @property
    def ok(self):
        return not self.errors


class _Checker:
    def __init__(self):
        self.result = CheckResult()
        self.naive_photos = set()   # offset-less photos are warned about once, not once per radius

    def ok(self, condition, message):
        self.result.n_checks += 1
        if not condition:
            self.result.errors.append(message)
        return bool(condition)

    def warn(self, message):
        self.result.warnings.append(message)

    def keys(self, obj, expected, where):
        if not self.ok(isinstance(obj, dict), f"{where}: not an object"):
            return False
        return self.ok(set(obj) == set(expected), f"{where}: keys {sorted(set(obj) ^ set(expected))} differ")


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _coord(value):
    """True for a number (never None) with at most 4 decimals."""
    return _is_number(value) and round(value, 4) == value


def _is_text(value):
    return isinstance(value, str) and value.strip() != ""


def _is_str_list(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _parse_time(text):
    """datetime for an ISO timestamp; naive values are treated as UTC. None if unparsable."""
    try:
        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _has_offset(text):
    try:
        return datetime.fromisoformat(text).tzinfo is not None
    except ValueError:
        return False


def _parse_date(text):
    try:
        return date.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def _summarize(trip_list):
    photos = [p for t in trip_list for p in t["photos"]]
    return {"trips": len(trip_list),
            "cities": len({c["id"] for t in trip_list for c in t["cities"]}),
            "countries": len({c["country_code"] for t in trip_list for c in t["cities"]}),
            "days_away": sum(t["days"] for t in trip_list),
            "distance_km": sum(t["distance_km"] for t in trip_list),
            "photos_total": len(photos),
            "photos_with_gps": sum(1 for p in photos if p["has_gps"])}


def _check_stat_shape(c, stat, where):
    if not c.keys(stat, STAT_KEYS, where):
        return False
    for key in STAT_INT_KEYS:
        c.ok(_is_int(stat[key]), f"{where}.{key} must be an integer")
    c.ok(isinstance(stat["top_tags"], list), f"{where}.top_tags must be a list")
    c.ok(stat["persona"] is None or isinstance(stat["persona"], str), f"{where}.persona")
    return True


def _check_top(c, trips, stats):
    c.ok(trips.get("schema_version") == SCHEMA_VERSION, "trips.json schema_version must be 1.1")
    c.ok(stats.get("schema_version") == SCHEMA_VERSION, "stats.json schema_version must be 1.1")
    if not (c.keys(trips, TRIPS_TOP_KEYS, "trips.json top level")
            and c.keys(stats, STATS_TOP_KEYS, "stats.json top level")):
        return False
    c.ok(isinstance(trips["generated_at"], str) and _has_offset(trips["generated_at"]),
         "generated_at must be ISO 8601 with a UTC offset")
    c.ok(_is_int(trips["default_radius_km"]) and trips["default_radius_km"] == DEFAULT_RADIUS,
         "default_radius_km must be 50")
    c.ok(trips["radius_options_km"] == RADIUS_OPTIONS, "radius_options_km must be [10,25,50,100,200]")
    radius_keys = [str(r) for r in RADIUS_OPTIONS]
    ok_radii = c.ok(isinstance(trips["trips_by_radius"], dict)
                    and list(trips["trips_by_radius"]) == radius_keys
                    and isinstance(stats["by_radius"], dict)
                    and list(stats["by_radius"]) == radius_keys, "radius keys differ from options")
    if not ok_radii:
        return False
    c.ok(trips["trips"] == trips["trips_by_radius"][str(DEFAULT_RADIUS)],
         "trips must equal trips_by_radius[50]")
    c.ok(stats["by_radius"][str(DEFAULT_RADIUS)]
         == {"all_time": stats["all_time"], "by_year": stats["by_year"]},
         "stats by_radius[50] must equal the top-level all_time/by_year")
    return True


def _check_homes(c, trips):
    homes = trips["homes"]
    if not c.ok(isinstance(homes, list) and len(homes) > 0, "homes must be a non-empty list"):
        return
    previous_end = None
    for entry in homes:
        if not c.keys(entry, HOMES_ENTRY_KEYS, "homes entry"):
            continue
        start, end = _parse_date(entry["from_date"]), _parse_date(entry["to_date"])
        if not c.ok(start is not None and end is not None, "homes entry has an invalid date"):
            continue
        c.ok(start <= end, "homes entry from_date is after to_date")
        c.ok(previous_end is None or start > previous_end, "homes must be sorted and non-overlapping")
        c.ok(_coord(entry["lat"]) and _coord(entry["lng"]),
             "homes entry lat/lng must be numbers with at most 4 decimals")
        c.ok(_is_text(entry["city"]) and _is_text(entry["country_code"]), "homes entry city/country_code")
        previous_end = end
    home = trips["home"]
    if c.keys(home, HOME_KEYS, "home") and isinstance(homes[-1], dict):
        last = homes[-1]
        c.ok(isinstance(home["country"], str) and home["country"] != "", "home.country is empty")
        c.ok(all(home.get(k) == last.get(k) for k in ("lat", "lng", "country_code"))
             and home["city"] == last.get("city"), "home must equal the last homes entry")
        c.ok(_coord(home["lat"]) and _coord(home["lng"]),
             "home lat/lng must be numbers with at most 4 decimals")


def _check_photo(c, photo, trip, where, mode, paths, start, end):
    pid = photo.get("id", "?")
    label = f"{where} photo {pid}"
    if not c.keys(photo, PHOTO_KEYS, label):
        return
    c.ok(isinstance(pid, str) and PHOTO_ID.fullmatch(pid), f"{where}: bad photo id format {pid}")
    taken = _parse_time(photo["taken_at"])
    if c.ok(taken is not None, f"{label}: taken_at is not ISO 8601"):
        c.ok(photo["taken_at"][:10] == photo["date"], f"{label}: date differs from taken_at")
        day = _parse_date(photo["date"])
        if start is not None and end is not None:
            c.ok(day is not None and start <= day <= end, f"{label}: date is outside the trip")
        if mode == "data" and datetime.fromisoformat(photo["taken_at"]).tzinfo is None:
            if pid not in c.naive_photos:
                c.naive_photos.add(pid)
                c.warn(f"{label}: taken_at has no UTC offset")
    city_ids = {city["id"] for city in trip["cities"] if isinstance(city, dict) and "id" in city}
    c.ok(photo["city_id"] is None or photo["city_id"] in city_ids,
         f"{label}: city_id is not one of the trip's cities")
    c.ok(isinstance(photo["has_gps"], bool), f"{label}: has_gps must be a boolean")
    if photo["has_gps"] is False:
        c.ok(photo["lat"] is None and photo["lng"] is None and photo["city_id"] is None,
             f"{label}: has_gps is false but lat/lng/city_id are not null")
    elif photo["has_gps"] is True:
        if c.ok(_is_number(photo["lat"]) and _is_number(photo["lng"]),
                f"{label}: has_gps is true but lat/lng are not numbers"):
            c.ok(round(photo["lat"], 4) == photo["lat"], f"{label}: lat has more than 4 decimals")
            c.ok(round(photo["lng"], 4) == photo["lng"], f"{label}: lng has more than 4 decimals")
            c.ok(-90 <= photo["lat"] <= 90 and -180 <= photo["lng"] <= 180,
                 f"{label}: lat/lng out of range")
    c.ok(photo["thumb"] == f"thumbs/{pid}_s.webp" and photo["full"] == f"thumbs/{pid}_l.webp",
         f"{label}: thumb/full paths must be thumbs/<id>_s.webp and thumbs/<id>_l.webp")
    c.ok(_is_int(photo["width"]) and _is_int(photo["height"]) and photo["width"] > 0
         and photo["height"] > 0, f"{label}: width/height must be positive integers")
    c.ok(_is_str_list(photo["tags"]), f"{label}: tags must be a list of strings")
    if isinstance(photo["thumb"], str):
        paths.add(photo["thumb"])
    if isinstance(photo["full"], str):
        paths.add(photo["full"])


def _check_trip(c, trip, radius, mode, paths):
    where = f"R{radius} {trip.get('id', '?')}"
    if not c.keys(trip, TRIP_KEYS, where):
        return False
    c.ok(isinstance(trip["id"], str) and TRIP_ID.fullmatch(trip["id"]), f"{where}: bad trip id format")
    start, end = _parse_date(trip["start_date"]), _parse_date(trip["end_date"])
    if c.ok(start is not None and end is not None, f"{where}: invalid start/end date"):
        c.ok(trip["days"] == (end - start).days + 1, f"{where}: days differs from end - start + 1")
    c.ok(_is_int(trip["distance_km"]) and trip["distance_km"] >= 0, f"{where}: distance_km")
    if mode == "mock":
        # The mock filters one fixed trip set by distance_km > R; real trips come from separate
        # segmentation runs and may have distance_km <= R, so this is a mock-only rule.
        c.ok(_is_int(trip["distance_km"]) and trip["distance_km"] > int(radius),
             f"[mock-only] {where}: distance_km must be > {radius}")
    c.ok(_is_str_list(trip["tags"]), f"{where}: tags must be a list of strings")
    c.ok(_is_text(trip["title"]), f"{where}: title must be a non-empty string")
    for key in ("index", "days", "photo_count"):
        c.ok(_is_int(trip[key]), f"{where}: {key} must be an integer")
    photos, cities = trip["photos"], trip["cities"]
    if not c.ok(isinstance(photos, list) and isinstance(cities, list), f"{where}: photos/cities"):
        return False
    c.ok(trip["photo_count"] == len(photos), f"{where}: photo_count differs from len(photos)")
    ids = [p.get("id") for p in photos if isinstance(p, dict)]
    c.ok(trip["cover_photo_id"] in ids, f"{where}: cover_photo_id is not one of the trip's photos")
    c.ok(len(ids) == len(set(ids)), f"{where}: duplicate photo ids")
    times = [_parse_time(p.get("taken_at")) for p in photos if isinstance(p, dict)]
    if all(t is not None for t in times):
        c.ok(times == sorted(times), f"{where}: photos are not sorted by taken_at")
    for city in cities:
        if not c.keys(city, CITY_KEYS, f"{where} city"):
            continue
        c.ok(isinstance(city["id"], str) and CITY_ID.fullmatch(city["id"]), f"{where}: bad city id format")
        c.ok(_coord(city["lat"]) and _coord(city["lng"]),
             f"{where}: city lat/lng must be numbers with at most 4 decimals")
        c.ok(_is_text(city["name"]), f"{where}: city name must be a non-empty string")
        c.ok(_is_int(city["photo_count"]), f"{where}: city photo_count must be an integer")
        arrive, leave = _parse_date(city["arrive"]), _parse_date(city["leave"])
        if c.ok(arrive is not None and leave is not None, f"{where}: city arrive/leave invalid date"):
            c.ok(arrive <= leave, f"{where}: city arrive is after leave")
            if start is not None and end is not None:
                c.ok(start <= arrive and leave <= end, f"{where}: city dates outside the trip")
    for photo in photos:
        _check_photo(c, photo, trip, where, mode, paths, start, end)
    return True


def _check_stats_for_radius(c, radius, trip_list, stats_radius):
    if not c.keys(stats_radius, ["all_time", "by_year"], f"stats by_radius[{radius}]"):
        return
    if _check_stat_shape(c, stats_radius["all_time"], f"R{radius}.all_time"):
        expected = _summarize(trip_list)
        c.ok({k: stats_radius["all_time"][k] for k in expected} == expected,
             f"R{radius}: all_time stats differ from the trips")
    years = sorted({t["start_date"][:4] for t in trip_list})
    if not c.ok(isinstance(stats_radius["by_year"], dict) and list(stats_radius["by_year"]) == years,
                f"R{radius}: by_year keys differ from the trip years"):
        return
    for year in years:
        if _check_stat_shape(c, stats_radius["by_year"][year], f"R{radius}.{year}"):
            expected = _summarize([t for t in trip_list if t["start_date"][:4] == year])
            c.ok({k: stats_radius["by_year"][year][k] for k in expected} == expected,
                 f"R{radius} {year}: stats differ from the trips")


def _check_files(c, folder, paths, mode):
    c.result.total_thumbs = len(paths)
    for rel in sorted(paths):
        # Contract paths are plain "thumbs/<name>"; refuse anything that could leave the folder.
        if not c.ok(re.fullmatch(r"thumbs/[A-Za-z0-9_]+\.webp", rel), f"bad thumbnail path {rel}"):
            continue
        file_path = folder / rel
        if not file_path.exists():
            if mode == "mock":
                c.ok(False, f"missing thumbnail file {rel}")
            else:
                c.result.missing_thumbs += 1
            continue
        try:
            with Image.open(file_path) as image:
                fmt, size = image.format, image.size
        except Exception:
            c.ok(False, f"thumbnail {rel} cannot be read as an image")
            continue
        c.ok(fmt == "WEBP", f"thumbnail {rel} is not WEBP")
        if rel.endswith("_s.webp"):
            width_ok = size[0] == THUMB_WIDTH if mode == "mock" else size[0] <= THUMB_WIDTH
            c.ok(width_ok, f"thumbnail {rel} has a wrong width ({size[0]})")
        else:
            long_ok = max(size) == FULL_LONG_EDGE if mode == "mock" else max(size) <= FULL_LONG_EDGE
            c.ok(long_ok, f"thumbnail {rel} has a wrong long edge ({max(size)})")
    if mode == "mock":
        thumbs_dir = folder / "thumbs"
        if thumbs_dir.is_dir():
            orphans = {p.name for p in thumbs_dir.iterdir()} - {Path(p).name for p in paths}
            c.ok(not orphans, f"{len(orphans)} orphan files in thumbs/")


def _check_body(c, folder, mode):
    trips = json.loads((folder / "trips.json").read_text(encoding="utf-8"))
    stats = json.loads((folder / "stats.json").read_text(encoding="utf-8"))
    if not _check_top(c, trips, stats):
        return
    _check_homes(c, trips)
    paths = set()
    for radius, trip_list in trips["trips_by_radius"].items():
        if not c.ok(isinstance(trip_list, list), f"R{radius}: trips must be a list"):
            continue
        shape_ok = [_check_trip(c, trip, radius, mode, paths) for trip in trip_list]
        starts = [t.get("start_date") for t in trip_list if isinstance(t, dict)]
        c.ok(starts == sorted(starts), f"R{radius}: trips are not sorted by start_date")
        c.ok([t.get("index") for t in trip_list if isinstance(t, dict)] == list(range(len(trip_list))),
             f"R{radius}: index must run 0..n-1")
        ids = [t.get("id") for t in trip_list if isinstance(t, dict)]
        c.ok(len(ids) == len(set(ids)), f"R{radius}: duplicate trip ids")
        if all(shape_ok):
            _check_stats_for_radius(c, radius, trip_list, stats["by_radius"][radius])
    if _check_stat_shape(c, stats["all_time"], "all_time") and isinstance(stats["by_year"], dict):
        for year, stat in stats["by_year"].items():
            _check_stat_shape(c, stat, f"by_year.{year}")
    _check_files(c, folder, paths, mode)


def check(folder, mode):
    """Validate folder/trips.json + folder/stats.json (+ thumbs/) against contract 1.1."""
    if mode not in MODES:
        raise ValueError("mode must be 'mock' or 'data'")
    folder = Path(folder)
    c = _Checker()
    try:
        _check_body(c, folder, mode)
    except FileNotFoundError:
        c.ok(False, "trips.json or stats.json not found")
    except json.JSONDecodeError:
        c.ok(False, "trips.json or stats.json is not valid JSON")
    except Exception as exc:  # malformed structure beyond what the checks anticipated
        c.ok(False, f"unexpected structure ({type(exc).__name__})")
    return c.result


def format_result(result, name):
    """Console lines for a CheckResult (no coordinates, at most MAX_ERROR_LINES errors)."""
    if result.errors:
        lines = [f"FAILED: {len(result.errors)} errors"]
        lines += [f"  - {message}" for message in result.errors[:MAX_ERROR_LINES]]
        return lines
    return [f"Contract {SCHEMA_VERSION} ({name}): OK ({result.n_checks} checks), "
            f"{len(result.warnings)} warnings"]


def build_parser():
    parser = argparse.ArgumentParser(description="Check trips.json/stats.json against contract 1.1.")
    parser.add_argument("--folder", choices=MODES, default="mock",
                        help="frontend/public/<folder>/ to check (default: mock)")
    return parser


def main(argv=None, root=REPO_ROOT):
    args = build_parser().parse_args(argv)
    folder = Path(root) / "frontend" / "public" / args.folder
    result = check(folder, args.folder)
    lines = format_result(result, args.folder)
    if args.folder == "data" and result.ok:
        lines.append(f"Missing thumbnail files: {result.missing_thumbs} of {result.total_thumbs}")
    print("\n".join(lines))
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
