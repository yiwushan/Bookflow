import json
import tempfile
import unittest
from pathlib import Path

from scripts.auto_tag_chunks import DEFAULT_TAG_RULES, load_rules, load_rules_bundle


class AutoTagRulesTests(unittest.TestCase):
    def test_load_rules_fallback_to_default(self):
        rules = load_rules(Path("/tmp/does_not_exist_bookflow_rules.json"))
        self.assertGreaterEqual(len(rules), 1)
        self.assertIn("干货", rules)

    def test_load_rules_from_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "rules.json"
            p.write_text(
                json.dumps(
                    {
                        "rules": {
                            "测试标签": {
                                "category": "general",
                                "keywords": ["alpha", "beta"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            rules = load_rules(p)
            self.assertEqual(len(rules), 1)
            self.assertIn("测试标签", rules)
            self.assertEqual(rules["测试标签"]["keywords"], ["alpha", "beta"])

    def test_default_rules_not_empty(self):
        self.assertGreaterEqual(len(DEFAULT_TAG_RULES), 1)

    def test_load_rules_versioned_schema(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "rules_versioned.json"
            p.write_text(
                json.dumps(
                    {
                        "active_rule_version": "v2",
                        "rule_versions": {
                            "v1": {
                                "旧规则": {
                                    "category": "general",
                                    "keywords": ["old"],
                                }
                            },
                            "v2": {
                                "新规则": {
                                    "category": "general",
                                    "keywords": ["new"],
                                }
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            bundle = load_rules_bundle(p)
            self.assertEqual(bundle["schema"], "versioned")
            self.assertEqual(bundle["active_rule_version"], "v2")
            self.assertEqual(bundle["selected_rule_version"], "v2")
            self.assertIn("新规则", bundle["rules"])

            rollback_bundle = load_rules_bundle(p, rule_version="v1")
            self.assertEqual(rollback_bundle["selected_rule_version"], "v1")
            self.assertIn("旧规则", rollback_bundle["rules"])

    def test_load_rules_versioned_invalid_version_fallback_to_active(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "rules_versioned.json"
            p.write_text(
                json.dumps(
                    {
                        "active_rule_version": "v1",
                        "rule_versions": {
                            "v1": {
                                "唯一规则": {
                                    "category": "general",
                                    "keywords": ["k1"],
                                }
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            bundle = load_rules_bundle(p, rule_version="not-exists")
            self.assertEqual(bundle["selected_rule_version"], "v1")
            rules = load_rules(p, rule_version="not-exists")
            self.assertIn("唯一规则", rules)


if __name__ == "__main__":
    unittest.main()
