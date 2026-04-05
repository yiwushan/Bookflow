#!/usr/bin/env python3
"""
Book import CLI:
file -> clean -> chunk -> insert to Postgres
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any
import zipfile
import xml.etree.ElementTree as ET

import psycopg
from psycopg.types.json import Json
try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None
try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover
    BeautifulSoup = None

try:
    from pipeline import load_config_for_book_type, run_pipeline
except ModuleNotFoundError:  # pragma: no cover
    from scripts.pipeline import load_config_for_book_type, run_pipeline

try:
    from pdf_sectioning import (
        build_materialization_fingerprint,
        extract_pdf_outline_entries,
        materialize_pdf_sections,
        rank_toc_source,
        upsert_book_and_pdf_chunks,
    )
except ModuleNotFoundError:  # pragma: no cover
    from scripts.pdf_sectioning import (
        build_materialization_fingerprint,
        extract_pdf_outline_entries,
        materialize_pdf_sections,
        rank_toc_source,
        upsert_book_and_pdf_chunks,
    )


MANUAL_TOC_STORE_PATH = Path(os.getenv("BOOKFLOW_TOC_STORE_PATH", "data/toc/manual_annotations.json"))
TOC_NORMALIZED_DIR = Path(os.getenv("BOOKFLOW_TOC_NORMALIZED_DIR", "data/toc/normalized"))
DEFAULT_PDF_SECTION_STORAGE = str(os.getenv("BOOKFLOW_PDF_SECTION_STORAGE", "precut") or "precut").strip().lower()
if DEFAULT_PDF_SECTION_STORAGE not in {"precut", "on_demand"}:
    DEFAULT_PDF_SECTION_STORAGE = "precut"


def _safe_int(raw: Any, default: int | None = None) -> int | None:
    try:
        return int(raw)
    except Exception:
        return default


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_source_path(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        p = Path(text)
        p = p.resolve() if p.is_absolute() else (Path.cwd() / p).resolve()
        return p.as_posix()
    except Exception:
        return text


def compute_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def read_toc_store() -> dict[str, Any]:
    if not MANUAL_TOC_STORE_PATH.exists():
        return {
            "schema_version": "bookflow.manual_toc.v1",
            "updated_at": now_iso(),
            "annotations": {},
            "fingerprint_annotations": {},
            "source_path_fingerprints": {},
        }
    try:
        payload = json.loads(MANUAL_TOC_STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {
            "schema_version": "bookflow.manual_toc.v1",
            "updated_at": now_iso(),
            "annotations": {},
            "fingerprint_annotations": {},
            "source_path_fingerprints": {},
        }
    return {
        "schema_version": "bookflow.manual_toc.v1",
        "updated_at": str(payload.get("updated_at") or now_iso()),
        "annotations": payload.get("annotations") if isinstance(payload.get("annotations"), dict) else {},
        "fingerprint_annotations": payload.get("fingerprint_annotations")
        if isinstance(payload.get("fingerprint_annotations"), dict)
        else {},
        "source_path_fingerprints": payload.get("source_path_fingerprints")
        if isinstance(payload.get("source_path_fingerprints"), dict)
        else {},
    }


def write_toc_store(payload: dict[str, Any]) -> None:
    MANUAL_TOC_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized = {
        "schema_version": "bookflow.manual_toc.v1",
        "updated_at": now_iso(),
        "annotations": payload.get("annotations", {}),
        "fingerprint_annotations": payload.get("fingerprint_annotations", {}),
        "source_path_fingerprints": payload.get("source_path_fingerprints", {}),
    }
    MANUAL_TOC_STORE_PATH.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")


def persist_normalized_toc_file(annotation: dict[str, Any]) -> str:
    TOC_NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    key = str(annotation.get("book_fingerprint") or annotation.get("book_id") or "unknown").strip() or "unknown"
    path = (TOC_NORMALIZED_DIR / f"{key}.json").resolve()
    path.write_text(json.dumps(annotation, ensure_ascii=False, indent=2), encoding="utf-8")
    return path.as_posix()


def normalize_toc_entries_for_store(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or "").strip()
        if not title:
            continue
        start_page = _safe_int(raw.get("start_page"), None)
        if start_page is None or start_page <= 0:
            continue
        end_page = _safe_int(raw.get("end_page"), start_page) or start_page
        if end_page < start_page:
            end_page = start_page
        level = _safe_int(raw.get("level"), 1) or 1
        out.append(
            {
                "title": title,
                "level": max(1, int(level)),
                "start_page": int(start_page),
                "end_page": int(end_page),
            }
        )
    return out


def find_manual_toc_entries(
    *,
    book_id: str,
    source_path: str,
    book_fingerprint: str,
) -> list[dict[str, Any]]:
    store = read_toc_store()
    annotations = store.get("annotations") if isinstance(store.get("annotations"), dict) else {}
    if isinstance(annotations.get(book_id), dict):
        return list((annotations.get(book_id) or {}).get("entries") or [])

    fp = str(book_fingerprint or "").strip().lower()
    fp_map = store.get("fingerprint_annotations") if isinstance(store.get("fingerprint_annotations"), dict) else {}
    if fp and isinstance(fp_map.get(fp), dict):
        return list((fp_map.get(fp) or {}).get("entries") or [])

    source_key = normalize_source_path(source_path)
    source_fp_map = store.get("source_path_fingerprints") if isinstance(store.get("source_path_fingerprints"), dict) else {}
    mapped_fp = str(source_fp_map.get(source_key) or "").strip().lower() if source_key else ""
    if mapped_fp and isinstance(fp_map.get(mapped_fp), dict):
        return list((fp_map.get(mapped_fp) or {}).get("entries") or [])

    if source_key and isinstance(annotations, dict):
        for ann in annotations.values():
            if not isinstance(ann, dict):
                continue
            if normalize_source_path(ann.get("source_path")) == source_key:
                return list((ann or {}).get("entries") or [])

    return []


def upsert_toc_annotation_for_import(
    *,
    book_id: str,
    source_path: str,
    book_fingerprint: str,
    toc_source: str,
    entries: list[dict[str, Any]],
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    normalized = normalize_toc_entries_for_store(entries)
    annotation = {
        "schema_version": "bookflow.manual_toc.v1",
        "book_id": str(book_id),
        "source": "pdf_outline_auto" if toc_source == "pdf_outline" else "import_manual_toc",
        "toc_source": str(toc_source),
        "entry_count": len(normalized),
        "updated_at": now_iso(),
        "page_offset": 0,
        "entries": normalized,
        "warnings": list(warnings or []),
        "source_path": normalize_source_path(source_path),
        "book_fingerprint": str(book_fingerprint or "").strip().lower(),
    }
    annotation["normalized_file"] = persist_normalized_toc_file(annotation)

    store = read_toc_store()
    annotations = store.get("annotations") if isinstance(store.get("annotations"), dict) else {}
    fp_map = store.get("fingerprint_annotations") if isinstance(store.get("fingerprint_annotations"), dict) else {}
    source_fp = store.get("source_path_fingerprints") if isinstance(store.get("source_path_fingerprints"), dict) else {}

    annotations[str(book_id)] = annotation
    fp = str(annotation.get("book_fingerprint") or "").strip().lower()
    sp = str(annotation.get("source_path") or "").strip()
    if fp:
        fp_map[fp] = annotation
    if fp and sp:
        source_fp[sp] = fp

    store["annotations"] = annotations
    store["fingerprint_annotations"] = fp_map
    store["source_path_fingerprints"] = source_fp
    write_toc_store(store)
    return annotation


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\x00", "")
    # Drop non-printable control chars that commonly appear in PDF extraction noise.
    text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


EPUB_NOISE_HINTS = (
    "toc",
    "tableofcontents",
    "table-of-contents",
    "contents",
    "navigation",
    "nav",
    "copyright",
)
DEFAULT_EPUB_SECTION_DOC_SAMPLE_LIMIT = 5
DEFAULT_EPUB_BASENAME_TOPK_MIN_COUNT = 1
DEFAULT_EPUB_BASENAME_TOPK_LIMIT = 5
DEFAULT_EPUB_BASENAME_TOPK_COVERAGE_RATIO_PRECISION = 4


def _prune_epub_noise(soup: Any) -> None:
    for tag in soup(["script", "style", "nav", "aside", "footer"]):
        tag.decompose()

    for tag in soup.find_all(True):
        attrs = [
            str(tag.get("id", "")),
            " ".join(tag.get("class", []) if isinstance(tag.get("class"), list) else [tag.get("class", "")]),
            str(tag.get("role", "")),
            str(tag.get("epub:type", "")),
            str(tag.get("type", "")),
        ]
        attr_text = " ".join(attrs).lower().replace(" ", "")
        if not attr_text:
            continue
        if any(hint in attr_text for hint in EPUB_NOISE_HINTS):
            tag.decompose()


def _looks_like_toc_text(text: str) -> bool:
    lines = [x.strip() for x in text.split("\n") if x.strip()]
    if not lines:
        return False
    header = " ".join(lines[:8]).lower()
    if "table of contents" in header or "contents" == header or "目录" in header:
        return True
    if len(lines) <= 14:
        dotted_lines = sum(1 for line in lines if re.search(r"\.{2,}\s*\d+$", line))
        if dotted_lines >= max(2, len(lines) // 3):
            return True
    return False


def extract_text_from_pdf(path: Path) -> str:
    if PdfReader is None:
        raise RuntimeError("pypdf is required for PDF import")
    reader = PdfReader(str(path))
    page_texts: list[str] = []
    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        page_texts.append(text)
    if not page_texts:
        raise ValueError("no extractable text in pdf")
    return normalize_text("\n\n".join(page_texts))


def _decode_bytes(raw: bytes) -> str:
    for enc in ("utf-8", "utf-16", "utf-16le", "utf-16be", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="ignore")


def _parse_epub_spine_order(zipf: zipfile.ZipFile) -> list[str]:
    try:
        container_xml = zipf.read("META-INF/container.xml")
        container_root = ET.fromstring(container_xml)
        ns_c = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
        rootfile = container_root.find(".//c:rootfile", ns_c)
        if rootfile is None:
            return []
        opf_path = str(rootfile.attrib.get("full-path", "")).strip()
        if not opf_path:
            return []
        opf_bytes = zipf.read(opf_path)
        opf_root = ET.fromstring(opf_bytes)
        ns_o = {"opf": "http://www.idpf.org/2007/opf"}
        manifest = {}
        for item in opf_root.findall(".//opf:manifest/opf:item", ns_o):
            item_id = str(item.attrib.get("id", "")).strip()
            href = str(item.attrib.get("href", "")).strip()
            if not item_id or not href:
                continue
            base = str(Path(opf_path).parent)
            normalized = str((Path(base) / href).as_posix()) if base not in {"", "."} else href
            manifest[item_id] = normalized
        order: list[str] = []
        for itemref in opf_root.findall(".//opf:spine/opf:itemref", ns_o):
            ref = str(itemref.attrib.get("idref", "")).strip()
            target = manifest.get(ref)
            if target:
                order.append(target)
        return order
    except Exception:
        return []


def _normalize_epub_sample_limit(sample_limit: int | None) -> int:
    if sample_limit is None:
        return DEFAULT_EPUB_SECTION_DOC_SAMPLE_LIMIT
    try:
        value = int(sample_limit)
    except Exception:
        return DEFAULT_EPUB_SECTION_DOC_SAMPLE_LIMIT
    return min(50, max(1, value))


def _normalize_epub_topk_min_count(min_count: int | None) -> int:
    if min_count is None:
        return DEFAULT_EPUB_BASENAME_TOPK_MIN_COUNT
    try:
        value = int(min_count)
    except Exception:
        return DEFAULT_EPUB_BASENAME_TOPK_MIN_COUNT
    return max(1, value)


def _normalize_epub_topk_limit(topk_limit: int | None) -> int:
    if topk_limit is None:
        return DEFAULT_EPUB_BASENAME_TOPK_LIMIT
    try:
        value = int(topk_limit)
    except Exception:
        return DEFAULT_EPUB_BASENAME_TOPK_LIMIT
    return min(20, max(1, value))


def _normalize_epub_topk_coverage_ratio_precision(precision: int | None) -> int:
    if precision is None:
        return DEFAULT_EPUB_BASENAME_TOPK_COVERAGE_RATIO_PRECISION
    try:
        value = int(precision)
    except Exception:
        return DEFAULT_EPUB_BASENAME_TOPK_COVERAGE_RATIO_PRECISION
    return min(6, max(0, value))


def _basename_samples(items: list[str]) -> list[str]:
    return [Path(x).name for x in items]


def _unique_count(items: list[str]) -> int:
    return len(set(items))


def _topk_counts(items: list[str], topk: int = 5, min_count: int = 1) -> list[dict[str, Any]]:
    counter: dict[str, int] = {}
    for item in items:
        counter[item] = counter.get(item, 0) + 1
    threshold = max(1, int(min_count))
    rows = [{"basename": key, "count": value} for key, value in counter.items() if int(value) >= threshold]
    rows.sort(key=lambda x: (-int(x["count"]), str(x["basename"])))
    return rows[:max(1, int(topk))]


def _topk_total_candidates(items: list[str], min_count: int = 1) -> int:
    counter: dict[str, int] = {}
    for item in items:
        counter[item] = counter.get(item, 0) + 1
    threshold = max(1, int(min_count))
    return sum(1 for count in counter.values() if int(count) >= threshold)


def extract_text_and_stats_from_epub(
    path: Path,
    sample_limit: int | None = None,
    basename_topk_min_count: int | None = None,
    basename_topk_limit: int | None = None,
    basename_topk_coverage_ratio_precision: int | None = None,
    basename_topk_coverage_ratio_precision_source: str | None = None,
) -> tuple[str, dict[str, Any]]:
    if BeautifulSoup is None:
        raise RuntimeError("beautifulsoup4 is required for EPUB import")
    limit = _normalize_epub_sample_limit(sample_limit)
    topk_min_count = _normalize_epub_topk_min_count(basename_topk_min_count)
    topk_limit = _normalize_epub_topk_limit(basename_topk_limit)
    topk_coverage_ratio_precision = _normalize_epub_topk_coverage_ratio_precision(basename_topk_coverage_ratio_precision)
    topk_coverage_ratio_precision_source = str(basename_topk_coverage_ratio_precision_source or "default").strip().lower()
    if topk_coverage_ratio_precision_source not in {"cli", "default"}:
        topk_coverage_ratio_precision_source = "default"
    with zipfile.ZipFile(path, "r") as zipf:
        names = set(zipf.namelist())
        candidate_suffixes = (".xhtml", ".html", ".htm")
        ordered = [n for n in _parse_epub_spine_order(zipf) if n in names]
        ordered_from_spine = bool(ordered)
        if not ordered:
            ordered = sorted([n for n in names if n.lower().endswith(candidate_suffixes)])

        texts: list[str] = []
        skipped_toc_docs = 0
        empty_docs = 0
        kept_doc_names: list[str] = []
        skipped_toc_doc_names: list[str] = []
        empty_doc_names: list[str] = []
        for name in ordered:
            lower_name = name.lower()
            if re.search(r"(^|[/_-])(toc|contents?|tableofcontents|table-of-contents|navigation|nav)([/_.-]|$)", lower_name):
                skipped_toc_docs += 1
                skipped_toc_doc_names.append(name)
                continue
            raw = zipf.read(name)
            html = _decode_bytes(raw)
            soup = BeautifulSoup(html, "html.parser")
            _prune_epub_noise(soup)
            text = soup.get_text("\n", strip=True)
            text = normalize_text(text)
            if not text:
                empty_docs += 1
                empty_doc_names.append(name)
                continue
            if _looks_like_toc_text(text):
                skipped_toc_docs += 1
                skipped_toc_doc_names.append(name)
                continue
            texts.append(text)
            kept_doc_names.append(name)

    if not texts:
        raise ValueError("no extractable text in epub")
    all_base = _basename_samples(ordered[:limit])
    kept_base = _basename_samples(kept_doc_names[:limit])
    skipped_base = _basename_samples(skipped_toc_doc_names[:limit])
    empty_base = _basename_samples(empty_doc_names[:limit])
    topk_candidates = _topk_total_candidates(all_base, min_count=topk_min_count)
    topk_rows = _topk_counts(all_base, topk=topk_limit, min_count=topk_min_count)
    topk_other_count = max(0, int(topk_candidates) - len(topk_rows))
    topk_coverage_ratio = (len(topk_rows) / topk_candidates) if topk_candidates > 0 else 0.0
    stats = {
        "section_docs_total": len(ordered),
        "section_docs_kept": len(texts),
        "section_docs_skipped_toc": skipped_toc_docs,
        "section_docs_empty_after_clean": empty_docs,
        "ordered_from_spine": ordered_from_spine,
        "section_doc_name_sample_limit": limit,
        "section_doc_name_samples": ordered[:limit],
        "section_doc_name_samples_basename": all_base,
        "section_doc_kept_name_samples": kept_doc_names[:limit],
        "section_doc_kept_name_samples_basename": kept_base,
        "section_doc_skipped_toc_name_samples": skipped_toc_doc_names[:limit],
        "section_doc_skipped_toc_name_samples_basename": skipped_base,
        "section_doc_empty_name_samples": empty_doc_names[:limit],
        "section_doc_empty_name_samples_basename": empty_base,
        "section_doc_name_sampled_counts": {
            "all": len(ordered[:limit]),
            "kept": len(kept_doc_names[:limit]),
            "skipped_toc": len(skipped_toc_doc_names[:limit]),
            "empty": len(empty_doc_names[:limit]),
        },
        "section_doc_basename_unique_counts": {
            "all": _unique_count(all_base),
            "kept": _unique_count(kept_base),
            "skipped_toc": _unique_count(skipped_base),
            "empty": _unique_count(empty_base),
        },
        "section_doc_basename_topk_min_count": topk_min_count,
        "section_doc_basename_topk_limit": topk_limit,
        "section_doc_basename_topk_limit_applied": topk_limit,
        "section_doc_basename_topk_threshold_applied": bool(topk_min_count > 1),
        "section_doc_basename_topk_total_candidates": topk_candidates,
        "section_doc_basename_topk_other_count": topk_other_count,
        "section_doc_basename_topk_coverage_ratio_precision": topk_coverage_ratio_precision,
        "section_doc_basename_topk_coverage_ratio_precision_source": topk_coverage_ratio_precision_source,
        "section_doc_basename_topk_coverage_ratio_precision_note": f"rounded_to_{topk_coverage_ratio_precision}_decimal_places",
        "section_doc_basename_topk_coverage_ratio_precision_note_template": "rounded_to_{precision}_decimal_places",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source": "static_template",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note": "template source is a static literal",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template": "template source is a {source} literal",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source": "static_template",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note": "template source field is a static template literal",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template": "template source field is a {source} template literal",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source": "static_template",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note": "template source field is a static template literal",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template": "template source field is a {source} template literal",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source": "static_template",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note": "template source field is a static template literal",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template": "template source field is a {source} template literal",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source": "static_template",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note": "template source field is a static template literal",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template": "template source field is a {source} template literal",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source": "static_template",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note": "template source field is a static template literal",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template": "template source field is a {source} template literal",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source": "static_template",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_note_template_source_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_template_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_template_source_note_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_version": "v1",
        "section_doc_basename_topk_coverage_ratio_precision_note_source": "derived_from_section_doc_basename_topk_coverage_ratio_precision",
        "section_doc_basename_topk_coverage_ratio_precision_note_source_version": "v1",
        "section_doc_basename_topk_coverage_ratio_raw": float(topk_coverage_ratio),
        "section_doc_basename_topk_coverage_ratio_raw_source": "len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates (unrounded)",
        "section_doc_basename_topk_coverage_ratio_raw_source_version": "v1",
        "section_doc_basename_topk_coverage_ratio_raw_source_version_note": "v1=len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates (unrounded)",
        "section_doc_basename_topk_coverage_ratio": round(float(topk_coverage_ratio), topk_coverage_ratio_precision),
        "section_doc_basename_topk_coverage_ratio_source": "len(section_doc_basename_topk)/section_doc_basename_topk_total_candidates",
        "section_doc_basename_topk": topk_rows,
    }
    return normalize_text("\n\n".join(texts)), stats


def extract_text_from_epub(path: Path) -> str:
    text, _ = extract_text_and_stats_from_epub(
        path,
        sample_limit=DEFAULT_EPUB_SECTION_DOC_SAMPLE_LIMIT,
        basename_topk_min_count=DEFAULT_EPUB_BASENAME_TOPK_MIN_COUNT,
        basename_topk_limit=DEFAULT_EPUB_BASENAME_TOPK_LIMIT,
        basename_topk_coverage_ratio_precision=DEFAULT_EPUB_BASENAME_TOPK_COVERAGE_RATIO_PRECISION,
        basename_topk_coverage_ratio_precision_source="default",
    )
    return text


def guess_source_format(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".epub":
        return "epub"
    if ext == ".pdf":
        return "pdf"
    return "txt"


def resolve_pdf_toc_entries(
    path: Path,
    book_id: str,
    book_fingerprint: str,
) -> tuple[str, list[dict[str, Any]], list[str], int | None]:
    warnings: list[str] = []
    try:
        outline_entries, outline_warnings, total_pages = extract_pdf_outline_entries(path)
    except Exception as exc:
        outline_entries = []
        outline_warnings = [f"outline_parse_failed: {exc}"]
        total_pages = None
    warnings.extend(outline_warnings)

    manual_entries = find_manual_toc_entries(
        book_id=book_id,
        source_path=str(path.resolve()),
        book_fingerprint=book_fingerprint,
    )
    toc_source, entries = rank_toc_source(outline_entries, manual_entries)
    if toc_source == "manual_toc":
        warnings.append("outline_missing_or_invalid: 使用 manual_toc 作为目录来源")
    if toc_source == "pending_manual_toc":
        warnings.append("toc_missing: 已加入待处理目录队列")
    return toc_source, entries, warnings, total_pages


def text_to_blocks(text: str) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    block_idx = 0

    def push_block(kind: str, content: str) -> None:
        nonlocal block_idx
        payload = content.strip()
        if not payload:
            return
        block_idx += 1
        blocks.append(
            {
                "block_id": f"b{block_idx}",
                "kind": kind,
                "text": payload,
                "page": None,
                "bbox": [0, 0, 1, 1],
            }
        )

    def flush_paragraph(lines: list[str]) -> None:
        if not lines:
            return
        para = " ".join(s.strip() for s in lines if s.strip()).strip()
        lines.clear()
        if not para:
            return
        if para.startswith("#"):
            heading = re.sub(r"^#+\s*", "", para).strip() or f"Section {block_idx + 1}"
            push_block("heading", heading)
            return
        if re.match(r"^\d+(\.\d+)*\s+\S+", para):
            push_block("heading", para)
            return
        push_block("paragraph", para)

    lines = text.split("\n")
    paragraph_lines: list[str] = []
    code_lines: list[str] = []
    in_fence = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if in_fence:
            if stripped.startswith("```"):
                push_block("code", "\n".join(code_lines))
                code_lines = []
                in_fence = False
            else:
                code_lines.append(line.rstrip("\n"))
            i += 1
            continue

        if stripped.startswith("```"):
            flush_paragraph(paragraph_lines)
            in_fence = True
            code_lines = []
            i += 1
            continue

        if re.match(r"^\s{4,}\S+", line):
            flush_paragraph(paragraph_lines)
            indented: list[str] = []
            while i < len(lines) and (re.match(r"^\s{4,}\S+", lines[i]) or lines[i].strip() == ""):
                current = lines[i]
                if current.strip() == "":
                    indented.append("")
                else:
                    indented.append(re.sub(r"^\s{4}", "", current))
                i += 1
            push_block("code", "\n".join(indented))
            continue

        if stripped == "":
            flush_paragraph(paragraph_lines)
            i += 1
            continue

        if stripped.startswith("#"):
            flush_paragraph(paragraph_lines)
            heading = re.sub(r"^#+\s*", "", stripped).strip() or f"Section {block_idx + 1}"
            push_block("heading", heading)
            i += 1
            continue

        if re.match(r"^\d+(\.\d+)*\s+\S+", stripped):
            flush_paragraph(paragraph_lines)
            push_block("heading", stripped)
            i += 1
            continue

        paragraph_lines.append(line)
        i += 1

    if in_fence and code_lines:
        push_block("code", "\n".join(code_lines))
    flush_paragraph(paragraph_lines)
    return blocks


def load_input_payload(
    path: Path,
    book_type: str,
    language: str,
    epub_sample_limit: int | None = None,
    epub_topk_min_count: int | None = None,
    epub_topk_limit: int | None = None,
    epub_topk_coverage_ratio_precision: int | None = None,
) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and ("blocks" in raw or "clean_text" in raw):
            raw.setdefault("book_type", book_type)
            raw.setdefault("language", language)
            return raw
        raise ValueError("JSON input must contain blocks or clean_text")

    if path.suffix.lower() == ".pdf":
        text = extract_text_from_pdf(path)
        return {
            "book_type": book_type,
            "language": language,
            "extract_confidence": 0.9,
            "blocks": text_to_blocks(text),
            "clean_text": text,
        }

    if path.suffix.lower() == ".epub":
        topk_coverage_ratio_precision_source = "default" if epub_topk_coverage_ratio_precision is None else "cli"
        text, extract_stats = extract_text_and_stats_from_epub(
            path,
            sample_limit=epub_sample_limit,
            basename_topk_min_count=epub_topk_min_count,
            basename_topk_limit=epub_topk_limit,
            basename_topk_coverage_ratio_precision=epub_topk_coverage_ratio_precision,
            basename_topk_coverage_ratio_precision_source=topk_coverage_ratio_precision_source,
        )
        return {
            "book_type": book_type,
            "language": language,
            "extract_confidence": 0.88,
            "blocks": text_to_blocks(text),
            "clean_text": text,
            "source_extract_stats": extract_stats,
        }

    text = normalize_text(path.read_text(encoding="utf-8"))
    return {
        "book_type": book_type,
        "language": language,
        "extract_confidence": 0.95,
        "blocks": text_to_blocks(text),
        "clean_text": text,
    }


def to_chunk_uuid(book_id: str, chunk_id: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"bookflow:{book_id}:{chunk_id}")


def import_to_db(
    dsn: str,
    book_id: str,
    title: str,
    author: str | None,
    language: str,
    book_type: str,
    source_format: str,
    source_path: str,
    chunk_result: dict[str, Any],
) -> int:
    chunks = chunk_result.get("chunks", [])
    chunk_uuid_map = {c["chunk_id"]: to_chunk_uuid(book_id, c["chunk_id"]) for c in chunks}

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO books (
                  id, title, author, language, book_type, source_format, source_path,
                  processing_status, total_sections, metadata
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'ready', %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                  title = EXCLUDED.title,
                  author = EXCLUDED.author,
                  language = EXCLUDED.language,
                  book_type = EXCLUDED.book_type,
                  source_format = EXCLUDED.source_format,
                  source_path = EXCLUDED.source_path,
                  processing_status = EXCLUDED.processing_status,
                  total_sections = EXCLUDED.total_sections,
                  metadata = EXCLUDED.metadata,
                  updated_at = NOW()
                """,
                (
                    book_id,
                    title,
                    author,
                    language,
                    book_type,
                    source_format,
                    source_path,
                    len({c["section_id"] for c in chunks}),
                    Json({"import_source": "import_book.py"}),
                ),
            )

            for c in chunks:
                prereq = [chunk_uuid_map[p] for p in c.get("prerequisite_chunk_ids", []) if p in chunk_uuid_map]
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
                        chunk_uuid_map[c["chunk_id"]],
                        book_id,
                        c["section_id"],
                        c["chunk_index_in_section"],
                        c["global_index"],
                        c.get("title"),
                        c.get("text", ""),
                        (c.get("text", "")[:80] + "...") if c.get("text") else None,
                        chunk_result.get("chunking_version", "chunking_v1"),
                        c.get("render_mode", "reflow"),
                        c.get("render_reason", []),
                        Json(c.get("source_anchor", {})),
                        int(c.get("read_time_sec_est", 0)),
                        bool(c.get("has_formula", False)),
                        bool(c.get("has_code", False)),
                        bool(c.get("has_table", False)),
                        float(c.get("quality_score", 0.0)),
                        prereq,
                        Json({"import_source": "import_book.py", "source_chunk_id": c.get("chunk_id")}),
                    ),
                )
    return len(chunks)


def mask_dsn(dsn: str | None) -> str | None:
    if not dsn:
        return dsn
    return re.sub(r"://([^:/]+):([^@]+)@", r"://\1:***@", dsn)


def run_with_retry(fn: Any, retries: int, retry_delay_sec: float) -> Any:
    attempts = retries + 1
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception:
            if attempt >= attempts:
                raise
            delay = retry_delay_sec * (2 ** (attempt - 1))
            if delay > 0:
                time.sleep(delay)
    raise RuntimeError("retry failed")


def write_error_report(
    error: Exception,
    report_dir: Path,
    context: dict[str, Any],
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    book_id = str(context.get("book_id") or "unknown")
    out = report_dir / f"import_error_{ts}_{book_id}.json"
    payload = {
        "status": "error",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "error_type": type(error).__name__,
        "error_message": str(error),
        "context": context,
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Import book file into BookFlow Postgres")
    parser.add_argument("--input", required=True, help="Input file path (.txt/.md/.json)")
    parser.add_argument("--title", required=True, help="Book title")
    parser.add_argument("--author", default=None, help="Book author")
    parser.add_argument("--book-type", default="general", choices=["general", "fiction", "technical"])
    parser.add_argument("--language", default="zh")
    parser.add_argument("--source-format", choices=["pdf", "epub", "txt"], default=None)
    parser.add_argument(
        "--pdf-section-storage",
        choices=["precut", "on_demand"],
        default=DEFAULT_PDF_SECTION_STORAGE,
        help="PDF章节存储策略：precut=预切片文件；on_demand=不落章节PDF，阅读时按源PDF生成",
    )
    parser.add_argument("--book-id", default=None, help="UUID string, auto-generate if omitted")
    parser.add_argument("--config", default="config/pipeline.json")
    parser.add_argument("--database-url", default=None, help="Override DATABASE_URL")
    parser.add_argument("--retry", type=int, default=2, help="Retry count for DB write")
    parser.add_argument("--retry-delay-sec", type=float, default=1.0, help="Initial retry delay in seconds")
    parser.add_argument("--error-report-dir", default="logs/import_errors", help="Error report output directory")
    parser.add_argument("--epub-sample-limit", type=int, default=DEFAULT_EPUB_SECTION_DOC_SAMPLE_LIMIT, help="EPUB extract stats sample size for section doc names")
    parser.add_argument("--epub-topk-min-count", type=int, default=DEFAULT_EPUB_BASENAME_TOPK_MIN_COUNT, help="EPUB basename topk minimum count threshold")
    parser.add_argument("--epub-topk-limit", type=int, default=DEFAULT_EPUB_BASENAME_TOPK_LIMIT, help="EPUB basename topk output limit (1..20)")
    parser.add_argument("--epub-topk-coverage-ratio-precision", type=int, default=DEFAULT_EPUB_BASENAME_TOPK_COVERAGE_RATIO_PRECISION, help="EPUB basename topk coverage ratio decimal precision (0..6)")
    parser.add_argument("--dry-run", action="store_true", help="Only process and print summary")
    args = parser.parse_args()

    input_path = Path(args.input)
    stable_input = str(input_path.resolve())
    default_book_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"bookflow:{stable_input}"))
    book_id = str(args.book_id or default_book_id)
    dsn = args.database_url or os.getenv("DATABASE_URL")
    context = {
        "book_id": book_id,
        "title": args.title,
        "input": str(input_path),
        "book_type": args.book_type,
        "language": args.language,
        "source_format": args.source_format,
        "pdf_section_storage": args.pdf_section_storage,
        "dry_run": bool(args.dry_run),
        "retry": int(args.retry),
        "retry_delay_sec": float(args.retry_delay_sec),
        "epub_sample_limit": int(args.epub_sample_limit),
        "epub_topk_min_count": int(args.epub_topk_min_count),
        "epub_topk_limit": int(args.epub_topk_limit),
        "epub_topk_coverage_ratio_precision": int(args.epub_topk_coverage_ratio_precision),
        "database_url": mask_dsn(dsn),
    }

    try:
        if not input_path.exists():
            raise FileNotFoundError(f"input file not found: {input_path}")

        source_format = args.source_format or guess_source_format(input_path)
        context["source_format"] = source_format
        source_fingerprint = ""
        if source_format == "pdf":
            source_fingerprint = compute_file_sha256(input_path)
            context["book_fingerprint"] = source_fingerprint

        if source_format == "pdf":
            toc_source, toc_entries, toc_warnings, total_pages = resolve_pdf_toc_entries(
                input_path,
                book_id=book_id,
                book_fingerprint=source_fingerprint,
            )
            context["toc_source"] = toc_source
            materialized: dict[str, Any] = {
                "total_pages": int(total_pages) if total_pages is not None else None,
                "toc_entry_count": len(toc_entries),
                "toc_leaf_count": len(toc_entries),
                "materialized_chunks": 0,
                "generated_pdf_count": 0,
                "long_section_warning_count": 0,
                "failed_entries": [],
                "warnings": list(toc_warnings),
                "chunk_records": [],
            }
            if toc_entries:
                materialized = materialize_pdf_sections(
                    pdf_path=input_path,
                    book_id=book_id,
                    toc_entries=toc_entries,
                    toc_source=toc_source,
                    persist_section_pdf=args.pdf_section_storage == "precut",
                )
                materialized["warnings"] = list(toc_warnings) + list(materialized.get("warnings", []))
            context["chunk_count"] = int(materialized.get("materialized_chunks", 0))

            if args.dry_run:
                print(
                    json.dumps(
                        {
                            "book_id": book_id,
                            "title": args.title,
                            "source_format": source_format,
                            "toc_source": toc_source,
                            "needs_manual_toc": toc_source == "pending_manual_toc",
                            "pdf_section_storage": args.pdf_section_storage,
                            "book_fingerprint": source_fingerprint,
                            "total_pages": materialized.get("total_pages"),
                            "toc_entry_count": materialized.get("toc_entry_count", 0),
                            "toc_leaf_count": materialized.get("toc_leaf_count", 0),
                            "materialized_chunks": materialized.get("materialized_chunks", 0),
                            "generated_pdf_count": materialized.get("generated_pdf_count", 0),
                            "failed_entries": materialized.get("failed_entries", []),
                            "warnings": materialized.get("warnings", []),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
                return 0

            if not dsn:
                raise RuntimeError("DATABASE_URL is required (or pass --database-url)")

            chunk_records = list(materialized.get("chunk_records", []))
            needs_manual_toc = toc_source == "pending_manual_toc"
            extra_metadata: dict[str, Any] = {
                "toc_warnings": list(materialized.get("warnings", []))[:80],
                "failed_entry_count": int(len(materialized.get("failed_entries", []))),
                "long_section_warning_count": int(materialized.get("long_section_warning_count", 0)),
                "materialization_fingerprint": build_materialization_fingerprint(chunk_records) if chunk_records else None,
                "pdf_section_storage_mode": str(args.pdf_section_storage),
                "book_fingerprint": source_fingerprint,
            }
            inserted = run_with_retry(
                lambda: upsert_book_and_pdf_chunks(
                    dsn=dsn,
                    book_id=book_id,
                    title=args.title,
                    author=args.author,
                    language=args.language,
                    book_type=args.book_type,
                    source_path=str(input_path.resolve()),
                    total_pages=_safe_int(materialized.get("total_pages"), None),
                    source_format=source_format,
                    toc_source=toc_source,
                    chunk_records=chunk_records,
                    replace_existing_chunks=True,
                    needs_manual_toc=needs_manual_toc,
                    manual_toc_entries=toc_entries if toc_source == "manual_toc" else None,
                    extra_metadata=extra_metadata,
                    processing_status="processing" if needs_manual_toc else "ready",
                    toc_review_status="pending_review",
                ),
                retries=max(0, int(args.retry)),
                retry_delay_sec=max(0.0, float(args.retry_delay_sec)),
            )

            if toc_entries:
                try:
                    upsert_toc_annotation_for_import(
                        book_id=book_id,
                        source_path=str(input_path.resolve()),
                        book_fingerprint=source_fingerprint,
                        toc_source=toc_source,
                        entries=toc_entries,
                        warnings=list(materialized.get("warnings", [])),
                    )
                except Exception:
                    pass
            print(
                json.dumps(
                    {
                        "status": "ok",
                        "book_id": book_id,
                        "title": args.title,
                        "source_format": source_format,
                        "toc_source": toc_source,
                        "needs_manual_toc": needs_manual_toc,
                        "pdf_section_storage": args.pdf_section_storage,
                        "book_fingerprint": source_fingerprint,
                        "total_pages": materialized.get("total_pages"),
                        "toc_entry_count": materialized.get("toc_entry_count", 0),
                        "toc_leaf_count": materialized.get("toc_leaf_count", 0),
                        "materialized_chunks": materialized.get("materialized_chunks", 0),
                        "generated_pdf_count": materialized.get("generated_pdf_count", 0),
                        "chunks_upserted": inserted,
                        "failed_entries": materialized.get("failed_entries", []),
                        "warnings": materialized.get("warnings", []),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        payload = load_input_payload(
            input_path,
            book_type=args.book_type,
            language=args.language,
            epub_sample_limit=args.epub_sample_limit,
            epub_topk_min_count=args.epub_topk_min_count,
            epub_topk_limit=args.epub_topk_limit,
            epub_topk_coverage_ratio_precision=args.epub_topk_coverage_ratio_precision,
        )
        payload["book_id"] = book_id
        payload["book_type"] = args.book_type
        payload["language"] = args.language
        source_extract_stats = payload.get("source_extract_stats", {})

        cfg = load_config_for_book_type(Path(args.config), args.book_type)
        chunk_result = run_pipeline(payload, cfg)
        context["chunk_count"] = int(chunk_result.get("chunk_count", 0))

        if args.dry_run:
            print(
                json.dumps(
                    {
                        "book_id": payload["book_id"],
                        "title": args.title,
                        "chunk_count": chunk_result.get("chunk_count", 0),
                        "stats": chunk_result.get("stats", {}),
                        "epub_sample_limit": int(args.epub_sample_limit),
                        "epub_topk_min_count": int(args.epub_topk_min_count),
                        "epub_topk_limit": int(args.epub_topk_limit),
                        "epub_topk_coverage_ratio_precision": int(args.epub_topk_coverage_ratio_precision),
                        "source_extract_stats": source_extract_stats,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if not dsn:
            raise RuntimeError("DATABASE_URL is required (or pass --database-url)")

        inserted = run_with_retry(
            lambda: import_to_db(
                dsn=dsn,
                book_id=payload["book_id"],
                title=args.title,
                author=args.author,
                language=args.language,
                book_type=args.book_type,
                source_format=source_format,
                source_path=str(input_path.resolve()),
                chunk_result=chunk_result,
            ),
            retries=max(0, int(args.retry)),
            retry_delay_sec=max(0.0, float(args.retry_delay_sec)),
        )
        print(
            json.dumps(
                {
                    "status": "ok",
                    "book_id": payload["book_id"],
                    "title": args.title,
                    "chunks_upserted": inserted,
                    "epub_sample_limit": int(args.epub_sample_limit),
                    "epub_topk_min_count": int(args.epub_topk_min_count),
                    "epub_topk_limit": int(args.epub_topk_limit),
                    "epub_topk_coverage_ratio_precision": int(args.epub_topk_coverage_ratio_precision),
                    "render_mode_counts": chunk_result.get("stats", {}).get("render_mode_counts", {}),
                    "source_extract_stats": source_extract_stats,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except Exception as exc:
        report_path = write_error_report(exc, Path(args.error_report_dir), context=context)
        print(
            json.dumps(
                {
                    "status": "error",
                    "book_id": book_id,
                    "error": str(exc),
                    "report_path": str(report_path),
                },
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
