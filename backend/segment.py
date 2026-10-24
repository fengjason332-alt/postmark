"""Detect trips in the cleaned photo table: stay points, home detection and trip segmentation.

Reads data/processed/photos_clean.csv and writes (all git-ignored, local only)
  data/processed/trips_pred.csv   one row per detected trip,
  data/processed/stays.csv        every stay point (trip_id empty outside trips),
  data/processed/photo_trips.csv  photo_id -> trip_id for photos inside a trip.

Algorithm (defaults in DEFAULT_PARAMS, see AGENTS.md section 7):
  1. Stay points: consecutive GPS photos within stay_radius_km of the stay's running centroid
     and within stay_gap_hours of the stay's last photo are merged.
  2. Home: night photos (local hour >= 22 or < 6) are clustered with DBSCAN (haversine);
     the biggest cluster's centroid is home. Recomputed per calendar quarter ("quarterly")
     or computed once ("fixed").
  3. Day classes, per local date from its GPS photos only: away (at least one photo
     > trip_min_km from home, even if the date also has photos near home), home (ALL GPS
     photos within home_radius_km), otherwise neutral (e.g. only 25-100 km photos, a mix of
     near-home and 25-100 km photos, or no GPS photos).
  4. Trips: runs of away days; short neutral gaps without a home day are bridged.
If data/ground_truth.csv exists, each ground-truth trip is compared with the best
overlapping predicted trip (Jaccard day overlap). Precision / recall / F1 are NOT computed
here; they come from backend/validate.py.

Only dates, day counts, distances and overlaps are printed; never coordinates, the home
location, file names or raw rows.

Run from the repo root:  python backend/segment.py [--<param> value ...]
"""

import argparse
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

REPO_ROOT = Path(__file__).resolve().parent.parent

EARTH_RADIUS_KM = 6371.0088

DEFAULT_PARAMS = {
    "stay_radius_km": 1.0,
    "stay_gap_hours": 3.0,
    "home_mode": "quarterly",      # or "fixed"
    "home_eps_km": 1.0,
    "home_min_samples": 3,
    "min_night_photos": 10,
    "night_start_hour": 22,        # night = local hour >= 22 or < 6
    "night_end_hour": 6,
    "trip_min_km": 100.0,
    "home_radius_km": 25.0,
    "max_gap_days": 2,
    "min_days": 2,
}
HOME_MODES = ("quarterly", "fixed")
NO_HOME_MESSAGE = "no home could be detected"
MATCH_THRESHOLD_PCT = 50

TRIP_COLUMNS = ["person", "trip_id", "start_date", "end_date", "days", "max_distance_km",
                "photo_count", "n_stays", "cities"]
STAY_COLUMNS = ["trip_id", "stay_id", "start", "end", "lat", "lng", "photo_count"]
PHOTO_TRIP_COLUMNS = ["photo_id", "trip_id"]
MATCH_COLUMNS = ["gt_start", "gt_end", "pred_trip_id", "pred_start", "pred_end",
                 "overlap_pct", "matched"]

INPUT_REL = Path("data") / "processed" / "photos_clean.csv"
GROUND_TRUTH_REL = Path("data") / "ground_truth.csv"
TRIPS_REL = Path("data") / "processed" / "trips_pred.csv"
STAYS_REL = Path("data") / "processed" / "stays.csv"
PHOTO_TRIPS_REL = Path("data") / "processed" / "photo_trips.csv"

DAY_HOME = "home"
DAY_AWAY = "away"
DAY_NEUTRAL = "neutral"


def haversine_km(lat1, lng1, lat2, lng2):
    """Great-circle distance in km; inputs in decimal degrees, scalars or numpy arrays."""
    lat1, lng1, lat2, lng2 = (np.radians(np.asarray(v, dtype=float))
                              for v in (lat1, lng1, lat2, lng2))
    a = (np.sin((lat2 - lat1) / 2.0) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2.0) ** 2)
    return 2.0 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def resolve_params(params=None):
    """Merge a partial params dict over a copy of DEFAULT_PARAMS and validate it."""
    merged = dict(DEFAULT_PARAMS)
    if params:
        unknown = sorted(set(params) - set(DEFAULT_PARAMS))
        if unknown:
            raise ValueError("unknown parameter(s): " + ", ".join(unknown))
        merged.update(params)
    if merged["home_mode"] not in HOME_MODES:
        raise ValueError("home_mode must be one of: " + ", ".join(HOME_MODES))
    return merged


def quarter_of(day):
    return (day.year, (day.month - 1) // 3 + 1)


def quarters_between(first_day, last_day):
    """All calendar quarters from first_day's to last_day's, inclusive, in order."""
    year, quarter = quarter_of(first_day)
    end = quarter_of(last_day)
    out = []
    while (year, quarter) <= end:
        out.append((year, quarter))
        year, quarter = (year + 1, 1) if quarter == 4 else (year, quarter + 1)
    return out


def prepare_photos(photos_df):
    """Return a typed copy of a photos_clean frame, sorted in time order.

    Order key: taken_utc when present; otherwise the local taken_at time treated as UTC
    (known approximation: off by the photo's UTC offset, at most a few hours).
    Ties keep the original row order (column `pos`).
    """
    df = photos_df.reset_index(drop=True)
    taken_at = df["taken_at"].astype(str)
    taken_utc = df["taken_utc"].astype(str)
    has_gps = (df["has_gps"].astype(str).str.lower() == "true").to_numpy(dtype=bool)
    key_text = taken_utc.str.slice(0, 19).where(taken_utc != "", taken_at.str.slice(0, 19))
    lat = [float(v) if g else np.nan for v, g in zip(df["lat"], has_gps)]
    lng = [float(v) if g else np.nan for v, g in zip(df["lng"], has_gps)]
    out = pd.DataFrame({
        "photo_id": df["photo_id"].astype(str).to_numpy(dtype=object),
        "taken_at": taken_at.to_numpy(dtype=object),
        "day": [date.fromisoformat(d) for d in df["date"].astype(str)],
        "has_gps": has_gps,
        "lat": np.asarray(lat, dtype=float),
        "lng": np.asarray(lng, dtype=float),
        "order_time": pd.to_datetime(key_text, format="%Y-%m-%dT%H:%M:%S").to_numpy(),
        "local_hour": [int(t[11:13]) for t in taken_at],
        "pos": np.arange(len(df)),
    })
    return out.sort_values(["order_time", "pos"], kind="mergesort").reset_index(drop=True)


def find_stays(gps, params):
    """Group time-ordered GPS photos into stay points. Returns a list of dicts."""
    radius_km = params["stay_radius_km"]
    max_gap = pd.Timedelta(hours=params["stay_gap_hours"])
    stays = []
    current = None
    for row in gps.itertuples(index=False):
        if current is not None:
            n = len(current["photo_ids"])
            centroid_lat = current["lat_sum"] / n
            centroid_lng = current["lng_sum"] / n
            near = haversine_km(centroid_lat, centroid_lng, row.lat, row.lng) <= radius_km
            soon = (row.order_time - current["last_time"]) <= max_gap
            if near and soon:
                current["photo_ids"].append(row.photo_id)
                current["lat_sum"] += row.lat
                current["lng_sum"] += row.lng
                current["end"] = row.taken_at
                current["last_time"] = row.order_time
                continue
            stays.append(current)
        current = {"photo_ids": [row.photo_id], "lat_sum": row.lat, "lng_sum": row.lng,
                   "start": row.taken_at, "end": row.taken_at, "last_time": row.order_time}
    if current is not None:
        stays.append(current)
    for number, stay in enumerate(stays, start=1):
        n = len(stay["photo_ids"])
        stay["stay_id"] = f"stay_{number:05d}"
        stay["lat"] = stay["lat_sum"] / n
        stay["lng"] = stay["lng_sum"] / n
    return stays


def cluster_home(lats, lngs, params):
    """Centroid (lat, lng) of the biggest DBSCAN cluster, or None if everything is noise.

    Inputs must be in time order: ties on cluster size go to the cluster whose first
    photo is earliest.
    """
    lats = np.asarray(lats, dtype=float)
    lngs = np.asarray(lngs, dtype=float)
    if len(lats) == 0:
        return None
    coords = np.radians(np.column_stack([lats, lngs]))
    labels = DBSCAN(eps=params["home_eps_km"] / EARTH_RADIUS_KM,
                    min_samples=params["home_min_samples"], metric="haversine",
                    algorithm="ball_tree").fit_predict(coords)
    best_label, best_size = None, 0
    for label in pd.unique(labels):  # order of first appearance = time order
        if label == -1:
            continue
        size = int(np.sum(labels == label))
        if size > best_size:
            best_label, best_size = label, size
    if best_label is None:
        return None
    members = labels == best_label
    return (float(np.mean(lats[members])), float(np.mean(lngs[members])))


def detect_homes(prepared, params):
    """Return ({quarter: (lat, lng)} for every quarter spanned by the data, info dict).

    info = {"mode": "quarterly" | "fixed", "own": n, "reused": n}. Quarterly mode falls back
    to one fixed home when no quarter qualifies. Raises ValueError(NO_HOME_MESSAGE).
    """
    if len(prepared) == 0:
        raise ValueError(NO_HOME_MESSAGE)
    quarters = quarters_between(min(prepared["day"]), max(prepared["day"]))
    gps = prepared[prepared["has_gps"]]
    hours = gps["local_hour"]
    night = gps[(hours >= params["night_start_hour"]) | (hours < params["night_end_hour"])]
    night_lat = night["lat"].to_numpy()
    night_lng = night["lng"].to_numpy()

    if params["home_mode"] == "quarterly":
        night_quarters = [quarter_of(d) for d in night["day"]]
        own = {}
        for quarter in quarters:
            mask = np.array([q == quarter for q in night_quarters], dtype=bool)
            if int(mask.sum()) < params["min_night_photos"]:
                continue
            home = cluster_home(night_lat[mask], night_lng[mask], params)
            if home is not None:
                own[quarter] = home
        if own:
            first_home = own[next(q for q in quarters if q in own)]
            homes, previous = {}, first_home  # leading quarters backfill from the next home
            for quarter in quarters:
                previous = own.get(quarter, previous)
                homes[quarter] = previous
            return homes, {"mode": "quarterly", "own": len(own),
                           "reused": len(quarters) - len(own)}

    home = cluster_home(night_lat, night_lng, params)
    if home is None:
        raise ValueError(NO_HOME_MESSAGE)
    return {quarter: home for quarter in quarters}, {"mode": "fixed", "own": 0, "reused": 0}


def classify_days(prepared, homes, params):
    """Return ([(day, class)] for every calendar day spanned, GPS rows with dist_km).

    Per date, using GPS photos only and each photo's distance to that date's home:
    away if any photo is > trip_min_km; home if all photos are <= home_radius_km;
    otherwise neutral (including dates without GPS photos).
    """
    gps = prepared[prepared["has_gps"]].copy()
    home_points = [homes[quarter_of(d)] for d in gps["day"]]
    gps["dist_km"] = haversine_km(gps["lat"].to_numpy(), gps["lng"].to_numpy(),
                                  [h[0] for h in home_points], [h[1] for h in home_points])
    # A date is away if ANY GPS photo is far (a travel day often starts or ends with photos
    # near home); it is a home day only if ALL its GPS photos are near home.
    far_days = set(gps.loc[gps["dist_km"] > params["trip_min_km"], "day"])
    near_only_days = set(gps.groupby("day")["dist_km"].max()
                         .loc[lambda dist: dist <= params["home_radius_km"]].index)
    first_day, last_day = min(prepared["day"]), max(prepared["day"])
    classes = []
    for offset in range((last_day - first_day).days + 1):
        day = first_day + timedelta(days=offset)
        if day in far_days:
            classes.append((day, DAY_AWAY))
        elif day in near_only_days:
            classes.append((day, DAY_HOME))
        else:
            classes.append((day, DAY_NEUTRAL))
    return classes, gps


def segment_days(classes, params):
    """Turn calendar-ordered (day, class) pairs into [(start, end)] trips >= min_days long."""
    trips = []
    start = last_away = None
    for day, kind in classes:
        if kind == DAY_AWAY:
            # Every day between last_away and day is non-away; a home day would have closed
            # the trip already, so only the gap length decides whether to bridge.
            if start is not None and (day - last_away).days - 1 <= params["max_gap_days"]:
                last_away = day
            else:
                if start is not None:
                    trips.append((start, last_away))
                start = last_away = day
        elif kind == DAY_HOME and start is not None:
            trips.append((start, last_away))
            start = last_away = None
    if start is not None:
        trips.append((start, last_away))
    return [(s, e) for s, e in trips if (e - s).days + 1 >= params["min_days"]]


def run_segmentation(photos_df, params=None):
    """Full pipeline. Returns a dict with trips, stays, photo_trips, home_info, gps_photos."""
    params = resolve_params(params)
    person = ""
    if "person" in photos_df.columns and len(photos_df):
        person = str(photos_df["person"].iloc[0])
    prepared = prepare_photos(photos_df)
    stays = find_stays(prepared[prepared["has_gps"]], params)
    homes, home_info = detect_homes(prepared, params)
    classes, gps_dist = classify_days(prepared, homes, params)
    spans = segment_days(classes, params)

    day_to_trip = {}
    for start, end in spans:
        trip_id = f"trip_{start:%Y%m%d}"
        for offset in range((end - start).days + 1):
            day_to_trip[start + timedelta(days=offset)] = trip_id
    prepared["trip_id"] = [day_to_trip.get(d, "") for d in prepared["day"]]
    photo_trip = dict(zip(prepared["photo_id"], prepared["trip_id"]))

    stay_rows = []
    for stay in stays:
        # Plurality of the stay's photos that are inside a trip; ties -> earliest trip.
        counts = Counter(photo_trip[p] for p in stay["photo_ids"] if photo_trip[p])
        trip_id = ""
        if counts:
            top = max(counts.values())
            trip_id = min(t for t, c in counts.items() if c == top)
        stay_rows.append({"trip_id": trip_id, "stay_id": stay["stay_id"],
                          "start": stay["start"], "end": stay["end"], "lat": stay["lat"],
                          "lng": stay["lng"], "photo_count": len(stay["photo_ids"])})
    stays_df = pd.DataFrame(stay_rows, columns=STAY_COLUMNS)

    trip_rows = []
    for start, end in spans:
        trip_id = day_to_trip[start]
        in_trip = [start <= d <= end for d in gps_dist["day"]]
        trip_rows.append({
            "person": person, "trip_id": trip_id,
            "start_date": start.isoformat(), "end_date": end.isoformat(),
            "days": (end - start).days + 1,
            "max_distance_km": int(round(float(gps_dist.loc[in_trip, "dist_km"].max()))),
            "photo_count": int((prepared["trip_id"] == trip_id).sum()),
            "n_stays": int((stays_df["trip_id"] == trip_id).sum()),
            "cities": "",
        })
    trips_df = pd.DataFrame(trip_rows, columns=TRIP_COLUMNS)

    # prepared is in photo-time order; a stable sort by trip_id (trip_YYYYMMDD) keeps it.
    assigned = prepared[prepared["trip_id"] != ""]
    photo_trips_df = (assigned.sort_values("trip_id", kind="mergesort")[PHOTO_TRIP_COLUMNS]
                      .reset_index(drop=True))
    return {"trips": trips_df, "stays": stays_df, "photo_trips": photo_trips_df,
            "home_info": home_info, "gps_photos": int(prepared["has_gps"].sum())}


def detect_trips(photos_df, params=None):
    """Return (trips_df, stays_df, photo_trip_df). No file I/O, no printing."""
    result = run_segmentation(photos_df, params)
    return result["trips"], result["stays"], result["photo_trips"]


def match_ground_truth(trips_df, gt_df, person):
    """Best predicted trip per ground-truth trip of `person` (Jaccard overlap of days)."""
    gt = gt_df[gt_df["person"].astype(str) == person]
    gt = gt.sort_values("start_date", kind="mergesort")
    preds = sorted((date.fromisoformat(str(s)), date.fromisoformat(str(e)), str(t))
                   for t, s, e in zip(trips_df["trip_id"], trips_df["start_date"],
                                      trips_df["end_date"]))
    rows = []
    for gt_start_text, gt_end_text in zip(gt["start_date"], gt["end_date"]):
        gt_start = date.fromisoformat(str(gt_start_text))
        gt_end = date.fromisoformat(str(gt_end_text))
        gt_days = (gt_end - gt_start).days + 1
        if gt_days < 1:
            raise ValueError("ground truth trip ends before it starts")
        best = None
        for pred_start, pred_end, trip_id in preds:
            inter = (min(gt_end, pred_end) - max(gt_start, pred_start)).days + 1
            if inter <= 0:
                continue
            union = gt_days + (pred_end - pred_start).days + 1 - inter
            pct = (200 * inter + union) // (2 * union)  # round half up, exact integers
            if best is None or pct > best[0]:  # preds are in start order: ties keep earliest
                best = (pct, trip_id, pred_start, pred_end)
        row = {"gt_start": gt_start.isoformat(), "gt_end": gt_end.isoformat(),
               "pred_trip_id": "", "pred_start": "", "pred_end": "",
               "overlap_pct": 0, "matched": False}
        if best is not None:
            pct, trip_id, pred_start, pred_end = best
            row.update({"pred_trip_id": trip_id, "pred_start": pred_start.isoformat(),
                        "pred_end": pred_end.isoformat(), "overlap_pct": int(pct),
                        "matched": pct >= MATCH_THRESHOLD_PCT})
        rows.append(row)
    return pd.DataFrame(rows, columns=MATCH_COLUMNS)


def build_parser():
    parser = argparse.ArgumentParser(description="Detect trips from photos_clean.csv.")
    for key, default in DEFAULT_PARAMS.items():
        if key == "home_mode":
            parser.add_argument(f"--{key}", choices=HOME_MODES, default=default)
        else:
            parser.add_argument(f"--{key}", type=type(default), default=default)
    return parser


def _fail(message):
    print(f"error: {message}")
    sys.exit(1)


def format_report(result, matches):
    """Console lines: counts, dates, days, distances and overlaps only."""
    trips = result["trips"]
    info = result["home_info"]
    lines = [f"GPS photos: {result['gps_photos']}", f"Stays: {len(result['stays'])}"]
    if info["mode"] == "fixed":
        lines.append("Quarters: fixed home")
    else:
        lines.append(f"Quarters: {info['own']} with own home, {info['reused']} reused")
    lines.append(f"Trips: {len(trips)} ({int(trips['days'].sum())} days, "
                 f"{len(result['photo_trips'])} photos assigned)")
    for row in trips.itertuples(index=False):
        lines.append(f"  {row.trip_id}  {row.start_date} -> {row.end_date}  "
                     f"{row.days} days  {row.max_distance_km} km")
    if matches is None:
        lines.append("Ground truth: not found")
    else:
        lines.append(f"Ground truth ({len(matches)} trips):")
        for row in matches.itertuples(index=False):
            best = row.pred_trip_id or "none"
            status = "matched" if row.matched else "not matched"
            lines.append(f"  {row.gt_start} -> {row.gt_end}  best: {best} "
                         f"({row.overlap_pct}%)  {status}")
        lines.append(f"Matched: {int(matches['matched'].sum())} of {len(matches)}")
    return lines


def main(argv=None, root=REPO_ROOT):
    args = build_parser().parse_args(argv)
    params = {key: getattr(args, key) for key in DEFAULT_PARAMS}
    root = Path(root)

    try:
        photos = pd.read_csv(root / INPUT_REL, dtype=str, keep_default_na=False)
    except Exception:
        _fail(f"could not read {INPUT_REL.as_posix()}")

    try:
        result = run_segmentation(photos, params)
    except ValueError as exc:
        _fail(NO_HOME_MESSAGE if str(exc) == NO_HOME_MESSAGE else "segmentation failed")
    except Exception:
        _fail("segmentation failed")

    matches = None
    if (root / GROUND_TRUTH_REL).exists():
        try:
            gt = pd.read_csv(root / GROUND_TRUTH_REL, dtype=str, keep_default_na=False)
            person = str(photos["person"].iloc[0])
            matches = match_ground_truth(result["trips"], gt, person)
        except Exception:
            _fail(f"could not read {GROUND_TRUTH_REL.as_posix()}")

    try:
        for frame, rel in ((result["trips"], TRIPS_REL), (result["stays"], STAYS_REL),
                           (result["photo_trips"], PHOTO_TRIPS_REL)):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(root / rel, index=False)
    except Exception:
        _fail("could not write outputs")

    print("\n".join(format_report(result, matches)))


if __name__ == "__main__":
    main()
