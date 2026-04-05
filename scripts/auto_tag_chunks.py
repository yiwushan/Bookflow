#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import psycopg


DEFAULT_TAG_RULES: dict[str, dict[str, Any]] = {
    "算法": {"category": "technical", "keywords": ["梯度", "损失函数", "优化", "algorithm", "gradient"]},
    "编程": {"category": "technical", "keywords": ["for ", "def ", "class ", "print(", "代码", "python", "函数"]},
    "心理学": {"category": "general", "keywords": ["心理", "认知", "情绪", "行为"]},
    "睡前故事": {"category": "fiction", "keywords": ["故事", "夜晚", "童话", "梦"]},
    "小说": {"category": "fiction", "keywords": ["主人公", "对白", "情节", "章节"]},
    "干货": {"category": "general", "keywords": ["总结", "步骤", "方法", "要点", "实践"]},
}
TAG_RULES = DEFAULT_TAG_RULES


def score_text(text: str, keywords: list[str]) -> float:
    lowered = text.lower()
    hits = 0
    for kw in keywords:
        if kw.lower() in lowered:
            hits += 1
    if hits == 0:
        return 0.0
    return min(0.99, 0.20 + 0.15 * hits)


def _normalize_rules(raw_rules: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(raw_rules, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for tag_name, cfg in raw_rules.items():
        if not isinstance(tag_name, str) or not isinstance(cfg, dict):
            continue
        category = str(cfg.get("category", "general"))
        keywords_raw = cfg.get("keywords", [])
        if not isinstance(keywords_raw, list):
            continue
        keywords = [str(k).strip() for k in keywords_raw if str(k).strip()]
        if not keywords:
            continue
        normalized[tag_name] = {"category": category, "keywords": keywords}
    return normalized


def load_rules_bundle(path: Path | None, rule_version: str | None = None) -> dict[str, Any]:
    fallback = {
        "rules": dict(DEFAULT_TAG_RULES),
        "schema": "default",
        "selected_rule_version": "default",
        "active_rule_version": "default",
        "available_rule_versions": ["default"],
    }
    if path is None or not path.exists():
        return fallback

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback

    if not isinstance(raw, dict):
        return fallback

    # Versioned schema (preferred): rule_versions + active_rule_version
    versioned_raw = raw.get("rule_versions")
    if isinstance(versioned_raw, dict):
        versioned_rules: dict[str, dict[str, dict[str, Any]]] = {}
        for version_name, version_rules in versioned_raw.items():
            normalized_rules = _normalize_rules(version_rules)
            if normalized_rules:
                versioned_rules[str(version_name)] = normalized_rules
        if versioned_rules:
            available = sorted(versioned_rules.keys())
            active = str(raw.get("active_rule_version", "")).strip()
            if active not in versioned_rules:
                active = available[0]
            selected = str(rule_version).strip() if rule_version else active
            if selected not in versioned_rules:
                selected = active
            return {
                "rules": versioned_rules[selected],
                "schema": "versioned",
                "selected_rule_version": selected,
                "active_rule_version": active,
                "available_rule_versions": available,
            }

    # Legacy schema: {"rules": {...}} or direct dict
    legacy_source = raw.get("rules", raw)
    legacy_rules = _normalize_rules(legacy_source)
    if not legacy_rules:
        return fallback
    return {
        "rules": legacy_rules,
        "schema": "legacy",
        "selected_rule_version": "legacy",
        "active_rule_version": "legacy",
        "available_rule_versions": ["legacy"],
    }


def load_rules(path: Path | None, rule_version: str | None = None) -> dict[str, dict[str, Any]]:
    return load_rules_bundle(path=path, rule_version=rule_version)["rules"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Auto tag chunks with local keyword rules")
    parser.add_argument("--book-id", default=None, help="Optional book UUID filter")
    parser.add_argument("--limit", type=int, default=1000, help="Max chunks to scan")
    parser.add_argument("--rules", default="config/auto_tag_rules.json", help="Rule config path")
    parser.add_argument("--rule-version", default=None, help="Optional rule version key for rollback")
    args = parser.parse_args()
    rules_bundle = load_rules_bundle(Path(args.rules), rule_version=args.rule_version)
    rules = rules_bundle["rules"]

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

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            for tag_name, cfg in rules.items():
                cur.execute(
                    "INSERT INTO tags (name, category) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                    (tag_name, cfg["category"]),
                )

            params: list[object] = [args.limit]
            where_sql = "TRUE"
            if book_id:
                where_sql = "book_id = %s"
                params = [book_id, args.limit]

            cur.execute(
                f"""
                SELECT id::text, text_content
                FROM book_chunks
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                tuple(params),
            )
            chunks = cur.fetchall()

            cur.execute("SELECT id, name FROM tags WHERE name = ANY(%s)", (list(rules.keys()),))
            tag_id_map = {row[1]: int(row[0]) for row in cur.fetchall()}

            tags_upserted = 0
            chunks_scanned = 0
            for chunk_id, text_content in chunks:
                chunks_scanned += 1
                text = text_content or ""
                scored: list[tuple[str, float]] = []
                for tag_name, cfg in rules.items():
                    s = score_text(text, cfg["keywords"])
                    if s > 0:
                        scored.append((tag_name, s))
                if not scored:
                    scored = [("干货", 0.2)]

                # Keep top-3 tags per chunk for v0.
                scored.sort(key=lambda x: x[1], reverse=True)
                for tag_name, score in scored[:3]:
                    tag_id = tag_id_map.get(tag_name)
                    if tag_id is None:
                        continue
                    cur.execute(
                        """
                        INSERT INTO chunk_tags (chunk_id, tag_id, score)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (chunk_id, tag_id) DO UPDATE SET
                          score = EXCLUDED.score
                        """,
                        (chunk_id, tag_id, round(score, 4)),
                    )
                    tags_upserted += 1

    print(
        json.dumps(
            {
                "status": "ok",
                "book_id_filter": book_id,
                "rules_path": str(Path(args.rules)),
                "rule_schema": rules_bundle["schema"],
                "selected_rule_version": rules_bundle["selected_rule_version"],
                "active_rule_version": rules_bundle["active_rule_version"],
                "available_rule_versions": rules_bundle["available_rule_versions"],
                "rules_count": len(rules),
                "chunks_scanned": chunks_scanned,
                "tags_upserted": tags_upserted,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
