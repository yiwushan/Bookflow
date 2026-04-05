#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import psycopg

JSONL_SCHEMA_VERSION = "chunk_granularity_ab_samples.jsonl.v1"
CSV_SCHEMA_VERSION = "chunk_granularity_ab_samples.csv.v1"
MARKDOWN_SCHEMA_VERSION = "chunk_granularity_ab_samples.markdown.v1"


def normalize_text(text: str) -> str:
    return " ".join((text or "").replace("\u3000", " ").split())


def _find_split_index(text: str) -> int:
    n = len(text)
    if n <= 1:
        return n
    mid = n // 2
    punct = set("。！？.!?;；:：")
    window = max(20, n // 5)

    right_end = min(n - 2, mid + window)
    for idx in range(mid, right_end + 1):
        if text[idx] in punct:
            return idx + 1

    left_start = max(1, mid - window)
    for idx in range(mid, left_start - 1, -1):
        if text[idx] in punct:
            return idx + 1
    return mid


def split_two_segments(text: str, min_split_chars: int = 120) -> list[str]:
    cleaned = normalize_text(text)
    if len(cleaned) < max(1, int(min_split_chars)):
        return [cleaned] if cleaned else []
    split_at = _find_split_index(cleaned)
    left = cleaned[:split_at].strip()
    right = cleaned[split_at:].strip()
    if not left or not right:
        return [cleaned] if cleaned else []
    return [left, right]


def build_ab_rows(chunks: list[dict[str, Any]], min_split_chars: int = 120) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    full_rows_count = 0
    split_rows_count = 0
    split_chunk_count = 0

    for rank, chunk in enumerate(chunks, start=1):
        text = normalize_text(str(chunk.get("text_content", "") or ""))
        if not text:
            continue
        full_rows_count += 1
        chunk_id = str(chunk.get("chunk_id"))
        chunk_title = chunk.get("chunk_title")
        section_id = chunk.get("section_id")
        book_id = str(chunk.get("book_id"))
        book_title = chunk.get("book_title")

        rows.append(
            {
                "arm": "A_full_section",
                "row_rank": rank,
                "book_id": book_id,
                "book_title": book_title,
                "chunk_id": chunk_id,
                "section_id": section_id,
                "chunk_title": chunk_title,
                "piece_index": 1,
                "piece_count": 1,
                "text_length": len(text),
                "text_preview": text[:96],
                "split_strategy": "full_section",
            }
        )

        segments = split_two_segments(text, min_split_chars=min_split_chars)
        if len(segments) > 1:
            split_chunk_count += 1
        split_rows_count += len(segments)
        for idx, segment in enumerate(segments, start=1):
            rows.append(
                {
                    "arm": "B_split_two",
                    "row_rank": rank,
                    "book_id": book_id,
                    "book_title": book_title,
                    "chunk_id": chunk_id,
                    "section_id": section_id,
                    "chunk_title": chunk_title,
                    "piece_index": idx,
                    "piece_count": len(segments),
                    "text_length": len(segment),
                    "text_preview": segment[:96],
                    "split_strategy": "split_two" if len(segments) > 1 else "fallback_full",
                }
            )

    summary = {
        "chunks_scanned": len(chunks),
        "chunks_with_text": full_rows_count,
        "full_rows_count": full_rows_count,
        "split_rows_count": split_rows_count,
        "split_chunk_count": split_chunk_count,
        "split_chunk_rate": round((split_chunk_count / full_rows_count), 4) if full_rows_count > 0 else 0.0,
    }
    return rows, summary


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            payload = dict(row)
            payload["schema_version"] = JSONL_SCHEMA_VERSION
            payload["csv_schema_version"] = CSV_SCHEMA_VERSION
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]], keyword_filter_stats: dict[str, Any] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "arm",
        "row_rank",
        "book_id",
        "book_title",
        "chunk_id",
        "section_id",
        "chunk_title",
        "piece_index",
        "piece_count",
        "text_length",
        "text_preview",
        "split_strategy",
        "markdown_schema_version",
        "schema_version",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = dict(row)
            payload["markdown_schema_version"] = MARKDOWN_SCHEMA_VERSION
            payload["schema_version"] = CSV_SCHEMA_VERSION
            writer.writerow(payload)
        if keyword_filter_stats is not None:
            total = int(keyword_filter_stats.get("total_candidates", 0) or 0)
            matched = int(keyword_filter_stats.get("matched_candidates", 0) or 0)
            hit_rate = float(keyword_filter_stats.get("hit_rate", 0.0) or 0.0)
            writer.writerow(
                {
                    "arm": "__summary__",
                    "row_rank": "",
                    "book_id": "",
                    "book_title": "",
                    "chunk_id": "",
                    "section_id": "",
                    "chunk_title": "",
                    "piece_index": "",
                    "piece_count": "",
                    "text_length": "",
                    "text_preview": f"keyword_filter_hit_rate={hit_rate}; matched={matched}; total={total}",
                    "split_strategy": "keyword_filter_summary",
                    "markdown_schema_version": MARKDOWN_SCHEMA_VERSION,
                    "schema_version": CSV_SCHEMA_VERSION,
                }
            )


def _md_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\n", " ").replace("|", "\\|").strip()


def build_markdown_report(
    *,
    book_id_filter: str | None,
    section_prefix: str | None,
    chunk_title_keyword: str | None,
    keyword_filter_stats: dict[str, Any] | None,
    limit: int,
    min_split_chars: int,
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    preview_top: int,
) -> str:
    keyword_total = int((keyword_filter_stats or {}).get("total_candidates", 0))
    keyword_matched = int((keyword_filter_stats or {}).get("matched_candidates", 0))
    keyword_hit_rate = float((keyword_filter_stats or {}).get("hit_rate", 0.0))
    lines = [
        "# Chunk Granularity A/B Samples",
        "",
        f"- book_id_filter: `{book_id_filter}`",
        f"- section_prefix: `{section_prefix if section_prefix is not None else 'n/a'}`",
        f"- chunk_title_keyword: `{chunk_title_keyword if chunk_title_keyword is not None else 'n/a'}`",
        f"- keyword_filter_total_candidates: `{keyword_total if chunk_title_keyword else 'n/a'}`",
        f"- keyword_filter_matched_candidates: `{keyword_matched if chunk_title_keyword else 'n/a'}`",
        f"- keyword_filter_hit_rate: `{keyword_hit_rate if chunk_title_keyword else 'n/a'}`",
        f"- limit: `{limit}`",
        f"- min_split_chars: `{min_split_chars}`",
        f"- chunks_scanned: `{summary.get('chunks_scanned', 0)}`",
        f"- chunks_with_text: `{summary.get('chunks_with_text', 0)}`",
        f"- split_chunk_count: `{summary.get('split_chunk_count', 0)}`",
        f"- split_chunk_rate: `{summary.get('split_chunk_rate', 0.0)}`",
        f"- jsonl_schema_version: `{JSONL_SCHEMA_VERSION}`",
        f"- csv_schema_version: `{CSV_SCHEMA_VERSION}`",
        f"- markdown_schema_version: `{MARKDOWN_SCHEMA_VERSION}`",
        f"- schema_version_consistency_note: `csv={CSV_SCHEMA_VERSION};jsonl={JSONL_SCHEMA_VERSION}`",
        "",
        "## Arm Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
    ]
    for key in [
        "chunks_scanned",
        "chunks_with_text",
        "full_rows_count",
        "split_rows_count",
        "split_chunk_count",
        "split_chunk_rate",
    ]:
        lines.append(f"| {key} | {summary.get(key)} |")

    lines.extend(
        [
            "",
            "## Row Preview",
            "",
            "| Arm | Chunk | Piece | Piece Count | Text Length | Preview |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in rows[: max(0, int(preview_top))]:
        lines.append(
            "| "
            + " | ".join(
                [
                    _md_cell(row.get("arm")),
                    _md_cell(row.get("chunk_id")),
                    _md_cell(row.get("piece_index")),
                    _md_cell(row.get("piece_count")),
                    _md_cell(row.get("text_length")),
                    _md_cell(row.get("text_preview")),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## CSV Notes",
            "",
            "- 当传入 `--chunk-title-keyword` 时，CSV 末尾会追加一行 `arm=__summary__`。",
            "- 该汇总行的 `split_strategy=keyword_filter_summary`，`text_preview` 包含 `keyword_filter_hit_rate/matched/total`。",
        ]
    )
    lines.append("")
    return "\n".join(lines)


def write_markdown(path: Path, markdown_text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown_text, encoding="utf-8")


def fetch_chunks(
    dsn: str,
    book_id: str | None,
    limit: int,
    section_prefix: str | None = None,
    chunk_title_keyword: str | None = None,
) -> list[dict[str, Any]]:
    where_clauses: list[str] = ["TRUE"]
    params: list[Any] = []
    if book_id is not None:
        where_clauses.append("c.book_id = %s")
        params.append(uuid.UUID(book_id))
    if section_prefix:
        where_clauses.append("COALESCE(c.section_id, '') LIKE %s")
        params.append(f"{section_prefix}%")
    if chunk_title_keyword:
        where_clauses.append("COALESCE(c.title, '') ILIKE %s")
        params.append(f"%{chunk_title_keyword}%")
    where_sql = " AND ".join(where_clauses)
    params.append(limit)

    sql = f"""
    SELECT
      c.id::text AS chunk_id,
      c.book_id::text AS book_id,
      b.title AS book_title,
      c.section_id,
      c.title AS chunk_title,
      c.text_content
    FROM book_chunks c
    JOIN books b ON b.id = c.book_id
    WHERE {where_sql}
    ORDER BY c.created_at DESC
    LIMIT %s
    """
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "chunk_id": row[0],
                "book_id": row[1],
                "book_title": row[2],
                "section_id": row[3],
                "chunk_title": row[4],
                "text_content": row[5],
            }
        )
    return out


def fetch_keyword_filter_stats(
    dsn: str,
    *,
    book_id: str | None,
    section_prefix: str | None = None,
    chunk_title_keyword: str | None = None,
) -> dict[str, Any] | None:
    if not chunk_title_keyword:
        return None
    where_clauses: list[str] = ["TRUE"]
    params: list[Any] = [f"%{chunk_title_keyword}%"]
    if book_id is not None:
        where_clauses.append("c.book_id = %s")
        params.append(uuid.UUID(book_id))
    if section_prefix:
        where_clauses.append("COALESCE(c.section_id, '') LIKE %s")
        params.append(f"{section_prefix}%")
    where_sql = " AND ".join(where_clauses)
    sql = f"""
    SELECT
      COUNT(*)::int AS total_candidates,
      COUNT(*) FILTER (WHERE COALESCE(c.title, '') ILIKE %s)::int AS matched_candidates
    FROM book_chunks c
    WHERE {where_sql}
    """
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            row = cur.fetchone()
    total_candidates = int(row[0]) if row else 0
    matched_candidates = int(row[1]) if row else 0
    hit_rate = round((matched_candidates / total_candidates), 4) if total_candidates > 0 else 0.0
    return {
        "total_candidates": total_candidates,
        "matched_candidates": matched_candidates,
        "hit_rate": hit_rate,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Export chunk granularity A/B samples (full section vs split-two)")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--book-id", default=None, help="Optional book UUID filter")
    parser.add_argument("--section-prefix", default=None, help="Optional section_id prefix filter")
    parser.add_argument("--chunk-title-keyword", default=None, help="Optional chunk title keyword filter")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--min-split-chars", type=int, default=120)
    parser.add_argument("--preview-top", type=int, default=30)
    parser.add_argument("--jsonl-output", default=None, help="Optional JSONL output path")
    parser.add_argument("--csv-output", default=None, help="Optional CSV output path")
    parser.add_argument("--markdown-output", default=None, help="Optional Markdown report output path")
    args = parser.parse_args()

    if args.limit <= 0:
        print("--limit must be > 0", file=sys.stderr)
        return 1
    if args.min_split_chars <= 0:
        print("--min-split-chars must be > 0", file=sys.stderr)
        return 1
    if args.preview_top < 0:
        print("--preview-top must be >= 0", file=sys.stderr)
        return 1

    dsn = args.database_url or os.getenv("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is required (or pass --database-url)", file=sys.stderr)
        return 1

    book_id_filter: str | None = None
    if args.book_id:
        try:
            book_id_filter = str(uuid.UUID(args.book_id))
        except Exception:
            print("invalid --book-id", file=sys.stderr)
            return 1

    section_prefix: str | None = None
    if args.section_prefix is not None:
        section_prefix = str(args.section_prefix).strip()
        if not section_prefix:
            section_prefix = None

    chunk_title_keyword: str | None = None
    if args.chunk_title_keyword is not None:
        chunk_title_keyword = str(args.chunk_title_keyword).strip()
        if not chunk_title_keyword:
            chunk_title_keyword = None

    chunks = fetch_chunks(
        dsn,
        book_id_filter,
        args.limit,
        section_prefix=section_prefix,
        chunk_title_keyword=chunk_title_keyword,
    )
    keyword_filter_stats = fetch_keyword_filter_stats(
        dsn,
        book_id=book_id_filter,
        section_prefix=section_prefix,
        chunk_title_keyword=chunk_title_keyword,
    )
    rows, summary = build_ab_rows(chunks, min_split_chars=args.min_split_chars)

    if args.jsonl_output:
        write_jsonl(Path(args.jsonl_output), rows)
    if args.csv_output:
        write_csv(Path(args.csv_output), rows, keyword_filter_stats=keyword_filter_stats)
    if args.markdown_output:
        markdown = build_markdown_report(
            book_id_filter=book_id_filter,
            section_prefix=section_prefix,
            chunk_title_keyword=chunk_title_keyword,
            keyword_filter_stats=keyword_filter_stats,
            limit=args.limit,
            min_split_chars=args.min_split_chars,
            summary=summary,
            rows=rows,
            preview_top=args.preview_top,
        )
        write_markdown(Path(args.markdown_output), markdown)

    payload = {
        "status": "ok",
        "book_id_filter": book_id_filter,
        "section_prefix": section_prefix,
        "chunk_title_keyword": chunk_title_keyword,
        "keyword_filter_stats": keyword_filter_stats,
        "limit": args.limit,
        "min_split_chars": args.min_split_chars,
        "summary": summary,
        "rows_count": len(rows),
        "jsonl_output": args.jsonl_output,
        "jsonl_schema_version": JSONL_SCHEMA_VERSION if args.jsonl_output else None,
        "csv_output": args.csv_output,
        "csv_schema_version": CSV_SCHEMA_VERSION if args.csv_output else None,
        "schema_version_consistency_note": (
            f"csv={CSV_SCHEMA_VERSION};jsonl={JSONL_SCHEMA_VERSION}"
            if (args.csv_output or args.jsonl_output)
            else "no_export"
        ),
        "markdown_output": args.markdown_output,
        "markdown_schema_version": MARKDOWN_SCHEMA_VERSION if args.markdown_output else None,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
