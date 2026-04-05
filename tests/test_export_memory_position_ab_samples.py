import tempfile
import unittest
from pathlib import Path

from scripts.export_memory_position_ab_samples import (
    build_markdown_report,
    build_sample_rows,
    default_scenarios,
    load_scenarios_from_config,
    normalize_scenarios,
    write_csv,
    write_jsonl,
    write_markdown,
)


class ExportMemoryPositionABSamplesTests(unittest.TestCase):
    def test_build_sample_rows(self):
        rows = build_sample_rows(
            [
                {
                    "arm": "A_top",
                    "memory_position": "top",
                    "memory_every": None,
                    "trace_id": "tr_a",
                    "timeline": [
                        {
                            "slot": 1,
                            "item_type": "memory_post",
                            "book_id": "b1",
                            "chunk_id": "c1",
                            "book_title": "Book",
                            "title": "Title",
                            "teaser_preview": "teaser",
                        }
                    ],
                }
            ]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["arm"], "A_top")
        self.assertEqual(rows[0]["item_type"], "memory_post")
        self.assertEqual(rows[0]["slot"], 1)

    def test_write_jsonl_and_csv(self):
        rows = [
            {
                "arm": "A_top",
                "memory_position": "top",
                "memory_every": None,
                "trace_id": "tr_a",
                "slot": 1,
                "item_type": "memory_post",
                "book_id": "b1",
                "chunk_id": "c1",
                "book_title": "Book",
                "title": "Title",
                "teaser_preview": "teaser",
            }
        ]
        with tempfile.TemporaryDirectory() as td:
            jsonl_path = Path(td) / "samples.jsonl"
            csv_path = Path(td) / "samples.csv"
            write_jsonl(jsonl_path, rows)
            write_csv(csv_path, rows)
            self.assertTrue(jsonl_path.exists())
            self.assertTrue(csv_path.exists())
            self.assertEqual(len(jsonl_path.read_text(encoding="utf-8").strip().splitlines()), 1)
            self.assertIn("arm,memory_position,memory_every,trace_id", csv_path.read_text(encoding="utf-8"))

    def test_build_and_write_markdown(self):
        arms = [
            {
                "arm": "A_top",
                "memory_position": "top",
                "memory_every": None,
                "memory_inserted": 1,
                "memory_positions": [1],
                "trace_id": "tr_a",
                "timeline": [
                    {
                        "slot": 1,
                        "item_type": "memory_post",
                        "book_title": "Book",
                        "title": "Title",
                        "teaser_preview": "teaser",
                    }
                ],
            }
        ]
        markdown = build_markdown_report(
            backend="postgres",
            user_id="u1",
            limit=8,
            interval_every=3,
            random_seed=7,
            arms=arms,
        )
        self.assertIn("# Memory Position A/B Samples", markdown)
        self.assertIn("## Arms Overview", markdown)
        self.assertIn("## A_top (`top`)", markdown)
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "ab.md"
            write_markdown(output, markdown)
            self.assertTrue(output.exists())
            self.assertIn("Memory Position A/B Samples", output.read_text(encoding="utf-8"))

    def test_default_scenarios(self):
        scenarios = default_scenarios(interval_every=3, random_seed=7)
        self.assertEqual(len(scenarios), 3)
        self.assertEqual(scenarios[0]["memory_position"], "top")
        self.assertEqual(scenarios[1]["memory_every"], 3)
        self.assertEqual(scenarios[2]["memory_seed"], 7)

    def test_normalize_scenarios(self):
        scenarios = normalize_scenarios(
            [
                {"arm": "A", "memory_position": "top"},
                {"arm": "B", "memory_position": "interval", "memory_every": 2},
                {
                    "arm": "C",
                    "memory_position": "random",
                    "memory_every": 2,
                    "memory_seed": 9,
                    "memory_random_never_first": 0,
                },
            ],
            default_interval_every=3,
            default_random_seed=7,
        )
        self.assertEqual(len(scenarios), 3)
        self.assertEqual(scenarios[1]["query_suffix"], "&memory_position=interval&memory_every=2")
        self.assertIn("memory_seed=9", scenarios[2]["query_suffix"])
        self.assertIn("memory_random_never_first=0", scenarios[2]["query_suffix"])

    def test_load_scenarios_from_config(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "scenarios.json"
            path.write_text(
                """
                {
                  "arms": [
                    {"arm":"A_top","memory_position":"top"},
                    {"arm":"B_interval","memory_position":"interval","memory_every":2}
                  ]
                }
                """,
                encoding="utf-8",
            )
            scenarios = load_scenarios_from_config(
                path,
                default_interval_every=3,
                default_random_seed=7,
            )
            self.assertEqual(len(scenarios), 2)
            self.assertEqual(scenarios[0]["arm"], "A_top")
            self.assertEqual(scenarios[1]["memory_every"], 2)

    def test_load_scenarios_from_yaml_config(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "scenarios.yaml"
            path.write_text(
                """
                arms:
                  - arm: A_top
                    memory_position: top
                  - arm: B_interval_2
                    memory_position: interval
                    memory_every: 2
                """,
                encoding="utf-8",
            )
            scenarios = load_scenarios_from_config(
                path,
                default_interval_every=3,
                default_random_seed=7,
            )
            self.assertEqual(len(scenarios), 2)
            self.assertEqual(scenarios[0]["memory_position"], "top")
            self.assertEqual(scenarios[1]["memory_every"], 2)


if __name__ == "__main__":
    unittest.main()
