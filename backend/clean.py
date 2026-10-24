"""Clean the raw ExifTool CSV into data/processed/photos_clean.csv.

Reads data/raw/photos_raw_<person>_all.csv (default person: jason) and
  1. drops rows with an invalid, pre-2005 or future DateTimeOriginal,
  2. normalises the timestamp (local time plus optional UTC offset),
  3. validates GPS (numeric, in range, not the (0, 0) placeholder),
  4. merges bursts (same second, both with GPS, within 10 m),
  5. assigns a stable photo_id (SHA-1 of the file content, first 10 hex chars),
  6. drops rows whose file content duplicates an earlier row.

Only a short count report is printed; no rows, names or coordinates.

Run from the repo root:  python backend/clean.py [person]
"""

import hashlib
import math
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent

DATE_FORMAT = "%Y:%m:%d %H:%M:%S"
MIN_DATE = date(2005, 1, 1)
BURST_DISTANCE_M = 10.0
EARTH_RADIUS_M = 6371000.0
HASH_CHUNK_BYTES = 1024 * 1024

PERSON_PATTERN = re.compile(r"[a-z0-9_-]+")
OFFSET_PATTERN = re.compile(r"[+-]\d\d:\d\d")

RAW_COLUMNS = ["SourceFile", "FileName", "DateTimeOriginal", "OffsetTimeOriginal",
               "GPSLatitude", "GPSLongitude"]
OUTPUT_COLUMNS = ["photo_id", "person", "file_name", "taken_at", "taken_utc",
                  "date", "lat", "lng", "has_gps"]


def parse_local_time(text):
    """Parse the first 19 chars of DateTimeOriginal; None if blank, zeroed or malformed."""
    try:
        return datetime.strptime(text[:19], DATE_FORMAT)
    except ValueError:
        return None


def parse_offset(text):
    """Return a '+HH:MM' string for a valid OffsetTimeOriginal ('Z' means +00:00), else None."""
    text = text.strip()
    if text == "Z":
        return "+00:00"
    if OFFSET_PATTERN.fullmatch(text):
        return text
    return None


def offset_to_timedelta(offset):
    sign = -1 if offset[0] == "-" else 1
    return sign * timedelta(hours=int(offset[1:3]), minutes=int(offset[4:6]))


def parse_gps(lat_text, lng_text):
    """Return (lat, lng) floats for a usable GPS fix, else None."""
    try:
        lat = float(lat_text)
        lng = float(lng_text)
    except ValueError:
        return None
    if not (abs(lat) <= 90 and abs(lng) <= 180):  # also rejects NaN
        return None
    if lat == 0 and lng == 0:
        return None
    return lat, lng


def haversine_m(a, b):
    """Great-circle distance in metres between two (lat, lng) pairs."""
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2)
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def resolve_source(source_file, root):
    path = Path(source_file)
    return path if path.is_absolute() else root / path


def content_hash(path):
    """SHA-1 hex digest of the file content, read in 1 MB chunks; None if unreadable."""
    try:
        digest = hashlib.sha1()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(HASH_CHUNK_BYTES), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except (OSError, ValueError):
        return None


def photo_id_for(record, root):
    """Return (photo_id, used_fallback)."""
    digest = content_hash(resolve_source(record["source"], root)) if record["source"] else None
    if digest is not None:
        return "p_" + digest[:10], False
    key = f"{record['source']}|{record['taken_at']}"
    return "p_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10], True


def merge_bursts(records):
    """Drop GPS rows within 10 m of an earlier kept GPS row with the same local second."""
    kept_gps = {}
    survivors = []
    merged = 0
    for record in records:
        if record["gps"] is not None:
            earlier = kept_gps.setdefault(record["local"], [])
            if any(haversine_m(record["gps"], other) <= BURST_DISTANCE_M for other in earlier):
                merged += 1
                continue
            earlier.append(record["gps"])
        survivors.append(record)
    return survivors, merged


def build_record(row, local_time):
    offset = parse_offset(row["OffsetTimeOriginal"])
    local = local_time.strftime("%Y-%m-%dT%H:%M:%S")
    taken_utc = ""
    taken_at = local
    if offset is not None:
        taken_at = local + offset
        utc_time = local_time - offset_to_timedelta(offset)
        taken_utc = utc_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "source": row["SourceFile"],
        "file_name": row["FileName"],
        "local": local,
        "taken_at": taken_at,
        "taken_utc": taken_utc,
        "date": local_time.strftime("%Y-%m-%d"),
        "gps": parse_gps(row["GPSLatitude"], row["GPSLongitude"]),
    }


def clean(df, person, today, root=REPO_ROOT):
    """Clean a raw ExifTool DataFrame. Returns (output DataFrame, report dict)."""
    df = df.copy()
    for column in RAW_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    df = df[RAW_COLUMNS].fillna("").astype(str)

    report = {"rows_in": len(df), "dropped_invalid_date": 0, "dropped_before_2005": 0,
              "dropped_future": 0, "bursts_merged": 0, "dropped_duplicate_content": 0,
              "rows_out": 0, "rows_with_gps": 0, "hash_fallbacks": 0}

    records = []
    for row in df.to_dict("records"):
        local_time = parse_local_time(row["DateTimeOriginal"])
        if local_time is None:
            report["dropped_invalid_date"] += 1
        elif local_time.date() < MIN_DATE:
            report["dropped_before_2005"] += 1
        elif local_time.date() > today:
            report["dropped_future"] += 1
        else:
            records.append(build_record(row, local_time))

    records, report["bursts_merged"] = merge_bursts(records)

    seen_ids = set()
    unique = []
    for record in records:
        record["photo_id"], used_fallback = photo_id_for(record, root)
        report["hash_fallbacks"] += int(used_fallback)
        if record["photo_id"] in seen_ids:
            report["dropped_duplicate_content"] += 1
            continue
        seen_ids.add(record["photo_id"])
        unique.append(record)

    unique.sort(key=lambda record: record["local"])  # stable: ties keep file order

    rows = []
    for record in unique:
        gps = record["gps"]
        rows.append({
            "photo_id": record["photo_id"],
            "person": person,
            "file_name": record["file_name"],
            "taken_at": record["taken_at"],
            "taken_utc": record["taken_utc"],
            "date": record["date"],
            "lat": "" if gps is None else repr(gps[0]),
            "lng": "" if gps is None else repr(gps[1]),
            "has_gps": "false" if gps is None else "true",
        })
    out = pd.DataFrame(rows, columns=OUTPUT_COLUMNS, dtype=str)

    report["rows_out"] = len(out)
    report["rows_with_gps"] = int((out["has_gps"] == "true").sum())
    return out, report


def format_report(report):
    return "\n".join([
        f"Rows in: {report['rows_in']}",
        f"Dropped (invalid date): {report['dropped_invalid_date']}",
        f"Dropped (before 2005): {report['dropped_before_2005']}",
        f"Dropped (future date): {report['dropped_future']}",
        f"Bursts merged: {report['bursts_merged']}",
        f"Dropped (duplicate content): {report['dropped_duplicate_content']}",
        f"Rows out: {report['rows_out']}",
        f"Rows with GPS: {report['rows_with_gps']}",
        f"Hash fallbacks: {report['hash_fallbacks']}",
    ])


def main(argv=None, root=REPO_ROOT, today=None):
    args = sys.argv[1:] if argv is None else argv
    person = args[0] if args else "jason"
    if not PERSON_PATTERN.fullmatch(person):
        print("error: person must match [a-z0-9_-]+")
        sys.exit(1)

    input_rel = Path("data") / "raw" / f"photos_raw_{person}_all.csv"
    output_rel = Path("data") / "processed" / "photos_clean.csv"
    try:
        df = pd.read_csv(root / input_rel, dtype=str, keep_default_na=False)
    except Exception:
        print(f"error: could not read {input_rel.as_posix()}")
        sys.exit(1)

    try:
        out, report = clean(df, person, today or date.today(), root)
    except Exception:
        print("error: could not clean input")
        sys.exit(1)

    try:
        (root / output_rel).parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(root / output_rel, index=False)
    except Exception:
        print("error: could not write output")
        sys.exit(1)
    print(format_report(report))
    if report["hash_fallbacks"] > 0:
        print(f"warning: {report['hash_fallbacks']} photo files could not be read; "
              "their photo_id is path-based, not a content hash. "
              "Give this terminal access to the photo folder and re-run.", file=sys.stderr)


if __name__ == "__main__":
    main()
