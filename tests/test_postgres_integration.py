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

try:
    import psycopg
except Exception:  # pragma: no cover
    psycopg = None


DEFAULT_TEST_DSN = "postgresql://bookflow:bookflow@127.0.0.1:55432/bookflow"
SEED_USER_ID = "11111111-1111-1111-1111-111111111111"
SEED_BOOK_ID = "22222222-2222-2222-2222-222222222222"
SEED_CHUNK_ID = "33333333-3333-3333-3333-333333333331"


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class PostgresIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if psycopg is None:
            raise unittest.SkipTest("psycopg not installed")

        cls.repo_root = Path(__file__).resolve().parents[1]
        cls.dsn = os.getenv("BOOKFLOW_TEST_DATABASE_URL") or os.getenv("DATABASE_URL") or DEFAULT_TEST_DSN
        cls.token = "pg-integration-token"
        cls.port = get_free_port()
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        try:
            with psycopg.connect(cls.dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1 FROM users WHERE id = %s", (SEED_USER_ID,))
                    if cur.fetchone() is None:
                        raise unittest.SkipTest("seed user missing; run scripts/dev_postgres.sh first")
                    cur.execute("SELECT 1 FROM books WHERE id = %s", (SEED_BOOK_ID,))
                    if cur.fetchone() is None:
                        raise unittest.SkipTest("seed book missing; run scripts/dev_postgres.sh first")
                    cur.execute("SELECT 1 FROM book_chunks WHERE id = %s", (SEED_CHUNK_ID,))
                    if cur.fetchone() is None:
                        raise unittest.SkipTest("seed chunk missing; run scripts/dev_postgres.sh first")
                    cur.execute("SELECT to_regclass('public.interaction_rejections')")
                    if cur.fetchone()[0] is None:
                        raise unittest.SkipTest("interaction_rejections table missing; run migrations/0004_interaction_rejections.sql")
        except unittest.SkipTest:
            raise
        except Exception as exc:
            raise unittest.SkipTest(f"postgres not available for integration test: {exc}")

        env = os.environ.copy()
        env["BOOKFLOW_TOKEN"] = cls.token
        env["DATABASE_URL"] = cls.dsn

        cls.proc = subprocess.Popen(
            ["python3", "server/app.py", "--host", "127.0.0.1", "--port", str(cls.port)],
            cwd=str(cls.repo_root),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        deadline = time.time() + 12
        while time.time() < deadline:
            try:
                status, payload = cls.request("GET", "/health")
                if status == 200 and payload.get("backend") == "postgres":
                    return
            except Exception:
                pass
            time.sleep(0.1)
        raise RuntimeError("postgres integration server did not become ready in time")

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "proc", None) is not None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                cls.proc.kill()

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

    @classmethod
    def _count_by_idem_prefix(cls, prefix: str) -> int:
        with psycopg.connect(cls.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM interactions WHERE user_id = %s AND idempotency_key LIKE %s",
                    (SEED_USER_ID, f"{prefix}%"),
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0

    @classmethod
    def _cleanup_by_idem_prefix(cls, prefix: str) -> None:
        with psycopg.connect(cls.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM interactions WHERE user_id = %s AND idempotency_key LIKE %s",
                    (SEED_USER_ID, f"{prefix}%"),
                )

    @classmethod
    def _count_rejections_by_session(cls, session_id: str) -> int:
        with psycopg.connect(cls.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM interaction_rejections
                    WHERE raw_event->>'session_id' = %s
                    """,
                    (session_id,),
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0

    @classmethod
    def _get_reading_progress(cls, user_id: str, book_id: str):
        with psycopg.connect(cls.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT section_completed_count, chunk_completed_count, latest_chunk_id::text
                    FROM reading_progress
                    WHERE user_id = %s AND book_id = %s
                    """,
                    (user_id, book_id),
                )
                return cur.fetchone()

    def test_interactions_batch_write_and_dedup(self):
        idem_prefix = f"pg-int-{uuid.uuid4().hex[:12]}-"
        self._cleanup_by_idem_prefix(idem_prefix)

        event_ts = datetime.now(timezone.utc).isoformat()
        body = {
            "events": [
                {
                    "event_id": str(uuid.uuid4()),
                    "event_type": "impression",
                    "event_ts": event_ts,
                    "user_id": SEED_USER_ID,
                    "session_id": "s_pg_integration",
                    "book_id": SEED_BOOK_ID,
                    "chunk_id": SEED_CHUNK_ID,
                    "position_in_chunk": 0.2,
                    "idempotency_key": f"{idem_prefix}1",
                    "client": {"platform": "web", "app_version": "0.1.0", "device_id": "pg_int_1"},
                    "payload": {},
                },
                {
                    "event_id": str(uuid.uuid4()),
                    "event_type": "like",
                    "event_ts": event_ts,
                    "user_id": SEED_USER_ID,
                    "session_id": "s_pg_integration",
                    "book_id": SEED_BOOK_ID,
                    "chunk_id": SEED_CHUNK_ID,
                    "position_in_chunk": 0.8,
                    "idempotency_key": f"{idem_prefix}2",
                    "client": {"platform": "web", "app_version": "0.1.0", "device_id": "pg_int_2"},
                    "payload": {"note": "integration test"},
                },
            ]
        }

        status1, payload1 = self.request("POST", "/v1/interactions", body=body, auth=True)
        self.assertEqual(status1, 200)
        self.assertEqual(payload1["accepted"], 2)
        self.assertEqual(payload1["deduplicated"], 0)
        self.assertEqual(payload1["rejected"], 0)
        self.assertEqual(self._count_by_idem_prefix(idem_prefix), 2)

        status2, payload2 = self.request("POST", "/v1/interactions", body=body, auth=True)
        self.assertEqual(status2, 200)
        self.assertEqual(payload2["accepted"], 0)
        self.assertEqual(payload2["deduplicated"], 2)
        self.assertEqual(payload2["rejected"], 0)
        self.assertEqual(self._count_by_idem_prefix(idem_prefix), 2)

        self._cleanup_by_idem_prefix(idem_prefix)

    def test_feed_book_type_filter_on_postgres(self):
        status, payload = self.request("GET", "/v1/feed?limit=10&book_type=technical", auth=True)
        self.assertEqual(status, 200)
        self.assertIn("items", payload)
        self.assertGreaterEqual(len(payload["items"]), 1)
        for item in payload["items"]:
            self.assertEqual(item.get("book_type"), "technical")

    def test_feed_trace_with_user_preference(self):
        status, payload = self.request(
            "GET",
            f"/v1/feed?limit=5&mode=default&book_type=technical&user_id={SEED_USER_ID}&trace=1",
            auth=True,
        )
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(payload.get("items", [])), 1)
        trace = payload["items"][0].get("ranking_trace")
        self.assertIsInstance(trace, dict)
        self.assertEqual(trace.get("source"), "tag_profile")
        self.assertIn("score", trace)
        self.assertIn("rank", trace)

    def test_feed_trace_file_contains_memory_diversity_bucket(self):
        status, payload = self.request(
            "GET",
            f"/v1/feed?limit=5&mode=default&user_id={SEED_USER_ID}&trace=1&trace_file=1&with_memory=1",
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
            self.assertIsInstance(saved.get("query", {}).get("memory_diversity_rollout_enabled"), bool)
            self.assertIn(saved.get("query", {}).get("memory_diversity_rollout_mode"), {"off", "partial", "full"})
            self.assertIsInstance(saved.get("query", {}).get("memory_diversity_rollout_bucket_hit"), bool)
            threshold = saved.get("query", {}).get("memory_diversity_rollout_threshold_percent")
            self.assertTrue(threshold is None or isinstance(threshold, int))
            distance = saved.get("query", {}).get("memory_diversity_rollout_bucket_distance")
            self.assertTrue(distance is None or isinstance(distance, int))
            bucket = int(saved.get("query", {}).get("memory_diversity_bucket"))
            percentile = saved.get("query", {}).get("memory_diversity_rollout_bucket_percentile")
            self.assertIsInstance(percentile, float)
            self.assertGreaterEqual(percentile, 0.0)
            self.assertLess(percentile, 1.0)
            self.assertAlmostEqual(percentile, round(bucket / 100.0, 2))
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

    def test_feed_with_memory_placeholder(self):
        marker = f"memory-test-{uuid.uuid4().hex[:10]}"
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memory_posts (
                      user_id, source_book_id, source_chunk_id, source_date, memory_type, post_text, status
                    ) VALUES (%s, %s, %s, CURRENT_DATE - 30, 'month_ago', %s, 'inserted')
                    """,
                    (SEED_USER_ID, SEED_BOOK_ID, SEED_CHUNK_ID, marker),
                )
        try:
            status, payload = self.request(
                "GET",
                f"/v1/feed?limit=5&mode=default&user_id={SEED_USER_ID}&with_memory=1",
                auth=True,
            )
            self.assertEqual(status, 200)
            self.assertGreaterEqual(int(payload.get("memory_inserted", 0)), 1)
            self.assertGreaterEqual(len(payload.get("items", [])), 1)
            self.assertEqual(payload["items"][0].get("item_type"), "memory_post")
            self.assertEqual(payload["items"][0].get("teaser_text"), marker)
        finally:
            with psycopg.connect(self.dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM memory_posts WHERE post_text = %s", (marker,))

    def test_feed_with_memory_frequency_control(self):
        marker_a = f"memory-freq-a-{uuid.uuid4().hex[:8]}"
        marker_b = f"memory-freq-b-{uuid.uuid4().hex[:8]}"
        seed_chunk_id_2 = "33333333-3333-3333-3333-333333333332"
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memory_posts (
                      user_id, source_book_id, source_chunk_id, source_date, memory_type, post_text, status
                    ) VALUES
                    (%s, %s, %s, CURRENT_DATE - 10, 'month_ago', %s, 'inserted'),
                    (%s, %s, %s, CURRENT_DATE - 20, 'month_ago', %s, 'inserted')
                    """,
                    (
                        SEED_USER_ID,
                        SEED_BOOK_ID,
                        SEED_CHUNK_ID,
                        marker_a,
                        SEED_USER_ID,
                        SEED_BOOK_ID,
                        seed_chunk_id_2,
                        marker_b,
                    ),
                )
        try:
            status, payload = self.request(
                "GET",
                f"/v1/feed?limit=5&mode=default&user_id={SEED_USER_ID}&with_memory=1&memory_every=1",
                auth=True,
            )
            self.assertEqual(status, 200)
            self.assertEqual(int(payload.get("memory_inserted", 0)), 2)
            items = payload.get("items", [])
            self.assertGreaterEqual(len(items), 4)
            self.assertNotEqual(items[0].get("item_type"), "memory_post")
            self.assertEqual(items[1].get("item_type"), "memory_post")
            self.assertEqual(items[3].get("item_type"), "memory_post")
            self.assertEqual(items[1].get("teaser_text"), marker_a)
            self.assertEqual(items[3].get("teaser_text"), marker_b)
        finally:
            with psycopg.connect(self.dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM memory_posts WHERE post_text IN (%s, %s)",
                        (marker_a, marker_b),
                    )

    def test_feed_with_memory_source_diversity(self):
        marker_a = f"memory-div-a-{uuid.uuid4().hex[:8]}"
        marker_b = f"memory-div-b-{uuid.uuid4().hex[:8]}"
        marker_c = f"memory-div-c-{uuid.uuid4().hex[:8]}"
        seed_chunk_id_2 = "33333333-3333-3333-3333-333333333332"
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memory_posts (
                      user_id, source_book_id, source_chunk_id, source_date, memory_type, post_text, status
                    ) VALUES
                    (%s, %s, %s, CURRENT_DATE - 1, 'month_ago', %s, 'inserted'),
                    (%s, %s, %s, CURRENT_DATE - 2, 'month_ago', %s, 'inserted'),
                    (%s, %s, %s, CURRENT_DATE - 3, 'month_ago', %s, 'inserted')
                    """,
                    (
                        SEED_USER_ID,
                        SEED_BOOK_ID,
                        SEED_CHUNK_ID,
                        marker_a,
                        SEED_USER_ID,
                        SEED_BOOK_ID,
                        SEED_CHUNK_ID,
                        marker_b,
                        SEED_USER_ID,
                        SEED_BOOK_ID,
                        seed_chunk_id_2,
                        marker_c,
                    ),
                )
        try:
            status, payload = self.request(
                "GET",
                f"/v1/feed?limit=5&mode=default&user_id={SEED_USER_ID}&with_memory=1&memory_every=1",
                auth=True,
            )
            self.assertEqual(status, 200)
            self.assertEqual(int(payload.get("memory_inserted", 0)), 2)
            items = payload.get("items", [])
            memory_items = [i for i in items if i.get("item_type") == "memory_post"]
            self.assertEqual(len(memory_items), 2)
            self.assertNotEqual(memory_items[0].get("chunk_id"), memory_items[1].get("chunk_id"))
            teasers = {str(i.get("teaser_text")) for i in memory_items}
            self.assertIn(marker_a, teasers)
            self.assertIn(marker_c, teasers)
        finally:
            with psycopg.connect(self.dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM memory_posts WHERE post_text IN (%s, %s, %s)",
                        (marker_a, marker_b, marker_c),
                    )

    def test_feed_with_memory_source_diversity_off(self):
        marker_a = f"memory-div-off-a-{uuid.uuid4().hex[:8]}"
        marker_b = f"memory-div-off-b-{uuid.uuid4().hex[:8]}"
        marker_c = f"memory-div-off-c-{uuid.uuid4().hex[:8]}"
        seed_chunk_id_2 = "33333333-3333-3333-3333-333333333332"
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memory_posts (
                      user_id, source_book_id, source_chunk_id, source_date, memory_type, post_text, status
                    ) VALUES
                    (%s, %s, %s, CURRENT_DATE - 1, 'month_ago', %s, 'inserted'),
                    (%s, %s, %s, CURRENT_DATE - 2, 'month_ago', %s, 'inserted'),
                    (%s, %s, %s, CURRENT_DATE - 3, 'month_ago', %s, 'inserted')
                    """,
                    (
                        SEED_USER_ID,
                        SEED_BOOK_ID,
                        SEED_CHUNK_ID,
                        marker_a,
                        SEED_USER_ID,
                        SEED_BOOK_ID,
                        SEED_CHUNK_ID,
                        marker_b,
                        SEED_USER_ID,
                        SEED_BOOK_ID,
                        seed_chunk_id_2,
                        marker_c,
                    ),
                )
        try:
            status, payload = self.request(
                "GET",
                (
                    f"/v1/feed?limit=5&mode=default&user_id={SEED_USER_ID}"
                    "&with_memory=1&memory_every=1&memory_diversity=off"
                ),
                auth=True,
            )
            self.assertEqual(status, 200)
            self.assertEqual(int(payload.get("memory_inserted", 0)), 2)
            items = payload.get("items", [])
            memory_items = [i for i in items if i.get("item_type") == "memory_post"]
            self.assertEqual(len(memory_items), 2)
            self.assertEqual(memory_items[0].get("chunk_id"), SEED_CHUNK_ID)
            self.assertEqual(memory_items[1].get("chunk_id"), SEED_CHUNK_ID)
            teasers = {str(i.get("teaser_text")) for i in memory_items}
            self.assertIn(marker_a, teasers)
            self.assertIn(marker_b, teasers)
            self.assertNotIn(marker_c, teasers)
        finally:
            with psycopg.connect(self.dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM memory_posts WHERE post_text IN (%s, %s, %s)",
                        (marker_a, marker_b, marker_c),
                    )

    def test_feed_with_memory_random_position(self):
        marker_a = f"memory-rand-a-{uuid.uuid4().hex[:8]}"
        marker_b = f"memory-rand-b-{uuid.uuid4().hex[:8]}"
        seed_chunk_id_2 = "33333333-3333-3333-3333-333333333332"
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memory_posts (
                      user_id, source_book_id, source_chunk_id, source_date, memory_type, post_text, status
                    ) VALUES
                    (%s, %s, %s, CURRENT_DATE - 11, 'month_ago', %s, 'inserted'),
                    (%s, %s, %s, CURRENT_DATE - 12, 'month_ago', %s, 'inserted')
                    """,
                    (
                        SEED_USER_ID,
                        SEED_BOOK_ID,
                        SEED_CHUNK_ID,
                        marker_a,
                        SEED_USER_ID,
                        SEED_BOOK_ID,
                        seed_chunk_id_2,
                        marker_b,
                    ),
                )
        try:
            status, payload = self.request(
                "GET",
                (
                    f"/v1/feed?limit=5&mode=default&user_id={SEED_USER_ID}"
                    "&with_memory=1&memory_position=random&memory_every=1&memory_seed=7"
                ),
                auth=True,
            )
            self.assertEqual(status, 200)
            self.assertEqual(int(payload.get("memory_inserted", 0)), 2)
            items = payload.get("items", [])
            self.assertGreaterEqual(len(items), 4)
            self.assertNotEqual(items[0].get("item_type"), "memory_post")
            memory_items = [i for i in items if i.get("item_type") == "memory_post"]
            self.assertEqual(len(memory_items), 2)
            teasers = {i.get("teaser_text") for i in memory_items}
            self.assertIn(marker_a, teasers)
            self.assertIn(marker_b, teasers)
        finally:
            with psycopg.connect(self.dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM memory_posts WHERE post_text IN (%s, %s)",
                        (marker_a, marker_b),
                    )

    def test_feed_with_memory_random_position_allow_first(self):
        marker_a = f"memory-rand-first-a-{uuid.uuid4().hex[:8]}"
        marker_b = f"memory-rand-first-b-{uuid.uuid4().hex[:8]}"
        seed_chunk_id_2 = "33333333-3333-3333-3333-333333333332"
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO memory_posts (
                      user_id, source_book_id, source_chunk_id, source_date, memory_type, post_text, status
                    ) VALUES
                    (%s, %s, %s, CURRENT_DATE - 11, 'month_ago', %s, 'inserted'),
                    (%s, %s, %s, CURRENT_DATE - 12, 'month_ago', %s, 'inserted')
                    """,
                    (
                        SEED_USER_ID,
                        SEED_BOOK_ID,
                        SEED_CHUNK_ID,
                        marker_a,
                        SEED_USER_ID,
                        SEED_BOOK_ID,
                        seed_chunk_id_2,
                        marker_b,
                    ),
                )
        try:
            status, payload = self.request(
                "GET",
                (
                    f"/v1/feed?limit=5&mode=default&user_id={SEED_USER_ID}"
                    "&with_memory=1&memory_position=random&memory_every=1&memory_seed=0&memory_random_never_first=0"
                ),
                auth=True,
            )
            self.assertEqual(status, 200)
            self.assertEqual(int(payload.get("memory_inserted", 0)), 2)
            items = payload.get("items", [])
            self.assertGreaterEqual(len(items), 3)
            self.assertEqual(items[0].get("item_type"), "memory_post")
        finally:
            with psycopg.connect(self.dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM memory_posts WHERE post_text IN (%s, %s)",
                        (marker_a, marker_b),
                    )

    def test_feed_user_tag_preference_ranking(self):
        book_id = str(uuid.uuid4())
        preferred_chunk_id = str(uuid.uuid4())
        neutral_chunk_id = str(uuid.uuid4())
        tag_name = f"pref_tag_{uuid.uuid4().hex[:10]}"
        tag_id: int | None = None

        with psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO books (
                      id, title, author, language, book_type, source_format, processing_status, total_sections
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        book_id,
                        "偏好排序测试书",
                        "BookFlow",
                        "zh",
                        "fiction",
                        "txt",
                        "ready",
                        1,
                    ),
                )
                cur.execute(
                    """
                    INSERT INTO book_chunks (
                      id, book_id, section_id, chunk_index_in_section, global_index, title, text_content
                    ) VALUES
                    (%s, %s, 'sec_01', 1, 1, '偏好片段', '这个片段应被优先推荐'),
                    (%s, %s, 'sec_01', 2, 2, '普通片段', '这个片段没有标签偏好')
                    """,
                    (preferred_chunk_id, book_id, neutral_chunk_id, book_id),
                )
                cur.execute(
                    "INSERT INTO tags (name, category) VALUES (%s, %s) RETURNING id",
                    (tag_name, "test"),
                )
                tag_id = int(cur.fetchone()[0])
                cur.execute(
                    "INSERT INTO chunk_tags (chunk_id, tag_id, score) VALUES (%s, %s, %s)",
                    (preferred_chunk_id, tag_id, 1.0),
                )
                cur.execute(
                    "INSERT INTO user_tag_profile (user_id, tag_id, weight) VALUES (%s, %s, %s)",
                    (SEED_USER_ID, tag_id, 50.0),
                )

        try:
            status, payload = self.request(
                "GET",
                f"/v1/feed?limit=10&mode=default&book_type=fiction&user_id={SEED_USER_ID}",
                auth=True,
            )
            self.assertEqual(status, 200)
            self.assertIn("items", payload)
            ranked = [item for item in payload["items"] if item.get("book_id") == book_id]
            self.assertGreaterEqual(len(ranked), 2)
            ranked_ids = [item["chunk_id"] for item in ranked]
            self.assertIn(preferred_chunk_id, ranked_ids)
            self.assertIn(neutral_chunk_id, ranked_ids)
        finally:
            with psycopg.connect(self.dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute("DELETE FROM books WHERE id = %s", (book_id,))
                    if tag_id is not None:
                        cur.execute("DELETE FROM tags WHERE id = %s", (tag_id,))

    def test_chunk_context_neighbors_on_postgres(self):
        status, payload = self.request(
            "GET",
            f"/v1/chunk_context?book_id={SEED_BOOK_ID}&chunk_id={SEED_CHUNK_ID}",
            auth=True,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["book_id"], SEED_BOOK_ID)
        self.assertEqual(payload["chunk_id"], SEED_CHUNK_ID)
        self.assertIsNone(payload["prev_chunk_id"])
        self.assertEqual(payload["next_chunk_id"], "33333333-3333-3333-3333-333333333332")

    def test_chunk_detail_on_postgres(self):
        status, payload = self.request(
            "GET",
            f"/v1/chunk_detail?book_id={SEED_BOOK_ID}&chunk_id={SEED_CHUNK_ID}",
            auth=True,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload.get("book_id"), SEED_BOOK_ID)
        self.assertEqual(payload.get("chunk_id"), SEED_CHUNK_ID)
        self.assertIn("book_title", payload)
        self.assertIn("title", payload)
        self.assertIn("text_content", payload)
        self.assertIn("teaser_text", payload)
        self.assertIn("content_type", payload)
        self.assertIn("section_pdf_url", payload)
        self.assertIn("page_start", payload)
        self.assertIn("page_end", payload)
        self.assertIn("trace_id", payload)

    def test_book_mosaic_on_postgres(self):
        status, payload = self.request(
            "GET",
            f"/v1/book_mosaic?book_id={SEED_BOOK_ID}&user_id={SEED_USER_ID}",
            auth=True,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload.get("book_id"), SEED_BOOK_ID)
        self.assertEqual(payload.get("user_id"), SEED_USER_ID)
        self.assertEqual(payload.get("schema_version"), "book_homepage_mosaic.tiles.v1")
        self.assertEqual(payload.get("tiles_json_schema_version"), "book_homepage_mosaic.tiles.v1")
        self.assertEqual(payload.get("html_schema_version"), "book_homepage_mosaic.html.v1")
        self.assertEqual(payload.get("html_meta_tiles_schema_echoed"), True)
        self.assertIn("summary", payload)
        self.assertIn("tiles", payload)
        self.assertIn("trace_id", payload)
        self.assertGreaterEqual(len(payload.get("tiles", [])), 1)

    def test_frontend_static_entry_on_postgres(self):
        url = f"{self.base_url}/app"
        req = Request(url, method="GET")
        with urlopen(req, timeout=5) as resp:
            html = resp.read().decode("utf-8")
            self.assertEqual(resp.status, 200)
            self.assertIn("BookFlow 信息流 MVP", html)

    def test_chunk_context_batch_on_postgres(self):
        c1 = "33333333-3333-3333-3333-333333333331"
        c2 = "33333333-3333-3333-3333-333333333332"
        status, payload = self.request(
            "GET",
            f"/v1/chunk_context_batch?book_id={SEED_BOOK_ID}&chunk_ids={c1},{c2}",
            auth=True,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["requested_count"], 2)
        self.assertEqual(payload["found_count"], 2)
        self.assertEqual(payload["not_found_chunk_ids"], [])
        self.assertEqual(payload["items"][0]["chunk_id"], c1)
        self.assertEqual(payload["items"][1]["chunk_id"], c2)
        self.assertIsNone(payload["items"][0]["prev_chunk_id"])
        self.assertEqual(payload["items"][0]["next_chunk_id"], c2)

    def test_chunk_context_batch_post_on_postgres(self):
        c1 = "33333333-3333-3333-3333-333333333331"
        c2 = "33333333-3333-3333-3333-333333333332"
        status, payload = self.request(
            "POST",
            "/v1/chunk_context_batch",
            body={"book_id": SEED_BOOK_ID, "chunk_ids": [c1, c2]},
            auth=True,
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["requested_count"], 2)
        self.assertEqual(payload["found_count"], 2)

    def test_chunk_context_batch_cache_stats_on_postgres(self):
        c1 = "33333333-3333-3333-3333-333333333331"
        c2 = "33333333-3333-3333-3333-333333333332"
        status1, _ = self.request(
            "GET",
            f"/v1/chunk_context_batch?book_id={SEED_BOOK_ID}&chunk_ids={c1},{c2}",
            auth=True,
        )
        self.assertEqual(status1, 200)
        status2, payload2 = self.request(
            "GET",
            f"/v1/chunk_context_batch?book_id={SEED_BOOK_ID}&chunk_ids={c1},{c2}&cache_stats=1",
            auth=True,
        )
        self.assertEqual(status2, 200)
        stats = payload2.get("cache_stats", {})
        self.assertIn("cache_hit_count", stats)
        self.assertIn("cache_source_fetch_count", stats)
        self.assertGreaterEqual(int(stats.get("cache_hit_count", 0)), 1)
        self.assertEqual(stats.get("request_trace_id"), payload2.get("trace_id"))
        self.assertEqual(int(stats.get("request_cache_hit_delta", 0)), 1)
        self.assertEqual(int(stats.get("request_cache_source_fetch_delta", 0)), 0)
        self.assertEqual(int(stats.get("cache_entries_delta", 0)), 0)
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
        expected_first_seen_source: dict[str, dict[str, object | None]] = {}
        for sample_index, sample in enumerate(stats.get("cache_key_samples", []), start=1):
            sample_book_id = sample.get("book_id")
            sample_book_id_text = str(sample_book_id) if sample_book_id is not None else None
            for chunk_id in (sample.get("chunk_ids") or []):
                chunk_id_text = str(chunk_id)
                if chunk_id_text in expected_first_seen_source:
                    continue
                expected_first_seen_source[chunk_id_text] = {
                    "book_id": sample_book_id_text,
                    "sample_index": sample_index,
                }
        self.assertIn("sample_chunk_ids_first_seen_source", stats)
        self.assertEqual(stats.get("sample_chunk_ids_first_seen_source"), expected_first_seen_source)
        self.assertEqual(
            int(stats.get("sample_chunk_ids_first_seen_source_count", -1)),
            len(stats.get("sample_chunk_ids_first_seen_source", {})),
        )
        self.assertEqual(
            stats.get("sample_chunk_ids_first_seen_source_sorted_chunk_ids"),
            sorted(stats.get("sample_chunk_ids_first_seen_source", {}).keys()),
        )
        samples = stats.get("cache_key_samples", [])
        if samples:
            self.assertIn("expire_in_sec", samples[0])
            self.assertIn("expire_estimate_ts", samples[0])
        self.assertIn("last_reset_trace_id", stats)
        self.assertIn("reset_ts", stats)
        self.assertIn("instance_id", stats)
        self.assertIn("instance_started_ts", stats)

    def test_chunk_context_batch_cache_reset_on_postgres(self):
        c1 = "33333333-3333-3333-3333-333333333331"
        c2 = "33333333-3333-3333-3333-333333333332"
        status1, _ = self.request(
            "GET",
            f"/v1/chunk_context_batch?book_id={SEED_BOOK_ID}&chunk_ids={c1},{c2}",
            auth=True,
        )
        self.assertEqual(status1, 200)
        status2, payload2 = self.request(
            "GET",
            f"/v1/chunk_context_batch?book_id={SEED_BOOK_ID}&chunk_ids={c1},{c2}&cache_stats=1&cache_reset=1",
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
        expected_first_seen_source: dict[str, dict[str, object | None]] = {}
        for sample_index, sample in enumerate(stats.get("cache_key_samples", []), start=1):
            sample_book_id = sample.get("book_id")
            sample_book_id_text = str(sample_book_id) if sample_book_id is not None else None
            for chunk_id in (sample.get("chunk_ids") or []):
                chunk_id_text = str(chunk_id)
                if chunk_id_text in expected_first_seen_source:
                    continue
                expected_first_seen_source[chunk_id_text] = {
                    "book_id": sample_book_id_text,
                    "sample_index": sample_index,
                }
        self.assertIn("sample_chunk_ids_first_seen_source", stats)
        self.assertEqual(stats.get("sample_chunk_ids_first_seen_source"), expected_first_seen_source)
        self.assertEqual(
            int(stats.get("sample_chunk_ids_first_seen_source_count", -1)),
            len(stats.get("sample_chunk_ids_first_seen_source", {})),
        )
        self.assertEqual(
            stats.get("sample_chunk_ids_first_seen_source_sorted_chunk_ids"),
            sorted(stats.get("sample_chunk_ids_first_seen_source", {}).keys()),
        )
        samples = stats.get("cache_key_samples", [])
        if samples:
            self.assertIn("expire_in_sec", samples[0])
            self.assertIn("expire_estimate_ts", samples[0])
        self.assertEqual(stats.get("last_reset_trace_id"), payload2.get("trace_id"))
        self.assertIsNotNone(stats.get("reset_ts"))
        self.assertIn("instance_id", stats)
        self.assertIn("instance_started_ts", stats)

    def test_interactions_invalid_uuid_rejected(self):
        session_id = f"s_pg_bad_uuid_{uuid.uuid4().hex[:8]}"
        before = self._count_rejections_by_session(session_id)
        body = {
            "events": [
                {
                    "event_id": str(uuid.uuid4()),
                    "event_type": "impression",
                    "event_ts": datetime.now(timezone.utc).isoformat(),
                    "user_id": "not-a-uuid",
                    "session_id": session_id,
                    "book_id": SEED_BOOK_ID,
                    "chunk_id": SEED_CHUNK_ID,
                    "position_in_chunk": 0.4,
                    "idempotency_key": f"bad-uuid-{uuid.uuid4().hex[:8]}",
                    "client": {"platform": "web", "app_version": "0.1.0", "device_id": "pg_bad_uuid"},
                    "payload": {},
                }
            ]
        }
        status, payload = self.request("POST", "/v1/interactions", body=body, auth=True)
        self.assertEqual(status, 200)
        self.assertEqual(payload["accepted"], 0)
        self.assertEqual(payload["deduplicated"], 0)
        self.assertEqual(payload["rejected"], 1)
        self.assertEqual(payload["results"][0]["error_code"], "INVALID_PAYLOAD")
        after = self._count_rejections_by_session(session_id)
        self.assertEqual(after, before + 1)

    def test_backfill_reading_progress_script(self):
        idem_key = f"backfill-{uuid.uuid4().hex[:10]}"
        section_id = f"sec_backfill_{uuid.uuid4().hex[:10]}"
        body = {
            "events": [
                {
                    "event_id": str(uuid.uuid4()),
                    "event_type": "section_complete",
                    "event_ts": datetime.now(timezone.utc).isoformat(),
                    "user_id": SEED_USER_ID,
                    "session_id": f"s_backfill_{uuid.uuid4().hex[:6]}",
                    "book_id": SEED_BOOK_ID,
                    "chunk_id": SEED_CHUNK_ID,
                    "position_in_chunk": 1.0,
                    "idempotency_key": idem_key,
                    "client": {"platform": "web", "app_version": "0.1.0", "device_id": "pg_backfill"},
                    "payload": {"section_id": section_id, "read_time_sec": 30},
                }
            ]
        }
        status, payload = self.request("POST", "/v1/interactions", body=body, auth=True)
        self.assertEqual(status, 200)
        self.assertEqual(payload["accepted"], 1)

        env = os.environ.copy()
        env["DATABASE_URL"] = self.dsn
        proc = subprocess.run(
            ["python3", "scripts/backfill_reading_progress.py", "--user-id", SEED_USER_ID, "--book-id", SEED_BOOK_ID],
            cwd=str(self.repo_root),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        backfill_payload = json.loads(proc.stdout)
        self.assertEqual(backfill_payload.get("status"), "ok")
        self.assertGreaterEqual(int(backfill_payload.get("affected_rows", 0)), 1)

        with psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT section_completed_count, chunk_completed_count, completion_rate
                    FROM reading_progress
                    WHERE user_id = %s AND book_id = %s
                    """,
                    (SEED_USER_ID, SEED_BOOK_ID),
                )
                row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertGreaterEqual(int(row[0]), 1)
        self.assertGreaterEqual(int(row[1]), 1)

    def test_bootstrap_user_tags_script(self):
        new_user_id = str(uuid.uuid4())
        env = os.environ.copy()
        env["DATABASE_URL"] = self.dsn
        proc = subprocess.run(
            ["python3", "scripts/bootstrap_user_tags.py", "--user-id", new_user_id, "--preset", "technical"],
            cwd=str(self.repo_root),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload.get("status"), "ok")
        self.assertEqual(payload.get("user_id"), new_user_id)
        self.assertGreaterEqual(int(payload.get("tags_upserted", 0)), 3)

        with psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM user_tag_profile
                    WHERE user_id = %s
                    """,
                    (new_user_id,),
                )
                row = cur.fetchone()
                self.assertGreaterEqual(int(row[0]), 3)
                cur.execute("DELETE FROM users WHERE id = %s", (new_user_id,))

    def test_reading_progress_trigger_updates_on_section_complete(self):
        before = self._get_reading_progress(SEED_USER_ID, SEED_BOOK_ID)
        before_sections = int(before[0]) if before else 0
        before_chunks = int(before[1]) if before else 0

        body = {
            "events": [
                {
                    "event_id": str(uuid.uuid4()),
                    "event_type": "section_complete",
                    "event_ts": datetime.now(timezone.utc).isoformat(),
                    "user_id": SEED_USER_ID,
                    "session_id": f"s_trigger_{uuid.uuid4().hex[:8]}",
                    "book_id": SEED_BOOK_ID,
                    "chunk_id": SEED_CHUNK_ID,
                    "position_in_chunk": 1.0,
                    "idempotency_key": f"trigger-{uuid.uuid4().hex[:10]}",
                    "client": {"platform": "web", "app_version": "0.1.0", "device_id": "pg_trigger"},
                    "payload": {"section_id": f"sec_trigger_{uuid.uuid4().hex[:8]}", "read_time_sec": 20},
                }
            ]
        }
        status, payload = self.request("POST", "/v1/interactions", body=body, auth=True)
        self.assertEqual(status, 200)
        self.assertEqual(payload["accepted"], 1)

        after = self._get_reading_progress(SEED_USER_ID, SEED_BOOK_ID)
        self.assertIsNotNone(after)
        self.assertGreaterEqual(int(after[0]), before_sections)
        self.assertGreaterEqual(int(after[1]), before_chunks)
        self.assertEqual(after[2], SEED_CHUNK_ID)

    def test_auto_tag_chunks_script(self):
        env = os.environ.copy()
        env["DATABASE_URL"] = self.dsn
        proc = subprocess.run(
            ["python3", "scripts/auto_tag_chunks.py", "--book-id", SEED_BOOK_ID, "--limit", "50"],
            cwd=str(self.repo_root),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload.get("status"), "ok")
        self.assertGreaterEqual(int(payload.get("chunks_scanned", 0)), 1)
        self.assertGreaterEqual(int(payload.get("tags_upserted", 0)), 1)

        with psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM chunk_tags WHERE chunk_id = %s",
                    (SEED_CHUNK_ID,),
                )
                row = cur.fetchone()
                self.assertGreaterEqual(int(row[0]), 1)

    def test_report_reading_progress_health_script(self):
        env = os.environ.copy()
        env["DATABASE_URL"] = self.dsn
        with tempfile.TemporaryDirectory() as td:
            csv_path = Path(td) / "health.csv"
            proc = subprocess.run(
                [
                    "python3",
                    "scripts/report_reading_progress_health.py",
                    "--stale-days",
                    "7",
                    "--top",
                    "5",
                    "--csv-output",
                    str(csv_path),
                ],
                cwd=str(self.repo_root),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload.get("status"), "ok")
            self.assertIn("summary", payload)
            self.assertIn("total_rows", payload["summary"])
            self.assertIn("avg_completion_rate", payload["summary"])
            self.assertEqual(payload.get("csv_output"), str(csv_path))
            self.assertTrue(csv_path.exists())
            self.assertIn("row_type,metric,value", csv_path.read_text(encoding="utf-8"))

    def test_report_auto_tag_rule_hits_script(self):
        env = os.environ.copy()
        env["DATABASE_URL"] = self.dsn
        proc = subprocess.run(
            ["python3", "scripts/report_auto_tag_rule_hits.py", "--book-id", SEED_BOOK_ID, "--limit", "100"],
            cwd=str(self.repo_root),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload.get("status"), "ok")
        self.assertIn("summary", payload)
        self.assertIn("rule_hit_rate", payload["summary"])

    def test_compare_auto_tag_rule_versions_script(self):
        env = os.environ.copy()
        env["DATABASE_URL"] = self.dsn
        with tempfile.TemporaryDirectory() as td:
            csv_path = Path(td) / "compare.csv"
            markdown_path = Path(td) / "compare.md"
            jsonl_path = Path(td) / "compare.jsonl"
            proc = subprocess.run(
                [
                    "python3",
                    "scripts/compare_auto_tag_rule_versions.py",
                    "--book-id",
                    SEED_BOOK_ID,
                    "--limit",
                    "100",
                    "--base-version",
                    "v0",
                    "--target-version",
                    "v1",
                    "--top",
                    "10",
                    "--csv-output",
                    str(csv_path),
                    "--markdown-output",
                    str(markdown_path),
                    "--jsonl-output",
                    str(jsonl_path),
                ],
                cwd=str(self.repo_root),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload.get("status"), "ok")
            self.assertEqual(payload.get("base_version"), "v0")
            self.assertEqual(payload.get("target_version"), "v1")
            self.assertIn("summary", payload)
            self.assertIn("delta_rule_hit_rate", payload["summary"])
            self.assertEqual(payload.get("csv_output"), str(csv_path))
            self.assertEqual(payload.get("csv_schema_version"), "compare_auto_tag_rule_versions.csv.v1")
            self.assertEqual(payload.get("markdown_output"), str(markdown_path))
            self.assertEqual(payload.get("markdown_schema_version"), "compare_auto_tag_rule_versions.markdown.v1")
            self.assertEqual(payload.get("jsonl_output"), str(jsonl_path))
            self.assertEqual(payload.get("jsonl_schema_version"), "compare_auto_tag_rule_versions.jsonl.v1")
            self.assertEqual(
                payload.get("schema_version_consistency_note"),
                "csv=compare_auto_tag_rule_versions.csv.v1;jsonl=compare_auto_tag_rule_versions.jsonl.v1",
            )
            self.assertTrue(csv_path.exists())
            csv_text = csv_path.read_text(encoding="utf-8")
            self.assertIn(
                "row_type,rule_rank,rule,base_chunks,target_chunks,delta_chunks,metric,value,schema_version,jsonl_schema_version,markdown_schema_version",
                csv_text,
            )
            self.assertIn("rule_delta,1,", csv_text)
            self.assertIn("compare_auto_tag_rule_versions.csv.v1", csv_text)
            self.assertIn("compare_auto_tag_rule_versions.jsonl.v1", csv_text)
            self.assertIn("compare_auto_tag_rule_versions.markdown.v1", csv_text)
            self.assertTrue(markdown_path.exists())
            markdown_text = markdown_path.read_text(encoding="utf-8")
            self.assertIn("# Auto-Tag Rule Version Compare", markdown_text)
            self.assertIn("- top: `10`", markdown_text)
            self.assertIn("## Export Schemas", markdown_text)
            self.assertIn("compare_auto_tag_rule_versions.csv.v1", markdown_text)
            self.assertIn("compare_auto_tag_rule_versions.jsonl.v1", markdown_text)
            self.assertIn("- markdown_schema_version: `compare_auto_tag_rule_versions.markdown.v1`", markdown_text)
            self.assertIn(
                "schema_version_consistency_note: `csv=compare_auto_tag_rule_versions.csv.v1;jsonl=compare_auto_tag_rule_versions.jsonl.v1`",
                markdown_text,
            )
            self.assertTrue(jsonl_path.exists())
            jsonl_lines = [line for line in jsonl_path.read_text(encoding="utf-8").strip().splitlines() if line.strip()]
            self.assertGreaterEqual(len(jsonl_lines), 1)
            self.assertIn('"row_type": "summary"', jsonl_lines[0])
            self.assertIn('"schema_version": "compare_auto_tag_rule_versions.jsonl.v1"', jsonl_lines[0])
            summary_row = json.loads(jsonl_lines[0])
            self.assertEqual(summary_row.get("csv_schema_version"), "compare_auto_tag_rule_versions.csv.v1")
            self.assertEqual(summary_row.get("markdown_schema_version"), "compare_auto_tag_rule_versions.markdown.v1")
            rule_delta_rows = [json.loads(line) for line in jsonl_lines[1:] if '"row_type": "rule_delta"' in line]
            if rule_delta_rows:
                self.assertEqual(int(rule_delta_rows[0].get("rule_rank", 0)), 1)
                self.assertEqual(rule_delta_rows[0].get("schema_version"), "compare_auto_tag_rule_versions.jsonl.v1")
                self.assertEqual(rule_delta_rows[0].get("csv_schema_version"), "compare_auto_tag_rule_versions.csv.v1")
                self.assertEqual(
                    rule_delta_rows[0].get("markdown_schema_version"),
                    "compare_auto_tag_rule_versions.markdown.v1",
                )

    def test_accept_memory_feed_script(self):
        env = os.environ.copy()
        env["DATABASE_URL"] = self.dsn
        proc = subprocess.run(
            [
                "python3",
                "scripts/accept_memory_feed.py",
                "--database-url",
                self.dsn,
                "--user-id",
                SEED_USER_ID,
            ],
            cwd=str(self.repo_root),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload.get("status"), "ok")
        self.assertEqual(payload.get("first_item_type"), "memory_post")

    def test_accept_end_to_end_flow_script(self):
        env = os.environ.copy()
        env["DATABASE_URL"] = self.dsn
        title = f"E2E验收样例书-{uuid.uuid4().hex[:8]}"
        proc = subprocess.run(
            [
                "python3",
                "scripts/accept_end_to_end_flow.py",
                "--database-url",
                self.dsn,
                "--input",
                "examples/sample_import.txt",
                "--title",
                title,
                "--book-type",
                "technical",
                "--user-id",
                SEED_USER_ID,
            ],
            cwd=str(self.repo_root),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload.get("status"), "ok")
        self.assertEqual(payload.get("backend"), "postgres")
        self.assertEqual(payload.get("title"), title)
        self.assertGreater(int(payload.get("chunks_upserted", 0)), 0)
        self.assertGreater(int(payload.get("feed_hits", 0)), 0)
        self.assertTrue(payload.get("feed_trace_id"))
        self.assertTrue(payload.get("feed_trace_file_path"))
        self.assertEqual(payload.get("feed_trace_file_exists"), True)
        self.assertTrue(payload.get("selected_chunk_id"))
        self.assertGreaterEqual(int(payload.get("chunk_context_batch_requested_count", 0)), 1)
        self.assertGreaterEqual(int(payload.get("chunk_context_batch_found_count", 0)), 1)
        self.assertIn(payload.get("chunk_context_batch_cache_enabled"), {True, False})
        self.assertGreaterEqual(int(payload.get("chunk_context_batch_request_hit_delta", 0)), 0)
        self.assertTrue(payload.get("chunk_context_batch_trace_id"))
        self.assertGreaterEqual(int(payload.get("interactions_accepted", 0)), 3)
        self.assertEqual(int(payload.get("interactions_rejected", 0)), 0)
        self.assertTrue(payload.get("interactions_trace_id"))

    def test_accept_end_to_end_flow_script_markdown_jsonl_output(self):
        env = os.environ.copy()
        env["DATABASE_URL"] = self.dsn
        with tempfile.TemporaryDirectory() as td:
            markdown_output = Path(td) / "e2e_acceptance.md"
            jsonl_output = Path(td) / "e2e_acceptance.jsonl"
            title = f"E2E验收双报告-{uuid.uuid4().hex[:8]}"
            proc = subprocess.run(
                [
                    "python3",
                    "scripts/accept_end_to_end_flow.py",
                    "--database-url",
                    self.dsn,
                    "--input",
                    "examples/sample_import.txt",
                    "--title",
                    title,
                    "--book-type",
                    "technical",
                    "--user-id",
                    SEED_USER_ID,
                    "--markdown-output",
                    str(markdown_output),
                    "--jsonl-output",
                    str(jsonl_output),
                ],
                cwd=str(self.repo_root),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload.get("status"), "ok")
            self.assertEqual(payload.get("title"), title)
            self.assertTrue(payload.get("feed_trace_id"))
            self.assertTrue(payload.get("feed_trace_file_path"))
            self.assertEqual(payload.get("feed_trace_file_exists"), True)
            self.assertEqual(payload.get("markdown_output"), str(markdown_output))
            self.assertEqual(payload.get("jsonl_output"), str(jsonl_output))
            self.assertEqual(payload.get("markdown_schema_version"), "accept_end_to_end_flow.markdown.v1")
            self.assertEqual(payload.get("jsonl_schema_version"), "accept_end_to_end_flow.jsonl.v1")
            self.assertGreaterEqual(int(payload.get("chunk_context_batch_requested_count", 0)), 1)
            self.assertGreaterEqual(int(payload.get("chunk_context_batch_found_count", 0)), 1)
            self.assertIn(payload.get("chunk_context_batch_cache_enabled"), {True, False})
            self.assertGreaterEqual(int(payload.get("chunk_context_batch_request_hit_delta", 0)), 0)
            self.assertTrue(payload.get("chunk_context_batch_trace_id"))
            self.assertEqual(
                payload.get("schema_version_consistency_note"),
                "markdown=accept_end_to_end_flow.markdown.v1;jsonl=accept_end_to_end_flow.jsonl.v1",
            )
            self.assertTrue(markdown_output.exists())
            self.assertTrue(jsonl_output.exists())

            markdown_text = markdown_output.read_text(encoding="utf-8")
            self.assertIn("# BookFlow E2E Acceptance", markdown_text)
            self.assertIn("markdown_schema_version", markdown_text)
            self.assertIn("chunk_context_batch_found_count", markdown_text)
            self.assertIn("feed_trace_file_exists", markdown_text)

            lines = [line for line in jsonl_output.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertGreaterEqual(len(lines), 1)
            last_row = json.loads(lines[-1])
            self.assertEqual(last_row.get("schema_version"), "accept_end_to_end_flow.jsonl.v1")
            self.assertEqual(last_row.get("status"), "ok")
            self.assertEqual(last_row.get("title"), title)
            self.assertEqual(last_row.get("feed_trace_file_exists"), True)
            self.assertGreaterEqual(int(last_row.get("chunk_context_batch_found_count", 0)), 1)

    def test_replay_memory_feed_script(self):
        env = os.environ.copy()
        env["DATABASE_URL"] = self.dsn
        proc = subprocess.run(
            [
                "python3",
                "scripts/replay_memory_feed.py",
                "--database-url",
                self.dsn,
                "--user-id",
                SEED_USER_ID,
                "--limit",
                "6",
                "--scenarios",
                "top,1,3",
            ],
            cwd=str(self.repo_root),
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload.get("status"), "ok")
        self.assertEqual(payload.get("backend"), "postgres")
        self.assertEqual(payload.get("schema_version_consistency_note"), "no_export")
        scenarios = payload.get("scenarios", [])
        self.assertEqual(len(scenarios), 3)
        self.assertTrue(any(int(s.get("memory_inserted", 0)) > 0 for s in scenarios))

    def test_replay_memory_feed_script_jsonl_output(self):
        env = os.environ.copy()
        env["DATABASE_URL"] = self.dsn
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "replay.jsonl"
            proc = subprocess.run(
                [
                    "python3",
                    "scripts/replay_memory_feed.py",
                    "--database-url",
                    self.dsn,
                    "--user-id",
                    SEED_USER_ID,
                    "--limit",
                    "6",
                    "--scenarios",
                    "top,1,3",
                    "--jsonl-output",
                    str(output_path),
                ],
                cwd=str(self.repo_root),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload.get("status"), "ok")
            self.assertEqual(payload.get("jsonl_output"), str(output_path))
            self.assertEqual(payload.get("jsonl_schema_version"), "replay_memory_feed.jsonl.v1")
            self.assertEqual(
                payload.get("schema_version_consistency_note"),
                "csv=replay_memory_feed.csv.v1;jsonl=replay_memory_feed.jsonl.v1",
            )
            self.assertTrue(output_path.exists())
            lines = output_path.read_text(encoding="utf-8").strip().splitlines()
            self.assertEqual(len(lines), 3)
            first_row = json.loads(lines[0])
            self.assertEqual(first_row.get("schema_version"), "replay_memory_feed.jsonl.v1")
            self.assertEqual(first_row.get("markdown_schema_version"), "replay_memory_feed.markdown.v1")

    def test_replay_memory_feed_script_markdown_output(self):
        env = os.environ.copy()
        env["DATABASE_URL"] = self.dsn
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "replay.md"
            proc = subprocess.run(
                [
                    "python3",
                    "scripts/replay_memory_feed.py",
                    "--database-url",
                    self.dsn,
                    "--user-id",
                    SEED_USER_ID,
                    "--limit",
                    "6",
                    "--scenarios",
                    "top,1,3",
                    "--markdown-output",
                    str(output_path),
                ],
                cwd=str(self.repo_root),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload.get("status"), "ok")
            self.assertEqual(payload.get("markdown_output"), str(output_path))
            self.assertEqual(payload.get("markdown_schema_version"), "replay_memory_feed.markdown.v1")
            self.assertTrue(output_path.exists())
            text = output_path.read_text(encoding="utf-8")
            self.assertIn("# Memory Feed Replay Report", text)
            self.assertIn("replay_memory_feed.csv.v1", text)
            self.assertIn("replay_memory_feed.jsonl.v1", text)
            self.assertIn("replay_memory_feed.markdown.v1", text)
            self.assertIn("- schema_version_consistency_note: `no_export`", text)
            self.assertIn("## Scenario `top`", text)
            self.assertIn("## Scenario `1`", text)
            self.assertIn("## Scenario `3`", text)
            self.assertIn("memory_type_distribution", text)

    def test_replay_memory_feed_script_csv_output(self):
        env = os.environ.copy()
        env["DATABASE_URL"] = self.dsn
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "replay.csv"
            proc = subprocess.run(
                [
                    "python3",
                    "scripts/replay_memory_feed.py",
                    "--database-url",
                    self.dsn,
                    "--user-id",
                    SEED_USER_ID,
                    "--limit",
                    "6",
                    "--scenarios",
                    "top,1,3",
                    "--csv-output",
                    str(output_path),
                ],
                cwd=str(self.repo_root),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload.get("status"), "ok")
            self.assertEqual(payload.get("csv_output"), str(output_path))
            self.assertEqual(payload.get("csv_schema_version"), "replay_memory_feed.csv.v1")
            self.assertEqual(
                payload.get("schema_version_consistency_note"),
                "csv=replay_memory_feed.csv.v1;jsonl=replay_memory_feed.jsonl.v1",
            )
            self.assertTrue(output_path.exists())
            text = output_path.read_text(encoding="utf-8")
            self.assertIn(
                "scenario,memory_every,memory_inserted,memory_positions,first_item_type,items_count,trace_id,user_id,limit,memory_type_distribution,jsonl_schema_version,markdown_schema_version,markdown_schema_version_source,schema_version",
                text,
            )
            self.assertIn("replay_memory_feed.jsonl.v1", text)
            self.assertIn("replay_memory_feed.markdown.v1", text)
            self.assertIn("constant", text)
            self.assertIn("replay_memory_feed.csv.v1", text)

    def test_export_memory_position_ab_samples_script(self):
        env = os.environ.copy()
        env["DATABASE_URL"] = self.dsn
        with tempfile.TemporaryDirectory() as td:
            jsonl_path = Path(td) / "memory_position_ab.jsonl"
            csv_path = Path(td) / "memory_position_ab.csv"
            markdown_path = Path(td) / "memory_position_ab.md"
            proc = subprocess.run(
                [
                    "python3",
                    "scripts/export_memory_position_ab_samples.py",
                    "--database-url",
                    self.dsn,
                    "--user-id",
                    SEED_USER_ID,
                    "--limit",
                    "6",
                    "--interval-every",
                    "2",
                    "--random-seed",
                    "7",
                    "--jsonl-output",
                    str(jsonl_path),
                    "--csv-output",
                    str(csv_path),
                    "--markdown-output",
                    str(markdown_path),
                ],
                cwd=str(self.repo_root),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload.get("status"), "ok")
            self.assertEqual(payload.get("backend"), "postgres")
            self.assertEqual(len(payload.get("arms", [])), 3)
            self.assertGreater(int(payload.get("sample_rows_count", 0)), 0)
            self.assertEqual(payload.get("jsonl_output"), str(jsonl_path))
            self.assertEqual(payload.get("csv_output"), str(csv_path))
            self.assertEqual(payload.get("markdown_output"), str(markdown_path))
            self.assertTrue(jsonl_path.exists())
            self.assertTrue(csv_path.exists())
            self.assertTrue(markdown_path.exists())
            self.assertGreater(len(jsonl_path.read_text(encoding="utf-8").strip().splitlines()), 0)
            self.assertIn("arm,memory_position,memory_every,trace_id", csv_path.read_text(encoding="utf-8"))
            self.assertIn("# Memory Position A/B Samples", markdown_path.read_text(encoding="utf-8"))

    def test_export_memory_position_ab_samples_script_with_scenario_config(self):
        env = os.environ.copy()
        env["DATABASE_URL"] = self.dsn
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "scenarios.json"
            cfg_path.write_text(
                """
                {
                  "arms": [
                    {"arm":"CFG_top","memory_position":"top"},
                    {"arm":"CFG_interval_2","memory_position":"interval","memory_every":2},
                    {
                      "arm":"CFG_random_2",
                      "memory_position":"random",
                      "memory_every":2,
                      "memory_seed":11,
                      "memory_random_never_first":0
                    }
                  ]
                }
                """,
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    "python3",
                    "scripts/export_memory_position_ab_samples.py",
                    "--database-url",
                    self.dsn,
                    "--user-id",
                    SEED_USER_ID,
                    "--limit",
                    "6",
                    "--scenario-config",
                    str(cfg_path),
                ],
                cwd=str(self.repo_root),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload.get("status"), "ok")
            self.assertEqual(payload.get("scenario_config"), str(cfg_path))
            arms = payload.get("arms", [])
            self.assertEqual(len(arms), 3)
            self.assertEqual(arms[0].get("arm"), "CFG_top")
            self.assertEqual(arms[2].get("memory_seed"), 11)
            self.assertEqual(arms[2].get("memory_random_never_first"), False)

    def test_export_chunk_granularity_ab_samples_script(self):
        env = os.environ.copy()
        env["DATABASE_URL"] = self.dsn
        with tempfile.TemporaryDirectory() as td:
            jsonl_path = Path(td) / "chunk_granularity_ab.jsonl"
            csv_path = Path(td) / "chunk_granularity_ab.csv"
            markdown_path = Path(td) / "chunk_granularity_ab.md"
            proc = subprocess.run(
                [
                    "python3",
                    "scripts/export_chunk_granularity_ab_samples.py",
                    "--database-url",
                    self.dsn,
                    "--book-id",
                    SEED_BOOK_ID,
                    "--limit",
                    "20",
                    "--min-split-chars",
                    "60",
                    "--jsonl-output",
                    str(jsonl_path),
                    "--csv-output",
                    str(csv_path),
                    "--markdown-output",
                    str(markdown_path),
                ],
                cwd=str(self.repo_root),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload.get("status"), "ok")
            self.assertEqual(payload.get("book_id_filter"), SEED_BOOK_ID)
            self.assertGreater(int(payload.get("rows_count", 0)), 0)
            self.assertEqual(payload.get("jsonl_output"), str(jsonl_path))
            self.assertEqual(payload.get("jsonl_schema_version"), "chunk_granularity_ab_samples.jsonl.v1")
            self.assertEqual(payload.get("csv_output"), str(csv_path))
            self.assertEqual(payload.get("csv_schema_version"), "chunk_granularity_ab_samples.csv.v1")
            self.assertEqual(
                payload.get("schema_version_consistency_note"),
                "csv=chunk_granularity_ab_samples.csv.v1;jsonl=chunk_granularity_ab_samples.jsonl.v1",
            )
            self.assertEqual(payload.get("markdown_output"), str(markdown_path))
            self.assertEqual(payload.get("markdown_schema_version"), "chunk_granularity_ab_samples.markdown.v1")
            self.assertTrue(jsonl_path.exists())
            self.assertTrue(csv_path.exists())
            self.assertTrue(markdown_path.exists())
            csv_text = csv_path.read_text(encoding="utf-8")
            self.assertIn("arm,row_rank,book_id,book_title,chunk_id", csv_text)
            self.assertIn("markdown_schema_version", csv_text)
            self.assertIn("chunk_granularity_ab_samples.markdown.v1", csv_text)
            self.assertIn("chunk_granularity_ab_samples.csv.v1", csv_text)
            markdown_text = markdown_path.read_text(encoding="utf-8")
            self.assertIn("# Chunk Granularity A/B Samples", markdown_text)
            self.assertIn("chunk_granularity_ab_samples.jsonl.v1", markdown_text)
            self.assertIn("chunk_granularity_ab_samples.csv.v1", markdown_text)
            self.assertIn("- markdown_schema_version: `chunk_granularity_ab_samples.markdown.v1`", markdown_text)
            self.assertIn(
                "schema_version_consistency_note: `csv=chunk_granularity_ab_samples.csv.v1;jsonl=chunk_granularity_ab_samples.jsonl.v1`",
                markdown_text,
            )

    def test_export_chunk_granularity_ab_samples_script_with_section_prefix(self):
        env = os.environ.copy()
        env["DATABASE_URL"] = self.dsn
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT section_id FROM book_chunks WHERE id = %s",
                    (SEED_CHUNK_ID,),
                )
                row = cur.fetchone()
        section_id = str(row[0]) if row and row[0] is not None else ""
        if not section_id:
            self.skipTest("seed chunk section_id missing")
        section_prefix = section_id[: min(6, len(section_id))]

        with tempfile.TemporaryDirectory() as td:
            jsonl_path = Path(td) / "chunk_granularity_ab_filtered.jsonl"
            proc = subprocess.run(
                [
                    "python3",
                    "scripts/export_chunk_granularity_ab_samples.py",
                    "--database-url",
                    self.dsn,
                    "--book-id",
                    SEED_BOOK_ID,
                    "--section-prefix",
                    section_prefix,
                    "--limit",
                    "50",
                    "--jsonl-output",
                    str(jsonl_path),
                ],
                cwd=str(self.repo_root),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload.get("status"), "ok")
            self.assertEqual(payload.get("section_prefix"), section_prefix)
            self.assertEqual(
                payload.get("schema_version_consistency_note"),
                "csv=chunk_granularity_ab_samples.csv.v1;jsonl=chunk_granularity_ab_samples.jsonl.v1",
            )
            self.assertTrue(jsonl_path.exists())
            lines = [line for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertGreater(len(lines), 0)
            for line in lines:
                item = json.loads(line)
                self.assertEqual(item.get("schema_version"), "chunk_granularity_ab_samples.jsonl.v1")
                self.assertEqual(item.get("csv_schema_version"), "chunk_granularity_ab_samples.csv.v1")
                self.assertTrue(str(item.get("section_id") or "").startswith(section_prefix))

    def test_export_chunk_granularity_ab_samples_script_with_chunk_title_keyword(self):
        env = os.environ.copy()
        env["DATABASE_URL"] = self.dsn
        with psycopg.connect(self.dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT title FROM book_chunks WHERE id = %s",
                    (SEED_CHUNK_ID,),
                )
                row = cur.fetchone()
        chunk_title = str(row[0]) if row and row[0] is not None else ""
        chunk_title = chunk_title.strip()
        if not chunk_title:
            self.skipTest("seed chunk title missing")
        chunk_title_keyword = chunk_title[: min(4, len(chunk_title))].strip()
        if not chunk_title_keyword.strip():
            self.skipTest("seed chunk title keyword missing")

        with tempfile.TemporaryDirectory() as td:
            jsonl_path = Path(td) / "chunk_granularity_ab_title_filtered.jsonl"
            csv_path = Path(td) / "chunk_granularity_ab_title_filtered.csv"
            markdown_path = Path(td) / "chunk_granularity_ab_title_filtered.md"
            proc = subprocess.run(
                [
                    "python3",
                    "scripts/export_chunk_granularity_ab_samples.py",
                    "--database-url",
                    self.dsn,
                    "--book-id",
                    SEED_BOOK_ID,
                    "--chunk-title-keyword",
                    chunk_title_keyword,
                    "--limit",
                    "50",
                    "--jsonl-output",
                    str(jsonl_path),
                    "--csv-output",
                    str(csv_path),
                    "--markdown-output",
                    str(markdown_path),
                ],
                cwd=str(self.repo_root),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload.get("status"), "ok")
            self.assertEqual(payload.get("chunk_title_keyword"), chunk_title_keyword)
            self.assertEqual(payload.get("jsonl_schema_version"), "chunk_granularity_ab_samples.jsonl.v1")
            self.assertEqual(payload.get("csv_schema_version"), "chunk_granularity_ab_samples.csv.v1")
            self.assertEqual(
                payload.get("schema_version_consistency_note"),
                "csv=chunk_granularity_ab_samples.csv.v1;jsonl=chunk_granularity_ab_samples.jsonl.v1",
            )
            self.assertEqual(payload.get("markdown_schema_version"), "chunk_granularity_ab_samples.markdown.v1")
            keyword_stats = payload.get("keyword_filter_stats")
            self.assertIsInstance(keyword_stats, dict)
            self.assertGreaterEqual(int(keyword_stats.get("total_candidates", 0)), 1)
            self.assertGreaterEqual(int(keyword_stats.get("matched_candidates", 0)), 1)
            self.assertIn("hit_rate", keyword_stats)
            self.assertTrue(jsonl_path.exists())
            self.assertTrue(csv_path.exists())
            self.assertTrue(markdown_path.exists())
            lines = [line for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            self.assertGreater(len(lines), 0)
            for line in lines:
                item = json.loads(line)
                self.assertEqual(item.get("schema_version"), "chunk_granularity_ab_samples.jsonl.v1")
                self.assertEqual(item.get("csv_schema_version"), "chunk_granularity_ab_samples.csv.v1")
                title = str(item.get("chunk_title") or "")
                self.assertIn(chunk_title_keyword.lower(), title.lower())
            markdown_text = markdown_path.read_text(encoding="utf-8")
            self.assertIn("keyword_filter_hit_rate", markdown_text)
            self.assertIn("chunk_granularity_ab_samples.jsonl.v1", markdown_text)
            self.assertIn("chunk_granularity_ab_samples.csv.v1", markdown_text)
            self.assertIn("- markdown_schema_version: `chunk_granularity_ab_samples.markdown.v1`", markdown_text)
            self.assertIn(
                "schema_version_consistency_note: `csv=chunk_granularity_ab_samples.csv.v1;jsonl=chunk_granularity_ab_samples.jsonl.v1`",
                markdown_text,
            )
            self.assertIn("## CSV Notes", markdown_text)
            self.assertIn("keyword_filter_summary", markdown_text)
            csv_text = csv_path.read_text(encoding="utf-8")
            self.assertIn("keyword_filter_summary", csv_text)
            self.assertIn("keyword_filter_hit_rate=", csv_text)
            self.assertIn("chunk_granularity_ab_samples.markdown.v1", csv_text)

    def test_render_book_homepage_mosaic_script(self):
        env = os.environ.copy()
        env["DATABASE_URL"] = self.dsn
        with tempfile.TemporaryDirectory() as td:
            output_path = Path(td) / "book_homepage_mosaic.html"
            tiles_json_path = Path(td) / "book_homepage_mosaic.tiles.json"
            proc = subprocess.run(
                [
                    "python3",
                    "scripts/render_book_homepage_mosaic.py",
                    "--database-url",
                    self.dsn,
                    "--book-id",
                    SEED_BOOK_ID,
                    "--user-id",
                    SEED_USER_ID,
                    "--output",
                    str(output_path),
                    "--tiles-json-output",
                    str(tiles_json_path),
                ],
                cwd=str(self.repo_root),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload.get("status"), "ok")
            self.assertEqual(payload.get("book_id"), SEED_BOOK_ID)
            self.assertEqual(payload.get("output"), str(output_path))
            self.assertEqual(payload.get("tiles_json_output"), str(tiles_json_path))
            self.assertIn("html_title", payload)
            self.assertEqual(payload.get("html_schema_version"), "book_homepage_mosaic.html.v1")
            self.assertEqual(payload.get("html_meta_tiles_schema_echoed"), True)
            self.assertIn("exported_at", payload)
            self.assertEqual(int(payload.get("min_read_events", 0)), 1)
            self.assertEqual(payload.get("tiles_json_schema_version"), "book_homepage_mosaic.tiles.v1")
            self.assertIn("summary", payload)
            self.assertTrue(output_path.exists())
            self.assertTrue(tiles_json_path.exists())
            html = output_path.read_text(encoding="utf-8")
            self.assertIn('class="mosaic-grid"', html)
            self.assertIn('class="tile', html)
            summary = payload.get("summary", {})
            self.assertIn(f"min_read_events: {int(payload.get('min_read_events', 0))}", html)
            self.assertIn(
                f'name="bookflow:html_schema_version" content="{payload.get("html_schema_version")}"',
                html,
            )
            self.assertIn(
                f'name="bookflow:tiles_json_schema_version" content="{payload.get("tiles_json_schema_version")}"',
                html,
            )
            self.assertIn(f"tiles_json_schema_version: {payload.get('tiles_json_schema_version')}", html)
            self.assertIn(f"已读 tile ({int(summary.get('read_chunks', 0))})", html)
            self.assertIn(f"未读 tile ({int(summary.get('unread_chunks', 0))})", html)
            self.assertIn("exported_at:", html)
            tiles_payload = json.loads(tiles_json_path.read_text(encoding="utf-8"))
            self.assertEqual(tiles_payload.get("schema_version"), "book_homepage_mosaic.tiles.v1")
            self.assertEqual(tiles_payload.get("tiles_json_schema_version"), payload.get("tiles_json_schema_version"))
            self.assertEqual(tiles_payload.get("html_schema_version"), payload.get("html_schema_version"))
            self.assertEqual(tiles_payload.get("book_id"), SEED_BOOK_ID)
            self.assertEqual(tiles_payload.get("html_title"), payload.get("html_title"))
            self.assertEqual(tiles_payload.get("exported_at"), payload.get("exported_at"))
            self.assertEqual(int(tiles_payload.get("min_read_events", 0)), 1)
            self.assertGreaterEqual(len(tiles_payload.get("tiles", [])), 1)


if __name__ == "__main__":
    unittest.main()
