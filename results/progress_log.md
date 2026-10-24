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

### Next
- Jason: count one-day trips; make the distance radius configurable instead of a fixed 100 km.
- DS: re-run validation after his push; compare several radius values.
- Idea proposed: per-outing trip score + ask the user when unsure (needs all three humans to agree, schema_version 1.1).
- After 18:00 (P1): `fill_gps.py`, `tag_clip.py`.
