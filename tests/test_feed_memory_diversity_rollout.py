import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from app import (  # noqa: E402
    deterministic_rollout_bucket,
    format_memory_diversity_default_note,
    memory_diversity_default_from_env,
    parse_rollout_percent,
    resolve_memory_diversity_bucket,
    resolve_memory_diversity_default_source,
    resolve_memory_diversity_gray_percent,
    resolve_memory_diversity_rollout_enabled,
    resolve_memory_diversity_rollout_bucket_hit,
    resolve_memory_diversity_rollout_bucket_distance,
    resolve_memory_diversity_rollout_bucket_percentile,
    resolve_memory_diversity_rollout_bucket_percentile_label,
    resolve_memory_diversity_rollout_mode,
    resolve_default_memory_diversity,
)


class FeedMemoryDiversityRolloutTests(unittest.TestCase):
    def test_parse_rollout_percent(self):
        self.assertIsNone(parse_rollout_percent(None))
        self.assertIsNone(parse_rollout_percent(""))
        self.assertIsNone(parse_rollout_percent("x"))
        self.assertEqual(parse_rollout_percent("0"), 0)
        self.assertEqual(parse_rollout_percent("55"), 55)
        self.assertEqual(parse_rollout_percent("-1"), 0)
        self.assertEqual(parse_rollout_percent("999"), 100)

    def test_memory_diversity_default_from_env(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BOOKFLOW_MEMORY_DIVERSITY_DEFAULT", None)
            self.assertTrue(memory_diversity_default_from_env())
        with patch.dict(os.environ, {"BOOKFLOW_MEMORY_DIVERSITY_DEFAULT": "off"}, clear=False):
            self.assertFalse(memory_diversity_default_from_env())
        with patch.dict(os.environ, {"BOOKFLOW_MEMORY_DIVERSITY_DEFAULT": "ON"}, clear=False):
            self.assertTrue(memory_diversity_default_from_env())

    def test_resolve_default_memory_diversity_rollout_bounds(self):
        with patch.dict(
            os.environ,
            {
                "BOOKFLOW_MEMORY_DIVERSITY_DEFAULT": "off",
                "BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT": "100",
            },
            clear=False,
        ):
            self.assertTrue(resolve_default_memory_diversity("user-a"))
        with patch.dict(
            os.environ,
            {
                "BOOKFLOW_MEMORY_DIVERSITY_DEFAULT": "on",
                "BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT": "0",
            },
            clear=False,
        ):
            self.assertFalse(resolve_default_memory_diversity("user-a"))

    def test_resolve_default_memory_diversity_rollout_deterministic(self):
        with patch.dict(
            os.environ,
            {
                "BOOKFLOW_MEMORY_DIVERSITY_DEFAULT": "off",
                "BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT": "50",
                "BOOKFLOW_MEMORY_DIVERSITY_GRAY_SALT": "test-salt",
            },
            clear=False,
        ):
            first = resolve_default_memory_diversity("user-a")
            second = resolve_default_memory_diversity("user-a")
            self.assertEqual(first, second)

    def test_resolve_default_memory_diversity_invalid_rollout_falls_back(self):
        with patch.dict(
            os.environ,
            {
                "BOOKFLOW_MEMORY_DIVERSITY_DEFAULT": "off",
                "BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT": "not-int",
            },
            clear=False,
        ):
            self.assertFalse(resolve_default_memory_diversity("user-a"))

    def test_deterministic_rollout_bucket_range(self):
        bucket = deterministic_rollout_bucket("user-a", "salt-a")
        self.assertGreaterEqual(bucket, 0)
        self.assertLess(bucket, 100)

    def test_resolve_memory_diversity_default_source(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT", None)
            self.assertEqual(resolve_memory_diversity_default_source(), "default")
        with patch.dict(os.environ, {"BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT": "30"}, clear=False):
            self.assertEqual(resolve_memory_diversity_default_source(), "gray")

    def test_resolve_memory_diversity_gray_percent(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT", None)
            self.assertIsNone(resolve_memory_diversity_gray_percent())
        with patch.dict(os.environ, {"BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT": "30"}, clear=False):
            self.assertEqual(resolve_memory_diversity_gray_percent(), 30)

    def test_format_memory_diversity_default_note(self):
        note_default = format_memory_diversity_default_note(
            default_source="default",
            default_enabled=True,
            gray_percent=None,
        )
        self.assertEqual(note_default, "source=default; default_value=on")
        note_gray = format_memory_diversity_default_note(
            default_source="gray",
            default_enabled=False,
            gray_percent=30,
        )
        self.assertEqual(note_gray, "source=gray; gray_percent=30; default_value=off")

    def test_resolve_memory_diversity_bucket(self):
        with patch.dict(os.environ, {"BOOKFLOW_MEMORY_DIVERSITY_GRAY_SALT": "test-salt"}, clear=False):
            first = resolve_memory_diversity_bucket("user-a")
            second = resolve_memory_diversity_bucket("user-a")
            self.assertEqual(first, second)
            self.assertGreaterEqual(first, 0)
            self.assertLess(first, 100)

    def test_resolve_memory_diversity_rollout_enabled(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT", None)
            self.assertFalse(resolve_memory_diversity_rollout_enabled())
        with patch.dict(os.environ, {"BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT": "30"}, clear=False):
            self.assertTrue(resolve_memory_diversity_rollout_enabled())

    def test_resolve_memory_diversity_rollout_mode(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT", None)
            self.assertEqual(resolve_memory_diversity_rollout_mode(), "off")
        with patch.dict(os.environ, {"BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT": "0"}, clear=False):
            self.assertEqual(resolve_memory_diversity_rollout_mode(), "off")
        with patch.dict(os.environ, {"BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT": "100"}, clear=False):
            self.assertEqual(resolve_memory_diversity_rollout_mode(), "full")
        with patch.dict(os.environ, {"BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT": "30"}, clear=False):
            self.assertEqual(resolve_memory_diversity_rollout_mode(), "partial")

    def test_resolve_memory_diversity_rollout_bucket_hit(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT", None)
            self.assertFalse(resolve_memory_diversity_rollout_bucket_hit("user-a"))
        with patch.dict(os.environ, {"BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT": "0"}, clear=False):
            self.assertFalse(resolve_memory_diversity_rollout_bucket_hit("user-a"))
        with patch.dict(os.environ, {"BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT": "100"}, clear=False):
            self.assertTrue(resolve_memory_diversity_rollout_bucket_hit("user-a"))
        with patch.dict(
            os.environ,
            {
                "BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT": "30",
                "BOOKFLOW_MEMORY_DIVERSITY_GRAY_SALT": "test-salt",
            },
            clear=False,
        ):
            expected = resolve_memory_diversity_bucket("user-a") < 30
            self.assertEqual(resolve_memory_diversity_rollout_bucket_hit("user-a"), expected)

    def test_resolve_memory_diversity_rollout_bucket_distance(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT", None)
            self.assertIsNone(resolve_memory_diversity_rollout_bucket_distance("user-a"))
        with patch.dict(
            os.environ,
            {
                "BOOKFLOW_MEMORY_DIVERSITY_GRAY_PERCENT": "30",
                "BOOKFLOW_MEMORY_DIVERSITY_GRAY_SALT": "test-salt",
            },
            clear=False,
        ):
            expected = resolve_memory_diversity_bucket("user-a") - 30
            self.assertEqual(resolve_memory_diversity_rollout_bucket_distance("user-a"), expected)

    def test_resolve_memory_diversity_rollout_bucket_percentile(self):
        with patch.dict(os.environ, {"BOOKFLOW_MEMORY_DIVERSITY_GRAY_SALT": "test-salt"}, clear=False):
            bucket = resolve_memory_diversity_bucket("user-a")
            percentile = resolve_memory_diversity_rollout_bucket_percentile("user-a")
            self.assertEqual(percentile, round(bucket / 100.0, 2))
            self.assertGreaterEqual(percentile, 0.0)
            self.assertLess(percentile, 1.0)

    def test_resolve_memory_diversity_rollout_bucket_percentile_label(self):
        with patch.dict(os.environ, {"BOOKFLOW_MEMORY_DIVERSITY_GRAY_SALT": "test-salt"}, clear=False):
            bucket = resolve_memory_diversity_bucket("user-a")
            label = resolve_memory_diversity_rollout_bucket_percentile_label("user-a")
            self.assertEqual(label, f"P{bucket:02d}")


if __name__ == "__main__":
    unittest.main()
