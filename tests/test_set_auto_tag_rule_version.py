import json
import tempfile
import unittest
from pathlib import Path

from scripts.set_auto_tag_rule_version import set_active_rule_version


class SetAutoTagRuleVersionTests(unittest.TestCase):
    def _write_versioned_config(self, path: Path) -> None:
        path.write_text(
            json.dumps(
                {
                    "active_rule_version": "v2",
                    "rule_versions": {
                        "v1": {"标签A": {"category": "general", "keywords": ["a"]}},
                        "v2": {"标签B": {"category": "general", "keywords": ["b"]}},
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_set_active_rule_version_dry_run(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "rules.json"
            self._write_versioned_config(config_path)

            payload = set_active_rule_version(
                config_path=config_path,
                to_version="v1",
                dry_run=True,
                backup_dir=Path(td) / "backups",
            )
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["previous_active_rule_version"], "v2")
            self.assertEqual(payload["next_active_rule_version"], "v1")
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["active_rule_version"], "v2")

    def test_set_active_rule_version_write_and_backup(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "rules.json"
            backup_dir = Path(td) / "backups"
            self._write_versioned_config(config_path)

            payload = set_active_rule_version(
                config_path=config_path,
                to_version="v1",
                dry_run=False,
                backup_dir=backup_dir,
            )
            self.assertEqual(payload["status"], "ok")
            self.assertIsNotNone(payload["backup_path"])
            self.assertTrue(Path(payload["backup_path"]).exists())
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["active_rule_version"], "v1")

    def test_set_active_rule_version_invalid_target(self):
        with tempfile.TemporaryDirectory() as td:
            config_path = Path(td) / "rules.json"
            self._write_versioned_config(config_path)
            with self.assertRaises(ValueError):
                set_active_rule_version(config_path=config_path, to_version="v3", dry_run=True, backup_dir=None)


if __name__ == "__main__":
    unittest.main()
