#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections import Counter
from pathlib import Path

import psycopg

try:
    from auto_tag_chunks import load_rules_bundle, score_text
except ModuleNotFoundError:  # pragma: no cover
    from scripts.auto_tag_chunks import load_rules_bundle, score_text


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze auto-tag rule hit rates")
    parser.add_argument("--book-id", default=None, help="Optional book UUID filter")
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--rules", default="config/auto_tag_rules.json", help="Rule config path")
    parser.add_argument("--rule-version", default=None, help="Optional rule version key for rollback")
    args = parser.parse_args()
    rules_bundle = load_rules_bundle(Path(args.rules), rule_version=args.rule_version)
    rules = rules_bundle["rules"]

    if args.limit <= 0:
        print("--limit must be > 0", file=sys.stderr)
        return 1

    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is required", file=sys.stderr)
        return 1

    book_id = None
    if args.book_id:
        try:
            book_id = str(uuid.UUID(args.book_id))
        except Exception:
            print("invalid --book-id", file=sys.stderr)
            return 1

    where_sql = "TRUE"
    params: list[object] = [args.limit]
    if book_id is not None:
        where_sql = "book_id = %s"
        params = [book_id, args.limit]

    chunks_sql = f"""
    SELECT id::text, text_content
    FROM book_chunks
    WHERE {where_sql}
    ORDER BY created_at DESC
    LIMIT %s
    """
    tag_count_sql = """
    SELECT chunk_id::text, COUNT(*)::int AS tag_count
    FROM chunk_tags
    WHERE chunk_id = ANY(%s::uuid[])
    GROUP BY chunk_id
    """

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(chunks_sql, tuple(params))
            chunks = cur.fetchall()

            chunk_ids = [row[0] for row in chunks]
            tag_count_map: dict[str, int] = {}
            if chunk_ids:
                cur.execute(tag_count_sql, (chunk_ids,))
                tag_count_map = {row[0]: int(row[1]) for row in cur.fetchall()}

    total = len(chunks)
    rule_hit_chunks = 0
    assigned_tag_chunks = 0
    sum_tag_count = 0
    matched_rule_counter: Counter[str] = Counter()

    for chunk_id, text_content in chunks:
        text = text_content or ""
        hit_rules: list[str] = []
        for tag_name, cfg in rules.items():
            if score_text(text, cfg["keywords"]) > 0:
                hit_rules.append(tag_name)
        if hit_rules:
            rule_hit_chunks += 1
            for r in set(hit_rules):
                matched_rule_counter[r] += 1

        tc = int(tag_count_map.get(chunk_id, 0))
        if tc > 0:
            assigned_tag_chunks += 1
        sum_tag_count += tc

    payload = {
        "status": "ok",
        "book_id_filter": book_id,
        "limit": args.limit,
        "rules_path": str(Path(args.rules)),
        "rule_schema": rules_bundle["schema"],
        "selected_rule_version": rules_bundle["selected_rule_version"],
        "active_rule_version": rules_bundle["active_rule_version"],
        "available_rule_versions": rules_bundle["available_rule_versions"],
        "rules_count": len(rules),
        "summary": {
            "chunks_scanned": total,
            "rule_hit_chunks": rule_hit_chunks,
            "rule_hit_rate": round((rule_hit_chunks / total), 4) if total > 0 else 0.0,
            "chunks_with_assigned_tags": assigned_tag_chunks,
            "assigned_tag_rate": round((assigned_tag_chunks / total), 4) if total > 0 else 0.0,
            "avg_assigned_tags_per_chunk": round((sum_tag_count / total), 4) if total > 0 else 0.0,
        },
        "top_rule_hits": [
            {"rule": name, "chunks": int(cnt)}
            for name, cnt in matched_rule_counter.most_common(10)
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
