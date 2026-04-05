from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from repository import BaseRepository


class DataService:
    def __init__(
        self,
        repository: BaseRepository,
        chunk_context_batch_cache_ttl_sec: float | None = None,
        chunk_context_batch_cache_max_entries: int | None = None,
        now_fn: Any | None = None,
    ) -> None:
        self.repository = repository
        self.backend = repository.backend
        self._now_fn = now_fn or time.monotonic
        self._chunk_context_batch_cache_ttl_sec = self._parse_float_env(
            value=chunk_context_batch_cache_ttl_sec,
            env_name="BOOKFLOW_CHUNK_CONTEXT_BATCH_CACHE_TTL_SEC",
            default_value=5.0,
        )
        self._chunk_context_batch_cache_max_entries = self._parse_int_env(
            value=chunk_context_batch_cache_max_entries,
            env_name="BOOKFLOW_CHUNK_CONTEXT_BATCH_CACHE_MAX_ENTRIES",
            default_value=256,
        )
        self._chunk_context_batch_cache: dict[
            tuple[str | None, tuple[str, ...]],
            tuple[float, list[dict[str, Any]]],
        ] = {}
        self._chunk_context_batch_cache_hit_count = 0
        self._chunk_context_batch_cache_expired_count = 0
        self._chunk_context_batch_cache_source_fetch_count = 0
        self._chunk_context_batch_cache_last_reset_trace_id: str | None = None
        self._chunk_context_batch_cache_last_reset_ts: str | None = None
        self._chunk_context_batch_cache_instance_id = os.getenv("BOOKFLOW_INSTANCE_ID", f"pid:{os.getpid()}")
        self._chunk_context_batch_cache_instance_started_ts = datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _parse_float_env(value: float | None, env_name: str, default_value: float) -> float:
        if value is not None:
            return float(value)
        raw = os.getenv(env_name)
        if raw is None:
            return default_value
        try:
            return float(raw)
        except Exception:
            return default_value

    @staticmethod
    def _parse_int_env(value: int | None, env_name: str, default_value: int) -> int:
        if value is not None:
            return int(value)
        raw = os.getenv(env_name)
        if raw is None:
            return default_value
        try:
            return int(raw)
        except Exception:
            return default_value

    @staticmethod
    def _clone_context_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [dict(item) for item in items]

    @staticmethod
    def _cache_key_samples(
        cache: dict[tuple[str | None, tuple[str, ...]], tuple[float, list[dict[str, Any]]]],
        *,
        now_monotonic: float,
        now_utc: datetime,
        max_items: int = 3,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        keys = sorted(cache.keys(), key=lambda key: ((key[0] or ""), ",".join(key[1])))
        for key in keys[: max(0, int(max_items))]:
            expire_at_monotonic = float(cache[key][0])
            expire_in_sec = max(0.0, expire_at_monotonic - float(now_monotonic))
            expire_estimate_ts = (now_utc + timedelta(seconds=expire_in_sec)).isoformat()
            out.append(
                {
                    "book_id": key[0],
                    "chunk_ids": list(key[1]),
                    "expire_in_sec": round(expire_in_sec, 3),
                    "expire_estimate_ts": expire_estimate_ts,
                }
            )
        return out

    def _cache_prune(self, now_ts: float) -> None:
        if not self._chunk_context_batch_cache:
            return
        expired_keys = [k for k, (expire_at, _) in self._chunk_context_batch_cache.items() if expire_at <= now_ts]
        for key in expired_keys:
            self._chunk_context_batch_cache.pop(key, None)
        self._chunk_context_batch_cache_expired_count += len(expired_keys)

        max_entries = max(1, self._chunk_context_batch_cache_max_entries)
        overflow = len(self._chunk_context_batch_cache) - max_entries
        if overflow <= 0:
            return
        # 删除最早过期的缓存项，避免无限增长。
        ordered = sorted(self._chunk_context_batch_cache.items(), key=lambda kv: kv[1][0])
        for key, _ in ordered[:overflow]:
            self._chunk_context_batch_cache.pop(key, None)

    def _cache_get(self, key: tuple[str | None, tuple[str, ...]], now_ts: float) -> list[dict[str, Any]] | None:
        cached = self._chunk_context_batch_cache.get(key)
        if cached is None:
            return None
        expire_at, items = cached
        if expire_at <= now_ts:
            self._chunk_context_batch_cache.pop(key, None)
            self._chunk_context_batch_cache_expired_count += 1
            return None
        self._chunk_context_batch_cache_hit_count += 1
        return self._clone_context_items(items)

    def _cache_set(self, key: tuple[str | None, tuple[str, ...]], items: list[dict[str, Any]], now_ts: float) -> None:
        ttl_sec = self._chunk_context_batch_cache_ttl_sec
        if ttl_sec <= 0:
            return
        expire_at = now_ts + ttl_sec
        self._chunk_context_batch_cache[key] = (expire_at, self._clone_context_items(items))
        self._cache_prune(now_ts)

    def get_chunk_context_batch_cache_stats(self, request_trace_id: str | None = None) -> dict[str, Any]:
        total_lookup = self._chunk_context_batch_cache_hit_count + self._chunk_context_batch_cache_source_fetch_count
        hit_rate = (self._chunk_context_batch_cache_hit_count / total_lookup) if total_lookup > 0 else 0.0
        now_monotonic = float(self._now_fn())
        now_utc = datetime.now(timezone.utc)
        cache_key_samples = self._cache_key_samples(
            self._chunk_context_batch_cache,
            now_monotonic=now_monotonic,
            now_utc=now_utc,
            max_items=3,
        )
        sample_book_ids = sorted({str(x.get("book_id")) for x in cache_key_samples if x.get("book_id") is not None})
        sample_book_ids_sorted_by_seen: list[str] = []
        seen_book_ids: set[str] = set()
        for sample in cache_key_samples:
            sample_book_id = sample.get("book_id")
            if sample_book_id is None:
                continue
            sample_book_id_text = str(sample_book_id)
            if sample_book_id_text in seen_book_ids:
                continue
            seen_book_ids.add(sample_book_id_text)
            sample_book_ids_sorted_by_seen.append(sample_book_id_text)
        sample_chunk_ids = sorted(
            {
                str(chunk_id)
                for sample in cache_key_samples
                for chunk_id in (sample.get("chunk_ids") or [])
                if chunk_id is not None
            }
        )
        sample_chunk_ids_sorted_by_seen: list[str] = []
        seen_chunk_ids: set[str] = set()
        sample_chunk_ids_first_seen_source: dict[str, dict[str, Any]] = {}
        for sample_index, sample in enumerate(cache_key_samples, start=1):
            sample_book_id = sample.get("book_id")
            source_book_id = str(sample_book_id) if sample_book_id is not None else None
            for chunk_id in (sample.get("chunk_ids") or []):
                if chunk_id is None:
                    continue
                chunk_id_text = str(chunk_id)
                if chunk_id_text in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(chunk_id_text)
                sample_chunk_ids_sorted_by_seen.append(chunk_id_text)
                sample_chunk_ids_first_seen_source[chunk_id_text] = {
                    "book_id": source_book_id,
                    "sample_index": sample_index,
                }
        sample_chunk_ids_first_seen_source_sorted_chunk_ids = sorted(sample_chunk_ids_first_seen_source.keys())
        payload = {
            "cache_enabled": self._chunk_context_batch_cache_ttl_sec > 0,
            "cache_ttl_sec": float(self._chunk_context_batch_cache_ttl_sec),
            "cache_max_entries": int(self._chunk_context_batch_cache_max_entries),
            "cache_entries": len(self._chunk_context_batch_cache),
            # 进程内缓存可直接拿到 key 集合，当前以条目数作为 cardinality 估算。
            "cache_key_cardinality": len(self._chunk_context_batch_cache),
            "cache_key_samples": cache_key_samples,
            "sample_count": len(cache_key_samples),
            "sample_book_ids": sample_book_ids,
            "sample_book_ids_count": len(sample_book_ids),
            "sample_book_ids_sorted_by_seen": sample_book_ids_sorted_by_seen,
            "sample_chunk_ids_count": len(sample_chunk_ids),
            "sample_chunk_ids_sorted_by_seen": sample_chunk_ids_sorted_by_seen,
            "sample_chunk_ids_first_seen_source": sample_chunk_ids_first_seen_source,
            "sample_chunk_ids_first_seen_source_count": len(sample_chunk_ids_first_seen_source),
            "sample_chunk_ids_first_seen_source_sorted_chunk_ids": (
                sample_chunk_ids_first_seen_source_sorted_chunk_ids
            ),
            "cache_hit_count": int(self._chunk_context_batch_cache_hit_count),
            "cache_expired_count": int(self._chunk_context_batch_cache_expired_count),
            "cache_source_fetch_count": int(self._chunk_context_batch_cache_source_fetch_count),
            "cache_hit_rate": round(hit_rate, 4),
            "last_reset_trace_id": self._chunk_context_batch_cache_last_reset_trace_id,
            "reset_ts": self._chunk_context_batch_cache_last_reset_ts,
            "instance_id": self._chunk_context_batch_cache_instance_id,
            "instance_started_ts": self._chunk_context_batch_cache_instance_started_ts,
        }
        if request_trace_id:
            payload["request_trace_id"] = str(request_trace_id)
        return payload

    def reset_chunk_context_batch_cache_stats(
        self,
        clear_cache_entries: bool = False,
        reset_trace_id: str | None = None,
    ) -> dict[str, Any]:
        self._chunk_context_batch_cache_hit_count = 0
        self._chunk_context_batch_cache_expired_count = 0
        self._chunk_context_batch_cache_source_fetch_count = 0
        self._chunk_context_batch_cache_last_reset_trace_id = str(reset_trace_id) if reset_trace_id else None
        self._chunk_context_batch_cache_last_reset_ts = datetime.now(timezone.utc).isoformat()
        if clear_cache_entries:
            self._chunk_context_batch_cache.clear()
        return self.get_chunk_context_batch_cache_stats()

    def fetch_feed_items(
        self,
        limit: int,
        offset: int,
        mode: str,
        book_type: str | None,
        user_id: str | None = None,
        include_trace: bool = False,
    ) -> list[dict[str, Any]]:
        return self.repository.fetch_feed_items(
            limit=limit,
            offset=offset,
            mode=mode,
            book_type=book_type,
            user_id=user_id,
            include_trace=include_trace,
        )

    def insert_interactions_bulk(self, events: list[dict[str, Any]]) -> list[tuple[str, str | None]]:
        return self.repository.insert_interactions_bulk(events)

    def insert_rejections_bulk(self, rejections: list[dict[str, Any]]) -> None:
        self.repository.insert_rejections_bulk(rejections)

    def fetch_chunk_neighbors(self, book_id: str | None, chunk_id: str) -> dict[str, Any] | None:
        return self.repository.fetch_chunk_neighbors(book_id=book_id, chunk_id=chunk_id)

    def fetch_chunk_neighbors_batch(self, book_id: str | None, chunk_ids: list[str]) -> list[dict[str, Any]]:
        if self._chunk_context_batch_cache_ttl_sec <= 0:
            self._chunk_context_batch_cache_source_fetch_count += 1
            return self.repository.fetch_chunk_neighbors_batch(book_id=book_id, chunk_ids=chunk_ids)

        now_ts = float(self._now_fn())
        self._cache_prune(now_ts)
        key = (book_id, tuple(chunk_ids))
        cached = self._cache_get(key, now_ts)
        if cached is not None:
            return cached

        self._chunk_context_batch_cache_source_fetch_count += 1
        fresh = self.repository.fetch_chunk_neighbors_batch(book_id=book_id, chunk_ids=chunk_ids)
        self._cache_set(key, fresh, now_ts)
        return self._clone_context_items(fresh)

    def fetch_chunk_detail(self, book_id: str | None, chunk_id: str) -> dict[str, Any] | None:
        return self.repository.fetch_chunk_detail(book_id=book_id, chunk_id=chunk_id)

    @staticmethod
    def build_mosaic_tiles(
        chunks: list[dict[str, Any]],
        *,
        min_read_events: int = 1,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
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

    def fetch_book_mosaic(
        self,
        *,
        book_id: str,
        user_id: str | None,
        min_read_events: int = 1,
    ) -> dict[str, Any] | None:
        result = self.repository.fetch_book_chunks_with_progress(book_id=book_id, user_id=user_id)
        if result is None:
            return None
        book_title, chunks = result
        tiles, summary = self.build_mosaic_tiles(chunks, min_read_events=min_read_events)
        return {
            "book_id": str(book_id),
            "book_title": str(book_title),
            "user_id": user_id,
            "min_read_events": max(1, int(min_read_events)),
            "summary": summary,
            "tiles": tiles,
        }

    def fetch_memory_feed_items(self, user_id: str, limit: int, prefer_diversity: bool = True) -> list[dict[str, Any]]:
        return self.repository.fetch_memory_feed_items(
            user_id=user_id,
            limit=limit,
            prefer_diversity=prefer_diversity,
        )
