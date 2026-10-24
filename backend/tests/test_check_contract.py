"""Unit tests for backend/check_contract.py. Run from the repo root:

    .venv/bin/python -W error -m unittest discover -s backend/tests -v

The checker is run on the committed mock data and on temporary copies with one defect each.
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import check_contract  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MOCK_DIR = REPO_ROOT / "frontend" / "public" / "mock"


class MockCopyCase(unittest.TestCase):
    """Each test gets a fresh temp copy of the mock folder that it may damage."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name) / "mock"
        shutil.copytree(MOCK_DIR, self.folder)

    def load(self, name="trips.json"):
        return json.loads((self.folder / name).read_text(encoding="utf-8"))

    def save(self, doc, name="trips.json"):
        (self.folder / name).write_text(json.dumps(doc), encoding="utf-8")

    def mutate_trips(self, function):
        doc = self.load()
        function(doc)
        self.save(doc)

    def assert_fails_with(self, fragment, mode="mock"):
        result = check_contract.check(self.folder, mode)
        self.assertFalse(result.ok)
        self.assertTrue(any(fragment in message for message in result.errors),
                        f"no error containing {fragment!r}: {result.errors[:5]}")
        return result


class RealMockTests(unittest.TestCase):
    def test_committed_mock_passes_in_mock_mode(self):
        result = check_contract.check(MOCK_DIR, "mock")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.warnings, [])
        self.assertGreater(result.n_checks, 500)
        self.assertEqual(result.missing_thumbs, 0)
        self.assertGreater(result.total_thumbs, 0)

    def test_committed_mock_also_passes_in_data_mode(self):
        result = check_contract.check(MOCK_DIR, "data")
        self.assertEqual(result.errors, [])

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            check_contract.check(MOCK_DIR, "other")

    def test_missing_folder_is_an_error_not_a_crash(self):
        result = check_contract.check(MOCK_DIR / "does_not_exist", "data")
        self.assertFalse(result.ok)


class DefectTests(MockCopyCase):
    def test_wrong_schema_version(self):
        self.mutate_trips(lambda d: d.update(schema_version="1.0"))
        self.assert_fails_with("schema_version")

    def test_missing_top_level_key(self):
        self.mutate_trips(lambda d: d.pop("homes"))
        self.assert_fails_with("trips.json top level")

    def test_trips_not_equal_to_default_radius_list(self):
        self.mutate_trips(lambda d: d["trips"][0].update(title="Changed"))
        self.assert_fails_with("trips must equal trips_by_radius[50]")

    def test_index_gap(self):
        def damage(doc):
            doc["trips_by_radius"]["50"][1]["index"] = 7
            doc["trips"] = doc["trips_by_radius"]["50"]
        self.mutate_trips(damage)
        self.assert_fails_with("index must run 0..n-1")

    def test_photo_city_not_in_trip_cities(self):
        def damage(doc):
            photo = doc["trips_by_radius"]["50"][0]["photos"][0]
            photo["city_id"] = "city_nowhere_xx"
            doc["trips"] = doc["trips_by_radius"]["50"]
        self.mutate_trips(damage)
        self.assert_fails_with("city_id is not one of the trip's cities")

    def test_city_without_photos_is_a_warning_not_an_error(self):
        removed = {}

        def damage(doc):
            trip = doc["trips_by_radius"]["50"][0]
            city = trip["cities"][0]["id"]
            removed.update(trip=trip["id"], city=city)
            for photo in trip["photos"]:
                if photo["city_id"] == city:
                    photo["city_id"] = None
            doc["trips"] = doc["trips_by_radius"]["50"]
        self.mutate_trips(damage)
        for mode in ("mock", "data"):
            result = check_contract.check(self.folder, mode)
            self.assertEqual(result.errors, [], mode)
            self.assertIn(f"trip {removed['trip']} city {removed['city']} has no photos",
                          result.warnings, mode)

    def test_no_gps_photo_with_coordinates(self):
        def damage(doc):
            doc["trips_by_radius"]["50"][0]["photos"][0]["has_gps"] = False
            doc["trips"] = doc["trips_by_radius"]["50"]
        self.mutate_trips(damage)
        self.assert_fails_with("has_gps is false but lat/lng/city_id are not null")

    def test_too_many_decimals_without_leaking_the_value(self):
        def damage(doc):
            doc["trips_by_radius"]["50"][0]["photos"][0]["lat"] = 40.123456789
            doc["trips"] = doc["trips_by_radius"]["50"]
        self.mutate_trips(damage)
        result = self.assert_fails_with("lat has more than 4 decimals")
        self.assertFalse(any("40.12345" in message for message in result.errors))

    def test_photo_count_cover_and_days(self):
        def damage(doc):
            trip = doc["trips_by_radius"]["50"][0]
            trip["photo_count"] += 1
            trip["cover_photo_id"] = "p_0000000000"
            trip["days"] += 1
            doc["trips"] = doc["trips_by_radius"]["50"]
        self.mutate_trips(damage)
        self.assert_fails_with("photo_count differs")
        self.assert_fails_with("cover_photo_id is not one of the trip's photos")
        self.assert_fails_with("days differs")

    def test_home_must_equal_last_homes_entry(self):
        self.mutate_trips(lambda d: d["home"].update(city="Elsewhere"))
        self.assert_fails_with("home must equal the last homes entry")

    def test_homes_must_be_sorted_and_non_overlapping(self):
        def damage(doc):
            first = dict(doc["homes"][0])
            doc["homes"].insert(0, first)
        self.mutate_trips(damage)
        self.assert_fails_with("sorted and non-overlapping")

    def test_empty_homes(self):
        self.mutate_trips(lambda d: d.update(homes=[]))
        self.assert_fails_with("homes must be a non-empty list")

    def test_stats_out_of_sync_with_trips(self):
        stats = self.load("stats.json")
        stats["by_radius"]["100"]["all_time"]["trips"] += 1
        self.save(stats, "stats.json")
        self.assert_fails_with("R100: all_time stats differ")

    def test_mock_only_distance_rule_is_skipped_in_data_mode(self):
        def damage(doc):
            doc["trips_by_radius"]["200"][0]["distance_km"] = 1
        self.mutate_trips(damage)
        self.assert_fails_with("[mock-only]")
        # (stats then differ too, but the distance rule itself must not fire in data mode)
        result = check_contract.check(self.folder, "data")
        self.assertFalse(any("[mock-only]" in message for message in result.errors))


class StrictFieldTests(MockCopyCase):
    """One mutation per rule; each must produce its own error message."""

    def edit_first_trip(self, function):
        def damage(doc):
            function(doc["trips_by_radius"]["50"][0])
            doc["trips"] = doc["trips_by_radius"]["50"]
        self.mutate_trips(damage)

    def test_null_city_latitude_fails(self):
        self.edit_first_trip(lambda t: t["cities"][0].update(lat=None))
        self.assert_fails_with("city lat/lng must be numbers")

    def test_null_home_latitude_fails(self):
        self.mutate_trips(lambda d: d["home"].update(lat=None))
        self.assert_fails_with("home lat/lng must be numbers")

    def test_null_homes_latitude_fails(self):
        self.mutate_trips(lambda d: d["homes"][-1].update(lat=None))
        self.assert_fails_with("homes entry lat/lng must be numbers")

    def test_photo_date_outside_the_trip(self):
        def damage(trip):
            trip["photos"][0]["date"] = "2020-01-01"
            trip["photos"][0]["taken_at"] = "2020-01-01" + trip["photos"][0]["taken_at"][10:]
        self.edit_first_trip(damage)
        self.assert_fails_with("date is outside the trip")

    def test_float_days_fails(self):
        self.edit_first_trip(lambda t: t.update(days=float(t["days"])))
        self.assert_fails_with("days must be an integer")

    def test_bool_photo_count_and_float_index_fail(self):
        self.edit_first_trip(lambda t: t.update(photo_count=True, index=0.0))
        self.assert_fails_with("photo_count must be an integer")
        self.assert_fails_with("index must be an integer")

    def test_float_city_photo_count_fails(self):
        self.edit_first_trip(lambda t: t["cities"][0].update(photo_count=2.0))
        self.assert_fails_with("city photo_count must be an integer")

    def test_float_width_and_height_fail(self):
        def damage(trip):
            trip["photos"][0]["width"] = 1600.0
            trip["photos"][0]["height"] = True
        self.edit_first_trip(damage)
        self.assert_fails_with("width/height must be positive integers")

    def test_empty_title_and_city_name_fail(self):
        def damage(trip):
            trip["title"] = " "
            trip["cities"][0]["name"] = ""
        self.edit_first_trip(damage)
        self.assert_fails_with("title must be a non-empty string")
        self.assert_fails_with("city name must be a non-empty string")

    def test_near_title_is_allowed(self):
        self.edit_first_trip(lambda t: t.update(title="Near Somewhere"))
        result = check_contract.check(self.folder, "mock")
        self.assertFalse(any("title" in message for message in result.errors))

    def test_invalid_city_dates(self):
        self.edit_first_trip(lambda t: t["cities"][0].update(arrive="not-a-date"))
        self.assert_fails_with("city arrive/leave invalid date")

    def test_city_arrive_after_leave(self):
        def damage(trip):
            city = trip["cities"][0]
            city["arrive"], city["leave"] = city["leave"], city["arrive"]
            city["arrive"] = trip["end_date"]
            city["leave"] = trip["start_date"]
        self.edit_first_trip(damage)
        self.assert_fails_with("city arrive is after leave")

    def test_city_dates_outside_the_trip(self):
        def damage(trip):
            trip["cities"][0]["leave"] = "2030-01-01"
        self.edit_first_trip(damage)
        self.assert_fails_with("city dates outside the trip")

    def test_non_string_tags_fail(self):
        def damage(trip):
            trip["tags"] = ["food", 3]
            trip["photos"][0]["tags"] = [None]
        self.edit_first_trip(damage)
        result = self.assert_fails_with("tags must be a list of strings")
        self.assertGreaterEqual(sum("tags must be a list of strings" in m for m in result.errors), 2)


class ThumbnailTests(MockCopyCase):
    def first_thumb(self):
        doc = self.load()
        return self.folder / doc["trips"][0]["photos"][0]["thumb"]

    def test_missing_thumbnail_is_an_error_in_mock_mode(self):
        self.first_thumb().unlink()
        self.assert_fails_with("missing thumbnail file", "mock")

    def test_missing_thumbnail_is_counted_in_data_mode(self):
        self.first_thumb().unlink()
        result = check_contract.check(self.folder, "data")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.missing_thumbs, 1)
        self.assertGreater(result.total_thumbs, 1)

    def test_oversized_thumbnail_fails_in_data_mode(self):
        from PIL import Image
        Image.new("RGB", (500, 300)).save(self.first_thumb(), "WEBP")
        self.assert_fails_with("wrong width", "data")

    def test_smaller_thumbnail_is_fine_in_data_mode_but_not_mock_mode(self):
        from PIL import Image
        Image.new("RGB", (300, 200)).save(self.first_thumb(), "WEBP")
        self.assertEqual(check_contract.check(self.folder, "data").errors, [])
        self.assert_fails_with("wrong width", "mock")

    def test_non_webp_thumbnail_fails(self):
        from PIL import Image
        Image.new("RGB", (400, 300)).save(self.first_thumb(), "PNG")
        self.assert_fails_with("is not WEBP", "data")

    def test_offsetless_taken_at_is_a_warning_in_data_mode(self):
        photos = set()

        def damage(doc):
            for radius_trips in doc["trips_by_radius"].values():
                for trip in radius_trips:
                    for photo in trip["photos"]:
                        photo["taken_at"] = photo["taken_at"][:19]
            doc["trips"] = doc["trips_by_radius"]["50"]
            photos.update(p["id"] for tl in doc["trips_by_radius"].values() for t in tl
                          for p in t["photos"])
        self.mutate_trips(damage)
        result = check_contract.check(self.folder, "data")
        self.assertEqual(result.errors, [])
        self.assertEqual(len(result.warnings), len(photos))  # once per photo, not per radius


class CliTests(MockCopyCase):
    def run_main(self, argv):
        root = Path(self._tmp.name) / "root"
        target = root / "frontend" / "public"
        target.mkdir(parents=True, exist_ok=True)
        if not (target / "mock").exists():
            shutil.copytree(self.folder, target / "mock")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = check_contract.main(argv, root=root)
        return code, out.getvalue()

    def test_ok_output_and_exit_code(self):
        code, text = self.run_main([])
        self.assertEqual(code, 0)
        self.assertRegex(text.strip(), r"^Contract 1\.1 \(mock\): OK \(\d+ checks\), 0 warnings$")

    def test_failure_output_is_capped_at_twenty_lines(self):
        def damage(doc):
            for trip in doc["trips_by_radius"]["50"]:
                for photo in trip["photos"]:
                    photo["id"] = "bad"
        self.mutate_trips(damage)
        code, text = self.run_main(["--folder", "mock"])
        lines = text.strip().splitlines()
        self.assertEqual(code, 1)
        self.assertRegex(lines[0], r"^FAILED: \d+ errors$")
        self.assertEqual(len(lines), 21)


if __name__ == "__main__":
    unittest.main()
