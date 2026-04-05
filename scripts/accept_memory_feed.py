#!/usr/bin/env python3
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Acceptance: memory posts inserted into feed")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--user-id", default="11111111-1111-1111-1111-111111111111")
    parser.add_argument("--token", default="local-dev-token")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args()

    dsn = args.database_url or os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL is required (or pass --database-url)")

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

        status, payload = request_json(
            "GET",
            f"{base_url}/v1/feed?limit=5&mode=default&user_id={args.user_id}&with_memory=1",
            token=args.token,
        )
        if status != 200:
            raise RuntimeError(f"feed failed: {status} {payload}")
        memory_inserted = int(payload.get("memory_inserted", 0))
        if memory_inserted <= 0:
            raise RuntimeError("memory_inserted == 0")
        first = payload.get("items", [{}])[0]
        if first.get("item_type") != "memory_post":
            raise RuntimeError("first item is not memory_post")

        print(
            json.dumps(
                {
                    "status": "ok",
                    "backend": health.get("backend"),
                    "memory_inserted": memory_inserted,
                    "first_item_type": first.get("item_type"),
                    "trace_id": payload.get("trace_id"),
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
