-- BookFlow metrics.sql (PostgreSQL)
-- Source tables: interactions, book_chunks
-- Focus: section_complete / backtrack / confusion

-- 1) 每日每用户完整小节完成数（北极星基础口径）
CREATE OR REPLACE VIEW vw_daily_section_complete_per_user AS
SELECT
  event_date,
  user_id,
  COUNT(*) AS section_complete_cnt
FROM interactions
WHERE event_type = 'section_complete'
GROUP BY event_date, user_id;

-- 2) 每日漏斗率：context / backtrack / confusion
CREATE OR REPLACE VIEW vw_daily_funnel_rates AS
WITH daily AS (
  SELECT
    event_date,
    COUNT(*) FILTER (WHERE event_type = 'impression') AS impressions,
    COUNT(*) FILTER (WHERE event_type = 'enter_context') AS context_entries,
    COUNT(*) FILTER (WHERE event_type = 'backtrack') AS backtracks,
    COUNT(*) FILTER (WHERE event_type = 'confusion') AS confusions
  FROM interactions
  GROUP BY event_date
)
SELECT
  event_date,
  impressions,
  context_entries,
  backtracks,
  confusions,
  CASE WHEN impressions = 0 THEN 0
       ELSE ROUND(context_entries::numeric / impressions, 4)
  END AS context_entry_rate,
  CASE WHEN context_entries = 0 THEN 0
       ELSE ROUND(backtracks::numeric / context_entries, 4)
  END AS backtrack_rate,
  CASE WHEN context_entries = 0 THEN 0
       ELSE ROUND(confusions::numeric / context_entries, 4)
  END AS confusion_rate
FROM daily;

-- 3) 每日连续深读深度（按 session + book 聚合后取 P50）
CREATE OR REPLACE VIEW vw_daily_deep_read_depth AS
WITH per_session_book AS (
  SELECT
    event_date,
    user_id,
    session_id,
    book_id,
    COUNT(DISTINCT chunk_id) FILTER (
      WHERE event_type IN ('enter_context', 'section_complete')
    ) AS deep_read_depth
  FROM interactions
  GROUP BY event_date, user_id, session_id, book_id
),
filtered AS (
  SELECT * FROM per_session_book WHERE deep_read_depth > 0
)
SELECT
  event_date,
  ROUND(AVG(deep_read_depth)::numeric, 2) AS deep_read_depth_avg,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY deep_read_depth) AS deep_read_depth_p50
FROM filtered
GROUP BY event_date;

-- 4) 每日碎片化风险率
-- 定义：enter_context 后 10 秒内发生 skip 且无 backtrack 的比例
CREATE OR REPLACE VIEW vw_daily_fragmentation_risk AS
WITH enters AS (
  SELECT
    id,
    event_date,
    user_id,
    session_id,
    book_id,
    chunk_id,
    event_ts
  FROM interactions
  WHERE event_type = 'enter_context'
),
flagged AS (
  SELECT
    e.event_date,
    e.id AS enter_id,
    EXISTS (
      SELECT 1
      FROM interactions s
      WHERE s.event_type = 'skip'
        AND s.user_id = e.user_id
        AND s.session_id = e.session_id
        AND s.event_ts >= e.event_ts
        AND s.event_ts <= e.event_ts + INTERVAL '10 seconds'
    ) AS has_quick_skip,
    EXISTS (
      SELECT 1
      FROM interactions b
      WHERE b.event_type = 'backtrack'
        AND b.user_id = e.user_id
        AND b.session_id = e.session_id
        AND b.event_ts >= e.event_ts
        AND b.event_ts <= e.event_ts + INTERVAL '10 seconds'
    ) AS has_backtrack
  FROM enters e
)
SELECT
  event_date,
  COUNT(*) AS enter_context_cnt,
  COUNT(*) FILTER (WHERE has_quick_skip AND NOT has_backtrack) AS fragmentation_risk_cnt,
  CASE WHEN COUNT(*) = 0 THEN 0
       ELSE ROUND(
         COUNT(*) FILTER (WHERE has_quick_skip AND NOT has_backtrack)::numeric / COUNT(*),
         4
       )
  END AS fragmentation_risk_rate
FROM flagged
GROUP BY event_date;

-- 5) 困惑热点切片（优先用于解释增强）
CREATE OR REPLACE VIEW vw_chunk_confusion_hotspots AS
SELECT
  book_id,
  chunk_id,
  COUNT(*) AS confusion_cnt,
  COUNT(DISTINCT user_id) AS affected_users,
  MAX(event_ts) AS last_confusion_ts
FROM interactions
WHERE event_type = 'confusion'
GROUP BY book_id, chunk_id
ORDER BY confusion_cnt DESC;

-- 6) 渲染原因分布（NOW-011 关联看板）
CREATE OR REPLACE VIEW vw_render_reason_distribution AS
SELECT
  reason,
  COUNT(*) AS chunk_cnt
FROM book_chunks bc
CROSS JOIN LATERAL UNNEST(bc.render_reason) AS reason
GROUP BY reason
ORDER BY chunk_cnt DESC, reason;

