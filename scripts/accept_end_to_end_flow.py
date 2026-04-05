#!/usr/bin/env python3
"""
Acceptance script (end-to-end):
1) import book
2) start API server
3) verify imported chunks appear in /v1/feed
4) verify /v1/chunk_context works on imported chunk
5) post /v1/interactions events for imported chunk
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

JSONL_SCHEMA_VERSION = "accept_end_to_end_flow.jsonl.v1"
MARKDOWN_SCHEMA_VERSION = "accept_end_to_end_flow.markdown.v1"


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def request_json(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    data = None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    req = Request(url, method=method, data=data, headers=headers)
    try:
        with urlopen(req, timeout=8) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8"))
        return exc.code, payload


def wait_server_ready(base_url: str, timeout_sec: int = 14) -> dict[str, Any]:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            status, payload = request_json("GET", f"{base_url}/health")
            if status == 200 and payload.get("status") == "ok":
                return payload
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError("server not ready in time")


def run_import(args: argparse.Namespace, repo_root: Path, dsn: str) -> dict[str, Any]:
    cmd = [
        "python3",
        "scripts/import_book.py",
        "--input",
        args.input,
        "--title",
        args.title,
        "--book-type",
        args.book_type,
        "--language",
        args.language,
        "--config",
        args.config,
        "--database-url",
        dsn,
    ]
    if args.author:
        cmd.extend(["--author", args.author])
    if args.book_id:
        cmd.extend(["--book-id", args.book_id])
    if args.source_format:
        cmd.extend(["--source-format", args.source_format])

    proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"import failed: {proc.stderr.strip() or proc.stdout.strip()}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"import output is not valid json: {exc}") from exc


def find_imported_feed_item(
    *,
    base_url: str,
    token: str,
    book_id: str,
    user_id: str,
    page_limit: int,
    page_size: int,
) -> tuple[dict[str, Any], int, int]:
    cursor: str | None = None
    pages = 0
    hits = 0
    selected: dict[str, Any] | None = None
    while pages < page_limit:
        pages += 1
        q = f"limit={page_size}&mode=default&user_id={user_id}"
        if cursor:
            q += f"&cursor={cursor}"
        status, payload = request_json("GET", f"{base_url}/v1/feed?{q}", token=token)
        if status != 200:
            raise RuntimeError(f"feed request failed: status={status} payload={payload}")
        items = payload.get("items", [])
        matched = [item for item in items if item.get("book_id") == book_id]
        hits += len(matched)
        if selected is None and matched:
            selected = dict(matched[0])
        cursor = payload.get("next_cursor")
        if not cursor:
            break
    if selected is None:
        raise RuntimeError("feed does not contain imported book chunks")
    return selected, hits, pages


def make_event(
    *,
    event_type: str,
    user_id: str,
    book_id: str,
    chunk_id: str,
    position_in_chunk: float,
    payload: dict[str, Any],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    event_id = str(uuid.uuid4())
    idem = f"accept_e2e_{event_type}_{chunk_id}_{event_id[:8]}"
    return {
        "event_id": event_id,
        "event_type": event_type,
        "event_ts": now,
        "user_id": user_id,
        "session_id": "s_accept_e2e",
        "book_id": book_id,
        "chunk_id": chunk_id,
        "position_in_chunk": max(0.0, min(1.0, float(position_in_chunk))),
        "idempotency_key": idem,
        "client": {"platform": "web", "app_version": "0.2.0-accept", "device_id": "d_accept_e2e"},
        "payload": payload,
    }


def write_markdown(path: Path, rows: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# BookFlow E2E Acceptance",
        "",
        f"- markdown_schema_version: `{MARKDOWN_SCHEMA_VERSION}`",
        f"- status: `{rows.get('status')}`",
        f"- backend: `{rows.get('backend')}`",
        f"- book_id: `{rows.get('book_id')}`",
        f"- chunks_upserted: `{rows.get('chunks_upserted')}`",
        f"- feed_hits: `{rows.get('feed_hits')}`",
        f"- feed_pages_scanned: `{rows.get('feed_pages_scanned')}`",
        f"- feed_trace_id: `{rows.get('feed_trace_id')}`",
        f"- feed_trace_file_path: `{rows.get('feed_trace_file_path')}`",
        f"- feed_trace_file_exists: `{rows.get('feed_trace_file_exists')}`",
        f"- selected_chunk_id: `{rows.get('selected_chunk_id')}`",
        f"- context_prev_chunk_id: `{rows.get('context_prev_chunk_id')}`",
        f"- context_next_chunk_id: `{rows.get('context_next_chunk_id')}`",
        f"- chunk_context_batch_requested_count: `{rows.get('chunk_context_batch_requested_count')}`",
        f"- chunk_context_batch_found_count: `{rows.get('chunk_context_batch_found_count')}`",
        f"- chunk_context_batch_cache_enabled: `{rows.get('chunk_context_batch_cache_enabled')}`",
        f"- chunk_context_batch_request_hit_delta: `{rows.get('chunk_context_batch_request_hit_delta')}`",
        f"- chunk_context_batch_trace_id: `{rows.get('chunk_context_batch_trace_id')}`",
        f"- interactions_accepted: `{rows.get('interactions_accepted')}`",
        f"- interactions_rejected: `{rows.get('interactions_rejected')}`",
        f"- interactions_trace_id: `{rows.get('interactions_trace_id')}`",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Acceptance: import -> feed -> context -> interactions")
    parser.add_argument("--input", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--author", default=None)
    parser.add_argument("--book-type", default="general", choices=["general", "fiction", "technical"])
    parser.add_argument("--language", default="zh")
    parser.add_argument("--source-format", default=None, choices=["pdf", "epub", "txt"])
    parser.add_argument("--book-id", default=None)
    parser.add_argument("--config", default="config/pipeline.json")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--user-id", default="11111111-1111-1111-1111-111111111111")
    parser.add_argument("--token", default="local-dev-token")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--feed-page-limit", type=int, default=5)
    parser.add_argument("--feed-page-size", type=int, default=50)
    parser.add_argument("--markdown-output", default=None)
    parser.add_argument("--jsonl-output", default=None)
    args = parser.parse_args()

    dsn = args.database_url or os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required (or pass --database-url)")

    try:
        uuid.UUID(str(args.user_id))
    except Exception:
        raise SystemExit("--user-id must be UUID")

    repo_root = Path(__file__).resolve().parents[1]
    import_result = run_import(args, repo_root, dsn)
    imported_book_id = str(import_result.get("book_id"))
    chunks_upserted = int(import_result.get("chunks_upserted", 0))
    if chunks_upserted <= 0:
        raise RuntimeError("import produced zero chunks")

    port = args.port or get_free_port()
    base_url = f"http://{args.host}:{port}"

    env = os.environ.copy()
    env["BOOKFLOW_TOKEN"] = args.token
    env["DATABASE_URL"] = dsn

    proc = subprocess.Popen(
        ["python3", "server/app.py", "--host", args.host, "--port", str(port)],
        cwd=str(repo_root),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        health = wait_server_ready(base_url)
        if health.get("backend") != "postgres":
            raise RuntimeError(f"backend is not postgres: {health}")

        item, feed_hits, feed_pages = find_imported_feed_item(
            base_url=base_url,
            token=args.token,
            book_id=imported_book_id,
            user_id=args.user_id,
            page_limit=args.feed_page_limit,
            page_size=args.feed_page_size,
        )
        status_feed_trace, payload_feed_trace = request_json(
            "GET",
            f"{base_url}/v1/feed?limit=5&mode=default&user_id={args.user_id}&trace=1&trace_file=1",
            token=args.token,
        )
        if status_feed_trace != 200:
            raise RuntimeError(f"feed trace_file failed: status={status_feed_trace} payload={payload_feed_trace}")
        feed_trace_id = payload_feed_trace.get("trace_id")
        feed_trace_file_path = str(payload_feed_trace.get("trace_file_path") or "").strip()
        if not feed_trace_file_path:
            raise RuntimeError(f"feed trace file path missing: {payload_feed_trace}")
        feed_trace_file_exists = Path(feed_trace_file_path).exists()
        if not feed_trace_file_exists:
            raise RuntimeError(f"feed trace file does not exist: {feed_trace_file_path}")
        chunk_id = str(item.get("chunk_id"))
        section_id = str(item.get("section_id") or "")

        status_ctx, payload_ctx = request_json(
            "GET",
            f"{base_url}/v1/chunk_context?book_id={imported_book_id}&chunk_id={chunk_id}",
            token=args.token,
        )
        if status_ctx != 200:
            raise RuntimeError(f"chunk_context failed: status={status_ctx} payload={payload_ctx}")

        batch_chunk_ids = [chunk_id]
        next_chunk_id = str(payload_ctx.get("next_chunk_id") or "").strip()
        prev_chunk_id = str(payload_ctx.get("prev_chunk_id") or "").strip()
        if next_chunk_id and next_chunk_id not in batch_chunk_ids:
            batch_chunk_ids.append(next_chunk_id)
        if prev_chunk_id and prev_chunk_id not in batch_chunk_ids:
            batch_chunk_ids.append(prev_chunk_id)
        chunk_ids_arg = ",".join(batch_chunk_ids)
        status_ctxb_warm, payload_ctxb_warm = request_json(
            "GET",
            f"{base_url}/v1/chunk_context_batch?book_id={imported_book_id}&chunk_ids={chunk_ids_arg}",
            token=args.token,
        )
        if status_ctxb_warm != 200:
            raise RuntimeError(
                f"chunk_context_batch warmup failed: status={status_ctxb_warm} payload={payload_ctxb_warm}"
            )
        if int(payload_ctxb_warm.get("found_count", 0)) <= 0:
            raise RuntimeError(f"chunk_context_batch warmup found_count invalid: {payload_ctxb_warm}")

        status_ctxb, payload_ctxb = request_json(
            "GET",
            f"{base_url}/v1/chunk_context_batch?book_id={imported_book_id}&chunk_ids={chunk_ids_arg}&cache_stats=1",
            token=args.token,
        )
        if status_ctxb != 200:
            raise RuntimeError(f"chunk_context_batch failed: status={status_ctxb} payload={payload_ctxb}")
        if int(payload_ctxb.get("found_count", 0)) <= 0:
            raise RuntimeError(f"chunk_context_batch found_count invalid: {payload_ctxb}")
        cache_stats = payload_ctxb.get("cache_stats", {}) or {}
        cache_enabled = bool(cache_stats.get("cache_enabled", False))
        request_hit_delta = int(cache_stats.get("request_cache_hit_delta", 0) or 0)
        if cache_enabled and request_hit_delta <= 0:
            raise RuntimeError(f"chunk_context_batch cache hit delta invalid: {payload_ctxb}")

        events = [
            make_event(
                event_type="impression",
                user_id=args.user_id,
                book_id=imported_book_id,
                chunk_id=chunk_id,
                position_in_chunk=0.05,
                payload={},
            ),
            make_event(
                event_type="enter_context",
                user_id=args.user_id,
                book_id=imported_book_id,
                chunk_id=chunk_id,
                position_in_chunk=0.1,
                payload={},
            ),
            make_event(
                event_type="like",
                user_id=args.user_id,
                book_id=imported_book_id,
                chunk_id=chunk_id,
                position_in_chunk=0.85,
                payload={"source": "accept_end_to_end_flow"},
            ),
            make_event(
                event_type="section_complete",
                user_id=args.user_id,
                book_id=imported_book_id,
                chunk_id=chunk_id,
                position_in_chunk=1.0,
                payload={
                    "section_id": section_id or f"sec_accept_{chunk_id[:8]}",
                    "read_time_sec": int(item.get("estimated_read_sec") or 30),
                },
            ),
        ]

        status_evt, payload_evt = request_json(
            "POST",
            f"{base_url}/v1/interactions",
            token=args.token,
            body={"events": events},
        )
        if status_evt != 200:
            raise RuntimeError(f"interactions failed: status={status_evt} payload={payload_evt}")
        if int(payload_evt.get("rejected", 0)) > 0:
            raise RuntimeError(f"interactions rejected events: {payload_evt}")

        out = {
            "status": "ok",
            "backend": health.get("backend"),
            "book_id": imported_book_id,
            "title": import_result.get("title"),
            "chunks_upserted": chunks_upserted,
            "feed_hits": int(feed_hits),
            "feed_pages_scanned": int(feed_pages),
            "feed_trace_id": feed_trace_id,
            "feed_trace_file_path": feed_trace_file_path,
            "feed_trace_file_exists": feed_trace_file_exists,
            "selected_chunk_id": chunk_id,
            "context_prev_chunk_id": payload_ctx.get("prev_chunk_id"),
            "context_next_chunk_id": payload_ctx.get("next_chunk_id"),
            "chunk_context_batch_requested_count": int(payload_ctxb.get("requested_count", 0)),
            "chunk_context_batch_found_count": int(payload_ctxb.get("found_count", 0)),
            "chunk_context_batch_cache_enabled": cache_enabled,
            "chunk_context_batch_request_hit_delta": request_hit_delta,
            "chunk_context_batch_trace_id": payload_ctxb.get("trace_id"),
            "interactions_accepted": int(payload_evt.get("accepted", 0)),
            "interactions_deduplicated": int(payload_evt.get("deduplicated", 0)),
            "interactions_rejected": int(payload_evt.get("rejected", 0)),
            "interactions_trace_id": payload_evt.get("trace_id"),
        }
        if args.markdown_output:
            write_markdown(Path(args.markdown_output), out)
            out["markdown_output"] = args.markdown_output
            out["markdown_schema_version"] = MARKDOWN_SCHEMA_VERSION
        if args.jsonl_output:
            jsonl_row = dict(out)
            jsonl_row["schema_version"] = JSONL_SCHEMA_VERSION
            append_jsonl(Path(args.jsonl_output), jsonl_row)
            out["jsonl_output"] = args.jsonl_output
            out["jsonl_schema_version"] = JSONL_SCHEMA_VERSION
        if args.markdown_output and args.jsonl_output:
            out["schema_version_consistency_note"] = (
                f"markdown={MARKDOWN_SCHEMA_VERSION};jsonl={JSONL_SCHEMA_VERSION}"
            )
        elif args.markdown_output:
            out["schema_version_consistency_note"] = f"markdown={MARKDOWN_SCHEMA_VERSION};jsonl=none"
        elif args.jsonl_output:
            out["schema_version_consistency_note"] = f"markdown=none;jsonl={JSONL_SCHEMA_VERSION}"
        else:
            out["schema_version_consistency_note"] = "no_export"

        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
