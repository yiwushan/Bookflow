#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def set_active_rule_version(
    config_path: Path,
    to_version: str,
    dry_run: bool = False,
    backup_dir: Path | None = None,
) -> dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(f"config not found: {config_path}")

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("config must be a JSON object")

    versions = raw.get("rule_versions")
    if not isinstance(versions, dict) or not versions:
        raise ValueError("config.rule_versions is required for version rollback")

    available_versions = sorted(str(v) for v in versions.keys())
    if to_version not in versions:
        raise ValueError(f"target version not found: {to_version}")

    prev_version = str(raw.get("active_rule_version", "")).strip() or None
    backup_path: str | None = None

    if not dry_run:
        if backup_dir is not None:
            backup_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            backup = backup_dir / f"{config_path.stem}_{ts}{config_path.suffix}"
            shutil.copy2(config_path, backup)
            backup_path = str(backup)
        raw["active_rule_version"] = to_version
        config_path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return {
        "status": "ok",
        "config_path": str(config_path),
        "dry_run": dry_run,
        "previous_active_rule_version": prev_version,
        "next_active_rule_version": to_version,
        "available_rule_versions": available_versions,
        "backup_path": backup_path,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Set active auto-tag rule version (rollback helper)")
    parser.add_argument("--config", default="config/auto_tag_rules.json")
    parser.add_argument("--to-version", required=True, help="Target rule version key")
    parser.add_argument("--backup-dir", default="logs/config_backups")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    try:
        payload = set_active_rule_version(
            config_path=Path(args.config),
            to_version=str(args.to_version),
            dry_run=bool(args.dry_run),
            backup_dir=Path(args.backup_dir),
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "message": str(exc)}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
