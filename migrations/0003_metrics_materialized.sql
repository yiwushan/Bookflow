-- Metrics materialized views for dashboard acceleration.
-- Source tables: interactions, book_chunks

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_section_complete_per_user AS
SELECT
  event_date,
  user_id,
  COUNT(*) AS section_complete_cnt
FROM interactions
WHERE event_type = 'section_complete'
GROUP BY event_date, user_id
WITH NO DATA;

CREATE INDEX IF NOT EXISTS idx_mv_daily_section_complete_per_user
ON mv_daily_section_complete_per_user (event_date, user_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_funnel_rates AS
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
FROM daily
WITH NO DATA;

CREATE INDEX IF NOT EXISTS idx_mv_daily_funnel_rates_event_date
ON mv_daily_funnel_rates (event_date);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_deep_read_depth AS
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
GROUP BY event_date
WITH NO DATA;

CREATE INDEX IF NOT EXISTS idx_mv_daily_deep_read_depth_event_date
ON mv_daily_deep_read_depth (event_date);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_fragmentation_risk AS
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
GROUP BY event_date
WITH NO DATA;

CREATE INDEX IF NOT EXISTS idx_mv_daily_fragmentation_risk_event_date
ON mv_daily_fragmentation_risk (event_date);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_chunk_confusion_hotspots AS
SELECT
  book_id,
  chunk_id,
  COUNT(*) AS confusion_cnt,
  COUNT(DISTINCT user_id) AS affected_users,
  MAX(event_ts) AS last_confusion_ts
FROM interactions
WHERE event_type = 'confusion'
GROUP BY book_id, chunk_id
WITH NO DATA;

CREATE INDEX IF NOT EXISTS idx_mv_chunk_confusion_hotspots_book_chunk
ON mv_chunk_confusion_hotspots (book_id, chunk_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_render_reason_distribution AS
SELECT
  reason,
  COUNT(*) AS chunk_cnt
FROM book_chunks bc
CROSS JOIN LATERAL UNNEST(bc.render_reason) AS reason
GROUP BY reason
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_mv_render_reason_distribution_reason
ON mv_render_reason_distribution (reason);

