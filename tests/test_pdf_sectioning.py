import tempfile
import unittest
from pathlib import Path

from scripts.pdf_sectioning import materialize_pdf_sections, normalize_toc_entries, pick_leaf_entries, rank_toc_source

try:
    from pypdf import PdfReader, PdfWriter
except Exception:  # pragma: no cover
    PdfReader = None
    PdfWriter = None


class PdfSectioningTests(unittest.TestCase):
    def test_rank_toc_source_priority(self):
        source, entries = rank_toc_source([{"title": "A", "start_page": 1}], [{"title": "B", "start_page": 2}])
        self.assertEqual(source, "pdf_outline")
        self.assertEqual(entries[0]["title"], "A")

        source2, entries2 = rank_toc_source([], [{"title": "Manual", "start_page": 3}])
        self.assertEqual(source2, "manual_toc")
        self.assertEqual(entries2[0]["title"], "Manual")

        source3, entries3 = rank_toc_source([], [])
        self.assertEqual(source3, "pending_manual_toc")
        self.assertEqual(entries3, [])

    def test_normalize_toc_entries_and_leaf_pick(self):
        normalized, warnings = normalize_toc_entries(
            [
                {"title": "第1章", "level": 1, "start_page": 1},
                {"title": "1.1", "level": 2, "start_page": 1},
                {"title": "1.2", "level": 2, "start_page": 3},
                {"title": "第2章", "level": 1, "start_page": 5},
            ],
            total_pages=8,
        )
        self.assertEqual(len(normalized), 4)
        self.assertGreaterEqual(len(warnings), 0)
        leaves = pick_leaf_entries(normalized)
        self.assertEqual([x["title"] for x in leaves], ["1.1", "1.2", "第2章"])

    @unittest.skipIf(PdfWriter is None or PdfReader is None, "pypdf not installed")
    def test_materialize_pdf_sections_outputs_pdf_chunks(self):
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            src_pdf = td_path / "src.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=595, height=842)
            writer.add_blank_page(width=595, height=842)
            writer.add_blank_page(width=595, height=842)
            with src_pdf.open("wb") as f:
                writer.write(f)

            toc_entries = [
                {"title": "第1章", "level": 1, "start_page": 1, "end_page": 2},
                {"title": "1.1", "level": 2, "start_page": 1, "end_page": 1},
                {"title": "1.2", "level": 2, "start_page": 2, "end_page": 2},
                {"title": "第2章", "level": 1, "start_page": 3, "end_page": 3},
            ]
            out = materialize_pdf_sections(
                pdf_path=src_pdf,
                book_id="11111111-1111-1111-1111-111111111111",
                toc_entries=toc_entries,
                toc_source="manual_toc",
                derived_root=td_path / "derived",
            )

            self.assertEqual(out["total_pages"], 3)
            self.assertEqual(out["materialized_chunks"], 3)
            self.assertEqual(out["generated_pdf_count"], 3)
            self.assertEqual(out["failed_entries"], [])

            records = out["chunk_records"]
            self.assertEqual(len(records), 3)
            first_abs = td_path / "derived" / "11111111-1111-1111-1111-111111111111" / f"{records[0]['chunk_id']}.pdf"
            self.assertTrue(first_abs.exists())
            first_pdf = PdfReader(str(first_abs))
            self.assertEqual(len(first_pdf.pages), 1)


if __name__ == "__main__":
    unittest.main()
