"""Tag photos with a few words (food, nature, city, ...) using CLIP, fully local (AGENTS.md P1).

Zero-shot: each photo is compared with the text "a photo of <label>" and keeps the labels the
model is confident about. Photos never leave this laptop; only the model weights are downloaded
once (from the open_clip model hub) and cached.

Inputs (local, never committed):
  data/processed/photos_clean.csv    photo_id,person,file_name,...
  data/raw/<person>/                 the original photos (HEIC/JPG), looked up by file_name
Output (local, never committed):
  data/processed/photo_tags.csv      photo_id,person,tags      tags = labels joined by ";"
Score output (aggregate only, safe to commit):
  results/tag_counts.csv             label,photos,share

Needs (not yet in requirements.txt, ask Jason before adding): torch, open_clip_torch.
They are imported only when tagging real photos, so --demo works without them.

Usage (run from the repo root):
  python backend/tag_clip.py --person kunal          # tag all of one person's photos
  python backend/tag_clip.py --person kunal --limit 20   # quick try on 20 photos
  python backend/tag_clip.py --demo                  # made-up scores, no model or files needed
"""

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parent.parent
PHOTOS_CSV = REPO_ROOT / "data" / "processed" / "photos_clean.csv"
RAW_DIR = REPO_ROOT / "data" / "raw"
OUT_TAGS = REPO_ROOT / "data" / "processed" / "photo_tags.csv"
OUT_COUNTS = REPO_ROOT / "results" / "tag_counts.csv"

MODEL_NAME, PRETRAINED = "ViT-B-32", "laion2b_s34b_b79k"
BATCH = 16

# Label -> text prompt. "people" is a tag too, so the public demo can leave those photos out.
LABELS = {
    "food": "food on a plate or a meal",
    "nature": "nature, trees, a park or a lake",
    "city": "a city street or buildings",
    "beach": "a beach or the sea",
    "mountain": "mountains or a hiking trail",
    "landmark": "a famous landmark or monument",
    "night": "a city or sky at night",
    "people": "a close-up of people or a selfie",
    "indoors": "inside a room or a building",
}
MIN_PROB = 0.30     # keep a label only if its probability is at least this
MAX_TAGS = 2        # and at most this many labels per photo
TEMPERATURE = 100.0  # CLIP's usual logit scale


def softmax(x):
    x = x - x.max(axis=1, keepdims=True)
    e = np.exp(x)
    return e / e.sum(axis=1, keepdims=True)


def assign_tags(similarities, labels, min_prob=MIN_PROB, max_tags=MAX_TAGS):
    """similarities: (n_photos, n_labels) cosine similarities. Returns one label list per photo."""
    probs = softmax(similarities * TEMPERATURE)
    tags = []
    for row in probs:
        best = np.argsort(row)[::-1][:max_tags]
        tags.append([labels[i] for i in best if row[i] >= min_prob])
    return tags


def find_photo(person, file_name):
    """Locate the original file under data/raw/<person>/ (any depth)."""
    direct = RAW_DIR / person / file_name
    if direct.exists():
        return direct
    for p in (RAW_DIR / person).rglob(file_name):
        return p
    return None


def load_model():
    """Import torch / open_clip only here, so --demo and the unit logic need neither."""
    try:
        import open_clip
        import torch
    except ImportError:
        sys.exit("tag_clip.py needs torch and open_clip_torch: pip install torch open_clip_torch")
    model, _, preprocess = open_clip.create_model_and_transforms(MODEL_NAME, pretrained=PRETRAINED)
    model.eval()
    tokenizer = open_clip.get_tokenizer(MODEL_NAME)
    return torch, model, preprocess, tokenizer


def embed_images(paths, torch, model, preprocess):
    from PIL import Image
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    keep, tensors = [], []
    for i, p in enumerate(paths):
        try:
            tensors.append(preprocess(Image.open(p).convert("RGB")))
            keep.append(i)
        except Exception:
            continue  # unreadable file: skipped, reported in the final count
    if not tensors:
        return keep, np.zeros((0, 0))
    with torch.no_grad():
        feats = model.encode_image(torch.stack(tensors))
        feats = feats / feats.norm(dim=-1, keepdim=True)
    return keep, feats.numpy()


def embed_text(labels, torch, model, tokenizer):
    with torch.no_grad():
        feats = model.encode_text(tokenizer([f"a photo of {LABELS[l]}" for l in labels]))
        feats = feats / feats.norm(dim=-1, keepdim=True)
    return feats.numpy()


def read_photos(person, limit):
    rows = []
    with open(PHOTOS_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["person"].strip().lower() == person:
                rows.append(row)
    return rows[:limit] if limit else rows


def save_outputs(results, person):
    """results: list of (photo_id, tags). Writes the local tag file and the aggregate counts."""
    OUT_TAGS.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_TAGS, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["photo_id", "person", "tags"])
        for pid, tags in results:
            w.writerow([pid, person, ";".join(tags)])
    counts = Counter(t for _, tags in results for t in tags)
    OUT_COUNTS.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_COUNTS, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["label", "photos", "share"])
        for label, n in counts.most_common():
            w.writerow([label, n, round(n / len(results), 3)])
    untagged = sum(1 for _, tags in results if not tags)
    print(f"Tagged {len(results)} photos ({untagged} with no confident tag)")
    for label, n in counts.most_common():
        print(f"  {label:<10}{n:>5}  {n / len(results):.0%}")
    print(f"Wrote {OUT_TAGS.relative_to(REPO_ROOT)} and {OUT_COUNTS.relative_to(REPO_ROOT)}")


def run_demo():
    """Invented similarity scores: check the threshold and max-tags logic."""
    labels = list(LABELS)
    rng = np.random.default_rng(0)
    sims = rng.normal(0.18, 0.01, (4, len(labels)))
    sims[0, labels.index("food")] = 0.30          # clear: food
    sims[1, labels.index("beach")] = 0.30         # two close winners: beach + nature
    sims[1, labels.index("nature")] = 0.30
    sims[2] = 0.20                                # nothing stands out: no tag
    sims[3, labels.index("city")] = 0.27          # clear: city
    for i, tags in enumerate(assign_tags(sims, labels)):
        print(f"  photo {i}: {tags or '(no confident tag)'}")


def main():
    ap = argparse.ArgumentParser(description="Tag photos with local CLIP.")
    ap.add_argument("--person", help="whose photos to tag, e.g. kunal")
    ap.add_argument("--limit", type=int, help="only the first N photos (quick try)")
    ap.add_argument("--demo", action="store_true", help="made-up scores, no model needed")
    args = ap.parse_args()

    if args.demo:
        run_demo()
        return
    if not args.person:
        sys.exit("Please pass --person <name> (or --demo).")
    person = args.person.strip().lower()
    if not PHOTOS_CSV.exists():
        sys.exit(f"Missing file: {PHOTOS_CSV}")

    photos = read_photos(person, args.limit)
    if not photos:
        sys.exit(f"No photos for '{person}' in {PHOTOS_CSV}")
    located = [(r["photo_id"], find_photo(person, r["file_name"])) for r in photos]
    located = [(pid, p) for pid, p in located if p is not None]
    print(f"Found {len(located)} of {len(photos)} photo files on disk")
    if not located:
        sys.exit("No original files found under data/raw/" + person)

    labels = list(LABELS)
    torch, model, preprocess, tokenizer = load_model()
    text = embed_text(labels, torch, model, tokenizer)
    results = []
    for start in range(0, len(located), BATCH):
        chunk = located[start:start + BATCH]
        keep, feats = embed_images([p for _, p in chunk], torch, model, preprocess)
        if not keep:
            continue
        for (pid, _), tags in zip([chunk[i] for i in keep], assign_tags(feats @ text.T, labels)):
            results.append((pid, tags))
    save_outputs(results, person)


if __name__ == "__main__":
    main()
