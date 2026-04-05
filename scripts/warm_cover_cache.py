#!/usr/bin/env python3
"""
Pre-warm BookFlow feed cover cache.

Generate chapter cover JPGs from source PDFs into a dedicated cache directory.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from pathlib import Path

import psycopg
from psycopg.rows import dict_row


def _safe_int(raw: object, default: int) -> int:
    try:
        return int(raw)
    except Exception:
        return int(default)


def _resolve(path: Path) -> Path:
    return path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()


def _is_stale(cache_path: Path, source_path: Path, ttl_sec: int) -> bool:
    if not cache_path.exists():
        return True
    try:
        if time.time() - cache_path.stat().st_mtime > max(1, int(ttl_sec)):
            return True
    except Exception:
        return True
    try:
        if cache_path.stat().st_mtime < source_path.stat().st_mtime:
            return True
    except Exception:
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Warm BookFlow chunk cover cache")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"), help="Postgres DSN")
    parser.add_argument("--cache-root", default=os.getenv("BOOKFLOW_COVER_CACHE_ROOT", "data/cache/covers"))
    parser.add_argument("--ttl-sec", type=int, default=int(os.getenv("BOOKFLOW_COVER_CACHE_TTL_SEC", "604800")))
    parser.add_argument("--book-id", default=None, help="Optional single book UUID")
    parser.add_argument("--limit", type=int, default=0, help="Max chunk rows to process (0=all)")
    parser.add_argument("--force", action="store_true", help="Ignore ttl/mtime and regenerate")
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("DATABASE_URL is required")

    cache_root = _resolve(Path(args.cache_root))
    cache_root.mkdir(parents=True, exist_ok=True)
    ttl_sec = max(60, int(args.ttl_sec))

    where_book = ""
    params: list[object] = []
    if args.book_id:
        where_book = "AND b.id = %s::uuid"
        params.append(str(args.book_id))

    limit_sql = ""
    if int(args.limit or 0) > 0:
        limit_sql = "LIMIT %s"
        params.append(int(args.limit))

    sql = f"""
    SELECT
      b.id::text AS book_id,
      c.id::text AS chunk_id,
      b.source_path,
      COALESCE(NULLIF(c.source_anchor->>'page_start', ''), '1')::int AS page_start
    FROM book_chunks c
    JOIN books b ON b.id = c.book_id
    WHERE b.source_format::text = 'pdf'
      AND COALESCE(c.metadata->>'content_type', '') = 'pdf_section'
      {where_book}
    ORDER BY b.created_at DESC, c.global_index ASC
    {limit_sql}
    """

    generated = 0
    skipped = 0
    failed = 0

    with psycopg.connect(args.database_url, autocommit=True, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()

    for row in rows:
        book_id = str(row.get("book_id") or "")
        chunk_id = str(row.get("chunk_id") or "")
        source_raw = str(row.get("source_path") or "").strip()
        page_start = max(1, _safe_int(row.get("page_start"), 1))
        if not book_id or not chunk_id or not source_raw:
            failed += 1
            continue

        source_path = _resolve(Path(source_raw))
        if not source_path.exists():
            failed += 1
            continue

        out_dir = cache_root / book_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{chunk_id}.jpg"
        out_prefix = out_path.with_suffix("")

        if not args.force and not _is_stale(out_path, source_path, ttl_sec):
            skipped += 1
            continue

        try:
            subprocess.run(
                [
                    "pdftoppm",
                    "-jpeg",
                    "-f",
                    str(page_start),
                    "-l",
                    str(page_start),
                    "-singlefile",
                    "-scale-to-x",
                    "900",
                    "-scale-to-y",
                    "-1",
                    str(source_path),
                    str(out_prefix),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if out_path.exists():
                generated += 1
            else:
                failed += 1
        except Exception:
            failed += 1

    print(
        json.dumps(
            {
                "status": "ok" if failed == 0 else ("partial" if generated > 0 else "error"),
                "cache_root": str(cache_root),
                "ttl_sec": ttl_sec,
                "force": bool(args.force),
                "generated": generated,
                "skipped": skipped,
                "failed": failed,
                "total": generated + skipped + failed,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
