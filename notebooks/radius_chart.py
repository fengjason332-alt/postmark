"""Chart: home-circle radius vs F1, from results/scores.csv (scores only, no GPS).

Run from the repo root:  python notebooks/radius_chart.py
Writes results/radius_vs_f1.png
"""

import csv
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO_ROOT = Path(__file__).resolve().parent.parent
SCORES = REPO_ROOT / "results" / "scores.csv"
OUT = REPO_ROOT / "results" / "radius_vs_f1.png"

COLORS = {"ours": "#2a6f97", "baseline": "#c4741a"}
LABELS = {"ours": "Our algorithm", "baseline": "Baseline (any far photo = travel day)"}


def load_f1(path):
    """Return {method: {radius_km: mean F1 across people}}."""
    cells = defaultdict(lambda: defaultdict(list))
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cells[row["method"]][int(row["threshold_km"])].append(float(row["f1"]))
    return {m: {r: sum(v) / len(v) for r, v in by_r.items()} for m, by_r in cells.items()}


def main():
    f1 = load_f1(SCORES)
    people = {row["person"] for row in csv.DictReader(open(SCORES, newline="", encoding="utf-8"))}

    fig, ax = plt.subplots(figsize=(7, 4.2))
    for method in ("baseline", "ours"):
        if method not in f1:
            continue
        radii = sorted(f1[method])
        ax.plot(radii, [f1[method][r] for r in radii], marker="o", linewidth=2,
                color=COLORS[method], label=LABELS[method])
    ax.set_xscale("log")
    all_radii = sorted({r for m in f1.values() for r in m})
    ax.set_xticks(all_radii)
    ax.set_xticklabels([str(r) for r in all_radii])
    ax.set_ylim(0, 1.05)
    ax.set_xlabel("Home circle radius (km)")
    ax.set_ylabel("F1 score")
    ax.set_title("Radius vs. trip-detection accuracy")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right", frameon=False)
    ax.text(0.01, 0.02, f"{len(people)} person(s), small labeled set; scores are preliminary",
            transform=ax.transAxes, fontsize=8, color="#555")
    fig.tight_layout()
    fig.savefig(OUT, dpi=160)
    print(f"Saved {OUT.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
