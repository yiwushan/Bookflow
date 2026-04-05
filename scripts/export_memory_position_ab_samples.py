#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import socket
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


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


def parse_bool_like(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    raise ValueError(f"invalid bool-like value: {value}")


def default_scenarios(interval_every: int, random_seed: int) -> list[dict[str, Any]]:
    return [
        {
            "arm": "A_top",
            "memory_position": "top",
            "memory_every": None,
            "memory_seed": None,
            "memory_random_never_first": True,
            "query_suffix": "&memory_position=top",
        },
        {
            "arm": "B_interval",
            "memory_position": "interval",
            "memory_every": interval_every,
            "memory_seed": None,
            "memory_random_never_first": True,
            "query_suffix": f"&memory_position=interval&memory_every={interval_every}",
        },
        {
            "arm": "C_random",
            "memory_position": "random",
            "memory_every": interval_every,
            "memory_seed": random_seed,
            "memory_random_never_first": True,
            "query_suffix": (
                f"&memory_position=random&memory_every={interval_every}"
                f"&memory_seed={random_seed}&memory_random_never_first=1"
            ),
        },
    ]


def normalize_scenarios(
    raw_arms: Any,
    *,
    default_interval_every: int,
    default_random_seed: int,
) -> list[dict[str, Any]]:
    if not isinstance(raw_arms, list) or not raw_arms:
        raise ValueError("scenario config must contain non-empty arms list")

    out: list[dict[str, Any]] = []
    seen_arms: set[str] = set()
    for idx, item in enumerate(raw_arms, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"arm[{idx}] must be object")
        arm = str(item.get("arm", f"arm_{idx}")).strip()
        if not arm:
            raise ValueError(f"arm[{idx}] has empty arm name")
        if arm in seen_arms:
            raise ValueError(f"duplicate arm name: {arm}")
        seen_arms.add(arm)

        position = str(item.get("memory_position", "")).strip().lower()
        if position not in {"top", "interval", "random"}:
            raise ValueError(f"arm[{idx}] invalid memory_position: {position}")

        memory_every: int | None = None
        memory_seed: int | None = None
        memory_random_never_first = True

        if position in {"interval", "random"}:
            raw_every = item.get("memory_every", default_interval_every)
            try:
                memory_every = int(raw_every)
            except Exception as exc:
                raise ValueError(f"arm[{idx}] memory_every must be integer") from exc
            if memory_every <= 0 or memory_every > 50:
                raise ValueError(f"arm[{idx}] memory_every must be in 1..50")

        if position == "random":
            raw_seed = item.get("memory_seed", default_random_seed)
            try:
                memory_seed = int(raw_seed)
            except Exception as exc:
                raise ValueError(f"arm[{idx}] memory_seed must be integer") from exc
            memory_random_never_first = parse_bool_like(item.get("memory_random_never_first", True), default=True)

        if position == "top":
            query_suffix = "&memory_position=top"
        elif position == "interval":
            query_suffix = f"&memory_position=interval&memory_every={memory_every}"
        else:
            never_first = "1" if memory_random_never_first else "0"
            query_suffix = (
                f"&memory_position=random&memory_every={memory_every}"
                f"&memory_seed={memory_seed}&memory_random_never_first={never_first}"
            )

        out.append(
            {
                "arm": arm,
                "memory_position": position,
                "memory_every": memory_every,
                "memory_seed": memory_seed,
                "memory_random_never_first": memory_random_never_first,
                "query_suffix": query_suffix,
            }
        )
    return out


def load_scenarios_from_config(
    path: Path,
    *,
    default_interval_every: int,
    default_random_seed: int,
) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    payload: Any
    try:
        payload = json.loads(text)
    except Exception:
        try:
            import yaml  # type: ignore
        except Exception as exc:
            raise ValueError("YAML scenario config requires PyYAML (or provide JSON)") from exc
        payload = yaml.safe_load(text)
    if isinstance(payload, dict):
        raw_arms = payload.get("arms")
    else:
        raw_arms = payload
    return normalize_scenarios(
        raw_arms,
        default_interval_every=default_interval_every,
        default_random_seed=default_random_seed,
    )


def summarize_items(items: list[dict[str, Any]]) -> tuple[list[int], list[dict[str, Any]]]:
    positions: list[int] = []
    timeline: list[dict[str, Any]] = []
    for idx, item in enumerate(items, start=1):
        item_type = str(item.get("item_type", "chunk"))
        if item_type == "memory_post":
            positions.append(idx)
        teaser = str(item.get("teaser_text", "") or "")
        timeline.append(
            {
                "slot": idx,
                "item_type": item_type,
                "book_id": item.get("book_id"),
                "chunk_id": item.get("chunk_id"),
                "book_title": item.get("book_title"),
                "title": item.get("title"),
                "teaser_preview": teaser[:64],
            }
        )
    return positions, timeline


def build_sample_rows(arms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for arm in arms:
        for item in arm.get("timeline", []):
            rows.append(
                {
                    "arm": arm.get("arm"),
                    "memory_position": arm.get("memory_position"),
                    "memory_every": arm.get("memory_every"),
                    "trace_id": arm.get("trace_id"),
                    "slot": item.get("slot"),
                    "item_type": item.get("item_type"),
                    "book_id": item.get("book_id"),
                    "chunk_id": item.get("chunk_id"),
                    "book_title": item.get("book_title"),
                    "title": item.get("title"),
                    "teaser_preview": item.get("teaser_preview"),
                }
            )
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "arm",
        "memory_position",
        "memory_every",
        "trace_id",
        "slot",
        "item_type",
        "book_id",
        "chunk_id",
        "book_title",
        "title",
        "teaser_preview",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _md_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\n", " ").replace("|", "\\|").strip()


def build_markdown_report(
    *,
    backend: str,
    user_id: str,
    limit: int,
    interval_every: int,
    random_seed: int,
    arms: list[dict[str, Any]],
    scenario_config: str | None = None,
) -> str:
    lines = [
        "# Memory Position A/B Samples",
        "",
        f"- backend: `{backend}`",
        f"- user_id: `{user_id}`",
        f"- limit: `{limit}`",
        f"- interval_every: `{interval_every}`",
        f"- random_seed: `{random_seed}`",
    ]
    if scenario_config:
        lines.append(f"- scenario_config: `{scenario_config}`")
    lines.extend(
        [
            "",
            "## Arms Overview",
            "",
            "| Arm | Strategy | Memory Every | Memory Inserted | Memory Positions | Trace ID |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for arm in arms:
        positions = arm.get("memory_positions") or []
        positions_text = ", ".join(str(x) for x in positions) if positions else "(none)"
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(arm.get("arm")),
                    _md_cell(arm.get("memory_position")),
                    _md_cell(arm.get("memory_every")),
                    _md_cell(int(arm.get("memory_inserted", 0))),
                    _md_cell(positions_text),
                    _md_cell(arm.get("trace_id")),
                ]
            )
            + " |"
        )
    lines.append("")
    for arm in arms:
        lines.extend(
            [
                f"## {arm.get('arm')} (`{arm.get('memory_position')}`)",
                "",
                "| Slot | Type | Book | Title | Teaser |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for item in arm.get("timeline", []):
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


def write_markdown(path: Path, markdown_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Export A/B samples for memory_position strategies")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--user-id", default="11111111-1111-1111-1111-111111111111")
    parser.add_argument("--token", default="local-dev-token")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--interval-every", type=int, default=3)
    parser.add_argument("--random-seed", type=int, default=7)
    parser.add_argument("--scenario-config", default=None, help="Optional JSON/YAML file for custom A/B arms")
    parser.add_argument("--jsonl-output", default=None, help="Optional JSONL output for flattened sample rows")
    parser.add_argument("--csv-output", default=None, help="Optional CSV output for flattened sample rows")
    parser.add_argument("--markdown-output", default=None, help="Optional Markdown report output path")
    args = parser.parse_args()

    dsn = args.database_url or os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required (or pass --database-url)")
    if args.limit <= 0 or args.limit > 50:
        raise SystemExit("--limit must be in 1..50")
    if args.interval_every <= 0 or args.interval_every > 50:
        raise SystemExit("--interval-every must be in 1..50")

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

        if args.scenario_config:
            scenarios = load_scenarios_from_config(
                Path(args.scenario_config),
                default_interval_every=args.interval_every,
                default_random_seed=args.random_seed,
            )
        else:
            scenarios = default_scenarios(args.interval_every, args.random_seed)

        outputs: list[dict[str, Any]] = []
        for scenario in scenarios:
            query = (
                f"limit={args.limit}&mode=default&user_id={args.user_id}&with_memory=1"
                f"{scenario['query_suffix']}"
            )
            status, payload = request_json("GET", f"{base_url}/v1/feed?{query}", token=args.token)
            if status != 200:
                raise RuntimeError(f"feed failed for arm={scenario['arm']}: {status} {payload}")
            items = payload.get("items", [])
            memory_positions, timeline = summarize_items(items)
            outputs.append(
                {
                    "arm": scenario["arm"],
                    "memory_position": scenario["memory_position"],
                    "memory_every": scenario["memory_every"],
                    "memory_seed": scenario.get("memory_seed"),
                    "memory_random_never_first": scenario.get("memory_random_never_first"),
                    "memory_inserted": int(payload.get("memory_inserted", 0)),
                    "memory_positions": memory_positions,
                    "items_count": len(items),
                    "trace_id": payload.get("trace_id"),
                    "timeline": timeline,
                }
            )

        rows = build_sample_rows(outputs)
        if args.jsonl_output:
            write_jsonl(Path(args.jsonl_output), rows)
        if args.csv_output:
            write_csv(Path(args.csv_output), rows)
        if args.markdown_output:
            markdown = build_markdown_report(
                backend=str(health.get("backend")),
                user_id=args.user_id,
                limit=args.limit,
                interval_every=args.interval_every,
                random_seed=args.random_seed,
                arms=outputs,
                scenario_config=args.scenario_config,
            )
            write_markdown(Path(args.markdown_output), markdown)

        print(
            json.dumps(
                {
                    "status": "ok",
                    "backend": health.get("backend"),
                    "user_id": args.user_id,
                    "limit": args.limit,
                    "interval_every": args.interval_every,
                    "random_seed": args.random_seed,
                    "scenario_config": args.scenario_config,
                    "arms": outputs,
                    "sample_rows_count": len(rows),
                    "jsonl_output": args.jsonl_output,
                    "csv_output": args.csv_output,
                    "markdown_output": args.markdown_output,
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
