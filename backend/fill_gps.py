"""Fill missing GPS from photos taken close in time (AGENTS.md P1).

A photo without GPS borrows a location from the GPS photos taken just before / after it,
but only when the answer is unambiguous:
  - neighbours = nearest GPS photos (same person) within max_gap_hours on each side;
  - none -> stays unfilled; one -> copy it;
  - two within max_km of each other -> interpolate by time;
  - two further apart than max_km -> stays unfilled (the person was moving).

Input  (local, never committed):
  data/processed/photos_clean.csv    photo_id,person,file_name,taken_at,taken_utc,date,lat,lng,has_gps
Output (local, never committed):
  data/processed/photos_filled.csv   same columns + gps_source ("exif" | "filled" | "none")
Score output (aggregate only, safe to commit):
  results/fill_gps_eval.csv          hold-out accuracy: fill rate and error in km

Hold-out evaluation (--eval): hide the GPS of a random 20% of the photos that have it, fill
them from the rest, and compare with the hidden truth. Only counts and km errors are printed.

Usage (run from the repo root):
  python backend/fill_gps.py --person kunal          # write photos_filled.csv
  python backend/fill_gps.py --person kunal --eval   # hold-out accuracy, writes results/
  python backend/fill_gps.py --demo                  # made-up data, no files needed
"""

import argparse
import csv
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_IN = REPO_ROOT / "data" / "processed" / "photos_clean.csv"
DEFAULT_OUT = REPO_ROOT / "data" / "processed" / "photos_filled.csv"
DEFAULT_EVAL = REPO_ROOT / "results" / "fill_gps_eval.csv"

EVAL_COLUMNS = ["person", "max_gap_hours", "max_km", "holdout_n", "filled_n",
                "fill_rate", "median_err_km", "p90_err_km"]
TRUE_VALUES = ("true", "1", "yes")


def haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp, dl = p2 - p1, np.radians(lng2 - lng1)
    a = np.sin(dp / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    return 2 * r * np.arcsin(np.sqrt(a))


def load_photos(path, person=None):
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    if person:
        df = df[df["person"].str.strip().str.lower() == person].copy()
    df["_utc"] = pd.to_datetime(df["taken_utc"], utc=True, errors="coerce")
    df["_has"] = df["has_gps"].str.strip().str.lower().isin(TRUE_VALUES)
    df["_lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["_lng"] = pd.to_numeric(df["lng"], errors="coerce")
    df["_has"] &= df["_lat"].notna() & df["_lng"].notna()
    return df.reset_index(drop=True)


def fill_person(times, has, lat, lng, max_gap_hours=1.0, max_km=1.0):
    """Return (new_lat, new_lng, filled_mask) for one person's photos.

    times: float seconds, has: bool mask of photos with GPS, lat/lng: float arrays (nan if none).
    """
    new_lat, new_lng = lat.copy(), lng.copy()
    filled = np.zeros(len(times), dtype=bool)
    gps_idx = np.flatnonzero(has & ~np.isnan(times))
    if len(gps_idx) == 0:
        return new_lat, new_lng, filled
    order = gps_idx[np.argsort(times[gps_idx])]
    gps_t = times[order]
    gap = max_gap_hours * 3600.0

    for i in np.flatnonzero(~has & ~np.isnan(times)):
        pos = np.searchsorted(gps_t, times[i])
        prev = order[pos - 1] if pos > 0 and times[i] - gps_t[pos - 1] <= gap else None
        nxt = order[pos] if pos < len(gps_t) and gps_t[pos] - times[i] <= gap else None
        if prev is None and nxt is None:
            continue
        if prev is None or nxt is None:
            src = nxt if prev is None else prev
            new_lat[i], new_lng[i] = lat[src], lng[src]
        else:
            if haversine_km(lat[prev], lng[prev], lat[nxt], lng[nxt]) > max_km:
                continue
            span = times[nxt] - times[prev]
            w = 0.5 if span <= 0 else (times[i] - times[prev]) / span
            new_lat[i] = lat[prev] + w * (lat[nxt] - lat[prev])
            new_lng[i] = lng[prev] + w * (lng[nxt] - lng[prev])
        filled[i] = True
    return new_lat, new_lng, filled


def fill_frame(df, max_gap_hours=1.0, max_km=1.0):
    """Fill the whole table, person by person. Returns a copy with gps_source set."""
    out = df.copy()
    out["gps_source"] = np.where(out["_has"], "exif", "none")
    for _, idx in out.groupby(out["person"].str.strip().str.lower()).groups.items():
        sub = out.loc[idx]
        epoch = pd.Timestamp("1970-01-01", tz="UTC")
        times = (sub["_utc"] - epoch).dt.total_seconds().to_numpy(dtype=float)
        nl, ng, mask = fill_person(times, sub["_has"].to_numpy(), sub["_lat"].to_numpy(),
                                   sub["_lng"].to_numpy(), max_gap_hours, max_km)
        rows = sub.index[mask]
        out.loc[rows, "_lat"] = nl[mask]
        out.loc[rows, "_lng"] = ng[mask]
        out.loc[rows, "_has"] = True
        out.loc[rows, "gps_source"] = "filled"
    return out


def holdout_eval(df, max_gap_hours=1.0, max_km=1.0, frac=0.2, seed=0):
    """Hide GPS on a random fraction of GPS photos, re-fill, and measure the error in km."""
    rng = np.random.default_rng(seed)
    has_idx = df.index[df["_has"]].to_numpy()
    hidden = rng.choice(has_idx, size=int(len(has_idx) * frac), replace=False)
    test = df.copy()
    test.loc[hidden, "_has"] = False
    filled = fill_frame(test, max_gap_hours, max_km)
    got = filled.loc[hidden]
    ok = got["gps_source"] == "filled"
    errs = haversine_km(df.loc[hidden[ok.to_numpy()], "_lat"].to_numpy(),
                        df.loc[hidden[ok.to_numpy()], "_lng"].to_numpy(),
                        got.loc[ok, "_lat"].to_numpy(), got.loc[ok, "_lng"].to_numpy())
    n = len(hidden)
    return {"holdout_n": n, "filled_n": int(ok.sum()),
            "fill_rate": round(ok.sum() / n, 3) if n else 0.0,
            "median_err_km": round(float(np.median(errs)), 3) if len(errs) else None,
            "p90_err_km": round(float(np.percentile(errs, 90)), 3) if len(errs) else None}


def save_eval(row, path):
    """Write the score row, replacing an earlier row with the same settings."""
    path.parent.mkdir(parents=True, exist_ok=True)
    keep = []
    key = (row["person"], str(row["max_gap_hours"]), str(row["max_km"]))
    if path.exists():
        with open(path, newline="", encoding="utf-8") as f:
            keep = [r for r in csv.DictReader(f)
                    if (r["person"], r["max_gap_hours"], r["max_km"]) != key]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EVAL_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in keep + [row]:
            w.writerow(r)
    print(f"Saved scores to {path.relative_to(REPO_ROOT)}")


def demo_frame():
    """Invented photos: a stay in one place, a drive between two cities, an isolated photo."""
    base = pd.Timestamp("2026-03-14T12:00:00Z")

    def row(minutes, lat, lng, has):
        t = base + pd.Timedelta(minutes=minutes)
        return {"photo_id": f"d{minutes}", "person": "demo", "taken_utc": t.isoformat(),
                "has_gps": "true" if has else "false",
                "lat": "" if lat is None else str(lat), "lng": "" if lng is None else str(lng)}

    rows = [row(0, 40.7580, -73.9855, True), row(10, None, None, False),
            row(20, 40.7582, -73.9853, True),              # stay: middle photo should fill
            row(300, 42.3601, -71.0589, True), row(330, None, None, False),
            row(360, 40.7128, -74.0060, True),             # far apart: middle stays unfilled
            row(900, None, None, False)]                    # isolated: stays unfilled
    df = pd.DataFrame(rows)
    df["_utc"] = pd.to_datetime(df["taken_utc"], utc=True)
    df["_has"] = df["has_gps"] == "true"
    df["_lat"] = pd.to_numeric(df["lat"], errors="coerce")
    df["_lng"] = pd.to_numeric(df["lng"], errors="coerce")
    return df


def main():
    ap = argparse.ArgumentParser(description="Fill missing GPS from nearby-in-time photos.")
    ap.add_argument("--person", help="whose photos to use, e.g. kunal")
    ap.add_argument("--input", type=Path, default=DEFAULT_IN)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--max_gap_hours", type=float, default=1.0)
    ap.add_argument("--max_km", type=float, default=1.0)
    ap.add_argument("--eval", action="store_true", help="hold-out accuracy; writes results/")
    ap.add_argument("--demo", action="store_true", help="invented data, writes nothing")
    args = ap.parse_args()

    if args.demo:
        out = fill_frame(demo_frame(), args.max_gap_hours, args.max_km)
        for _, r in out.iterrows():
            print(f"  {r['photo_id']:>5}  {r['gps_source']:<7}  lat={r['_lat']:.4f}")
        return

    if not args.person:
        sys.exit("Please pass --person <name> (or --demo).")
    person = args.person.strip().lower()
    if not args.input.exists():
        sys.exit(f"Missing file: {args.input}")
    df = load_photos(args.input, person)
    if df.empty:
        sys.exit(f"No photos for '{person}' in {args.input}")

    if args.eval:
        res = holdout_eval(df, args.max_gap_hours, args.max_km)
        print(f"Hold-out: {res['holdout_n']} photos hidden, {res['filled_n']} filled "
              f"({res['fill_rate']:.0%}); median error {res['median_err_km']} km, "
              f"90th percentile {res['p90_err_km']} km")
        save_eval({"person": person, "max_gap_hours": args.max_gap_hours,
                   "max_km": args.max_km, **res}, DEFAULT_EVAL)
        return

    out = fill_frame(df, args.max_gap_hours, args.max_km)
    out["lat"] = out["_lat"].round(6).astype(str).replace("nan", "")
    out["lng"] = out["_lng"].round(6).astype(str).replace("nan", "")
    out["has_gps"] = out["_has"].map({True: "True", False: "False"})
    cols = [c for c in out.columns if not c.startswith("_")]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out[cols].to_csv(args.output, index=False)
    counts = out["gps_source"].value_counts()
    print(f"Photos: {len(out)}  exif GPS: {counts.get('exif', 0)}  "
          f"filled: {counts.get('filled', 0)}  still no GPS: {counts.get('none', 0)}")
    print(f"Wrote {args.output.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
