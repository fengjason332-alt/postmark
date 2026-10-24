"""Unit tests for backend/thumbnails.py (synthetic images only). Run from the repo root:

    .venv/bin/python -m unittest discover -s backend/tests -v
"""

import contextlib
import hashlib
import io
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd
import pillow_heif
from PIL import Image, ImageCms

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import thumbnails as thumbs_module  # noqa: E402

RAW_COLUMNS = ["SourceFile", "FileName", "DateTimeOriginal", "OffsetTimeOriginal",
               "GPSLatitude", "GPSLongitude", "ImageWidth", "ImageHeight"]
CLEAN_COLUMNS = ["photo_id", "person", "file_name", "taken_at", "taken_utc",
                 "date", "lat", "lng", "has_gps"]


def jpeg_bytes(size, orientation=None, gps=False):
    img = Image.new("RGB", size, (200, 80, 40))
    exif = Image.Exif()
    if orientation is not None:
        exif[0x0112] = orientation
    if gps:
        exif[0x8825] = {1: "N", 2: (42.0, 21.0, 36.0), 3: "W", 4: (71.0, 3.0, 30.0)}
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes() if (orientation or gps) else b"")
    return buf.getvalue()


# Display-P3 colorants adapted to D50 (ICC profile connection space).
P3_COLORANTS = {b"rXYZ": (0.5151, 0.2412, -0.0011),
                b"gXYZ": (0.2920, 0.6922, 0.0419),
                b"bXYZ": (0.1571, 0.0666, 0.7841)}


def wide_gamut_profile():
    """A synthetic non-sRGB RGB profile: the lcms sRGB profile with P3 colorants."""
    data = bytearray(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    count = struct.unpack(">I", data[128:132])[0]
    for i in range(count):
        sig, offset, _size = struct.unpack(">4sII", data[132 + 12 * i:144 + 12 * i])
        if sig in P3_COLORANTS:
            xyz = [round(v * 65536) for v in P3_COLORANTS[sig]]
            data[offset + 8:offset + 20] = struct.pack(">3i", *xyz)
    return bytes(data)


def marker_jpeg(size, marker_corner, orientation=None, icc_profile=None):
    """Grey image with a 25%-wide red block in one corner ('tl' or 'tr')."""
    img = Image.new("RGB", size, (128, 128, 128))
    block = (size[0] // 4, size[1] // 4)
    left = 0 if marker_corner == "tl" else size[0] - block[0]
    img.paste((255, 0, 0), (left, 0, left + block[0], block[1]))
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    buf = io.BytesIO()
    kwargs = {"exif": exif.tobytes()} if orientation else {}
    if icc_profile:
        kwargs["icc_profile"] = icc_profile
    img.save(buf, format="JPEG", quality=95, **kwargs)
    return buf.getvalue()


def is_red(pixel):
    return pixel[0] > 200 and pixel[1] < 60 and pixel[2] < 60


def corner_pixels(img):
    """Pixels 8 px in from each corner."""
    w, h = img.size
    return {"tl": img.getpixel((8, 8)), "tr": img.getpixel((w - 9, 8)),
            "bl": img.getpixel((8, h - 9)), "br": img.getpixel((w - 9, h - 9))}


def photo_id_of(data):
    return "p_" + hashlib.sha1(data).hexdigest()[:10]


class ThumbnailsTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "photos").mkdir()
        (self.root / "data" / "processed").mkdir(parents=True)
        (self.root / "data" / "raw").mkdir(parents=True)
        self.thumbs = self.root / "frontend" / "public" / "data" / "thumbs"
        self.clean_rows = []
        self.raw_rows = []
        self.trips = {}  # radius -> list of photo_ids
        self.counter = 0

    def add_photo(self, data, name=None, in_raw=True, in_trip=(10,), write=True,
                  dt="2026:03:14 15:32:08"):
        """Register a synthetic photo; returns its photo_id."""
        self.counter += 1
        name = name or f"synthetic_name_{self.counter}.jpg"
        path = self.root / "photos" / name
        if write:
            path.write_bytes(data)
        pid = photo_id_of(data)
        taken_at = dt[:10].replace(":", "-") + "T" + dt[11:] + "-04:00"
        self.clean_rows.append({"photo_id": pid, "person": "tester", "file_name": name,
                                "taken_at": taken_at, "taken_utc": "", "date": taken_at[:10],
                                "lat": "", "lng": "", "has_gps": "false"})
        if in_raw:
            self.raw_rows.append({"SourceFile": str(path), "FileName": name,
                                  "DateTimeOriginal": dt, "OffsetTimeOriginal": "-04:00",
                                  "GPSLatitude": "", "GPSLongitude": "",
                                  "ImageWidth": "1", "ImageHeight": "1"})
        for radius in in_trip:
            self.trips.setdefault(radius, []).append(pid)
        return pid

    def write_inputs(self):
        pd.DataFrame(self.clean_rows, columns=CLEAN_COLUMNS).to_csv(
            self.root / "data" / "processed" / "photos_clean.csv", index=False)
        pd.DataFrame(self.raw_rows, columns=RAW_COLUMNS).to_csv(
            self.root / "data" / "raw" / "photos_raw_tester_all.csv", index=False)
        for radius, ids in self.trips.items():
            pd.DataFrame({"photo_id": ids, "trip_id": ["t"] * len(ids)}).to_csv(
                self.root / "data" / "processed" / f"photo_trips_r{radius}.csv", index=False)

    def run_main(self, args=("tester",)):
        buf = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(buf):
            try:
                thumbs_module.main(list(args), root=self.root)
            except SystemExit as exc:
                code = exc.code
        return buf.getvalue(), code

    def stats(self, output):
        return dict(line.split(": ") for line in output.strip().splitlines())


class TestSizing(unittest.TestCase):
    def test_target_size_downscales_and_never_upscales(self):
        self.assertEqual(thumbs_module.target_size(3000, 2000), ((400, 267), (1600, 1067)))
        self.assertEqual(thumbs_module.target_size(800, 600), ((400, 300), (800, 600)))
        self.assertEqual(thumbs_module.target_size(300, 200), ((300, 200), (300, 200)))
        self.assertEqual(thumbs_module.target_size(2000, 3000), ((400, 600), (1067, 1600)))

    def test_raw_time_key(self):
        self.assertEqual(thumbs_module.raw_time_key("2026-03-14T15:32:08-04:00"),
                         "2026:03:14 15:32:08")
        self.assertEqual(thumbs_module.raw_time_key("2026-03-14T15:32:08"), "2026:03:14 15:32:08")


class TestOrientationAndColour(unittest.TestCase):
    def red_corners(self, data):
        with Image.open(io.BytesIO(data)) as img:
            _small, large = thumbs_module.make_thumbs(img)
        return large.size, {k for k, v in corner_pixels(large).items() if is_red(v)}

    def test_orientation_6_moves_top_left_marker_to_top_right(self):
        size, red = self.red_corners(marker_jpeg((600, 400), "tl", orientation=6))
        self.assertEqual(size, (400, 600))
        self.assertEqual(red, {"tr"})

    def test_orientation_2_mirrors_top_left_marker_to_top_right(self):
        size, red = self.red_corners(marker_jpeg((600, 400), "tl", orientation=2))
        self.assertEqual(size, (600, 400))
        self.assertEqual(red, {"tr"})

    def test_orientation_5_transposes_top_right_marker_to_bottom_left(self):
        size, red = self.red_corners(marker_jpeg((600, 400), "tr", orientation=5))
        self.assertEqual(size, (400, 600))
        self.assertEqual(red, {"bl"})

    def test_no_orientation_keeps_marker_in_place(self):
        size, red = self.red_corners(marker_jpeg((600, 400), "tl"))
        self.assertEqual(size, (600, 400))
        self.assertEqual(red, {"tl"})

    def test_embedded_profile_is_converted_to_srgb_and_dropped(self):
        profile = wide_gamut_profile()
        colour = (200, 60, 60)
        plain = Image.new("RGB", (64, 64), colour)
        buf = io.BytesIO()
        plain.save(buf, format="JPEG", quality=100, icc_profile=profile)
        tagged = buf.getvalue()
        buf = io.BytesIO()
        plain.save(buf, format="JPEG", quality=100)
        untagged = buf.getvalue()

        def centre(data):
            with Image.open(io.BytesIO(data)) as img:
                small, _large = thumbs_module.make_thumbs(img)
            self.assertNotIn("icc_profile", small.info)
            return small.getpixel((32, 32))

        naive = centre(untagged)  # no profile -> pixels pass through untouched
        converted = centre(tagged)
        self.assertLess(max(abs(a - b) for a, b in zip(naive, (200, 60, 60))), 4)
        self.assertGreater(max(abs(a - b) for a, b in zip(naive, converted)), 10)

    def test_bad_profile_falls_back_without_crash(self):
        data = marker_jpeg((600, 400), "tl", icc_profile=b"not a real icc profile")
        with Image.open(io.BytesIO(data)) as img:
            img.info["icc_profile"] = b"not a real icc profile"
            small, large = thumbs_module.make_thumbs(img)
        self.assertEqual(large.size, (600, 400))
        self.assertTrue(is_red(corner_pixels(large)["tl"]))

    def test_written_webp_has_no_iccp_chunk(self):
        data = marker_jpeg((600, 400), "tl", icc_profile=wide_gamut_profile())
        with Image.open(io.BytesIO(data)) as img:
            self.assertIn("icc_profile", img.info)
            small, _large = thumbs_module.make_thumbs(img)
        out = io.BytesIO()
        small.save(out, format="WEBP")
        self.assertNotIn(b"ICCP", out.getvalue())


class TestOutputs(ThumbnailsTestCase):
    def test_rotated_exif_stripped_webp(self):
        # 3000x2000 stored landscape with Orientation=6 -> upright portrait.
        data = jpeg_bytes((3000, 2000), orientation=6, gps=True)
        with Image.open(io.BytesIO(data)) as probe:
            self.assertIn("exif", probe.info)  # sanity: the source does carry EXIF
        pid = self.add_photo(data)
        self.write_inputs()
        output, code = self.run_main()
        self.assertEqual(code, 0)
        self.assertEqual(self.stats(output)["Written"], "1")
        large = self.thumbs / f"{pid}_l.webp"
        small = self.thumbs / f"{pid}_s.webp"
        with Image.open(large) as img:
            self.assertEqual(img.format, "WEBP")
            self.assertEqual(img.size, (1067, 1600))
            self.assertNotIn("exif", img.info)
            self.assertNotIn("xmp", img.info)
            self.assertNotIn("icc_profile", img.info)
        with Image.open(small) as img:
            self.assertEqual(img.format, "WEBP")
            self.assertEqual(img.size[0], 400)
            self.assertEqual(img.size[1], 600)
            self.assertNotIn("exif", img.info)
        for path in (large, small):
            raw = path.read_bytes()
            for marker in (b"EXIF", b"XMP ", b"ICCP"):
                self.assertNotIn(marker, raw)

    def test_no_upscaling(self):
        pid_mid = self.add_photo(jpeg_bytes((800, 600)))
        pid_tiny = self.add_photo(jpeg_bytes((300, 200)))
        self.write_inputs()
        self.run_main()
        sizes = {}
        for pid in (pid_mid, pid_tiny):
            for suffix in ("s", "l"):
                with Image.open(self.thumbs / f"{pid}_{suffix}.webp") as img:
                    sizes[(pid, suffix)] = img.size
        self.assertEqual(sizes[(pid_mid, "l")], (800, 600))
        self.assertEqual(sizes[(pid_mid, "s")], (400, 300))
        self.assertEqual(sizes[(pid_tiny, "l")], (300, 200))
        self.assertEqual(sizes[(pid_tiny, "s")], (300, 200))

    def test_heic_source(self):
        buf = io.BytesIO()
        try:
            pillow_heif.register_heif_opener()
            Image.new("RGB", (640, 480), (10, 120, 200)).save(buf, format="HEIF")
        except Exception:
            self.skipTest("HEIF encoding not available")
        data = buf.getvalue()
        pid = self.add_photo(data, name="synthetic_heic.heic")
        self.write_inputs()
        output, _ = self.run_main()
        self.assertEqual(self.stats(output)["Written"], "1")
        with Image.open(self.thumbs / f"{pid}_s.webp") as img:
            self.assertEqual(img.size, (400, 300))

    def test_no_temp_files_left(self):
        self.add_photo(jpeg_bytes((900, 700)))
        self.write_inputs()
        self.run_main()
        names = [p.name for p in self.thumbs.iterdir()]
        self.assertEqual(len(names), 2)
        self.assertTrue(all(n.endswith(".webp") and not n.startswith(".") for n in names))


class TestSelection(ThumbnailsTestCase):
    def test_union_across_radii_and_ignores_non_trip_photos(self):
        both = self.add_photo(jpeg_bytes((500, 400), orientation=None), in_trip=(10, 25))
        only_r10 = self.add_photo(jpeg_bytes((510, 400)), in_trip=(10,))
        only_r200 = self.add_photo(jpeg_bytes((520, 400)), in_trip=(200,))
        outside = self.add_photo(jpeg_bytes((530, 400)), in_trip=())
        self.write_inputs()
        output, code = self.run_main()
        stats = self.stats(output)
        self.assertEqual(code, 0)
        self.assertEqual(stats["Photos in trips"], "3")
        self.assertEqual(stats["Written"], "3")
        for pid in (both, only_r10, only_r200):
            self.assertTrue((self.thumbs / f"{pid}_s.webp").exists())
        self.assertFalse((self.thumbs / f"{outside}_s.webp").exists())

    def test_skip_when_both_exist_without_reading_source(self):
        data = jpeg_bytes((500, 400))
        pid = self.add_photo(data)
        self.write_inputs()
        self.thumbs.mkdir(parents=True)
        (self.thumbs / f"{pid}_s.webp").write_bytes(b"existing-s")
        (self.thumbs / f"{pid}_l.webp").write_bytes(b"existing-l")
        (self.root / "photos" / self.clean_rows[0]["file_name"]).unlink()  # source gone
        output, _ = self.run_main()
        stats = self.stats(output)
        self.assertEqual(stats["Skipped (already exist)"], "1")
        self.assertEqual(stats["Written"], "0")
        self.assertEqual(stats["Not found"], "0")
        self.assertEqual((self.thumbs / f"{pid}_s.webp").read_bytes(), b"existing-s")

    def test_only_one_existing_file_is_rewritten(self):
        pid = self.add_photo(jpeg_bytes((500, 400)))
        self.write_inputs()
        self.thumbs.mkdir(parents=True)
        (self.thumbs / f"{pid}_s.webp").write_bytes(b"stale")
        output, _ = self.run_main()
        self.assertEqual(self.stats(output)["Written"], "1")
        with Image.open(self.thumbs / f"{pid}_l.webp") as img:
            self.assertEqual(img.format, "WEBP")


class TestFailures(ThumbnailsTestCase):
    def test_not_found_hash_mismatch_unreadable(self):
        self.add_photo(jpeg_bytes((500, 400)), in_raw=False)                   # no raw row
        self.add_photo(jpeg_bytes((510, 400)), write=False)                    # file missing
        changed = self.add_photo(jpeg_bytes((520, 400)))
        (self.root / "photos" / self.clean_rows[-1]["file_name"]).write_bytes(
            jpeg_bytes((521, 400)))                                            # content changed
        corrupt = b"this is not an image at all"
        self.add_photo(corrupt)                                                # decode failure
        good = self.add_photo(jpeg_bytes((540, 400)))
        self.write_inputs()
        output, code = self.run_main()
        stats = self.stats(output)
        self.assertEqual(code, 0)
        self.assertEqual(stats["Photos in trips"], "5")
        self.assertEqual(stats["Not found"], "2")
        self.assertEqual(stats["Hash mismatch"], "1")
        self.assertEqual(stats["Unreadable"], "1")
        self.assertEqual(stats["Written"], "1")
        self.assertTrue((self.thumbs / f"{good}_s.webp").exists())
        self.assertFalse((self.thumbs / f"{changed}_s.webp").exists())
        leftovers = [p.name for p in self.thumbs.iterdir()]
        self.assertEqual(len(leftovers), 2)

    def test_unreadable_when_open_raises_permission_error(self):
        pid = self.add_photo(jpeg_bytes((500, 400)))
        self.write_inputs()
        original = Path.read_bytes

        def deny(path_self):
            if path_self.parent.name == "photos":
                raise PermissionError("denied")
            return original(path_self)

        Path.read_bytes = deny
        try:
            output, code = self.run_main()
        finally:
            Path.read_bytes = original
        self.assertEqual(code, 0)
        self.assertEqual(self.stats(output)["Unreadable"], "1")
        self.assertFalse((self.thumbs / f"{pid}_s.webp").exists())


class TestConsole(ThumbnailsTestCase):
    def test_stdout_is_exactly_six_count_lines_without_names(self):
        self.add_photo(jpeg_bytes((500, 400)), name="secret_holiday_name.jpg")
        self.add_photo(jpeg_bytes((510, 400)), name="another_secret.jpg", write=False)
        self.write_inputs()
        output, code = self.run_main()
        self.assertEqual(code, 0)
        lines = output.strip().splitlines()
        self.assertEqual([line.split(":")[0] for line in lines],
                         ["Photos in trips", "Written", "Skipped (already exist)",
                          "Not found", "Hash mismatch", "Unreadable"])
        self.assertTrue(all(line.split(": ")[1].isdigit() for line in lines))
        for secret in ("secret_holiday_name", "another_secret", str(self.root), "2026"):
            self.assertNotIn(secret, output)

    def test_missing_photo_trips_files_one_line_exit_1(self):
        self.add_photo(jpeg_bytes((500, 400)), in_trip=())
        self.write_inputs()
        output, code = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(len(output.strip().splitlines()), 1)
        self.assertFalse(self.thumbs.exists())

    def test_missing_other_inputs_one_line_exit_1(self):
        self.add_photo(jpeg_bytes((500, 400)))
        self.write_inputs()
        (self.root / "data" / "raw" / "photos_raw_tester_all.csv").unlink()
        output, code = self.run_main()
        self.assertEqual(code, 1)
        self.assertEqual(len(output.strip().splitlines()), 1)

    def test_bad_person_one_line_exit_1(self):
        output, code = self.run_main(("Bad/Person",))
        self.assertEqual(code, 1)
        self.assertEqual(len(output.strip().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
