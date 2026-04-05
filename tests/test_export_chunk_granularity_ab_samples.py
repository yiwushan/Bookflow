import json
import tempfile
import unittest
from pathlib import Path

from scripts.export_chunk_granularity_ab_samples import (
    build_ab_rows,
    build_markdown_report,
    split_two_segments,
    write_csv,
    write_jsonl,
    write_markdown,
)


class ExportChunkGranularityABSamplesTests(unittest.TestCase):
    def test_split_two_segments_short_text(self):
        parts = split_two_segments("短文本", min_split_chars=20)
        self.assertEqual(parts, ["短文本"])

    def test_split_two_segments_long_text(self):
        text = (
            "第一段介绍问题背景。第二段解释核心概念并给出定义。"
            "第三段给出一个最小例子帮助理解。第四段总结下一步实践建议。"
        )
        parts = split_two_segments(text, min_split_chars=20)
        self.assertEqual(len(parts), 2)
        self.assertTrue(parts[0])
        self.assertTrue(parts[1])
        self.assertEqual("".join(parts), " ".join(text.split()))

    def test_build_ab_rows(self):
        rows, summary = build_ab_rows(
            [
                {
                    "chunk_id": "ck1",
                    "book_id": "b1",
                    "book_title": "Book 1",
                    "section_id": "sec1",
                    "chunk_title": "Title 1",
                    "text_content": "A。B。C。D。" * 30,
                },
                {
                    "chunk_id": "ck2",
                    "book_id": "b1",
                    "book_title": "Book 1",
                    "section_id": "sec2",
                    "chunk_title": "Title 2",
                    "text_content": "短段落",
                },
            ],
            min_split_chars=40,
        )
        self.assertGreaterEqual(len(rows), 4)
        self.assertEqual(summary["chunks_scanned"], 2)
        self.assertEqual(summary["chunks_with_text"], 2)
        self.assertEqual(summary["full_rows_count"], 2)
        self.assertGreaterEqual(summary["split_rows_count"], 2)

        arm_names = {row["arm"] for row in rows}
        self.assertIn("A_full_section", arm_names)
        self.assertIn("B_split_two", arm_names)

    def test_build_markdown_report(self):
        rows = [
            {
                "arm": "A_full_section",
                "chunk_id": "ck1",
                "piece_index": 1,
                "piece_count": 1,
                "text_length": 120,
                "text_preview": "hello|world",
            }
        ]
        summary = {
            "chunks_scanned": 1,
            "chunks_with_text": 1,
            "full_rows_count": 1,
            "split_rows_count": 1,
            "split_chunk_count": 0,
            "split_chunk_rate": 0.0,
        }
        md = build_markdown_report(
            book_id_filter="book1",
            section_prefix="sec_",
            chunk_title_keyword="梯度",
            keyword_filter_stats={"total_candidates": 10, "matched_candidates": 3, "hit_rate": 0.3},
            limit=10,
            min_split_chars=120,
            summary=summary,
            rows=rows,
            preview_top=10,
        )
        self.assertIn("# Chunk Granularity A/B Samples", md)
        self.assertIn("- section_prefix: `sec_`", md)
        self.assertIn("- chunk_title_keyword: `梯度`", md)
        self.assertIn("- keyword_filter_hit_rate: `0.3`", md)
        self.assertIn("- jsonl_schema_version: `chunk_granularity_ab_samples.jsonl.v1`", md)
        self.assertIn("- csv_schema_version: `chunk_granularity_ab_samples.csv.v1`", md)
        self.assertIn("- markdown_schema_version: `chunk_granularity_ab_samples.markdown.v1`", md)
        self.assertIn(
            "- schema_version_consistency_note: `csv=chunk_granularity_ab_samples.csv.v1;jsonl=chunk_granularity_ab_samples.jsonl.v1`",
            md,
        )
        self.assertIn("## Arm Summary", md)
        self.assertIn("## CSV Notes", md)
        self.assertIn("keyword_filter_summary", md)
        self.assertIn("hello\\|world", md)

    def test_write_jsonl_csv_markdown(self):
        with tempfile.TemporaryDirectory() as td:
            jsonl_path = Path(td) / "rows.jsonl"
            csv_path = Path(td) / "rows.csv"
            md_path = Path(td) / "rows.md"
            rows = [
                {
                    "arm": "A_full_section",
                    "row_rank": 1,
                    "book_id": "b1",
                    "book_title": "Book 1",
                    "chunk_id": "ck1",
                    "section_id": "sec1",
                    "chunk_title": "T1",
                    "piece_index": 1,
                    "piece_count": 1,
                    "text_length": 12,
                    "text_preview": "preview",
                    "split_strategy": "full_section",
                }
            ]
            write_jsonl(jsonl_path, rows)
            write_csv(csv_path, rows)
            write_markdown(md_path, "# Report\n")
            self.assertTrue(jsonl_path.exists())
            self.assertTrue(csv_path.exists())
            self.assertTrue(md_path.exists())
            first_json = json.loads(jsonl_path.read_text(encoding="utf-8").strip())
            self.assertEqual(first_json["arm"], "A_full_section")
            self.assertEqual(first_json.get("schema_version"), "chunk_granularity_ab_samples.jsonl.v1")
            self.assertEqual(first_json.get("csv_schema_version"), "chunk_granularity_ab_samples.csv.v1")
            csv_text = csv_path.read_text(encoding="utf-8")
            self.assertIn("arm,row_rank,book_id,book_title,chunk_id", csv_text)
            self.assertIn("markdown_schema_version", csv_text)
            self.assertIn("chunk_granularity_ab_samples.markdown.v1", csv_text)
            self.assertIn("chunk_granularity_ab_samples.csv.v1", csv_text)
            self.assertEqual(md_path.read_text(encoding="utf-8"), "# Report\n")

    def test_write_csv_with_keyword_filter_summary(self):
        with tempfile.TemporaryDirectory() as td:
            csv_path = Path(td) / "rows.csv"
            write_csv(
                csv_path,
                [
                    {
                        "arm": "A_full_section",
                        "row_rank": 1,
                        "book_id": "b1",
                        "book_title": "Book 1",
                        "chunk_id": "ck1",
                        "section_id": "sec1",
                        "chunk_title": "T1",
                        "piece_index": 1,
                        "piece_count": 1,
                        "text_length": 12,
                        "text_preview": "preview",
                        "split_strategy": "full_section",
                    }
                ],
                keyword_filter_stats={"total_candidates": 10, "matched_candidates": 3, "hit_rate": 0.3},
            )
            text = csv_path.read_text(encoding="utf-8")
            self.assertIn("keyword_filter_summary", text)
            self.assertIn("keyword_filter_hit_rate=0.3; matched=3; total=10", text)
            self.assertIn("chunk_granularity_ab_samples.markdown.v1", text)
            self.assertIn("chunk_granularity_ab_samples.csv.v1", text)


if __name__ == "__main__":
    unittest.main()
