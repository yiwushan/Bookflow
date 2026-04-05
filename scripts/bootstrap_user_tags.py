#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

import psycopg


TAG_CATALOG = [
    ("干货", "general"),
    ("睡前故事", "fiction"),
    ("心理学", "general"),
    ("算法", "technical"),
    ("编程", "technical"),
    ("小说", "fiction"),
]

PRESET_WEIGHTS = {
    "balanced": {
        "干货": 0.8,
        "心理学": 0.7,
        "算法": 0.6,
        "编程": 0.6,
        "睡前故事": 0.4,
        "小说": 0.4,
    },
    "technical": {
        "算法": 1.2,
        "编程": 1.0,
        "干货": 0.8,
        "心理学": 0.4,
        "睡前故事": 0.2,
        "小说": 0.2,
    },
    "fiction": {
        "睡前故事": 1.1,
        "小说": 1.0,
        "心理学": 0.6,
        "干货": 0.5,
        "算法": 0.2,
        "编程": 0.2,
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap user tag profile with cold-start preset")
    parser.add_argument("--user-id", required=True, help="User UUID")
    parser.add_argument("--preset", choices=sorted(PRESET_WEIGHTS.keys()), default="balanced")
    args = parser.parse_args()

    try:
        user_id = str(uuid.UUID(args.user_id))
    except Exception:
        print("invalid --user-id", file=sys.stderr)
        return 1

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is required", file=sys.stderr)
        return 1

    preset = PRESET_WEIGHTS[args.preset]
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                (user_id, f"user_{user_id[:8]}"),
            )
            for name, category in TAG_CATALOG:
                cur.execute(
                    "INSERT INTO tags (name, category) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                    (name, category),
                )

            affected = 0
            for name, weight in preset.items():
                cur.execute("SELECT id FROM tags WHERE name = %s", (name,))
                row = cur.fetchone()
                if row is None:
                    continue
                tag_id = int(row[0])
                cur.execute(
                    """
                    INSERT INTO user_tag_profile (user_id, tag_id, weight)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (user_id, tag_id) DO UPDATE SET
                      weight = EXCLUDED.weight,
                      updated_at = NOW()
                    """,
                    (user_id, tag_id, weight),
                )
                affected += 1

    print(
        json.dumps(
            {
                "status": "ok",
                "user_id": user_id,
                "preset": args.preset,
                "tags_upserted": affected,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
