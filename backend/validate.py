"""Validate trip detection against hand-labeled trips (AGENTS.md P0-4).

Compares predicted trips with each person's ground truth and reports
precision, recall and F1, for our algorithm and for a simple baseline.

Inputs (all local, never committed):
  data/ground_truth.csv              person,start_date,end_date,cities
  data/processed/trips_pred.csv      person,trip_id,start_date,end_date,cities,photo_count
  data/processed/photos_clean.csv    photo_id,person,file_name,taken_at,date,lat,lng,has_gps
                                     (only needed for the baseline)

Output (scores only, no GPS, safe to commit):
  results/scores.csv                 one row per (person, method)

Matching rule:
  A predicted trip and a true trip match when
  overlap_days / union_days >= 0.5 (both date ranges inclusive).
  Matching is one-to-one: best overlaps are paired first.

Baseline:
  "Any day with a photo > 100 km from home is a travel day."
  Consecutive travel days are merged into one trip so it can be
  scored the same way as our algorithm.

Usage (run from the repo root):
  python backend/validate.py --person kunal
  python backend/validate.py --person kunal --details   # print matches in the terminal only
  python backend/validate.py --demo                     # made-up data, no files needed

Uses only the Python standard library.
"""

import argparse
import csv
import math
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TRUTH = REPO_ROOT / "data" / "ground_truth.csv"
DEFAULT_PRED = REPO_ROOT / "data" / "processed" / "trips_pred.csv"
DEFAULT_PHOTOS = REPO_ROOT / "data" / "processed" / "photos_clean.csv"
DEFAULT_OUT = REPO_ROOT / "results" / "scores.csv"

MATCH_THRESHOLD = 0.5
SCORE_COLUMNS = ["person", "method", "threshold_km", "n_pred", "n_true",
                 "true_pos", "precision", "recall", "f1"]


# ---------------------------------------------------------------- loading

def parse_day(text):
    return date.fromisoformat(text.strip()[:10])


def load_trips(path, person=None):
    """Read a trips CSV into a list of dicts with start/end as dates."""
    trips = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            who = row["person"].strip().lower()
            if person and who != person:
                continue
            start, end = parse_day(row["start_date"]), parse_day(row["end_date"])
            if end < start:
                start, end = end, start
            trips.append({"person": who, "start": start, "end": end,
                          "cities": row.get("cities", "").strip()})
    return sorted(trips, key=lambda t: t["start"])


def load_photos(path, person=None):
    """Read photos_clean.csv, keeping only photos with GPS."""
    photos = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            who = row["person"].strip().lower()
            if person and who != person:
                continue
            if str(row.get("has_gps", "")).strip().lower() not in ("true", "1", "yes"):
                continue
            if not row.get("lat") or not row.get("lng"):
                continue
            photos.append({"person": who,
                           "taken_at": row["taken_at"].strip(),
                           "date": parse_day(row["date"]),
                           "lat": float(row["lat"]),
                           "lng": float(row["lng"])})
    return photos


# ---------------------------------------------------------------- matching

def overlap_ratio(a, b):
    """Overlap days / union days, both ranges inclusive."""
    overlap = (min(a["end"], b["end"]) - max(a["start"], b["start"])).days + 1
    if overlap <= 0:
        return 0.0
    union = (max(a["end"], b["end"]) - min(a["start"], b["start"])).days + 1
    return overlap / union


def match_trips(pred, truth, threshold=MATCH_THRESHOLD):
    """One-to-one greedy matching by best overlap. Returns list of (i_pred, i_true, ratio)."""
    candidates = []
    for i, p in enumerate(pred):
        for j, t in enumerate(truth):
            r = overlap_ratio(p, t)
            if r >= threshold:
                candidates.append((r, i, j))
    candidates.sort(reverse=True)
    used_p, used_t, pairs = set(), set(), []
    for r, i, j in candidates:
        if i not in used_p and j not in used_t:
            used_p.add(i)
            used_t.add(j)
            pairs.append((i, j, r))
    return pairs


def score(pred, truth):
    pairs = match_trips(pred, truth)
    tp = len(pairs)
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(truth) if truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"n_pred": len(pred), "n_true": len(truth), "true_pos": tp,
            "precision": round(precision, 3), "recall": round(recall, 3),
            "f1": round(f1, 3), "pairs": pairs}


# ---------------------------------------------------------------- baseline

def haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def local_hour(taken_at):
    """Hour in the photo's local time (the ISO string already carries local time)."""
    return datetime.fromisoformat(taken_at).hour


def quarter_key(d):
    return (d.year, (d.month - 1) // 3)


def find_home(photos):
    """Densest ~10 km cell of night photos (22:00-06:00), per quarter.

    Returns {quarter_key: (lat, lng)} plus a fallback under key None.
    Mirrors the pipeline's home rule so the baseline is a fair comparison.
    """
    def densest(points):
        cells = Counter((round(p["lat"], 1), round(p["lng"], 1)) for p in points)
        best = cells.most_common(1)[0][0]
        inside = [p for p in points if (round(p["lat"], 1), round(p["lng"], 1)) == best]
        return (sum(p["lat"] for p in inside) / len(inside),
                sum(p["lng"] for p in inside) / len(inside))

    night = [p for p in photos if local_hour(p["taken_at"]) >= 22 or local_hour(p["taken_at"]) < 6]
    pool = night or photos
    homes = {None: densest(pool)}
    by_q = defaultdict(list)
    for p in pool:
        by_q[quarter_key(p["date"])].append(p)
    for q, pts in by_q.items():
        if len(pts) >= 5:  # too few night photos -> use the overall home
            homes[q] = densest(pts)
    return homes


def baseline_trips(photos, threshold_km=100):
    """Any day with a photo > threshold_km from home is a travel day; merge consecutive days."""
    if not photos:
        return []
    homes = find_home(photos)
    travel_days = set()
    for p in photos:
        home = homes.get(quarter_key(p["date"]), homes[None])
        if haversine_km(p["lat"], p["lng"], *home) > threshold_km:
            travel_days.add(p["date"])
    trips = []
    for d in sorted(travel_days):
        if trips and d - trips[-1]["end"] == timedelta(days=1):
            trips[-1]["end"] = d
        else:
            trips.append({"person": photos[0]["person"], "start": d, "end": d, "cities": ""})
    return trips


# ---------------------------------------------------------------- output

def print_table(rows):
    print(f"\n{'person':<10}{'method':<12}{'pred':>6}{'true':>6}{'TP':>5}"
          f"{'precision':>11}{'recall':>8}{'F1':>7}")
    for r in rows:
        print(f"{r['person']:<10}{r['method']:<12}{r['n_pred']:>6}{r['n_true']:>6}"
              f"{r['true_pos']:>5}{r['precision']:>11.3f}{r['recall']:>8.3f}{r['f1']:>7.3f}")
    print()


def print_details(label, pred, truth, pairs):
    """Terminal-only listing for error analysis. Never written to a file."""
    matched_p = {i for i, _, _ in pairs}
    matched_t = {j for _, j, _ in pairs}
    print(f"--- {label} ---")
    for i, j, r in sorted(pairs, key=lambda x: truth[x[1]]["start"]):
        print(f"  MATCH  true {truth[j]['start']}..{truth[j]['end']} {truth[j]['cities']}"
              f"  <->  pred {pred[i]['start']}..{pred[i]['end']}  (overlap {r:.2f})")
    for j, t in enumerate(truth):
        if j not in matched_t:
            print(f"  MISSED true {t['start']}..{t['end']} {t['cities']}")
    for i, p in enumerate(pred):
        if i not in matched_p:
            print(f"  EXTRA  pred {p['start']}..{p['end']} {p['cities']}")
    print()


def save_scores(rows, out_path):
    """Write scores, replacing earlier rows for the same (person, method, threshold)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    keep = []
    new_keys = {(r["person"], r["method"], str(r["threshold_km"])) for r in rows}
    if out_path.exists():
        with open(out_path, newline="", encoding="utf-8") as f:
            for old in csv.DictReader(f):
                if (old["person"], old["method"], old["threshold_km"]) not in new_keys:
                    keep.append(old)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SCORE_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in keep + rows:
            w.writerow(r)
    print(f"Saved scores to {out_path.relative_to(REPO_ROOT)}")


# ---------------------------------------------------------------- demo

def demo_data():
    """Invented data: home in Boston, 3 real trips, 1 day trip, 1 layover."""
    boston, nyc, tokyo, montreal, providence = (
        (42.36, -71.06), (40.71, -74.01), (35.68, 139.69), (45.50, -73.57), (41.82, -71.41))
    photos = []

    def add(day, hour, place):
        photos.append({"person": "demo", "date": day,
                       "taken_at": f"{day}T{hour:02d}:00:00-04:00",
                       "lat": place[0], "lng": place[1]})

    start = date(2026, 1, 1)
    for k in range(200):  # daily life at home, including night photos
        d = start + timedelta(days=k)
        add(d, 23, boston)
        add(d, 14, boston)
    for k in range(4):     # NYC 2026-03-14..17
        add(date(2026, 3, 14) + timedelta(days=k), 15, nyc)
    for k in range(7):     # Tokyo 2026-05-02..08
        add(date(2026, 5, 2) + timedelta(days=k), 12, tokyo)
    for k in range(3):     # Montreal 2026-06-19..21
        add(date(2026, 6, 19) + timedelta(days=k), 18, montreal)
    add(date(2026, 4, 11), 13, nyc)  # day trip, back home that night (not a real trip)

    truth = [
        {"person": "demo", "start": date(2026, 3, 14), "end": date(2026, 3, 17), "cities": "New York"},
        {"person": "demo", "start": date(2026, 5, 1), "end": date(2026, 5, 9), "cities": "Tokyo"},
        {"person": "demo", "start": date(2026, 6, 19), "end": date(2026, 6, 21), "cities": "Montreal"},
    ]
    # Pretend output of our algorithm: gets NYC and Tokyo, misses Montreal,
    # and splits nothing; one false trip to Providence (55 km, should not count).
    pred = [
        {"person": "demo", "start": date(2026, 3, 14), "end": date(2026, 3, 17), "cities": "New York"},
        {"person": "demo", "start": date(2026, 5, 2), "end": date(2026, 5, 8), "cities": "Tokyo"},
        {"person": "demo", "start": date(2026, 2, 7), "end": date(2026, 2, 8), "cities": "Providence"},
    ]
    return photos, truth, pred


# ---------------------------------------------------------------- main

def run(person, pred, truth, photos, threshold_km, details):
    rows = []
    ours = score(pred, truth)
    rows.append({"person": person, "method": "ours", "threshold_km": threshold_km, **ours})
    if details:
        print_details(f"{person} / ours", pred, truth, ours["pairs"])
    if photos:
        base_pred = baseline_trips(photos, threshold_km)
        base = score(base_pred, truth)
        rows.append({"person": person, "method": "baseline", "threshold_km": threshold_km, **base})
        if details:
            print_details(f"{person} / baseline", base_pred, truth, base["pairs"])
    else:
        print("No photos for the baseline (photos_clean.csv missing or empty); skipping it.")
    print_table(rows)
    return rows


def main():
    ap = argparse.ArgumentParser(description="Score trip detection against ground truth.")
    ap.add_argument("--person", help="whose trips to score, e.g. kunal")
    ap.add_argument("--truth", type=Path, default=DEFAULT_TRUTH)
    ap.add_argument("--pred", type=Path, default=DEFAULT_PRED)
    ap.add_argument("--photos", type=Path, default=DEFAULT_PHOTOS)
    ap.add_argument("--km", type=int, default=100, help="baseline distance threshold")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--details", action="store_true",
                    help="print each match / miss / extra trip (terminal only)")
    ap.add_argument("--demo", action="store_true", help="run on invented data, write nothing")
    args = ap.parse_args()

    if args.demo:
        photos, truth, pred = demo_data()
        run("demo", pred, truth, photos, args.km, details=True)
        return

    if not args.person:
        sys.exit("Please pass --person <name> (or --demo).")
    person = args.person.strip().lower()

    for path in (args.truth, args.pred):
        if not path.exists():
            sys.exit(f"Missing file: {path}")
    truth = load_trips(args.truth, person)
    pred = load_trips(args.pred, person)
    if not truth:
        sys.exit(f"No ground-truth trips for '{person}' in {args.truth}")
    photos = load_photos(args.photos, person) if args.photos.exists() else []

    rows = run(person, pred, truth, photos, args.km, args.details)
    save_scores(rows, args.out)


if __name__ == "__main__":
    main()
