#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg

TILES_JSON_SCHEMA_VERSION = "book_homepage_mosaic.tiles.v1"
HTML_SCHEMA_VERSION = "book_homepage_mosaic.html.v1"


def fetch_book_chunks_with_progress(dsn: str, book_id: str, user_id: str) -> tuple[str, list[dict[str, Any]]]:
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
      WHERE i.user_id = %s
        AND i.book_id = c.book_id
        AND i.chunk_id = c.id
        AND i.event_type IN ('enter_context', 'section_complete', 'like', 'comment')
    ) stats ON TRUE
    WHERE b.id = %s
    ORDER BY c.global_index ASC
    """
    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (uuid.UUID(user_id), uuid.UUID(book_id)))
            rows = cur.fetchall()

    if not rows:
        raise ValueError("book not found or has no chunks")
    book_title = str(rows[0][0])
    items: list[dict[str, Any]] = []
    for row in rows:
        items.append(
            {
                "chunk_id": row[1],
                "global_index": int(row[2]),
                "section_id": row[3],
                "chunk_title": row[4],
                "read_events": int(row[5]),
            }
        )
    return book_title, items


def build_mosaic_tiles(chunks: list[dict[str, Any]], min_read_events: int = 1) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    threshold = max(1, int(min_read_events))
    tiles: list[dict[str, Any]] = []
    read_count = 0
    for row in chunks:
        read_events = int(row.get("read_events", 0))
        state = "read" if read_events >= threshold else "unread"
        if state == "read":
            read_count += 1
        tiles.append(
            {
                "chunk_id": str(row.get("chunk_id")),
                "global_index": int(row.get("global_index", 0)),
                "section_id": row.get("section_id"),
                "chunk_title": row.get("chunk_title"),
                "read_events": read_events,
                "state": state,
            }
        )

    total = len(tiles)
    completion_rate = round((read_count / total), 4) if total > 0 else 0.0
    summary = {
        "total_chunks": total,
        "read_chunks": read_count,
        "unread_chunks": total - read_count,
        "completion_rate": completion_rate,
    }
    return tiles, summary


def _escape_html(text: Any) -> str:
    raw = "" if text is None else str(text)
    return (
        raw.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def render_mosaic_html(
    *,
    book_id: str,
    book_title: str,
    user_id: str,
    exported_at: str,
    min_read_events: int,
    html_schema_version: str,
    tiles_json_schema_version: str,
    tiles: list[dict[str, Any]],
    summary: dict[str, Any],
) -> str:
    completion_pct = int(round(float(summary.get("completion_rate", 0.0)) * 100))
    read_chunks = int(summary.get("read_chunks", 0))
    unread_chunks = int(summary.get("unread_chunks", 0))
    tile_html = []
    for tile in tiles:
        state = tile.get("state", "unread")
        tile_html.append(
            """
            <article class="tile {state}">
              <div class="tile-meta">#{index}</div>
              <h3 class="tile-title">{title}</h3>
              <p class="tile-sub">{section}</p>
              <p class="tile-foot">read_events: {events}</p>
            </article>
            """.format(
                state=_escape_html(state),
                index=_escape_html(tile.get("global_index")),
                title=_escape_html(tile.get("chunk_title") or "(untitled chunk)"),
                section=_escape_html(tile.get("section_id") or "no-section"),
                events=_escape_html(tile.get("read_events")),
            ).strip()
        )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="bookflow:html_schema_version" content="{_escape_html(html_schema_version)}">
  <meta name="bookflow:tiles_json_schema_version" content="{_escape_html(tiles_json_schema_version)}">
  <title>BookFlow Mosaic - {_escape_html(book_title)}</title>
  <style>
    :root {{
      --bg-a: #f6f2e9;
      --bg-b: #d8e9f7;
      --ink: #13243b;
      --muted: #4b5e78;
      --card-read: #fff3df;
      --card-read-border: #f08a24;
      --card-unread: #edf1f4;
      --card-unread-border: #9ba8b6;
      --shadow: 0 10px 28px rgba(19, 36, 59, 0.14);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      font-family: "IBM Plex Sans", "Noto Sans SC", "PingFang SC", sans-serif;
      background:
        radial-gradient(circle at 20% 15%, rgba(240,138,36,0.22), transparent 40%),
        radial-gradient(circle at 85% 90%, rgba(34,94,168,0.20), transparent 35%),
        linear-gradient(145deg, var(--bg-a), var(--bg-b));
      min-height: 100vh;
    }}
    .page {{
      max-width: 980px;
      margin: 0 auto;
      padding: 28px 16px 36px;
    }}
    .hero {{
      background: rgba(255, 255, 255, 0.84);
      backdrop-filter: blur(3px);
      border: 1px solid rgba(19, 36, 59, 0.12);
      border-radius: 18px;
      box-shadow: var(--shadow);
      padding: 18px 18px 14px;
      margin-bottom: 16px;
    }}
    .title {{
      margin: 0 0 8px;
      font-size: 1.28rem;
      line-height: 1.3;
      letter-spacing: 0.01em;
    }}
    .meta {{
      margin: 0;
      font-size: 0.9rem;
      color: var(--muted);
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .progress {{
      margin-top: 12px;
      height: 10px;
      background: rgba(19, 36, 59, 0.12);
      border-radius: 999px;
      overflow: hidden;
    }}
    .progress > span {{
      display: block;
      height: 100%;
      width: {completion_pct}%;
      background: linear-gradient(90deg, #f08a24, #f0be4a);
    }}
    .legend {{
      margin-top: 12px;
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }}
    .legend-item {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 0.8rem;
      color: var(--muted);
    }}
    .legend-dot {{
      width: 14px;
      height: 14px;
      border-radius: 4px;
      border: 1px solid;
      flex: none;
    }}
    .legend-dot.read {{
      background: var(--card-read);
      border-color: var(--card-read-border);
    }}
    .legend-dot.unread {{
      background: var(--card-unread);
      border-color: var(--card-unread-border);
    }}
    .mosaic-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
      gap: 12px;
    }}
    .tile {{
      border-radius: 14px;
      padding: 12px 11px;
      border: 1px solid;
      min-height: 124px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      transition: transform 160ms ease, box-shadow 160ms ease;
    }}
    .tile:hover {{
      transform: translateY(-2px);
      box-shadow: 0 8px 20px rgba(19, 36, 59, 0.14);
    }}
    .tile.read {{
      background: var(--card-read);
      border-color: var(--card-read-border);
    }}
    .tile.unread {{
      background: var(--card-unread);
      border-color: var(--card-unread-border);
      opacity: 0.82;
    }}
    .tile-meta {{
      font-size: 0.78rem;
      color: var(--muted);
      margin-bottom: 8px;
    }}
    .tile-title {{
      margin: 0;
      font-size: 0.94rem;
      line-height: 1.34;
    }}
    .tile-sub {{
      margin: 8px 0 0;
      font-size: 0.78rem;
      color: var(--muted);
      line-height: 1.3;
    }}
    .tile-foot {{
      margin: 10px 0 0;
      font-size: 0.76rem;
      color: #34465e;
    }}
    @media (max-width: 640px) {{
      .title {{ font-size: 1.08rem; }}
      .mosaic-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .tile {{ min-height: 112px; }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <h1 class="title">{_escape_html(book_title)} · 进度拼图</h1>
      <p class="meta">
        <span>book_id: {_escape_html(book_id)}</span>
        <span>user_id: {_escape_html(user_id)}</span>
        <span>min_read_events: {_escape_html(min_read_events)}</span>
        <span>tiles_json_schema_version: {_escape_html(tiles_json_schema_version)}</span>
        <span>read {int(summary.get("read_chunks", 0))}/{int(summary.get("total_chunks", 0))} ({completion_pct}%)</span>
        <span>exported_at: {_escape_html(exported_at)}</span>
      </p>
      <div class="progress"><span></span></div>
      <div class="legend">
        <span class="legend-item"><i class="legend-dot read"></i> 已读 tile ({read_chunks})</span>
        <span class="legend-item"><i class="legend-dot unread"></i> 未读 tile ({unread_chunks})</span>
      </div>
    </section>
    <section class="mosaic-grid">
      {"".join(tile_html)}
    </section>
  </main>
</body>
</html>
"""


def write_tiles_json(
    path: Path,
    *,
    book_id: str,
    book_title: str,
    html_title: str,
    user_id: str,
    exported_at: str,
    min_read_events: int,
    summary: dict[str, Any],
    tiles: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": TILES_JSON_SCHEMA_VERSION,
        "tiles_json_schema_version": TILES_JSON_SCHEMA_VERSION,
        "html_schema_version": HTML_SCHEMA_VERSION,
        "book_id": book_id,
        "book_title": book_title,
        "html_title": html_title,
        "user_id": user_id,
        "exported_at": exported_at,
        "min_read_events": int(min_read_events),
        "summary": summary,
        "tiles": tiles,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a static BookFlow book-homepage mosaic prototype")
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--user-id", default="11111111-1111-1111-1111-111111111111")
    parser.add_argument("--min-read-events", type=int, default=1)
    parser.add_argument("--output", default="logs/prototypes/book_homepage_mosaic.html")
    parser.add_argument("--tiles-json-output", default=None, help="Optional tile JSON output for frontend integration")
    args = parser.parse_args()

    dsn = args.database_url or os.getenv("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is required (or pass --database-url)", file=sys.stderr)
        return 1

    try:
        book_id = str(uuid.UUID(args.book_id))
        user_id = str(uuid.UUID(args.user_id))
    except Exception:
        print("--book-id/--user-id must be UUID", file=sys.stderr)
        return 1

    if args.min_read_events <= 0:
        print("--min-read-events must be > 0", file=sys.stderr)
        return 1

    try:
        book_title, chunks = fetch_book_chunks_with_progress(dsn, book_id=book_id, user_id=user_id)
    except Exception as exc:
        print(f"failed to fetch book chunks: {exc}", file=sys.stderr)
        return 1
    tiles, summary = build_mosaic_tiles(chunks, min_read_events=args.min_read_events)
    exported_at = datetime.now(timezone.utc).isoformat()
    html_title = f"{book_title} · 进度拼图"
    html = render_mosaic_html(
        book_id=book_id,
        book_title=book_title,
        user_id=user_id,
        exported_at=exported_at,
        min_read_events=args.min_read_events,
        html_schema_version=HTML_SCHEMA_VERSION,
        tiles_json_schema_version=TILES_JSON_SCHEMA_VERSION,
        tiles=tiles,
        summary=summary,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    if args.tiles_json_output:
        write_tiles_json(
            Path(args.tiles_json_output),
            book_id=book_id,
            book_title=book_title,
            html_title=html_title,
            user_id=user_id,
            exported_at=exported_at,
            min_read_events=args.min_read_events,
            summary=summary,
            tiles=tiles,
        )

    payload = {
        "status": "ok",
        "book_id": book_id,
        "book_title": book_title,
        "html_title": html_title,
        "html_schema_version": HTML_SCHEMA_VERSION,
        "html_meta_tiles_schema_echoed": True,
        "user_id": user_id,
        "exported_at": exported_at,
        "min_read_events": args.min_read_events,
        "summary": summary,
        "output": str(output_path),
        "tiles_json_output": args.tiles_json_output,
        "tiles_json_schema_version": TILES_JSON_SCHEMA_VERSION if args.tiles_json_output else None,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
