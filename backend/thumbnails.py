"""Make EXIF-free WebP thumbnails for every photo that belongs to a trip.

Photos to process = the union of photo_ids over data/processed/photo_trips_r{R}.csv
for every R in segment.RADIUS_OPTIONS_KM (missing files are skipped). For each photo
the source file is located through data/raw/photos_raw_<person>_all.csv, read once,
checked against its photo_id (SHA-1 of the content, as clean.py computed it), and
written to

    frontend/public/data/thumbs/<photo_id>_s.webp   400 px wide (grids)
    frontend/public/data/thumbs/<photo_id>_l.webp   1600 px long edge (viewer)

Images are never upscaled, rotated upright using the EXIF orientation, and rebuilt
from raw pixels so no EXIF / XMP / ICC / GPS metadata survives. Files are written
atomically, and photos whose two thumbnails already exist are skipped without reading
the source.

The original photos live in the user's Photos library, so this script must be run by
the user from a terminal that is allowed to read that library (not from an AI sandbox).

Only counts are printed; never file names, paths, times or coordinates.

Run from the repo root:  .venv/bin/python backend/thumbnails.py [person]
"""

import hashlib
import io
import os
import re
import sys
from pathlib import Path

import pandas as pd
import pillow_heif
from PIL import Image, ImageCms, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))

import segment  # noqa: E402  (for RADIUS_OPTIONS_KM)

pillow_heif.register_heif_opener()

REPO_ROOT = Path(__file__).resolve().parent.parent

LARGE_LONG_EDGE = 1600
SMALL_WIDTH = 400
WEBP_QUALITY = 80
WEBP_METHOD = 4
SRGB_PROFILE = ImageCms.createProfile("sRGB")
PERSON_PATTERN = re.compile(r"[a-z0-9_-]+")
THUMBS_REL = Path("frontend") / "public" / "data" / "thumbs"
LOCAL_TIME_LEN = 19  # 'YYYY-MM-DDTHH:MM:SS' / 'YYYY:MM:DD HH:MM:SS'


def target_size(width, height):
    """Return ((small_w, small_h), (large_w, large_h)); never upscales."""
    large_scale = min(1.0, LARGE_LONG_EDGE / max(width, height))
    large = (max(1, round(width * large_scale)), max(1, round(height * large_scale)))
    small_scale = min(1.0, SMALL_WIDTH / width)
    small = (max(1, round(width * small_scale)), max(1, round(height * small_scale)))
    return small, large


def to_srgb(img, icc_profile):
    """Convert pixels from an embedded ICC profile (e.g. Display P3) to sRGB.

    Returns an RGB image; on any failure falls back to a plain RGB conversion.
    """
    img = img.convert("RGB")
    if not icc_profile:
        return img
    try:
        source = ImageCms.ImageCmsProfile(io.BytesIO(icc_profile))
        return ImageCms.profileToProfile(img, source, SRGB_PROFILE, outputMode="RGB")
    except Exception:
        return img


def make_thumbs(img):
    """Return (small, large) metadata-free sRGB images from an opened Pillow image."""
    icc_profile = img.info.get("icc_profile")
    img = to_srgb(ImageOps.exif_transpose(img), icc_profile)
    # Rebuild from raw pixels so nothing but pixel data (no ICC/EXIF/XMP) carries over.
    pixels = Image.frombytes("RGB", img.size, img.tobytes())
    small_size, large_size = target_size(*pixels.size)
    large = pixels if large_size == pixels.size else pixels.resize(large_size, Image.LANCZOS)
    small = pixels if small_size == pixels.size else pixels.resize(small_size, Image.LANCZOS)
    return small, large


def raw_time_key(taken_at):
    """'2026-03-14T15:32:08-04:00' -> '2026:03:14 15:32:08' (matches DateTimeOriginal[:19])."""
    local = taken_at[:LOCAL_TIME_LEN]
    return local[:10].replace("-", ":") + " " + local[11:]


def build_raw_index(raw_df):
    """Map (FileName, DateTimeOriginal[:19]) -> list of SourceFile strings."""
    index = {}
    for name, stamp, source in zip(raw_df["FileName"], raw_df["DateTimeOriginal"],
                                   raw_df["SourceFile"]):
        index.setdefault((name, stamp[:LOCAL_TIME_LEN]), []).append(source)
    return index


def find_sources(photo_row, raw_index):
    """SourceFile candidates for a photos_clean row (file_name, taken_at); [] if none."""
    if photo_row is None:
        return []
    file_name, taken_at = photo_row
    return raw_index.get((file_name, raw_time_key(taken_at)), [])


def resolve_source(source_file, root):
    path = Path(source_file)
    return path if path.is_absolute() else root / path


def read_photo(photo_id, sources, root):
    """Return ('ok', bytes) or (status, None), status in not_found / hash_mismatch / unreadable."""
    status = "not_found"
    for source in sources:
        if not source:
            continue
        try:
            data = resolve_source(source, root).read_bytes()
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            status = "unreadable"
            continue
        if "p_" + hashlib.sha1(data).hexdigest()[:10] == photo_id:
            return "ok", data
        if status == "not_found":
            status = "hash_mismatch"
    return status, None


def save_webp_atomic(img, path):
    """Write to a temp name in the same folder, then os.replace; no metadata arguments."""
    tmp = path.with_name("." + path.name + ".tmp")
    try:
        img.save(tmp, format="WEBP", quality=WEBP_QUALITY, method=WEBP_METHOD)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def trip_photo_ids(root):
    """Sorted union of photo_ids over all photo_trips_r{R}.csv; None if no file exists."""
    ids = set()
    found = False
    for radius in segment.RADIUS_OPTIONS_KM:
        path = root / "data" / "processed" / f"photo_trips_r{radius}.csv"
        if not path.exists():
            continue
        found = True
        ids.update(pd.read_csv(path, dtype=str, keep_default_na=False)["photo_id"])
    return sorted(ids) if found else None


def process(ids, clean_df, raw_index, thumbs_dir, root):
    counts = {"written": 0, "skipped": 0, "not_found": 0, "hash_mismatch": 0, "unreadable": 0}
    clean_rows = dict(zip(clean_df["photo_id"], zip(clean_df["file_name"], clean_df["taken_at"])))
    for photo_id in ids:
        small_path = thumbs_dir / f"{photo_id}_s.webp"
        large_path = thumbs_dir / f"{photo_id}_l.webp"
        if small_path.exists() and large_path.exists():
            counts["skipped"] += 1
            continue
        sources = find_sources(clean_rows.get(photo_id), raw_index)
        status, data = read_photo(photo_id, sources, root)
        if status != "ok":
            counts[status] += 1
            continue
        try:
            with Image.open(io.BytesIO(data)) as img:
                small, large = make_thumbs(img)
            save_webp_atomic(small, small_path)
            save_webp_atomic(large, large_path)
        except Exception:
            for path in (small_path, large_path):
                if path.exists():
                    path.unlink()
            counts["unreadable"] += 1
            continue
        counts["written"] += 1
    return counts


def main(argv=None, root=REPO_ROOT):
    args = sys.argv[1:] if argv is None else argv
    person = args[0] if args else "jason"
    if not PERSON_PATTERN.fullmatch(person):
        print("error: person must match [a-z0-9_-]+")
        sys.exit(1)

    try:
        ids = trip_photo_ids(root)
        if ids is not None:
            clean_df = pd.read_csv(root / "data" / "processed" / "photos_clean.csv",
                                   dtype=str, keep_default_na=False)
            raw_df = pd.read_csv(root / "data" / "raw" / f"photos_raw_{person}_all.csv",
                                 dtype=str, keep_default_na=False)
            for column in ("SourceFile", "FileName", "DateTimeOriginal"):
                if column not in raw_df.columns:
                    raw_df[column] = ""
            for column in ("photo_id", "file_name", "taken_at"):
                if column not in clean_df.columns:
                    clean_df[column] = ""
            raw_index = build_raw_index(raw_df)
    except Exception:
        print("error: could not read inputs")
        sys.exit(1)
    if ids is None:
        print("error: no data/processed/photo_trips_r*.csv found; run backend/segment.py first")
        sys.exit(1)

    thumbs_dir = root / THUMBS_REL
    try:
        thumbs_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        print("error: could not create thumbnail folder")
        sys.exit(1)

    counts = process(ids, clean_df, raw_index, thumbs_dir, root)
    print(f"Photos in trips: {len(ids)}")
    print(f"Written: {counts['written']}")
    print(f"Skipped (already exist): {counts['skipped']}")
    print(f"Not found: {counts['not_found']}")
    print(f"Hash mismatch: {counts['hash_mismatch']}")
    print(f"Unreadable: {counts['unreadable']}")


if __name__ == "__main__":
    main()
