"""Write a coarse copy of the cleaned photo table for the data science teammate.

Reads data/processed/photos_clean.csv and writes data/share/photos_coarse_<person>.csv with
  1. file_name and person removed,
  2. lat / lng rounded to 2 decimals (about 1 km), empty values kept empty.

Only the row count and column names are printed; no rows, names or coordinates.
The output stays on the owner's laptop (data/ is git-ignored) and is shared privately.

Run from the repo root:  python backend/export_for_ds.py [person]
"""

import math
import re
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent

PERSON_PATTERN = re.compile(r"[a-z0-9_-]+")

OUTPUT_COLUMNS = ["photo_id", "taken_at", "taken_utc", "date", "lat", "lng", "has_gps"]
COORD_COLUMNS = ["lat", "lng"]


def round_coordinate(text):
    """Return a fixed 2-decimal string ('' stays ''); raises ValueError if unparseable."""
    if text == "":
        return ""
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("coordinate is not finite")
    rounded = f"{value:.2f}"
    return "0.00" if rounded == "-0.00" else rounded


def coarsen(df):
    """Return the shareable copy of a photos_clean DataFrame (all columns are strings)."""
    out = df[OUTPUT_COLUMNS].copy()
    for column in COORD_COLUMNS:
        out[column] = [round_coordinate(value) for value in out[column]]
    return out


def main(argv=None, root=REPO_ROOT):
    args = sys.argv[1:] if argv is None else argv
    person = args[0] if args else "jason"
    if not PERSON_PATTERN.fullmatch(person):
        print("error: person must match [a-z0-9_-]+")
        sys.exit(1)

    input_rel = Path("data") / "processed" / "photos_clean.csv"
    output_rel = Path("data") / "share" / f"photos_coarse_{person}.csv"
    try:
        df = pd.read_csv(root / input_rel, dtype=str, keep_default_na=False)
    except Exception:
        print(f"error: could not read {input_rel.as_posix()}")
        sys.exit(1)

    try:
        out = coarsen(df)
    except Exception:
        print("error: could not export")
        sys.exit(1)

    try:
        (root / output_rel).parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(root / output_rel, index=False)
    except Exception:
        print("error: could not export")
        sys.exit(1)
    print(f"Rows: {len(out)}")
    print("Columns: " + ", ".join(out.columns))


if __name__ == "__main__":
    main()
