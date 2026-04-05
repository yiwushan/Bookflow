#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys

import psycopg


def main() -> int:
    parser = argparse.ArgumentParser(description="Report interaction rejection distribution")
    parser.add_argument("--hours", type=int, default=24, help="Lookback window in hours")
    parser.add_argument("--limit", type=int, default=50, help="Top N rows for detail section")
    args = parser.parse_args()

    if args.hours <= 0:
        print("--hours must be positive", file=sys.stderr)
        return 1
    if args.limit <= 0:
        print("--limit must be positive", file=sys.stderr)
        return 1

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is required", file=sys.stderr)
        return 1

    summary_sql = """
    SELECT
      error_stage,
      error_code,
      COUNT(*) AS cnt
    FROM interaction_rejections
    WHERE created_at >= NOW() - (%s::text || ' hours')::interval
    GROUP BY error_stage, error_code
    ORDER BY cnt DESC, error_stage, error_code
    """

    detail_sql = """
    SELECT
      created_at,
      error_stage,
      error_code,
      event_id,
      event_type,
      user_id,
      book_id,
      chunk_id
    FROM interaction_rejections
    WHERE created_at >= NOW() - (%s::text || ' hours')::interval
    ORDER BY created_at DESC
    LIMIT %s
    """

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(summary_sql, (args.hours,))
            summary_rows = cur.fetchall()
            cur.execute(detail_sql, (args.hours, args.limit))
            detail_rows = cur.fetchall()

    summary = [
        {
            "error_stage": str(row[0]),
            "error_code": str(row[1]),
            "count": int(row[2]),
        }
        for row in summary_rows
    ]
    detail = [
        {
            "created_at": row[0].isoformat() if row[0] else None,
            "error_stage": str(row[1]),
            "error_code": str(row[2]),
            "event_id": row[3],
            "event_type": row[4],
            "user_id": row[5],
            "book_id": row[6],
            "chunk_id": row[7],
        }
        for row in detail_rows
    ]

    print(
        json.dumps(
            {
                "window_hours": args.hours,
                "summary": summary,
                "details": detail,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
