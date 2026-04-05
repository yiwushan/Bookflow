#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path


def collect_expired_reports(report_dir: Path, older_than_days: int) -> list[Path]:
    if older_than_days < 0:
        raise ValueError("older_than_days must be >= 0")
    if not report_dir.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    out: list[Path] = []
    for path in sorted(report_dir.glob("import_error_*.json")):
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        if mtime <= cutoff:
            out.append(path)
    return out


def cleanup_reports(
    report_dir: Path,
    archive_dir: Path | None,
    older_than_days: int,
    dry_run: bool,
    delete_only: bool,
) -> dict[str, object]:
    candidates = collect_expired_reports(report_dir=report_dir, older_than_days=older_than_days)
    moved: list[str] = []
    deleted: list[str] = []

    if not dry_run:
        if not delete_only and archive_dir is not None:
            archive_dir.mkdir(parents=True, exist_ok=True)

    for src in candidates:
        if dry_run:
            continue
        if delete_only:
            src.unlink(missing_ok=True)
            deleted.append(str(src))
            continue
        if archive_dir is None:
            src.unlink(missing_ok=True)
            deleted.append(str(src))
            continue
        dst = archive_dir / src.name
        if dst.exists():
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            dst = archive_dir / f"{src.stem}_{ts}{src.suffix}"
        shutil.move(str(src), str(dst))
        moved.append(str(dst))

    return {
        "status": "ok",
        "report_dir": str(report_dir),
        "archive_dir": str(archive_dir) if archive_dir is not None else None,
        "older_than_days": older_than_days,
        "dry_run": dry_run,
        "delete_only": delete_only,
        "candidates": len(candidates),
        "moved": len(moved),
        "deleted": len(deleted),
        "moved_paths": moved,
        "deleted_paths": deleted,
    }


def determine_exit_code(payload: dict[str, object], cron_exit_codes: bool) -> int:
    if not cron_exit_codes:
        return 0
    if str(payload.get("status")) != "ok":
        return 2
    candidates = int(payload.get("candidates", 0) or 0)
    moved = int(payload.get("moved", 0) or 0)
    deleted = int(payload.get("deleted", 0) or 0)
    dry_run = bool(payload.get("dry_run", False))

    # cron mode:
    # 0: 成功且无需告警
    # 3: dry-run 发现待清理文件（可作为告警信号）
    # 4: 非 dry-run 但存在未处理完的候选（异常情况）
    if dry_run and candidates > 0:
        return 3
    if (not dry_run) and candidates > (moved + deleted):
        return 4
    return 0


def output_payload(payload: dict[str, object], summary_only: bool) -> dict[str, object]:
    if not summary_only:
        return payload
    copied = dict(payload)
    copied.pop("moved_paths", None)
    copied.pop("deleted_paths", None)
    return copied


def truncate_paths(paths: list[str], detail_limit: int = 30) -> tuple[list[str], int]:
    safe_limit = max(0, int(detail_limit))
    shown = paths[:safe_limit]
    truncated = max(0, len(paths) - len(shown))
    return shown, truncated


def build_markdown_report(payload: dict[str, object], detail_limit: int = 30) -> str:
    status = str(payload.get("status", "unknown"))
    moved_paths = [str(x) for x in payload.get("moved_paths", [])]
    deleted_paths = [str(x) for x in payload.get("deleted_paths", [])]
    moved_shown, moved_truncated = truncate_paths(moved_paths, detail_limit=detail_limit)
    deleted_shown, deleted_truncated = truncate_paths(deleted_paths, detail_limit=detail_limit)
    lines = [
        "# Import Error Report Cleanup",
        "",
        f"- status: `{status}`",
        f"- report_dir: `{payload.get('report_dir')}`",
        f"- archive_dir: `{payload.get('archive_dir')}`",
        f"- older_than_days: `{payload.get('older_than_days')}`",
        f"- dry_run: `{payload.get('dry_run')}`",
        f"- delete_only: `{payload.get('delete_only')}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| candidates | {int(payload.get('candidates', 0) or 0)} |",
        f"| moved | {int(payload.get('moved', 0) or 0)} |",
        f"| deleted | {int(payload.get('deleted', 0) or 0)} |",
        f"| moved_paths_truncated_count | {moved_truncated} |",
        f"| deleted_paths_truncated_count | {deleted_truncated} |",
        "",
    ]
    if moved_shown:
        lines.extend(["## Moved Paths", ""])
        for path in moved_shown:
            lines.append(f"- `{path}`")
        if moved_truncated > 0:
            lines.append(f"- ... and {moved_truncated} more")
        lines.append("")
    if deleted_shown:
        lines.extend(["## Deleted Paths", ""])
        for path in deleted_shown:
            lines.append(f"- `{path}`")
        if deleted_truncated > 0:
            lines.append(f"- ... and {deleted_truncated} more")
        lines.append("")
    return "\n".join(lines)


def write_markdown_report(path: Path, markdown_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_text, encoding="utf-8")


def write_csv_summary(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "status",
        "report_dir",
        "archive_dir",
        "older_than_days",
        "dry_run",
        "delete_only",
        "candidates",
        "moved",
        "deleted",
    ]
    row = {key: payload.get(key) for key in fieldnames}
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cleanup/archive import error reports")
    parser.add_argument("--report-dir", default="logs/import_errors")
    parser.add_argument("--archive-dir", default="logs/import_errors_archive")
    parser.add_argument("--older-than-days", type=int, default=7)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delete-only", action="store_true")
    parser.add_argument("--cron-exit-codes", action="store_true")
    parser.add_argument("--summary-only", action="store_true")
    parser.add_argument("--markdown-output", default=None)
    parser.add_argument("--markdown-detail-limit", type=int, default=30)
    parser.add_argument("--csv-output", default=None)
    args = parser.parse_args()

    report_dir = Path(args.report_dir)
    archive_dir = None if args.delete_only else Path(args.archive_dir)
    if args.markdown_detail_limit < 0:
        raise SystemExit("--markdown-detail-limit must be >= 0")
    try:
        payload = cleanup_reports(
            report_dir=report_dir,
            archive_dir=archive_dir,
            older_than_days=args.older_than_days,
            dry_run=bool(args.dry_run),
            delete_only=bool(args.delete_only),
        )
        if args.markdown_output:
            write_markdown_report(
                Path(args.markdown_output),
                build_markdown_report(payload, detail_limit=int(args.markdown_detail_limit)),
            )
            payload = dict(payload)
            payload["markdown_output"] = str(args.markdown_output)
            payload["markdown_detail_limit"] = int(args.markdown_detail_limit)
        if args.csv_output:
            write_csv_summary(Path(args.csv_output), payload)
            payload = dict(payload)
            payload["csv_output"] = str(args.csv_output)
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": str(exc),
                    "report_dir": str(report_dir),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2 if bool(args.cron_exit_codes) else 1
    print(json.dumps(output_payload(payload, summary_only=bool(args.summary_only)), ensure_ascii=False, indent=2))
    return determine_exit_code(payload, cron_exit_codes=bool(args.cron_exit_codes))


if __name__ == "__main__":
    raise SystemExit(main())
