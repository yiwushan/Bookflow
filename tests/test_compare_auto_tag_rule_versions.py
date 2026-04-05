import unittest
from collections import Counter
import json
import tempfile
from pathlib import Path

from scripts.compare_auto_tag_rule_versions import (
    build_markdown_report,
    build_rule_deltas,
    compute_rule_hits,
    write_csv_report,
    write_jsonl_report,
    write_markdown_report,
)


class CompareAutoTagRuleVersionsTests(unittest.TestCase):
    def test_compute_rule_hits(self):
        chunks = [
            ("c1", "这里包含梯度和损失函数"),
            ("c2", "普通文本，没有关键词"),
            ("c3", "for step in range(10): print(step)"),
        ]
        rules = {
            "算法": {"keywords": ["梯度", "损失函数"]},
            "编程": {"keywords": ["for ", "print("]},
        }
        out = compute_rule_hits(chunks, rules)
        self.assertEqual(out["chunks_scanned"], 3)
        self.assertEqual(out["rule_hit_chunks"], 2)
        self.assertGreater(out["rule_hit_rate"], 0.0)
        self.assertEqual(int(out["per_rule_counter"]["算法"]), 1)
        self.assertEqual(int(out["per_rule_counter"]["编程"]), 1)

    def test_build_rule_deltas(self):
        base = Counter({"算法": 5, "编程": 3})
        target = Counter({"算法": 4, "编程": 6, "心理学": 2})
        rows = build_rule_deltas(base, target, top=10)
        row_map = {r["rule"]: r for r in rows}
        self.assertEqual(row_map["算法"]["delta_chunks"], -1)
        self.assertEqual(row_map["编程"]["delta_chunks"], 3)
        self.assertEqual(row_map["心理学"]["delta_chunks"], 2)

    def test_write_csv_report(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "compare.csv"
            summary = {"chunks_scanned": 10, "delta_rule_hit_rate": 0.1}
            rule_deltas = [{"rule": "算法", "base_chunks": 3, "target_chunks": 5, "delta_chunks": 2}]
            write_csv_report(output, summary=summary, rule_deltas=rule_deltas)
            self.assertTrue(output.exists())
            text = output.read_text(encoding="utf-8")
            self.assertIn(
                "row_type,rule_rank,rule,base_chunks,target_chunks,delta_chunks,metric,value,schema_version,jsonl_schema_version,markdown_schema_version",
                text,
            )
            self.assertIn("summary", text)
            self.assertIn("rule_delta", text)
            self.assertIn("compare_auto_tag_rule_versions.jsonl.v1", text)
            self.assertIn("compare_auto_tag_rule_versions.markdown.v1", text)

    def test_build_and_write_markdown_report(self):
        summary = {"chunks_scanned": 10, "delta_rule_hit_rate": 0.1}
        rule_deltas = [{"rule": "算法", "base_chunks": 3, "target_chunks": 5, "delta_chunks": 2}]
        markdown = build_markdown_report(
            book_id_filter="book1",
            limit=10,
            top=20,
            rules_path="config/auto_tag_rules.json",
            base_version="v0",
            target_version="v1",
            summary=summary,
            rule_deltas=rule_deltas,
        )
        self.assertIn("# Auto-Tag Rule Version Compare", markdown)
        self.assertIn("- top: `20`", markdown)
        self.assertIn("## Summary", markdown)
        self.assertIn("## Rule Deltas", markdown)
        self.assertIn("## Export Schemas", markdown)
        self.assertIn("rule_rank", markdown)
        self.assertIn("schema_version", markdown)
        self.assertIn("compare_auto_tag_rule_versions.csv.v1", markdown)
        self.assertIn("compare_auto_tag_rule_versions.jsonl.v1", markdown)
        self.assertIn("- markdown_schema_version: `compare_auto_tag_rule_versions.markdown.v1`", markdown)
        self.assertIn(
            "schema_version_consistency_note: `csv=compare_auto_tag_rule_versions.csv.v1;jsonl=compare_auto_tag_rule_versions.jsonl.v1`",
            markdown,
        )
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "compare.md"
            write_markdown_report(output, markdown)
            self.assertTrue(output.exists())
            self.assertIn("delta_rule_hit_rate", output.read_text(encoding="utf-8"))

    def test_write_jsonl_report(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "compare.jsonl"
            write_jsonl_report(
                output,
                book_id_filter="book1",
                limit=10,
                base_version="v0",
                target_version="v1",
                summary={"chunks_scanned": 10},
                rule_deltas=[{"rule": "算法", "base_chunks": 3, "target_chunks": 5, "delta_chunks": 2}],
            )
            self.assertTrue(output.exists())
            lines = output.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn('"row_type": "summary"', lines[0])
            self.assertIn('"schema_version"', lines[0])
            summary_row = json.loads(lines[0])
            self.assertEqual(summary_row.get("csv_schema_version"), "compare_auto_tag_rule_versions.csv.v1")
            self.assertEqual(summary_row.get("markdown_schema_version"), "compare_auto_tag_rule_versions.markdown.v1")
            self.assertIn('"row_type": "rule_delta"', lines[1])
            delta_row = json.loads(lines[1])
            self.assertEqual(int(delta_row.get("rule_rank", 0)), 1)
            self.assertIsNotNone(delta_row.get("schema_version"))
            self.assertEqual(delta_row.get("csv_schema_version"), "compare_auto_tag_rule_versions.csv.v1")
            self.assertEqual(delta_row.get("markdown_schema_version"), "compare_auto_tag_rule_versions.markdown.v1")


if __name__ == "__main__":
    unittest.main()
