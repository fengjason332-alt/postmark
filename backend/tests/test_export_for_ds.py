"""Unit tests for backend/export_for_ds.py (synthetic data only). Run from the repo root:

    .venv/bin/python -m unittest discover -s backend/tests -v
"""

import contextlib
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import export_for_ds as export_module  # noqa: E402

CLEAN_COLUMNS = ["photo_id", "person", "file_name", "taken_at", "taken_utc",
                 "date", "lat", "lng", "has_gps"]
EXPECTED_COLUMNS = ["photo_id", "taken_at", "taken_utc", "date", "lat", "lng", "has_gps"]
SENTINEL_NAME = "SENTINEL_SECRET_NAME_123.HEIC"
COORD_PATTERN = re.compile(r"-?\d+\.\d{2}")


def make_row(i, lat="", lng="", **overrides):
    row = {"photo_id": f"p_{i:010d}", "person": "tester", "file_name": SENTINEL_NAME,
           "taken_at": f"2026-03-14T15:32:0{i % 10}-04:00",
           "taken_utc": f"2026-03-14T19:32:0{i % 10}Z", "date": "2026-03-14",
           "lat": str(lat), "lng": str(lng), "has_gps": "true" if lat != "" else "false"}
    row.update(overrides)
    return row


def frame(rows):
    return pd.DataFrame(rows, columns=CLEAN_COLUMNS, dtype=str)


class TestCoarsen(unittest.TestCase):
    def test_columns_and_order(self):
        out = export_module.coarsen(frame([make_row(1, 42.3601, -71.0589)]))
        self.assertEqual(list(out.columns), EXPECTED_COLUMNS)
        self.assertNotIn("file_name", out.columns)
        self.assertNotIn("person", out.columns)

    def test_rounding_values(self):
        cases = [
            ("42.3601", "-71.0589", "42.36", "-71.06"),
            ("10", "-5", "10.00", "-5.00"),
            ("0.999", "-0.999", "1.00", "-1.00"),
            ("0.004", "-0.004", "0.00", "0.00"),
            ("-0.001", "-0.0049", "0.00", "0.00"),
            ("179.996", "-179.996", "180.00", "-180.00"),
            ("1.005", "2.675", "1.00", "2.67"),  # binary floats: consistently f"{x:.2f}"
        ]
        rows = [make_row(i, lat, lng) for i, (lat, lng, _, _) in enumerate(cases)]
        out = export_module.coarsen(frame(rows))
        self.assertEqual(list(out["lat"]), [c[2] for c in cases])
        self.assertEqual(list(out["lng"]), [c[3] for c in cases])

    def test_empty_coordinates_stay_empty(self):
        out = export_module.coarsen(frame([make_row(1), make_row(2, 1.234, 5.678)]))
        self.assertEqual(out.loc[0, "lat"], "")
        self.assertEqual(out.loc[0, "lng"], "")
        self.assertEqual(out.loc[0, "has_gps"], "false")
        self.assertEqual(out.loc[1, "lat"], "1.23")
        self.assertEqual(out.loc[1, "lng"], "5.68")

    def test_other_columns_unchanged(self):
        src = frame([make_row(1, 42.3601, -71.0589), make_row(2)])
        out = export_module.coarsen(src)
        for column in ["photo_id", "taken_at", "taken_utc", "date", "has_gps"]:
            self.assertEqual(list(out[column]), list(src[column]), column)

    def test_all_coordinates_match_pattern_or_empty(self):
        rows = [make_row(i, lat, lng) for i, (lat, lng) in enumerate(
            [(42.3601, -71.0589), (0, 0.5), (-33.8688, 151.2093), (89.9999, -179.9999)])]
        rows.append(make_row(9))
        out = export_module.coarsen(frame(rows))
        for column in ["lat", "lng"]:
            for value in out[column]:
                self.assertTrue(value == "" or COORD_PATTERN.fullmatch(value), column)

    def test_unparseable_coordinate_raises(self):
        for bad in ["abc", "nan", "inf"]:
            with self.assertRaises(ValueError):
                export_module.coarsen(frame([make_row(1, bad, "1.0")]))

    def test_does_not_modify_input(self):
        src = frame([make_row(1, 42.3601, -71.0589)])
        export_module.coarsen(src)
        self.assertEqual(list(src.columns), CLEAN_COLUMNS)
        self.assertEqual(src.loc[0, "lat"], "42.3601")


class TestMain(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write_input(self, rows):
        path = self.root / "data" / "processed" / "photos_clean.csv"
        path.parent.mkdir(parents=True)
        frame(rows).to_csv(path, index=False)

    def run_main(self, argv):
        buffer = io.StringIO()
        code = 0
        with contextlib.redirect_stdout(buffer):
            try:
                export_module.main(argv, root=self.root)
            except SystemExit as exc:
                code = exc.code
        return buffer.getvalue(), code

    def test_end_to_end(self):
        self.write_input([make_row(1, 42.3601, -71.0589), make_row(2)])
        stdout, code = self.run_main([])
        self.assertEqual(code, 0)
        self.assertEqual(stdout, "Rows: 2\n"
                                 "Columns: photo_id, taken_at, taken_utc, date, lat, lng, has_gps\n")
        output = self.root / "data" / "share" / "photos_coarse_jason.csv"
        self.assertTrue(output.exists())
        text = output.read_text()
        self.assertNotIn(SENTINEL_NAME, text)
        self.assertNotIn("tester", text)
        self.assertNotIn("42.3601", text)
        df = pd.read_csv(output, dtype=str, keep_default_na=False)
        self.assertEqual(list(df.columns), EXPECTED_COLUMNS)
        self.assertEqual(list(df["lat"]), ["42.36", ""])
        self.assertEqual(list(df["lng"]), ["-71.06", ""])

    def test_person_argument_names_output(self):
        self.write_input([make_row(1, 1.0, 2.0)])
        stdout, code = self.run_main(["amy_2"])
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "data" / "share" / "photos_coarse_amy_2.csv").exists())

    def test_overwrites_existing_output(self):
        self.write_input([make_row(1, 1.0, 2.0)])
        output = self.root / "data" / "share" / "photos_coarse_jason.csv"
        output.parent.mkdir(parents=True)
        output.write_text("stale")
        _, code = self.run_main([])
        self.assertEqual(code, 0)
        self.assertNotIn("stale", output.read_text())

    def test_bad_person_name(self):
        self.write_input([make_row(1, 1.0, 2.0)])
        for bad in ["../x", "Jason", "a b", ""]:
            stdout, code = self.run_main([bad])
            self.assertEqual(code, 1)
            self.assertEqual(stdout, "error: person must match [a-z0-9_-]+\n")
        self.assertFalse((self.root / "data" / "share").exists())

    def test_missing_input(self):
        stdout, code = self.run_main([])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "error: could not read data/processed/photos_clean.csv\n")

    def test_missing_expected_column(self):
        self.write_input([make_row(1, 1.0, 2.0)])
        path = self.root / "data" / "processed" / "photos_clean.csv"
        pd.read_csv(path, dtype=str).drop(columns=["lng"]).to_csv(path, index=False)
        stdout, code = self.run_main([])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "error: could not export\n")

    def test_unparseable_coordinate_does_not_leak(self):
        self.write_input([make_row(1, "SENTINEL_BAD_COORD", "2.0")])
        stdout, code = self.run_main([])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "error: could not export\n")
        self.assertFalse((self.root / "data" / "share" / "photos_coarse_jason.csv").exists())

    def test_exception_inside_coarsen_does_not_leak(self):
        self.write_input([make_row(1, 1.0, 2.0)])
        with mock.patch.object(export_module, "coarsen",
                               side_effect=RuntimeError("SENTINEL_LEAK_42")):
            stdout, code = self.run_main([])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "error: could not export\n")
        self.assertNotIn("SENTINEL", stdout)

    def test_write_failure(self):
        self.write_input([make_row(1, 1.0, 2.0)])
        (self.root / "data" / "share").write_text("not a directory")  # blocks mkdir
        stdout, code = self.run_main([])
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "error: could not export\n")


if __name__ == "__main__":
    unittest.main()
