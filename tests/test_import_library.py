import tempfile
import unittest
from pathlib import Path

from scripts.import_library import (
    derive_title_from_path,
    infer_book_type_from_name,
    list_supported_files,
)


class ImportLibraryTests(unittest.TestCase):
    def test_derive_title_strips_author_like_suffix(self):
        path = Path("A first course in numerical analysis (A. Iserles).pdf")
        self.assertEqual(
            derive_title_from_path(path),
            "A first course in numerical analysis",
        )

    def test_derive_title_keeps_numeric_suffix(self):
        path = Path("Linear Algebra (3rd Edition).pdf")
        self.assertEqual(
            derive_title_from_path(path),
            "Linear Algebra (3rd Edition)",
        )

    def test_infer_book_type_auto(self):
        self.assertEqual(
            infer_book_type_from_name("Numerical Analysis and Differential Equations"),
            "technical",
        )
        self.assertEqual(
            infer_book_type_from_name("A sci-fi novel story"),
            "fiction",
        )
        self.assertEqual(
            infer_book_type_from_name("像哲学家一样生活", default_book_type="general"),
            "general",
        )

    def test_list_supported_files_non_recursive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.pdf").write_text("x", encoding="utf-8")
            (root / "b.epub").write_text("x", encoding="utf-8")
            (root / "c.txt").write_text("x", encoding="utf-8")
            (root / "ignore.png").write_text("x", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "d.pdf").write_text("x", encoding="utf-8")

            files = list_supported_files(root, recursive=False)
            self.assertEqual([p.name for p in files], ["a.pdf", "b.epub", "c.txt"])

    def test_list_supported_files_recursive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "a.pdf").write_text("x", encoding="utf-8")
            nested = root / "nested"
            nested.mkdir()
            (nested / "d.pdf").write_text("x", encoding="utf-8")

            files = list_supported_files(root, recursive=True)
            self.assertEqual([p.name for p in files], ["a.pdf", "d.pdf"])


if __name__ == "__main__":
    unittest.main()
