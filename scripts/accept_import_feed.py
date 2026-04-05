#!/usr/bin/env python3
"""
Acceptance script:
1) run import_book CLI
2) boot API server in Postgres mode
3) verify /v1/feed returns imported book chunks
"""

from __future__ import annotations

import argparse
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


def request_json(
    method: str,
    url: str,
    body: dict[str, Any] | None = None,
    token: str | None = None,
) -> tuple[int, dict[str, Any]]:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, method=method, data=data, headers=headers)
    try:
        with urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        payload = json.loads(exc.read().decode("utf-8"))
        return exc.code, payload


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


def wait_server_ready(base_url: str, timeout_sec: int = 12) -> dict[str, Any]:
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


def find_book_in_feed(base_url: str, token: str, book_id: str, page_limit: int, page_size: int) -> tuple[int, int]:
    cursor: str | None = None
    pages = 0
    hits = 0
    while pages < page_limit:
        pages += 1
        q = f"limit={page_size}"
        if cursor:
            q = f"{q}&cursor={cursor}"
        status, payload = request_json("GET", f"{base_url}/v1/feed?{q}", token=token)
        if status != 200:
            raise RuntimeError(f"feed request failed: status={status} payload={payload}")

        items = payload.get("items", [])
        hits += sum(1 for item in items if item.get("book_id") == book_id)
        cursor = payload.get("next_cursor")
        if not cursor:
            break
    return hits, pages


def main() -> int:
    parser = argparse.ArgumentParser(description="Acceptance: import -> feed visibility")
    parser.add_argument("--input", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--author", default=None)
    parser.add_argument("--book-type", default="general", choices=["general", "fiction", "technical"])
    parser.add_argument("--language", default="zh")
    parser.add_argument("--source-format", default=None, choices=["pdf", "epub", "txt"])
    parser.add_argument("--book-id", default=None)
    parser.add_argument("--config", default="config/pipeline.json")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--token", default="local-dev-token")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--feed-page-limit", type=int, default=5)
    parser.add_argument("--feed-page-size", type=int, default=50)
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    dsn = args.database_url or os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required (or pass --database-url)")

    import_result = run_import(args, repo_root, dsn)
    imported_book_id = str(import_result.get("book_id"))
    chunks_upserted = int(import_result.get("chunks_upserted", 0))

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

        feed_hits, pages = find_book_in_feed(
            base_url=base_url,
            token=args.token,
            book_id=imported_book_id,
            page_limit=args.feed_page_limit,
            page_size=args.feed_page_size,
        )

        if feed_hits <= 0:
            raise RuntimeError("feed does not contain imported book chunks")

        print(
            json.dumps(
                {
                    "status": "ok",
                    "book_id": imported_book_id,
                    "title": import_result.get("title"),
                    "chunks_upserted": chunks_upserted,
                    "feed_hits": feed_hits,
                    "feed_pages_scanned": pages,
                    "backend": health.get("backend"),
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
