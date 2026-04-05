import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import scripts.import_book as import_book_mod
from scripts.import_book import load_input_payload, normalize_text, run_with_retry, text_to_blocks, write_error_report


class ImportBookTests(unittest.TestCase):
    def test_normalize_text_removes_nul_and_control_chars(self):
        dirty = "A\x00B\x07C\r\n\r\nD"
        self.assertEqual(normalize_text(dirty), "ABC\n\nD")

    def test_markdown_fence_code_boundary(self):
        text = """
# 第一节

这是一段说明文字。

```python
def add(a, b):
    return a + b
```

继续说明。
""".strip()
        blocks = text_to_blocks(text)
        kinds = [b["kind"] for b in blocks]
        self.assertEqual(kinds, ["heading", "paragraph", "code", "paragraph"])
        self.assertIn("def add", blocks[2]["text"])

    def test_indented_code_block_boundary(self):
        text = """
1.1 开始

普通说明段。

    for i in range(3):
        print(i)

收尾段。
""".strip()
        blocks = text_to_blocks(text)
        kinds = [b["kind"] for b in blocks]
        self.assertEqual(kinds, ["heading", "paragraph", "code", "paragraph"])
        self.assertIn("for i in range(3)", blocks[2]["text"])

    def test_run_with_retry_success_after_failures(self):
        state = {"n": 0}

        def flaky():
            state["n"] += 1
            if state["n"] < 3:
                raise RuntimeError("temporary failure")
            return "ok"

        out = run_with_retry(flaky, retries=2, retry_delay_sec=0)
        self.assertEqual(out, "ok")
        self.assertEqual(state["n"], 3)

    def test_write_error_report(self):
        with tempfile.TemporaryDirectory() as td:
            report = write_error_report(
                RuntimeError("boom"),
                report_dir=Path(td),
                context={"book_id": "b_test", "title": "T"},
            )
            self.assertTrue(report.exists())
            payload = report.read_text(encoding="utf-8")
            self.assertIn("\"status\": \"error\"", payload)
            self.assertIn("\"book_id\": \"b_test\"", payload)

    def test_load_input_payload_pdf(self):
        class FakePage:
            @staticmethod
            def extract_text():
                return "第一段。\n\n第二段。"

        class FakeReader:
            def __init__(self, _path: str):
                self.pages = [FakePage()]

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.pdf"
            path.write_bytes(b"%PDF-1.4")
            with mock.patch.object(import_book_mod, "PdfReader", FakeReader):
                payload = load_input_payload(path, book_type="technical", language="zh")
        self.assertEqual(payload.get("book_type"), "technical")
        self.assertEqual(payload.get("language"), "zh")
        self.assertTrue(payload.get("clean_text"))
        self.assertGreaterEqual(len(payload.get("blocks", [])), 1)

    def test_load_input_payload_epub(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.epub"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr(
                    "META-INF/container.xml",
                    """<?xml version='1.0'?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    """<?xml version='1.0' encoding='utf-8'?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf">
  <manifest>
    <item id="chap1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
  </spine>
</package>
""",
                )
                zf.writestr(
                    "OEBPS/chap1.xhtml",
                    "<html><body><h1>第一章</h1><p>这里是 EPUB 内容。</p></body></html>",
                )
            payload = load_input_payload(path, book_type="general", language="zh")
        self.assertEqual(payload.get("book_type"), "general")
        self.assertEqual(payload.get("language"), "zh")
        self.assertIn("EPUB 内容", payload.get("clean_text", ""))
        extract_stats = payload.get("source_extract_stats", {})
        self.assertEqual(int(extract_stats.get("section_docs_total", -1)), 1)
        self.assertEqual(int(extract_stats.get("section_docs_kept", -1)), 1)
        self.assertEqual(int(extract_stats.get("section_docs_skipped_toc", -1)), 0)
        self.assertEqual(int(extract_stats.get("section_doc_name_sample_limit", -1)), 5)
        self.assertEqual(extract_stats.get("section_doc_name_samples"), ["OEBPS/chap1.xhtml"])
        self.assertEqual(extract_stats.get("section_doc_name_samples_basename"), ["chap1.xhtml"])
        self.assertEqual(extract_stats.get("section_doc_kept_name_samples"), ["OEBPS/chap1.xhtml"])
        self.assertEqual(extract_stats.get("section_doc_kept_name_samples_basename"), ["chap1.xhtml"])
        self.assertEqual(
            extract_stats.get("section_doc_name_sampled_counts"),
            {"all": 1, "kept": 1, "skipped_toc": 0, "empty": 0},
        )
        self.assertEqual(
            extract_stats.get("section_doc_basename_unique_counts"),
            {"all": 1, "kept": 1, "skipped_toc": 0, "empty": 0},
        )
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk"),
            [{"basename": "chap1.xhtml", "count": 1}],
        )
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_min_count", -1)), 1)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_limit", -1)), 5)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_limit_applied", -1)), 5)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_total_candidates", -1)), 1)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_other_count", -1)), 0)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision", -1)), 4)
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_source"), "default")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note"),
            "rounded_to_4_decimal_places",
        )
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template"),
            "rounded_to_{precision}_decimal_places",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_version"), "v1")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note"),
            "template source is a static literal",
        )
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template"),
            "template source is a {source} literal",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_version"), "v1")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_source"),
            "derived_from_section_doc_basename_topk_coverage_ratio_precision",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_source_version"), "v1")
        self.assertAlmostEqual(float(extract_stats.get("section_doc_basename_topk_coverage_ratio_raw", -1)), 1.0, places=6)
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_raw_source"),
            "len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates (unrounded)",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_raw_source_version"), "v1")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_raw_source_version_note"),
            "v1=len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates (unrounded)",
        )
        self.assertAlmostEqual(float(extract_stats.get("section_doc_basename_topk_coverage_ratio", -1)), 1.0, places=4)
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_source"),
            "len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates",
        )
        self.assertEqual(bool(extract_stats.get("section_doc_basename_topk_threshold_applied", True)), False)
        self.assertGreaterEqual(len(payload.get("blocks", [])), 1)

    def test_load_input_payload_epub_custom_sample_limit(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.epub"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr(
                    "META-INF/container.xml",
                    """<?xml version='1.0'?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    """<?xml version='1.0' encoding='utf-8'?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf">
  <manifest>
    <item id="chap1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
    <item id="chap2" href="chap2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
    <itemref idref="chap2"/>
  </spine>
</package>
""",
                )
                zf.writestr("OEBPS/chap1.xhtml", "<html><body><p>一</p></body></html>")
                zf.writestr("OEBPS/chap2.xhtml", "<html><body><p>二</p></body></html>")
            payload = load_input_payload(path, book_type="general", language="zh", epub_sample_limit=1)
        extract_stats = payload.get("source_extract_stats", {})
        self.assertEqual(int(extract_stats.get("section_doc_name_sample_limit", -1)), 1)
        self.assertEqual(extract_stats.get("section_doc_name_samples"), ["OEBPS/chap1.xhtml"])
        self.assertEqual(extract_stats.get("section_doc_name_samples_basename"), ["chap1.xhtml"])
        self.assertEqual(extract_stats.get("section_doc_kept_name_samples"), ["OEBPS/chap1.xhtml"])
        self.assertEqual(extract_stats.get("section_doc_kept_name_samples_basename"), ["chap1.xhtml"])
        self.assertEqual(
            extract_stats.get("section_doc_name_sampled_counts"),
            {"all": 1, "kept": 1, "skipped_toc": 0, "empty": 0},
        )
        self.assertEqual(
            extract_stats.get("section_doc_basename_unique_counts"),
            {"all": 1, "kept": 1, "skipped_toc": 0, "empty": 0},
        )
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk"),
            [{"basename": "chap1.xhtml", "count": 1}],
        )
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_min_count", -1)), 1)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_limit", -1)), 5)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_limit_applied", -1)), 5)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_total_candidates", -1)), 1)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_other_count", -1)), 0)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision", -1)), 4)
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_source"), "default")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note"),
            "rounded_to_4_decimal_places",
        )
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template"),
            "rounded_to_{precision}_decimal_places",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_version"), "v1")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note"),
            "template source is a static literal",
        )
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template"),
            "template source is a {source} literal",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_version"), "v1")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_source"),
            "derived_from_section_doc_basename_topk_coverage_ratio_precision",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_source_version"), "v1")
        self.assertAlmostEqual(float(extract_stats.get("section_doc_basename_topk_coverage_ratio_raw", -1)), 1.0, places=6)
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_raw_source"),
            "len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates (unrounded)",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_raw_source_version"), "v1")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_raw_source_version_note"),
            "v1=len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates (unrounded)",
        )
        self.assertAlmostEqual(float(extract_stats.get("section_doc_basename_topk_coverage_ratio", -1)), 1.0, places=4)
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_source"),
            "len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates",
        )
        self.assertEqual(bool(extract_stats.get("section_doc_basename_topk_threshold_applied", True)), False)

    def test_load_input_payload_epub_missing_bs4_dependency(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.epub"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("chapter.xhtml", "<html><body><p>demo</p></body></html>")
            with mock.patch.object(import_book_mod, "BeautifulSoup", None):
                with self.assertRaisesRegex(RuntimeError, "beautifulsoup4"):
                    load_input_payload(path, book_type="general", language="zh")

    def test_load_input_payload_epub_skips_toc_noise(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.epub"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr(
                    "META-INF/container.xml",
                    """<?xml version='1.0'?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    """<?xml version='1.0' encoding='utf-8'?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf">
  <manifest>
    <item id="toc" href="toc.xhtml" media-type="application/xhtml+xml"/>
    <item id="chap1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="toc"/>
    <itemref idref="chap1"/>
  </spine>
</package>
""",
                )
                zf.writestr(
                    "OEBPS/toc.xhtml",
                    """
<html><body>
  <nav id="toc"><h1>Table of Contents</h1><p>1. Intro .... 1</p><p>2. Theory .... 7</p></nav>
</body></html>
""",
                )
                zf.writestr(
                    "OEBPS/chap1.xhtml",
                    "<html><body><h1>第一章</h1><p>真正章节内容。</p></body></html>",
                )
            payload = load_input_payload(path, book_type="general", language="zh")
        clean_text = payload.get("clean_text", "")
        self.assertIn("真正章节内容", clean_text)
        self.assertNotIn("Table of Contents", clean_text)
        extract_stats = payload.get("source_extract_stats", {})
        self.assertEqual(int(extract_stats.get("section_docs_total", -1)), 2)
        self.assertEqual(int(extract_stats.get("section_docs_kept", -1)), 1)
        self.assertEqual(int(extract_stats.get("section_docs_skipped_toc", -1)), 1)
        self.assertEqual(extract_stats.get("section_doc_name_samples"), ["OEBPS/toc.xhtml", "OEBPS/chap1.xhtml"])
        self.assertEqual(extract_stats.get("section_doc_name_samples_basename"), ["toc.xhtml", "chap1.xhtml"])
        self.assertEqual(extract_stats.get("section_doc_kept_name_samples"), ["OEBPS/chap1.xhtml"])
        self.assertEqual(extract_stats.get("section_doc_kept_name_samples_basename"), ["chap1.xhtml"])
        self.assertEqual(extract_stats.get("section_doc_skipped_toc_name_samples"), ["OEBPS/toc.xhtml"])
        self.assertEqual(extract_stats.get("section_doc_skipped_toc_name_samples_basename"), ["toc.xhtml"])
        self.assertEqual(
            extract_stats.get("section_doc_name_sampled_counts"),
            {"all": 2, "kept": 1, "skipped_toc": 1, "empty": 0},
        )
        self.assertEqual(
            extract_stats.get("section_doc_basename_unique_counts"),
            {"all": 2, "kept": 1, "skipped_toc": 1, "empty": 0},
        )
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk"),
            [{"basename": "chap1.xhtml", "count": 1}, {"basename": "toc.xhtml", "count": 1}],
        )
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_min_count", -1)), 1)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_limit", -1)), 5)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_limit_applied", -1)), 5)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_total_candidates", -1)), 2)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_other_count", -1)), 0)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision", -1)), 4)
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_source"), "default")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note"),
            "rounded_to_4_decimal_places",
        )
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template"),
            "rounded_to_{precision}_decimal_places",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_version"), "v1")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note"),
            "template source is a static literal",
        )
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template"),
            "template source is a {source} literal",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_version"), "v1")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_source"),
            "derived_from_section_doc_basename_topk_coverage_ratio_precision",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_source_version"), "v1")
        self.assertAlmostEqual(float(extract_stats.get("section_doc_basename_topk_coverage_ratio_raw", -1)), 1.0, places=6)
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_raw_source"),
            "len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates (unrounded)",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_raw_source_version"), "v1")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_raw_source_version_note"),
            "v1=len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates (unrounded)",
        )
        self.assertAlmostEqual(float(extract_stats.get("section_doc_basename_topk_coverage_ratio", -1)), 1.0, places=4)
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_source"),
            "len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates",
        )
        self.assertEqual(bool(extract_stats.get("section_doc_basename_topk_threshold_applied", True)), False)

    def test_load_input_payload_epub_topk_min_count_filter(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.epub"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr(
                    "META-INF/container.xml",
                    """<?xml version='1.0'?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    """<?xml version='1.0' encoding='utf-8'?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf">
  <manifest>
    <item id="a1" href="a/dup.xhtml" media-type="application/xhtml+xml"/>
    <item id="a2" href="b/dup.xhtml" media-type="application/xhtml+xml"/>
    <item id="a3" href="c/solo.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="a1"/>
    <itemref idref="a2"/>
    <itemref idref="a3"/>
  </spine>
</package>
""",
                )
                zf.writestr("OEBPS/a/dup.xhtml", "<html><body><p>dup 1</p></body></html>")
                zf.writestr("OEBPS/b/dup.xhtml", "<html><body><p>dup 2</p></body></html>")
                zf.writestr("OEBPS/c/solo.xhtml", "<html><body><p>solo</p></body></html>")
            payload = load_input_payload(
                path,
                book_type="general",
                language="zh",
                epub_sample_limit=5,
                epub_topk_min_count=2,
            )
        extract_stats = payload.get("source_extract_stats", {})
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_min_count", -1)), 2)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_limit", -1)), 5)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_limit_applied", -1)), 5)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_total_candidates", -1)), 1)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_other_count", -1)), 0)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision", -1)), 4)
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_source"), "default")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note"),
            "rounded_to_4_decimal_places",
        )
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template"),
            "rounded_to_{precision}_decimal_places",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_version"), "v1")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note"),
            "template source is a static literal",
        )
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template"),
            "template source is a {source} literal",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_version"), "v1")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_source"),
            "derived_from_section_doc_basename_topk_coverage_ratio_precision",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_source_version"), "v1")
        self.assertAlmostEqual(float(extract_stats.get("section_doc_basename_topk_coverage_ratio_raw", -1)), 1.0, places=6)
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_raw_source"),
            "len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates (unrounded)",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_raw_source_version"), "v1")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_raw_source_version_note"),
            "v1=len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates (unrounded)",
        )
        self.assertAlmostEqual(float(extract_stats.get("section_doc_basename_topk_coverage_ratio", -1)), 1.0, places=4)
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_source"),
            "len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates",
        )
        self.assertEqual(bool(extract_stats.get("section_doc_basename_topk_threshold_applied", False)), True)
        self.assertEqual(extract_stats.get("section_doc_basename_topk"), [{"basename": "dup.xhtml", "count": 2}])

    def test_load_input_payload_epub_topk_limit(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.epub"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr(
                    "META-INF/container.xml",
                    """<?xml version='1.0'?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    """<?xml version='1.0' encoding='utf-8'?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf">
  <manifest>
    <item id="a1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
    <item id="a2" href="chap2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="a1"/>
    <itemref idref="a2"/>
  </spine>
</package>
""",
                )
                zf.writestr("OEBPS/chap1.xhtml", "<html><body><p>one</p></body></html>")
                zf.writestr("OEBPS/chap2.xhtml", "<html><body><p>two</p></body></html>")
            payload = load_input_payload(
                path,
                book_type="general",
                language="zh",
                epub_sample_limit=5,
                epub_topk_min_count=1,
                epub_topk_limit=1,
            )
        extract_stats = payload.get("source_extract_stats", {})
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_limit", -1)), 1)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_limit_applied", -1)), 1)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_total_candidates", -1)), 2)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_other_count", -1)), 1)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision", -1)), 4)
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_source"), "default")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note"),
            "rounded_to_4_decimal_places",
        )
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template"),
            "rounded_to_{precision}_decimal_places",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_version"), "v1")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note"),
            "template source is a static literal",
        )
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template"),
            "template source is a {source} literal",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_version"), "v1")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_source"),
            "derived_from_section_doc_basename_topk_coverage_ratio_precision",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_source_version"), "v1")
        self.assertAlmostEqual(float(extract_stats.get("section_doc_basename_topk_coverage_ratio_raw", -1)), 0.5, places=6)
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_raw_source"),
            "len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates (unrounded)",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_raw_source_version"), "v1")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_raw_source_version_note"),
            "v1=len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates (unrounded)",
        )
        self.assertAlmostEqual(float(extract_stats.get("section_doc_basename_topk_coverage_ratio", -1)), 0.5, places=4)
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_source"),
            "len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates",
        )
        self.assertEqual(len(extract_stats.get("section_doc_basename_topk", [])), 1)

    def test_load_input_payload_epub_topk_coverage_ratio_precision(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "sample.epub"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr(
                    "META-INF/container.xml",
                    """<?xml version='1.0'?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
""",
                )
                zf.writestr(
                    "OEBPS/content.opf",
                    """<?xml version='1.0' encoding='utf-8'?>
<package version="2.0" xmlns="http://www.idpf.org/2007/opf">
  <manifest>
    <item id="a1" href="chap1.xhtml" media-type="application/xhtml+xml"/>
    <item id="a2" href="chap2.xhtml" media-type="application/xhtml+xml"/>
    <item id="a3" href="chap3.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="a1"/>
    <itemref idref="a2"/>
    <itemref idref="a3"/>
  </spine>
</package>
""",
                )
                zf.writestr("OEBPS/chap1.xhtml", "<html><body><p>one</p></body></html>")
                zf.writestr("OEBPS/chap2.xhtml", "<html><body><p>two</p></body></html>")
                zf.writestr("OEBPS/chap3.xhtml", "<html><body><p>three</p></body></html>")
            payload = load_input_payload(
                path,
                book_type="general",
                language="zh",
                epub_sample_limit=5,
                epub_topk_min_count=1,
                epub_topk_limit=1,
                epub_topk_coverage_ratio_precision=2,
            )
        extract_stats = payload.get("source_extract_stats", {})
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_total_candidates", -1)), 3)
        self.assertEqual(int(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision", -1)), 2)
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_source"), "cli")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note"),
            "rounded_to_2_decimal_places",
        )
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template"),
            "rounded_to_{precision}_decimal_places",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_version"), "v1")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note"),
            "template source is a static literal",
        )
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template"),
            "template source is a {source} literal",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note"), "template source field is a static template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template"), "template source field is a {source} template literal")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source"), "static_template")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version"), "v1")
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_version"), "v1")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_source"),
            "derived_from_section_doc_basename_topk_coverage_ratio_precision",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_precision_note_source_version"), "v1")
        self.assertAlmostEqual(float(extract_stats.get("section_doc_basename_topk_coverage_ratio_raw", -1)), 1 / 3, places=6)
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_raw_source"),
            "len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates (unrounded)",
        )
        self.assertEqual(extract_stats.get("section_doc_basename_topk_coverage_ratio_raw_source_version"), "v1")
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_raw_source_version_note"),
            "v1=len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates (unrounded)",
        )
        self.assertAlmostEqual(float(extract_stats.get("section_doc_basename_topk_coverage_ratio", -1)), 0.33, places=4)
        self.assertEqual(
            extract_stats.get("section_doc_basename_topk_coverage_ratio_source"),
            "len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates",
        )


if __name__ == "__main__":
    unittest.main()
