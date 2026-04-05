#!/usr/bin/env python3
"""
BookFlow V0 server (clean rebuild).

Goal:
- TOC-driven PDF section reading
- Two-column feed cards
- Book mosaic progress
- Manual TOC preview/save/materialize
- Lightweight interactions

No legacy trace/debug response noise.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import mimetypes
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from urllib import error as urlerror
from urllib import request as urlrequest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Json
except Exception:  # pragma: no cover
    psycopg = None
    dict_row = None
    Json = None

try:
    from rapidocr_onnxruntime import RapidOCR
except Exception:  # pragma: no cover
    RapidOCR = None

try:
    from pypdf import PdfReader, PdfWriter
except Exception:  # pragma: no cover
    PdfReader = None
    PdfWriter = None

from scripts.pdf_sectioning import (
    DEFAULT_DERIVED_ROOT,
    materialize_pdf_sections,
    upsert_book_and_pdf_chunks,
)

TOKEN = os.getenv("BOOKFLOW_TOKEN", "local-dev-token")
DATABASE_URL = os.getenv("DATABASE_URL")
PYTHON_BIN = sys.executable or "python3"
FRONTEND_ROOT = Path(os.getenv("BOOKFLOW_FRONTEND_DIR", REPO_ROOT / "frontend"))
TOC_STORE_PATH = Path(os.getenv("BOOKFLOW_TOC_STORE_PATH", "data/toc/manual_annotations.json"))
TOC_NORMALIZED_DIR = Path(os.getenv("BOOKFLOW_TOC_NORMALIZED_DIR", "data/toc/normalized"))
TOC_SCHEMA_VERSION = "bookflow.manual_toc.v1"
LLM_TOC_BASE_URL = str(os.getenv("BOOKFLOW_LLM_TOC_BASE_URL", "")).strip()
LLM_TOC_MODEL = str(os.getenv("BOOKFLOW_LLM_TOC_MODEL", "")).strip()
LLM_TOC_API_KEY = str(os.getenv("BOOKFLOW_LLM_TOC_API_KEY", "")).strip()
LLM_TOC_CONFIG_PATH = Path(os.getenv("BOOKFLOW_LLM_TOC_CONFIG_PATH", "data/toc/llm_config.json"))
LLM_TOC_RUN_DIR = Path(os.getenv("BOOKFLOW_LLM_TOC_RUN_DIR", "data/toc/llm_runs"))


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return int(default)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return bool(default)
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(default)


PDF_SECTION_STORAGE_MODE = str(os.getenv("BOOKFLOW_PDF_SECTION_STORAGE", "precut") or "precut").strip().lower()
if PDF_SECTION_STORAGE_MODE not in {"precut", "on_demand"}:
    PDF_SECTION_STORAGE_MODE = "precut"

CACHE_ROOT = Path(os.getenv("BOOKFLOW_CACHE_ROOT", "data/cache"))
COVER_CACHE_ROOT = Path(os.getenv("BOOKFLOW_COVER_CACHE_ROOT", str((CACHE_ROOT / "covers").as_posix())))
PAGE_CACHE_ROOT = Path(os.getenv("BOOKFLOW_PAGE_CACHE_ROOT", str((CACHE_ROOT / "pages").as_posix())))
COVER_CACHE_TTL_SEC = max(60, _env_int("BOOKFLOW_COVER_CACHE_TTL_SEC", 86400 * 7))
PAGE_CACHE_TTL_SEC = max(60, _env_int("BOOKFLOW_PAGE_CACHE_TTL_SEC", 86400 * 7))

USER_EXPORT_ROOT = Path(os.getenv("BOOKFLOW_USER_EXPORT_DIR", "data/users/export"))
AUTO_EXPORT_USER_STATE = _env_bool("BOOKFLOW_AUTO_EXPORT_USER_STATE", True)

STARTUP_BOOTSTRAP_ENABLED = _env_bool("BOOKFLOW_STARTUP_BOOTSTRAP_ENABLED", True)
STARTUP_BOOTSTRAP_INPUT_DIR = Path(os.getenv("BOOKFLOW_STARTUP_BOOTSTRAP_INPUT_DIR", "data/books/inbox"))
STARTUP_BOOTSTRAP_RECURSIVE = _env_bool("BOOKFLOW_STARTUP_BOOTSTRAP_RECURSIVE", True)
STARTUP_BOOTSTRAP_INTERVAL_SEC = max(30, _env_int("BOOKFLOW_STARTUP_BOOTSTRAP_INTERVAL_SEC", 300))
STARTUP_BOOTSTRAP_INITIAL_DELAY_SEC = max(0, _env_int("BOOKFLOW_STARTUP_BOOTSTRAP_INITIAL_DELAY_SEC", 2))
STARTUP_BOOTSTRAP_SKIP_EXISTING = _env_bool("BOOKFLOW_STARTUP_BOOTSTRAP_SKIP_EXISTING", True)
STARTUP_BOOTSTRAP_RESCAN_APPROVED = _env_bool("BOOKFLOW_STARTUP_BOOTSTRAP_RESCAN_APPROVED", False)
STARTUP_BOOTSTRAP_AUTO_APPROVE_IMPORTED = _env_bool("BOOKFLOW_STARTUP_BOOTSTRAP_AUTO_APPROVE_IMPORTED", False)
STARTUP_BOOTSTRAP_FEED_LIMIT = max(1, _env_int("BOOKFLOW_STARTUP_BOOTSTRAP_FEED_LIMIT", 30))
STARTUP_BOOTSTRAP_WARM_COVER_LIMIT = max(0, _env_int("BOOKFLOW_STARTUP_BOOTSTRAP_WARM_COVER_LIMIT", 24))
STARTUP_BOOTSTRAP_IMPORT_TIMEOUT_SEC = max(30, _env_int("BOOKFLOW_STARTUP_BOOTSTRAP_IMPORT_TIMEOUT_SEC", 1800))
STARTUP_BOOTSTRAP_WARM_COVER_TIMEOUT_SEC = max(20, _env_int("BOOKFLOW_STARTUP_BOOTSTRAP_WARM_COVER_TIMEOUT_SEC", 300))
FEED_QUERY_TIMEOUT_MS = max(500, _env_int("BOOKFLOW_FEED_QUERY_TIMEOUT_MS", 8000))
DB_CONNECT_TIMEOUT_SEC = max(1, _env_int("BOOKFLOW_DB_CONNECT_TIMEOUT_SEC", 5))
STARTUP_BOOTSTRAP_LANGUAGE = str(os.getenv("BOOKFLOW_STARTUP_BOOTSTRAP_LANGUAGE", "zh") or "zh").strip() or "zh"
STARTUP_BOOTSTRAP_BOOK_TYPE_STRATEGY = str(
    os.getenv("BOOKFLOW_STARTUP_BOOTSTRAP_BOOK_TYPE_STRATEGY", "auto") or "auto"
).strip().lower()
if STARTUP_BOOTSTRAP_BOOK_TYPE_STRATEGY not in {"auto", "fixed"}:
    STARTUP_BOOTSTRAP_BOOK_TYPE_STRATEGY = "auto"
STARTUP_BOOTSTRAP_DEFAULT_BOOK_TYPE = str(
    os.getenv("BOOKFLOW_STARTUP_BOOTSTRAP_DEFAULT_BOOK_TYPE", "general") or "general"
).strip().lower()
if STARTUP_BOOTSTRAP_DEFAULT_BOOK_TYPE not in {"general", "fiction", "technical"}:
    STARTUP_BOOTSTRAP_DEFAULT_BOOK_TYPE = "general"
STARTUP_BOOTSTRAP_FIXED_BOOK_TYPE = str(
    os.getenv("BOOKFLOW_STARTUP_BOOTSTRAP_FIXED_BOOK_TYPE", "technical") or "technical"
).strip().lower()
if STARTUP_BOOTSTRAP_FIXED_BOOK_TYPE not in {"general", "fiction", "technical"}:
    STARTUP_BOOTSTRAP_FIXED_BOOK_TYPE = "technical"

VALID_EVENT_TYPES = {
    "impression",
    "enter_context",
    "backtrack",
    "section_complete",
    "skip",
    "confusion",
    "like",
    "comment",
}

_OCR_ENGINE: Any | None = None
IMPORT_JOB_PROGRESS_RE = re.compile(
    r"^\[(\d+)/(\d+)\]\s+(?:importing|skipping approved):\s+(.+?)(?:\s+\(book_type=.*\))?\s*$"
)
IMPORT_JOBS_LOCK = threading.Lock()
IMPORT_JOBS: dict[str, dict[str, Any]] = {}
STARTUP_BOOTSTRAP_LOCK = threading.Lock()
STARTUP_BOOTSTRAP_STATE: dict[str, Any] = {
    "enabled": bool(STARTUP_BOOTSTRAP_ENABLED),
    "status": "idle",
    "running": False,
    "cycle": 0,
    "started_at": None,
    "updated_at": None,
    "last_run_started_at": None,
    "last_run_finished_at": None,
    "last_error": "",
    "last_summary": {},
}
LLM_BATCH_JOBS_LOCK = threading.Lock()
LLM_BATCH_JOBS: dict[str, dict[str, Any]] = {}
DEFAULT_LLM_TOC_PROMPT = (
    "你是目录识别助手。请从图片中提取目录条目，并严格按每行一条返回："
    "“标题 ...... 页码”。"
    "只输出目录行，不要解释，不要 markdown，不要代码块。"
    "页码可为阿拉伯数字或罗马数字。"
)
TINY_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO7Z0uQAAAAASUVORK5CYII="
)


def get_ocr_engine() -> Any | None:
    global _OCR_ENGINE
    if _OCR_ENGINE is not None:
        return _OCR_ENGINE
    if RapidOCR is None:
        return None
    try:
        _OCR_ENGINE = RapidOCR()
    except Exception:
        _OCR_ENGINE = None
    return _OCR_ENGINE


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso(raw: str) -> datetime:
    text = str(raw or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def safe_int(raw: Any, default: int | None = None) -> int | None:
    try:
        return int(raw)
    except Exception:
        return default


def safe_bool(raw: Any, default: bool = False) -> bool:
    if raw is None:
        return default
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def resolve_runtime_path(path: Path) -> Path:
    if path.is_absolute():
        return path.resolve()
    return (Path.cwd() / path).resolve()


def is_cache_stale(cache_path: Path, source_path: Path | None, ttl_sec: int) -> bool:
    if not cache_path.exists():
        return True
    try:
        age = max(0.0, time.time() - cache_path.stat().st_mtime)
        if age > max(1, int(ttl_sec)):
            return True
    except Exception:
        return True
    if source_path and source_path.exists():
        try:
            if cache_path.stat().st_mtime < source_path.stat().st_mtime:
                return True
        except Exception:
            return True
    return False


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def error_response(handler: BaseHTTPRequestHandler, status: int, code: str, message: str) -> None:
    return json_response(handler, status, {"error": {"code": code, "message": message}})


def encode_cursor(offset: int) -> str:
    raw = json.dumps({"offset": max(0, int(offset))}).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8")


def decode_cursor(cursor: str) -> int:
    decoded = base64.urlsafe_b64decode(str(cursor).encode("utf-8")).decode("utf-8")
    payload = json.loads(decoded)
    return max(0, int(payload.get("offset", 0)))


def ensure_uuid(value: str) -> str:
    return str(uuid.UUID(str(value)))


def load_seed_items() -> list[dict[str, Any]]:
    sample_path = REPO_ROOT / "examples" / "sample_output.json"
    if not sample_path.exists():
        return []
    try:
        payload = json.loads(sample_path.read_text(encoding="utf-8"))
    except Exception:
        return []

    chunks = payload.get("chunks") if isinstance(payload.get("chunks"), list) else []
    book_id = str(payload.get("book_id") or "b_sample_001")
    out: list[dict[str, Any]] = []
    for idx, chunk in enumerate(chunks, start=1):
        source_anchor = chunk.get("source_anchor") if isinstance(chunk.get("source_anchor"), dict) else {}
        text_content = str(chunk.get("text") or "")
        teaser = text_content[:120] + ("..." if len(text_content) > 120 else "")
        out.append(
            {
                "book_id": book_id,
                "book_title": "Sample Book",
                "chunk_id": str(chunk.get("chunk_id") or f"c_{idx:04d}"),
                "section_id": str(chunk.get("section_id") or f"sec_{idx:04d}"),
                "title": str(chunk.get("title") or f"Section {idx}"),
                "teaser_text": teaser,
                "text_content": text_content,
                "global_index": idx,
                "source_anchor": source_anchor,
                "metadata": {},
            }
        )
    return out


def read_toc_store() -> dict[str, Any]:
    if not TOC_STORE_PATH.exists():
        return {
            "schema_version": TOC_SCHEMA_VERSION,
            "updated_at": now_iso(),
            "annotations": {},
            "fingerprint_annotations": {},
            "source_path_fingerprints": {},
        }
    try:
        payload = json.loads(TOC_STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {
            "schema_version": TOC_SCHEMA_VERSION,
            "updated_at": now_iso(),
            "annotations": {},
            "fingerprint_annotations": {},
            "source_path_fingerprints": {},
        }
    annotations = payload.get("annotations") if isinstance(payload.get("annotations"), dict) else {}
    fingerprint_annotations = payload.get("fingerprint_annotations") if isinstance(payload.get("fingerprint_annotations"), dict) else {}
    source_path_fingerprints = payload.get("source_path_fingerprints") if isinstance(payload.get("source_path_fingerprints"), dict) else {}
    return {
        "schema_version": TOC_SCHEMA_VERSION,
        "updated_at": str(payload.get("updated_at") or now_iso()),
        "annotations": annotations,
        "fingerprint_annotations": fingerprint_annotations,
        "source_path_fingerprints": source_path_fingerprints,
    }


def write_toc_store(payload: dict[str, Any]) -> None:
    TOC_STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized = {
        "schema_version": TOC_SCHEMA_VERSION,
        "updated_at": now_iso(),
        "annotations": payload.get("annotations", {}),
        "fingerprint_annotations": payload.get("fingerprint_annotations", {}),
        "source_path_fingerprints": payload.get("source_path_fingerprints", {}),
    }
    TOC_STORE_PATH.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")


def normalize_source_path(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        path = Path(text)
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        else:
            path = path.resolve()
        return path.as_posix()
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


def persist_normalized_toc_file(annotation: dict[str, Any]) -> str:
    TOC_NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)
    key = str(annotation.get("book_fingerprint") or annotation.get("book_id") or "unknown").strip() or "unknown"
    file_path = (TOC_NORMALIZED_DIR / f"{key}.json").resolve()
    file_path.write_text(json.dumps(annotation, ensure_ascii=False, indent=2), encoding="utf-8")
    return file_path.as_posix()


def normalize_toc_entries(entries: Any) -> tuple[list[dict[str, Any]], list[str]]:
    normalized: list[dict[str, Any]] = []
    warnings: list[str] = []
    rows = entries if isinstance(entries, list) else []
    for idx, entry in enumerate(rows, start=1):
        if not isinstance(entry, dict):
            continue
        title = str(entry.get("title") or "").strip()
        if not title:
            continue
        start_page = safe_int(entry.get("start_page"), None)
        end_page = safe_int(entry.get("end_page"), None)
        level = safe_int(entry.get("level"), infer_toc_level(title)) or 1

        if start_page is None or start_page <= 0:
            warnings.append(f"entry#{idx} start_page invalid, skipped")
            continue
        if end_page is None or end_page < start_page:
            end_page = start_page

        normalized.append(
            {
                "title": title,
                "level": max(1, int(level)),
                "start_page": int(start_page),
                "end_page": int(end_page),
            }
        )

    for i in range(1, len(normalized)):
        if int(normalized[i]["start_page"]) < int(normalized[i - 1]["start_page"]):
            warnings.append(f"page descending: {normalized[i - 1]['title']} -> {normalized[i]['title']}")

    return normalized, warnings


def upsert_toc_annotation_in_store(
    *,
    store_payload: dict[str, Any],
    book_id: str,
    annotation: dict[str, Any],
) -> dict[str, Any]:
    annotations = store_payload.get("annotations") if isinstance(store_payload.get("annotations"), dict) else {}
    fingerprint_annotations = (
        store_payload.get("fingerprint_annotations")
        if isinstance(store_payload.get("fingerprint_annotations"), dict)
        else {}
    )
    source_path_fingerprints = (
        store_payload.get("source_path_fingerprints")
        if isinstance(store_payload.get("source_path_fingerprints"), dict)
        else {}
    )

    # 清理旧索引，避免同一本书旧校验码残留影响匹配。
    for key, ann in list(fingerprint_annotations.items()):
        if isinstance(ann, dict) and str(ann.get("book_id") or "") == str(book_id):
            fingerprint_annotations.pop(key, None)
    source_path_norm = normalize_source_path(annotation.get("source_path"))
    if source_path_norm:
        for src_key in list(source_path_fingerprints.keys()):
            if normalize_source_path(src_key) == source_path_norm:
                source_path_fingerprints.pop(src_key, None)

    normalized = dict(annotation)
    normalized["book_id"] = str(book_id)
    normalized["normalized_file"] = persist_normalized_toc_file(normalized)
    annotations[str(book_id)] = normalized

    book_fingerprint = str(normalized.get("book_fingerprint") or "").strip().lower()
    if book_fingerprint:
        fingerprint_annotations[book_fingerprint] = normalized
    if source_path_norm and book_fingerprint:
        source_path_fingerprints[source_path_norm] = book_fingerprint

    store_payload["annotations"] = annotations
    store_payload["fingerprint_annotations"] = fingerprint_annotations
    store_payload["source_path_fingerprints"] = source_path_fingerprints
    return normalized


def resolve_manual_toc_annotation(
    *,
    annotations: dict[str, Any],
    fingerprint_annotations: dict[str, Any] | None = None,
    source_path_fingerprints: dict[str, Any] | None = None,
    book_id: str,
    book_source_path: str | None,
    book_fingerprint: str | None = None,
    store: Any,
    source_cache: dict[str, str] | None = None,
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    if not isinstance(annotations, dict):
        return None, None, None

    direct = annotations.get(book_id)
    if isinstance(direct, dict):
        return direct, str(book_id), "book_id"

    fp_map = fingerprint_annotations if isinstance(fingerprint_annotations, dict) else {}
    source_fp_map = source_path_fingerprints if isinstance(source_path_fingerprints, dict) else {}
    fingerprint = str(book_fingerprint or "").strip().lower()
    if fingerprint and isinstance(fp_map.get(fingerprint), dict):
        ann = fp_map.get(fingerprint)
        ann_book_id = str((ann or {}).get("book_id") or "")
        return ann, ann_book_id or None, "fingerprint"

    source_key = normalize_source_path(book_source_path)
    if not source_key:
        try:
            book = store.get_book(book_id)
        except Exception:
            book = None
        source_key = normalize_source_path((book or {}).get("source_path"))
    if not source_key:
        return None, None, None

    fingerprint_from_source = str(source_fp_map.get(source_key) or "").strip().lower()
    if fingerprint_from_source and isinstance(fp_map.get(fingerprint_from_source), dict):
        ann = fp_map.get(fingerprint_from_source)
        ann_book_id = str((ann or {}).get("book_id") or "")
        return ann, ann_book_id or None, "source_path->fingerprint"

    for ann_key, ann in annotations.items():
        if not isinstance(ann, dict):
            continue
        ann_source = normalize_source_path(ann.get("source_path"))
        if ann_source and ann_source == source_key:
            return ann, str(ann_key), "source_path"

    src_cache = source_cache if isinstance(source_cache, dict) else {}
    for ann_key, ann in annotations.items():
        if not isinstance(ann, dict):
            continue
        key = str(ann_key or "")
        if not key or key == str(book_id):
            continue
        if key in src_cache:
            old_source = src_cache[key]
        else:
            old_source = ""
            try:
                old_book = store.get_book(key)
            except Exception:
                old_book = None
            if old_book:
                old_source = normalize_source_path(old_book.get("source_path"))
            src_cache[key] = old_source
        if old_source and old_source == source_key:
            return ann, key, "source_path_via_book_id"

    return None, None, None


def infer_toc_level(title: str) -> int:
    text = str(title or "").strip()
    if not text:
        return 1
    m = re.match(r"^\s*(\d+(?:\.\d+)*)", text)
    if m:
        return max(1, m.group(1).count(".") + 1)
    m2 = re.match(r"^\s*([A-Za-z](?:\.\d+)+)", text)
    if m2:
        return max(1, m2.group(1).count(".") + 1)
    if re.match(r"^\s*第[一二三四五六七八九十百千0-9]+章", text):
        return 1
    return 2


def _int_to_roman(num: int) -> str:
    value_map = (
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    )
    n = int(num)
    out: list[str] = []
    for value, symbol in value_map:
        while n >= value:
            out.append(symbol)
            n -= value
    return "".join(out)


def roman_to_int(token: str) -> int | None:
    raw = str(token or "").strip().upper()
    if not raw or not re.fullmatch(r"[IVXLCDM]+", raw):
        return None
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    for idx, ch in enumerate(raw):
        val = values[ch]
        next_val = values.get(raw[idx + 1], 0) if idx + 1 < len(raw) else 0
        total += -val if val < next_val else val
    if total <= 0 or total > 3999:
        return None
    if _int_to_roman(total) != raw:
        return None
    return total


def parse_page_token(token: str) -> int | None:
    cleaned = str(token or "").strip()
    cleaned = cleaned.strip("()[]{}（）【】<>,.;:·• ")
    if not cleaned:
        return None
    if re.fullmatch(r"-?\d{1,5}", cleaned):
        return int(cleaned)
    if re.fullmatch(r"[IVXLCDMivxlcdm]{1,12}", cleaned):
        return roman_to_int(cleaned)
    return None


def parse_toc_line(raw: str) -> tuple[str, int] | None:
    line = str(raw or "").strip()
    if not line:
        return None
    line = re.sub(r"^[•\-*]+\s*", "", line).strip()
    if not line:
        return None

    m = re.match(r"^(?P<title>.+?)(?:\.{2,}|\s+)(?P<page>-?\d{1,5}|[IVXLCDMivxlcdm]{1,12})\s*$", line)
    if m:
        title = re.sub(r"[.\u2026。．·•\s]+$", "", str(m.group("title") or "").strip()).strip()
        page = parse_page_token(str(m.group("page") or ""))
        if title and page is not None:
            return title, int(page)

    m2 = re.match(r"^(?P<title>.+?)\s+(?P<page>-?\d{1,5}|[IVXLCDMivxlcdm]{1,12})\s*$", line)
    if m2:
        title = re.sub(r"[.\u2026。．·•\s]+$", "", str(m2.group("title") or "").strip()).strip()
        page = parse_page_token(str(m2.group("page") or ""))
        if title and page is not None:
            return title, int(page)

    # 兼容 OCR 里 "title .... vii." 这类末尾带标点的页码写法
    m3 = re.match(r"^(?P<title>.+?)(?:\.{2,}|\s+)(?P<page>[\[(（]?[IVXLCDMivxlcdm]+[)\]）]?[.,;:]?)\s*$", line)
    if m3:
        title = re.sub(r"[.\u2026。．·•\s]+$", "", str(m3.group("title") or "").strip()).strip()
        page = parse_page_token(str(m3.group("page") or ""))
        if title and page is not None:
            return title, int(page)

    m4 = re.match(r"^(?P<title>.+?)\s+(?P<page>[\[(（]?[IVXLCDMivxlcdm]+[)\]）]?[.,;:]?)\s*$", line)
    if m4:
        title = re.sub(r"[.\u2026。．·•\s]+$", "", str(m4.group("title") or "").strip()).strip()
        page = parse_page_token(str(m4.group("page") or ""))
        if title:
            if page is not None:
                return title, int(page)

    return None


def build_toc_preview(toc_text: str, total_pages: int | None = None, page_offset: int = 0) -> dict[str, Any]:
    lines = [x for x in str(toc_text or "").splitlines() if x.strip()]
    parsed: list[tuple[int, str, int]] = []
    skipped: list[str] = []
    warnings: list[str] = []
    same_page_pairs: list[dict[str, Any]] = []
    offset = int(page_offset or 0)

    for idx, line in enumerate(lines, start=1):
        item = parse_toc_line(line)
        if not item:
            skipped.append(line)
            continue
        title, start_page = item
        parsed.append((idx, title, start_page))

    entries: list[dict[str, Any]] = []
    for i, (line_no, title, start_page_raw) in enumerate(parsed):
        start_page = int(start_page_raw) + offset
        next_line_no = parsed[i + 1][0] if i + 1 < len(parsed) else None
        next_title = parsed[i + 1][1] if i + 1 < len(parsed) else None
        next_start_raw = parsed[i + 1][2] if i + 1 < len(parsed) else None
        next_start = (int(next_start_raw) + offset) if next_start_raw is not None else None
        if next_start is not None:
            end_page = max(start_page, int(next_start) - 1)
            if int(next_start) == start_page:
                warnings.append(
                    f"同页起始: line={line_no} '{title}' -> line={next_line_no} '{next_title}' page={start_page} (可能是章标题+小节)"
                )
                same_page_pairs.append(
                    {
                        "line_no": int(line_no),
                        "title": str(title),
                        "next_line_no": int(next_line_no or 0),
                        "next_title": str(next_title or ""),
                        "page": int(start_page),
                    }
                )
            elif int(next_start) < start_page:
                warnings.append(
                    f"目录页码未递增: line={line_no} start={start_page} next={next_start} (offset={offset})"
                )
        elif total_pages is not None:
            end_page = max(start_page, int(total_pages))
        else:
            end_page = start_page

        if start_page <= 0:
            warnings.append(
                f"目录页经偏移后<=0: line={line_no} raw_start={start_page_raw} offset={offset}, 需人工校正"
            )

        if total_pages is not None and start_page > int(total_pages):
            warnings.append(
                f"目录页超范围: line={line_no} start={start_page} total_pages={int(total_pages)} (offset={offset})"
            )
        if total_pages is not None:
            end_page = min(int(end_page), int(total_pages))

        entries.append(
            {
                "line_no": line_no,
                "title": title,
                "level": infer_toc_level(title),
                "start_page_raw": int(start_page_raw),
                "end_page_raw": int(next_start_raw - 1) if next_start_raw is not None else None,
                "start_page": int(start_page),
                "end_page": int(end_page),
            }
        )

    if not entries:
        warnings.append("未解析出有效目录条目，请使用“标题 ...... 页码”格式")

    return {
        "schema_version": TOC_SCHEMA_VERSION,
        "raw_line_count": len(lines),
        "parsed_count": len(entries),
        "skipped_count": len(skipped),
        "skipped_lines": skipped[:30],
        "warnings": warnings,
        "same_page_pairs": same_page_pairs[:200],
        "entries": entries,
        "total_pages": total_pages,
        "page_offset": offset,
        "generated_at": now_iso(),
    }


def decode_image_payload(raw_data: Any) -> tuple[bytes, str]:
    raw = str(raw_data or "").strip()
    if not raw:
        raise ValueError("image_data_url is required")

    mime_type = "image/png"
    b64_payload = raw
    data_url = ""
    if "," in raw and raw.lower().startswith("data:"):
        header, b64_payload = raw.split(",", 1)
        data_url = raw
        m = re.match(r"^data:([^;]+);base64$", header.strip(), flags=re.IGNORECASE)
        if m:
            mime_type = str(m.group(1) or "image/png").strip() or "image/png"

    try:
        image_bytes = base64.b64decode(b64_payload, validate=True)
    except Exception:
        try:
            image_bytes = base64.b64decode(b64_payload)
        except Exception as exc:
            raise ValueError("invalid base64 image payload") from exc
    if not image_bytes:
        raise ValueError("empty image payload")

    if not data_url:
        data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    return image_bytes, data_url


def _extract_text_from_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                t = str(item.get("type") or "").strip().lower()
                if t == "text":
                    txt = str(item.get("text") or "").strip()
                    if txt:
                        parts.append(txt)
                    continue
                txt2 = str(item.get("text") or "").strip()
                if txt2:
                    parts.append(txt2)
        return "\n".join([x for x in parts if x]).strip()
    return ""


def _extract_llm_output_text(payload: dict[str, Any]) -> str:
    output_text = ""
    choices = payload.get("choices") if isinstance(payload.get("choices"), list) else []
    if choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        msg = first.get("message") if isinstance(first.get("message"), dict) else {}
        output_text = _extract_text_from_message_content(msg.get("content"))
    if not output_text and isinstance(payload.get("output_text"), str):
        output_text = str(payload.get("output_text") or "").strip()
    if not output_text and isinstance(payload.get("output"), list):
        chunks: list[str] = []
        for item in payload.get("output") or []:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and str(part.get("type") or "").lower() == "output_text":
                        txt = str(part.get("text") or "").strip()
                        if txt:
                            chunks.append(txt)
        output_text = "\n".join(chunks).strip()
    return str(output_text or "").strip()


def _entries_to_toc_text(entries: Any) -> str:
    if not isinstance(entries, list):
        return ""
    lines: list[str] = []
    for row in entries:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        page = row.get("page")
        if page is None:
            page = row.get("start_page")
        page_text = str(page or "").strip()
        if not page_text:
            continue
        lines.append(f"{title} ...... {page_text}")
    return "\n".join(lines).strip()


def _unwrap_llm_output_to_toc_text(raw_text: str) -> str:
    text = str(raw_text or "").strip()
    if not text:
        return ""

    fenced = re.search(r"```(?:json|text|txt)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = str(fenced.group(1) or "").strip()

    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            if isinstance(obj.get("toc_text"), str) and obj.get("toc_text").strip():
                return str(obj.get("toc_text")).strip()
            from_entries = _entries_to_toc_text(obj.get("entries"))
            if from_entries:
                return from_entries
        if isinstance(obj, list):
            from_entries = _entries_to_toc_text(obj)
            if from_entries:
                return from_entries
    except Exception:
        pass
    return text


def build_llm_chat_completions_url(base_url: str) -> str:
    base = str(base_url or "").strip()
    if not base:
        raise ValueError("llm.base_url is required")
    lower = base.lower().rstrip("/")
    if lower.endswith("/v1/chat/completions") or lower.endswith("/chat/completions"):
        return base
    parsed = urlparse(base)
    norm_path = str(parsed.path or "").strip().rstrip("/").lower()
    # 常见 OpenAI 兼容基址：
    # - .../v1
    # - .../api/v3（如火山方舟）
    # - .../v3
    if norm_path.endswith("/v1") or norm_path.endswith("/api/v3") or re.search(r"/v\d+$", norm_path):
        return f"{base.rstrip('/')}/chat/completions"
    return f"{base.rstrip('/')}/v1/chat/completions"


def call_llm_toc_extract(
    *,
    image_data_url: str,
    prompt: str,
    base_url: str,
    api_key: str,
    model: str,
    timeout_sec: int,
    max_tokens: int = 1800,
    allow_empty: bool = False,
) -> dict[str, Any]:
    url = build_llm_chat_completions_url(base_url)
    if not str(api_key or "").strip():
        raise ValueError("llm.api_key is required")
    if not str(model or "").strip():
        raise ValueError("llm.model is required")

    body = {
        "model": str(model).strip(),
        "temperature": 0,
        "max_tokens": max(16, int(max_tokens)),
        "messages": [
            {
                "role": "system",
                "content": "你是严格的目录识别器，只返回目录文本。",
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": str(prompt).strip()},
                    {"type": "image_url", "image_url": {"url": str(image_data_url)}},
                ],
            },
        ],
    }
    req = urlrequest.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=max(10, int(timeout_sec))) as resp:
            raw_bytes = resp.read()
    except urlerror.HTTPError as exc:
        detail = ""
        try:
            detail = (exc.read() or b"").decode("utf-8", errors="ignore")[:1200]
        except Exception:
            detail = ""
        raise RuntimeError(f"llm_http_error: {exc.code} {detail}".strip())
    except Exception as exc:
        raise RuntimeError(f"llm_request_failed: {exc}") from exc

    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"llm_response_not_json: {exc}") from exc

    output_text = _extract_llm_output_text(payload)

    toc_text = _unwrap_llm_output_to_toc_text(output_text)
    if not toc_text and not allow_empty:
        raise RuntimeError("llm_empty_output")
    return {
        "toc_text": toc_text,
        "raw_output_text": output_text,
        "raw_payload": payload,
    }


def call_llm_text_probe(
    *,
    base_url: str,
    api_key: str,
    model: str,
    timeout_sec: int,
) -> dict[str, Any]:
    url = build_llm_chat_completions_url(base_url)
    if not str(api_key or "").strip():
        raise ValueError("llm.api_key is required")
    if not str(model or "").strip():
        raise ValueError("llm.model is required")

    body = {
        "model": str(model).strip(),
        "temperature": 0,
        "max_tokens": 32,
        "messages": [
            {
                "role": "system",
                "content": "你是连通性检测助手。",
            },
            {
                "role": "user",
                "content": "请仅回复OK",
            },
        ],
    }
    req = urlrequest.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlrequest.urlopen(req, timeout=max(6, min(30, int(timeout_sec)))) as resp:
            raw_bytes = resp.read()
    except urlerror.HTTPError as exc:
        detail = ""
        try:
            detail = (exc.read() or b"").decode("utf-8", errors="ignore")[:1200]
        except Exception:
            detail = ""
        raise RuntimeError(f"llm_http_error: {exc.code} {detail}".strip())
    except Exception as exc:
        raise RuntimeError(f"llm_request_failed: {exc}") from exc
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"llm_response_not_json: {exc}") from exc

    output_text = _extract_llm_output_text(payload)
    return {
        "output_text": output_text,
        "elapsed_ms": elapsed_ms,
        "raw_payload": payload,
    }


def _read_llm_toc_config_file() -> dict[str, Any]:
    if not LLM_TOC_CONFIG_PATH.exists():
        return {}
    try:
        payload = json.loads(LLM_TOC_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def load_llm_toc_config() -> dict[str, Any]:
    file_cfg = _read_llm_toc_config_file()
    base_url = str(file_cfg.get("base_url") or LLM_TOC_BASE_URL or "").strip()
    model = str(file_cfg.get("model") or LLM_TOC_MODEL or "").strip()
    api_key = str(file_cfg.get("api_key") or LLM_TOC_API_KEY or "").strip()
    prompt = str(file_cfg.get("prompt") or DEFAULT_LLM_TOC_PROMPT or "").strip()
    return {
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
        "prompt": prompt,
        "updated_at": str(file_cfg.get("updated_at") or ""),
    }


def save_llm_toc_config(
    *,
    base_url: str,
    model: str,
    api_key: str,
    prompt: str,
    remember_api_key: bool = True,
) -> dict[str, Any]:
    clean_base = str(base_url or "").strip()
    clean_model = str(model or "").strip()
    clean_prompt = str(prompt or "").strip() or DEFAULT_LLM_TOC_PROMPT
    clean_key = str(api_key or "").strip() if remember_api_key else ""
    payload = {
        "schema_version": "bookflow.toc_llm_config.v1",
        "updated_at": now_iso(),
        "base_url": clean_base,
        "model": clean_model,
        "api_key": clean_key,
        "prompt": clean_prompt,
    }
    LLM_TOC_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LLM_TOC_CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _image_file_to_data_url(path: Path) -> str:
    mime = str(mimetypes.guess_type(path.name)[0] or "").strip() or "image/jpeg"
    raw = path.read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def persist_llm_toc_run(run_payload: dict[str, Any]) -> str:
    out_dir = resolve_runtime_path(LLM_TOC_RUN_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_id = f"llm_{timestamp}_{uuid.uuid4().hex[:10]}"
    out_path = (out_dir / f"{run_id}.json").resolve()
    payload = {
        "schema_version": "bookflow.toc_llm_run.v1",
        "run_id": run_id,
        "created_at": now_iso(),
        **(run_payload or {}),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path.as_posix()


def _import_job_snapshot(job_id: str) -> dict[str, Any] | None:
    with IMPORT_JOBS_LOCK:
        job = IMPORT_JOBS.get(str(job_id))
        if not isinstance(job, dict):
            return None
        return dict(job)


def _import_job_update(job_id: str, **patch: Any) -> None:
    jid = str(job_id)
    with IMPORT_JOBS_LOCK:
        job = IMPORT_JOBS.get(jid)
        if not isinstance(job, dict):
            return
        job.update(patch)
        job["updated_at"] = now_iso()


def _run_import_job(job_id: str, *, cmd: list[str], env: dict[str, str], repo_root: Path) -> None:
    stderr_lines: list[str] = []
    stdout_text = ""
    proc: subprocess.Popen[str] | None = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(repo_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            bufsize=1,
        )
        _import_job_update(job_id, pid=proc.pid)

        if proc.stderr is not None:
            for raw_line in iter(proc.stderr.readline, ""):
                line = str(raw_line or "").rstrip("\n")
                if not line:
                    continue
                stderr_lines.append(line)
                matched = IMPORT_JOB_PROGRESS_RE.match(line.strip())
                if matched:
                    cur = max(0, int(matched.group(1)))
                    total = max(1, int(matched.group(2)))
                    current_file = str(matched.group(3) or "").strip()
                    percent = round((cur / total) * 100, 1) if total > 0 else 0.0
                    _import_job_update(
                        job_id,
                        progress_current=cur,
                        progress_total=total,
                        progress_percent=percent,
                        current_file=current_file,
                    )

        if proc.stdout is not None:
            stdout_text = proc.stdout.read() or ""
        return_code = int(proc.wait())

        summary: dict[str, Any] = {}
        if stdout_text.strip():
            try:
                summary = json.loads(stdout_text)
            except Exception:
                summary = {}

        failed_items: list[dict[str, Any]] = []
        if isinstance(summary.get("results"), list):
            for row in summary.get("results") or []:
                if isinstance(row, dict) and str(row.get("status") or "") == "error":
                    failed_items.append(
                        {
                            "path": row.get("path"),
                            "title": row.get("title"),
                            "error": row.get("error"),
                        }
                    )
                if len(failed_items) >= 20:
                    break

        final_status = "ok"
        if return_code != 0:
            if str(summary.get("status") or "").strip().lower() == "partial":
                final_status = "partial"
            else:
                final_status = "error"

        _import_job_update(
            job_id,
            status=final_status,
            return_code=return_code,
            summary=summary,
            failed_items=failed_items,
            stderr_tail="\n".join(stderr_lines[-120:]),
            completed_at=now_iso(),
        )
    except Exception as exc:
        _import_job_update(
            job_id,
            status="error",
            return_code=-1,
            summary={},
            failed_items=[],
            stderr_tail="\n".join(stderr_lines[-120:]),
            error_message=str(exc),
            completed_at=now_iso(),
        )
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass


def start_import_job(*, cmd: list[str], env: dict[str, str], repo_root: Path, meta: dict[str, Any]) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    job_payload = {
        "job_id": job_id,
        "status": "running",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "completed_at": None,
        "return_code": None,
        "progress_current": 0,
        "progress_total": 0,
        "progress_percent": 0.0,
        "current_file": None,
        "summary": {},
        "failed_items": [],
        "stderr_tail": "",
        "error_message": "",
        "meta": dict(meta),
        "cmd": list(cmd),
    }
    with IMPORT_JOBS_LOCK:
        IMPORT_JOBS[job_id] = job_payload

    thread = threading.Thread(
        target=_run_import_job,
        kwargs={"job_id": job_id, "cmd": list(cmd), "env": dict(env), "repo_root": repo_root},
        name=f"bookflow-import-{job_id[:8]}",
        daemon=True,
    )
    thread.start()
    return dict(job_payload)


def _startup_bootstrap_snapshot() -> dict[str, Any]:
    with STARTUP_BOOTSTRAP_LOCK:
        return dict(STARTUP_BOOTSTRAP_STATE)


def _startup_bootstrap_update(**patch: Any) -> None:
    with STARTUP_BOOTSTRAP_LOCK:
        STARTUP_BOOTSTRAP_STATE.update(patch)
        STARTUP_BOOTSTRAP_STATE["updated_at"] = now_iso()


def _list_bootstrap_supported_files(input_dir: Path, recursive: bool) -> list[Path]:
    suffixes = {".pdf", ".epub", ".txt", ".md", ".markdown", ".json"}
    try:
        if recursive:
            files = [x for x in input_dir.rglob("*") if x.is_file() and x.suffix.lower() in suffixes]
        else:
            files = [x for x in input_dir.iterdir() if x.is_file() and x.suffix.lower() in suffixes]
    except Exception:
        return []
    files.sort(key=lambda p: p.as_posix().lower())
    return files


def _run_startup_import_cycle() -> dict[str, Any]:
    input_dir = resolve_runtime_path(STARTUP_BOOTSTRAP_INPUT_DIR)
    if STORE.backend != "postgres" or not str(DATABASE_URL or "").strip():
        return {
            "status": "skipped",
            "reason": "database_unavailable",
            "input_dir": str(input_dir),
            "imported_count": 0,
            "skipped_count": 0,
            "failure_count": 0,
            "total_files": 0,
        }
    if not input_dir.exists() or not input_dir.is_dir():
        return {
            "status": "skipped",
            "reason": "input_dir_not_found",
            "input_dir": str(input_dir),
            "imported_count": 0,
            "skipped_count": 0,
            "failure_count": 0,
            "total_files": 0,
        }

    files = _list_bootstrap_supported_files(input_dir=input_dir, recursive=bool(STARTUP_BOOTSTRAP_RECURSIVE))
    if not files:
        return {
            "status": "ok",
            "reason": "no_supported_files",
            "input_dir": str(input_dir),
            "imported_count": 0,
            "skipped_count": 0,
            "failure_count": 0,
            "total_files": 0,
        }

    cmd = [
        PYTHON_BIN,
        str((REPO_ROOT / "scripts" / "import_library.py").resolve()),
        "--input-dir",
        str(input_dir),
        "--language",
        STARTUP_BOOTSTRAP_LANGUAGE,
        "--book-type-strategy",
        STARTUP_BOOTSTRAP_BOOK_TYPE_STRATEGY,
        "--default-book-type",
        STARTUP_BOOTSTRAP_DEFAULT_BOOK_TYPE,
        "--fixed-book-type",
        STARTUP_BOOTSTRAP_FIXED_BOOK_TYPE,
        "--pdf-section-storage",
        PDF_SECTION_STORAGE_MODE,
        "--database-url",
        str(DATABASE_URL or ""),
    ]
    if STARTUP_BOOTSTRAP_RECURSIVE:
        cmd.append("--recursive")
    if STARTUP_BOOTSTRAP_SKIP_EXISTING:
        cmd.append("--skip-existing")
    if STARTUP_BOOTSTRAP_RESCAN_APPROVED:
        cmd.append("--rescan-approved")

    env = os.environ.copy()
    env["DATABASE_URL"] = str(DATABASE_URL or "")
    env["BOOKFLOW_PDF_SECTION_STORAGE"] = PDF_SECTION_STORAGE_MODE

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            env=env,
            timeout=max(30, int(STARTUP_BOOTSTRAP_IMPORT_TIMEOUT_SEC)),
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "error",
            "reason": "import_timeout",
            "input_dir": str(input_dir),
            "imported_count": 0,
            "skipped_count": 0,
            "failure_count": 0,
            "total_files": len(files),
            "return_code": -2,
            "stderr_tail": "\n".join(str(exc.stderr or "").splitlines()[-40:]),
        }
    stdout_text = str(proc.stdout or "").strip()
    stderr_text = str(proc.stderr or "").strip()
    summary: dict[str, Any] = {}
    if stdout_text:
        try:
            summary = json.loads(stdout_text)
        except Exception:
            summary = {}
    imported_count = safe_int(summary.get("success_count"), 0) or 0
    skipped_count = safe_int(summary.get("skipped_count"), 0) or 0
    failure_count = safe_int(summary.get("failure_count"), 0) or 0
    total_files = safe_int(summary.get("total_files"), len(files)) or len(files)

    if not summary:
        status = "error"
    elif proc.returncode == 0:
        status = "ok"
    elif str(summary.get("status") or "").strip().lower() == "partial":
        status = "partial"
    else:
        status = "error"

    result: dict[str, Any] = {
        "status": status,
        "input_dir": str(input_dir),
        "imported_count": int(imported_count),
        "skipped_count": int(skipped_count),
        "failure_count": int(failure_count),
        "total_files": int(total_files),
        "return_code": int(proc.returncode),
        "summary": summary if isinstance(summary, dict) else {},
        "stderr_tail": "\n".join(stderr_text.splitlines()[-40:]),
    }

    if STARTUP_BOOTSTRAP_AUTO_APPROVE_IMPORTED:
        approved = 0
        approve_failed = 0
        results = summary.get("results") if isinstance(summary, dict) else []
        for row in (results if isinstance(results, list) else []):
            if not isinstance(row, dict):
                continue
            if str(row.get("status") or "") != "ok":
                continue
            book_id = str(row.get("book_id") or "").strip()
            if not book_id:
                continue
            try:
                STORE.set_toc_review_status(
                    book_id=book_id,
                    review_status="approved",
                    review_note="auto_approved_on_startup",
                )
                approved += 1
            except Exception:
                approve_failed += 1
        result["auto_approved_count"] = int(approved)
        result["auto_approve_failed_count"] = int(approve_failed)

    return result


def _run_startup_feed_warm() -> dict[str, Any]:
    feed_summary: dict[str, Any] = {
        "status": "ok",
        "feed_limit": int(STARTUP_BOOTSTRAP_FEED_LIMIT),
        "feed_items": 0,
        "cover_warm_limit": int(STARTUP_BOOTSTRAP_WARM_COVER_LIMIT),
        "covers_generated": 0,
        "covers_skipped": 0,
        "covers_failed": 0,
        "cover_warm_status": "skipped",
        "cover_warm_error": "",
    }
    try:
        payload = STORE.fetch_feed(
            limit=int(STARTUP_BOOTSTRAP_FEED_LIMIT),
            offset=0,
            user_id=None,
            with_memory=False,
        )
        items = payload.get("items") if isinstance(payload, dict) else []
        feed_summary["feed_items"] = len(items if isinstance(items, list) else [])
    except Exception as exc:
        feed_summary["status"] = "error"
        feed_summary["feed_error"] = str(exc)
        return feed_summary

    if STORE.backend != "postgres" or not str(DATABASE_URL or "").strip() or STARTUP_BOOTSTRAP_WARM_COVER_LIMIT <= 0:
        return feed_summary

    cmd = [
        PYTHON_BIN,
        str((REPO_ROOT / "scripts" / "warm_cover_cache.py").resolve()),
        "--database-url",
        str(DATABASE_URL or ""),
        "--limit",
        str(int(STARTUP_BOOTSTRAP_WARM_COVER_LIMIT)),
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            timeout=max(20, int(STARTUP_BOOTSTRAP_WARM_COVER_TIMEOUT_SEC)),
        )
    except subprocess.TimeoutExpired:
        feed_summary["cover_warm_status"] = "error"
        feed_summary["cover_warm_error"] = "warm_cover_timeout"
        if feed_summary["status"] == "ok":
            feed_summary["status"] = "partial"
        return feed_summary
    out = str(proc.stdout or "").strip()
    payload: dict[str, Any] = {}
    if out:
        try:
            payload = json.loads(out)
        except Exception:
            payload = {}
    feed_summary["cover_warm_status"] = (
        str(payload.get("status") or "").strip().lower()
        if isinstance(payload, dict) and payload
        else ("ok" if proc.returncode == 0 else "error")
    )
    feed_summary["covers_generated"] = safe_int(payload.get("generated"), 0) or 0
    feed_summary["covers_skipped"] = safe_int(payload.get("skipped"), 0) or 0
    feed_summary["covers_failed"] = safe_int(payload.get("failed"), 0) or 0
    if proc.returncode != 0:
        feed_summary["cover_warm_error"] = "\n".join(str(proc.stderr or "").splitlines()[-20:])
        if feed_summary["status"] == "ok":
            feed_summary["status"] = "partial"
    return feed_summary


def run_startup_bootstrap_once() -> dict[str, Any]:
    run_started = now_iso()
    _startup_bootstrap_update(
        running=True,
        status="running",
        last_run_started_at=run_started,
        last_error="",
    )
    cycle_no = int(_startup_bootstrap_snapshot().get("cycle") or 0) + 1
    _startup_bootstrap_update(cycle=cycle_no)
    try:
        import_summary = _run_startup_import_cycle()
        feed_summary = _run_startup_feed_warm()
        status_candidates = [str(import_summary.get("status") or "ok"), str(feed_summary.get("status") or "ok")]
        status = "ok"
        if "error" in status_candidates:
            status = "error"
        elif "partial" in status_candidates:
            status = "partial"
        summary = {
            "cycle": cycle_no,
            "import": import_summary,
            "feed_warm": feed_summary,
        }
        _startup_bootstrap_update(
            running=False,
            status=status,
            last_run_finished_at=now_iso(),
            last_summary=summary,
            last_error="",
        )
        return summary
    except Exception as exc:
        msg = str(exc)[:500]
        _startup_bootstrap_update(
            running=False,
            status="error",
            last_run_finished_at=now_iso(),
            last_error=msg,
        )
        return {
            "cycle": cycle_no,
            "error": msg,
        }


def startup_bootstrap_loop() -> None:
    if not STARTUP_BOOTSTRAP_ENABLED:
        _startup_bootstrap_update(enabled=False, status="disabled", running=False)
        return
    _startup_bootstrap_update(enabled=True, status="starting", running=False, started_at=now_iso())
    delay_sec = max(0, int(STARTUP_BOOTSTRAP_INITIAL_DELAY_SEC))
    if delay_sec > 0:
        time.sleep(delay_sec)
    while True:
        run_startup_bootstrap_once()
        time.sleep(max(30, int(STARTUP_BOOTSTRAP_INTERVAL_SEC)))


def start_startup_bootstrap_thread() -> None:
    if not STARTUP_BOOTSTRAP_ENABLED:
        _startup_bootstrap_update(enabled=False, status="disabled", running=False, started_at=now_iso())
        return
    t = threading.Thread(
        target=startup_bootstrap_loop,
        name="bookflow-startup-bootstrap",
        daemon=True,
    )
    t.start()


def _llm_batch_job_snapshot(job_id: str) -> dict[str, Any] | None:
    with LLM_BATCH_JOBS_LOCK:
        job = LLM_BATCH_JOBS.get(str(job_id))
        if not isinstance(job, dict):
            return None
        return dict(job)


def _llm_batch_job_update(job_id: str, **patch: Any) -> None:
    jid = str(job_id)
    with LLM_BATCH_JOBS_LOCK:
        job = LLM_BATCH_JOBS.get(jid)
        if not isinstance(job, dict):
            return
        job.update(patch)
        job["updated_at"] = now_iso()


def _llm_batch_job_create(*, meta: dict[str, Any]) -> dict[str, Any]:
    job_id = str(uuid.uuid4())
    now = now_iso()
    job_payload = {
        "schema_version": "bookflow.llm_batch_job.v1",
        "job_id": job_id,
        "status": "running",
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "progress_current": 0,
        "progress_total": 0,
        "progress_percent": 0.0,
        "current_page": None,
        "current_attempt": 0,
        "max_attempts": 0,
        "phase": "running",
        "last_error": "",
        "failed_pages": 0,
        "failed_page_numbers": [],
        "line_count": 0,
        "error_message": "",
        "meta": dict(meta or {}),
        "result": None,
    }
    with LLM_BATCH_JOBS_LOCK:
        LLM_BATCH_JOBS[job_id] = job_payload
        if len(LLM_BATCH_JOBS) > 100:
            removable: list[str] = []
            for jid, row in LLM_BATCH_JOBS.items():
                if str(row.get("status") or "") in {"ok", "partial", "error"}:
                    removable.append(jid)
            removable.sort(
                key=lambda jid: str((LLM_BATCH_JOBS.get(jid) or {}).get("updated_at") or ""),
            )
            for jid in removable[: max(0, len(LLM_BATCH_JOBS) - 80)]:
                LLM_BATCH_JOBS.pop(jid, None)
    return dict(job_payload)


class BookFlowStore:
    def __init__(self, dsn: str | None) -> None:
        self.dsn = dsn if dsn and psycopg is not None else None
        self.backend = "postgres" if self.dsn else "memory"
        self.seed_items = load_seed_items()
        self.mem_section_complete: set[tuple[str, str, str]] = set()
        self.mem_idempotency: set[tuple[str, str]] = set()

    def _connect(self):
        if not self.dsn or psycopg is None:
            return None
        return psycopg.connect(
            self.dsn,
            row_factory=dict_row,
            autocommit=True,
            connect_timeout=int(DB_CONNECT_TIMEOUT_SEC),
        )

    def ensure_user(self, user_id: str) -> None:
        if self.backend != "postgres":
            return
        uid = ensure_uuid(user_id)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (id, name, profile)
                    VALUES (%s::uuid, %s, '{}'::jsonb)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (uid, "BookFlow Local User"),
                )

    def set_manual_toc_page_offset(self, *, book_id: str, page_offset: int) -> None:
        if self.backend != "postgres":
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE books
                    SET metadata = COALESCE(metadata, '{}'::jsonb)
                      || jsonb_build_object(
                           'manual_toc_page_offset', %s,
                           'toc_source', 'manual_toc',
                           'needs_manual_toc', false,
                           'toc_review_status', 'pending_review',
                           'review_required', true,
                           'toc_review_updated_at', %s
                         )
                    WHERE id = %s::uuid
                    """,
                    (int(page_offset), now_iso(), ensure_uuid(book_id)),
                )

    def set_toc_review_status(self, *, book_id: str, review_status: str, review_note: str | None = None) -> dict[str, Any]:
        if self.backend != "postgres":
            raise RuntimeError("toc review requires postgres backend")
        status = str(review_status or "").strip().lower()
        if status not in {"pending_review", "approved", "rejected"}:
            raise ValueError("invalid review_status")
        patch: dict[str, Any] = {
            "toc_review_status": status,
            "review_required": status != "approved",
            "toc_review_updated_at": now_iso(),
        }
        if status == "approved":
            patch["toc_reviewed_at"] = now_iso()
        if review_note:
            patch["toc_review_note"] = str(review_note).strip()[:500]

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE books
                    SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                        updated_at = NOW()
                    WHERE id = %s::uuid
                    RETURNING metadata
                    """,
                    (
                        Json(patch) if Json is not None else json.dumps(patch, ensure_ascii=False),
                        ensure_uuid(book_id),
                    ),
                )
                row = cur.fetchone()
        return row.get("metadata") if isinstance((row or {}).get("metadata"), dict) else {}

    def update_book_fingerprint(
        self,
        *,
        book_id: str,
        fingerprint: str,
        force_pending_review: bool = True,
    ) -> dict[str, Any]:
        if self.backend != "postgres":
            raise RuntimeError("book update requires postgres backend")
        fp = str(fingerprint or "").strip().lower()
        patch: dict[str, Any] = {
            "book_fingerprint": fp,
            "toc_outline_written_at": now_iso(),
            "toc_outline_origin": "manual_write_back",
        }
        if force_pending_review:
            patch["toc_review_status"] = "pending_review"
            patch["review_required"] = True
            patch["toc_review_updated_at"] = now_iso()

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE books
                    SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                        updated_at = NOW()
                    WHERE id = %s::uuid
                    RETURNING metadata
                    """,
                    (
                        Json(patch) if Json is not None else json.dumps(patch, ensure_ascii=False),
                        ensure_uuid(book_id),
                    ),
                )
                row = cur.fetchone()
        return row.get("metadata") if isinstance((row or {}).get("metadata"), dict) else {}

    def export_user_state(
        self,
        *,
        user_id: str,
        export_root: Path | None = None,
        include_library_books: bool = True,
    ) -> dict[str, Any]:
        uid = ensure_uuid(user_id)
        out_root = resolve_runtime_path(export_root or USER_EXPORT_ROOT)
        out_root.mkdir(parents=True, exist_ok=True)

        if self.backend != "postgres":
            used_books = sorted({str(x.get("book_id") or "") for x in self.seed_items if str(x.get("book_id") or "").strip()})
            payload = {
                "schema_version": "bookflow.user_export.v1",
                "generated_at": now_iso(),
                "backend": self.backend,
                "user": {
                    "user_id": uid,
                    "name": "BookFlow Local User",
                    "profile": {},
                },
                "library_books": [],
                "used_books": [{"book_id": bid} for bid in used_books],
                "interaction_summary": {
                    "accepted_event_count": 0,
                    "book_count_used": len(used_books),
                },
            }
            out_path = out_root / f"user_{uid}.json"
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return {"saved": True, "export_path": str(out_path), "payload": payload}

        self.ensure_user(uid)
        user_row: dict[str, Any] | None = None
        used_books: list[dict[str, Any]] = []
        interaction_summary: dict[str, Any] = {
            "accepted_event_count": 0,
            "book_count_used": 0,
            "like_count": 0,
            "comment_count": 0,
            "complete_count": 0,
            "impression_dwell_sec_total": 0,
            "last_event_ts": None,
        }
        recent_events: list[dict[str, Any]] = []

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id::text AS user_id, name, profile, created_at, updated_at
                    FROM users
                    WHERE id = %s::uuid
                    """,
                    (uid,),
                )
                user_row = cur.fetchone()

                cur.execute(
                    """
                    SELECT
                      b.id::text AS book_id,
                      b.title AS book_title,
                      COUNT(*)::int AS event_count,
                      COUNT(*) FILTER (WHERE i.event_type = 'like')::int AS like_count,
                      COUNT(*) FILTER (WHERE i.event_type = 'comment')::int AS comment_count,
                      COUNT(*) FILTER (WHERE i.event_type = 'section_complete')::int AS complete_count,
                      COALESCE(SUM(
                        CASE
                          WHEN i.event_type = 'impression'
                            AND COALESCE(i.payload->>'dwell_sec', '') ~ '^[0-9]+$'
                          THEN (i.payload->>'dwell_sec')::int
                          ELSE 0
                        END
                      ), 0)::int AS impression_dwell_sec_total,
                      MIN(i.event_ts) AS first_event_ts,
                      MAX(i.event_ts) AS last_event_ts
                    FROM interactions i
                    JOIN books b ON b.id = i.book_id
                    WHERE i.user_id = %s::uuid
                    GROUP BY b.id, b.title
                    ORDER BY last_event_ts DESC NULLS LAST, event_count DESC
                    """,
                    (uid,),
                )
                book_rows = cur.fetchall()
                for row in book_rows:
                    used_books.append(
                        {
                            "book_id": row["book_id"],
                            "book_title": row.get("book_title"),
                            "event_count": int(row.get("event_count") or 0),
                            "like_count": int(row.get("like_count") or 0),
                            "comment_count": int(row.get("comment_count") or 0),
                            "complete_count": int(row.get("complete_count") or 0),
                            "impression_dwell_sec_total": int(row.get("impression_dwell_sec_total") or 0),
                            "first_event_ts": row.get("first_event_ts").isoformat() if row.get("first_event_ts") else None,
                            "last_event_ts": row.get("last_event_ts").isoformat() if row.get("last_event_ts") else None,
                        }
                    )

                cur.execute(
                    """
                    SELECT
                      COUNT(*)::int AS accepted_event_count,
                      COUNT(*) FILTER (WHERE event_type = 'like')::int AS like_count,
                      COUNT(*) FILTER (WHERE event_type = 'comment')::int AS comment_count,
                      COUNT(*) FILTER (WHERE event_type = 'section_complete')::int AS complete_count,
                      COALESCE(SUM(
                        CASE
                          WHEN event_type = 'impression'
                            AND COALESCE(payload->>'dwell_sec', '') ~ '^[0-9]+$'
                          THEN (payload->>'dwell_sec')::int
                          ELSE 0
                        END
                      ), 0)::int AS impression_dwell_sec_total,
                      MAX(event_ts) AS last_event_ts
                    FROM interactions
                    WHERE user_id = %s::uuid
                    """,
                    (uid,),
                )
                row = cur.fetchone() or {}
                interaction_summary = {
                    "accepted_event_count": int(row.get("accepted_event_count") or 0),
                    "book_count_used": len(used_books),
                    "like_count": int(row.get("like_count") or 0),
                    "comment_count": int(row.get("comment_count") or 0),
                    "complete_count": int(row.get("complete_count") or 0),
                    "impression_dwell_sec_total": int(row.get("impression_dwell_sec_total") or 0),
                    "last_event_ts": row.get("last_event_ts").isoformat() if row.get("last_event_ts") else None,
                }

                cur.execute(
                    """
                    SELECT
                      i.event_id::text AS event_id,
                      i.event_type::text AS event_type,
                      i.event_ts,
                      i.book_id::text AS book_id,
                      i.chunk_id::text AS chunk_id,
                      b.title AS book_title,
                      c.title AS chunk_title
                    FROM interactions i
                    JOIN books b ON b.id = i.book_id
                    JOIN book_chunks c ON c.id = i.chunk_id
                    WHERE i.user_id = %s::uuid
                    ORDER BY i.event_ts DESC
                    LIMIT 120
                    """,
                    (uid,),
                )
                event_rows = cur.fetchall()
                for row in event_rows:
                    recent_events.append(
                        {
                            "event_id": row.get("event_id"),
                            "event_type": row.get("event_type"),
                            "event_ts": row.get("event_ts").isoformat() if row.get("event_ts") else None,
                            "book_id": row.get("book_id"),
                            "book_title": row.get("book_title"),
                            "chunk_id": row.get("chunk_id"),
                            "chunk_title": row.get("chunk_title"),
                        }
                    )

        library_books: list[dict[str, Any]] = []
        if include_library_books:
            library_books = self.list_pdf_books(limit=2000)
            for row in library_books:
                metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
                row["toc_source"] = str(metadata.get("toc_source") or "")
                row["needs_manual_toc"] = bool(metadata.get("needs_manual_toc", False))
                row["materialization_status"] = str(metadata.get("materialization_status") or "")

        payload = {
            "schema_version": "bookflow.user_export.v1",
            "generated_at": now_iso(),
            "backend": self.backend,
            "user": {
                "user_id": uid,
                "name": str((user_row or {}).get("name") or ""),
                "profile": (user_row or {}).get("profile") if isinstance((user_row or {}).get("profile"), dict) else {},
                "created_at": (user_row or {}).get("created_at").isoformat() if (user_row or {}).get("created_at") else None,
                "updated_at": (user_row or {}).get("updated_at").isoformat() if (user_row or {}).get("updated_at") else None,
            },
            "library_books": library_books,
            "used_books": used_books,
            "interaction_summary": interaction_summary,
            "recent_events": recent_events,
        }

        out_path = out_root / f"user_{uid}.json"
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"saved": True, "export_path": str(out_path), "payload": payload}

    def fetch_feed(self, *, limit: int, offset: int, user_id: str | None, with_memory: bool) -> dict[str, Any]:
        fallback_reason = ""
        feed_source = "postgres" if self.backend == "postgres" else "memory"
        if self.backend == "postgres":
            try:
                items = self._fetch_feed_pg(limit=limit + 1, offset=offset, user_id=user_id)
            except Exception as exc:
                # Keep front-end responsive even if DB is busy during startup import.
                items = self._fetch_feed_memory(limit=limit + 1, offset=offset, user_id=user_id)
                feed_source = "memory_fallback"
                fallback_reason = str(exc)[:300]
        else:
            items = self._fetch_feed_memory(limit=limit + 1, offset=offset, user_id=user_id)

        page_items = items[:limit]
        next_cursor = encode_cursor(offset + len(page_items)) if len(items) > limit else None

        memory_inserted = 0
        if with_memory and user_id and offset == 0:
            memory_items = self.fetch_memory_items(user_id=user_id, limit=1)
            if memory_items:
                page_items = [memory_items[0]] + page_items[: max(0, limit - 1)]
                memory_inserted = 1

        return {
            "items": page_items,
            "next_cursor": next_cursor,
            "memory_inserted": memory_inserted,
            "feed_source": feed_source,
            "fallback_reason": fallback_reason,
        }

    def _fetch_feed_memory(self, *, limit: int, offset: int, user_id: str | None) -> list[dict[str, Any]]:
        done: set[str] = set()
        if user_id:
            for uid, cid, _sid in self.mem_section_complete:
                if uid == user_id:
                    done.add(cid)

        ranked = sorted(
            self.seed_items,
            key=lambda x: (
                1 if str(x.get("chunk_id")) in done else 0,
                str(x.get("book_id") or ""),
                int(x.get("global_index") or 0),
            ),
        )
        rows = ranked[offset : offset + limit]
        out: list[dict[str, Any]] = []
        for i, row in enumerate(rows, start=1):
            out.append(
                {
                    "feed_item_id": f"fi_{offset + i:04d}",
                    "item_type": "feed_item",
                    "book_id": str(row.get("book_id") or ""),
                    "book_title": str(row.get("book_title") or "Untitled"),
                    "chunk_id": str(row.get("chunk_id") or ""),
                    "section_id": str(row.get("section_id") or ""),
                    "title": str(row.get("title") or "Untitled"),
                    "teaser_text": str(row.get("teaser_text") or ""),
                    "like_count": 0,
                    "comment_count": 0,
                    "complete_count": 0,
                }
            )
        return out

    def _fetch_feed_pg(self, *, limit: int, offset: int, user_id: str | None) -> list[dict[str, Any]]:
        params: list[Any] = []
        completion_join = ""
        completion_select = "0::int AS done"

        if user_id:
            self.ensure_user(user_id)
            completion_join = """
            LEFT JOIN LATERAL (
              SELECT 1 AS done
              FROM interactions i
              WHERE i.user_id = %s::uuid
                AND i.book_id = c.book_id
                AND i.chunk_id = c.id
                AND i.event_type = 'section_complete'
              LIMIT 1
            ) d ON TRUE
            """
            completion_select = "COALESCE(d.done, 0) AS done"
            params.append(ensure_uuid(user_id))

        sql = f"""
        WITH latest_books AS (
          SELECT DISTINCT ON (COALESCE(NULLIF(b.source_path, ''), b.id::text))
            b.id
          FROM books b
          WHERE b.source_format::text = 'pdf'
          ORDER BY
            COALESCE(NULLIF(b.source_path, ''), b.id::text),
            CASE COALESCE(NULLIF(b.metadata->>'toc_review_status', ''), 'pending_review')
              WHEN 'approved' THEN 0
              WHEN 'pending_review' THEN 1
              WHEN 'rejected' THEN 2
              ELSE 3
            END ASC,
            b.created_at DESC,
            b.id DESC
        ),
        base AS (
          SELECT
            c.id::text AS chunk_id,
            b.id::text AS book_id,
            b.title AS book_title,
            b.source_path,
            c.section_id,
            c.title,
            COALESCE(c.teaser_text, LEFT(c.text_content, 120) || '...') AS teaser_text,
            COALESCE(s.like_count, 0) AS like_count,
            COALESCE(s.comment_count, 0) AS comment_count,
            COALESCE(s.complete_count, 0) AS complete_count,
            c.global_index,
            c.created_at,
            {completion_select},
            ABS(hashtext(c.id::text || to_char(CURRENT_DATE, 'YYYYMMDD'))) %% 1000 AS jitter
          FROM book_chunks c
          JOIN books b ON b.id = c.book_id
          JOIN latest_books lb ON lb.id = b.id
          LEFT JOIN LATERAL (
            SELECT
              COUNT(*) FILTER (WHERE i.event_type = 'like')::int AS like_count,
              COUNT(*) FILTER (WHERE i.event_type = 'comment')::int AS comment_count,
              COUNT(*) FILTER (WHERE i.event_type = 'section_complete')::int AS complete_count
            FROM interactions i
            WHERE i.book_id = c.book_id
              AND i.chunk_id = c.id
          ) s ON TRUE
          {completion_join}
          WHERE COALESCE(c.metadata->>'content_type', '') = 'pdf_section'
            AND COALESCE(b.metadata->>'needs_manual_toc', 'false') <> 'true'
            AND COALESCE(b.metadata->>'materialization_status', 'materialized') <> 'pending_manual_toc'
            AND COALESCE(NULLIF(b.metadata->>'toc_review_status', ''), 'pending_review') = 'approved'
        ),
        ranked AS (
          SELECT
            *,
            ROW_NUMBER() OVER (PARTITION BY book_id ORDER BY global_index ASC, created_at ASC) AS per_book_rank
          FROM base
        )
        SELECT
          chunk_id,
          book_id,
          book_title,
          source_path,
          section_id,
          title,
          teaser_text,
          like_count,
          comment_count,
          complete_count
        FROM ranked
        ORDER BY done ASC, per_book_rank ASC, jitter ASC, created_at DESC
        LIMIT %s OFFSET %s
        """
        params.extend([int(limit), int(offset)])

        with self._connect() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute("SET statement_timeout TO %s", (f"{int(FEED_QUERY_TIMEOUT_MS)}ms",))
                except Exception:
                    pass
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()

        out: list[dict[str, Any]] = []
        for i, row in enumerate(rows, start=1):
            source_path = str(row.get("source_path") or "").strip()
            if source_path:
                source_file = Path(source_path)
                if not source_file.is_absolute():
                    source_file = (Path.cwd() / source_file).resolve()
                else:
                    source_file = source_file.resolve()
                if not source_file.exists():
                    continue
            out.append(
                {
                    "feed_item_id": f"fi_{offset + i:04d}",
                    "item_type": "feed_item",
                    "book_id": row["book_id"],
                    "book_title": row["book_title"],
                    "chunk_id": row["chunk_id"],
                    "section_id": row.get("section_id"),
                    "title": row.get("title"),
                    "teaser_text": row.get("teaser_text"),
                    "like_count": int(row.get("like_count") or 0),
                    "comment_count": int(row.get("comment_count") or 0),
                    "complete_count": int(row.get("complete_count") or 0),
                }
            )
        return out

    def fetch_memory_items(self, *, user_id: str, limit: int) -> list[dict[str, Any]]:
        if self.backend != "postgres":
            return []
        self.ensure_user(user_id)
        sql = """
        SELECT
          mp.id::text AS memory_post_id,
          mp.memory_type,
          mp.source_date,
          mp.post_text,
          b.id::text AS book_id,
          b.title AS book_title,
          c.id::text AS chunk_id,
          c.section_id,
          c.title,
          COALESCE(c.teaser_text, LEFT(c.text_content, 120) || '...') AS teaser_text,
          COALESCE(s.like_count, 0) AS like_count,
          COALESCE(s.comment_count, 0) AS comment_count,
          COALESCE(s.complete_count, 0) AS complete_count
        FROM memory_posts mp
        JOIN books b ON b.id = mp.source_book_id
        JOIN book_chunks c ON c.id = mp.source_chunk_id
        LEFT JOIN LATERAL (
          SELECT
            COUNT(*) FILTER (WHERE i.event_type = 'like')::int AS like_count,
            COUNT(*) FILTER (WHERE i.event_type = 'comment')::int AS comment_count,
            COUNT(*) FILTER (WHERE i.event_type = 'section_complete')::int AS complete_count
          FROM interactions i
          WHERE i.book_id = c.book_id
            AND i.chunk_id = c.id
        ) s ON TRUE
        WHERE mp.user_id = %s::uuid
          AND mp.status = 'inserted'
          AND COALESCE(NULLIF(b.metadata->>'toc_review_status', ''), 'pending_review') = 'approved'
        ORDER BY mp.source_date DESC, mp.created_at DESC
        LIMIT %s
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (ensure_uuid(user_id), int(limit)))
                rows = cur.fetchall()

        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "feed_item_id": f"mem_{row['memory_post_id']}",
                    "item_type": "memory_post",
                    "memory_type": row.get("memory_type"),
                    "memory_source_date": row.get("source_date").isoformat() if row.get("source_date") else None,
                    "book_id": row["book_id"],
                    "book_title": row["book_title"],
                    "chunk_id": row["chunk_id"],
                    "section_id": row.get("section_id"),
                    "title": row.get("title"),
                    "teaser_text": row.get("post_text") or row.get("teaser_text") or "",
                    "like_count": int(row.get("like_count") or 0),
                    "comment_count": int(row.get("comment_count") or 0),
                    "complete_count": int(row.get("complete_count") or 0),
                }
            )
        return out

    def fetch_chunk_detail(self, *, chunk_id: str, book_id: str | None = None) -> dict[str, Any] | None:
        if self.backend == "memory":
            for row in self.seed_items:
                if str(row.get("chunk_id")) != str(chunk_id):
                    continue
                if book_id and str(row.get("book_id")) != str(book_id):
                    continue
                source_anchor = row.get("source_anchor") if isinstance(row.get("source_anchor"), dict) else {}
                metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
                content_type = str(metadata.get("content_type") or "text")
                section_pdf_url = metadata.get("section_pdf_url")
                if not section_pdf_url and content_type == "pdf_section":
                    section_pdf_url = f"/v1/chunk_pdf?book_id={row.get('book_id')}&chunk_id={row.get('chunk_id')}"
                return {
                    "book_id": str(row.get("book_id") or ""),
                    "book_title": str(row.get("book_title") or "Untitled"),
                    "chunk_id": str(row.get("chunk_id") or ""),
                    "section_id": row.get("section_id"),
                    "title": row.get("title"),
                    "teaser_text": row.get("teaser_text"),
                    "text_content": row.get("text_content") or row.get("teaser_text") or "",
                    "content_type": content_type,
                    "section_pdf_url": section_pdf_url,
                    "section_pdf_relpath": metadata.get("section_pdf_relpath"),
                    "page_start": source_anchor.get("page_start"),
                    "page_end": source_anchor.get("page_end"),
                }
            return None

        params: list[Any] = [ensure_uuid(chunk_id)]
        sql = """
        SELECT
          c.id::text AS chunk_id,
          c.book_id::text AS book_id,
          b.title AS book_title,
          c.section_id,
          c.title,
          c.text_content,
          COALESCE(c.teaser_text, LEFT(c.text_content, 120) || '...') AS teaser_text,
          c.source_anchor,
          c.metadata
        FROM book_chunks c
        JOIN books b ON b.id = c.book_id
        WHERE c.id = %s::uuid
        """
        if book_id:
            sql += " AND c.book_id = %s::uuid"
            params.append(ensure_uuid(book_id))

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                row = cur.fetchone()

        if not row:
            return None

        source_anchor = row.get("source_anchor") if isinstance(row.get("source_anchor"), dict) else {}
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        content_type = str(metadata.get("content_type") or "text")
        section_pdf_url = metadata.get("section_pdf_url")
        if not section_pdf_url and content_type == "pdf_section":
            section_pdf_url = f"/v1/chunk_pdf?book_id={row['book_id']}&chunk_id={row['chunk_id']}"

        return {
            "book_id": row["book_id"],
            "book_title": row["book_title"],
            "chunk_id": row["chunk_id"],
            "section_id": row.get("section_id"),
            "title": row.get("title"),
            "teaser_text": row.get("teaser_text"),
            "text_content": row.get("text_content") or "",
            "content_type": content_type,
            "section_pdf_url": section_pdf_url,
            "section_pdf_relpath": metadata.get("section_pdf_relpath"),
            "page_start": source_anchor.get("page_start"),
            "page_end": source_anchor.get("page_end"),
        }

    def fetch_chunk_context(self, *, chunk_id: str, book_id: str | None = None) -> dict[str, Any] | None:
        if self.backend == "memory":
            rows = self.seed_items
            if book_id:
                rows = [x for x in rows if str(x.get("book_id")) == str(book_id)]
            rows = sorted(rows, key=lambda x: (str(x.get("book_id") or ""), int(x.get("global_index") or 0)))
            idx = -1
            for i, row in enumerate(rows):
                if str(row.get("chunk_id")) == str(chunk_id):
                    idx = i
                    break
            if idx < 0:
                return None
            cur = rows[idx]
            prev_item = rows[idx - 1] if idx > 0 else None
            next_item = rows[idx + 1] if idx + 1 < len(rows) else None
            return {
                "book_id": str(cur.get("book_id") or ""),
                "chunk_id": str(cur.get("chunk_id") or ""),
                "title": cur.get("title"),
                "prev_chunk_id": str(prev_item.get("chunk_id")) if prev_item else None,
                "prev_title": prev_item.get("title") if prev_item else None,
                "next_chunk_id": str(next_item.get("chunk_id")) if next_item else None,
                "next_title": next_item.get("title") if next_item else None,
            }

        try:
            chunk_uuid = ensure_uuid(chunk_id)
            book_uuid = ensure_uuid(book_id) if book_id else None
        except Exception:
            return None

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id::text AS chunk_id, book_id::text AS book_id, global_index, title
                    FROM book_chunks
                    WHERE id = %s::uuid
                    """,
                    (chunk_uuid,),
                )
                current = cur.fetchone()
                if not current:
                    return None
                if book_uuid and str(current.get("book_id")) != str(book_uuid):
                    return None

                cur.execute(
                    """
                    SELECT id::text AS chunk_id, title
                    FROM book_chunks
                    WHERE book_id = %s::uuid AND global_index < %s
                    ORDER BY global_index DESC
                    LIMIT 1
                    """,
                    (str(current.get("book_id")), int(current.get("global_index") or 0)),
                )
                prev_row = cur.fetchone()

                cur.execute(
                    """
                    SELECT id::text AS chunk_id, title
                    FROM book_chunks
                    WHERE book_id = %s::uuid AND global_index > %s
                    ORDER BY global_index ASC
                    LIMIT 1
                    """,
                    (str(current.get("book_id")), int(current.get("global_index") or 0)),
                )
                next_row = cur.fetchone()

        return {
            "book_id": current["book_id"],
            "chunk_id": current["chunk_id"],
            "title": current.get("title"),
            "prev_chunk_id": prev_row["chunk_id"] if prev_row else None,
            "prev_title": prev_row.get("title") if prev_row else None,
            "next_chunk_id": next_row["chunk_id"] if next_row else None,
            "next_title": next_row.get("title") if next_row else None,
        }

    def fetch_book_mosaic(self, *, book_id: str, user_id: str | None, min_read_events: int = 1) -> dict[str, Any] | None:
        threshold = max(1, int(min_read_events))

        if self.backend == "memory":
            rows = [x for x in self.seed_items if str(x.get("book_id")) == str(book_id)]
            rows = sorted(rows, key=lambda x: int(x.get("global_index") or 0))
            if not rows:
                return None
            completed = set()
            if user_id:
                for uid, cid, _sid in self.mem_section_complete:
                    if uid == user_id:
                        completed.add(cid)

            tiles: list[dict[str, Any]] = []
            read_count = 0
            for row in rows:
                cid = str(row.get("chunk_id") or "")
                read_events = 1 if cid in completed else 0
                state = "read" if read_events >= threshold else "unread"
                if state == "read":
                    read_count += 1
                tiles.append(
                    {
                        "chunk_id": cid,
                        "global_index": int(row.get("global_index") or 0),
                        "section_id": row.get("section_id"),
                        "chunk_title": row.get("title"),
                        "read_events": read_events,
                        "state": state,
                    }
                )
            total = len(tiles)
            return {
                "book_id": str(book_id),
                "book_title": str(rows[0].get("book_title") or "Untitled"),
                "user_id": user_id,
                "min_read_events": threshold,
                "summary": {
                    "total_chunks": total,
                    "read_chunks": read_count,
                    "unread_chunks": total - read_count,
                    "completion_rate": round(read_count / total, 4) if total > 0 else 0.0,
                },
                "tiles": tiles,
            }

        try:
            book_uuid = ensure_uuid(book_id)
            user_uuid = ensure_uuid(user_id) if user_id else None
        except Exception:
            return None

        if user_uuid:
            self.ensure_user(user_uuid)
            sql = """
            SELECT
              b.title AS book_title,
              c.id::text AS chunk_id,
              c.global_index,
              c.section_id,
              c.title AS chunk_title,
              COALESCE(stats.read_events, 0) AS read_events
            FROM books b
            JOIN book_chunks c ON c.book_id = b.id
            LEFT JOIN LATERAL (
              SELECT COUNT(*)::int AS read_events
              FROM interactions i
              WHERE i.user_id = %s::uuid
                AND i.book_id = c.book_id
                AND i.chunk_id = c.id
                AND i.event_type = 'section_complete'
            ) stats ON TRUE
            WHERE b.id = %s::uuid
            ORDER BY c.global_index ASC
            """
            params = (user_uuid, book_uuid)
        else:
            sql = """
            SELECT
              b.title AS book_title,
              c.id::text AS chunk_id,
              c.global_index,
              c.section_id,
              c.title AS chunk_title,
              0::int AS read_events
            FROM books b
            JOIN book_chunks c ON c.book_id = b.id
            WHERE b.id = %s::uuid
            ORDER BY c.global_index ASC
            """
            params = (book_uuid,)

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()

        if not rows:
            return None

        tiles: list[dict[str, Any]] = []
        read_count = 0
        for row in rows:
            read_events = int(row.get("read_events") or 0)
            state = "read" if read_events >= threshold else "unread"
            if state == "read":
                read_count += 1
            tiles.append(
                {
                    "chunk_id": row["chunk_id"],
                    "global_index": int(row.get("global_index") or 0),
                    "section_id": row.get("section_id"),
                    "chunk_title": row.get("chunk_title"),
                    "read_events": read_events,
                    "state": state,
                }
            )

        total = len(tiles)
        return {
            "book_id": str(book_id),
            "book_title": str(rows[0].get("book_title") or "Untitled"),
            "user_id": user_id,
            "min_read_events": threshold,
            "summary": {
                "total_chunks": total,
                "read_chunks": read_count,
                "unread_chunks": total - read_count,
                "completion_rate": round(read_count / total, 4) if total > 0 else 0.0,
            },
            "tiles": tiles,
        }

    def insert_interactions(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        accepted = 0
        deduplicated = 0
        rejected = 0
        results: list[dict[str, Any]] = []

        if self.backend == "memory":
            for event in events:
                event_id = str(event.get("event_id") or "")
                status, error = self._validate_event(event)
                if status != "ok":
                    rejected += 1
                    results.append({"event_id": event_id, "status": "rejected", "error_code": error})
                    continue

                user_id = str(event.get("user_id"))
                idem = str(event.get("idempotency_key"))
                dedupe_key = (user_id, idem)
                if dedupe_key in self.mem_idempotency:
                    deduplicated += 1
                    results.append({"event_id": event_id, "status": "deduplicated"})
                    continue
                self.mem_idempotency.add(dedupe_key)

                if str(event.get("event_type")) == "section_complete":
                    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                    section_id = str(payload.get("section_id") or "")
                    if section_id:
                        self.mem_section_complete.add((user_id, str(event.get("chunk_id")), section_id))

                accepted += 1
                results.append({"event_id": event_id, "status": "accepted"})

            return {
                "accepted": accepted,
                "deduplicated": deduplicated,
                "rejected": rejected,
                "results": results,
            }

        with self._connect() as conn:
            with conn.cursor() as cur:
                for event in events:
                    event_id = str(event.get("event_id") or "")
                    status, error = self._validate_event(event)
                    if status != "ok":
                        rejected += 1
                        results.append({"event_id": event_id, "status": "rejected", "error_code": error})
                        continue

                    try:
                        user_id = ensure_uuid(str(event.get("user_id")))
                        book_id = ensure_uuid(str(event.get("book_id")))
                        chunk_id = ensure_uuid(str(event.get("chunk_id")))
                        self.ensure_user(user_id)

                        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
                        client = event.get("client") if isinstance(event.get("client"), dict) else {}
                        event_ts = parse_iso(str(event.get("event_ts")))

                        cur.execute(
                            """
                            INSERT INTO interactions (
                              event_id,
                              event_type,
                              event_ts,
                              user_id,
                              session_id,
                              book_id,
                              chunk_id,
                              position_in_chunk,
                              platform,
                              app_version,
                              device_id,
                              idempotency_key,
                              payload
                            ) VALUES (
                              %s::uuid,
                              %s,
                              %s,
                              %s::uuid,
                              %s,
                              %s::uuid,
                              %s::uuid,
                              %s,
                              %s,
                              %s,
                              %s,
                              %s,
                              %s
                            )
                            ON CONFLICT DO NOTHING
                            RETURNING event_id
                            """,
                            (
                                ensure_uuid(event_id),
                                str(event.get("event_type")),
                                event_ts,
                                user_id,
                                str(event.get("session_id") or ""),
                                book_id,
                                chunk_id,
                                float(event.get("position_in_chunk") or 0),
                                str(client.get("platform") or "web"),
                                str(client.get("app_version") or "v0"),
                                str(client.get("device_id") or "") or None,
                                str(event.get("idempotency_key") or ""),
                                Json(payload) if Json is not None else json.dumps(payload),
                            ),
                        )
                        inserted = cur.fetchone()
                        if inserted is None:
                            deduplicated += 1
                            results.append({"event_id": event_id, "status": "deduplicated"})
                        else:
                            accepted += 1
                            results.append({"event_id": event_id, "status": "accepted"})
                    except Exception as exc:
                        msg = str(exc).lower()
                        code = "INVALID_PAYLOAD" if (
                            "foreign key" in msg or "invalid input syntax for type uuid" in msg
                        ) else "INTERNAL_ERROR"
                        rejected += 1
                        results.append({"event_id": event_id, "status": "rejected", "error_code": code})

        return {
            "accepted": accepted,
            "deduplicated": deduplicated,
            "rejected": rejected,
            "results": results,
        }

    def _validate_event(self, event: dict[str, Any]) -> tuple[str, str | None]:
        required = {
            "event_id",
            "event_type",
            "event_ts",
            "user_id",
            "session_id",
            "book_id",
            "chunk_id",
            "position_in_chunk",
            "idempotency_key",
            "client",
        }
        if not isinstance(event, dict):
            return "rejected", "INVALID_PAYLOAD"
        if not required.issubset(set(event.keys())):
            return "rejected", "INVALID_PAYLOAD"

        event_type = str(event.get("event_type"))
        if event_type not in VALID_EVENT_TYPES:
            return "rejected", "INVALID_EVENT_TYPE"

        try:
            pos = float(event.get("position_in_chunk"))
            if pos < 0 or pos > 1:
                return "rejected", "INVALID_POSITION"
        except Exception:
            return "rejected", "INVALID_POSITION"

        try:
            dt = parse_iso(str(event.get("event_ts")))
            if (dt - datetime.now(timezone.utc)).total_seconds() > 600:
                return "rejected", "INVALID_PAYLOAD"
        except Exception:
            return "rejected", "INVALID_PAYLOAD"

        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event_type == "section_complete" and not str(payload.get("section_id") or "").strip():
            return "rejected", "INVALID_PAYLOAD"
        if event_type == "confusion" and not str(payload.get("confusion_type") or "").strip():
            return "rejected", "INVALID_PAYLOAD"
        if event_type == "backtrack":
            if not str(payload.get("from_chunk_id") or "").strip():
                return "rejected", "INVALID_PAYLOAD"
            if not str(payload.get("to_chunk_id") or "").strip():
                return "rejected", "INVALID_PAYLOAD"

        return "ok", None

    def list_pdf_books(self, *, limit: int = 200) -> list[dict[str, Any]]:
        if self.backend != "postgres":
            return []

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH latest_books AS (
                      SELECT DISTINCT ON (COALESCE(NULLIF(source_path, ''), id::text))
                        id,
                        title,
                        source_path,
                        total_pages,
                        total_sections,
                        metadata,
                        created_at
                      FROM books
                      WHERE source_format::text = 'pdf'
                      ORDER BY
                        COALESCE(NULLIF(source_path, ''), id::text),
                        CASE COALESCE(NULLIF(metadata->>'toc_review_status', ''), 'pending_review')
                          WHEN 'approved' THEN 0
                          WHEN 'pending_review' THEN 1
                          WHEN 'rejected' THEN 2
                          ELSE 3
                        END ASC,
                        created_at DESC,
                        id DESC
                    )
                    SELECT
                      b.id::text AS book_id,
                      b.title,
                      b.source_path,
                      b.total_pages,
                      b.total_sections,
                      b.metadata,
                      b.created_at,
                      COALESCE(cs.chunk_count, 0) AS materialized_chunk_count
                    FROM latest_books b
                    LEFT JOIN LATERAL (
                      SELECT COUNT(*)::int AS chunk_count
                      FROM book_chunks c
                      WHERE c.book_id = b.id
                    ) cs ON TRUE
                    ORDER BY b.created_at DESC
                    LIMIT %s
                    """,
                    (max(1, min(1000, int(limit))),),
                )
                rows = cur.fetchall()

        out: list[dict[str, Any]] = []
        for row in rows:
            source_path = row.get("source_path")
            source_text = str(source_path or "").strip()
            if source_text:
                source_file = Path(source_text)
                if not source_file.is_absolute():
                    source_file = (Path.cwd() / source_file).resolve()
                else:
                    source_file = source_file.resolve()
                if not source_file.exists():
                    continue
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            out.append(
                {
                    "book_id": str(row.get("book_id")),
                    "title": str(row.get("title") or "Untitled"),
                    "source_path": source_path,
                    "total_pages": row.get("total_pages"),
                    "total_sections": row.get("total_sections"),
                    "metadata": metadata,
                    "created_at": str(row.get("created_at") or ""),
                    "materialized_chunk_count": int(row.get("materialized_chunk_count") or 0),
                }
            )
        return out

    def get_book(self, book_id: str) -> dict[str, Any] | None:
        if self.backend != "postgres":
            return None
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      id::text AS book_id,
                      title,
                      author,
                      language,
                      book_type::text AS book_type,
                      source_format::text AS source_format,
                      source_path,
                      total_pages,
                      metadata
                    FROM books
                    WHERE id = %s::uuid
                    """,
                    (ensure_uuid(book_id),),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {
            "book_id": row["book_id"],
            "title": str(row.get("title") or "Untitled"),
            "author": row.get("author"),
            "language": str(row.get("language") or "zh"),
            "book_type": str(row.get("book_type") or "general"),
            "source_format": str(row.get("source_format") or "pdf"),
            "source_path": row.get("source_path"),
            "total_pages": safe_int(row.get("total_pages"), None),
            "metadata": row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
        }

    def materialize_from_toc(self, *, book_id: str, entries: list[dict[str, Any]], toc_source: str) -> dict[str, Any]:
        if self.backend != "postgres":
            raise RuntimeError("materialization requires postgres backend")

        book = self.get_book(book_id)
        if book is None:
            raise RuntimeError("book not found")
        if str(book.get("source_format")) != "pdf":
            raise RuntimeError("only pdf books support toc materialization")

        source_path = str(book.get("source_path") or "").strip()
        if not source_path:
            raise RuntimeError("book.source_path is empty")

        pdf_path = Path(source_path)
        if not pdf_path.exists():
            raise RuntimeError(f"source pdf not found: {pdf_path}")

        result = materialize_pdf_sections(
            pdf_path=pdf_path,
            book_id=book_id,
            toc_entries=entries,
            toc_source=toc_source,
            persist_section_pdf=PDF_SECTION_STORAGE_MODE == "precut",
        )

        chunk_records = list(result.get("chunk_records") or [])
        inserted = upsert_book_and_pdf_chunks(
            dsn=str(self.dsn),
            book_id=book_id,
            title=str(book.get("title") or "Untitled"),
            author=book.get("author"),
            language=str(book.get("language") or "zh"),
            book_type=str(book.get("book_type") or "general"),
            source_path=str(pdf_path.resolve()),
            total_pages=safe_int(result.get("total_pages"), book.get("total_pages")),
            source_format="pdf",
            toc_source=toc_source,
            chunk_records=chunk_records,
            replace_existing_chunks=True,
            needs_manual_toc=False,
            manual_toc_entries=entries if toc_source == "manual_toc" else None,
            extra_metadata={
                "toc_warnings": list(result.get("warnings") or [])[:80],
                "failed_entry_count": len(result.get("failed_entries") or []),
                "long_section_warning_count": int(result.get("long_section_warning_count") or 0),
                "pdf_section_storage_mode": PDF_SECTION_STORAGE_MODE,
            },
            processing_status="ready",
            toc_review_status="pending_review",
        )

        out = dict(result)
        out["chunks_upserted"] = int(inserted)
        return out


STORE = BookFlowStore(DATABASE_URL)


class BookFlowHandler(BaseHTTPRequestHandler):
    server_version = "BookFlowV0/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def _authorized(self, *, allow_query_token: bool = False, parsed: Any | None = None) -> bool:
        auth = self.headers.get("Authorization", "")
        if auth == f"Bearer {TOKEN}":
            return True
        if allow_query_token and parsed is not None:
            params = parse_qs(parsed.query)
            token = str(params.get("token", [""])[0] or "")
            return token == TOKEN
        return False

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length > 0 else "{}"
            payload = json.loads(raw) if raw.strip() else {}
            return payload if isinstance(payload, dict) else {}
        except Exception:
            error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "Malformed JSON body")
            return None

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)

        if parsed.path in {"/", "/app", "/app/", "/app/feed", "/app/reader", "/app/book", "/app/toc"} or parsed.path.startswith("/app/"):
            if self.handle_frontend(parsed):
                return

        if parsed.path == "/health":
            return json_response(
                self,
                HTTPStatus.OK,
                {
                    "status": "ok",
                    "time": now_iso(),
                    "backend": STORE.backend,
                    "startup_bootstrap": _startup_bootstrap_snapshot(),
                },
            )

        if parsed.path == "/v1/feed":
            return self.handle_feed(parsed)
        if parsed.path == "/v1/chunk_detail":
            return self.handle_chunk_detail(parsed)
        if parsed.path == "/v1/chunk_context":
            return self.handle_chunk_context(parsed)
        if parsed.path == "/v1/chunk_pdf":
            return self.handle_chunk_pdf(parsed)
        if parsed.path == "/v1/chunk_cover":
            return self.handle_chunk_cover(parsed)
        if parsed.path == "/v1/book_pdf":
            return self.handle_book_pdf(parsed)
        if parsed.path == "/v1/book_page_image":
            return self.handle_book_page_image(parsed)
        if parsed.path == "/v1/book_mosaic":
            return self.handle_book_mosaic(parsed)
        if parsed.path == "/v1/books":
            return self.handle_books(parsed)
        if parsed.path == "/v1/books/import_job":
            return self.handle_books_import_job(parsed)
        if parsed.path == "/v1/user/export":
            return self.handle_user_export(parsed)
        if parsed.path == "/v1/toc/pending":
            return self.handle_toc_pending(parsed)
        if parsed.path == "/v1/toc/annotation":
            return self.handle_toc_annotation(parsed)
        if parsed.path == "/v1/toc/llm_config":
            return self.handle_toc_llm_config_get(parsed)
        if parsed.path == "/v1/toc/llm_extract_pages_job":
            return self.handle_toc_llm_extract_pages_job(parsed)

        return error_response(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "Path not found")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/v1/interactions":
            return self.handle_interactions()
        if parsed.path == "/v1/books/import":
            return self.handle_books_import()
        if parsed.path == "/v1/books/import_start":
            return self.handle_books_import_start()
        if parsed.path == "/v1/toc/preview":
            return self.handle_toc_preview()
        if parsed.path == "/v1/toc/save":
            return self.handle_toc_save()
        if parsed.path == "/v1/toc/review":
            return self.handle_toc_review()
        if parsed.path == "/v1/toc/write_back":
            return self.handle_toc_write_back()
        if parsed.path == "/v1/toc/ocr_extract":
            return self.handle_toc_ocr_extract()
        if parsed.path == "/v1/toc/llm_extract":
            return self.handle_toc_llm_extract()
        if parsed.path == "/v1/toc/ocr_extract_pages":
            return self.handle_toc_ocr_extract_pages()
        if parsed.path == "/v1/toc/llm_extract_pages_start":
            return self.handle_toc_llm_extract_pages_start()
        if parsed.path == "/v1/toc/llm_extract_pages":
            return self.handle_toc_llm_extract_pages()
        if parsed.path == "/v1/toc/llm_config":
            return self.handle_toc_llm_config_save()
        if parsed.path == "/v1/toc/llm_validate":
            return self.handle_toc_llm_validate()

        return error_response(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "Path not found")

    def handle_feed(self, parsed: Any) -> None:
        if not self._authorized(parsed=parsed):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        params = parse_qs(parsed.query)
        limit = safe_int(params.get("limit", ["20"])[0], None)
        if limit is None or limit <= 0 or limit > 50:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "limit must be in 1..50")

        offset = 0
        cursor = str(params.get("cursor", [""])[0] or "").strip()
        if cursor:
            try:
                offset = decode_cursor(cursor)
            except Exception:
                return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "Invalid cursor")

        user_id = str(params.get("user_id", [""])[0] or "").strip() or None
        if user_id:
            try:
                user_id = ensure_uuid(user_id)
            except Exception:
                return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "Invalid user_id")

        with_memory = safe_bool(params.get("with_memory", ["0"])[0], False)
        if with_memory and not user_id:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "with_memory requires user_id")

        try:
            payload = STORE.fetch_feed(limit=int(limit), offset=int(offset), user_id=user_id, with_memory=with_memory)
        except Exception:
            return error_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Failed to fetch feed")

        return json_response(self, HTTPStatus.OK, payload)

    def handle_chunk_detail(self, parsed: Any) -> None:
        if not self._authorized(parsed=parsed):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        params = parse_qs(parsed.query)
        chunk_id = str(params.get("chunk_id", [""])[0] or "").strip()
        book_id = str(params.get("book_id", [""])[0] or "").strip() or None
        if not chunk_id:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "chunk_id is required")

        try:
            detail = STORE.fetch_chunk_detail(chunk_id=chunk_id, book_id=book_id)
        except Exception:
            return error_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Failed to fetch chunk detail")

        if detail is None:
            return error_response(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "Chunk not found")

        return json_response(self, HTTPStatus.OK, detail)

    def handle_chunk_context(self, parsed: Any) -> None:
        if not self._authorized(parsed=parsed):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        params = parse_qs(parsed.query)
        chunk_id = str(params.get("chunk_id", [""])[0] or "").strip()
        book_id = str(params.get("book_id", [""])[0] or "").strip() or None
        if not chunk_id:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "chunk_id is required")

        try:
            payload = STORE.fetch_chunk_context(chunk_id=chunk_id, book_id=book_id)
        except Exception:
            return error_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Failed to fetch chunk context")

        if payload is None:
            return error_response(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "Chunk not found")

        return json_response(self, HTTPStatus.OK, payload)

    def _resolve_chunk_pdf_path(self, *, book_id: str, chunk_id: str) -> Path | None:
        try:
            detail = STORE.fetch_chunk_detail(chunk_id=chunk_id, book_id=book_id)
        except Exception:
            return None
        if not detail:
            return None

        rel_path = str(detail.get("section_pdf_relpath") or "").strip()
        if not rel_path:
            rel_path = str((Path("data/books/derived") / book_id / f"{chunk_id}.pdf").as_posix())

        pdf_path = Path(rel_path)
        if not pdf_path.is_absolute():
            pdf_path = (Path.cwd() / pdf_path).resolve()
        else:
            pdf_path = pdf_path.resolve()

        derived_root = DEFAULT_DERIVED_ROOT
        if not derived_root.is_absolute():
            derived_root = (Path.cwd() / derived_root).resolve()
        else:
            derived_root = derived_root.resolve()

        if not pdf_path.exists() or (derived_root not in pdf_path.parents and pdf_path != derived_root):
            return None

        return pdf_path

    def _resolve_book_source_pdf_path(self, *, book_id: str) -> Path | None:
        try:
            book = STORE.get_book(book_id)
        except Exception:
            return None
        if not book:
            return None
        if str(book.get("source_format") or "").lower() != "pdf":
            return None
        raw = str(book.get("source_path") or "").strip()
        if not raw:
            return None
        path = Path(raw)
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        else:
            path = path.resolve()
        return path if path.exists() and path.is_file() else None

    def _book_page_cache_path(self, *, book_id: str, page: int) -> Path:
        cache_root = resolve_runtime_path(PAGE_CACHE_ROOT)
        cache_dir = cache_root / str(book_id)
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_prefix = cache_dir / f"p_{int(page)}"
        return Path(f"{cache_prefix}.jpg")

    def _ensure_book_page_image_path(self, *, book_id: str, page: int) -> Path | None:
        pdf_path = self._resolve_book_source_pdf_path(book_id=book_id)
        if not pdf_path:
            return None
        page_num = max(1, int(page))
        cache_path = self._book_page_cache_path(book_id=book_id, page=page_num)
        cache_prefix = cache_path.with_suffix("")
        should_generate = is_cache_stale(cache_path, pdf_path, PAGE_CACHE_TTL_SEC)
        if should_generate:
            try:
                subprocess.run(
                    [
                        "pdftoppm",
                        "-jpeg",
                        "-f",
                        str(page_num),
                        "-l",
                        str(page_num),
                        "-singlefile",
                        "-scale-to-x",
                        "1300",
                        "-scale-to-y",
                        "-1",
                        str(pdf_path),
                        str(cache_prefix),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                return None

        return cache_path if cache_path.exists() else None

    def _resolve_chunk_page_range(self, *, book_id: str, chunk_id: str) -> tuple[int, int] | None:
        try:
            detail = STORE.fetch_chunk_detail(chunk_id=chunk_id, book_id=book_id)
        except Exception:
            detail = None
        if not detail:
            return None
        start_page = safe_int(detail.get("page_start"), None)
        end_page = safe_int(detail.get("page_end"), None)
        if start_page is None:
            return None
        start_page = max(1, int(start_page))
        end_page = max(start_page, int(end_page if end_page is not None else start_page))
        return start_page, end_page

    def _chunk_cover_cache_path(self, *, book_id: str, chunk_id: str) -> Path:
        cache_root = resolve_runtime_path(COVER_CACHE_ROOT)
        cache_dir = cache_root / str(book_id)
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / f"{chunk_id}.jpg"

    def _ensure_chunk_cover_image_path(self, *, book_id: str, chunk_id: str) -> Path | None:
        range_pages = self._resolve_chunk_page_range(book_id=book_id, chunk_id=chunk_id)
        source_pdf_path = self._resolve_book_source_pdf_path(book_id=book_id)
        render_pdf_path: Path | None = source_pdf_path
        render_page = int(range_pages[0]) if range_pages else 1

        if render_pdf_path is None:
            section_pdf_path = self._resolve_chunk_pdf_path(book_id=book_id, chunk_id=chunk_id)
            if section_pdf_path is None:
                return None
            render_pdf_path = section_pdf_path
            render_page = 1

        cache_path = self._chunk_cover_cache_path(book_id=book_id, chunk_id=chunk_id)
        cache_prefix = cache_path.with_suffix("")
        should_generate = is_cache_stale(cache_path, render_pdf_path, COVER_CACHE_TTL_SEC)
        if should_generate:
            try:
                subprocess.run(
                    [
                        "pdftoppm",
                        "-jpeg",
                        "-f",
                        str(max(1, int(render_page))),
                        "-l",
                        str(max(1, int(render_page))),
                        "-singlefile",
                        "-scale-to-x",
                        "900",
                        "-scale-to-y",
                        "-1",
                        str(render_pdf_path),
                        str(cache_prefix),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                return None
        return cache_path if cache_path.exists() else None

    def handle_chunk_pdf(self, parsed: Any) -> None:
        if not self._authorized(parsed=parsed, allow_query_token=True):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        params = parse_qs(parsed.query)
        book_id = str(params.get("book_id", [""])[0] or "").strip()
        chunk_id = str(params.get("chunk_id", [""])[0] or "").strip()
        if not book_id or not chunk_id:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "book_id and chunk_id are required")

        body: bytes | None = None
        pdf_path = self._resolve_chunk_pdf_path(book_id=book_id, chunk_id=chunk_id)
        if pdf_path:
            try:
                body = pdf_path.read_bytes()
            except Exception:
                return error_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Failed to read section pdf")

        if body is None:
            body = self._build_chunk_pdf_bytes_from_source(book_id=book_id, chunk_id=chunk_id)
        if body is None:
            return error_response(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "section pdf not found")

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'inline; filename="{chunk_id}.pdf"')
        self.end_headers()
        self.wfile.write(body)

    def _build_chunk_pdf_bytes_from_source(self, *, book_id: str, chunk_id: str) -> bytes | None:
        source_pdf = self._resolve_book_source_pdf_path(book_id=book_id)
        pages = self._resolve_chunk_page_range(book_id=book_id, chunk_id=chunk_id)
        if not source_pdf or not pages or PdfReader is None or PdfWriter is None:
            return None
        start_page, end_page = pages
        try:
            reader = PdfReader(str(source_pdf))
            total = int(len(reader.pages))
            if total <= 0:
                return None
            start_idx = max(1, min(int(start_page), total)) - 1
            end_idx = max(start_idx, min(int(end_page), total) - 1)
            writer = PdfWriter()
            for page_idx in range(start_idx, end_idx + 1):
                writer.add_page(reader.pages[page_idx])
            buff = io.BytesIO()
            writer.write(buff)
            return buff.getvalue()
        except Exception:
            return None

    def handle_chunk_cover(self, parsed: Any) -> None:
        if not self._authorized(parsed=parsed, allow_query_token=True):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        params = parse_qs(parsed.query)
        book_id = str(params.get("book_id", [""])[0] or "").strip()
        chunk_id = str(params.get("chunk_id", [""])[0] or "").strip()
        if not book_id or not chunk_id:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "book_id and chunk_id are required")

        cover_path = self._ensure_chunk_cover_image_path(book_id=book_id, chunk_id=chunk_id)
        if not cover_path:
            return error_response(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "section cover not found")

        try:
            body = cover_path.read_bytes()
        except Exception:
            return error_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Failed to read pdf cover")

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=21600")
        self.end_headers()
        self.wfile.write(body)

    def handle_book_pdf(self, parsed: Any) -> None:
        if not self._authorized(parsed=parsed, allow_query_token=True):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        params = parse_qs(parsed.query)
        book_id = str(params.get("book_id", [""])[0] or "").strip()
        if not book_id:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "book_id is required")

        pdf_path = self._resolve_book_source_pdf_path(book_id=book_id)
        if not pdf_path:
            return error_response(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "book pdf not found")

        try:
            body = pdf_path.read_bytes()
        except Exception:
            return error_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Failed to read book pdf")

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", f'inline; filename="{book_id}.pdf"')
        self.end_headers()
        self.wfile.write(body)

    def handle_book_page_image(self, parsed: Any) -> None:
        if not self._authorized(parsed=parsed, allow_query_token=True):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        params = parse_qs(parsed.query)
        book_id = str(params.get("book_id", [""])[0] or "").strip()
        page = safe_int(params.get("page", ["1"])[0], 1) or 1
        if not book_id:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "book_id is required")
        cache_path = self._ensure_book_page_image_path(book_id=book_id, page=max(1, int(page)))
        if not cache_path:
            return error_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Failed to render book page image")

        try:
            body = cache_path.read_bytes()
        except Exception:
            return error_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Failed to read book page image")

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def handle_books(self, parsed: Any) -> None:
        if not self._authorized(parsed=parsed):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")
        params = parse_qs(parsed.query)
        limit = safe_int(params.get("limit", ["200"])[0], 200) or 200
        limit = max(1, min(2000, int(limit)))
        try:
            books = STORE.list_pdf_books(limit=limit)
        except Exception:
            return error_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Failed to fetch books")
        return json_response(
            self,
            HTTPStatus.OK,
            {
                "schema_version": "bookflow.books.v1",
                "count": len(books),
                "items": books,
            },
        )

    def handle_books_import_job(self, parsed: Any) -> None:
        if not self._authorized(parsed=parsed):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")
        params = parse_qs(parsed.query)
        job_id = str(params.get("job_id", [""])[0] or "").strip()
        if not job_id:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "job_id is required")
        snapshot = _import_job_snapshot(job_id)
        if snapshot is None:
            return error_response(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "import job not found")

        progress_total = max(0, int(snapshot.get("progress_total") or 0))
        progress_current = max(0, int(snapshot.get("progress_current") or 0))
        progress_percent = float(snapshot.get("progress_percent") or 0.0)
        if progress_total > 0:
            progress_percent = max(0.0, min(100.0, round((progress_current / progress_total) * 100, 1)))

        return json_response(
            self,
            HTTPStatus.OK,
            {
                "schema_version": "bookflow.import_job.v1",
                "job_id": snapshot.get("job_id"),
                "status": snapshot.get("status"),
                "created_at": snapshot.get("created_at"),
                "updated_at": snapshot.get("updated_at"),
                "completed_at": snapshot.get("completed_at"),
                "return_code": snapshot.get("return_code"),
                "progress_current": progress_current,
                "progress_total": progress_total,
                "progress_percent": progress_percent,
                "current_file": snapshot.get("current_file"),
                "summary": snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {},
                "failed_items": snapshot.get("failed_items") if isinstance(snapshot.get("failed_items"), list) else [],
                "stderr_tail": str(snapshot.get("stderr_tail") or ""),
                "error_message": str(snapshot.get("error_message") or ""),
                "meta": snapshot.get("meta") if isinstance(snapshot.get("meta"), dict) else {},
            },
        )

    def handle_books_import_start(self) -> None:
        if not self._authorized(parsed=None):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        payload = self._read_json()
        if payload is None:
            return

        input_dir_raw = str(payload.get("input_dir") or "data/books/inbox").strip()
        if not input_dir_raw:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "input_dir is required")
        input_dir = resolve_runtime_path(Path(input_dir_raw))
        if not input_dir.exists() or not input_dir.is_dir():
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", f"input_dir not found: {input_dir}")

        recursive = safe_bool(payload.get("recursive"), True)
        dry_run = safe_bool(payload.get("dry_run"), False)
        limit = safe_int(payload.get("limit"), 0) or 0
        if limit < 0 or limit > 10000:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "limit must be in 0..10000")

        book_type_strategy = str(payload.get("book_type_strategy") or "auto").strip().lower()
        if book_type_strategy not in {"auto", "fixed"}:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "book_type_strategy must be auto|fixed")
        default_book_type = str(payload.get("default_book_type") or "general").strip().lower()
        fixed_book_type = str(payload.get("fixed_book_type") or "technical").strip().lower()
        if default_book_type not in {"general", "fiction", "technical"}:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "invalid default_book_type")
        if fixed_book_type not in {"general", "fiction", "technical"}:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "invalid fixed_book_type")

        language = str(payload.get("language") or "zh").strip() or "zh"
        pdf_section_storage = str(payload.get("pdf_section_storage") or PDF_SECTION_STORAGE_MODE).strip().lower()
        if pdf_section_storage not in {"precut", "on_demand"}:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "pdf_section_storage must be precut|on_demand")

        database_url = str(payload.get("database_url") or DATABASE_URL or "").strip()
        if not dry_run and not database_url:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "DATABASE_URL is required for non-dry-run import")

        cmd = [
            PYTHON_BIN,
            str((REPO_ROOT / "scripts" / "import_library.py").resolve()),
            "--input-dir",
            str(input_dir),
            "--book-type-strategy",
            book_type_strategy,
            "--default-book-type",
            default_book_type,
            "--fixed-book-type",
            fixed_book_type,
            "--language",
            language,
            "--pdf-section-storage",
            pdf_section_storage,
        ]
        if recursive:
            cmd.append("--recursive")
        if limit > 0:
            cmd.extend(["--limit", str(int(limit))])
        if database_url:
            cmd.extend(["--database-url", database_url])
        if dry_run:
            cmd.append("--dry-run")

        env = os.environ.copy()
        if database_url:
            env["DATABASE_URL"] = database_url
        env["BOOKFLOW_PDF_SECTION_STORAGE"] = pdf_section_storage

        job = start_import_job(
            cmd=cmd,
            env=env,
            repo_root=REPO_ROOT,
            meta={
                "input_dir": str(input_dir),
                "recursive": bool(recursive),
                "dry_run": bool(dry_run),
                "pdf_section_storage": pdf_section_storage,
                "book_type_strategy": book_type_strategy,
                "default_book_type": default_book_type,
                "fixed_book_type": fixed_book_type,
                "language": language,
            },
        )

        return json_response(
            self,
            HTTPStatus.OK,
            {
                "status": "running",
                "schema_version": "bookflow.import_job.v1",
                "job_id": job.get("job_id"),
                "created_at": job.get("created_at"),
                "meta": job.get("meta"),
            },
        )

    def handle_books_import(self) -> None:
        if not self._authorized(parsed=None):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        payload = self._read_json()
        if payload is None:
            return

        input_dir_raw = str(payload.get("input_dir") or "data/books/inbox").strip()
        if not input_dir_raw:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "input_dir is required")
        input_dir = resolve_runtime_path(Path(input_dir_raw))
        if not input_dir.exists() or not input_dir.is_dir():
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", f"input_dir not found: {input_dir}")

        recursive = safe_bool(payload.get("recursive"), True)
        dry_run = safe_bool(payload.get("dry_run"), False)
        limit = safe_int(payload.get("limit"), 0) or 0
        if limit < 0 or limit > 10000:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "limit must be in 0..10000")

        book_type_strategy = str(payload.get("book_type_strategy") or "auto").strip().lower()
        if book_type_strategy not in {"auto", "fixed"}:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "book_type_strategy must be auto|fixed")
        default_book_type = str(payload.get("default_book_type") or "general").strip().lower()
        fixed_book_type = str(payload.get("fixed_book_type") or "technical").strip().lower()
        if default_book_type not in {"general", "fiction", "technical"}:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "invalid default_book_type")
        if fixed_book_type not in {"general", "fiction", "technical"}:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "invalid fixed_book_type")

        language = str(payload.get("language") or "zh").strip() or "zh"
        pdf_section_storage = str(payload.get("pdf_section_storage") or PDF_SECTION_STORAGE_MODE).strip().lower()
        if pdf_section_storage not in {"precut", "on_demand"}:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "pdf_section_storage must be precut|on_demand")

        database_url = str(payload.get("database_url") or DATABASE_URL or "").strip()
        if not dry_run and not database_url:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "DATABASE_URL is required for non-dry-run import")

        cmd = [
            PYTHON_BIN,
            str((REPO_ROOT / "scripts" / "import_library.py").resolve()),
            "--input-dir",
            str(input_dir),
            "--book-type-strategy",
            book_type_strategy,
            "--default-book-type",
            default_book_type,
            "--fixed-book-type",
            fixed_book_type,
            "--language",
            language,
            "--pdf-section-storage",
            pdf_section_storage,
        ]
        if recursive:
            cmd.append("--recursive")
        if limit > 0:
            cmd.extend(["--limit", str(int(limit))])
        if database_url:
            cmd.extend(["--database-url", database_url])
        if dry_run:
            cmd.append("--dry-run")

        timeout_sec = max(30, safe_int(payload.get("timeout_sec"), _env_int("BOOKFLOW_IMPORT_TIMEOUT_SEC", 1800)) or 1800)
        env = os.environ.copy()
        if database_url:
            env["DATABASE_URL"] = database_url
        env["BOOKFLOW_PDF_SECTION_STORAGE"] = pdf_section_storage

        try:
            proc = subprocess.run(
                cmd,
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=int(timeout_sec),
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return error_response(self, HTTPStatus.REQUEST_TIMEOUT, "IMPORT_TIMEOUT", f"import timed out after {timeout_sec}s")
        except Exception:
            return error_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Failed to execute import command")

        stdout_text = str(proc.stdout or "").strip()
        stderr_text = str(proc.stderr or "").strip()
        summary: dict[str, Any] = {}
        if stdout_text:
            try:
                summary = json.loads(stdout_text)
            except Exception:
                summary = {}

        status_code = HTTPStatus.OK if proc.returncode == 0 else HTTPStatus.BAD_REQUEST
        response_payload: dict[str, Any] = {
            "status": "ok" if proc.returncode == 0 else "error",
            "return_code": int(proc.returncode),
            "input_dir": str(input_dir),
            "recursive": bool(recursive),
            "dry_run": bool(dry_run),
            "pdf_section_storage": pdf_section_storage,
            "summary": summary,
            "stderr_tail": stderr_text[-2000:],
        }
        failed_items: list[dict[str, Any]] = []
        if isinstance(summary.get("results"), list):
            for row in summary.get("results") or []:
                if isinstance(row, dict) and str(row.get("status") or "") == "error":
                    failed_items.append(
                        {
                            "path": row.get("path"),
                            "title": row.get("title"),
                            "error": row.get("error"),
                        }
                    )
                if len(failed_items) >= 20:
                    break
        if failed_items:
            response_payload["failed_items"] = failed_items
        if proc.returncode != 0:
            summary_status = str(summary.get("status") or "").strip().lower()
            if summary_status == "partial":
                response_payload["status"] = "partial"
                return json_response(self, HTTPStatus.OK, response_payload)
            message = "import failed"
            if isinstance(summary, dict) and summary_status in {"error"}:
                message = f"import_{summary.get('status')}"
            return json_response(
                self,
                status_code,
                {
                    **response_payload,
                    "error": {
                        "code": "IMPORT_FAILED",
                        "message": f"{message}; return_code={proc.returncode}; details in stderr_tail/summary",
                    },
                },
            )

        return json_response(self, HTTPStatus.OK, response_payload)

    def handle_user_export(self, parsed: Any) -> None:
        if not self._authorized(parsed=parsed):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")
        params = parse_qs(parsed.query)
        user_id = str(params.get("user_id", [""])[0] or "").strip()
        if not user_id:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "user_id is required")
        try:
            user_id = ensure_uuid(user_id)
        except Exception:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "Invalid user_id")

        include_library = safe_bool(params.get("include_library_books", ["1"])[0], True)
        export_dir_raw = str(params.get("export_dir", [""])[0] or "").strip()
        export_root = resolve_runtime_path(Path(export_dir_raw)) if export_dir_raw else USER_EXPORT_ROOT

        try:
            result = STORE.export_user_state(
                user_id=user_id,
                export_root=export_root,
                include_library_books=include_library,
            )
        except Exception:
            return error_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Failed to export user state")

        payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
        return json_response(
            self,
            HTTPStatus.OK,
            {
                "status": "ok",
                "schema_version": payload.get("schema_version") or "bookflow.user_export.v1",
                "user_id": user_id,
                "export_path": result.get("export_path"),
                "generated_at": payload.get("generated_at"),
                "library_book_count": len(payload.get("library_books") or []),
                "used_book_count": len(payload.get("used_books") or []),
                "interaction_summary": payload.get("interaction_summary") or {},
            },
        )

    def handle_toc_llm_config_get(self, parsed: Any) -> None:
        if not self._authorized(parsed=parsed):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")
        cfg = load_llm_toc_config()
        return json_response(
            self,
            HTTPStatus.OK,
            {
                "status": "ok",
                "base_url": str(cfg.get("base_url") or ""),
                "model": str(cfg.get("model") or ""),
                "api_key": str(cfg.get("api_key") or ""),
                "has_api_key": bool(str(cfg.get("api_key") or "").strip()),
                "prompt": str(cfg.get("prompt") or DEFAULT_LLM_TOC_PROMPT),
                "updated_at": str(cfg.get("updated_at") or ""),
                "config_file": str(resolve_runtime_path(LLM_TOC_CONFIG_PATH)),
            },
        )

    def handle_toc_llm_config_save(self) -> None:
        if not self._authorized(parsed=None):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")
        payload = self._read_json()
        if payload is None:
            return
        current = load_llm_toc_config()

        base_url = str(payload.get("base_url") if "base_url" in payload else current.get("base_url") or "").strip()
        model = str(payload.get("model") if "model" in payload else current.get("model") or "").strip()
        prompt = str(payload.get("prompt") if "prompt" in payload else current.get("prompt") or DEFAULT_LLM_TOC_PROMPT).strip()
        remember_api_key = safe_bool(payload.get("remember_api_key"), True)

        if "api_key" in payload:
            api_key = str(payload.get("api_key") or "").strip()
        else:
            api_key = str(current.get("api_key") or "").strip()

        saved = save_llm_toc_config(
            base_url=base_url,
            model=model,
            api_key=api_key,
            prompt=prompt,
            remember_api_key=remember_api_key,
        )
        return json_response(
            self,
            HTTPStatus.OK,
            {
                "status": "ok",
                "base_url": str(saved.get("base_url") or ""),
                "model": str(saved.get("model") or ""),
                "api_key": str(saved.get("api_key") or ""),
                "has_api_key": bool(str(saved.get("api_key") or "").strip()),
                "prompt": str(saved.get("prompt") or DEFAULT_LLM_TOC_PROMPT),
                "updated_at": str(saved.get("updated_at") or ""),
                "config_file": str(resolve_runtime_path(LLM_TOC_CONFIG_PATH)),
            },
        )

    def _resolve_llm_request_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        saved_cfg = load_llm_toc_config()
        llm_cfg = payload.get("llm") if isinstance(payload.get("llm"), dict) else {}
        base_url = str(
            llm_cfg.get("base_url")
            or payload.get("base_url")
            or saved_cfg.get("base_url")
            or ""
        ).strip()
        api_key = str(
            llm_cfg.get("api_key")
            or payload.get("api_key")
            or saved_cfg.get("api_key")
            or ""
        ).strip()
        model = str(
            llm_cfg.get("model")
            or payload.get("model")
            or saved_cfg.get("model")
            or ""
        ).strip()
        prompt = str(payload.get("prompt") or saved_cfg.get("prompt") or DEFAULT_LLM_TOC_PROMPT).strip()
        timeout_sec = safe_int(payload.get("timeout_sec"), 90) or 90
        remember_config = safe_bool(payload.get("remember_config"), True)
        remember_api_key = safe_bool(payload.get("remember_api_key"), True)
        return {
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
            "prompt": prompt,
            "timeout_sec": max(10, int(timeout_sec)),
            "remember_config": bool(remember_config),
            "remember_api_key": bool(remember_api_key),
        }

    def _run_llm_validation(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        prompt: str,
        timeout_sec: int,
        book_id: str | None = None,
        page: int | None = None,
        include_image_probe: bool = True,
    ) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        valid = True
        resolved_url = ""

        try:
            resolved_url = build_llm_chat_completions_url(base_url)
            checks.append({"name": "base_url", "status": "ok", "detail": resolved_url})
        except Exception as exc:
            valid = False
            checks.append({"name": "base_url", "status": "failed", "detail": str(exc)})

        if not str(model or "").strip():
            valid = False
            checks.append({"name": "model", "status": "failed", "detail": "llm.model is required"})
        else:
            checks.append({"name": "model", "status": "ok", "detail": str(model)})

        if not str(api_key or "").strip():
            valid = False
            checks.append({"name": "api_key", "status": "failed", "detail": "llm.api_key is required"})
        else:
            masked = f"{str(api_key)[:6]}***{str(api_key)[-4:]}" if len(str(api_key)) >= 12 else "***"
            checks.append({"name": "api_key", "status": "ok", "detail": f"present({masked})"})

        if valid:
            try:
                probe = call_llm_text_probe(
                    base_url=base_url,
                    api_key=api_key,
                    model=model,
                    timeout_sec=max(6, min(30, int(timeout_sec))),
                )
                checks.append(
                    {
                        "name": "text_probe",
                        "status": "ok",
                        "detail": f"ok ({probe.get('elapsed_ms')} ms)",
                        "output_excerpt": str(probe.get("output_text") or "")[:200],
                    }
                )
            except Exception as exc:
                valid = False
                checks.append({"name": "text_probe", "status": "failed", "detail": str(exc)[:500]})

        if include_image_probe and valid:
            image_data_url = ""
            probe_image_desc = "tiny_png"
            probe_page = safe_int(page, None)
            if book_id and probe_page and probe_page > 0:
                img_path = self._ensure_book_page_image_path(book_id=book_id, page=int(probe_page))
                if not img_path:
                    valid = False
                    checks.append(
                        {
                            "name": "page_image",
                            "status": "failed",
                            "detail": f"book page image not ready (book_id={book_id}, page={int(probe_page)})",
                        }
                    )
                else:
                    try:
                        image_data_url = _image_file_to_data_url(img_path)
                        probe_image_desc = f"book_page:{int(probe_page)}"
                        checks.append(
                            {
                                "name": "page_image",
                                "status": "ok",
                                "detail": f"ready: {img_path}",
                            }
                        )
                    except Exception as exc:
                        valid = False
                        checks.append({"name": "page_image", "status": "failed", "detail": str(exc)[:300]})
            else:
                image_data_url = TINY_PNG_DATA_URL
                checks.append({"name": "page_image", "status": "warn", "detail": "no page supplied, using tiny image probe"})

            if image_data_url and valid:
                try:
                    vision = call_llm_toc_extract(
                        image_data_url=image_data_url,
                        prompt=str(prompt or "请只回复OK"),
                        base_url=base_url,
                        api_key=api_key,
                        model=model,
                        timeout_sec=max(10, min(45, int(timeout_sec))),
                        max_tokens=96,
                        allow_empty=True,
                    )
                    out_excerpt = str(vision.get("raw_output_text") or vision.get("toc_text") or "")[:200]
                    checks.append(
                        {
                            "name": "vision_probe",
                            "status": "ok" if out_excerpt else "warn",
                            "detail": f"ok ({probe_image_desc})",
                            "output_excerpt": out_excerpt,
                        }
                    )
                except Exception as exc:
                    valid = False
                    checks.append({"name": "vision_probe", "status": "failed", "detail": str(exc)[:500]})

        failed = [x for x in checks if str(x.get("status") or "") == "failed"]
        warning = [x for x in checks if str(x.get("status") or "") == "warn"]
        return {
            "valid": bool(valid),
            "resolved_url": resolved_url,
            "checks": checks,
            "failed_count": len(failed),
            "warn_count": len(warning),
            "failed_reasons": [str(x.get("detail") or "") for x in failed][:10],
        }

    def handle_toc_llm_validate(self) -> None:
        if not self._authorized(parsed=None):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        payload = self._read_json()
        if payload is None:
            return

        cfg = self._resolve_llm_request_config(payload)
        book_id = str(payload.get("book_id") or "").strip()
        page = safe_int(payload.get("page"), None)
        if page is None:
            page = safe_int(payload.get("page_start"), None)
        include_image_probe = safe_bool(payload.get("include_image_probe"), True)

        if cfg.get("remember_config"):
            try:
                save_llm_toc_config(
                    base_url=str(cfg.get("base_url") or ""),
                    model=str(cfg.get("model") or ""),
                    api_key=str(cfg.get("api_key") or ""),
                    prompt=str(cfg.get("prompt") or DEFAULT_LLM_TOC_PROMPT),
                    remember_api_key=bool(cfg.get("remember_api_key")),
                )
            except Exception:
                pass

        validation = self._run_llm_validation(
            base_url=str(cfg.get("base_url") or ""),
            api_key=str(cfg.get("api_key") or ""),
            model=str(cfg.get("model") or ""),
            prompt=str(cfg.get("prompt") or DEFAULT_LLM_TOC_PROMPT),
            timeout_sec=int(cfg.get("timeout_sec") or 90),
            book_id=book_id or None,
            page=page,
            include_image_probe=include_image_probe,
        )
        return json_response(
            self,
            HTTPStatus.OK,
            {
                "status": "ok" if validation.get("valid") else "invalid",
                "validation": validation,
                "llm": {
                    "base_url": str(cfg.get("base_url") or ""),
                    "resolved_url": str(validation.get("resolved_url") or ""),
                    "model": str(cfg.get("model") or ""),
                    "has_api_key": bool(str(cfg.get("api_key") or "").strip()),
                },
            },
        )

    def handle_toc_ocr_extract_pages(self) -> None:
        if not self._authorized(parsed=None):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        payload = self._read_json()
        if payload is None:
            return

        engine = get_ocr_engine()
        if engine is None:
            return error_response(self, HTTPStatus.SERVICE_UNAVAILABLE, "OCR_UNAVAILABLE", "OCR engine not available")

        book_id = str(payload.get("book_id") or "").strip()
        page_start = safe_int(payload.get("page_start"), None)
        page_end = safe_int(payload.get("page_end"), None)
        if not book_id:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "book_id is required")
        if page_start is None or page_end is None:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "page_start and page_end are required")
        if page_start <= 0 or page_end <= 0:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "page_start/page_end must be >= 1")
        if page_start > page_end:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "page_start must be <= page_end")
        if page_end - page_start + 1 > 120:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "page range too large (max 120 pages)")

        total_pages = safe_int(payload.get("total_pages"), None)
        page_offset = safe_int(payload.get("page_offset"), 0) or 0

        page_results: list[dict[str, Any]] = []
        merged_lines: list[str] = []

        for page in range(int(page_start), int(page_end) + 1):
            img_path = self._ensure_book_page_image_path(book_id=book_id, page=page)
            if not img_path:
                page_results.append(
                    {
                        "page": page,
                        "status": "failed",
                        "line_count": 0,
                        "lines": [],
                    }
                )
                continue

            try:
                result, _elapsed = engine(str(img_path))
            except Exception:
                page_results.append(
                    {
                        "page": page,
                        "status": "failed",
                        "line_count": 0,
                        "lines": [],
                    }
                )
                continue

            lines: list[str] = []
            for item in result or []:
                text_val = ""
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    text_val = str(item[1] or "").strip()
                elif isinstance(item, dict):
                    text_val = str(item.get("text") or "").strip()
                if text_val:
                    lines.append(text_val)
                    merged_lines.append(text_val)

            page_results.append(
                {
                    "page": page,
                    "status": "ok",
                    "line_count": len(lines),
                    "lines": lines[:500],
                }
            )

        toc_text = "\n".join(merged_lines)
        preview = (
            build_toc_preview(toc_text, total_pages=total_pages, page_offset=int(page_offset))
            if toc_text
            else build_toc_preview("", total_pages=total_pages, page_offset=int(page_offset))
        )

        return json_response(
            self,
            HTTPStatus.OK,
            {
                "status": "ok",
                "engine": "rapidocr_onnxruntime",
                "book_id": book_id,
                "page_start": int(page_start),
                "page_end": int(page_end),
                "page_count": int(page_end) - int(page_start) + 1,
                "line_count": len(merged_lines),
                "lines": merged_lines[:2000],
                "toc_text": toc_text,
                "page_results": page_results,
                "preview": preview,
            },
        )

    def handle_book_mosaic(self, parsed: Any) -> None:
        if not self._authorized(parsed=parsed):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        params = parse_qs(parsed.query)
        book_id = str(params.get("book_id", [""])[0] or "").strip()
        if not book_id:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "book_id is required")

        user_id = str(params.get("user_id", [""])[0] or "").strip() or None
        if user_id:
            try:
                user_id = ensure_uuid(user_id)
            except Exception:
                return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "Invalid user_id")

        min_read_events = safe_int(params.get("min_read_events", ["1"])[0], None)
        if min_read_events is None or min_read_events <= 0 or min_read_events > 20:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "min_read_events must be in 1..20")

        try:
            payload = STORE.fetch_book_mosaic(book_id=book_id, user_id=user_id, min_read_events=int(min_read_events))
        except Exception:
            return error_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Failed to fetch book mosaic")

        if payload is None:
            return error_response(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "Book not found")

        payload["schema_version"] = "bookflow.book_mosaic.v0"
        return json_response(self, HTTPStatus.OK, payload)

    def handle_interactions(self) -> None:
        if not self._authorized(parsed=None):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        payload = self._read_json()
        if payload is None:
            return

        events = payload.get("events")
        if not isinstance(events, list):
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "events must be a list")
        if len(events) > 200:
            return error_response(self, HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "TOO_MANY_EVENTS", "events max is 200")

        try:
            result = STORE.insert_interactions(events)
        except Exception:
            return error_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Failed to write interactions")

        auto_exported_users: list[str] = []
        if AUTO_EXPORT_USER_STATE and int(result.get("accepted") or 0) > 0:
            accepted_ids: set[str] = set()
            for idx, event in enumerate(events):
                status = ""
                if idx < len(result.get("results") or []):
                    status = str((result.get("results") or [])[idx].get("status") or "")
                if status != "accepted":
                    continue
                uid = str((event or {}).get("user_id") or "").strip()
                try:
                    accepted_ids.add(ensure_uuid(uid))
                except Exception:
                    continue
            for uid in sorted(accepted_ids):
                try:
                    STORE.export_user_state(user_id=uid, export_root=USER_EXPORT_ROOT, include_library_books=True)
                    auto_exported_users.append(uid)
                except Exception:
                    continue

        if auto_exported_users:
            result["auto_exported_user_ids"] = auto_exported_users

        return json_response(self, HTTPStatus.OK, result)

    def handle_toc_pending(self, parsed: Any) -> None:
        if not self._authorized(parsed=parsed):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        params = parse_qs(parsed.query)
        limit = safe_int(params.get("limit", ["100"])[0], 100) or 100
        limit = max(1, min(500, int(limit)))

        toc_store_payload = read_toc_store()
        annotations = toc_store_payload.get("annotations") if isinstance(toc_store_payload.get("annotations"), dict) else {}
        fingerprint_annotations = toc_store_payload.get("fingerprint_annotations") if isinstance(toc_store_payload.get("fingerprint_annotations"), dict) else {}
        source_path_fingerprints = toc_store_payload.get("source_path_fingerprints") if isinstance(toc_store_payload.get("source_path_fingerprints"), dict) else {}
        books = STORE.list_pdf_books(limit=max(limit * 3, 100))
        source_cache: dict[str, str] = {}

        pending: list[dict[str, Any]] = []
        annotated: list[dict[str, Any]] = []

        for row in books:
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            book_id = str(row.get("book_id") or "")
            ann, ann_key, ann_match_by = resolve_manual_toc_annotation(
                annotations=annotations if isinstance(annotations, dict) else {},
                fingerprint_annotations=fingerprint_annotations,
                source_path_fingerprints=source_path_fingerprints,
                book_id=book_id,
                book_source_path=str(row.get("source_path") or ""),
                book_fingerprint=str(metadata.get("book_fingerprint") or ""),
                store=STORE,
                source_cache=source_cache,
            )

            toc_source = str(metadata.get("toc_source") or ("manual_toc" if ann else "pending_manual_toc"))
            materialized_chunk_count = int(row.get("materialized_chunk_count") or metadata.get("materialized_chunk_count") or 0)
            materialization_status = str(
                metadata.get("materialization_status")
                or ("materialized" if materialized_chunk_count > 0 else "pending_manual_toc")
            )
            toc_review_status = str(metadata.get("toc_review_status") or "pending_review").strip().lower()
            if toc_review_status not in {"pending_review", "approved", "rejected"}:
                toc_review_status = "pending_review"
            needs_manual_toc = bool(metadata.get("needs_manual_toc", False))
            if not needs_manual_toc and materialized_chunk_count <= 0:
                needs_manual_toc = toc_source in {"pending_manual_toc", "pending"} and not bool(ann)

            item = {
                "book_id": book_id,
                "title": row.get("title"),
                "source_path": row.get("source_path"),
                "total_pages": row.get("total_pages"),
                "total_sections": row.get("total_sections"),
                "created_at": row.get("created_at"),
                "book_fingerprint": str(metadata.get("book_fingerprint") or ""),
                "has_manual_toc": bool(ann),
                "manual_toc_entry_count": int((ann or {}).get("entry_count", 0) or 0),
                "manual_toc_updated_at": (ann or {}).get("updated_at"),
                "manual_toc_matched_book_id": ann_key,
                "manual_toc_match_by": ann_match_by,
                "manual_toc_file": (ann or {}).get("normalized_file"),
                "needs_manual_toc": needs_manual_toc,
                "toc_source": toc_source,
                "materialization_status": materialization_status,
                "materialized_chunk_count": materialized_chunk_count,
                "toc_review_status": toc_review_status,
                "review_required": toc_review_status != "approved",
                "is_feed_visible": toc_review_status == "approved",
                "page_offset": safe_int(
                    (ann or {}).get("page_offset") if isinstance(ann, dict) else None,
                    safe_int(metadata.get("manual_toc_page_offset"), 0) or 0,
                )
                or 0,
            }

            if toc_review_status != "approved":
                pending.append(item)
            else:
                annotated.append(item)

            if len(pending) >= limit and len(annotated) >= limit:
                break

        return json_response(
            self,
            HTTPStatus.OK,
            {
                "schema_version": TOC_SCHEMA_VERSION,
                "pending": pending[:limit],
                "annotated": annotated[:limit],
                "pending_count": len(pending),
                "annotated_count": len(annotated),
            },
        )

    def handle_toc_annotation(self, parsed: Any) -> None:
        if not self._authorized(parsed=parsed):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        params = parse_qs(parsed.query)
        book_id = str(params.get("book_id", [""])[0] or "").strip()
        if not book_id:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "book_id is required")

        store_payload = read_toc_store()
        annotations = store_payload.get("annotations") if isinstance(store_payload.get("annotations"), dict) else {}
        fingerprint_annotations = store_payload.get("fingerprint_annotations") if isinstance(store_payload.get("fingerprint_annotations"), dict) else {}
        source_path_fingerprints = store_payload.get("source_path_fingerprints") if isinstance(store_payload.get("source_path_fingerprints"), dict) else {}
        book = STORE.get_book(book_id)
        metadata = (book or {}).get("metadata") if isinstance((book or {}).get("metadata"), dict) else {}
        source_path = normalize_source_path((book or {}).get("source_path"))
        book_fingerprint = str(metadata.get("book_fingerprint") or "").strip().lower()
        if not book_fingerprint and source_path:
            try:
                src_path = Path(source_path)
                if src_path.exists():
                    book_fingerprint = compute_file_sha256(src_path)
            except Exception:
                book_fingerprint = ""
        annotation, ann_key, match_by = resolve_manual_toc_annotation(
            annotations=annotations,
            fingerprint_annotations=fingerprint_annotations,
            source_path_fingerprints=source_path_fingerprints,
            book_id=book_id,
            book_source_path=str((book or {}).get("source_path") or ""),
            book_fingerprint=book_fingerprint,
            store=STORE,
            source_cache={},
        )
        if not annotation:
            return error_response(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "manual toc annotation not found")

        if ann_key and ann_key != book_id:
            migrated = dict(annotation)
            migrated["book_id"] = book_id
            if source_path:
                migrated["source_path"] = source_path
            if book_fingerprint:
                migrated["book_fingerprint"] = book_fingerprint
            migrated["aliased_from_book_id"] = ann_key
            migrated["alias_matched_by"] = match_by
            migrated["updated_at"] = now_iso()
            migrated = upsert_toc_annotation_in_store(
                store_payload=store_payload,
                book_id=book_id,
                annotation=migrated,
            )
            write_toc_store(store_payload)
            annotation = migrated

        return json_response(
            self,
            HTTPStatus.OK,
            {
                "schema_version": TOC_SCHEMA_VERSION,
                "book_id": book_id,
                "match_by": match_by,
                "matched_annotation_book_id": ann_key,
                "annotation": annotation,
            },
        )

    def handle_toc_preview(self) -> None:
        if not self._authorized(parsed=None):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        payload = self._read_json()
        if payload is None:
            return

        toc_text = str(payload.get("toc_text") or "")
        if not toc_text.strip():
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "toc_text is required")

        book_id = str(payload.get("book_id") or "").strip()
        total_pages = safe_int(payload.get("total_pages"), None)
        page_offset = safe_int(payload.get("page_offset"), 0) or 0
        if total_pages is None and book_id:
            book = STORE.get_book(book_id)
            if book:
                total_pages = safe_int(book.get("total_pages"), None)

        preview = build_toc_preview(toc_text, total_pages=total_pages, page_offset=int(page_offset))
        preview["book_id"] = book_id or None
        return json_response(self, HTTPStatus.OK, preview)

    def handle_toc_save(self) -> None:
        if not self._authorized(parsed=None):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        payload = self._read_json()
        if payload is None:
            return

        book_id = str(payload.get("book_id") or "").strip()
        page_offset = safe_int(payload.get("page_offset"), 0) or 0
        if not book_id:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "book_id is required")

        entries = payload.get("entries")
        if not isinstance(entries, list):
            toc_text = str(payload.get("toc_text") or "")
            if not toc_text.strip():
                return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "entries(list) or toc_text is required")

            total_pages = safe_int(payload.get("total_pages"), None)
            if total_pages is None:
                book = STORE.get_book(book_id)
                if book:
                    total_pages = safe_int(book.get("total_pages"), None)
            entries = build_toc_preview(toc_text, total_pages=total_pages, page_offset=int(page_offset)).get("entries", [])

        normalized, warnings = normalize_toc_entries(entries)

        if not normalized:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "no valid toc entries")

        store_payload = read_toc_store()
        book = STORE.get_book(book_id)
        source_path_norm = normalize_source_path((book or {}).get("source_path"))
        metadata = (book or {}).get("metadata") if isinstance((book or {}).get("metadata"), dict) else {}
        book_fingerprint = str(metadata.get("book_fingerprint") or "").strip().lower()
        if not book_fingerprint and source_path_norm:
            try:
                source_file = Path(source_path_norm)
                if source_file.exists():
                    book_fingerprint = compute_file_sha256(source_file)
            except Exception:
                book_fingerprint = ""
        annotation: dict[str, Any] = {
            "schema_version": TOC_SCHEMA_VERSION,
            "book_id": book_id,
            "entry_count": len(normalized),
            "updated_at": now_iso(),
            "source": "manual_batch_paste",
            "toc_source": "manual_toc",
            "page_offset": int(page_offset),
            "entries": normalized,
            "warnings": warnings,
        }
        if source_path_norm:
            annotation["source_path"] = source_path_norm
        if book_fingerprint:
            annotation["book_fingerprint"] = book_fingerprint
        annotation = upsert_toc_annotation_in_store(
            store_payload=store_payload,
            book_id=book_id,
            annotation=annotation,
        )
        write_toc_store(store_payload)

        materialized_chunks = 0
        generated_pdf_count = 0
        failed_entries: list[dict[str, Any]] = []
        chunks_upserted = 0

        try:
            result = STORE.materialize_from_toc(book_id=book_id, entries=normalized, toc_source="manual_toc")
            materialized_chunks = int(result.get("materialized_chunks") or 0)
            generated_pdf_count = int(result.get("generated_pdf_count") or 0)
            failed_entries = list(result.get("failed_entries") or [])
            chunks_upserted = int(result.get("chunks_upserted") or materialized_chunks)
            warnings.extend([str(x) for x in (result.get("warnings") or [])])
        except Exception as exc:
            warnings.append(f"materialization_failed: {exc}")

        try:
            STORE.set_manual_toc_page_offset(book_id=book_id, page_offset=int(page_offset))
        except Exception:
            pass

        return json_response(
            self,
            HTTPStatus.OK,
            {
                "status": "ok" if materialized_chunks > 0 else "partial",
                "schema_version": TOC_SCHEMA_VERSION,
                "book_id": book_id,
                "entry_count": len(normalized),
                "toc_source": "manual_toc",
                "page_offset": int(page_offset),
                "pdf_section_storage_mode": PDF_SECTION_STORAGE_MODE,
                "materialized_chunks": materialized_chunks,
                "generated_pdf_count": generated_pdf_count,
                "chunks_upserted": chunks_upserted,
                "failed_entries": failed_entries,
                "warnings": warnings,
                "toc_review_status": "pending_review",
                "review_required": True,
            },
        )

    def handle_toc_review(self) -> None:
        if not self._authorized(parsed=None):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        payload = self._read_json()
        if payload is None:
            return

        book_id = str(payload.get("book_id") or "").strip()
        review_status = str(payload.get("review_status") or "approved").strip().lower()
        review_note = str(payload.get("review_note") or "").strip()
        if not book_id:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "book_id is required")
        if review_status not in {"pending_review", "approved", "rejected"}:
            return error_response(
                self,
                HTTPStatus.BAD_REQUEST,
                "INVALID_PAYLOAD",
                "review_status must be pending_review|approved|rejected",
            )

        try:
            metadata = STORE.set_toc_review_status(
                book_id=book_id,
                review_status=review_status,
                review_note=review_note or None,
            )
        except ValueError as exc:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", str(exc))
        except Exception:
            return error_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Failed to update review status")

        return json_response(
            self,
            HTTPStatus.OK,
            {
                "status": "ok",
                "book_id": book_id,
                "toc_review_status": review_status,
                "review_required": review_status != "approved",
                "metadata": metadata,
            },
        )

    def handle_toc_write_back(self) -> None:
        if not self._authorized(parsed=None):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")
        if PdfReader is None or PdfWriter is None:
            return error_response(self, HTTPStatus.SERVICE_UNAVAILABLE, "PDF_UNAVAILABLE", "pypdf is not available")

        payload = self._read_json()
        if payload is None:
            return

        book_id = str(payload.get("book_id") or "").strip()
        if not book_id:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "book_id is required")

        book = STORE.get_book(book_id)
        if not book:
            return error_response(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "Book not found")
        if str(book.get("source_format") or "").lower() != "pdf":
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "Only PDF supports toc write-back")

        source_path_norm = normalize_source_path(book.get("source_path"))
        if not source_path_norm:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "book.source_path is empty")
        source_path = Path(source_path_norm)
        if not source_path.exists() or not source_path.is_file():
            return error_response(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "source pdf not found")

        old_metadata = book.get("metadata") if isinstance(book.get("metadata"), dict) else {}
        old_fingerprint = str(old_metadata.get("book_fingerprint") or "").strip().lower()

        input_entries = payload.get("entries")
        annotation: dict[str, Any] | None = None
        if not isinstance(input_entries, list) or not input_entries:
            store_payload = read_toc_store()
            annotations = store_payload.get("annotations") if isinstance(store_payload.get("annotations"), dict) else {}
            fp_map = (
                store_payload.get("fingerprint_annotations")
                if isinstance(store_payload.get("fingerprint_annotations"), dict)
                else {}
            )
            src_fp_map = (
                store_payload.get("source_path_fingerprints")
                if isinstance(store_payload.get("source_path_fingerprints"), dict)
                else {}
            )
            annotation, _ann_key, _match_by = resolve_manual_toc_annotation(
                annotations=annotations,
                fingerprint_annotations=fp_map,
                source_path_fingerprints=src_fp_map,
                book_id=book_id,
                book_source_path=source_path_norm,
                book_fingerprint=old_fingerprint,
                store=STORE,
                source_cache={},
            )
            if not annotation:
                return error_response(
                    self,
                    HTTPStatus.BAD_REQUEST,
                    "INVALID_PAYLOAD",
                    "entries missing and saved annotation not found",
                )
            input_entries = list(annotation.get("entries") or [])

        normalized, warnings = normalize_toc_entries(input_entries)
        if not normalized:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "no valid toc entries")

        temp_path: Path | None = None
        outline_written = 0
        try:
            reader = PdfReader(str(source_path))
            total_pages = int(len(reader.pages))
            if total_pages <= 0:
                return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "source pdf has no pages")

            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)

            parents: dict[int, Any] = {}
            for entry in normalized:
                title = str(entry.get("title") or "").strip() or "Untitled"
                level = max(1, int(safe_int(entry.get("level"), 1) or 1))
                start_page = max(1, int(safe_int(entry.get("start_page"), 1) or 1))
                page_idx = min(total_pages - 1, start_page - 1)
                parent = parents.get(level - 1) if level > 1 else None
                node = writer.add_outline_item(title=title, page_number=page_idx, parent=parent)
                parents[level] = node
                for lv in list(parents.keys()):
                    if lv > level:
                        parents.pop(lv, None)
                outline_written += 1

            with tempfile.NamedTemporaryFile(
                mode="wb",
                delete=False,
                dir=str(source_path.parent),
                prefix=f"{source_path.stem}.tmp_",
                suffix=".pdf",
            ) as tmp_fh:
                writer.write(tmp_fh)
                temp_path = Path(tmp_fh.name)

            os.replace(str(temp_path), str(source_path))
        except Exception as exc:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            return error_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", f"write_back_failed: {exc}")

        try:
            new_fingerprint = compute_file_sha256(source_path)
        except Exception:
            new_fingerprint = ""

        try:
            STORE.update_book_fingerprint(
                book_id=book_id,
                fingerprint=new_fingerprint,
                force_pending_review=True,
            )
        except Exception:
            pass

        store_payload = read_toc_store()
        page_offset_from_payload = safe_int(payload.get("page_offset"), None)
        page_offset = page_offset_from_payload if page_offset_from_payload is not None else safe_int((annotation or {}).get("page_offset"), 0)
        merged_annotation: dict[str, Any] = {
            "schema_version": TOC_SCHEMA_VERSION,
            "book_id": book_id,
            "entry_count": len(normalized),
            "updated_at": now_iso(),
            "source": "manual_write_back",
            "toc_source": "manual_toc",
            "page_offset": int(page_offset or 0),
            "entries": normalized,
            "warnings": warnings,
            "source_path": source_path_norm,
            "book_fingerprint": new_fingerprint,
        }
        if isinstance(annotation, dict):
            merged_annotation = {
                **annotation,
                **merged_annotation,
            }
        merged_annotation = upsert_toc_annotation_in_store(
            store_payload=store_payload,
            book_id=book_id,
            annotation=merged_annotation,
        )
        write_toc_store(store_payload)

        try:
            STORE.set_manual_toc_page_offset(book_id=book_id, page_offset=int(page_offset or 0))
        except Exception:
            pass

        return json_response(
            self,
            HTTPStatus.OK,
            {
                "status": "ok",
                "book_id": book_id,
                "source_path": source_path_norm,
                "outline_items_written": int(outline_written),
                "old_fingerprint": old_fingerprint,
                "new_fingerprint": new_fingerprint,
                "toc_review_status": "pending_review",
                "review_required": True,
                "warning_count": len(warnings),
                "normalized_file": merged_annotation.get("normalized_file"),
            },
        )

    def handle_toc_llm_extract(self) -> None:
        if not self._authorized(parsed=None):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        payload = self._read_json()
        if payload is None:
            return

        try:
            _image_bytes, image_data_url = decode_image_payload(payload.get("image_data_url") or payload.get("image_base64"))
        except ValueError as exc:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", str(exc))

        cfg = self._resolve_llm_request_config(payload)
        base_url = str(cfg.get("base_url") or "").strip()
        api_key = str(cfg.get("api_key") or "").strip()
        model = str(cfg.get("model") or "").strip()
        prompt = str(cfg.get("prompt") or DEFAULT_LLM_TOC_PROMPT).strip()
        timeout_sec = int(cfg.get("timeout_sec") or 90)
        remember_config = bool(cfg.get("remember_config"))
        remember_api_key = bool(cfg.get("remember_api_key"))

        if not base_url:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "llm.base_url is required")
        if not api_key:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "llm.api_key is required")
        if not model:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "llm.model is required")

        validate_first = safe_bool(payload.get("validate_first"), False)
        validation: dict[str, Any] | None = None
        if validate_first:
            book_id = str(payload.get("book_id") or "").strip()
            page = safe_int(payload.get("page"), None)
            validation = self._run_llm_validation(
                base_url=base_url,
                api_key=api_key,
                model=model,
                prompt=prompt,
                timeout_sec=max(10, min(45, int(timeout_sec))),
                book_id=book_id or None,
                page=page,
                include_image_probe=True,
            )
            if not bool(validation.get("valid")):
                failed_reasons = list(validation.get("failed_reasons") or [])
                reason = failed_reasons[0] if failed_reasons else "LLM validation failed"
                return json_response(
                    self,
                    HTTPStatus.BAD_REQUEST,
                    {
                        "error": {
                            "code": "LLM_INVALID_CONFIG",
                            "message": f"LLM preflight failed: {reason}",
                        },
                        "validation": validation,
                    },
                )

        if remember_config:
            try:
                save_llm_toc_config(
                    base_url=base_url,
                    model=model,
                    api_key=api_key,
                    prompt=prompt,
                    remember_api_key=remember_api_key,
                )
            except Exception:
                pass

        try:
            llm_result = call_llm_toc_extract(
                image_data_url=image_data_url,
                prompt=prompt,
                base_url=base_url,
                api_key=api_key,
                model=model,
                timeout_sec=max(10, int(timeout_sec)),
            )
        except ValueError as exc:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", str(exc))
        except Exception as exc:
            return error_response(self, HTTPStatus.BAD_GATEWAY, "LLM_REQUEST_FAILED", str(exc))

        toc_text = str(llm_result.get("toc_text") or "").strip()
        total_pages = safe_int(payload.get("total_pages"), None)
        page_offset = safe_int(payload.get("page_offset"), 0) or 0
        preview = (
            build_toc_preview(toc_text, total_pages=total_pages, page_offset=int(page_offset))
            if toc_text
            else build_toc_preview("", total_pages=total_pages, page_offset=int(page_offset))
        )

        lines = [x for x in toc_text.splitlines() if x.strip()]
        saved_result_file = ""
        try:
            saved_result_file = persist_llm_toc_run(
                {
                    "mode": "single_image",
                    "book_id": str(payload.get("book_id") or ""),
                    "page": safe_int(payload.get("page"), None),
                    "line_count": len(lines),
                    "toc_text": toc_text,
                    "preview": preview,
                    "llm": {
                        "model": model,
                        "base_url": build_llm_chat_completions_url(base_url),
                    },
                    "raw_output_excerpt": str(llm_result.get("raw_output_text") or "")[:2000],
                }
            )
        except Exception:
            saved_result_file = ""

        return json_response(
            self,
            HTTPStatus.OK,
            {
                "status": "ok",
                "engine": "llm",
                "model": model,
                "base_url": build_llm_chat_completions_url(base_url),
                "line_count": len(lines),
                "toc_text": toc_text,
                "lines": lines[:500],
                "preview": preview,
                "raw_output_excerpt": str(llm_result.get("raw_output_text") or "")[:1200],
                "saved_result_file": saved_result_file,
            },
        )

    def _parse_optional_page_list(self, raw: Any) -> list[int]:
        if raw is None:
            return []
        values: list[Any] = []
        if isinstance(raw, list):
            values = list(raw)
        elif isinstance(raw, str):
            text = str(raw).strip()
            values = re.split(r"[,\s]+", text) if text else []
        else:
            return []
        out: list[int] = []
        seen: set[int] = set()
        for item in values:
            num = safe_int(item, None)
            if num is None or int(num) <= 0:
                continue
            page = int(num)
            if page in seen:
                continue
            seen.add(page)
            out.append(page)
        out.sort()
        return out

    def _prepare_llm_extract_pages_request(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        book_id = str(payload.get("book_id") or "").strip()
        page_start = safe_int(payload.get("page_start"), None)
        page_end = safe_int(payload.get("page_end"), None)
        if not book_id:
            error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "book_id is required")
            return None
        if page_start is None or page_end is None:
            error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "page_start and page_end are required")
            return None
        page_start = int(page_start)
        page_end = int(page_end)
        if page_start <= 0 or page_end <= 0:
            error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "page_start/page_end must be >= 1")
            return None
        if page_start > page_end:
            error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "page_start must be <= page_end")
            return None
        if page_end - page_start + 1 > 120:
            error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "page range too large (max 120 pages)")
            return None

        pages = self._parse_optional_page_list(payload.get("pages"))
        if pages:
            if len(pages) > 120:
                error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "pages too large (max 120)")
                return None
            invalid_pages = [x for x in pages if x < page_start or x > page_end]
            if invalid_pages:
                error_response(
                    self,
                    HTTPStatus.BAD_REQUEST,
                    "INVALID_PAYLOAD",
                    f"pages out of range: {','.join([str(x) for x in invalid_pages[:20]])}",
                )
                return None
        else:
            pages = list(range(page_start, page_end + 1))

        cfg = self._resolve_llm_request_config(payload)
        base_url = str(cfg.get("base_url") or "").strip()
        api_key = str(cfg.get("api_key") or "").strip()
        model = str(cfg.get("model") or "").strip()
        prompt = str(cfg.get("prompt") or DEFAULT_LLM_TOC_PROMPT).strip()
        timeout_sec = int(cfg.get("timeout_sec") or 90)
        remember_config = bool(cfg.get("remember_config"))
        remember_api_key = bool(cfg.get("remember_api_key"))
        if not base_url:
            error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "llm.base_url is required")
            return None
        if not api_key:
            error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "llm.api_key is required")
            return None
        if not model:
            error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", "llm.model is required")
            return None

        max_retries_per_page = safe_int(payload.get("max_retries_per_page"), 2)
        if max_retries_per_page is None:
            max_retries_per_page = 2
        max_retries_per_page = max(0, min(8, int(max_retries_per_page)))
        retry_backoff_ms = safe_int(payload.get("retry_backoff_ms"), 700)
        if retry_backoff_ms is None:
            retry_backoff_ms = 700
        retry_backoff_ms = max(0, min(10000, int(retry_backoff_ms)))

        return {
            "book_id": book_id,
            "page_start": page_start,
            "page_end": page_end,
            "pages": pages,
            "total_pages": safe_int(payload.get("total_pages"), None),
            "page_offset": safe_int(payload.get("page_offset"), 0) or 0,
            "validate_first": safe_bool(payload.get("validate_first"), True),
            "base_url": base_url,
            "api_key": api_key,
            "model": model,
            "prompt": prompt,
            "timeout_sec": max(10, int(timeout_sec)),
            "remember_config": remember_config,
            "remember_api_key": remember_api_key,
            "max_retries_per_page": max_retries_per_page,
            "retry_backoff_ms": retry_backoff_ms,
        }

    def _execute_llm_extract_pages(
        self,
        *,
        request_payload: dict[str, Any],
        validation: dict[str, Any] | None = None,
        progress_hook: Any | None = None,
    ) -> dict[str, Any]:
        book_id = str(request_payload.get("book_id") or "").strip()
        page_start = int(request_payload.get("page_start") or 1)
        page_end = int(request_payload.get("page_end") or page_start)
        pages = [int(x) for x in (request_payload.get("pages") or []) if safe_int(x, None)]
        total_pages = safe_int(request_payload.get("total_pages"), None)
        page_offset = int(request_payload.get("page_offset") or 0)
        prompt = str(request_payload.get("prompt") or DEFAULT_LLM_TOC_PROMPT)
        base_url = str(request_payload.get("base_url") or "")
        api_key = str(request_payload.get("api_key") or "")
        model = str(request_payload.get("model") or "")
        timeout_sec = max(10, int(request_payload.get("timeout_sec") or 90))
        max_retries_per_page = max(0, int(request_payload.get("max_retries_per_page") or 0))
        retry_backoff_ms = max(0, int(request_payload.get("retry_backoff_ms") or 0))

        try:
            llm_base_url = build_llm_chat_completions_url(base_url)
        except Exception:
            llm_base_url = str(base_url or "")

        page_results: list[dict[str, Any]] = []
        merged_lines: list[str] = []
        failed_pages = 0
        attempt_total = 0
        retry_attempts = 0
        progress_total = max(0, len(pages))

        if callable(progress_hook):
            progress_hook(
                progress_current=0,
                progress_total=progress_total,
                current_page=pages[0] if pages else None,
                current_attempt=0,
                max_attempts=max(1, max_retries_per_page + 1),
                phase="queued",
                failed_pages=0,
                line_count=0,
                last_error="",
            )

        for idx, page in enumerate(pages, start=1):
            page_started = time.monotonic()
            if callable(progress_hook):
                progress_hook(
                    progress_current=max(0, idx - 1),
                    progress_total=progress_total,
                    current_page=int(page),
                    current_attempt=0,
                    max_attempts=max(1, max_retries_per_page + 1),
                    phase="page_running",
                    failed_pages=failed_pages,
                    line_count=len(merged_lines),
                    last_error="",
                )

            page_lines: list[str] = []
            raw_output_excerpt = ""
            page_error = ""
            attempts = 0
            for attempt in range(1, max_retries_per_page + 2):
                attempts = int(attempt)
                attempt_total += 1
                if callable(progress_hook):
                    progress_hook(
                        progress_current=max(0, idx - 1),
                        progress_total=progress_total,
                        current_page=int(page),
                        current_attempt=attempts,
                        max_attempts=max(1, max_retries_per_page + 1),
                        phase="attempting",
                        failed_pages=failed_pages,
                        line_count=len(merged_lines),
                        last_error=page_error,
                    )
                try:
                    img_path = self._ensure_book_page_image_path(book_id=book_id, page=int(page))
                    if not img_path:
                        raise RuntimeError("page_image_missing")
                    image_data_url = _image_file_to_data_url(img_path)
                    llm_result = call_llm_toc_extract(
                        image_data_url=image_data_url,
                        prompt=prompt,
                        base_url=base_url,
                        api_key=api_key,
                        model=model,
                        timeout_sec=timeout_sec,
                    )
                    page_toc_text = str(llm_result.get("toc_text") or "").strip()
                    page_lines = [x for x in page_toc_text.splitlines() if x.strip()]
                    raw_output_excerpt = str(llm_result.get("raw_output_text") or "")[:800]
                    page_error = ""
                    break
                except Exception as exc:
                    page_error = str(exc)[:500] or "unknown_error"
                    if callable(progress_hook):
                        progress_hook(
                            progress_current=max(0, idx - 1),
                            progress_total=progress_total,
                            current_page=int(page),
                            current_attempt=attempts,
                            max_attempts=max(1, max_retries_per_page + 1),
                            phase="retry_wait" if attempt <= max_retries_per_page else "page_failed",
                            failed_pages=failed_pages,
                            line_count=len(merged_lines),
                            last_error=page_error,
                        )
                    if attempt <= max_retries_per_page:
                        retry_attempts += 1
                        if retry_backoff_ms > 0:
                            time.sleep(float(retry_backoff_ms) / 1000.0)
                        continue

            elapsed_ms = max(1, int((time.monotonic() - page_started) * 1000))
            if page_error:
                failed_pages += 1
                page_results.append(
                    {
                        "page": int(page),
                        "status": "failed",
                        "line_count": 0,
                        "lines": [],
                        "error": page_error,
                        "attempts": attempts,
                        "retries_used": max(0, attempts - 1),
                        "elapsed_ms": elapsed_ms,
                    }
                )
            else:
                merged_lines.extend(page_lines)
                page_results.append(
                    {
                        "page": int(page),
                        "status": "ok",
                        "line_count": len(page_lines),
                        "lines": page_lines[:500],
                        "raw_output_excerpt": raw_output_excerpt,
                        "attempts": attempts,
                        "retries_used": max(0, attempts - 1),
                        "elapsed_ms": elapsed_ms,
                    }
                )

            if callable(progress_hook):
                progress_hook(
                    progress_current=idx,
                    progress_total=progress_total,
                    current_page=int(page),
                    current_attempt=attempts,
                    max_attempts=max(1, max_retries_per_page + 1),
                    phase="page_done" if not page_error else "page_failed",
                    failed_pages=failed_pages,
                    line_count=len(merged_lines),
                    last_error=page_error,
                )

        toc_text = "\n".join(merged_lines)
        preview = (
            build_toc_preview(toc_text, total_pages=total_pages, page_offset=int(page_offset))
            if toc_text
            else build_toc_preview("", total_pages=total_pages, page_offset=int(page_offset))
        )

        failure_breakdown: dict[str, int] = {}
        failed_page_numbers: list[int] = []
        for row in page_results:
            if str(row.get("status") or "") == "ok":
                continue
            page_val = safe_int(row.get("page"), None)
            if page_val:
                failed_page_numbers.append(int(page_val))
            reason = str(row.get("error") or "unknown_error").strip() or "unknown_error"
            key = reason if len(reason) <= 160 else reason[:160]
            failure_breakdown[key] = int(failure_breakdown.get(key, 0) or 0) + 1
        failed_reason_top = ""
        if failure_breakdown:
            failed_reason_top = sorted(failure_breakdown.items(), key=lambda kv: kv[1], reverse=True)[0][0]

        saved_result_file = ""
        try:
            saved_result_file = persist_llm_toc_run(
                {
                    "mode": "page_range",
                    "book_id": book_id,
                    "requested_page_start": int(page_start),
                    "requested_page_end": int(page_end),
                    "processed_pages": pages,
                    "page_count": len(pages),
                    "failed_pages": int(failed_pages),
                    "failed_page_numbers": failed_page_numbers,
                    "line_count": len(merged_lines),
                    "attempt_total": int(attempt_total),
                    "retry_attempts": int(retry_attempts),
                    "max_retries_per_page": int(max_retries_per_page),
                    "retry_backoff_ms": int(retry_backoff_ms),
                    "toc_text": toc_text,
                    "preview": preview,
                    "page_results": page_results,
                    "failure_breakdown": failure_breakdown,
                    "llm": {
                        "model": model,
                        "base_url": llm_base_url,
                    },
                }
            )
        except Exception:
            saved_result_file = ""

        return {
            "status": "partial" if failed_pages > 0 else "ok",
            "engine": "llm",
            "model": model,
            "base_url": llm_base_url,
            "book_id": book_id,
            "page_start": int(page_start),
            "page_end": int(page_end),
            "page_count": len(pages),
            "processed_page_start": min(pages) if pages else int(page_start),
            "processed_page_end": max(pages) if pages else int(page_end),
            "processed_pages": pages,
            "failed_pages": int(failed_pages),
            "failed_page_numbers": failed_page_numbers,
            "line_count": len(merged_lines),
            "attempt_total": int(attempt_total),
            "retry_attempts": int(retry_attempts),
            "retry_config": {
                "max_retries_per_page": int(max_retries_per_page),
                "retry_backoff_ms": int(retry_backoff_ms),
            },
            "toc_text": toc_text,
            "lines": merged_lines[:2000],
            "page_results": page_results,
            "failure_breakdown": failure_breakdown,
            "failed_reason_top": failed_reason_top,
            "validation": validation,
            "preview": preview,
            "saved_result_file": saved_result_file,
        }

    def _run_toc_llm_extract_pages_job(
        self,
        *,
        job_id: str,
        request_payload: dict[str, Any],
        validation: dict[str, Any] | None = None,
    ) -> None:
        def progress_hook(**patch: Any) -> None:
            total = max(0, int(patch.get("progress_total") or 0))
            current = max(0, int(patch.get("progress_current") or 0))
            percent = 0.0
            if total > 0:
                percent = max(0.0, min(100.0, round((current / total) * 100, 1)))
            _llm_batch_job_update(
                job_id,
                progress_current=current,
                progress_total=total,
                progress_percent=percent,
                current_page=patch.get("current_page"),
                current_attempt=max(0, int(patch.get("current_attempt") or 0)),
                max_attempts=max(0, int(patch.get("max_attempts") or 0)),
                phase=str(patch.get("phase") or "running"),
                failed_pages=max(0, int(patch.get("failed_pages") or 0)),
                line_count=max(0, int(patch.get("line_count") or 0)),
                last_error=str(patch.get("last_error") or ""),
            )

        try:
            result = self._execute_llm_extract_pages(
                request_payload=request_payload,
                validation=validation,
                progress_hook=progress_hook,
            )
            progress_total = max(0, int(len(result.get("processed_pages") or [])))
            progress_current = progress_total
            progress_percent = 100.0 if progress_total > 0 else 0.0
            _llm_batch_job_update(
                job_id,
                status=str(result.get("status") or "ok"),
                progress_current=progress_current,
                progress_total=progress_total,
                progress_percent=progress_percent,
                current_page=(result.get("processed_pages") or [None])[-1] if progress_total > 0 else None,
                current_attempt=0,
                max_attempts=max(1, int(result.get("retry_config", {}).get("max_retries_per_page") or 0) + 1),
                phase="done",
                failed_pages=max(0, int(result.get("failed_pages") or 0)),
                failed_page_numbers=list(result.get("failed_page_numbers") or []),
                line_count=max(0, int(result.get("line_count") or 0)),
                last_error="",
                result=result,
                completed_at=now_iso(),
            )
        except Exception as exc:
            _llm_batch_job_update(
                job_id,
                status="error",
                phase="error",
                error_message=str(exc)[:500],
                last_error=str(exc)[:500],
                completed_at=now_iso(),
            )

    def handle_toc_llm_extract_pages_start(self) -> None:
        if not self._authorized(parsed=None):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")
        payload = self._read_json()
        if payload is None:
            return

        request_payload = self._prepare_llm_extract_pages_request(payload)
        if request_payload is None:
            return

        validation: dict[str, Any] | None = None
        if bool(request_payload.get("validate_first")):
            probe_page = int((request_payload.get("pages") or [request_payload.get("page_start")])[0] or request_payload.get("page_start") or 1)
            validation = self._run_llm_validation(
                base_url=str(request_payload.get("base_url") or ""),
                api_key=str(request_payload.get("api_key") or ""),
                model=str(request_payload.get("model") or ""),
                prompt=str(request_payload.get("prompt") or DEFAULT_LLM_TOC_PROMPT),
                timeout_sec=max(10, min(45, int(request_payload.get("timeout_sec") or 90))),
                book_id=str(request_payload.get("book_id") or ""),
                page=max(1, int(probe_page)),
                include_image_probe=True,
            )
            if not bool(validation.get("valid")):
                failed_reasons = list(validation.get("failed_reasons") or [])
                reason = failed_reasons[0] if failed_reasons else "LLM validation failed"
                return json_response(
                    self,
                    HTTPStatus.BAD_REQUEST,
                    {
                        "error": {
                            "code": "LLM_INVALID_CONFIG",
                            "message": f"LLM preflight failed: {reason}",
                        },
                        "validation": validation,
                    },
                )

        if bool(request_payload.get("remember_config")):
            try:
                save_llm_toc_config(
                    base_url=str(request_payload.get("base_url") or ""),
                    model=str(request_payload.get("model") or ""),
                    api_key=str(request_payload.get("api_key") or ""),
                    prompt=str(request_payload.get("prompt") or DEFAULT_LLM_TOC_PROMPT),
                    remember_api_key=bool(request_payload.get("remember_api_key")),
                )
            except Exception:
                pass

        processed_pages = [int(x) for x in (request_payload.get("pages") or []) if safe_int(x, None)]
        job = _llm_batch_job_create(
            meta={
                "book_id": str(request_payload.get("book_id") or ""),
                "page_start": int(request_payload.get("page_start") or 1),
                "page_end": int(request_payload.get("page_end") or 1),
                "processed_pages": processed_pages,
                "page_count": len(processed_pages),
                "model": str(request_payload.get("model") or ""),
                "retry_config": {
                    "max_retries_per_page": int(request_payload.get("max_retries_per_page") or 0),
                    "retry_backoff_ms": int(request_payload.get("retry_backoff_ms") or 0),
                },
            },
        )
        _llm_batch_job_update(
            str(job.get("job_id") or ""),
            progress_total=len(processed_pages),
            progress_current=0,
            progress_percent=0.0,
            current_page=processed_pages[0] if processed_pages else None,
            current_attempt=0,
            max_attempts=max(1, int(request_payload.get("max_retries_per_page") or 0) + 1),
            phase="queued",
            failed_pages=0,
            failed_page_numbers=[],
            line_count=0,
            last_error="",
        )

        job_id = str(job.get("job_id") or "")
        thread = threading.Thread(
            target=self._run_toc_llm_extract_pages_job,
            kwargs={
                "job_id": job_id,
                "request_payload": request_payload,
                "validation": validation,
            },
            name=f"bookflow-llm-batch-{job_id[:8]}",
            daemon=True,
        )
        thread.start()

        return json_response(
            self,
            HTTPStatus.OK,
            {
                "status": "running",
                "schema_version": "bookflow.llm_batch_job.v1",
                "job_id": job_id,
                "created_at": job.get("created_at"),
                "book_id": request_payload.get("book_id"),
                "page_start": request_payload.get("page_start"),
                "page_end": request_payload.get("page_end"),
                "page_count": len(processed_pages),
                "processed_pages": processed_pages,
                "retry_config": {
                    "max_retries_per_page": int(request_payload.get("max_retries_per_page") or 0),
                    "retry_backoff_ms": int(request_payload.get("retry_backoff_ms") or 0),
                },
                "validation": validation,
            },
        )

    def handle_toc_llm_extract_pages_job(self, parsed: Any) -> None:
        if not self._authorized(parsed=parsed):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")
        params = parse_qs(parsed.query)
        job_id = str(params.get("job_id", [""])[0] or "").strip()
        if not job_id:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "job_id is required")
        snapshot = _llm_batch_job_snapshot(job_id)
        if snapshot is None:
            return error_response(self, HTTPStatus.NOT_FOUND, "NOT_FOUND", "llm batch job not found")

        progress_total = max(0, int(snapshot.get("progress_total") or 0))
        progress_current = max(0, int(snapshot.get("progress_current") or 0))
        progress_percent = float(snapshot.get("progress_percent") or 0.0)
        if progress_total > 0:
            progress_percent = max(0.0, min(100.0, round((progress_current / progress_total) * 100, 1)))

        return json_response(
            self,
            HTTPStatus.OK,
            {
                "schema_version": "bookflow.llm_batch_job.v1",
                "job_id": snapshot.get("job_id"),
                "status": snapshot.get("status"),
                "created_at": snapshot.get("created_at"),
                "updated_at": snapshot.get("updated_at"),
                "completed_at": snapshot.get("completed_at"),
                "progress_current": progress_current,
                "progress_total": progress_total,
                "progress_percent": progress_percent,
                "current_page": snapshot.get("current_page"),
                "current_attempt": max(0, int(snapshot.get("current_attempt") or 0)),
                "max_attempts": max(0, int(snapshot.get("max_attempts") or 0)),
                "phase": str(snapshot.get("phase") or "running"),
                "failed_pages": max(0, int(snapshot.get("failed_pages") or 0)),
                "failed_page_numbers": list(snapshot.get("failed_page_numbers") or []),
                "line_count": max(0, int(snapshot.get("line_count") or 0)),
                "error_message": str(snapshot.get("error_message") or ""),
                "last_error": str(snapshot.get("last_error") or ""),
                "meta": snapshot.get("meta") if isinstance(snapshot.get("meta"), dict) else {},
                "result": snapshot.get("result") if isinstance(snapshot.get("result"), dict) else None,
            },
        )

    def handle_toc_llm_extract_pages(self) -> None:
        if not self._authorized(parsed=None):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        payload = self._read_json()
        if payload is None:
            return

        request_payload = self._prepare_llm_extract_pages_request(payload)
        if request_payload is None:
            return

        validation: dict[str, Any] | None = None
        if bool(request_payload.get("validate_first")):
            probe_page = int((request_payload.get("pages") or [request_payload.get("page_start")])[0] or request_payload.get("page_start") or 1)
            validation = self._run_llm_validation(
                base_url=str(request_payload.get("base_url") or ""),
                api_key=str(request_payload.get("api_key") or ""),
                model=str(request_payload.get("model") or ""),
                prompt=str(request_payload.get("prompt") or DEFAULT_LLM_TOC_PROMPT),
                timeout_sec=max(10, min(45, int(request_payload.get("timeout_sec") or 90))),
                book_id=str(request_payload.get("book_id") or ""),
                page=max(1, int(probe_page)),
                include_image_probe=True,
            )
            if not bool(validation.get("valid")):
                failed_reasons = list(validation.get("failed_reasons") or [])
                reason = failed_reasons[0] if failed_reasons else "LLM validation failed"
                return json_response(
                    self,
                    HTTPStatus.BAD_REQUEST,
                    {
                        "error": {
                            "code": "LLM_INVALID_CONFIG",
                            "message": f"LLM preflight failed: {reason}",
                        },
                        "validation": validation,
                    },
                )

        if bool(request_payload.get("remember_config")):
            try:
                save_llm_toc_config(
                    base_url=str(request_payload.get("base_url") or ""),
                    model=str(request_payload.get("model") or ""),
                    api_key=str(request_payload.get("api_key") or ""),
                    prompt=str(request_payload.get("prompt") or DEFAULT_LLM_TOC_PROMPT),
                    remember_api_key=bool(request_payload.get("remember_api_key")),
                )
            except Exception:
                pass

        result = self._execute_llm_extract_pages(
            request_payload=request_payload,
            validation=validation,
            progress_hook=None,
        )
        return json_response(self, HTTPStatus.OK, result)

    def handle_toc_ocr_extract(self) -> None:
        if not self._authorized(parsed=None):
            return error_response(self, HTTPStatus.UNAUTHORIZED, "INVALID_AUTH", "Unauthorized")

        payload = self._read_json()
        if payload is None:
            return

        engine = get_ocr_engine()
        if engine is None:
            return error_response(self, HTTPStatus.SERVICE_UNAVAILABLE, "OCR_UNAVAILABLE", "OCR engine not available")

        try:
            image_bytes, _image_data_url = decode_image_payload(payload.get("image_data_url") or payload.get("image_base64"))
        except ValueError as exc:
            return error_response(self, HTTPStatus.BAD_REQUEST, "INVALID_PAYLOAD", str(exc))

        try:
            with tempfile.NamedTemporaryFile(prefix="bookflow_toc_ocr_", suffix=".png", delete=False) as tmp:
                tmp.write(image_bytes)
                tmp_path = Path(tmp.name)
        except Exception:
            return error_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "failed to persist ocr image")

        try:
            result, _elapsed = engine(str(tmp_path))
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            return error_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "ocr execution failed")
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

        lines: list[str] = []
        for item in result or []:
            text_val = ""
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                text_val = str(item[1] or "").strip()
            elif isinstance(item, dict):
                text_val = str(item.get("text") or "").strip()
            if text_val:
                lines.append(text_val)

        toc_text = "\n".join(lines)
        total_pages = safe_int(payload.get("total_pages"), None)
        page_offset = safe_int(payload.get("page_offset"), 0) or 0
        preview = (
            build_toc_preview(toc_text, total_pages=total_pages, page_offset=int(page_offset))
            if toc_text
            else build_toc_preview("", total_pages=total_pages, page_offset=int(page_offset))
        )

        return json_response(
            self,
            HTTPStatus.OK,
            {
                "status": "ok",
                "engine": "rapidocr_onnxruntime",
                "line_count": len(lines),
                "lines": lines[:500],
                "toc_text": toc_text,
                "preview": preview,
            },
        )

    def handle_frontend(self, parsed: Any) -> bool:
        path = parsed.path
        if path in {"/", "/app", "/app/", "/app/feed"}:
            rel = "index.html"
        elif path == "/app/reader":
            rel = "reader.html"
        elif path == "/app/book":
            rel = "book.html"
        elif path == "/app/toc":
            rel = "toc.html"
        elif path.startswith("/app/"):
            rel = path[len("/app/") :]
        else:
            return False

        root = FRONTEND_ROOT.resolve()
        file_path = (root / rel).resolve()
        if root not in file_path.parents and file_path != root:
            return False
        if not file_path.exists() or not file_path.is_file():
            return False

        try:
            body = file_path.read_bytes()
        except Exception:
            return False

        mime, _ = mimetypes.guess_type(str(file_path))
        content_type = mime or "application/octet-stream"
        if content_type.startswith("text/"):
            content_type = f"{content_type}; charset=utf-8"

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)
        return True


def run_server(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), BookFlowHandler)
    start_startup_bootstrap_thread()
    print(f"BookFlow V0 server listening on http://{host}:{port}")
    print("Token:", TOKEN)
    print("Backend:", STORE.backend)
    if STARTUP_BOOTSTRAP_ENABLED:
        print(
            "Startup bootstrap: enabled",
            f"(input_dir={resolve_runtime_path(STARTUP_BOOTSTRAP_INPUT_DIR)}, interval={STARTUP_BOOTSTRAP_INTERVAL_SEC}s)",
        )
    else:
        print("Startup bootstrap: disabled")
    server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="BookFlow V0 server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    run_server(args.host, args.port)


if __name__ == "__main__":
    main()
