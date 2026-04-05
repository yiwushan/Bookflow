import unittest
import json
import tempfile
from pathlib import Path

from scripts.replay_memory_feed import (
    build_markdown_report,
    format_memory_type_distribution,
    parse_scenarios,
    summarize_memory_types,
    summarize_items,
    write_csv,
    write_jsonl,
    write_markdown_report,
)


class ReplayMemoryFeedTests(unittest.TestCase):
    def test_parse_scenarios_normalized(self):
        scenarios = parse_scenarios("top,1,3,none,3")
        self.assertEqual(scenarios, [("top", None), ("1", 1), ("3", 3)])

    def test_parse_scenarios_invalid(self):
        with self.assertRaises(ValueError):
            parse_scenarios("")
        with self.assertRaises(ValueError):
            parse_scenarios("0")
        with self.assertRaises(ValueError):
            parse_scenarios("abc")

    def test_summarize_items(self):
        positions, timeline = summarize_items(
            [
                {"item_type": "chunk", "title": "A", "teaser_text": "alpha"},
                {"item_type": "memory_post", "title": "B", "teaser_text": "beta", "memory_type": "month_ago"},
            ]
        )
        self.assertEqual(positions, [2])
        self.assertEqual(len(timeline), 2)
        self.assertEqual(timeline[1]["item_type"], "memory_post")
        self.assertEqual(timeline[1]["memory_type"], "month_ago")

    def test_summarize_memory_types(self):
        stats = summarize_memory_types(
            [
                {"item_type": "chunk"},
                {"item_type": "memory_post", "memory_type": "month_ago"},
                {"item_type": "memory_post", "memory_type": "year_ago"},
                {"item_type": "memory_post", "memory_type": "month_ago"},
            ]
        )
        self.assertEqual(stats, {"month_ago": 2, "year_ago": 1})
        self.assertEqual(format_memory_type_distribution(stats), "month_ago:2, year_ago:1")
        self.assertEqual(format_memory_type_distribution({}), "(none)")

    def test_write_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "replay.jsonl"
            write_jsonl(output, [{"scenario": "top"}, {"scenario": "1"}])
            self.assertTrue(output.exists())
            lines = output.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(json.loads(lines[0])["scenario"], "top")

    def test_build_markdown_report(self):
        markdown = build_markdown_report(
            [
                {
                    "scenario": "top",
                    "memory_every": None,
                    "memory_inserted": 1,
                    "memory_positions": [1],
                    "trace_id": "tr_x",
                    "timeline": [
                        {
                            "slot": 1,
                            "item_type": "memory_post",
                            "memory_type": "month_ago",
                            "book_title": "B",
                            "title": "T",
                            "teaser_preview": "hello|world",
                        }
                    ],
                }
            ],
            backend="postgres",
            user_id="u1",
            limit=8,
        )
        self.assertIn("# Memory Feed Replay Report", markdown)
        self.assertIn("## Overview", markdown)
        self.assertIn("- csv_schema_version: `replay_memory_feed.csv.v1`", markdown)
        self.assertIn("- jsonl_schema_version: `replay_memory_feed.jsonl.v1`", markdown)
        self.assertIn("- markdown_schema_version: `replay_memory_feed.markdown.v1`", markdown)
        self.assertIn(
            "- schema_version_consistency_note: `csv=replay_memory_feed.csv.v1;jsonl=replay_memory_feed.jsonl.v1`",
            markdown,
        )
        self.assertIn(
            "| top | 1 | 1 | month_ago:1 | memory_post | 0 | tr_x | replay_memory_feed.markdown.v1 |",
            markdown,
        )
        self.assertIn("## Scenario `top`", markdown)
        self.assertIn("- memory_type_distribution: `month_ago:1`", markdown)
        self.assertIn("- first_item_type: `memory_post`", markdown)
        self.assertIn("hello\\|world", markdown)
        self.assertIn("| Slot | Type | Book | Title | Teaser |", markdown)

    def test_write_markdown_report(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "replay.md"
            write_markdown_report(output, "# R\n")
            self.assertTrue(output.exists())
            self.assertEqual(output.read_text(encoding="utf-8"), "# R\n")

    def test_write_csv(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "replay.csv"
            write_csv(
                output,
                [
                    {
                        "scenario": "top",
                        "memory_every": "",
                        "memory_inserted": 1,
                        "memory_positions": "1",
                        "first_item_type": "memory_post",
                        "items_count": 8,
                        "trace_id": "tr_1",
                        "user_id": "u1",
                        "limit": 8,
                        "memory_type_distribution": "month_ago:1",
                        "jsonl_schema_version": "replay_memory_feed.jsonl.v1",
                        "markdown_schema_version": "replay_memory_feed.markdown.v1",
                        "markdown_schema_version_source": "constant",
                        "schema_version": "replay_memory_feed.csv.v1",
                    }
                ],
            )
            self.assertTrue(output.exists())
            text = output.read_text(encoding="utf-8")
            self.assertIn(
                "scenario,memory_every,memory_inserted,memory_positions,first_item_type,items_count,trace_id,user_id,limit,memory_type_distribution,jsonl_schema_version,markdown_schema_version,markdown_schema_version_source,schema_version",
                text,
            )
            self.assertIn("top", text)
            self.assertIn("month_ago:1", text)
            self.assertIn("replay_memory_feed.jsonl.v1", text)
            self.assertIn("replay_memory_feed.markdown.v1", text)
            self.assertIn("constant", text)
            self.assertIn("replay_memory_feed.csv.v1", text)


if __name__ == "__main__":
    unittest.main()
