import json
import tempfile
import unittest
from pathlib import Path

from scripts.pipeline import Config, load_config, load_config_for_book_type, run_pipeline


def make_payload(blocks, book_type="technical", language="zh", extract_confidence=0.8):
    return {
        "book_id": "b_test",
        "book_type": book_type,
        "language": language,
        "extract_confidence": extract_confidence,
        "blocks": blocks,
    }


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()

    def test_section_heading_creates_multiple_sections(self):
        payload = make_payload(
            [
                {"kind": "heading", "text": "1. A", "page": 1, "bbox": [0, 0, 1, 0.1]},
                {"kind": "paragraph", "text": "alpha", "page": 1, "bbox": [0, 0.1, 1, 0.3]},
                {"kind": "heading", "text": "2. B", "page": 2, "bbox": [0, 0, 1, 0.1]},
                {"kind": "paragraph", "text": "beta", "page": 2, "bbox": [0, 0.1, 1, 0.3]},
            ]
        )
        out = run_pipeline(payload, self.cfg)
        self.assertEqual(out["chunk_count"], 2)
        self.assertEqual(out["chunks"][0]["section_id"], "sec_01")
        self.assertEqual(out["chunks"][1]["section_id"], "sec_02")

    def test_technical_formula_bias_prefers_crop(self):
        payload = make_payload(
            [
                {"kind": "heading", "text": "1", "page": 1, "bbox": [0, 0, 1, 0.1]},
                {"kind": "formula", "text": "w_{t+1}=w_t-η∂L/∂w", "page": 1, "bbox": [0, 0.2, 1, 0.3]},
                {"kind": "paragraph", "text": "解释段落", "page": 1, "bbox": [0, 0.3, 1, 0.5]},
            ],
            book_type="technical",
        )
        out = run_pipeline(payload, self.cfg)
        self.assertEqual(out["chunks"][0]["render_mode"], "crop")

    def test_code_block_not_misdetected_as_formula(self):
        payload = make_payload(
            [
                {"kind": "heading", "text": "1", "page": 1, "bbox": [0, 0, 1, 0.1]},
                {"kind": "code", "text": "x = 1\nfor i in range(3):\n    x = x + i", "page": 1, "bbox": [0, 0.2, 1, 0.5]},
            ],
            book_type="general",
        )
        out = run_pipeline(payload, self.cfg)
        self.assertTrue(out["chunks"][0]["has_code"])
        self.assertFalse(out["chunks"][0]["has_formula"])

    def test_hard_char_limit_splits_chunk(self):
        long_text = "段落" * 2500
        payload = make_payload(
            [
                {"kind": "heading", "text": "1", "page": 1, "bbox": [0, 0, 1, 0.1]},
                {"kind": "paragraph", "text": long_text, "page": 1, "bbox": [0, 0.2, 1, 0.8]},
            ]
        )
        out = run_pipeline(payload, self.cfg)
        self.assertGreaterEqual(out["chunk_count"], 2)

    def test_prerequisite_link_within_same_section(self):
        payload = make_payload(
            [
                {"kind": "heading", "text": "1", "page": 1, "bbox": [0, 0, 1, 0.1]},
                {"kind": "paragraph", "text": ("A" * 2000), "page": 1, "bbox": [0, 0.2, 1, 0.5]},
                {"kind": "paragraph", "text": ("B" * 2000), "page": 2, "bbox": [0, 0.2, 1, 0.5]},
            ]
        )
        out = run_pipeline(payload, self.cfg)
        self.assertGreaterEqual(out["chunk_count"], 2)
        second = out["chunks"][1]
        first = out["chunks"][0]
        self.assertEqual(second["prerequisite_chunk_ids"], [first["chunk_id"]])

    def test_output_contains_render_reason_stats(self):
        payload = make_payload(
            [
                {"kind": "heading", "text": "1", "page": 1, "bbox": [0, 0, 1, 0.1]},
                {"kind": "formula", "text": "w_{t+1}=w_t-η∂L/∂w", "page": 1, "bbox": [0, 0.2, 1, 0.3]},
            ],
            book_type="technical",
        )
        out = run_pipeline(payload, self.cfg)
        self.assertIn("stats", out)
        self.assertIn("render_mode_counts", out["stats"])
        self.assertIn("render_reason_counts", out["stats"])
        self.assertGreaterEqual(out["stats"]["render_reason_counts"].get("technical_formula_bias", 0), 1)

    def test_load_config_overrides_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "pipeline.json"
            p.write_text(
                json.dumps(
                    {
                        "hard_char_max": 1200,
                        "extract_confidence_crop_threshold": 0.6,
                        "technical_formula_bias": False,
                    }
                ),
                encoding="utf-8",
            )
            cfg = load_config(p)
            self.assertEqual(cfg.hard_char_max, 1200)
            self.assertEqual(cfg.extract_confidence_crop_threshold, 0.6)
            self.assertFalse(cfg.technical_formula_bias)

    def test_load_config_template_selection(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "pipeline.json"
            p.write_text(
                json.dumps(
                    {
                        "defaults": {
                            "hard_char_max": 3000,
                            "technical_formula_bias": False,
                        },
                        "templates": {
                            "technical": {
                                "hard_char_max": 2400,
                                "technical_formula_bias": True,
                            },
                            "fiction": {
                                "hard_char_max": 4200,
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            cfg_tech = load_config_for_book_type(p, "technical")
            cfg_fic = load_config_for_book_type(p, "fiction")
            cfg_gen = load_config_for_book_type(p, "general")
            self.assertEqual(cfg_tech.hard_char_max, 2400)
            self.assertTrue(cfg_tech.technical_formula_bias)
            self.assertEqual(cfg_fic.hard_char_max, 4200)
            self.assertFalse(cfg_fic.technical_formula_bias)
            self.assertEqual(cfg_gen.hard_char_max, 3000)
            self.assertFalse(cfg_gen.technical_formula_bias)

    def test_pipeline_template_regression_sample_set(self):
        blocks = [
            {"kind": "heading", "text": "1 模板回归", "page": 1, "bbox": [0, 0, 1, 0.1]},
            {"kind": "formula", "text": "w_{t+1}=w_t-η∂L/∂w", "page": 1, "bbox": [0, 0.1, 1, 0.2]},
            {"kind": "paragraph", "text": "理论说明" * 900, "page": 1, "bbox": [0, 0.2, 1, 0.9]},
        ]

        outputs = {}
        for book_type in ("general", "fiction", "technical"):
            cfg = load_config_for_book_type(Path("config/pipeline.json"), book_type)
            payload = make_payload(blocks, book_type=book_type, extract_confidence=0.95)
            outputs[book_type] = run_pipeline(payload, cfg)

        # hard_char_max: fiction(4200) > general(3200), fiction should split less.
        self.assertEqual(outputs["fiction"]["chunk_count"], 1)
        self.assertGreater(outputs["general"]["chunk_count"], outputs["fiction"]["chunk_count"])
        self.assertGreaterEqual(outputs["technical"]["chunk_count"], outputs["general"]["chunk_count"])

        # technical template enables technical_formula_bias => crop.
        self.assertTrue(all(c["render_mode"] == "crop" for c in outputs["technical"]["chunks"]))
        self.assertTrue(all(c["render_mode"] == "reflow" for c in outputs["general"]["chunks"]))
        self.assertTrue(all(c["render_mode"] == "reflow" for c in outputs["fiction"]["chunks"]))

    def test_pipeline_template_baseline_file(self):
        baseline_path = Path("tests/fixtures/pipeline_template_baseline_v1.json")
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        template = baseline["payload_template"]

        blocks = [
            {"kind": "heading", "text": template["heading"], "page": 1, "bbox": [0, 0, 1, 0.1]},
            {"kind": "formula", "text": template["formula"], "page": 1, "bbox": [0, 0.1, 1, 0.2]},
            {
                "kind": "paragraph",
                "text": template["paragraph_token"] * int(template["paragraph_repeat"]),
                "page": 1,
                "bbox": [0, 0.2, 1, 0.9],
            },
        ]

        for book_type, expected in baseline["expected"].items():
            cfg = load_config_for_book_type(Path("config/pipeline.json"), book_type)
            payload = {
                "book_id": template["book_id"],
                "book_type": book_type,
                "language": template["language"],
                "extract_confidence": template["extract_confidence"],
                "blocks": blocks,
            }
            out = run_pipeline(payload, cfg)
            self.assertEqual(out["chunk_count"], expected["chunk_count"])
            self.assertEqual(out["stats"]["render_mode_counts"], expected["render_mode_counts"])
            self.assertEqual(out["stats"]["render_reason_counts"], expected["render_reason_counts"])


if __name__ == "__main__":
    unittest.main()
