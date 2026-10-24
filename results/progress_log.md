# Postmark — data science progress log

Facts only, for the Devpost write-up and slides. No photos, GPS or personal trip details.
All scores come from real runs of `backend/validate.py` (saved in `results/scores.csv`).

## Sat Oct 24, 2026

| Time (EDT) | What happened |
| --- | --- |
| ~12:00 | Repo set up; agent rules (AGENTS.md) and mock data added |
| ~13:00 | Backend: `clean.py` filters invalid dates/GPS, merges burst shots, hashes photos |
| ~13:07 | Backend: `export_for_ds.py` makes a coarse (2-decimal) copy for data science |
| ~13:32 | Backend: `segment.py` v1 (stay points, quarterly home, trip segmentation) |
| ~13:50 | DS: `validate.py` (precision / recall / F1 + 100 km baseline) pushed |

### First validation run (one person, 258 photos, 4 hand-labeled trips)

| Method | Trips matched | Precision | Recall | F1 |
| --- | --- | --- | --- | --- |
| Our algorithm (v1) | 0 of 4 | 0.00 | 0.00 | 0.00 |
| Baseline (>100 km from home = travel day) | 2 of 4 | 0.67 | 0.50 | 0.57 |

Pipeline counts for this run: 277 photos in, 258 after cleaning, 225 with GPS.

### What we learned
- v1 only detects overnight trips, so one-day trips were missed.
- A long trip was found only for its first week (21% date overlap, below the 50% match rule), so it did not count as a match.
- Ground truth had one wrong year; fixing it moved the baseline from F1 0.29 to 0.57. Labels matter.
- Only 4 labeled trips: too few to tune reliably; test on more photo sets.

### Second validation run (after Jason: day trips count + configurable home radius, schema 1.1)

| Radius (km) | Trips matched | Precision | Recall | F1 |
| --- | --- | --- | --- | --- |
| 10, 25, 50, 100, 200 (all identical) | 2 of 4 | 0.67 | 0.50 | 0.57 |

- Our algorithm went from 0 of 4 to 2 of 4 and now ties the baseline (F1 0.57).
- Score is flat across radii: on this small set, trips are either near home or very far.
- Still missed: one trip with no detection, and one long trip found only for its first week.
- Direction: user-set "home circle" slider (5 radii) replaces the trip-score idea for now.

### Radius chart and GPS filling (P1, started early)

- Radius vs F1 chart: `results/radius_vs_f1.png` (script `notebooks/radius_chart.py`). Flat at F1 0.57 for every radius; one person's data cannot pick a default.
- `backend/fill_gps.py` fills missing GPS from photos taken close in time, and refuses when the neighbours are far apart (the person was moving).
- Hold-out test (hide GPS on 45 photos that have it, re-fill, compare): 91% filled, median error 0.002 km, 90th percentile 0.04 km (`results/fill_gps_eval.csv`).
- On the real GPS-less photos it filled only 2 of 33: they have no GPS photo within an hour. Accurate, but small gain.
- Backend now has `geocode.py` (city names). Still missing for real data on the globe: `build_json.py`.

### CLIP photo tags (P1)

- `backend/tag_clip.py` tags each photo with up to two labels using CLIP, run fully locally (only the model weights are downloaded; photos never leave the laptop).
- Needs `torch` and `open_clip_torch`; Jason agreed to add them to `backend/requirements.txt`.
- Run on one person's 258 photos (`results/tag_counts.csv`): people 47%, food 19%, landmark 18%, indoors 11%, city 7%, nature 5%, night 3%, beach 0.4% (shares sum above 100% because of two tags per photo).
- The "people" tag lets the public demo leave out photos with people.
- Tag accuracy has not been measured (no labeled tags), so no accuracy number is claimed.
- Backend also added `thumbnails.py`; still missing for real data on the globe: `build_json.py`.
- Draft slides for the pitch exist (private Artifact), with every number taken from `results/`.

### Next
- Jason: count one-day trips; make the distance radius configurable instead of a fixed 100 km.
- DS: re-run validation after his push; compare several radius values.
- Idea proposed: per-outing trip score + ask the user when unsure (needs all three humans to agree, schema_version 1.1).
- After 18:00 (P1): `fill_gps.py`, `tag_clip.py`.
