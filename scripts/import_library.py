#!/usr/bin/env python3
"""
Bulk import files from a local library directory into BookFlow.

Supported file types: pdf / epub / txt / md / json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover
    psycopg = None
    dict_row = None

SUPPORTED_SUFFIXES = {".pdf", ".epub", ".txt", ".md", ".markdown", ".json"}
BOOK_TYPES = {"general", "fiction", "technical"}

TECHNICAL_KEYWORDS = (
    "technical",
    "numerical",
    "analysis",
    "differential",
    "equation",
    "algorithm",
    "calculus",
    "algebra",
    "statistics",
    "machine learning",
    "deep learning",
    "computer",
    "programming",
    "engineering",
    "physics",
    "chemistry",
    "mathematics",
    "math",
    "理工",
    "数学",
    "算法",
    "编程",
    "工程",
    "物理",
    "化学",
    "统计",
    "机器学习",
    "深度学习",
)

FICTION_KEYWORDS = (
    "novel",
    "fiction",
    "story",
    "poem",
    "fantasy",
    "科幻",
    "小说",
    "故事",
    "诗",
)


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def derive_title_from_path(path: Path) -> str:
    """Best effort title extraction from filename."""
    name = _normalize_whitespace(path.stem.replace("_", " ").replace("-", " "))

    # Strip trailing parenthesized suffix if it looks like an author hint.
    # Example: "Book Name (A. Author)" -> "Book Name"
    m = re.search(r"\s*[（(]([^()（）]{1,80})[)）]\s*$", name)
    if m:
        tail = m.group(1).strip()
        token_count = len(re.findall(r"[A-Za-z\u4e00-\u9fff]+", tail))
        has_digit = bool(re.search(r"\d", tail))
        if token_count <= 8 and not has_digit:
            name = _normalize_whitespace(name[: m.start()])

    return name or path.stem


def infer_book_type_from_name(name: str, default_book_type: str = "general") -> str:
    lowered = _normalize_whitespace(name).lower()
    if any(keyword in lowered for keyword in TECHNICAL_KEYWORDS):
        return "technical"
    if any(keyword in lowered for keyword in FICTION_KEYWORDS):
        return "fiction"
    return default_book_type if default_book_type in BOOK_TYPES else "general"


def list_supported_files(input_dir: Path, recursive: bool) -> list[Path]:
    if recursive:
        candidates = [p for p in input_dir.rglob("*") if p.is_file()]
    else:
        candidates = [p for p in input_dir.iterdir() if p.is_file()]
    files = [p for p in candidates if p.suffix.lower() in SUPPORTED_SUFFIXES]
    files.sort(key=lambda p: p.as_posix().lower())
    return files


def build_import_command(
    *,
    repo_root: Path,
    file_path: Path,
    title: str,
    author: str | None,
    book_type: str,
    language: str,
    config: str,
    database_url: str | None,
    retry: int,
    retry_delay_sec: float,
    pdf_section_storage: str,
    dry_run: bool,
) -> list[str]:
    cmd = [
        sys.executable or "python3",
        "scripts/import_book.py",
        "--input",
        str(file_path),
        "--title",
        title,
        "--book-type",
        book_type,
        "--language",
        language,
        "--config",
        config,
        "--retry",
        str(max(0, int(retry))),
        "--retry-delay-sec",
        str(max(0.0, float(retry_delay_sec))),
        "--pdf-section-storage",
        str(pdf_section_storage),
    ]
    if author:
        cmd.extend(["--author", author])
    if database_url:
        cmd.extend(["--database-url", database_url])
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def _parse_import_stdout(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if not text:
        raise ValueError("import_book stdout is empty")
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid import_book stdout json: {exc}") from exc


def run_single_import(cmd: list[str], repo_root: Path) -> tuple[int, dict[str, Any] | None, str]:
    proc = subprocess.run(cmd, cwd=str(repo_root), capture_output=True, text=True)
    combined = (proc.stderr or "").strip() or (proc.stdout or "").strip()
    if proc.returncode != 0:
        return proc.returncode, None, combined
    try:
        payload = _parse_import_stdout(proc.stdout)
    except Exception as exc:  # pragma: no cover
        return 2, None, str(exc)
    return 0, payload, combined


def fetch_latest_books_by_source(
    *,
    database_url: str | None,
    source_paths: list[str],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not database_url or not source_paths or psycopg is None or dict_row is None:
        return out
    uniq_paths = sorted({str(x).strip() for x in source_paths if str(x).strip()})
    if not uniq_paths:
        return out
    try:
        with psycopg.connect(database_url, row_factory=dict_row, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH latest AS (
                      SELECT DISTINCT ON (source_path)
                        source_path,
                        id::text AS book_id,
                        title,
                        COALESCE(NULLIF(metadata->>'toc_review_status', ''), 'pending_review') AS toc_review_status,
                        NULLIF(metadata->>'toc_reviewed_at', '') AS toc_reviewed_at
                      FROM books
                      WHERE source_path = ANY(%s)
                      ORDER BY source_path, created_at DESC, id DESC
                    )
                    SELECT * FROM latest
                    """,
                    (uniq_paths,),
                )
                rows = cur.fetchall()
    except Exception:
        return out
    for row in rows:
        sp = str(row.get("source_path") or "").strip()
        if not sp:
            continue
        out[sp] = {
            "book_id": row.get("book_id"),
            "title": row.get("title"),
            "toc_review_status": str(row.get("toc_review_status") or "pending_review"),
            "toc_reviewed_at": row.get("toc_reviewed_at"),
        }
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk import local library files into BookFlow")
    parser.add_argument("--input-dir", required=True, help="Directory that contains book files")
    parser.add_argument("--recursive", action="store_true", help="Recursively scan subdirectories")
    parser.add_argument("--limit", type=int, default=0, help="Import at most N files (0 = all)")
    parser.add_argument("--book-type-strategy", choices=["auto", "fixed"], default="auto")
    parser.add_argument("--default-book-type", choices=["general", "fiction", "technical"], default="general")
    parser.add_argument("--fixed-book-type", choices=["general", "fiction", "technical"], default="technical")
    parser.add_argument("--language", default="zh")
    parser.add_argument("--author", default=None)
    parser.add_argument("--config", default="config/pipeline.json")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--retry", type=int, default=2)
    parser.add_argument("--retry-delay-sec", type=float, default=1.0)
    parser.add_argument("--pdf-section-storage", choices=["precut", "on_demand"], default="precut")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip files that already exist in books table by source_path (any review status)",
    )
    parser.add_argument(
        "--rescan-approved",
        action="store_true",
        help="Force re-import books even if source_path is already approved",
    )
    parser.add_argument("--json-output", default=None, help="Optional summary JSON output file")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    input_dir = Path(args.input_dir)
    database_url = args.database_url or os.getenv("DATABASE_URL")

    if not input_dir.exists() or not input_dir.is_dir():
        raise SystemExit(f"input directory not found: {input_dir}")
    if not args.dry_run and not database_url:
        raise SystemExit("DATABASE_URL is required (or pass --database-url), unless --dry-run")

    files = list_supported_files(input_dir, recursive=bool(args.recursive))
    if args.limit and args.limit > 0:
        files = files[: args.limit]
    if not files:
        raise SystemExit(f"no supported files in: {input_dir}")

    results: list[dict[str, Any]] = []
    success = 0
    failed = 0
    skipped = 0

    file_source_paths = [str(p.resolve()) for p in files]
    existing_by_source = fetch_latest_books_by_source(database_url=database_url, source_paths=file_source_paths)
    skip_approved = not bool(args.rescan_approved)

    for idx, file_path in enumerate(files, start=1):
        title = derive_title_from_path(file_path)
        source_path = str(file_path.resolve())

        existing = existing_by_source.get(source_path)
        if bool(args.skip_existing) and isinstance(existing, dict):
            skipped += 1
            existing_review = str(existing.get("toc_review_status") or "pending_review").strip().lower()
            print(f"[{idx}/{len(files)}] skipping existing: {file_path.name}", file=sys.stderr)
            results.append(
                {
                    "status": "skipped",
                    "reason": "already_exists",
                    "path": source_path,
                    "title": title,
                    "existing_book_id": existing.get("book_id"),
                    "existing_review_status": existing_review,
                    "existing_reviewed_at": existing.get("toc_reviewed_at"),
                }
            )
            continue

        if skip_approved and isinstance(existing, dict):
            existing_review = str(existing.get("toc_review_status") or "pending_review").strip().lower()
            if existing_review == "approved":
                skipped += 1
                print(f"[{idx}/{len(files)}] skipping approved: {file_path.name}", file=sys.stderr)
                results.append(
                    {
                        "status": "skipped",
                        "reason": "already_approved",
                        "path": source_path,
                        "title": title,
                        "existing_book_id": existing.get("book_id"),
                        "existing_review_status": existing_review,
                        "existing_reviewed_at": existing.get("toc_reviewed_at"),
                    }
                )
                continue

        if args.book_type_strategy == "fixed":
            book_type = args.fixed_book_type
        else:
            book_type = infer_book_type_from_name(file_path.stem, default_book_type=args.default_book_type)

        cmd = build_import_command(
            repo_root=repo_root,
            file_path=file_path,
            title=title,
            author=args.author,
            book_type=book_type,
            language=args.language,
            config=args.config,
            database_url=database_url,
            retry=args.retry,
            retry_delay_sec=args.retry_delay_sec,
            pdf_section_storage=args.pdf_section_storage,
            dry_run=bool(args.dry_run),
        )

        print(f"[{idx}/{len(files)}] importing: {file_path.name} (book_type={book_type})", file=sys.stderr)
        code, payload, error_text = run_single_import(cmd, repo_root)

        if code == 0 and payload is not None:
            success += 1
            results.append(
                {
                    "status": "ok",
                    "path": str(file_path.resolve()),
                    "title": title,
                    "book_type": book_type,
                    "book_id": payload.get("book_id"),
                    "chunks_upserted": payload.get("chunks_upserted", payload.get("chunk_count", 0)),
                }
            )
            continue

        failed += 1
        results.append(
            {
                "status": "error",
                "path": str(file_path.resolve()),
                "title": title,
                "book_type": book_type,
                "error": error_text,
            }
        )
        if args.fail_fast:
            break

    summary = {
        "status": "ok" if failed == 0 else ("partial" if success > 0 else "error"),
        "input_dir": str(input_dir.resolve()),
        "recursive": bool(args.recursive),
        "dry_run": bool(args.dry_run),
        "book_type_strategy": args.book_type_strategy,
        "default_book_type": args.default_book_type,
        "fixed_book_type": args.fixed_book_type,
        "language": args.language,
        "pdf_section_storage": args.pdf_section_storage,
        "skip_existing": bool(args.skip_existing),
        "rescan_approved": bool(args.rescan_approved),
        "total_files": len(files),
        "success_count": success,
        "failure_count": failed,
        "skipped_count": skipped,
        "results": results,
    }

    if args.json_output:
        out = Path(args.json_output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
