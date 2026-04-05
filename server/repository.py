from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

try:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Json
except Exception:  # pragma: no cover
    psycopg = None
    dict_row = None
    Json = None


class BaseRepository:
    backend = "base"

    def fetch_feed_items(
        self,
        limit: int,
        offset: int,
        mode: str,
        book_type: str | None,
        user_id: str | None = None,
        include_trace: bool = False,
    ) -> list[dict[str, Any]]:
        raise NotImplementedError

    def insert_interactions_bulk(self, events: list[dict[str, Any]]) -> list[tuple[str, str | None]]:
        raise NotImplementedError

    def insert_rejections_bulk(self, rejections: list[dict[str, Any]]) -> None:
        raise NotImplementedError

    def fetch_chunk_neighbors(self, book_id: str | None, chunk_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def fetch_chunk_neighbors_batch(self, book_id: str | None, chunk_ids: list[str]) -> list[dict[str, Any]]:
        raise NotImplementedError

    def fetch_chunk_detail(self, book_id: str | None, chunk_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def fetch_book_chunks_with_progress(
        self,
        book_id: str,
        user_id: str | None,
    ) -> tuple[str, list[dict[str, Any]]] | None:
        raise NotImplementedError

    def fetch_memory_feed_items(self, user_id: str, limit: int, prefer_diversity: bool = True) -> list[dict[str, Any]]:
        raise NotImplementedError


class MemoryRepository(BaseRepository):
    backend = "memory"

    def __init__(self, seed_items: list[dict[str, Any]]) -> None:
        self.seed_items = seed_items
        self.idempotency_keys: set[tuple[str, str]] = set()
        self.section_complete_daily: set[tuple[str, str, str]] = set()

    def fetch_feed_items(
        self,
        limit: int,
        offset: int,
        mode: str,
        book_type: str | None,
        user_id: str | None = None,
        include_trace: bool = False,
    ) -> list[dict[str, Any]]:
        items = self.seed_items
        if book_type is not None:
            items = [i for i in items if i.get("book_type") == book_type]
        if mode == "deep_read":
            items = sorted(items, key=lambda x: (x.get("book_id", ""), x.get("section_id", "")))
        _ = user_id  # reserved for signature compatibility
        out = items[offset : offset + limit]
        if include_trace:
            for item in out:
                item["_ranking_score"] = 0.0
        return out

    def insert_interactions_bulk(self, events: list[dict[str, Any]]) -> list[tuple[str, str | None]]:
        out: list[tuple[str, str | None]] = []
        for event in events:
            user_id = str(event.get("user_id"))
            idem = str(event.get("idempotency_key"))
            key = (user_id, idem)
            if key in self.idempotency_keys:
                out.append(("deduplicated", None))
                continue
            self.idempotency_keys.add(key)

            event_type = str(event.get("event_type"))
            if event_type == "section_complete":
                payload = event.get("payload", {}) or {}
                section_id = str(payload.get("section_id", ""))
                if not section_id:
                    out.append(("rejected", "INVALID_PAYLOAD"))
                    continue
                dt = datetime.fromisoformat(str(event.get("event_ts")).replace("Z", "+00:00"))
                day = dt.date().isoformat()
                skey = (user_id, section_id, day)
                if skey in self.section_complete_daily:
                    out.append(("deduplicated", None))
                    continue
                self.section_complete_daily.add(skey)
            out.append(("accepted", None))
        return out

    def insert_rejections_bulk(self, rejections: list[dict[str, Any]]) -> None:
        _ = rejections
        return

    def fetch_chunk_neighbors(self, book_id: str | None, chunk_id: str) -> dict[str, Any] | None:
        items = self.seed_items
        if book_id:
            items = [i for i in items if i.get("book_id") == book_id]
        ordered = sorted(items, key=lambda x: (x.get("book_id", ""), x.get("section_id", ""), x.get("chunk_id", "")))
        idx = -1
        for i, item in enumerate(ordered):
            if str(item.get("chunk_id")) == chunk_id:
                idx = i
                break
        if idx < 0:
            return None
        current = ordered[idx]
        prev_item = ordered[idx - 1] if idx > 0 and ordered[idx - 1].get("book_id") == current.get("book_id") else None
        next_item = (
            ordered[idx + 1]
            if idx + 1 < len(ordered) and ordered[idx + 1].get("book_id") == current.get("book_id")
            else None
        )
        return {
            "book_id": str(current.get("book_id")),
            "chunk_id": str(current.get("chunk_id")),
            "title": current.get("title"),
            "prev_chunk_id": str(prev_item.get("chunk_id")) if prev_item else None,
            "prev_title": prev_item.get("title") if prev_item else None,
            "next_chunk_id": str(next_item.get("chunk_id")) if next_item else None,
            "next_title": next_item.get("title") if next_item else None,
        }

    def fetch_chunk_neighbors_batch(self, book_id: str | None, chunk_ids: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for chunk_id in chunk_ids:
            ctx = self.fetch_chunk_neighbors(book_id=book_id, chunk_id=chunk_id)
            if ctx is not None:
                out.append(ctx)
        return out

    def fetch_chunk_detail(self, book_id: str | None, chunk_id: str) -> dict[str, Any] | None:
        items = self.seed_items
        if book_id:
            items = [i for i in items if str(i.get("book_id")) == str(book_id)]
        for item in items:
            if str(item.get("chunk_id")) != str(chunk_id):
                continue
            teaser_text = str(item.get("teaser_text") or "")
            text_content = str(item.get("text_content") or teaser_text)
            source_anchor = item.get("source_anchor") or {}
            metadata = item.get("metadata") or {}
            content_type = str(metadata.get("content_type") or "text")
            section_pdf_url = metadata.get("section_pdf_url")
            if not section_pdf_url and content_type == "pdf_section":
                section_pdf_url = f"/v1/chunk_pdf?book_id={item.get('book_id')}&chunk_id={item.get('chunk_id')}"
            return {
                "book_id": str(item.get("book_id")),
                "book_title": item.get("book_title"),
                "book_type": item.get("book_type"),
                "chunk_id": str(item.get("chunk_id")),
                "section_id": item.get("section_id"),
                "title": item.get("title"),
                "teaser_text": teaser_text,
                "text_content": text_content,
                "render_mode": item.get("render_mode") or "reflow",
                "source_anchor": source_anchor,
                "content_type": content_type,
                "section_pdf_url": section_pdf_url,
                "section_pdf_relpath": metadata.get("section_pdf_relpath"),
                "page_start": source_anchor.get("page_start"),
                "page_end": source_anchor.get("page_end"),
                "has_formula": bool(item.get("has_formula")),
                "has_code": bool(item.get("has_code")),
                "has_table": bool(item.get("has_table", False)),
                "estimated_read_sec": int(item.get("estimated_read_sec") or 0),
            }
        return None

    def fetch_book_chunks_with_progress(
        self,
        book_id: str,
        user_id: str | None,
    ) -> tuple[str, list[dict[str, Any]]] | None:
        _ = user_id
        items = [i for i in self.seed_items if str(i.get("book_id")) == str(book_id)]
        if not items:
            return None
        ordered = sorted(items, key=lambda x: (x.get("section_id", ""), x.get("chunk_id", "")))
        book_title = str(ordered[0].get("book_title") or "Unknown Book")
        chunks: list[dict[str, Any]] = []
        for idx, row in enumerate(ordered, start=1):
            chunks.append(
                {
                    "chunk_id": str(row.get("chunk_id")),
                    "global_index": idx,
                    "section_id": row.get("section_id"),
                    "chunk_title": row.get("title"),
                    "read_events": 0,
                }
            )
        return book_title, chunks

    def fetch_memory_feed_items(self, user_id: str, limit: int, prefer_diversity: bool = True) -> list[dict[str, Any]]:
        _ = user_id
        _ = limit
        _ = prefer_diversity
        return []


class PostgresRepository(BaseRepository):
    backend = "postgres"

    def __init__(self, dsn: str) -> None:
        if psycopg is None:
            raise RuntimeError("psycopg is not installed")
        self.dsn = dsn

    def _connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row, autocommit=True)

    @staticmethod
    def _to_uuid(value: Any) -> UUID:
        return UUID(str(value))

    def fetch_feed_items(
        self,
        limit: int,
        offset: int,
        mode: str,
        book_type: str | None,
        user_id: str | None = None,
        include_trace: bool = False,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where_clause = "TRUE"
        if book_type is not None:
            where_clause = "b.book_type::text = %s"
            params.append(book_type)

        if mode == "deep_read":
            sql = f"""
            SELECT
              c.id::text AS chunk_id,
              b.id::text AS book_id,
              b.title AS book_title,
              b.book_type::text AS book_type,
              c.section_id,
              c.title,
              COALESCE(c.teaser_text, LEFT(c.text_content, 120) || '...') AS teaser_text,
              c.render_mode::text AS render_mode,
              c.source_anchor,
              c.has_formula,
              c.has_code,
              COALESCE(c.read_time_sec_est, 0) AS estimated_read_sec,
              0::numeric AS ranking_score
            FROM book_chunks c
            JOIN books b ON b.id = c.book_id
            WHERE {where_clause}
            ORDER BY b.id, c.global_index
            LIMIT %s OFFSET %s
            """
            params.extend([limit, offset])
        else:
            completion_join_sql = ""
            completion_select_sql = "0::int AS completion_flag"
            if user_id:
                completion_join_sql = """
                LEFT JOIN LATERAL (
                  SELECT 1 AS completion_flag
                  FROM interactions i
                  WHERE i.user_id = %s
                    AND i.book_id = c.book_id
                    AND i.chunk_id = c.id
                    AND i.event_type = 'section_complete'
                  LIMIT 1
                ) done ON TRUE
                """
                completion_select_sql = "COALESCE(done.completion_flag, 0) AS completion_flag"
                params.append(self._to_uuid(user_id))

            sql = f"""
            WITH base AS (
              SELECT
                c.id::text AS chunk_id,
                b.id::text AS book_id,
                b.title AS book_title,
                b.book_type::text AS book_type,
                c.section_id,
                c.title,
                COALESCE(c.teaser_text, LEFT(c.text_content, 120) || '...') AS teaser_text,
                c.render_mode::text AS render_mode,
                c.source_anchor,
                c.has_formula,
                c.has_code,
                COALESCE(c.read_time_sec_est, 0) AS estimated_read_sec,
                c.global_index,
                c.created_at,
                {completion_select_sql}
              FROM book_chunks c
              JOIN books b ON b.id = c.book_id
              {completion_join_sql}
              WHERE {where_clause}
            ),
            ranked AS (
              SELECT
                *,
                ROW_NUMBER() OVER (PARTITION BY book_id ORDER BY global_index ASC, created_at ASC) AS book_seq,
                ABS(hashtext(chunk_id || to_char(CURRENT_DATE, 'YYYYMMDD'))) % 1000 AS jitter
              FROM base
            )
            SELECT
              chunk_id,
              book_id,
              book_title,
              book_type,
              section_id,
              title,
              teaser_text,
              render_mode,
              source_anchor,
              has_formula,
              has_code,
              estimated_read_sec,
              (
                CASE
                  WHEN completion_flag = 0 THEN (1000 - jitter) / 1000.0
                  ELSE 0
                END
              )::numeric AS ranking_score
            FROM ranked
            ORDER BY completion_flag ASC, book_seq ASC, jitter ASC, created_at DESC
            LIMIT %s OFFSET %s
            """
            params.extend([limit, offset])

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()
        items: list[dict[str, Any]] = []
        for i, row in enumerate(rows, start=1):
            items.append(
                {
                    "feed_item_id": f"fi_{offset + i:04d}",
                    "book_id": row["book_id"],
                    "book_title": row["book_title"],
                    "chunk_id": row["chunk_id"],
                    "section_id": row["section_id"],
                    "title": row["title"],
                    "teaser_text": row["teaser_text"],
                    "render_mode": row["render_mode"],
                    "source_anchor": row["source_anchor"] or {},
                    "has_formula": bool(row["has_formula"]),
                    "has_code": bool(row["has_code"]),
                    "estimated_read_sec": int(row["estimated_read_sec"]),
                    "book_type": row["book_type"],
                }
            )
            if include_trace:
                items[-1]["_ranking_score"] = float(row.get("ranking_score") or 0.0)
        return items

    def _insert_single(self, cur: Any, event: dict[str, Any]) -> tuple[str, str | None]:
        try:
            event_id = self._to_uuid(event.get("event_id"))
            user_id = self._to_uuid(event.get("user_id"))
            book_id = self._to_uuid(event.get("book_id"))
            chunk_id = self._to_uuid(event.get("chunk_id"))
            event_ts = datetime.fromisoformat(str(event.get("event_ts")).replace("Z", "+00:00"))
            payload = event.get("payload", {}) or {}
            client = event.get("client", {}) or {}

            sql = """
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
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT DO NOTHING
            RETURNING event_id
            """
            params = (
                event_id,
                str(event.get("event_type")),
                event_ts,
                user_id,
                str(event.get("session_id")),
                book_id,
                chunk_id,
                float(event.get("position_in_chunk")),
                str(client.get("platform", "web")),
                str(client.get("app_version", "0.1.0")),
                str(client.get("device_id", "")) or None,
                str(event.get("idempotency_key")),
                Json(payload),
            )
            cur.execute(sql, params)
            if cur.fetchone() is None:
                return "deduplicated", None
            return "accepted", None
        except ValueError:
            return "rejected", "INVALID_PAYLOAD"
        except Exception as exc:
            msg = str(exc).lower()
            if "foreign key" in msg or "invalid input syntax for type uuid" in msg:
                return "rejected", "INVALID_PAYLOAD"
            return "rejected", "INTERNAL_ERROR"

    def insert_interactions_bulk(self, events: list[dict[str, Any]]) -> list[tuple[str, str | None]]:
        # Batch optimization: one connection + one transaction boundary for whole batch.
        # This removes per-event connect overhead while keeping per-event status.
        out: list[tuple[str, str | None]] = []
        with self._connect() as conn:
            with conn.cursor() as cur:
                for event in events:
                    out.append(self._insert_single(cur, event))
        return out

    def insert_rejections_bulk(self, rejections: list[dict[str, Any]]) -> None:
        if not rejections:
            return
        sql = """
        INSERT INTO interaction_rejections (
          trace_id,
          event_id,
          error_code,
          error_stage,
          event_type,
          user_id,
          book_id,
          chunk_id,
          reason,
          raw_event
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        rows = [
            (
                str(r.get("trace_id", "")),
                str(r.get("event_id", "")) or None,
                str(r.get("error_code", "UNKNOWN")),
                str(r.get("error_stage", "api_validation")),
                str(r.get("event_type", "")) or None,
                str(r.get("user_id", "")) or None,
                str(r.get("book_id", "")) or None,
                str(r.get("chunk_id", "")) or None,
                str(r.get("reason", "")) or None,
                Json(r.get("raw_event", {}) or {}),
            )
            for r in rejections
        ]
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, rows)

    def fetch_chunk_neighbors(self, book_id: str | None, chunk_id: str) -> dict[str, Any] | None:
        try:
            chunk_uuid = self._to_uuid(chunk_id)
            expected_book_uuid = self._to_uuid(book_id) if book_id else None
        except ValueError:
            return None

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id::text AS chunk_id, book_id::text AS book_id, global_index, title
                    FROM book_chunks
                    WHERE id = %s
                    """,
                    (chunk_uuid,),
                )
                current = cur.fetchone()
                if current is None:
                    return None
                if expected_book_uuid and current["book_id"] != str(expected_book_uuid):
                    return None

                cur.execute(
                    """
                    SELECT id::text AS chunk_id, title
                    FROM book_chunks
                    WHERE book_id = %s AND global_index < %s
                    ORDER BY global_index DESC
                    LIMIT 1
                    """,
                    (self._to_uuid(current["book_id"]), int(current["global_index"])),
                )
                prev_row = cur.fetchone()

                cur.execute(
                    """
                    SELECT id::text AS chunk_id, title
                    FROM book_chunks
                    WHERE book_id = %s AND global_index > %s
                    ORDER BY global_index ASC
                    LIMIT 1
                    """,
                    (self._to_uuid(current["book_id"]), int(current["global_index"])),
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

    def fetch_chunk_neighbors_batch(self, book_id: str | None, chunk_ids: list[str]) -> list[dict[str, Any]]:
        try:
            expected_book_uuid = self._to_uuid(book_id) if book_id else None
        except ValueError:
            return []
        chunk_uuids: list[UUID] = []
        for chunk_id in chunk_ids:
            try:
                chunk_uuids.append(self._to_uuid(chunk_id))
            except ValueError:
                continue
        if not chunk_uuids:
            return []

        if expected_book_uuid:
            sql = """
            WITH target AS (
              SELECT id, book_id
              FROM book_chunks
              WHERE id = ANY(%s::uuid[]) AND book_id = %s
            ),
            ctx AS (
              SELECT
                c.id::text AS chunk_id,
                c.book_id::text AS book_id,
                c.title,
                LAG(c.id::text) OVER (PARTITION BY c.book_id ORDER BY c.global_index) AS prev_chunk_id,
                LAG(c.title) OVER (PARTITION BY c.book_id ORDER BY c.global_index) AS prev_title,
                LEAD(c.id::text) OVER (PARTITION BY c.book_id ORDER BY c.global_index) AS next_chunk_id,
                LEAD(c.title) OVER (PARTITION BY c.book_id ORDER BY c.global_index) AS next_title
              FROM book_chunks c
              WHERE c.book_id = %s
            )
            SELECT
              ctx.book_id,
              ctx.chunk_id,
              ctx.title,
              ctx.prev_chunk_id,
              ctx.prev_title,
              ctx.next_chunk_id,
              ctx.next_title
            FROM ctx
            JOIN target t ON t.id::text = ctx.chunk_id
            ORDER BY array_position(%s::uuid[], t.id)
            """
            params: tuple[Any, ...] = (chunk_uuids, expected_book_uuid, expected_book_uuid, chunk_uuids)
        else:
            sql = """
            WITH target AS (
              SELECT id, book_id
              FROM book_chunks
              WHERE id = ANY(%s::uuid[])
            ),
            ctx AS (
              SELECT
                c.id::text AS chunk_id,
                c.book_id::text AS book_id,
                c.title,
                LAG(c.id::text) OVER (PARTITION BY c.book_id ORDER BY c.global_index) AS prev_chunk_id,
                LAG(c.title) OVER (PARTITION BY c.book_id ORDER BY c.global_index) AS prev_title,
                LEAD(c.id::text) OVER (PARTITION BY c.book_id ORDER BY c.global_index) AS next_chunk_id,
                LEAD(c.title) OVER (PARTITION BY c.book_id ORDER BY c.global_index) AS next_title
              FROM book_chunks c
              WHERE c.book_id IN (SELECT DISTINCT book_id FROM target)
            )
            SELECT
              ctx.book_id,
              ctx.chunk_id,
              ctx.title,
              ctx.prev_chunk_id,
              ctx.prev_title,
              ctx.next_chunk_id,
              ctx.next_title
            FROM ctx
            JOIN target t ON t.id::text = ctx.chunk_id
            ORDER BY array_position(%s::uuid[], t.id)
            """
            params = (chunk_uuids, chunk_uuids)

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()

        return [
            {
                "book_id": row["book_id"],
                "chunk_id": row["chunk_id"],
                "title": row.get("title"),
                "prev_chunk_id": row.get("prev_chunk_id"),
                "prev_title": row.get("prev_title"),
                "next_chunk_id": row.get("next_chunk_id"),
                "next_title": row.get("next_title"),
            }
            for row in rows
        ]

    def fetch_chunk_detail(self, book_id: str | None, chunk_id: str) -> dict[str, Any] | None:
        try:
            chunk_uuid = self._to_uuid(chunk_id)
            expected_book_uuid = self._to_uuid(book_id) if book_id else None
        except ValueError:
            return None

        sql = """
        SELECT
          c.id::text AS chunk_id,
          c.book_id::text AS book_id,
          b.title AS book_title,
          b.book_type::text AS book_type,
          c.section_id,
          c.title,
          c.text_content,
          COALESCE(c.teaser_text, LEFT(c.text_content, 120) || '...') AS teaser_text,
          c.render_mode::text AS render_mode,
          c.source_anchor,
          c.metadata,
          c.has_formula,
          c.has_code,
          c.has_table,
          COALESCE(c.read_time_sec_est, 0) AS estimated_read_sec
        FROM book_chunks c
        JOIN books b ON b.id = c.book_id
        WHERE c.id = %s
        """
        params: list[Any] = [chunk_uuid]
        if expected_book_uuid is not None:
            sql += " AND c.book_id = %s"
            params.append(expected_book_uuid)

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, tuple(params))
                row = cur.fetchone()
        if row is None:
            return None

        source_anchor = row["source_anchor"] or {}
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        content_type = str(metadata.get("content_type") or "text")
        section_pdf_url = metadata.get("section_pdf_url")
        if not section_pdf_url and content_type == "pdf_section":
            section_pdf_url = f"/v1/chunk_pdf?book_id={row['book_id']}&chunk_id={row['chunk_id']}"

        return {
            "book_id": row["book_id"],
            "book_title": row["book_title"],
            "book_type": row["book_type"],
            "chunk_id": row["chunk_id"],
            "section_id": row["section_id"],
            "title": row["title"],
            "text_content": row["text_content"],
            "teaser_text": row["teaser_text"],
            "render_mode": row["render_mode"],
            "source_anchor": source_anchor,
            "content_type": content_type,
            "section_pdf_url": section_pdf_url,
            "section_pdf_relpath": metadata.get("section_pdf_relpath"),
            "page_start": source_anchor.get("page_start"),
            "page_end": source_anchor.get("page_end"),
            "has_formula": bool(row["has_formula"]),
            "has_code": bool(row["has_code"]),
            "has_table": bool(row["has_table"]),
            "estimated_read_sec": int(row["estimated_read_sec"]),
        }

    def fetch_book_chunks_with_progress(
        self,
        book_id: str,
        user_id: str | None,
    ) -> tuple[str, list[dict[str, Any]]] | None:
        try:
            book_uuid = self._to_uuid(book_id)
            user_uuid = self._to_uuid(user_id) if user_id else None
        except ValueError:
            return None

        if user_uuid is not None:
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
	                AND i.event_type = 'section_complete'
	            ) stats ON TRUE
            WHERE b.id = %s
            ORDER BY c.global_index ASC
            """
            params: tuple[Any, ...] = (user_uuid, book_uuid)
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
            WHERE b.id = %s
            ORDER BY c.global_index ASC
            """
            params = (book_uuid,)

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()
        if not rows:
            return None
        book_title = str(rows[0]["book_title"] or "Unknown Book")
        chunks: list[dict[str, Any]] = []
        for row in rows:
            chunks.append(
                {
                    "chunk_id": row["chunk_id"],
                    "global_index": int(row["global_index"]),
                    "section_id": row["section_id"],
                    "chunk_title": row["chunk_title"],
                    "read_events": int(row["read_events"]),
                }
            )
        return book_title, chunks

    def fetch_memory_feed_items(self, user_id: str, limit: int, prefer_diversity: bool = True) -> list[dict[str, Any]]:
        try:
            user_uuid = self._to_uuid(user_id)
        except ValueError:
            return []
        if prefer_diversity:
            sql = """
            WITH ranked AS (
              SELECT
                mp.id::text AS memory_post_id,
                mp.memory_type,
                mp.source_date,
                mp.post_text,
                b.id::text AS book_id,
                b.title AS book_title,
                b.book_type::text AS book_type,
                c.id::text AS chunk_id,
                c.section_id,
                c.title,
                COALESCE(c.teaser_text, LEFT(c.text_content, 120) || '...') AS teaser_text,
                c.render_mode::text AS render_mode,
                c.source_anchor,
                c.has_formula,
                c.has_code,
                COALESCE(c.read_time_sec_est, 0) AS estimated_read_sec,
                ROW_NUMBER() OVER (
                  PARTITION BY mp.source_chunk_id
                  ORDER BY mp.source_date DESC, mp.created_at DESC
                ) AS source_chunk_rank,
                ROW_NUMBER() OVER (
                  PARTITION BY mp.memory_type
                  ORDER BY mp.source_date DESC, mp.created_at DESC
                ) AS memory_type_rank,
                ROW_NUMBER() OVER (
                  ORDER BY mp.source_date DESC, mp.created_at DESC
                ) AS global_rank
              FROM memory_posts mp
              JOIN books b ON b.id = mp.source_book_id
              JOIN book_chunks c ON c.id = mp.source_chunk_id
              WHERE mp.user_id = %s
                AND mp.status = 'inserted'
            )
            SELECT
              memory_post_id,
              memory_type,
              source_date,
              post_text,
              book_id,
              book_title,
              book_type,
              chunk_id,
              section_id,
              title,
              teaser_text,
              render_mode,
              source_anchor,
              has_formula,
              has_code,
              estimated_read_sec
            FROM ranked
            ORDER BY source_chunk_rank ASC, memory_type_rank ASC, global_rank ASC
            LIMIT %s
            """
        else:
            sql = """
            SELECT
              mp.id::text AS memory_post_id,
              mp.memory_type,
              mp.source_date,
              mp.post_text,
              b.id::text AS book_id,
              b.title AS book_title,
              b.book_type::text AS book_type,
              c.id::text AS chunk_id,
              c.section_id,
              c.title,
              COALESCE(c.teaser_text, LEFT(c.text_content, 120) || '...') AS teaser_text,
              c.render_mode::text AS render_mode,
              c.source_anchor,
              c.has_formula,
              c.has_code,
              COALESCE(c.read_time_sec_est, 0) AS estimated_read_sec
            FROM memory_posts mp
            JOIN books b ON b.id = mp.source_book_id
            JOIN book_chunks c ON c.id = mp.source_chunk_id
            WHERE mp.user_id = %s
              AND mp.status = 'inserted'
            ORDER BY mp.source_date DESC, mp.created_at DESC
            LIMIT %s
            """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (user_uuid, limit))
                rows = cur.fetchall()
        return [
            {
                "feed_item_id": f"mem_{row['memory_post_id']}",
                "item_type": "memory_post",
                "memory_type": row["memory_type"],
                "memory_source_date": row["source_date"].isoformat() if row.get("source_date") else None,
                "book_id": row["book_id"],
                "book_title": row["book_title"],
                "chunk_id": row["chunk_id"],
                "section_id": row["section_id"],
                "title": row["title"],
                "teaser_text": row.get("post_text") or row["teaser_text"],
                "render_mode": row["render_mode"],
                "source_anchor": row["source_anchor"] or {},
                "has_formula": bool(row["has_formula"]),
                "has_code": bool(row["has_code"]),
                "estimated_read_sec": int(row["estimated_read_sec"]),
                "book_type": row["book_type"],
            }
            for row in rows
        ]


def build_repository(seed_items: list[dict[str, Any]], dsn: str | None) -> BaseRepository:
    if dsn:
        try:
            return PostgresRepository(dsn)
        except Exception:
            return MemoryRepository(seed_items)
    return MemoryRepository(seed_items)
