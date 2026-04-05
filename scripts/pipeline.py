#!/usr/bin/env python3
"""
BookFlow minimal offline pipeline:
1. Section-first chunking (best effort)
2. Render mode decision (reflow/crop)
3. JSON output for downstream ingestion
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Config:
    target_read_sec_min: int = 180
    target_read_sec_max: int = 480
    hard_char_max: int = 3600
    chars_per_sec_zh: float = 4.5
    english_words_per_min: float = 170.0
    extract_confidence_crop_threshold: float = 0.55
    code_confidence_threshold: float = 0.75
    formula_dense_threshold: int = 3
    technical_formula_bias: bool = True


REASON_ORDER = [
    "table_present",
    "low_extract_confidence",
    "dense_formula",
    "code_layout_sensitive",
    "text_reflow_friendly",
    "technical_formula_bias",
]
REASON_RANK = {k: i for i, k in enumerate(REASON_ORDER)}


def normalize_reasons(reasons: list[str]) -> list[str]:
    unique = set(reasons)
    return sorted(unique, key=lambda x: (REASON_RANK.get(x, 999), x))


def _apply_overrides(cfg: Config, overrides: dict[str, Any]) -> Config:
    for field in cfg.__dataclass_fields__.keys():
        if field in overrides:
            setattr(cfg, field, overrides[field])
    return cfg


def _read_config_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    return raw


def load_config(path: Path | None) -> Config:
    cfg = Config()
    raw = _read_config_json(path)
    if not raw:
        return cfg

    # New format:
    # {
    #   "defaults": {...},
    #   "templates": {"technical": {...}, ...}
    # }
    if "defaults" in raw and isinstance(raw.get("defaults"), dict):
        return _apply_overrides(cfg, raw["defaults"])

    # Legacy flat format:
    # {"hard_char_max": 3600, ...}
    return _apply_overrides(cfg, raw)


def load_config_for_book_type(path: Path | None, book_type: str) -> Config:
    cfg = load_config(path)
    raw = _read_config_json(path)
    templates = raw.get("templates")
    if isinstance(templates, dict):
        tpl = templates.get(book_type)
        if isinstance(tpl, dict):
            cfg = _apply_overrides(cfg, tpl)
    return cfg


def estimate_read_seconds(text: str, book_language: str, cfg: Config) -> int:
    if not text:
        return 0
    if book_language.startswith("zh"):
        return int(len(text) / cfg.chars_per_sec_zh)
    words = max(1, len(text.split()))
    return int(words / (cfg.english_words_per_min / 60))


def detect_has_formula(text: str, block_kinds: list[str]) -> bool:
    if "formula" in block_kinds:
        return True
    # Avoid treating normal code assignment as math formula.
    if "code" in block_kinds:
        pattern = r"(∑|∫|∂|∇|∞|≈|≠|≤|≥)"
    else:
        pattern = r"(∑|∫|∂|∇|∞|≈|≠|≤|≥|[A-Za-z]\s*=\s*[A-Za-z0-9_()+\-*/^]+)"
    return bool(re.search(pattern, text))


def detect_has_code(text: str, block_kinds: list[str]) -> bool:
    if "code" in block_kinds:
        return True
    code_like = [
        r"\bdef\s+\w+\(",
        r"\bclass\s+\w+",
        r"\bfor\s+\w+\s+in\s+",
        r"\bif\s*\(",
        r"{\s*$",
    ]
    return any(re.search(p, text, re.MULTILINE) for p in code_like)


def choose_render_mode(
    has_formula: bool,
    has_code: bool,
    has_table: bool,
    extract_confidence: float,
    formula_count: int,
    cfg: Config,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if has_table:
        return "crop", ["table_present"]
    if extract_confidence < cfg.extract_confidence_crop_threshold:
        return "crop", ["low_extract_confidence"]
    if has_formula and formula_count >= cfg.formula_dense_threshold:
        return "crop", ["dense_formula"]
    if has_code and extract_confidence < cfg.code_confidence_threshold:
        return "crop", ["code_layout_sensitive"]
    reasons.append("text_reflow_friendly")
    return "reflow", reasons


def section_from_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current = {"title": "Untitled", "blocks": []}
    for b in blocks:
        kind = b.get("kind", "paragraph")
        if kind == "heading":
            if current["blocks"]:
                sections.append(current)
            current = {"title": b.get("text", "Untitled").strip() or "Untitled", "blocks": []}
        else:
            current["blocks"].append(b)
    if current["blocks"] or not sections:
        sections.append(current)
    return sections


def split_text_by_paragraph(text: str, max_chars: int) -> list[str]:
    text = text.strip()
    if len(text) <= max_chars:
        return [text] if text else []
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    out: list[str] = []
    buf = ""
    for p in parts:
        if len(p) > max_chars:
            if buf:
                out.append(buf)
                buf = ""
            start = 0
            while start < len(p):
                out.append(p[start : start + max_chars])
                start += max_chars
            continue
        if not buf:
            buf = p
            continue
        if len(buf) + 2 + len(p) <= max_chars:
            buf = f"{buf}\n\n{p}"
        else:
            out.append(buf)
            buf = p
    if buf:
        out.append(buf)
    if not out:
        return [text[:max_chars], text[max_chars:]]
    return out


def stable_chunk_id(book_id: str, section_id: str, idx: int, text: str) -> str:
    raw = f"{book_id}|{section_id}|{idx}|{text[:80]}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"ck_{digest}"


def build_source_anchor(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    if not blocks:
        return {"page_start": None, "page_end": None, "bbox_union": [0, 0, 1, 1]}
    pages = [b.get("page") for b in blocks if b.get("page") is not None]
    bbox_vals = [b.get("bbox") for b in blocks if isinstance(b.get("bbox"), list) and len(b.get("bbox")) == 4]
    if not bbox_vals:
        bbox_union = [0, 0, 1, 1]
    else:
        x1 = min(bb[0] for bb in bbox_vals)
        y1 = min(bb[1] for bb in bbox_vals)
        x2 = max(bb[2] for bb in bbox_vals)
        y2 = max(bb[3] for bb in bbox_vals)
        bbox_union = [round(x1, 4), round(y1, 4), round(x2, 4), round(y2, 4)]
    return {
        "page_start": min(pages) if pages else None,
        "page_end": max(pages) if pages else None,
        "bbox_union": bbox_union,
    }


def run_pipeline(payload: dict[str, Any], cfg: Config) -> dict[str, Any]:
    book_id = payload.get("book_id", "book_unknown")
    book_type = payload.get("book_type", "general")
    language = payload.get("language", "zh")
    extract_confidence = float(payload.get("extract_confidence", 0.8))
    blocks = payload.get("blocks", [])
    sections = section_from_blocks(blocks) if blocks else []

    if not sections:
        clean_text = payload.get("clean_text", "")
        pseudo_blocks = [{"kind": "paragraph", "text": clean_text, "page": None, "bbox": [0, 0, 1, 1]}]
        sections = [{"title": "Section 1", "blocks": pseudo_blocks}]

    chunks: list[dict[str, Any]] = []
    global_index = 0

    for sec_idx, sec in enumerate(sections, start=1):
        sec_id = f"sec_{sec_idx:02d}"
        sec_blocks = sec.get("blocks", [])
        raw_text = "\n\n".join((b.get("text") or "").strip() for b in sec_blocks if (b.get("text") or "").strip())
        if not raw_text:
            continue

        split_parts = split_text_by_paragraph(raw_text, cfg.hard_char_max)
        for i, part in enumerate(split_parts, start=1):
            global_index += 1
            block_kinds = [b.get("kind", "paragraph") for b in sec_blocks]
            has_formula = detect_has_formula(part, block_kinds)
            has_code = detect_has_code(part, block_kinds)
            has_table = "table" in block_kinds
            formula_count = sum(1 for k in block_kinds if k == "formula")

            render_mode, reasons = choose_render_mode(
                has_formula=has_formula,
                has_code=has_code,
                has_table=has_table,
                extract_confidence=extract_confidence,
                formula_count=formula_count,
                cfg=cfg,
            )
            if book_type == "technical" and has_formula and render_mode == "reflow" and cfg.technical_formula_bias:
                render_mode = "crop"
                reasons.append("technical_formula_bias")
            reasons = normalize_reasons(reasons)

            chunk_id = stable_chunk_id(book_id, sec_id, i, part)
            read_sec = estimate_read_seconds(part, language, cfg)
            quality_score = 0.9 if read_sec <= cfg.target_read_sec_max else 0.75
            anchor = build_source_anchor(sec_blocks)

            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "section_id": sec_id,
                    "chunk_index_in_section": i,
                    "global_index": global_index,
                    "title": sec.get("title", f"Section {sec_idx}"),
                    "text": part,
                    "read_time_sec_est": read_sec,
                    "has_formula": has_formula,
                    "has_code": has_code,
                    "has_table": has_table,
                    "render_mode": render_mode,
                    "render_reason": reasons,
                    "source_anchor": anchor,
                    "quality_score": quality_score,
                    "prerequisite_chunk_ids": [],
                }
            )

    for idx, c in enumerate(chunks):
        if idx > 0 and c["section_id"] == chunks[idx - 1]["section_id"]:
            c["prerequisite_chunk_ids"] = [chunks[idx - 1]["chunk_id"]]

    mode_counter: Counter[str] = Counter()
    reason_counter: Counter[str] = Counter()
    for c in chunks:
        mode_counter[c["render_mode"]] += 1
        for r in c["render_reason"]:
            reason_counter[r] += 1

    return {
        "book_id": book_id,
        "chunking_version": "chunking_v1",
        "render_mode_version": "render_mode_v1",
        "chunk_count": len(chunks),
        "stats": {
            "render_mode_counts": dict(sorted(mode_counter.items())),
            "render_reason_counts": dict(sorted(reason_counter.items())),
        },
        "chunks": chunks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="BookFlow minimal offline pipeline")
    parser.add_argument("--input", required=True, help="Input JSON path")
    parser.add_argument("--output", required=True, help="Output JSON path")
    parser.add_argument("--config", default="config/pipeline.json", help="Config JSON path")
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)
    config_path = Path(args.config)
    payload = json.loads(input_path.read_text(encoding="utf-8"))
    book_type = str(payload.get("book_type", "general"))
    cfg = load_config_for_book_type(config_path, book_type)
    result = run_pipeline(payload, cfg)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"Wrote {result['chunk_count']} chunks -> {output_path} "
        f"(modes={result['stats']['render_mode_counts']})"
    )


if __name__ == "__main__":
    main()
