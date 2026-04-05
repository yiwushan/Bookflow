import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "server"
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from repository import BaseRepository  # noqa: E402
from service import DataService  # noqa: E402


class CountingRepository(BaseRepository):
    backend = "counting"

    def __init__(self) -> None:
        self.batch_calls = 0

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
        self.batch_calls += 1
        return [
            {
                "book_id": book_id or "book-x",
                "chunk_id": chunk_id,
                "title": f"title-{chunk_id}",
                "prev_chunk_id": None,
                "prev_title": None,
                "next_chunk_id": None,
                "next_title": None,
            }
            for chunk_id in chunk_ids
        ]

    def fetch_memory_feed_items(self, user_id: str, limit: int) -> list[dict[str, Any]]:
        raise NotImplementedError


class ServiceCacheTests(unittest.TestCase):
    @staticmethod
    def _expected_chunk_first_seen_source(stats: dict[str, Any]) -> dict[str, dict[str, Any]]:
        expected: dict[str, dict[str, Any]] = {}
        for sample_index, sample in enumerate(stats.get("cache_key_samples", []), start=1):
            sample_book_id = sample.get("book_id")
            sample_book_id_text = str(sample_book_id) if sample_book_id is not None else None
            for chunk_id in (sample.get("chunk_ids") or []):
                chunk_id_text = str(chunk_id)
                if chunk_id_text in expected:
                    continue
                expected[chunk_id_text] = {
                    "book_id": sample_book_id_text,
                    "sample_index": sample_index,
                }
        return expected

    @staticmethod
    def _expected_chunk_first_seen_source_sorted_chunk_ids(stats: dict[str, Any]) -> list[str]:
        return sorted(ServiceCacheTests._expected_chunk_first_seen_source(stats).keys())

    def test_chunk_context_batch_cache_hit(self):
        repo = CountingRepository()
        now = {"ts": 100.0}
        service = DataService(
            repo,
            chunk_context_batch_cache_ttl_sec=5.0,
            chunk_context_batch_cache_max_entries=8,
            now_fn=lambda: now["ts"],
        )
        chunk_ids = ["ck1", "ck2"]

        first = service.fetch_chunk_neighbors_batch(book_id="b1", chunk_ids=chunk_ids)
        first[0]["title"] = "mutated"
        second = service.fetch_chunk_neighbors_batch(book_id="b1", chunk_ids=chunk_ids)

        self.assertEqual(repo.batch_calls, 1)
        self.assertEqual(second[0]["title"], "title-ck1")
        stats = service.get_chunk_context_batch_cache_stats()
        self.assertEqual(int(stats["cache_hit_count"]), 1)
        self.assertEqual(int(stats["cache_source_fetch_count"]), 1)
        self.assertEqual(int(stats["cache_expired_count"]), 0)
        self.assertIn("cache_key_cardinality", stats)
        self.assertIn("cache_key_samples", stats)
        self.assertIn("sample_count", stats)
        self.assertIn("sample_book_ids", stats)
        self.assertIn("sample_book_ids_count", stats)
        self.assertEqual(int(stats.get("sample_book_ids_count", -1)), len(stats.get("sample_book_ids", [])))
        expected_seen_order: list[str] = []
        for sample in stats.get("cache_key_samples", []):
            sample_book_id = sample.get("book_id")
            if sample_book_id is None:
                continue
            sample_book_id_text = str(sample_book_id)
            if sample_book_id_text not in expected_seen_order:
                expected_seen_order.append(sample_book_id_text)
        self.assertIn("sample_book_ids_sorted_by_seen", stats)
        self.assertEqual(stats.get("sample_book_ids_sorted_by_seen"), expected_seen_order)
        expected_chunk_ids = {
            str(chunk_id)
            for sample in stats.get("cache_key_samples", [])
            for chunk_id in (sample.get("chunk_ids") or [])
        }
        expected_chunk_order: list[str] = []
        for sample in stats.get("cache_key_samples", []):
            for chunk_id in (sample.get("chunk_ids") or []):
                chunk_id_text = str(chunk_id)
                if chunk_id_text not in expected_chunk_order:
                    expected_chunk_order.append(chunk_id_text)
        self.assertIn("sample_chunk_ids_count", stats)
        self.assertEqual(int(stats.get("sample_chunk_ids_count", -1)), len(expected_chunk_ids))
        self.assertIn("sample_chunk_ids_sorted_by_seen", stats)
        self.assertEqual(stats.get("sample_chunk_ids_sorted_by_seen"), expected_chunk_order)
        self.assertIn("sample_chunk_ids_first_seen_source", stats)
        self.assertEqual(
            stats.get("sample_chunk_ids_first_seen_source"),
            self._expected_chunk_first_seen_source(stats),
        )
        self.assertEqual(
            int(stats.get("sample_chunk_ids_first_seen_source_count", -1)),
            len(stats.get("sample_chunk_ids_first_seen_source", {})),
        )
        self.assertEqual(
            stats.get("sample_chunk_ids_first_seen_source_sorted_chunk_ids"),
            self._expected_chunk_first_seen_source_sorted_chunk_ids(stats),
        )
        self.assertIn("instance_id", stats)
        self.assertIsNotNone(stats.get("instance_started_ts"))

    def test_chunk_context_batch_cache_expired(self):
        repo = CountingRepository()
        now = {"ts": 200.0}
        service = DataService(
            repo,
            chunk_context_batch_cache_ttl_sec=2.0,
            now_fn=lambda: now["ts"],
        )
        chunk_ids = ["ck1", "ck2"]

        _ = service.fetch_chunk_neighbors_batch(book_id="b1", chunk_ids=chunk_ids)
        now["ts"] += 3.0
        _ = service.fetch_chunk_neighbors_batch(book_id="b1", chunk_ids=chunk_ids)

        self.assertEqual(repo.batch_calls, 2)
        stats = service.get_chunk_context_batch_cache_stats()
        self.assertEqual(int(stats["cache_source_fetch_count"]), 2)
        self.assertGreaterEqual(int(stats["cache_expired_count"]), 1)
        self.assertIn("cache_key_cardinality", stats)
        self.assertIn("cache_key_samples", stats)
        self.assertIn("sample_count", stats)
        self.assertIn("sample_book_ids", stats)
        self.assertIn("sample_book_ids_count", stats)
        self.assertEqual(int(stats.get("sample_book_ids_count", -1)), len(stats.get("sample_book_ids", [])))
        expected_seen_order: list[str] = []
        for sample in stats.get("cache_key_samples", []):
            sample_book_id = sample.get("book_id")
            if sample_book_id is None:
                continue
            sample_book_id_text = str(sample_book_id)
            if sample_book_id_text not in expected_seen_order:
                expected_seen_order.append(sample_book_id_text)
        self.assertIn("sample_book_ids_sorted_by_seen", stats)
        self.assertEqual(stats.get("sample_book_ids_sorted_by_seen"), expected_seen_order)
        expected_chunk_ids = {
            str(chunk_id)
            for sample in stats.get("cache_key_samples", [])
            for chunk_id in (sample.get("chunk_ids") or [])
        }
        expected_chunk_order: list[str] = []
        for sample in stats.get("cache_key_samples", []):
            for chunk_id in (sample.get("chunk_ids") or []):
                chunk_id_text = str(chunk_id)
                if chunk_id_text not in expected_chunk_order:
                    expected_chunk_order.append(chunk_id_text)
        self.assertIn("sample_chunk_ids_count", stats)
        self.assertEqual(int(stats.get("sample_chunk_ids_count", -1)), len(expected_chunk_ids))
        self.assertIn("sample_chunk_ids_sorted_by_seen", stats)
        self.assertEqual(stats.get("sample_chunk_ids_sorted_by_seen"), expected_chunk_order)
        self.assertIn("sample_chunk_ids_first_seen_source", stats)
        self.assertEqual(
            stats.get("sample_chunk_ids_first_seen_source"),
            self._expected_chunk_first_seen_source(stats),
        )
        self.assertEqual(
            int(stats.get("sample_chunk_ids_first_seen_source_count", -1)),
            len(stats.get("sample_chunk_ids_first_seen_source", {})),
        )
        self.assertEqual(
            stats.get("sample_chunk_ids_first_seen_source_sorted_chunk_ids"),
            self._expected_chunk_first_seen_source_sorted_chunk_ids(stats),
        )
        self.assertIn("instance_id", stats)
        self.assertIsNotNone(stats.get("instance_started_ts"))

    def test_chunk_context_batch_cache_disabled_when_ttl_non_positive(self):
        repo = CountingRepository()
        service = DataService(repo, chunk_context_batch_cache_ttl_sec=0.0)
        chunk_ids = ["ck1", "ck2"]

        _ = service.fetch_chunk_neighbors_batch(book_id="b1", chunk_ids=chunk_ids)
        _ = service.fetch_chunk_neighbors_batch(book_id="b1", chunk_ids=chunk_ids)

        self.assertEqual(repo.batch_calls, 2)
        stats = service.get_chunk_context_batch_cache_stats()
        self.assertEqual(int(stats["cache_hit_count"]), 0)
        self.assertEqual(int(stats["cache_source_fetch_count"]), 2)
        self.assertEqual(bool(stats["cache_enabled"]), False)
        self.assertIn("cache_key_cardinality", stats)
        self.assertIn("cache_key_samples", stats)
        self.assertIn("sample_count", stats)
        self.assertIn("sample_book_ids", stats)
        self.assertIn("sample_book_ids_count", stats)
        self.assertEqual(int(stats.get("sample_book_ids_count", -1)), len(stats.get("sample_book_ids", [])))
        expected_seen_order: list[str] = []
        for sample in stats.get("cache_key_samples", []):
            sample_book_id = sample.get("book_id")
            if sample_book_id is None:
                continue
            sample_book_id_text = str(sample_book_id)
            if sample_book_id_text not in expected_seen_order:
                expected_seen_order.append(sample_book_id_text)
        self.assertIn("sample_book_ids_sorted_by_seen", stats)
        self.assertEqual(stats.get("sample_book_ids_sorted_by_seen"), expected_seen_order)
        expected_chunk_ids = {
            str(chunk_id)
            for sample in stats.get("cache_key_samples", [])
            for chunk_id in (sample.get("chunk_ids") or [])
        }
        expected_chunk_order: list[str] = []
        for sample in stats.get("cache_key_samples", []):
            for chunk_id in (sample.get("chunk_ids") or []):
                chunk_id_text = str(chunk_id)
                if chunk_id_text not in expected_chunk_order:
                    expected_chunk_order.append(chunk_id_text)
        self.assertIn("sample_chunk_ids_count", stats)
        self.assertEqual(int(stats.get("sample_chunk_ids_count", -1)), len(expected_chunk_ids))
        self.assertIn("sample_chunk_ids_sorted_by_seen", stats)
        self.assertEqual(stats.get("sample_chunk_ids_sorted_by_seen"), expected_chunk_order)
        self.assertIn("sample_chunk_ids_first_seen_source", stats)
        self.assertEqual(
            stats.get("sample_chunk_ids_first_seen_source"),
            self._expected_chunk_first_seen_source(stats),
        )
        self.assertEqual(
            int(stats.get("sample_chunk_ids_first_seen_source_count", -1)),
            len(stats.get("sample_chunk_ids_first_seen_source", {})),
        )
        self.assertEqual(
            stats.get("sample_chunk_ids_first_seen_source_sorted_chunk_ids"),
            self._expected_chunk_first_seen_source_sorted_chunk_ids(stats),
        )
        self.assertIn("instance_id", stats)
        self.assertIsNotNone(stats.get("instance_started_ts"))

    def test_chunk_context_batch_cache_stats_reset(self):
        repo = CountingRepository()
        service = DataService(repo, chunk_context_batch_cache_ttl_sec=5.0)
        chunk_ids = ["ck1", "ck2"]
        _ = service.fetch_chunk_neighbors_batch(book_id="b1", chunk_ids=chunk_ids)
        _ = service.fetch_chunk_neighbors_batch(book_id="b1", chunk_ids=chunk_ids)
        before = service.get_chunk_context_batch_cache_stats()
        self.assertGreaterEqual(int(before["cache_source_fetch_count"]), 1)
        self.assertGreaterEqual(int(before["cache_hit_count"]), 1)

        after = service.reset_chunk_context_batch_cache_stats(clear_cache_entries=True)
        self.assertEqual(int(after["cache_source_fetch_count"]), 0)
        self.assertEqual(int(after["cache_hit_count"]), 0)
        self.assertEqual(int(after["cache_expired_count"]), 0)
        self.assertEqual(int(after["cache_entries"]), 0)
        self.assertEqual(int(after["cache_key_cardinality"]), 0)
        self.assertEqual(after.get("cache_key_samples"), [])
        self.assertEqual(int(after.get("sample_count", -1)), 0)
        self.assertEqual(after.get("sample_book_ids"), [])
        self.assertEqual(int(after.get("sample_book_ids_count", -1)), 0)
        self.assertEqual(after.get("sample_book_ids_sorted_by_seen"), [])
        self.assertEqual(int(after.get("sample_chunk_ids_count", -1)), 0)
        self.assertEqual(after.get("sample_chunk_ids_sorted_by_seen"), [])
        self.assertEqual(after.get("sample_chunk_ids_first_seen_source"), {})
        self.assertEqual(int(after.get("sample_chunk_ids_first_seen_source_count", -1)), 0)
        self.assertEqual(after.get("sample_chunk_ids_first_seen_source_sorted_chunk_ids"), [])
        self.assertIsNone(after.get("last_reset_trace_id"))
        self.assertIsNotNone(after.get("reset_ts"))
        self.assertIn("instance_id", after)
        self.assertIsNotNone(after.get("instance_started_ts"))

    def test_chunk_context_batch_cache_stats_trace_association(self):
        repo = CountingRepository()
        service = DataService(repo, chunk_context_batch_cache_ttl_sec=5.0)
        _ = service.fetch_chunk_neighbors_batch(book_id="b1", chunk_ids=["ck1"])
        stats_default = service.get_chunk_context_batch_cache_stats()
        self.assertNotIn("request_trace_id", stats_default)
        stats_with_trace = service.get_chunk_context_batch_cache_stats(request_trace_id="tr_ctxb_abc")
        self.assertEqual(stats_with_trace.get("request_trace_id"), "tr_ctxb_abc")
        self.assertIn("cache_key_cardinality", stats_with_trace)
        self.assertIn("cache_key_samples", stats_with_trace)
        self.assertIn("sample_count", stats_with_trace)
        self.assertIn("sample_book_ids", stats_with_trace)
        self.assertIn("sample_book_ids_count", stats_with_trace)
        self.assertEqual(
            int(stats_with_trace.get("sample_book_ids_count", -1)),
            len(stats_with_trace.get("sample_book_ids", [])),
        )
        expected_seen_order: list[str] = []
        for sample in stats_with_trace.get("cache_key_samples", []):
            sample_book_id = sample.get("book_id")
            if sample_book_id is None:
                continue
            sample_book_id_text = str(sample_book_id)
            if sample_book_id_text not in expected_seen_order:
                expected_seen_order.append(sample_book_id_text)
        self.assertIn("sample_book_ids_sorted_by_seen", stats_with_trace)
        self.assertEqual(stats_with_trace.get("sample_book_ids_sorted_by_seen"), expected_seen_order)
        expected_chunk_ids = {
            str(chunk_id)
            for sample in stats_with_trace.get("cache_key_samples", [])
            for chunk_id in (sample.get("chunk_ids") or [])
        }
        expected_chunk_order: list[str] = []
        for sample in stats_with_trace.get("cache_key_samples", []):
            for chunk_id in (sample.get("chunk_ids") or []):
                chunk_id_text = str(chunk_id)
                if chunk_id_text not in expected_chunk_order:
                    expected_chunk_order.append(chunk_id_text)
        self.assertIn("sample_chunk_ids_count", stats_with_trace)
        self.assertEqual(int(stats_with_trace.get("sample_chunk_ids_count", -1)), len(expected_chunk_ids))
        self.assertIn("sample_chunk_ids_sorted_by_seen", stats_with_trace)
        self.assertEqual(stats_with_trace.get("sample_chunk_ids_sorted_by_seen"), expected_chunk_order)
        self.assertIn("sample_chunk_ids_first_seen_source", stats_with_trace)
        self.assertEqual(
            stats_with_trace.get("sample_chunk_ids_first_seen_source"),
            self._expected_chunk_first_seen_source(stats_with_trace),
        )
        self.assertEqual(
            int(stats_with_trace.get("sample_chunk_ids_first_seen_source_count", -1)),
            len(stats_with_trace.get("sample_chunk_ids_first_seen_source", {})),
        )
        self.assertEqual(
            stats_with_trace.get("sample_chunk_ids_first_seen_source_sorted_chunk_ids"),
            self._expected_chunk_first_seen_source_sorted_chunk_ids(stats_with_trace),
        )
        self.assertIn("instance_id", stats_with_trace)
        self.assertIsNotNone(stats_with_trace.get("instance_started_ts"))

    def test_chunk_context_batch_cache_reset_trace_record(self):
        repo = CountingRepository()
        service = DataService(repo, chunk_context_batch_cache_ttl_sec=5.0)
        stats = service.reset_chunk_context_batch_cache_stats(clear_cache_entries=True, reset_trace_id="tr_ctxb_reset")
        self.assertEqual(stats.get("last_reset_trace_id"), "tr_ctxb_reset")
        self.assertIsNotNone(stats.get("reset_ts"))
        self.assertIn("cache_key_cardinality", stats)
        self.assertIn("cache_key_samples", stats)
        self.assertIn("sample_count", stats)
        self.assertIn("sample_book_ids", stats)
        self.assertIn("sample_book_ids_count", stats)
        self.assertEqual(int(stats.get("sample_book_ids_count", -1)), len(stats.get("sample_book_ids", [])))
        expected_seen_order: list[str] = []
        for sample in stats.get("cache_key_samples", []):
            sample_book_id = sample.get("book_id")
            if sample_book_id is None:
                continue
            sample_book_id_text = str(sample_book_id)
            if sample_book_id_text not in expected_seen_order:
                expected_seen_order.append(sample_book_id_text)
        self.assertIn("sample_book_ids_sorted_by_seen", stats)
        self.assertEqual(stats.get("sample_book_ids_sorted_by_seen"), expected_seen_order)
        expected_chunk_ids = {
            str(chunk_id)
            for sample in stats.get("cache_key_samples", [])
            for chunk_id in (sample.get("chunk_ids") or [])
        }
        expected_chunk_order: list[str] = []
        for sample in stats.get("cache_key_samples", []):
            for chunk_id in (sample.get("chunk_ids") or []):
                chunk_id_text = str(chunk_id)
                if chunk_id_text not in expected_chunk_order:
                    expected_chunk_order.append(chunk_id_text)
        self.assertIn("sample_chunk_ids_count", stats)
        self.assertEqual(int(stats.get("sample_chunk_ids_count", -1)), len(expected_chunk_ids))
        self.assertIn("sample_chunk_ids_sorted_by_seen", stats)
        self.assertEqual(stats.get("sample_chunk_ids_sorted_by_seen"), expected_chunk_order)
        self.assertIn("sample_chunk_ids_first_seen_source", stats)
        self.assertEqual(
            stats.get("sample_chunk_ids_first_seen_source"),
            self._expected_chunk_first_seen_source(stats),
        )
        self.assertEqual(
            int(stats.get("sample_chunk_ids_first_seen_source_count", -1)),
            len(stats.get("sample_chunk_ids_first_seen_source", {})),
        )
        self.assertEqual(
            stats.get("sample_chunk_ids_first_seen_source_sorted_chunk_ids"),
            self._expected_chunk_first_seen_source_sorted_chunk_ids(stats),
        )
        self.assertIn("instance_id", stats)
        self.assertIsNotNone(stats.get("instance_started_ts"))

    def test_chunk_context_batch_cache_key_samples_limited(self):
        repo = CountingRepository()
        service = DataService(repo, chunk_context_batch_cache_ttl_sec=5.0)
        service.fetch_chunk_neighbors_batch(book_id="b1", chunk_ids=["a1"])
        service.fetch_chunk_neighbors_batch(book_id="b1", chunk_ids=["a2"])
        service.fetch_chunk_neighbors_batch(book_id="b1", chunk_ids=["a3"])
        service.fetch_chunk_neighbors_batch(book_id="b1", chunk_ids=["a4"])
        stats = service.get_chunk_context_batch_cache_stats()
        samples = stats.get("cache_key_samples")
        self.assertIsInstance(samples, list)
        self.assertLessEqual(len(samples), 3)
        self.assertEqual(int(stats.get("sample_count", -1)), len(samples))
        self.assertIn("sample_book_ids", stats)
        self.assertIn("sample_book_ids_count", stats)
        self.assertEqual(int(stats.get("sample_book_ids_count", -1)), len(stats.get("sample_book_ids", [])))
        expected_seen_order: list[str] = []
        for sample in stats.get("cache_key_samples", []):
            sample_book_id = sample.get("book_id")
            if sample_book_id is None:
                continue
            sample_book_id_text = str(sample_book_id)
            if sample_book_id_text not in expected_seen_order:
                expected_seen_order.append(sample_book_id_text)
        self.assertIn("sample_book_ids_sorted_by_seen", stats)
        self.assertEqual(stats.get("sample_book_ids_sorted_by_seen"), expected_seen_order)
        expected_chunk_ids = {
            str(chunk_id)
            for sample in stats.get("cache_key_samples", [])
            for chunk_id in (sample.get("chunk_ids") or [])
        }
        expected_chunk_order: list[str] = []
        for sample in stats.get("cache_key_samples", []):
            for chunk_id in (sample.get("chunk_ids") or []):
                chunk_id_text = str(chunk_id)
                if chunk_id_text not in expected_chunk_order:
                    expected_chunk_order.append(chunk_id_text)
        self.assertIn("sample_chunk_ids_count", stats)
        self.assertEqual(int(stats.get("sample_chunk_ids_count", -1)), len(expected_chunk_ids))
        self.assertIn("sample_chunk_ids_sorted_by_seen", stats)
        self.assertEqual(stats.get("sample_chunk_ids_sorted_by_seen"), expected_chunk_order)
        self.assertIn("sample_chunk_ids_first_seen_source", stats)
        self.assertEqual(
            stats.get("sample_chunk_ids_first_seen_source"),
            self._expected_chunk_first_seen_source(stats),
        )
        self.assertEqual(
            int(stats.get("sample_chunk_ids_first_seen_source_count", -1)),
            len(stats.get("sample_chunk_ids_first_seen_source", {})),
        )
        self.assertEqual(
            stats.get("sample_chunk_ids_first_seen_source_sorted_chunk_ids"),
            self._expected_chunk_first_seen_source_sorted_chunk_ids(stats),
        )
        for sample in samples:
            self.assertIn("book_id", sample)
            self.assertIn("chunk_ids", sample)
            self.assertIn("expire_in_sec", sample)
            self.assertIn("expire_estimate_ts", sample)


if __name__ == "__main__":
    unittest.main()
