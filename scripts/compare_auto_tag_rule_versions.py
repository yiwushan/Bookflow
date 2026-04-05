#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import psycopg

try:
    from auto_tag_chunks import load_rules_bundle, score_text
except ModuleNotFoundError:  # pragma: no cover
    from scripts.auto_tag_chunks import load_rules_bundle, score_text


JSONL_SCHEMA_VERSION = "compare_auto_tag_rule_versions.jsonl.v1"
CSV_SCHEMA_VERSION = "compare_auto_tag_rule_versions.csv.v1"
MARKDOWN_SCHEMA_VERSION = "compare_auto_tag_rule_versions.markdown.v1"


def compute_rule_hits(chunks: list[tuple[str, str]], rules: dict[str, dict[str, Any]]) -> dict[str, Any]:
    total = len(chunks)
    hit_chunks = 0
    per_rule_counter: Counter[str] = Counter()

    for _, text_content in chunks:
        text = text_content or ""
        hit_rules: list[str] = []
        for tag_name, cfg in rules.items():
            if score_text(text, cfg["keywords"]) > 0:
                hit_rules.append(tag_name)
        if hit_rules:
            hit_chunks += 1
            for name in set(hit_rules):
                per_rule_counter[name] += 1

    return {
        "chunks_scanned": total,
        "rule_hit_chunks": hit_chunks,
        "rule_hit_rate": round((hit_chunks / total), 4) if total > 0 else 0.0,
        "per_rule_counter": per_rule_counter,
    }


def build_rule_deltas(base_counter: Counter[str], target_counter: Counter[str], top: int = 20) -> list[dict[str, Any]]:
    names = set(base_counter.keys()) | set(target_counter.keys())
    rows: list[dict[str, Any]] = []
    for name in names:
        base = int(base_counter.get(name, 0))
        target = int(target_counter.get(name, 0))
        rows.append(
            {
                "rule": name,
                "base_chunks": base,
                "target_chunks": target,
                "delta_chunks": target - base,
            }
        )
    rows.sort(key=lambda x: (abs(int(x["delta_chunks"])), int(x["target_chunks"])), reverse=True)
    return rows[:top]


def write_csv_report(path: Path, summary: dict[str, Any], rule_deltas: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "row_type",
                "rule_rank",
                "rule",
                "base_chunks",
                "target_chunks",
                "delta_chunks",
                "metric",
                "value",
                "schema_version",
                "jsonl_schema_version",
                "markdown_schema_version",
            ]
        )
        for metric, value in summary.items():
            writer.writerow(
                [
                    "summary",
                    "",
                    "",
                    "",
                    "",
                    "",
                    metric,
                    value,
                    CSV_SCHEMA_VERSION,
                    JSONL_SCHEMA_VERSION,
                    MARKDOWN_SCHEMA_VERSION,
                ]
            )
        for rank, row in enumerate(rule_deltas, start=1):
            writer.writerow(
                [
                    "rule_delta",
                    rank,
                    row.get("rule", ""),
                    row.get("base_chunks", 0),
                    row.get("target_chunks", 0),
                    row.get("delta_chunks", 0),
                    "",
                    "",
                    CSV_SCHEMA_VERSION,
                    "",
                    "",
                ]
            )


def build_markdown_report(
    *,
    book_id_filter: str | None,
    limit: int,
    top: int,
    rules_path: str,
    base_version: str,
    target_version: str,
    summary: dict[str, Any],
    rule_deltas: list[dict[str, Any]],
    schema_version_consistency_note: str = f"csv={CSV_SCHEMA_VERSION};jsonl={JSONL_SCHEMA_VERSION}",
) -> str:
    lines = [
        "# Auto-Tag Rule Version Compare",
        "",
        f"- book_id_filter: `{book_id_filter}`",
        f"- limit: `{limit}`",
        f"- top: `{top}`",
        f"- rules_path: `{rules_path}`",
        f"- base_version: `{base_version}`",
        f"- target_version: `{target_version}`",
        f"- csv_schema_version: `{CSV_SCHEMA_VERSION}`",
        f"- jsonl_schema_version: `{JSONL_SCHEMA_VERSION}`",
        f"- markdown_schema_version: `{MARKDOWN_SCHEMA_VERSION}`",
        f"- schema_version_consistency_note: `{schema_version_consistency_note}`",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    for metric, value in summary.items():
        lines.append(f"| {metric} | {value} |")

    lines.extend(["", "## Rule Deltas", "", "| Rule | Base Chunks | Target Chunks | Delta |", "| --- | --- | --- | --- |"])
    for row in rule_deltas:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("rule", "")),
                    str(int(row.get("base_chunks", 0))),
                    str(int(row.get("target_chunks", 0))),
                    str(int(row.get("delta_chunks", 0))),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Export Schemas",
            "",
            "### CSV (`--csv-output`)",
            "",
            f"- schema_version: `{CSV_SCHEMA_VERSION}`",
            "- `summary` 行：`row_type,rule_rank,rule,base_chunks,target_chunks,delta_chunks,metric,value,schema_version,jsonl_schema_version,markdown_schema_version`（仅 `metric/value` 有值）。",
            "- `rule_delta` 行：`row_type,rule_rank,rule,base_chunks,target_chunks,delta_chunks,metric,value,schema_version,jsonl_schema_version,markdown_schema_version`（`rule_rank` 从 1 开始）。",
            "",
            "### JSONL (`--jsonl-output`)",
            "",
            f"- schema_version: `{JSONL_SCHEMA_VERSION}`",
            "- `summary` 行字段：`row_type,schema_version,csv_schema_version,markdown_schema_version,book_id_filter,limit,base_version,target_version,summary`。",
            "- `rule_delta` 行字段：`row_type,schema_version,csv_schema_version,markdown_schema_version,rule_rank,book_id_filter,limit,base_version,target_version,rule,base_chunks,target_chunks,delta_chunks`。",
            "",
        ]
    )
    return "\n".join(lines)


def write_markdown_report(path: Path, markdown_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_text, encoding="utf-8")


def write_jsonl_report(
    path: Path,
    *,
    book_id_filter: str | None,
    limit: int,
    base_version: str,
    target_version: str,
    summary: dict[str, Any],
    rule_deltas: list[dict[str, Any]],
    schema_version: str = JSONL_SCHEMA_VERSION,
    csv_schema_version: str = CSV_SCHEMA_VERSION,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "row_type": "summary",
                    "schema_version": schema_version,
                    "book_id_filter": book_id_filter,
                    "limit": limit,
                    "base_version": base_version,
                    "target_version": target_version,
                    "csv_schema_version": csv_schema_version,
                    "markdown_schema_version": MARKDOWN_SCHEMA_VERSION,
                    "summary": summary,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        for rank, row in enumerate(rule_deltas, start=1):
            f.write(
                json.dumps(
                    {
                        "row_type": "rule_delta",
                        "schema_version": schema_version,
                        "csv_schema_version": csv_schema_version,
                        "markdown_schema_version": MARKDOWN_SCHEMA_VERSION,
                        "rule_rank": rank,
                        "book_id_filter": book_id_filter,
                        "limit": limit,
                        "base_version": base_version,
                        "target_version": target_version,
                        "rule": row.get("rule"),
                        "base_chunks": int(row.get("base_chunks", 0)),
                        "target_chunks": int(row.get("target_chunks", 0)),
                        "delta_chunks": int(row.get("delta_chunks", 0)),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare auto-tag rule hit metrics between two versions")
    parser.add_argument("--book-id", default=None, help="Optional book UUID filter")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--rules", default="config/auto_tag_rules.json", help="Rule config path")
    parser.add_argument("--base-version", required=True, help="Base rule version key (e.g. v0)")
    parser.add_argument("--target-version", required=True, help="Target rule version key (e.g. v1)")
    parser.add_argument("--top", type=int, default=20, help="Top changed rules to show")
    parser.add_argument("--csv-output", default=None, help="Optional CSV output path")
    parser.add_argument("--markdown-output", default=None, help="Optional Markdown report output path")
    parser.add_argument("--jsonl-output", default=None, help="Optional JSONL detail output path")
    args = parser.parse_args()

    if args.limit <= 0:
        print("--limit must be > 0", file=sys.stderr)
        return 1
    if args.top <= 0:
        print("--top must be > 0", file=sys.stderr)
        return 1

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is required", file=sys.stderr)
        return 1

    book_id = None
    if args.book_id:
        try:
            book_id = str(uuid.UUID(args.book_id))
        except Exception:
            print("invalid --book-id", file=sys.stderr)
            return 1

    rules_path = Path(args.rules)
    base_bundle = load_rules_bundle(rules_path, rule_version=args.base_version)
    target_bundle = load_rules_bundle(rules_path, rule_version=args.target_version)
    base_rules = base_bundle["rules"]
    target_rules = target_bundle["rules"]

    where_sql = "TRUE"
    params: list[object] = [args.limit]
    if book_id is not None:
        where_sql = "book_id = %s"
        params = [book_id, args.limit]

    sql = f"""
    SELECT id::text, text_content
    FROM book_chunks
    WHERE {where_sql}
    ORDER BY created_at DESC
    LIMIT %s
    """
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            chunks = cur.fetchall()

    base_metrics = compute_rule_hits(chunks, base_rules)
    target_metrics = compute_rule_hits(chunks, target_rules)
    deltas = build_rule_deltas(
        base_counter=base_metrics["per_rule_counter"],
        target_counter=target_metrics["per_rule_counter"],
        top=args.top,
    )

    summary = {
        "chunks_scanned": int(target_metrics["chunks_scanned"]),
        "base_rule_hit_chunks": int(base_metrics["rule_hit_chunks"]),
        "target_rule_hit_chunks": int(target_metrics["rule_hit_chunks"]),
        "delta_rule_hit_chunks": int(target_metrics["rule_hit_chunks"]) - int(base_metrics["rule_hit_chunks"]),
        "base_rule_hit_rate": float(base_metrics["rule_hit_rate"]),
        "target_rule_hit_rate": float(target_metrics["rule_hit_rate"]),
        "delta_rule_hit_rate": round(
            float(target_metrics["rule_hit_rate"]) - float(base_metrics["rule_hit_rate"]),
            4,
        ),
    }
    if args.csv_output:
        write_csv_report(Path(args.csv_output), summary=summary, rule_deltas=deltas)
    schema_version_consistency_note = (
        f"csv={CSV_SCHEMA_VERSION};jsonl={JSONL_SCHEMA_VERSION}" if (args.csv_output or args.jsonl_output) else "no_export"
    )
    if args.markdown_output:
        markdown = build_markdown_report(
            book_id_filter=book_id,
            limit=args.limit,
            top=args.top,
            rules_path=str(rules_path),
            base_version=str(base_bundle["selected_rule_version"]),
            target_version=str(target_bundle["selected_rule_version"]),
            summary=summary,
            rule_deltas=deltas,
            schema_version_consistency_note=schema_version_consistency_note,
        )
        write_markdown_report(Path(args.markdown_output), markdown)
    if args.jsonl_output:
        write_jsonl_report(
            Path(args.jsonl_output),
            book_id_filter=book_id,
            limit=args.limit,
            base_version=str(base_bundle["selected_rule_version"]),
            target_version=str(target_bundle["selected_rule_version"]),
            summary=summary,
            rule_deltas=deltas,
            schema_version=JSONL_SCHEMA_VERSION,
            csv_schema_version=CSV_SCHEMA_VERSION,
        )

    payload = {
        "status": "ok",
        "book_id_filter": book_id,
        "limit": args.limit,
        "rules_path": str(rules_path),
        "base_version": base_bundle["selected_rule_version"],
        "target_version": target_bundle["selected_rule_version"],
        "summary": summary,
        "rule_deltas": deltas,
        "csv_output": args.csv_output,
        "csv_schema_version": CSV_SCHEMA_VERSION if args.csv_output else None,
        "markdown_output": args.markdown_output,
        "markdown_schema_version": MARKDOWN_SCHEMA_VERSION if args.markdown_output else None,
        "jsonl_output": args.jsonl_output,
        "jsonl_schema_version": JSONL_SCHEMA_VERSION if args.jsonl_output else None,
        "schema_version_consistency_note": schema_version_consistency_note,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
