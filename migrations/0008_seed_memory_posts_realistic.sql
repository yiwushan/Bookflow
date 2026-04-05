-- Migration: 0008_seed_memory_posts_realistic
-- Realistic memory-post seed samples for replay/demo scenarios.

WITH seed_rows AS (
  SELECT *
  FROM (
    VALUES
      (
        'realistic_01',
        '33333333-3333-3333-3333-333333333331'::uuid,
        CURRENT_DATE - 31,
        'month_ago',
        '一个月前你在这里停留了 4 分钟：梯度下降的直觉终于连起来了。',
        'inserted',
        jsonb_build_object(
          'seed', '0008',
          'sample_id', 'realistic_01',
          'trigger', 'month_review',
          'source_event', 'section_complete',
          'emotion', 'aha'
        )
      ),
      (
        'realistic_02',
        '33333333-3333-3333-3333-333333333332'::uuid,
        CURRENT_DATE - 36,
        'month_ago',
        '一个月前你收藏了这个最小实现：今天要不要把它手敲一遍？',
        'inserted',
        jsonb_build_object(
          'seed', '0008',
          'sample_id', 'realistic_02',
          'trigger', 'month_review',
          'source_event', 'like',
          'emotion', 'practice'
        )
      ),
      (
        'realistic_03',
        '33333333-3333-3333-3333-333333333331'::uuid,
        CURRENT_DATE - 365,
        'year_ago',
        '一年前你在这里写下疑问：学习率到底应该怎么选？',
        'inserted',
        jsonb_build_object(
          'seed', '0008',
          'sample_id', 'realistic_03',
          'trigger', 'year_review',
          'source_event', 'comment',
          'emotion', 'question'
        )
      ),
      (
        'realistic_04',
        '33333333-3333-3333-3333-333333333332'::uuid,
        CURRENT_DATE - 372,
        'year_ago',
        '一年前你划过这段代码，今天你已经能看懂它为什么会收敛了。',
        'inserted',
        jsonb_build_object(
          'seed', '0008',
          'sample_id', 'realistic_04',
          'trigger', 'year_review',
          'source_event', 'impression',
          'emotion', 'growth'
        )
      ),
      (
        'realistic_05',
        '33333333-3333-3333-3333-333333333331'::uuid,
        CURRENT_DATE - 34,
        'month_ago',
        '这是一个被跳过的回忆帖样例，不会进入当前 feed。',
        'skipped',
        jsonb_build_object(
          'seed', '0008',
          'sample_id', 'realistic_05',
          'trigger', 'month_review',
          'source_event', 'skip',
          'skip_reason', 'low_relevance'
        )
      ),
      (
        'realistic_06',
        '33333333-3333-3333-3333-333333333332'::uuid,
        CURRENT_DATE - 28,
        'month_ago',
        '这是一个 pending 状态样例，用于状态流转演示。',
        'pending',
        jsonb_build_object(
          'seed', '0008',
          'sample_id', 'realistic_06',
          'trigger', 'month_review',
          'source_event', 'impression'
        )
      )
  ) AS t(sample_id, source_chunk_id, source_date, memory_type, post_text, status, metadata)
)
INSERT INTO memory_posts (
  user_id,
  source_book_id,
  source_chunk_id,
  source_date,
  memory_type,
  post_text,
  inserted_at,
  status,
  metadata
)
SELECT
  '11111111-1111-1111-1111-111111111111'::uuid,
  '22222222-2222-2222-2222-222222222222'::uuid,
  sr.source_chunk_id,
  sr.source_date,
  sr.memory_type,
  sr.post_text,
  CASE WHEN sr.status = 'inserted' THEN NOW() ELSE NULL END,
  sr.status,
  sr.metadata
FROM seed_rows sr
WHERE NOT EXISTS (
  SELECT 1
  FROM memory_posts mp
  WHERE mp.user_id = '11111111-1111-1111-1111-111111111111'::uuid
    AND mp.metadata ->> 'sample_id' = sr.sample_id
);
