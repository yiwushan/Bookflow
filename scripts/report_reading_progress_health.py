#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import psycopg


def main() -> int:
    parser = argparse.ArgumentParser(description="Reading progress health check report")
    parser.add_argument("--stale-days", type=int, default=7)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--csv-output", default=None, help="Optional CSV output path")
    args = parser.parse_args()

    if args.stale_days < 0:
        print("--stale-days must be >= 0", file=sys.stderr)
        return 1
    if args.top <= 0:
        print("--top must be > 0", file=sys.stderr)
        return 1

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is required", file=sys.stderr)
        return 1

    summary_sql = """
    SELECT
      COUNT(*)::int AS total_rows,
      COUNT(*) FILTER (WHERE completion_rate > 0)::int AS active_rows,
      COUNT(*) FILTER (WHERE completion_rate = 0)::int AS zero_completion_rows,
      COUNT(*) FILTER (WHERE updated_at < NOW() - (%s::text || ' days')::interval)::int AS stale_rows,
      ROUND(COALESCE(AVG(completion_rate), 0), 4)::numeric AS avg_completion_rate
    FROM reading_progress
    """

    top_books_sql = """
    SELECT
      rp.book_id::text AS book_id,
      b.title AS book_title,
      COUNT(*)::int AS users_tracked,
      ROUND(COALESCE(AVG(rp.completion_rate), 0), 4)::numeric AS avg_completion_rate
    FROM reading_progress rp
    JOIN books b ON b.id = rp.book_id
    GROUP BY rp.book_id, b.title
    ORDER BY avg_completion_rate DESC, users_tracked DESC
    LIMIT %s
    """

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(summary_sql, (args.stale_days,))
            row = cur.fetchone()
            cur.execute(top_books_sql, (args.top,))
            top_rows = cur.fetchall()

    payload = {
        "status": "ok",
        "stale_days": args.stale_days,
        "summary": {
            "total_rows": int(row[0]),
            "active_rows": int(row[1]),
            "zero_completion_rows": int(row[2]),
            "stale_rows": int(row[3]),
            "avg_completion_rate": float(row[4] or 0.0),
        },
        "top_books": [
            {
                "book_id": r[0],
                "book_title": r[1],
                "users_tracked": int(r[2]),
                "avg_completion_rate": float(r[3] or 0.0),
            }
            for r in top_rows
        ],
    }

    if args.csv_output:
        out_path = Path(args.csv_output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "row_type",
                    "metric",
                    "value",
                    "book_id",
                    "book_title",
                    "users_tracked",
                    "avg_completion_rate",
                ]
            )
            for k, v in payload["summary"].items():
                writer.writerow(["summary", k, v, "", "", "", ""])
            for row in payload["top_books"]:
                writer.writerow(
                    [
                        "top_book",
                        "",
                        "",
                        row["book_id"],
                        row["book_title"],
                        row["users_tracked"],
                        row["avg_completion_rate"],
                    ]
                )
        payload["csv_output"] = str(out_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
