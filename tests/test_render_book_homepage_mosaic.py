import unittest
import tempfile
import json
from pathlib import Path

from scripts.render_book_homepage_mosaic import build_mosaic_tiles, render_mosaic_html, write_tiles_json


class RenderBookHomepageMosaicTests(unittest.TestCase):
    def test_build_mosaic_tiles(self):
        tiles, summary = build_mosaic_tiles(
            [
                {"chunk_id": "c1", "global_index": 1, "section_id": "s1", "chunk_title": "T1", "read_events": 2},
                {"chunk_id": "c2", "global_index": 2, "section_id": "s2", "chunk_title": "T2", "read_events": 0},
            ],
            min_read_events=1,
        )
        self.assertEqual(len(tiles), 2)
        self.assertEqual(tiles[0]["state"], "read")
        self.assertEqual(tiles[1]["state"], "unread")
        self.assertEqual(summary["read_chunks"], 1)
        self.assertEqual(summary["total_chunks"], 2)
        self.assertEqual(summary["completion_rate"], 0.5)

    def test_render_mosaic_html(self):
        html = render_mosaic_html(
            book_id="book1",
            book_title="书名",
            user_id="user1",
            exported_at="2026-03-29T06:00:00+00:00",
            min_read_events=1,
            html_schema_version="book_homepage_mosaic.html.v1",
            tiles_json_schema_version="book_homepage_mosaic.tiles.v1",
            tiles=[
                {
                    "chunk_id": "c1",
                    "global_index": 1,
                    "section_id": "s1",
                    "chunk_title": "标题|A",
                    "read_events": 1,
                    "state": "read",
                }
            ],
            summary={"total_chunks": 1, "read_chunks": 1, "completion_rate": 1.0},
        )
        self.assertIn("<!doctype html>", html.lower())
        self.assertIn('class="mosaic-grid"', html)
        self.assertIn('class="tile read"', html)
        self.assertIn("标题|A", html)
        self.assertIn("read 1/1 (100%)", html)
        self.assertIn("min_read_events: 1", html)
        self.assertIn('name="bookflow:html_schema_version" content="book_homepage_mosaic.html.v1"', html)
        self.assertIn('name="bookflow:tiles_json_schema_version" content="book_homepage_mosaic.tiles.v1"', html)
        self.assertIn("tiles_json_schema_version: book_homepage_mosaic.tiles.v1", html)
        self.assertIn("已读 tile (1)", html)
        self.assertIn("未读 tile (0)", html)
        self.assertIn("exported_at: 2026-03-29T06:00:00+00:00", html)

    def test_write_tiles_json(self):
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "tiles.json"
            write_tiles_json(
                output,
                book_id="book1",
                book_title="书名",
                html_title="书名 · 进度拼图",
                user_id="user1",
                exported_at="2026-03-29T06:00:00+00:00",
                min_read_events=1,
                summary={"total_chunks": 1, "read_chunks": 1, "completion_rate": 1.0},
                tiles=[
                    {
                        "chunk_id": "c1",
                        "global_index": 1,
                        "section_id": "s1",
                        "chunk_title": "T1",
                        "read_events": 1,
                        "state": "read",
                    }
                ],
            )
            self.assertTrue(output.exists())
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("schema_version"), "book_homepage_mosaic.tiles.v1")
            self.assertEqual(payload.get("tiles_json_schema_version"), "book_homepage_mosaic.tiles.v1")
            self.assertEqual(payload.get("html_schema_version"), "book_homepage_mosaic.html.v1")
            self.assertEqual(payload.get("book_id"), "book1")
            self.assertEqual(payload.get("html_title"), "书名 · 进度拼图")
            self.assertEqual(payload.get("exported_at"), "2026-03-29T06:00:00+00:00")
            self.assertEqual(payload.get("min_read_events"), 1)
            self.assertEqual(len(payload.get("tiles", [])), 1)


if __name__ == "__main__":
    unittest.main()
