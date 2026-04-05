#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

import psycopg


def main() -> int:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is required", file=sys.stderr)
        return 1

    statements = [
        "REFRESH MATERIALIZED VIEW mv_daily_section_complete_per_user",
        "REFRESH MATERIALIZED VIEW mv_daily_funnel_rates",
        "REFRESH MATERIALIZED VIEW mv_daily_deep_read_depth",
        "REFRESH MATERIALIZED VIEW mv_daily_fragmentation_risk",
        "REFRESH MATERIALIZED VIEW mv_chunk_confusion_hotspots",
        "REFRESH MATERIALIZED VIEW mv_render_reason_distribution",
    ]
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            for sql in statements:
                cur.execute(sql)
                print(f"ok: {sql}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

