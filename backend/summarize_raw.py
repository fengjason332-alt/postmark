"""Print summary numbers for the raw ExifTool CSV (no rows, names or coordinates).

Reads data/raw/photos_raw_jason_all.csv by default (or the CSV path given as the
first argument) and prints only counts and date range:
  total rows, rows with GPS, rows with a valid DateTimeOriginal,
  earliest/latest date, photos per year.

Run from the repo root:  python backend/summarize_raw.py [path/to/file.csv]
"""

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = Path("data") / "raw" / "photos_raw_jason_all.csv"

DATE_FORMAT = "%Y:%m:%d %H:%M:%S"


def resolve_path(arg):
    """Resolve the CSV path: absolute paths as-is, relative ones against the repo root."""
    path = Path(arg)
    return path if path.is_absolute() else REPO_ROOT / path


def gps_mask(df):
    """True for rows with numeric, in-range coordinates that are not the (0, 0) placeholder."""
    lat = pd.to_numeric(df["GPSLatitude"], errors="coerce")
    lng = pd.to_numeric(df["GPSLongitude"], errors="coerce")
    in_range = (lat.abs() <= 90) & (lng.abs() <= 180)
    placeholder = (lat == 0) & (lng == 0)
    return in_range & ~placeholder


def parse_dates(df):
    """Parse the first 19 chars of DateTimeOriginal (local time, offset ignored); NaT if invalid."""
    text = df["DateTimeOriginal"].fillna("").str.slice(0, 19)
    return pd.to_datetime(text, format=DATE_FORMAT, errors="coerce")


def summarize(df):
    dates = parse_dates(df).dropna()
    lines = [
        f"Total rows: {len(df)}",
        f"Rows with GPS: {int(gps_mask(df).sum())}",
        f"Rows with valid DateTimeOriginal: {len(dates)}",
        f"Earliest date: {dates.min().strftime('%Y-%m-%d') if len(dates) else 'none'}",
        f"Latest date: {dates.max().strftime('%Y-%m-%d') if len(dates) else 'none'}",
        "Photos per year:",
    ]
    per_year = dates.dt.year.value_counts().sort_index()
    lines += [f"  {year}: {count}" for year, count in per_year.items()]
    return "\n".join(lines)


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_CSV)
    path = resolve_path(arg)
    if not path.is_file():
        print(f"error: CSV not found: {arg}")
        sys.exit(1)
    df = pd.read_csv(path, dtype=str)
    for column in ("DateTimeOriginal", "GPSLatitude", "GPSLongitude"):
        if column not in df.columns:
            df[column] = pd.NA
    print(summarize(df))


if __name__ == "__main__":
    main()
