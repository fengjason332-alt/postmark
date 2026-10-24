"""Unit tests for backend/clean.py (synthetic data only). Run from the repo root:

    .venv/bin/python -m unittest discover -s backend/tests -v
"""

import contextlib
import hashlib
import io
import os
import sys
import tempfile
import unittest
from unittest import mock
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import clean as clean_module  # noqa: E402

TODAY = date(2026, 10, 24)
RAW_COLUMNS = ["SourceFile", "FileName", "DateTimeOriginal", "OffsetTimeOriginal",
               "GPSLatitude", "GPSLongitude", "ImageWidth", "ImageHeight"]


class CleanTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.photo_dir = self.root / "photos"
        self.photo_dir.mkdir()
        self.counter = 0

    def photo(self, dt="2026:03:14 15:32:08", offset="", lat="", lng="",
              content=None, name=None, source=None):
        """Build one raw row; writes a tiny synthetic photo file unless a source is given."""
        self.counter += 1
        name = name or f"img_{self.counter}.jpg"
        if source is None:
            path = self.photo_dir / name
            path.write_bytes(content if content is not None else f"synthetic-{self.counter}".encode())
            source = str(path)
        return {"SourceFile": source, "FileName": name, "DateTimeOriginal": dt,
                "OffsetTimeOriginal": offset, "GPSLatitude": str(lat), "GPSLongitude": str(lng),
                "ImageWidth": "100", "ImageHeight": "80"}

    def run_clean(self, rows):
        df = pd.DataFrame(rows, columns=RAW_COLUMNS, dtype=str)
        out, report = clean_module.clean(df, "tester", TODAY, self.root)
        dropped = (report["dropped_invalid_date"] + report["dropped_before_2005"]
                   + report["dropped_future"] + report["dropped_duplicate_content"])
        self.assertEqual(report["rows_in"] - dropped - report["bursts_merged"], report["rows_out"])
        self.assertEqual(len(out), report["rows_out"])
        return out, report


class TestDateFilter(CleanTestCase):
    def test_invalid_dates(self):
        rows = [self.photo(dt=""), self.photo(dt="0000:00:00 00:00:00"), self.photo(dt="not a date")]
        out, report = self.run_clean(rows)
        self.assertEqual(report["dropped_invalid_date"], 3)
        self.assertEqual(report["rows_out"], 0)

    def test_before_2005_and_boundary(self):
        out, report = self.run_clean([self.photo(dt="2004:12:31 23:59:59"),
                                      self.photo(dt="2005:01:01 00:00:00")])
        self.assertEqual(report["dropped_before_2005"], 1)
        self.assertEqual(list(out["date"]), ["2005-01-01"])

    def test_future_and_today(self):
        out, report = self.run_clean([self.photo(dt="2026:10:25 00:00:00"),
                                      self.photo(dt="2026:10:24 23:59:59")])
        self.assertEqual(report["dropped_future"], 1)
        self.assertEqual(list(out["date"]), ["2026-10-24"])

    def test_extra_chars_after_seconds(self):
        out, report = self.run_clean([self.photo(dt="2026:03:14 15:32:08.123")])
        self.assertEqual(report["dropped_invalid_date"], 0)
        self.assertEqual(out.iloc[0]["taken_at"], "2026-03-14T15:32:08")


class TestGps(CleanTestCase):
    def test_invalid_gps_variants(self):
        rows = [self.photo(dt=f"2026:03:14 10:00:0{i}", lat=lat, lng=lng)
                for i, (lat, lng) in enumerate([("", ""), ("abc", "12"), ("0", "0"), ("95", "200"),
                                                ("40", "200"), ("95", "10")])]
        out, report = self.run_clean(rows)
        self.assertEqual(report["rows_out"], 6)
        self.assertEqual(report["rows_with_gps"], 0)
        self.assertTrue((out["has_gps"] == "false").all())
        self.assertTrue((out["lat"] == "").all())
        self.assertTrue((out["lng"] == "").all())

    def test_valid_gps_keeps_precision(self):
        out, report = self.run_clean([self.photo(lat="42.36012345", lng="-71.05889876")])
        row = out.iloc[0]
        self.assertEqual((row["has_gps"], row["lat"], row["lng"]), ("true", "42.36012345", "-71.05889876"))
        self.assertEqual(report["rows_with_gps"], 1)

    def test_zero_latitude_alone_is_valid(self):
        out, _ = self.run_clean([self.photo(lat="0", lng="10")])
        self.assertEqual(out.iloc[0]["has_gps"], "true")


class TestOffsets(CleanTestCase):
    def test_negative_offset(self):
        out, _ = self.run_clean([self.photo(dt="2026:03:14 15:32:08", offset="-04:00")])
        self.assertEqual(out.iloc[0]["taken_at"], "2026-03-14T15:32:08-04:00")
        self.assertEqual(out.iloc[0]["taken_utc"], "2026-03-14T19:32:08Z")

    def test_utc_crosses_midnight(self):
        out, _ = self.run_clean([self.photo(dt="2026:03:14 22:30:00", offset="-04:00"),
                                 self.photo(dt="2026:03:14 01:15:00", offset="+05:30")])
        by_at = dict(zip(out["taken_at"], out["taken_utc"]))
        self.assertEqual(by_at["2026-03-14T22:30:00-04:00"], "2026-03-15T02:30:00Z")
        self.assertEqual(by_at["2026-03-14T01:15:00+05:30"], "2026-03-13T19:45:00Z")

    def test_blank_and_malformed_offsets(self):
        out, _ = self.run_clean([self.photo(dt="2026:03:14 10:00:00", offset=""),
                                 self.photo(dt="2026:03:14 11:00:00", offset="-4")])
        self.assertEqual(list(out["taken_at"]), ["2026-03-14T10:00:00", "2026-03-14T11:00:00"])
        self.assertEqual(list(out["taken_utc"]), ["", ""])

    def test_z_offset(self):
        out, _ = self.run_clean([self.photo(dt="2026:03:14 10:00:00", offset="Z")])
        self.assertEqual(out.iloc[0]["taken_at"], "2026-03-14T10:00:00+00:00")
        self.assertEqual(out.iloc[0]["taken_utc"], "2026-03-14T10:00:00Z")


class TestBursts(CleanTestCase):
    LAT, LNG = 42.3601, -71.0589
    # 1 degree of latitude is about 111 km, so these are about 5 m and 50 m north.
    D5, D50 = 5 / 111195, 50 / 111195

    def test_same_second_5m_merged(self):
        first = self.photo(lat=self.LAT, lng=self.LNG, name="first.jpg")
        second = self.photo(lat=self.LAT + self.D5, lng=self.LNG, name="second.jpg")
        out, report = self.run_clean([first, second])
        self.assertEqual(report["bursts_merged"], 1)
        self.assertEqual(list(out["file_name"]), ["first.jpg"])

    def test_same_second_50m_kept(self):
        out, report = self.run_clean([self.photo(lat=self.LAT, lng=self.LNG),
                                      self.photo(lat=self.LAT + self.D50, lng=self.LNG)])
        self.assertEqual(report["bursts_merged"], 0)
        self.assertEqual(len(out), 2)

    def test_same_second_without_gps_kept(self):
        out, report = self.run_clean([self.photo(), self.photo()])
        self.assertEqual(report["bursts_merged"], 0)
        self.assertEqual(len(out), 2)

    def test_gps_and_non_gps_same_second_kept(self):
        out, report = self.run_clean([self.photo(lat=self.LAT, lng=self.LNG), self.photo()])
        self.assertEqual(report["bursts_merged"], 0)
        self.assertEqual(len(out), 2)

    def test_one_second_apart_kept(self):
        out, report = self.run_clean([self.photo(dt="2026:03:14 15:32:08", lat=self.LAT, lng=self.LNG),
                                      self.photo(dt="2026:03:14 15:32:09", lat=self.LAT, lng=self.LNG)])
        self.assertEqual(report["bursts_merged"], 0)
        self.assertEqual(len(out), 2)


class TestPhotoId(CleanTestCase):
    def test_id_is_content_hash(self):
        content = b"hello synthetic photo"
        out, report = self.run_clean([self.photo(content=content)])
        self.assertEqual(out.iloc[0]["photo_id"], "p_" + hashlib.sha1(content).hexdigest()[:10])
        self.assertEqual(report["hash_fallbacks"], 0)

    def test_relative_source_resolves_against_root(self):
        content = b"relative file"
        (self.root / "rel.jpg").write_bytes(content)
        out, report = self.run_clean([self.photo(source="rel.jpg", name="rel.jpg")])
        self.assertEqual(out.iloc[0]["photo_id"], "p_" + hashlib.sha1(content).hexdigest()[:10])
        self.assertEqual(report["hash_fallbacks"], 0)

    def test_unreadable_files_fall_back(self):
        missing = str(self.photo_dir / "missing.jpg")
        directory = str(self.photo_dir)
        rows = [self.photo(dt="2026:03:14 15:32:08", offset="-04:00", source=missing, name="missing.jpg"),
                self.photo(dt="2026:03:14 16:00:00", source=directory, name="dir.jpg")]
        out, report = self.run_clean(rows)
        self.assertEqual(report["hash_fallbacks"], 2)
        expected = {
            "p_" + hashlib.sha1(f"{missing}|2026-03-14T15:32:08-04:00".encode()).hexdigest()[:10],
            "p_" + hashlib.sha1(f"{directory}|2026-03-14T16:00:00".encode()).hexdigest()[:10],
        }
        self.assertEqual(set(out["photo_id"]), expected)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root can read any file")
    def test_unreadable_existing_file_falls_back(self):
        row = self.photo(dt="2026:03:14 15:32:08", name="locked.jpg")
        path = Path(row["SourceFile"])
        os.chmod(path, 0)
        self.addCleanup(os.chmod, path, 0o644)
        out, report = self.run_clean([row])
        self.assertEqual(report["hash_fallbacks"], 1)
        expected = "p_" + hashlib.sha1(f"{path}|2026-03-14T15:32:08".encode()).hexdigest()[:10]
        self.assertEqual(out.iloc[0]["photo_id"], expected)

    def test_identical_content_dropped(self):
        rows = [self.photo(dt="2026:03:14 10:00:00", content=b"same", name="a.jpg"),
                self.photo(dt="2026:03:15 10:00:00", content=b"same", name="b.jpg"),
                self.photo(dt="2026:03:16 10:00:00", content=b"other", name="c.jpg")]
        out, report = self.run_clean(rows)
        self.assertEqual(report["dropped_duplicate_content"], 1)
        self.assertEqual(list(out["file_name"]), ["a.jpg", "c.jpg"])
        self.assertEqual(out["photo_id"].nunique(), 2)


class TestOutput(CleanTestCase):
    def test_columns_booleans_and_person(self):
        out, _ = self.run_clean([self.photo(lat="10", lng="20"), self.photo(dt="2026:03:14 15:32:09")])
        self.assertEqual(list(out.columns), ["photo_id", "person", "file_name", "taken_at",
                                             "taken_utc", "date", "lat", "lng", "has_gps"])
        self.assertEqual(list(out["has_gps"]), ["true", "false"])
        self.assertEqual(set(out["person"]), {"tester"})

    def test_sort_order_with_tie_keeping_file_order(self):
        rows = [self.photo(dt="2026:05:01 10:00:00", name="late.jpg"),
                self.photo(dt="2026:03:01 10:00:00", name="tie_a.jpg"),
                self.photo(dt="2026:03:01 10:00:00", name="tie_b.jpg"),
                self.photo(dt="2026:01:01 10:00:00", name="early.jpg")]
        out, _ = self.run_clean(rows)
        self.assertEqual(list(out["file_name"]), ["early.jpg", "tie_a.jpg", "tie_b.jpg", "late.jpg"])

    def test_empty_input(self):
        out, report = self.run_clean([])
        self.assertEqual(len(out), 0)
        self.assertEqual(list(out.columns), clean_module.OUTPUT_COLUMNS)
        self.assertEqual(report["rows_in"], 0)


class TestReportAndMain(CleanTestCase):
    def test_format_report_nine_lines(self):
        _, report = self.run_clean([self.photo(lat="10", lng="20"), self.photo(dt=""),
                                    self.photo(dt="2004:01:01 00:00:00"), self.photo(dt="2030:01:01 00:00:00")])
        lines = clean_module.format_report(report).split("\n")
        self.assertEqual(lines, ["Rows in: 4", "Dropped (invalid date): 1", "Dropped (before 2005): 1",
                                 "Dropped (future date): 1", "Bursts merged: 0",
                                 "Dropped (duplicate content): 0", "Rows out: 1",
                                 "Rows with GPS: 1", "Hash fallbacks: 0"])

    def write_input(self, rows, person="tester"):
        raw_dir = self.root / "data" / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows, columns=RAW_COLUMNS, dtype=str).to_csv(
            raw_dir / f"photos_raw_{person}_all.csv", index=False)

    def call_main(self, argv):
        stdout, _, code = self.call_main_streams(argv)
        return stdout, code

    def call_main_streams(self, argv):
        stdout, stderr = io.StringIO(), io.StringIO()
        code = 0
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                clean_module.main(argv, root=self.root, today=TODAY)
            except SystemExit as exit_info:
                code = exit_info.code
        return stdout.getvalue(), stderr.getvalue(), code

    def test_main_warns_on_fallbacks(self):
        missing = str(self.photo_dir / "gone.jpg")
        self.write_input([self.photo(source=missing, name="gone.jpg"), self.photo()])
        stdout, stderr, code = self.call_main_streams(["tester"])
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "\n".join([
            "Rows in: 2", "Dropped (invalid date): 0", "Dropped (before 2005): 0",
            "Dropped (future date): 0", "Bursts merged: 0", "Dropped (duplicate content): 0",
            "Rows out: 2", "Rows with GPS: 0", "Hash fallbacks: 1"]) + "\n")
        self.assertEqual(stderr, "warning: 1 photo files could not be read; their photo_id is "
                                 "path-based, not a content hash. Give this terminal access to "
                                 "the photo folder and re-run.\n")
        self.assertTrue((self.root / "data" / "processed" / "photos_clean.csv").is_file())

    def test_main_no_warning_without_fallbacks(self):
        self.write_input([self.photo()])
        _, stderr, code = self.call_main_streams(["tester"])
        self.assertEqual((stderr, code), ("", 0))

    def test_main_clean_failure_is_generic(self):
        self.write_input([self.photo()])
        with mock.patch.object(clean_module, "clean", side_effect=ValueError("SENTINEL-secret-row")):
            stdout, stderr, code = self.call_main_streams(["tester"])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "error: could not clean input\n")
        self.assertEqual(stderr, "")
        self.assertNotIn("SENTINEL", stdout + stderr)

    def test_main_end_to_end(self):
        self.write_input([self.photo(lat="10", lng="20", offset="-04:00"), self.photo(dt="")])
        stdout, code = self.call_main(["tester"])
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "\n".join([
            "Rows in: 2", "Dropped (invalid date): 1", "Dropped (before 2005): 0",
            "Dropped (future date): 0", "Bursts merged: 0", "Dropped (duplicate content): 0",
            "Rows out: 1", "Rows with GPS: 1", "Hash fallbacks: 0"]) + "\n")
        written = pd.read_csv(self.root / "data" / "processed" / "photos_clean.csv",
                              dtype=str, keep_default_na=False)
        self.assertEqual(list(written.columns), clean_module.OUTPUT_COLUMNS)
        self.assertEqual(len(written), 1)
        self.assertEqual(written.iloc[0]["person"], "tester")

    def test_main_overwrites_existing_output(self):
        self.write_input([self.photo()])
        out_path = self.root / "data" / "processed" / "photos_clean.csv"
        out_path.parent.mkdir(parents=True)
        out_path.write_text("stale\n")
        _, code = self.call_main(["tester"])
        self.assertEqual(code, 0)
        self.assertNotIn("stale", out_path.read_text())

    def test_main_bad_person(self):
        for bad in ("Bad Name", "../x", "UPPER", "a/b", ""):
            stdout, code = self.call_main([bad])
            self.assertEqual(code, 1, bad)
            self.assertEqual(len(stdout.strip().split("\n")), 1, bad)
            self.assertTrue(stdout.startswith("error:"), bad)

    def test_main_missing_input(self):
        stdout, code = self.call_main(["nobody"])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "error: could not read data/raw/photos_raw_nobody_all.csv\n")

    def test_main_unwritable_output(self):
        self.write_input([self.photo()])
        (self.root / "data" / "processed").write_text("a file, not a folder")
        stdout, code = self.call_main(["tester"])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "error: could not write output\n")


if __name__ == "__main__":
    unittest.main()
