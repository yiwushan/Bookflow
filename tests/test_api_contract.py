import json
import os
import socket
import subprocess
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class ApiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.port = get_free_port()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.token = "contract-test-token"
        cls._tmp_dir = tempfile.TemporaryDirectory()
        cls._toc_store_path = str(Path(cls._tmp_dir.name) / "manual_annotations.json")

        env = os.environ.copy()
        env["BOOKFLOW_TOKEN"] = cls.token
        env["BOOKFLOW_TOC_STORE_PATH"] = cls._toc_store_path
        env.pop("DATABASE_URL", None)  # force memory backend in contract tests

        cls.proc = subprocess.Popen(
            ["python3", "server/app.py", "--host", "127.0.0.1", "--port", str(cls.port)],
            cwd=str(cls.repo_root),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                status, payload = cls.request("GET", "/health")
                if status == 200 and payload.get("status") == "ok":
                    return
            except Exception:
                pass
            time.sleep(0.1)
        raise RuntimeError("server did not become ready in time")

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "proc", None) is not None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                cls.proc.kill()
        if getattr(cls, "_tmp_dir", None) is not None:
            cls._tmp_dir.cleanup()

    @classmethod
    def request(cls, method: str, path: str, body: dict | None = None, auth: bool = False):
        url = f"{cls.base_url}{path}"
        data = None
        headers = {"Content-Type": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
        if auth:
            headers["Authorization"] = f"Bearer {cls.token}"
        req = Request(url, method=method, data=data, headers=headers)
        try:
            with urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            payload = json.loads(e.read().decode("utf-8"))
            return e.code, payload

    @staticmethod
    def _expected_chunk_first_seen_source(cache_stats: dict) -> dict[str, dict[str, object | None]]:
        expected: dict[str, dict[str, object | None]] = {}
        for sample_index, sample in enumerate(cache_stats.get("cache_key_samples", []), start=1):
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
    def _expected_chunk_first_seen_source_sorted_chunk_ids(cache_stats: dict) -> list[str]:
        return sorted(ApiContractTests._expected_chunk_first_seen_source(cache_stats).keys())

    def test_health_contract(self):
        status, payload = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload.get("status"), "ok")
        self.assertIn(payload.get("backend"), {"memory", "postgres"})
        self.assertIn("trace_id", payload)

    def test_feed_requires_auth(self):
        status, payload = self.request("GET", "/v1/feed?limit=2")
        self.assertEqual(status, 401)
        self.assertEqual(payload["error"]["code"], "INVALID_AUTH")

    def test_feed_success_contract(self):
        status, payload = self.request("GET", "/v1/feed?limit=2&mode=default", auth=True)
        self.assertEqual(status, 200)
        self.assertIn("items", payload)
        self.assertIsInstance(payload["items"], list)
        self.assertIn("next_cursor", payload)
        self.assertIn("memory_inserted", payload)
        self.assertIn("trace_id", payload)

    def test_feed_trace_contract(self):
        status, payload = self.request("GET", "/v1/feed?limit=2&mode=default&trace=1", auth=True)
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(payload.get("items", [])), 1)
        self.assertIn("ranking_trace", payload["items"][0])

    def test_feed_trace_file_contract(self):
        status, payload = self.request("GET", "/v1/feed?limit=2&mode=default&trace=1&trace_file=1", auth=True)
        self.assertEqual(status, 200)
        trace_id = payload.get("trace_id")
        self.assertIsNotNone(trace_id)
        self.assertIsNotNone(payload.get("trace_file_path"))
        trace_path = self.repo_root / "logs" / "feed_trace" / f"{trace_id}.json"
        self.assertEqual(payload.get("trace_file_path"), str(trace_path))
        self.assertTrue(trace_path.exists())
        try:
            saved = json.loads(trace_path.read_text(encoding="utf-8"))
            self.assertEqual(saved.get("trace_id"), trace_id)
            self.assertIn("memory_diversity_source", saved.get("query", {}))
            self.assertIn("memory_diversity_gray_percent", saved.get("query", {}))
            self.assertIn("memory_diversity_rollout_threshold_percent", saved.get("query", {}))
            self.assertIn("memory_diversity_rollout_enabled", saved.get("query", {}))
            self.assertIn("memory_diversity_rollout_mode", saved.get("query", {}))
            self.assertIn("memory_diversity_bucket", saved.get("query", {}))
            self.assertIn("memory_diversity_rollout_bucket_percentile", saved.get("query", {}))
            self.assertIn("memory_diversity_rollout_bucket_percentile_source", saved.get("query", {}))
            self.assertIn("memory_diversity_rollout_bucket_percentile_label", saved.get("query", {}))
            self.assertIn("memory_diversity_rollout_bucket_hit", saved.get("query", {}))
            self.assertIn("memory_diversity_rollout_bucket_distance", saved.get("query", {}))
            self.assertIn("memory_diversity_default_note", saved.get("query", {}))
            self.assertIsInstance(saved.get("query", {}).get("memory_diversity_rollout_enabled"), bool)
            self.assertIn(saved.get("query", {}).get("memory_diversity_rollout_mode"), {"off", "partial", "full"})
            self.assertIsInstance(saved.get("query", {}).get("memory_diversity_rollout_bucket_hit"), bool)
            distance = saved.get("query", {}).get("memory_diversity_rollout_bucket_distance")
            self.assertTrue(distance is None or isinstance(distance, int))
            threshold = saved.get("query", {}).get("memory_diversity_rollout_threshold_percent")
            self.assertTrue(threshold is None or isinstance(threshold, int))
            bucket = int(saved.get("query", {}).get("memory_diversity_bucket"))
            bucket_percentile = saved.get("query", {}).get("memory_diversity_rollout_bucket_percentile")
            self.assertIsInstance(bucket_percentile, float)
            self.assertGreaterEqual(bucket_percentile, 0.0)
            self.assertLess(bucket_percentile, 1.0)
            self.assertAlmostEqual(bucket_percentile, round(bucket / 100.0, 2))
            self.assertEqual(
                saved.get("query", {}).get("memory_diversity_rollout_bucket_percentile_source"),
                "derived_from_bucket",
            )
            self.assertEqual(
                saved.get("query", {}).get("memory_diversity_rollout_bucket_percentile_label"),
                f"P{bucket:02d}",
            )
            self.assertGreaterEqual(bucket, 0)
            self.assertLess(bucket, 100)
        finally:
            trace_path.unlink(missing_ok=True)

    def test_feed_trace_file_memory_diversity_source_query(self):
        user_id = "11111111-1111-1111-1111-111111111111"
        status, payload = self.request(
            "GET",
            f"/v1/feed?limit=2&mode=default&trace=1&trace_file=1&with_memory=1&user_id={user_id}&memory_diversity=off",
            auth=True,
        )
        self.assertEqual(status, 200)
        trace_id = payload.get("trace_id")
        self.assertIsNotNone(trace_id)
        self.assertIsNotNone(payload.get("trace_file_path"))
        trace_path = self.repo_root / "logs" / "feed_trace" / f"{trace_id}.json"
        self.assertEqual(payload.get("trace_file_path"), str(trace_path))
        self.assertTrue(trace_path.exists())
        try:
            saved = json.loads(trace_path.read_text(encoding="utf-8"))
            self.assertEqual(saved.get("query", {}).get("memory_diversity_source"), "query")
            self.assertIn("memory_diversity_gray_percent", saved.get("query", {}))
            self.assertIn("memory_diversity_rollout_threshold_percent", saved.get("query", {}))
            self.assertIn("memory_diversity_rollout_enabled", saved.get("query", {}))
            self.assertIn("memory_diversity_rollout_mode", saved.get("query", {}))
            self.assertIn("memory_diversity_bucket", saved.get("query", {}))
            self.assertIn("memory_diversity_rollout_bucket_percentile", saved.get("query", {}))
            self.assertIn("memory_diversity_rollout_bucket_percentile_source", saved.get("query", {}))
            self.assertIn("memory_diversity_rollout_bucket_percentile_label", saved.get("query", {}))
            self.assertIn("memory_diversity_rollout_bucket_hit", saved.get("query", {}))
            self.assertIn("memory_diversity_rollout_bucket_distance", saved.get("query", {}))
            self.assertIn("memory_diversity_default_note", saved.get("query", {}))
            self.assertEqual(
                saved.get("query", {}).get("memory_diversity_rollout_bucket_percentile_source"),
                "derived_from_bucket",
            )
            bucket = int(saved.get("query", {}).get("memory_diversity_bucket"))
            self.assertEqual(
                saved.get("query", {}).get("memory_diversity_rollout_bucket_percentile_label"),
                f"P{bucket:02d}",
            )
        finally:
            trace_path.unlink(missing_ok=True)

    def test_feed_invalid_query_contract(self):
        status, payload = self.request("GET", "/v1/feed?limit=999&mode=default", auth=True)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_QUERY")

    def test_feed_invalid_user_id_contract(self):
        status, payload = self.request("GET", "/v1/feed?limit=2&user_id=not-a-uuid", auth=True)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_QUERY")

    def test_feed_with_memory_requires_user_id(self):
        status, payload = self.request("GET", "/v1/feed?limit=2&with_memory=1", auth=True)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_QUERY")

    def test_feed_memory_every_requires_with_memory(self):
        user_id = "11111111-1111-1111-1111-111111111111"
        status, payload = self.request("GET", f"/v1/feed?limit=2&user_id={user_id}&memory_every=3", auth=True)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_QUERY")

    def test_feed_memory_every_validation(self):
        user_id = "11111111-1111-1111-1111-111111111111"
        status, payload = self.request(
            "GET",
            f"/v1/feed?limit=2&with_memory=1&user_id={user_id}&memory_every=0",
            auth=True,
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_QUERY")

    def test_feed_memory_position_requires_with_memory(self):
        user_id = "11111111-1111-1111-1111-111111111111"
        status, payload = self.request(
            "GET",
            f"/v1/feed?limit=2&user_id={user_id}&memory_position=random",
            auth=True,
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_QUERY")

    def test_feed_memory_diversity_requires_with_memory(self):
        user_id = "11111111-1111-1111-1111-111111111111"
        status, payload = self.request(
            "GET",
            f"/v1/feed?limit=2&user_id={user_id}&memory_diversity=off",
            auth=True,
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_QUERY")

    def test_feed_memory_diversity_validation(self):
        user_id = "11111111-1111-1111-1111-111111111111"
        status, payload = self.request(
            "GET",
            f"/v1/feed?limit=2&with_memory=1&user_id={user_id}&memory_diversity=maybe",
            auth=True,
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_QUERY")

    def test_feed_memory_diversity_on_off(self):
        user_id = "11111111-1111-1111-1111-111111111111"
        status_on, payload_on = self.request(
            "GET",
            f"/v1/feed?limit=2&with_memory=1&user_id={user_id}&memory_diversity=on",
            auth=True,
        )
        self.assertEqual(status_on, 200)
        self.assertIn("memory_inserted", payload_on)

        status_off, payload_off = self.request(
            "GET",
            f"/v1/feed?limit=2&with_memory=1&user_id={user_id}&memory_diversity=off",
            auth=True,
        )
        self.assertEqual(status_off, 200)
        self.assertIn("memory_inserted", payload_off)

    def test_feed_memory_position_validation(self):
        user_id = "11111111-1111-1111-1111-111111111111"
        status, payload = self.request(
            "GET",
            f"/v1/feed?limit=2&with_memory=1&user_id={user_id}&memory_position=middle",
            auth=True,
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_QUERY")

    def test_feed_memory_seed_validation(self):
        user_id = "11111111-1111-1111-1111-111111111111"
        status, payload = self.request(
            "GET",
            f"/v1/feed?limit=2&with_memory=1&user_id={user_id}&memory_position=random&memory_seed=x",
            auth=True,
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_QUERY")

    def test_feed_memory_random_never_first_requires_random(self):
        user_id = "11111111-1111-1111-1111-111111111111"
        status, payload = self.request(
            "GET",
            f"/v1/feed?limit=2&with_memory=1&user_id={user_id}&memory_position=top&memory_random_never_first=1",
            auth=True,
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_QUERY")

    def test_feed_memory_random_never_first_validation(self):
        user_id = "11111111-1111-1111-1111-111111111111"
        status, payload = self.request(
            "GET",
            f"/v1/feed?limit=2&with_memory=1&user_id={user_id}&memory_position=random&memory_random_never_first=maybe",
            auth=True,
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_QUERY")

        status, payload = self.request(
            "GET",
            f"/v1/feed?limit=2&with_memory=1&user_id={user_id}&memory_every=abc",
            auth=True,
        )
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_QUERY")

    def test_chunk_context_contract(self):
        feed_status, feed_payload = self.request("GET", "/v1/feed?limit=2&mode=default", auth=True)
        self.assertEqual(feed_status, 200)
        self.assertGreaterEqual(len(feed_payload.get("items", [])), 1)
        first = feed_payload["items"][0]
        chunk_id = first["chunk_id"]
        book_id = first["book_id"]

        status, payload = self.request(
            "GET",
            f"/v1/chunk_context?book_id={book_id}&chunk_id={chunk_id}",
            auth=True,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["book_id"], book_id)
        self.assertEqual(payload["chunk_id"], chunk_id)
        self.assertIn("prev_chunk_id", payload)
        self.assertIn("next_chunk_id", payload)
        self.assertIn("trace_id", payload)

    def test_chunk_context_missing_chunk_id(self):
        status, payload = self.request("GET", "/v1/chunk_context", auth=True)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_QUERY")

    def test_chunk_detail_contract(self):
        feed_status, feed_payload = self.request("GET", "/v1/feed?limit=2&mode=default", auth=True)
        self.assertEqual(feed_status, 200)
        first = feed_payload["items"][0]
        chunk_id = first["chunk_id"]
        book_id = first["book_id"]

        status, payload = self.request(
            "GET",
            f"/v1/chunk_detail?book_id={book_id}&chunk_id={chunk_id}",
            auth=True,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload.get("book_id"), book_id)
        self.assertEqual(payload.get("chunk_id"), chunk_id)
        self.assertIn("title", payload)
        self.assertIn("teaser_text", payload)
        self.assertIn("text_content", payload)
        self.assertIn("content_type", payload)
        self.assertIn("section_pdf_url", payload)
        self.assertIn("page_start", payload)
        self.assertIn("page_end", payload)
        self.assertIn("trace_id", payload)

    def test_chunk_detail_missing_chunk_id(self):
        status, payload = self.request("GET", "/v1/chunk_detail", auth=True)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_QUERY")

    def test_chunk_pdf_missing_params(self):
        status, payload = self.request("GET", "/v1/chunk_pdf", auth=True)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_QUERY")

    def test_toc_save_returns_materialization_stats(self):
        status, payload = self.request(
            "POST",
            "/v1/toc/save",
            body={
                "book_id": "00000000-0000-4000-8000-000000000001",
                "entries": [
                    {"title": "第1章", "level": 1, "start_page": 1, "end_page": 1},
                ],
            },
            auth=True,
        )
        self.assertEqual(status, 200)
        self.assertIn("materialized_chunks", payload)
        self.assertIn("generated_pdf_count", payload)
        self.assertIn("failed_entries", payload)
        self.assertIn("warnings", payload)

    def test_book_mosaic_contract(self):
        feed_status, feed_payload = self.request("GET", "/v1/feed?limit=2&mode=default", auth=True)
        self.assertEqual(feed_status, 200)
        first = feed_payload["items"][0]
        book_id = first["book_id"]
        user_id = "11111111-1111-1111-1111-111111111111"
        status, payload = self.request(
            "GET",
            f"/v1/book_mosaic?book_id={book_id}&user_id={user_id}",
            auth=True,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload.get("book_id"), book_id)
        self.assertEqual(payload.get("user_id"), user_id)
        self.assertEqual(payload.get("schema_version"), "book_homepage_mosaic.tiles.v1")
        self.assertEqual(payload.get("tiles_json_schema_version"), "book_homepage_mosaic.tiles.v1")
        self.assertEqual(payload.get("html_schema_version"), "book_homepage_mosaic.html.v1")
        self.assertEqual(payload.get("html_meta_tiles_schema_echoed"), True)
        self.assertIn("summary", payload)
        self.assertIn("tiles", payload)
        self.assertIn("trace_id", payload)
        self.assertGreaterEqual(len(payload.get("tiles", [])), 1)

    def test_book_mosaic_missing_book_id(self):
        status, payload = self.request("GET", "/v1/book_mosaic", auth=True)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_QUERY")

    def test_book_mosaic_invalid_user_id(self):
        status, payload = self.request("GET", "/v1/book_mosaic?book_id=b_sample_001&user_id=bad", auth=True)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_QUERY")

    def test_frontend_static_entry(self):
        url = f"{self.base_url}/app"
        req = Request(url, method="GET")
        with urlopen(req, timeout=5) as resp:
            html = resp.read().decode("utf-8")
            self.assertEqual(resp.status, 200)
            self.assertIn("BookFlow 信息流 MVP", html)

    def test_chunk_context_batch_contract(self):
        feed_status, feed_payload = self.request("GET", "/v1/feed?limit=3&mode=default", auth=True)
        self.assertEqual(feed_status, 200)
        chunks = [item["chunk_id"] for item in feed_payload.get("items", [])]
        self.assertGreaterEqual(len(chunks), 1)
        requested = chunks[:2]
        chunk_ids = ",".join(requested)
        status, payload = self.request(
            "GET",
            f"/v1/chunk_context_batch?chunk_ids={chunk_ids}",
            auth=True,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["requested_count"], len(requested))
        self.assertIn("items", payload)
        self.assertIn("found_count", payload)
        self.assertIn("not_found_chunk_ids", payload)
        self.assertIn("trace_id", payload)

    def test_chunk_context_batch_cache_stats_contract(self):
        feed_status, feed_payload = self.request("GET", "/v1/feed?limit=3&mode=default", auth=True)
        self.assertEqual(feed_status, 200)
        chunks = [item["chunk_id"] for item in feed_payload.get("items", [])]
        requested = chunks[:2]
        chunk_ids = ",".join(requested)
        status, payload = self.request(
            "GET",
            f"/v1/chunk_context_batch?chunk_ids={chunk_ids}&cache_stats=1",
            auth=True,
        )
        self.assertEqual(status, 200)
        self.assertIn("cache_stats", payload)
        self.assertIn("cache_hit_count", payload["cache_stats"])
        self.assertIn("cache_source_fetch_count", payload["cache_stats"])
        self.assertEqual(payload["cache_stats"].get("request_trace_id"), payload.get("trace_id"))
        self.assertIn("request_cache_hit_delta", payload["cache_stats"])
        self.assertIn("request_cache_source_fetch_delta", payload["cache_stats"])
        self.assertIn("request_cache_expired_delta", payload["cache_stats"])
        self.assertIn("cache_entries_delta", payload["cache_stats"])
        self.assertIn("cache_key_cardinality", payload["cache_stats"])
        self.assertIn("cache_key_samples", payload["cache_stats"])
        self.assertIn("sample_count", payload["cache_stats"])
        self.assertIn("sample_book_ids", payload["cache_stats"])
        self.assertIn("sample_book_ids_count", payload["cache_stats"])
        self.assertEqual(
            int(payload["cache_stats"].get("sample_book_ids_count", -1)),
            len(payload["cache_stats"].get("sample_book_ids", [])),
        )
        expected_seen_order: list[str] = []
        for sample in payload["cache_stats"].get("cache_key_samples", []):
            sample_book_id = sample.get("book_id")
            if sample_book_id is None:
                continue
            sample_book_id_text = str(sample_book_id)
            if sample_book_id_text not in expected_seen_order:
                expected_seen_order.append(sample_book_id_text)
        self.assertIn("sample_book_ids_sorted_by_seen", payload["cache_stats"])
        self.assertEqual(payload["cache_stats"].get("sample_book_ids_sorted_by_seen"), expected_seen_order)
        expected_chunk_ids = {
            str(chunk_id)
            for sample in payload["cache_stats"].get("cache_key_samples", [])
            for chunk_id in (sample.get("chunk_ids") or [])
        }
        expected_chunk_order: list[str] = []
        for sample in payload["cache_stats"].get("cache_key_samples", []):
            for chunk_id in (sample.get("chunk_ids") or []):
                chunk_id_text = str(chunk_id)
                if chunk_id_text not in expected_chunk_order:
                    expected_chunk_order.append(chunk_id_text)
        self.assertIn("sample_chunk_ids_count", payload["cache_stats"])
        self.assertEqual(int(payload["cache_stats"].get("sample_chunk_ids_count", -1)), len(expected_chunk_ids))
        self.assertIn("sample_chunk_ids_sorted_by_seen", payload["cache_stats"])
        self.assertEqual(payload["cache_stats"].get("sample_chunk_ids_sorted_by_seen"), expected_chunk_order)
        self.assertIn("sample_chunk_ids_first_seen_source", payload["cache_stats"])
        self.assertEqual(
            payload["cache_stats"].get("sample_chunk_ids_first_seen_source"),
            self._expected_chunk_first_seen_source(payload["cache_stats"]),
        )
        self.assertEqual(
            int(payload["cache_stats"].get("sample_chunk_ids_first_seen_source_count", -1)),
            len(payload["cache_stats"].get("sample_chunk_ids_first_seen_source", {})),
        )
        self.assertEqual(
            payload["cache_stats"].get("sample_chunk_ids_first_seen_source_sorted_chunk_ids"),
            self._expected_chunk_first_seen_source_sorted_chunk_ids(payload["cache_stats"]),
        )
        samples = payload["cache_stats"].get("cache_key_samples", [])
        if samples:
            self.assertIn("expire_in_sec", samples[0])
            self.assertIn("expire_estimate_ts", samples[0])
        self.assertIn("last_reset_trace_id", payload["cache_stats"])
        self.assertIn("reset_ts", payload["cache_stats"])
        self.assertIn("instance_id", payload["cache_stats"])
        self.assertIn("instance_started_ts", payload["cache_stats"])

    def test_chunk_context_batch_cache_reset_contract(self):
        feed_status, feed_payload = self.request("GET", "/v1/feed?limit=3&mode=default", auth=True)
        self.assertEqual(feed_status, 200)
        chunks = [item["chunk_id"] for item in feed_payload.get("items", [])]
        requested = chunks[:2]
        chunk_ids = ",".join(requested)

        status1, _ = self.request(
            "GET",
            f"/v1/chunk_context_batch?chunk_ids={chunk_ids}&cache_stats=1",
            auth=True,
        )
        self.assertEqual(status1, 200)
        status2, payload2 = self.request(
            "GET",
            f"/v1/chunk_context_batch?chunk_ids={chunk_ids}&cache_stats=1&cache_reset=1",
            auth=True,
        )
        self.assertEqual(status2, 200)
        stats = payload2.get("cache_stats", {})
        self.assertEqual(int(stats.get("cache_hit_count", 0)), 0)
        self.assertEqual(int(stats.get("cache_source_fetch_count", 0)), 1)
        self.assertEqual(stats.get("request_trace_id"), payload2.get("trace_id"))
        self.assertEqual(int(stats.get("request_cache_hit_delta", 0)), 0)
        self.assertEqual(int(stats.get("request_cache_source_fetch_delta", 0)), 1)
        self.assertEqual(int(stats.get("cache_entries_delta", 0)), 1)
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
        samples = stats.get("cache_key_samples", [])
        if samples:
            self.assertIn("expire_in_sec", samples[0])
            self.assertIn("expire_estimate_ts", samples[0])
        self.assertEqual(stats.get("last_reset_trace_id"), payload2.get("trace_id"))
        self.assertIsNotNone(stats.get("reset_ts"))
        self.assertIn("instance_id", stats)
        self.assertIn("instance_started_ts", stats)

    def test_chunk_context_batch_missing_chunk_ids(self):
        status, payload = self.request("GET", "/v1/chunk_context_batch", auth=True)
        self.assertEqual(status, 400)
        self.assertEqual(payload["error"]["code"], "INVALID_QUERY")

    def test_chunk_context_batch_post_contract(self):
        feed_status, feed_payload = self.request("GET", "/v1/feed?limit=3&mode=default", auth=True)
        self.assertEqual(feed_status, 200)
        chunks = [item["chunk_id"] for item in feed_payload.get("items", [])]
        requested = chunks[:2]
        self.assertGreaterEqual(len(requested), 1)
        status, payload = self.request(
            "POST",
            "/v1/chunk_context_batch",
            body={"chunk_ids": requested},
            auth=True,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["requested_count"], len(requested))
        self.assertIn("items", payload)
        self.assertIn("trace_id", payload)

    def test_chunk_context_batch_post_cache_stats_contract(self):
        feed_status, feed_payload = self.request("GET", "/v1/feed?limit=3&mode=default", auth=True)
        self.assertEqual(feed_status, 200)
        chunks = [item["chunk_id"] for item in feed_payload.get("items", [])]
        requested = chunks[:2]
        status, payload = self.request(
            "POST",
            "/v1/chunk_context_batch",
            body={"chunk_ids": requested, "cache_stats": True},
            auth=True,
        )
        self.assertEqual(status, 200)
        self.assertIn("cache_stats", payload)
        self.assertEqual(payload["cache_stats"].get("request_trace_id"), payload.get("trace_id"))
        self.assertIn("request_cache_hit_delta", payload["cache_stats"])
        self.assertIn("request_cache_source_fetch_delta", payload["cache_stats"])
        self.assertIn("cache_entries_delta", payload["cache_stats"])
        self.assertIn("cache_key_cardinality", payload["cache_stats"])
        self.assertIn("cache_key_samples", payload["cache_stats"])
        self.assertIn("sample_count", payload["cache_stats"])
        self.assertIn("sample_book_ids", payload["cache_stats"])
        self.assertIn("sample_book_ids_count", payload["cache_stats"])
        self.assertEqual(
            int(payload["cache_stats"].get("sample_book_ids_count", -1)),
            len(payload["cache_stats"].get("sample_book_ids", [])),
        )
        expected_seen_order: list[str] = []
        for sample in payload["cache_stats"].get("cache_key_samples", []):
            sample_book_id = sample.get("book_id")
            if sample_book_id is None:
                continue
            sample_book_id_text = str(sample_book_id)
            if sample_book_id_text not in expected_seen_order:
                expected_seen_order.append(sample_book_id_text)
        self.assertIn("sample_book_ids_sorted_by_seen", payload["cache_stats"])
        self.assertEqual(payload["cache_stats"].get("sample_book_ids_sorted_by_seen"), expected_seen_order)
        expected_chunk_ids = {
            str(chunk_id)
            for sample in payload["cache_stats"].get("cache_key_samples", [])
            for chunk_id in (sample.get("chunk_ids") or [])
        }
        expected_chunk_order: list[str] = []
        for sample in payload["cache_stats"].get("cache_key_samples", []):
            for chunk_id in (sample.get("chunk_ids") or []):
                chunk_id_text = str(chunk_id)
                if chunk_id_text not in expected_chunk_order:
                    expected_chunk_order.append(chunk_id_text)
        self.assertIn("sample_chunk_ids_count", payload["cache_stats"])
        self.assertEqual(int(payload["cache_stats"].get("sample_chunk_ids_count", -1)), len(expected_chunk_ids))
        self.assertIn("sample_chunk_ids_sorted_by_seen", payload["cache_stats"])
        self.assertEqual(payload["cache_stats"].get("sample_chunk_ids_sorted_by_seen"), expected_chunk_order)
        self.assertIn("sample_chunk_ids_first_seen_source", payload["cache_stats"])
        self.assertEqual(
            payload["cache_stats"].get("sample_chunk_ids_first_seen_source"),
            self._expected_chunk_first_seen_source(payload["cache_stats"]),
        )
        self.assertEqual(
            int(payload["cache_stats"].get("sample_chunk_ids_first_seen_source_count", -1)),
            len(payload["cache_stats"].get("sample_chunk_ids_first_seen_source", {})),
        )
        self.assertEqual(
            payload["cache_stats"].get("sample_chunk_ids_first_seen_source_sorted_chunk_ids"),
            self._expected_chunk_first_seen_source_sorted_chunk_ids(payload["cache_stats"]),
        )
        samples = payload["cache_stats"].get("cache_key_samples", [])
        if samples:
            self.assertIn("expire_in_sec", samples[0])
            self.assertIn("expire_estimate_ts", samples[0])
        self.assertIn("last_reset_trace_id", payload["cache_stats"])
        self.assertIn("reset_ts", payload["cache_stats"])
        self.assertIn("instance_id", payload["cache_stats"])
        self.assertIn("instance_started_ts", payload["cache_stats"])

    def test_interactions_accept_and_dedup(self):
        event_id = str(uuid.uuid4())
        event_ts = datetime.now(timezone.utc).isoformat()
        body = {
            "events": [
                {
                    "event_id": event_id,
                    "event_type": "section_complete",
                    "event_ts": event_ts,
                    "user_id": "u_contract",
                    "session_id": "s_contract",
                    "book_id": "b_contract",
                    "chunk_id": "ck_contract",
                    "position_in_chunk": 1.0,
                    "idempotency_key": "idem-contract-1",
                    "client": {"platform": "web", "app_version": "0.1.0", "device_id": "d_1"},
                    "payload": {"section_id": "sec_01", "read_time_sec": 120},
                }
            ]
        }
        status1, payload1 = self.request("POST", "/v1/interactions", body=body, auth=True)
        status2, payload2 = self.request("POST", "/v1/interactions", body=body, auth=True)
        self.assertEqual(status1, 200)
        self.assertEqual(payload1["accepted"], 1)
        self.assertEqual(status2, 200)
        self.assertEqual(payload2["deduplicated"], 1)

    def test_interactions_invalid_position_contract(self):
        body = {
            "events": [
                {
                    "event_id": str(uuid.uuid4()),
                    "event_type": "section_complete",
                    "event_ts": datetime.now(timezone.utc).isoformat(),
                    "user_id": "u_contract",
                    "session_id": "s_contract",
                    "book_id": "b_contract",
                    "chunk_id": "ck_contract",
                    "position_in_chunk": 2.0,
                    "idempotency_key": "idem-contract-2",
                    "client": {"platform": "web", "app_version": "0.1.0", "device_id": "d_2"},
                    "payload": {"section_id": "sec_01", "read_time_sec": 120},
                }
            ]
        }
        status, payload = self.request("POST", "/v1/interactions", body=body, auth=True)
        self.assertEqual(status, 200)
        self.assertEqual(payload["rejected"], 1)
        self.assertEqual(payload["results"][0]["error_code"], "INVALID_POSITION")


if __name__ == "__main__":
    unittest.main()
