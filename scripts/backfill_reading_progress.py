#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

import psycopg


def validate_uuid(raw: str | None, name: str) -> str | None:
    if raw is None:
        return None
    try:
        return str(uuid.UUID(raw))
    except Exception:
        raise ValueError(f"invalid {name}: {raw}") from None


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill reading_progress from interactions")
    parser.add_argument("--user-id", default=None, help="Optional UUID filter")
    parser.add_argument("--book-id", default=None, help="Optional UUID filter")
    args = parser.parse_args()

    try:
        user_id = validate_uuid(args.user_id, "user-id")
        book_id = validate_uuid(args.book_id, "book-id")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is required", file=sys.stderr)
        return 1

    filters = ["i.event_type = 'section_complete'"]
    params: list[object] = []
    if user_id is not None:
        filters.append("i.user_id = %s")
        params.append(user_id)
    if book_id is not None:
        filters.append("i.book_id = %s")
        params.append(book_id)
    where_sql = " AND ".join(filters)

    sql = f"""
    WITH aggregated AS (
      SELECT
        i.user_id,
        i.book_id,
        COUNT(DISTINCT COALESCE(i.payload->>'section_id', '')) FILTER (
          WHERE COALESCE(i.payload->>'section_id', '') <> ''
        )::int AS section_completed_count,
        COUNT(DISTINCT i.chunk_id)::int AS chunk_completed_count,
        (ARRAY_AGG(i.chunk_id ORDER BY i.event_ts DESC))[1] AS latest_chunk_id,
        MAX(i.event_ts) AS latest_event_ts
      FROM interactions i
      WHERE {where_sql}
      GROUP BY i.user_id, i.book_id
    ),
    upserted AS (
      INSERT INTO reading_progress (
        user_id,
        book_id,
        section_completed_count,
        chunk_completed_count,
        completion_rate,
        latest_chunk_id,
        latest_event_ts,
        updated_at
      )
      SELECT
        a.user_id,
        a.book_id,
        a.section_completed_count,
        a.chunk_completed_count,
        CASE
          WHEN COALESCE(b.total_sections, 0) > 0
            THEN ROUND(LEAST(1.0, a.section_completed_count::numeric / b.total_sections::numeric), 4)
          ELSE 0.0
        END AS completion_rate,
        a.latest_chunk_id,
        a.latest_event_ts,
        NOW()
      FROM aggregated a
      JOIN books b ON b.id = a.book_id
      ON CONFLICT (user_id, book_id) DO UPDATE SET
        section_completed_count = EXCLUDED.section_completed_count,
        chunk_completed_count = EXCLUDED.chunk_completed_count,
        completion_rate = EXCLUDED.completion_rate,
        latest_chunk_id = EXCLUDED.latest_chunk_id,
        latest_event_ts = EXCLUDED.latest_event_ts,
        updated_at = NOW()
      RETURNING 1
    )
    SELECT COUNT(*) FROM upserted
    """

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            affected = int(cur.fetchone()[0])

    print(
        json.dumps(
            {
                "status": "ok",
                "affected_rows": affected,
                "filters": {"user_id": user_id, "book_id": book_id},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
