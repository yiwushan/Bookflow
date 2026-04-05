#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


JSONL_SCHEMA_VERSION = "replay_memory_feed.jsonl.v1"
CSV_SCHEMA_VERSION = "replay_memory_feed.csv.v1"
MARKDOWN_SCHEMA_VERSION = "replay_memory_feed.markdown.v1"
MARKDOWN_SCHEMA_VERSION_SOURCE = "constant"


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def request_json(method: str, url: str, token: str | None = None) -> tuple[int, dict[str, Any]]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, method=method, headers=headers)
    try:
        with urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def wait_ready(base_url: str, timeout_sec: int = 12) -> dict[str, Any]:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            status, payload = request_json("GET", f"{base_url}/health")
            if status == 200 and payload.get("status") == "ok":
                return payload
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError("server not ready")


def parse_scenarios(raw: str) -> list[tuple[str, int | None]]:
    out: list[tuple[str, int | None]] = []
    seen: set[str] = set()
    for token in [x.strip() for x in raw.split(",") if x.strip()]:
        lowered = token.lower()
        if lowered in {"top", "none"}:
            key = "top"
            if key not in seen:
                out.append((key, None))
                seen.add(key)
            continue
        try:
            n = int(token)
        except Exception as exc:
            raise ValueError(f"invalid scenario token: {token}") from exc
        if n <= 0 or n > 50:
            raise ValueError(f"memory_every out of range (1..50): {n}")
        key = str(n)
        if key not in seen:
            out.append((key, n))
            seen.add(key)
    if not out:
        raise ValueError("no scenarios provided")
    return out


def summarize_items(items: list[dict[str, Any]]) -> tuple[list[int], list[dict[str, Any]]]:
    memory_positions: list[int] = []
    timeline: list[dict[str, Any]] = []
    for idx, item in enumerate(items, start=1):
        item_type = str(item.get("item_type", "chunk"))
        if item_type == "memory_post":
            memory_positions.append(idx)
        teaser = str(item.get("teaser_text", "") or "")
        timeline.append(
            {
                "slot": idx,
                "item_type": item_type,
                "memory_type": item.get("memory_type") if item_type == "memory_post" else None,
                "book_title": item.get("book_title"),
                "title": item.get("title"),
                "teaser_preview": teaser[:48],
            }
        )
    return memory_positions, timeline


def summarize_memory_types(timeline: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for item in timeline:
        if str(item.get("item_type")) != "memory_post":
            continue
        memory_type = str(item.get("memory_type") or "unknown")
        counter[memory_type] += 1
    return dict(counter)


def format_memory_type_distribution(stats: dict[str, int] | None) -> str:
    if not stats:
        return "(none)"
    parts = [f"{name}:{int(count)}" for name, count in sorted(stats.items(), key=lambda kv: kv[0])]
    return ", ".join(parts)


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "scenario",
        "memory_every",
        "memory_inserted",
        "memory_positions",
        "first_item_type",
        "items_count",
        "trace_id",
        "user_id",
        "limit",
        "memory_type_distribution",
        "jsonl_schema_version",
        "markdown_schema_version",
        "markdown_schema_version_source",
        "schema_version",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(record)


def _md_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\n", " ").replace("|", "\\|")
    return text.strip()


def build_markdown_report(
    scenarios: list[dict[str, Any]],
    *,
    backend: str,
    user_id: str,
    limit: int,
    schema_version_consistency_note: str = f"csv={CSV_SCHEMA_VERSION};jsonl={JSONL_SCHEMA_VERSION}",
) -> str:
    lines = [
        "# Memory Feed Replay Report",
        "",
        f"- backend: `{backend}`",
        f"- user_id: `{user_id}`",
        f"- limit: `{limit}`",
        f"- csv_schema_version: `{CSV_SCHEMA_VERSION}`",
        f"- jsonl_schema_version: `{JSONL_SCHEMA_VERSION}`",
        f"- markdown_schema_version: `{MARKDOWN_SCHEMA_VERSION}`",
        f"- schema_version_consistency_note: `{schema_version_consistency_note}`",
        "",
        "## Overview",
        "",
        "| Scenario | Memory Inserted | Memory Positions | Memory Types | First Item Type | Items Count | Trace ID | Markdown Schema |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in scenarios:
        positions = row.get("memory_positions") or []
        positions_text = ", ".join(str(x) for x in positions) if positions else "(none)"
        memory_type_distribution = row.get("memory_type_distribution")
        if memory_type_distribution is None:
            timeline = row.get("timeline") or []
            memory_type_distribution = summarize_memory_types(timeline if isinstance(timeline, list) else [])
        first_item_type = row.get("first_item_type")
        if first_item_type is None:
            timeline = row.get("timeline") or []
            first_item_type = (timeline[0].get("item_type") if timeline else None) if isinstance(timeline, list) else None
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(row.get("scenario")),
                    _md_cell(int(row.get("memory_inserted", 0))),
                    _md_cell(positions_text),
                    _md_cell(format_memory_type_distribution(memory_type_distribution)),
                    _md_cell(first_item_type),
                    _md_cell(int(row.get("items_count", 0))),
                    _md_cell(row.get("trace_id")),
                    _md_cell(row.get("markdown_schema_version") or MARKDOWN_SCHEMA_VERSION),
                ]
            )
            + " |"
        )
    lines.append("")

    for row in scenarios:
        scenario = str(row.get("scenario", "unknown"))
        memory_every = row.get("memory_every")
        positions = row.get("memory_positions") or []
        positions_text = ", ".join(str(x) for x in positions) if positions else "(none)"
        memory_type_distribution = row.get("memory_type_distribution")
        if memory_type_distribution is None:
            timeline = row.get("timeline") or []
            memory_type_distribution = summarize_memory_types(timeline if isinstance(timeline, list) else [])
        first_item_type = row.get("first_item_type")
        if first_item_type is None:
            timeline = row.get("timeline") or []
            first_item_type = (timeline[0].get("item_type") if timeline else None) if isinstance(timeline, list) else None
        lines.extend(
            [
                f"## Scenario `{scenario}`",
                "",
                f"- memory_every: `{memory_every if memory_every is not None else 'n/a'}`",
                f"- memory_inserted: `{int(row.get('memory_inserted', 0))}`",
                f"- memory_positions: `{positions_text}`",
                f"- memory_type_distribution: `{format_memory_type_distribution(memory_type_distribution)}`",
                f"- first_item_type: `{first_item_type}`",
                f"- trace_id: `{row.get('trace_id')}`",
                "",
                "| Slot | Type | Book | Title | Teaser |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for item in row.get("timeline", []):
            lines.append(
                "| "
                + " | ".join(
                    [
                        _md_cell(item.get("slot")),
                        _md_cell(item.get("item_type")),
                        _md_cell(item.get("book_title")),
                        _md_cell(item.get("title")),
                        _md_cell(item.get("teaser_preview")),
                    ]
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines)


def write_markdown_report(path: Path, markdown_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay memory-post insertion on feed")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--user-id", default="11111111-1111-1111-1111-111111111111")
    parser.add_argument("--token", default="local-dev-token")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--scenarios", default="top,1,3", help="comma list: top|none|<memory_every>")
    parser.add_argument("--jsonl-output", default=None, help="Optional JSONL output path for scenario rows")
    parser.add_argument("--csv-output", default=None, help="Optional CSV output path for scenario summary")
    parser.add_argument("--markdown-output", default=None, help="Optional Markdown report output path")
    args = parser.parse_args()

    dsn = args.database_url or os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required (or pass --database-url)")
    if args.limit <= 0 or args.limit > 50:
        raise SystemExit("--limit must be in 1..50")
    scenarios = parse_scenarios(args.scenarios)

    repo_root = Path(__file__).resolve().parents[1]
    port = args.port or get_free_port()
    base_url = f"http://{args.host}:{port}"

    env = os.environ.copy()
    env["DATABASE_URL"] = dsn
    env["BOOKFLOW_TOKEN"] = args.token

    proc = subprocess.Popen(
        ["python3", "server/app.py", "--host", args.host, "--port", str(port)],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        health = wait_ready(base_url)
        if health.get("backend") != "postgres":
            raise RuntimeError("backend is not postgres")

        outputs: list[dict[str, Any]] = []
        max_memory_inserted = 0
        for scenario_name, memory_every in scenarios:
            query = f"limit={args.limit}&mode=default&user_id={args.user_id}&with_memory=1"
            if memory_every is not None:
                query += f"&memory_position=interval&memory_every={memory_every}"
            else:
                query += "&memory_position=top"
            status, payload = request_json(
                "GET",
                f"{base_url}/v1/feed?{query}",
                token=args.token,
            )
            if status != 200:
                raise RuntimeError(f"feed failed for scenario={scenario_name}: {status} {payload}")
            items = payload.get("items", [])
            memory_inserted = int(payload.get("memory_inserted", 0))
            max_memory_inserted = max(max_memory_inserted, memory_inserted)
            memory_positions, timeline = summarize_items(items)
            memory_type_distribution = summarize_memory_types(timeline)
            first_item_type = timeline[0].get("item_type") if timeline else None
            outputs.append(
                {
                    "scenario": scenario_name,
                    "memory_every": memory_every,
                    "memory_inserted": memory_inserted,
                    "memory_positions": memory_positions,
                    "memory_type_distribution": memory_type_distribution,
                    "first_item_type": first_item_type,
                    "items_count": len(items),
                    "trace_id": payload.get("trace_id"),
                    "timeline": timeline,
                }
            )

        if max_memory_inserted <= 0:
            raise RuntimeError("no memory posts inserted across scenarios")

        if args.jsonl_output:
            jsonl_rows: list[dict[str, Any]] = []
            for row in outputs:
                item = dict(row)
                item["schema_version"] = JSONL_SCHEMA_VERSION
                item["markdown_schema_version"] = MARKDOWN_SCHEMA_VERSION
                item["user_id"] = args.user_id
                item["limit"] = args.limit
                item["memory_positions"] = ",".join(str(x) for x in item.get("memory_positions", []))
                jsonl_rows.append(item)
            write_jsonl(Path(args.jsonl_output), jsonl_rows)
        if args.csv_output:
            csv_rows: list[dict[str, Any]] = []
            for row in outputs:
                item = dict(row)
                item.pop("timeline", None)
                item["user_id"] = args.user_id
                item["limit"] = args.limit
                item["memory_positions"] = ",".join(str(x) for x in item.get("memory_positions", []))
                memory_type_distribution = item.get("memory_type_distribution")
                if isinstance(memory_type_distribution, dict):
                    item["memory_type_distribution"] = format_memory_type_distribution(memory_type_distribution)
                elif memory_type_distribution is None:
                    item["memory_type_distribution"] = "(none)"
                else:
                    item["memory_type_distribution"] = str(memory_type_distribution)
                item["jsonl_schema_version"] = JSONL_SCHEMA_VERSION
                item["markdown_schema_version"] = MARKDOWN_SCHEMA_VERSION
                item["markdown_schema_version_source"] = MARKDOWN_SCHEMA_VERSION_SOURCE
                item["schema_version"] = CSV_SCHEMA_VERSION
                csv_rows.append(item)
            write_csv(Path(args.csv_output), csv_rows)
        schema_version_consistency_note = (
            f"csv={CSV_SCHEMA_VERSION};jsonl={JSONL_SCHEMA_VERSION}" if (args.csv_output or args.jsonl_output) else "no_export"
        )

        if args.markdown_output:
            markdown = build_markdown_report(
                outputs,
                backend=str(health.get("backend")),
                user_id=args.user_id,
                limit=args.limit,
                schema_version_consistency_note=schema_version_consistency_note,
            )
            write_markdown_report(Path(args.markdown_output), markdown)

        print(
            json.dumps(
                {
                    "status": "ok",
                    "backend": health.get("backend"),
                    "user_id": args.user_id,
                    "limit": args.limit,
                    "scenarios": outputs,
                    "jsonl_output": args.jsonl_output,
                    "jsonl_schema_version": JSONL_SCHEMA_VERSION if args.jsonl_output else None,
                    "csv_output": args.csv_output,
                    "csv_schema_version": CSV_SCHEMA_VERSION if args.csv_output else None,
                    "schema_version_consistency_note": schema_version_consistency_note,
                    "markdown_output": args.markdown_output,
                    "markdown_schema_version": MARKDOWN_SCHEMA_VERSION if args.markdown_output else None,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
