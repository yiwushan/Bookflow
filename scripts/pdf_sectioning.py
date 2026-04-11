#!/usr/bin/env python3
"""
PDF section materialization helpers for BookFlow v0.

Responsibilities:
- Parse PDF outline/bookmarks into TOC-like entries
- Normalize TOC entries and pick leaf sections
- Pre-generate per-section PDF files
- Upsert books/chunks into Postgres for PDF-section reading flow
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any
import uuid

try:
    import psycopg
    from psycopg.types.json import Json
except Exception:  # pragma: no cover
    psycopg = None
    Json = None

try:
    from pypdf import PdfReader, PdfWriter
except Exception:  # pragma: no cover
    PdfReader = None
    PdfWriter = None


TOC_SCHEMA_VERSION = "bookflow.manual_toc.v1"
PDF_SECTION_CONTENT_VERSION = "pdf_section_v0"
DEFAULT_DERIVED_ROOT = Path(os.getenv("BOOKFLOW_DERIVED_ROOT", "data/books/derived"))
DEFAULT_LONG_SECTION_PAGE_THRESHOLD = int(os.getenv("BOOKFLOW_LONG_SECTION_PAGE_THRESHOLD", "35"))
DEFAULT_PDF_SECTION_STORAGE = str(os.getenv("BOOKFLOW_PDF_SECTION_STORAGE", "precut") or "precut").strip().lower()


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_int(raw: Any, default: int | None = None) -> int | None:
    try:
        return int(raw)
    except Exception:
        return default


def _safe_level(raw: Any, default: int = 1) -> int:
    value = _safe_int(raw, default)
    if value is None:
        return max(1, int(default))
    return max(1, int(value))


def _stable_chunk_uuid(book_id: str, title: str, start_page: int, end_page: int, ordinal: int) -> str:
    key = f"bookflow:pdf-section:{book_id}:{ordinal}:{start_page}:{end_page}:{title}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, key))


def _section_id(ordinal: int) -> str:
    return f"sec_{int(ordinal):04d}"


def _teaser(title: str, start_page: int, end_page: int) -> str:
    return f"{title}（P{start_page}-{end_page}）"


def _content_placeholder(title: str, start_page: int, end_page: int) -> str:
    return (
        f"[PDF章节原文] {title}\n"
        f"页码范围：{start_page}-{end_page}\n"
        "请在阅读器中打开章节 PDF 原文。"
    )


def _estimate_read_sec(page_start: int, page_end: int) -> int:
    page_count = max(1, int(page_end) - int(page_start) + 1)
    return max(45, min(3600, page_count * 90))


def load_manual_toc_entries(toc_store_path: Path, book_id: str) -> list[dict[str, Any]]:
    if not toc_store_path.exists():
        return []
    try:
        payload = json.loads(toc_store_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    annotations = payload.get("annotations")
    if not isinstance(annotations, dict):
        return []
    annotation = annotations.get(str(book_id))
    if not isinstance(annotation, dict):
        return []
    entries = annotation.get("entries")
    if not isinstance(entries, list):
        return []
    out: list[dict[str, Any]] = []
    for item in entries:
        if isinstance(item, dict):
            out.append(dict(item))
    return out


def normalize_toc_entries(entries: list[dict[str, Any]], total_pages: int | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    normalized: list[dict[str, Any]] = []
    for idx, raw in enumerate(entries, start=1):
        if not isinstance(raw, dict):
            warnings.append(f"entry#{idx} 非对象，已跳过")
            continue
        title = str(raw.get("title") or "").strip()
        if not title:
            warnings.append(f"entry#{idx} 缺少 title，已跳过")
            continue
        start_page = _safe_int(raw.get("start_page"), None)
        if start_page is None or start_page <= 0:
            warnings.append(f"entry#{idx} start_page 无效，已跳过")
            continue
        level = _safe_level(raw.get("level"), 1)
        end_page = _safe_int(raw.get("end_page"), None)
        normalized.append(
            {
                "toc_index": idx,
                "title": title,
                "level": level,
                "start_page": int(start_page),
                "end_page": int(end_page) if end_page is not None else None,
            }
        )

    for idx, item in enumerate(normalized):
        next_start = normalized[idx + 1]["start_page"] if idx + 1 < len(normalized) else None
        start_page = int(item["start_page"])
        end_page = _safe_int(item.get("end_page"), None)

        if end_page is None or end_page < start_page:
            if next_start is not None and int(next_start) > start_page:
                end_page = int(next_start) - 1
            else:
                end_page = start_page

        if next_start is not None and int(next_start) <= start_page:
            warnings.append(
                f"目录页码未递增: toc_index={item['toc_index']} start_page={start_page} next_start={int(next_start)}"
            )

        if total_pages is not None and total_pages > 0:
            if start_page > int(total_pages):
                warnings.append(
                    f"目录起始页超范围: toc_index={item['toc_index']} start_page={start_page} total_pages={int(total_pages)}"
                )
            end_page = min(int(end_page), int(total_pages))

        item["end_page"] = max(start_page, int(end_page))

    return normalized, warnings


def pick_leaf_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not entries:
        return []
    out: list[dict[str, Any]] = []
    for idx, entry in enumerate(entries):
        next_level = int(entries[idx + 1]["level"]) if idx + 1 < len(entries) else 0
        current_level = int(entry.get("level") or 1)
        if idx + 1 >= len(entries) or next_level <= current_level:
            out.append(dict(entry))
    return out


def extract_pdf_outline_entries(pdf_path: Path) -> tuple[list[dict[str, Any]], list[str], int]:
    if PdfReader is None:
        raise RuntimeError("pypdf is required for PDF section materialization")
    reader = PdfReader(str(pdf_path))
    total_pages = int(len(reader.pages))
    warnings: list[str] = []
    outline: Any
    if hasattr(reader, "outline"):
        outline = reader.outline
    elif hasattr(reader, "outlines"):
        outline = reader.outlines
    else:
        outline = []

    raw_entries: list[dict[str, Any]] = []

    def _title_from_node(node: Any) -> str:
        title = getattr(node, "title", None)
        if title:
            return str(title).strip()
        if isinstance(node, dict):
            maybe = node.get("/Title") or node.get("title")
            if maybe:
                return str(maybe).strip()
        return ""

    def _page_from_node(node: Any) -> int | None:
        try:
            page_idx = reader.get_destination_page_number(node)
            if page_idx is None:
                return None
            return int(page_idx) + 1
        except Exception:
            pass
        page = getattr(node, "page", None)
        if page is None:
            return None
        try:
            page_idx = reader.pages.index(page)
            return int(page_idx) + 1
        except Exception:
            return None

    def _walk(nodes: Any, level: int) -> None:
        if not isinstance(nodes, list):
            return
        for node in nodes:
            if isinstance(node, list):
                _walk(node, level + 1)
                continue
            title = _title_from_node(node)
            page_num = _page_from_node(node)
            if not title or page_num is None:
                continue
            raw_entries.append(
                {
                    "title": title,
                    "level": max(1, int(level)),
                    "start_page": int(page_num),
                    "end_page": None,
                }
            )

    _walk(outline if isinstance(outline, list) else [], 1)

    dedup: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_entries:
        key = f"{item.get('title')}|{item.get('level')}|{item.get('start_page')}"
        if key in seen:
            continue
        seen.add(key)
        dedup.append(item)

    if not dedup:
        warnings.append("PDF 未解析到可用 Outline/Bookmarks")

    normalized, normalize_warnings = normalize_toc_entries(dedup, total_pages=total_pages)
    warnings.extend(normalize_warnings)
    return normalized, warnings, total_pages


def materialize_pdf_sections(
    *,
    pdf_path: Path,
    book_id: str,
    toc_entries: list[dict[str, Any]],
    toc_source: str,
    derived_root: Path | None = None,
    long_section_page_threshold: int | None = None,
    persist_section_pdf: bool | None = None,
) -> dict[str, Any]:
    if PdfReader is None or PdfWriter is None:
        raise RuntimeError("pypdf is required for PDF section materialization")

    reader = PdfReader(str(pdf_path))
    total_pages = int(len(reader.pages))
    threshold = int(long_section_page_threshold or DEFAULT_LONG_SECTION_PAGE_THRESHOLD)
    persist_mode = (
        bool(persist_section_pdf)
        if persist_section_pdf is not None
        else DEFAULT_PDF_SECTION_STORAGE != "on_demand"
    )
    output_root = (derived_root or DEFAULT_DERIVED_ROOT) / str(book_id)
    if persist_mode:
        output_root.mkdir(parents=True, exist_ok=True)

    normalized, warnings = normalize_toc_entries(toc_entries, total_pages=total_pages)
    leaves = pick_leaf_entries(normalized)

    chunk_records: list[dict[str, Any]] = []
    failed_entries: list[dict[str, Any]] = []
    generated_pdf_count = 0
    long_section_count = 0
    previous_chunk_uuid: str | None = None

    for ordinal, entry in enumerate(leaves, start=1):
        title = str(entry.get("title") or f"Section {ordinal}").strip() or f"Section {ordinal}"
        level = _safe_level(entry.get("level"), 1)
        start_page = int(entry.get("start_page") or 0)
        end_page = int(entry.get("end_page") or start_page)

        if start_page <= 0 or start_page > total_pages:
            failed_entries.append(
                {
                    "toc_index": entry.get("toc_index"),
                    "title": title,
                    "start_page": start_page,
                    "end_page": end_page,
                    "reason": "start_page_out_of_range",
                }
            )
            continue

        end_page = max(start_page, min(end_page, total_pages))

        chunk_uuid = _stable_chunk_uuid(
            book_id=str(book_id),
            title=title,
            start_page=start_page,
            end_page=end_page,
            ordinal=ordinal,
        )
        rel_path: str | None = None
        if persist_mode:
            out_path = output_root / f"{chunk_uuid}.pdf"
            writer = PdfWriter()
            for page_idx in range(start_page - 1, end_page):
                try:
                    writer.add_page(reader.pages[page_idx])
                except Exception:
                    continue
            with out_path.open("wb") as f:
                writer.write(f)
            generated_pdf_count += 1
            rel_path = (Path("data/books/derived") / str(book_id) / f"{chunk_uuid}.pdf").as_posix()
        page_count = max(1, end_page - start_page + 1)
        is_long_section = page_count > threshold
        if is_long_section:
            long_section_count += 1
            warnings.append(
                f"long_section_warning: title={title} pages={page_count} range={start_page}-{end_page} threshold={threshold}"
            )

        source_anchor = {
            "page_start": int(start_page),
            "page_end": int(end_page),
            "bbox_union": [0, 0, 1, 1],
        }
        metadata = {
            "content_type": "pdf_section",
            "section_pdf_relpath": rel_path,
            "section_pdf_url": f"/v1/chunk_pdf?book_id={book_id}&chunk_id={chunk_uuid}",
            "toc_source": str(toc_source),
            "toc_level": int(level),
            "long_section_warning": bool(is_long_section),
            "materialized_at": _now_iso_utc(),
            "materializer_version": "pdf_section_v0",
            "pdf_section_storage_mode": "precut" if persist_mode else "on_demand",
        }

        prereq_ids = [previous_chunk_uuid] if previous_chunk_uuid else []
        chunk_records.append(
            {
                "chunk_id": chunk_uuid,
                "section_id": _section_id(ordinal),
                "chunk_index_in_section": 1,
                "global_index": int(ordinal),
                "title": title,
                "text": _content_placeholder(title, start_page, end_page),
                "teaser_text": _teaser(title, start_page, end_page),
                "render_mode": "crop",
                "render_reason": ["pdf_section"],
                "source_anchor": source_anchor,
                "read_time_sec_est": _estimate_read_sec(start_page, end_page),
                "has_formula": False,
                "has_code": False,
                "has_table": False,
                "quality_score": 0.9,
                "prerequisite_chunk_ids": prereq_ids,
                "metadata": metadata,
            }
        )
        previous_chunk_uuid = chunk_uuid

    return {
        "total_pages": total_pages,
        "toc_entry_count": len(normalized),
        "toc_leaf_count": len(leaves),
        "materialized_chunks": len(chunk_records),
        "generated_pdf_count": int(generated_pdf_count),
        "long_section_warning_count": int(long_section_count),
        "failed_entries": failed_entries,
        "warnings": warnings,
        "chunk_records": chunk_records,
    }


def _base_book_metadata_patch(
    *,
    toc_source: str,
    needs_manual_toc: bool,
    chunk_count: int,
    manual_toc_entries: list[dict[str, Any]] | None = None,
    extra_metadata: dict[str, Any] | None = None,
    toc_review_status: str | None = "pending_review",
    review_required: bool | None = None,
    toc_reviewed_at: str | None = None,
) -> dict[str, Any]:
    patch: dict[str, Any] = {
        "import_source": "import_book.py",
        "toc_source": str(toc_source),
        "needs_manual_toc": bool(needs_manual_toc),
        "materialization_status": "pending_manual_toc" if needs_manual_toc else "materialized",
        "materialized_chunk_count": int(chunk_count),
        "materialized_at": _now_iso_utc() if chunk_count > 0 else None,
    }
    status = str(toc_review_status or "").strip().lower()
    if status:
        if status not in {"pending_review", "approved", "rejected"}:
            status = "pending_review"
        patch["toc_review_status"] = status
        if review_required is None:
            patch["review_required"] = status != "approved"
        else:
            patch["review_required"] = bool(review_required)
        reviewed_at = str(toc_reviewed_at or "").strip()
        if status == "approved" and reviewed_at:
            patch["toc_reviewed_at"] = reviewed_at
    elif review_required is not None:
        patch["review_required"] = bool(review_required)
    if manual_toc_entries is not None:
        patch.update(
            {
                "manual_toc_schema_version": TOC_SCHEMA_VERSION,
                "manual_toc_updated_at": _now_iso_utc(),
                "manual_toc_entry_count": int(len(manual_toc_entries)),
                "manual_toc": manual_toc_entries,
            }
        )
    if isinstance(extra_metadata, dict):
        patch.update(extra_metadata)
    return patch


def upsert_book_and_pdf_chunks(
    *,
    dsn: str,
    book_id: str,
    title: str,
    author: str | None,
    language: str,
    book_type: str,
    source_path: str,
    total_pages: int | None,
    source_format: str,
    toc_source: str,
    chunk_records: list[dict[str, Any]],
    replace_existing_chunks: bool = True,
    needs_manual_toc: bool = False,
    manual_toc_entries: list[dict[str, Any]] | None = None,
    extra_metadata: dict[str, Any] | None = None,
    processing_status: str = "ready",
    toc_review_status: str | None = "pending_review",
    review_required: bool | None = None,
    toc_reviewed_at: str | None = None,
) -> int:
    if psycopg is None or Json is None:
        raise RuntimeError("psycopg is required for DB materialization")

    metadata_patch = _base_book_metadata_patch(
        toc_source=toc_source,
        needs_manual_toc=needs_manual_toc,
        chunk_count=len(chunk_records),
        manual_toc_entries=manual_toc_entries,
        extra_metadata=extra_metadata,
        toc_review_status=toc_review_status,
        review_required=review_required,
        toc_reviewed_at=toc_reviewed_at,
    )

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO books (
                  id, title, author, language, book_type, source_format, source_path,
                  processing_status, total_pages, total_sections, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  title = EXCLUDED.title,
                  author = EXCLUDED.author,
                  language = EXCLUDED.language,
                  book_type = EXCLUDED.book_type,
                  source_format = EXCLUDED.source_format,
                  source_path = EXCLUDED.source_path,
                  processing_status = EXCLUDED.processing_status,
                  total_pages = COALESCE(EXCLUDED.total_pages, books.total_pages),
                  total_sections = EXCLUDED.total_sections,
                  metadata = COALESCE(books.metadata, '{}'::jsonb) || EXCLUDED.metadata,
                  updated_at = NOW()
                """,
                (
                    str(book_id),
                    title,
                    author,
                    language,
                    book_type,
                    source_format,
                    source_path,
                    processing_status,
                    int(total_pages) if total_pages is not None else None,
                    int(len(chunk_records)),
                    Json(metadata_patch),
                ),
            )

            if replace_existing_chunks:
                cur.execute("DELETE FROM book_chunks WHERE book_id = %s::uuid", (str(book_id),))

            for chunk in chunk_records:
                prereq_values: list[uuid.UUID] = []
                for raw in chunk.get("prerequisite_chunk_ids", []):
                    try:
                        prereq_values.append(uuid.UUID(str(raw)))
                    except Exception:
                        continue
                metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
                chunk_meta = {
                    "import_source": "import_book.py",
                    "source_chunk_id": chunk.get("chunk_id"),
                    **metadata,
                }
                cur.execute(
                    """
                    INSERT INTO book_chunks (
                      id, book_id, section_id, chunk_index_in_section, global_index,
                      title, text_content, teaser_text, content_version,
                      render_mode, render_reason, source_anchor, read_time_sec_est,
                      has_formula, has_code, has_table, quality_score,
                      prerequisite_chunk_ids, metadata
                    ) VALUES (
                      %s, %s, %s, %s, %s,
                      %s, %s, %s, %s,
                      %s, %s, %s, %s,
                      %s, %s, %s, %s,
                      %s, %s
                    )
                    ON CONFLICT (id) DO UPDATE SET
                      section_id = EXCLUDED.section_id,
                      chunk_index_in_section = EXCLUDED.chunk_index_in_section,
                      global_index = EXCLUDED.global_index,
                      title = EXCLUDED.title,
                      text_content = EXCLUDED.text_content,
                      teaser_text = EXCLUDED.teaser_text,
                      content_version = EXCLUDED.content_version,
                      render_mode = EXCLUDED.render_mode,
                      render_reason = EXCLUDED.render_reason,
                      source_anchor = EXCLUDED.source_anchor,
                      read_time_sec_est = EXCLUDED.read_time_sec_est,
                      has_formula = EXCLUDED.has_formula,
                      has_code = EXCLUDED.has_code,
                      has_table = EXCLUDED.has_table,
                      quality_score = EXCLUDED.quality_score,
                      prerequisite_chunk_ids = EXCLUDED.prerequisite_chunk_ids,
                      metadata = EXCLUDED.metadata,
                      updated_at = NOW()
                    """,
                    (
                        str(chunk.get("chunk_id")),
                        str(book_id),
                        str(chunk.get("section_id") or "sec_0001"),
                        int(chunk.get("chunk_index_in_section") or 1),
                        int(chunk.get("global_index") or 1),
                        str(chunk.get("title") or "Untitled Section"),
                        str(chunk.get("text") or ""),
                        str(chunk.get("teaser_text") or ""),
                        PDF_SECTION_CONTENT_VERSION,
                        str(chunk.get("render_mode") or "crop"),
                        list(chunk.get("render_reason") or ["pdf_section"]),
                        Json(chunk.get("source_anchor") or {}),
                        int(chunk.get("read_time_sec_est") or 0),
                        bool(chunk.get("has_formula", False)),
                        bool(chunk.get("has_code", False)),
                        bool(chunk.get("has_table", False)),
                        float(chunk.get("quality_score", 0.9)),
                        prereq_values,
                        Json(chunk_meta),
                    ),
                )
    return len(chunk_records)


def rank_toc_source(entries_from_outline: list[dict[str, Any]], entries_from_manual: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    if entries_from_outline:
        return "pdf_outline", entries_from_outline
    if entries_from_manual:
        return "manual_toc", entries_from_manual
    return "pending_manual_toc", []


def build_materialization_fingerprint(chunk_records: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for chunk in chunk_records:
        digest.update(str(chunk.get("chunk_id")).encode("utf-8"))
        digest.update(str(chunk.get("section_id")).encode("utf-8"))
        anchor = chunk.get("source_anchor") or {}
        digest.update(str(anchor.get("page_start")).encode("utf-8"))
        digest.update(str(anchor.get("page_end")).encode("utf-8"))
    return digest.hexdigest()[:16]
