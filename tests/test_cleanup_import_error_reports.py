import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.cleanup_import_error_reports import (
    build_markdown_report,
    cleanup_reports,
    determine_exit_code,
    output_payload,
    truncate_paths,
    write_csv_summary,
    write_markdown_report,
)


class CleanupImportErrorReportsTests(unittest.TestCase):
    def _touch_with_age_days(self, path: Path, days_old: int) -> None:
        path.write_text('{"status":"error"}', encoding="utf-8")
        ts = (datetime.now(timezone.utc) - timedelta(days=days_old)).timestamp()
        os.utime(path, (ts, ts))

    def test_cleanup_reports_archive_mode(self):
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "reports"
            archive_dir = Path(td) / "archive"
            report_dir.mkdir(parents=True, exist_ok=True)
            old_file = report_dir / "import_error_old.json"
            new_file = report_dir / "import_error_new.json"
            self._touch_with_age_days(old_file, 10)
            self._touch_with_age_days(new_file, 1)

            payload = cleanup_reports(
                report_dir=report_dir,
                archive_dir=archive_dir,
                older_than_days=7,
                dry_run=False,
                delete_only=False,
            )
            self.assertEqual(payload["candidates"], 1)
            self.assertEqual(payload["moved"], 1)
            self.assertTrue((archive_dir / "import_error_old.json").exists())
            self.assertTrue(new_file.exists())

    def test_cleanup_reports_delete_only(self):
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "reports"
            report_dir.mkdir(parents=True, exist_ok=True)
            old_file = report_dir / "import_error_old.json"
            self._touch_with_age_days(old_file, 10)

            payload = cleanup_reports(
                report_dir=report_dir,
                archive_dir=None,
                older_than_days=7,
                dry_run=False,
                delete_only=True,
            )
            self.assertEqual(payload["deleted"], 1)
            self.assertFalse(old_file.exists())

    def test_cleanup_reports_dry_run(self):
        with tempfile.TemporaryDirectory() as td:
            report_dir = Path(td) / "reports"
            archive_dir = Path(td) / "archive"
            report_dir.mkdir(parents=True, exist_ok=True)
            old_file = report_dir / "import_error_old.json"
            self._touch_with_age_days(old_file, 10)

            payload = cleanup_reports(
                report_dir=report_dir,
                archive_dir=archive_dir,
                older_than_days=7,
                dry_run=True,
                delete_only=False,
            )
            self.assertEqual(payload["candidates"], 1)
            self.assertEqual(payload["moved"], 0)
            self.assertTrue(old_file.exists())
            self.assertFalse(archive_dir.exists())

    def test_determine_exit_code_non_cron(self):
        payload = {"status": "ok", "candidates": 10, "dry_run": True, "moved": 0, "deleted": 0}
        self.assertEqual(determine_exit_code(payload, cron_exit_codes=False), 0)

    def test_determine_exit_code_cron_dry_run_candidates(self):
        payload = {"status": "ok", "candidates": 2, "dry_run": True, "moved": 0, "deleted": 0}
        self.assertEqual(determine_exit_code(payload, cron_exit_codes=True), 3)

    def test_determine_exit_code_cron_partial(self):
        payload = {"status": "ok", "candidates": 3, "dry_run": False, "moved": 1, "deleted": 1}
        self.assertEqual(determine_exit_code(payload, cron_exit_codes=True), 4)

    def test_determine_exit_code_cron_ok(self):
        payload = {"status": "ok", "candidates": 3, "dry_run": False, "moved": 2, "deleted": 1}
        self.assertEqual(determine_exit_code(payload, cron_exit_codes=True), 0)

    def test_output_payload_summary_only(self):
        payload = {
            "status": "ok",
            "moved": 1,
            "deleted": 0,
            "moved_paths": ["/tmp/a.json"],
            "deleted_paths": [],
        }
        summary = output_payload(payload, summary_only=True)
        self.assertEqual(summary["status"], "ok")
        self.assertNotIn("moved_paths", summary)
        self.assertNotIn("deleted_paths", summary)

    def test_output_payload_full(self):
        payload = {
            "status": "ok",
            "moved": 1,
            "deleted": 0,
            "moved_paths": ["/tmp/a.json"],
            "deleted_paths": [],
        }
        full = output_payload(payload, summary_only=False)
        self.assertIn("moved_paths", full)
        self.assertIn("deleted_paths", full)

    def test_build_markdown_report(self):
        payload = {
            "status": "ok",
            "report_dir": "logs/import_errors",
            "archive_dir": "logs/import_errors_archive",
            "older_than_days": 7,
            "dry_run": False,
            "delete_only": False,
            "candidates": 3,
            "moved": 2,
            "deleted": 1,
            "moved_paths": ["/tmp/a.json"],
            "deleted_paths": ["/tmp/b.json"],
        }
        text = build_markdown_report(payload)
        self.assertIn("# Import Error Report Cleanup", text)
        self.assertIn("| candidates | 3 |", text)
        self.assertIn("## Moved Paths", text)
        self.assertIn("## Deleted Paths", text)
        self.assertIn("| moved_paths_truncated_count | 0 |", text)
        self.assertIn("| deleted_paths_truncated_count | 0 |", text)

    def test_build_markdown_report_with_truncated_counts(self):
        payload = {
            "status": "ok",
            "report_dir": "logs/import_errors",
            "archive_dir": "logs/import_errors_archive",
            "older_than_days": 7,
            "dry_run": False,
            "delete_only": False,
            "candidates": 100,
            "moved": 100,
            "deleted": 0,
            "moved_paths": [f"/tmp/m_{i}.json" for i in range(35)],
            "deleted_paths": [],
        }
        text = build_markdown_report(payload, detail_limit=30)
        self.assertIn("| moved_paths_truncated_count | 5 |", text)
        self.assertIn("- ... and 5 more", text)

    def test_build_markdown_report_with_custom_detail_limit(self):
        payload = {
            "status": "ok",
            "report_dir": "logs/import_errors",
            "archive_dir": "logs/import_errors_archive",
            "older_than_days": 7,
            "dry_run": False,
            "delete_only": False,
            "candidates": 3,
            "moved": 3,
            "deleted": 0,
            "moved_paths": ["/tmp/m1.json", "/tmp/m2.json", "/tmp/m3.json"],
            "deleted_paths": [],
        }
        text = build_markdown_report(payload, detail_limit=1)
        self.assertIn("| moved_paths_truncated_count | 2 |", text)
        self.assertIn("- `/tmp/m1.json`", text)
        self.assertNotIn("- `/tmp/m2.json`", text)

    def test_truncate_paths(self):
        shown, truncated = truncate_paths([str(i) for i in range(10)], detail_limit=3)
        self.assertEqual(len(shown), 3)
        self.assertEqual(truncated, 7)

    def test_write_markdown_report(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "report.md"
            write_markdown_report(path, "# report\n")
            self.assertTrue(path.exists())
            self.assertEqual(path.read_text(encoding="utf-8"), "# report\n")

    def test_write_csv_summary(self):
        payload = {
            "status": "ok",
            "report_dir": "logs/import_errors",
            "archive_dir": "logs/import_errors_archive",
            "older_than_days": 7,
            "dry_run": False,
            "delete_only": False,
            "candidates": 10,
            "moved": 8,
            "deleted": 2,
        }
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "summary.csv"
            write_csv_summary(path, payload)
            self.assertTrue(path.exists())
            text = path.read_text(encoding="utf-8")
            self.assertIn("status,report_dir,archive_dir,older_than_days,dry_run,delete_only,candidates,moved,deleted", text)
            self.assertIn("ok,logs/import_errors,logs/import_errors_archive,7,False,False,10,8,2", text)


if __name__ == "__main__":
    unittest.main()
