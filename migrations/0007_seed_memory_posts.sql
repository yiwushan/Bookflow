-- Migration: 0007_seed_memory_posts
-- Dev seed for memory-post feed insertion verification.

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
  '33333333-3333-3333-3333-333333333331'::uuid,
  CURRENT_DATE - 30,
  'month_ago',
  '一个月前你读过：梯度下降的核心直觉。',
  NOW(),
  'inserted',
  '{"seed": "0007"}'::jsonb
WHERE NOT EXISTS (
  SELECT 1
  FROM memory_posts mp
  WHERE mp.user_id = '11111111-1111-1111-1111-111111111111'::uuid
    AND mp.source_chunk_id = '33333333-3333-3333-3333-333333333331'::uuid
    AND mp.memory_type = 'month_ago'
);

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
  '33333333-3333-3333-3333-333333333332'::uuid,
  CURRENT_DATE - 365,
  'year_ago',
  '一年前你标记了：一个最小实现。',
  NOW(),
  'inserted',
  '{"seed": "0007"}'::jsonb
WHERE NOT EXISTS (
  SELECT 1
  FROM memory_posts mp
  WHERE mp.user_id = '11111111-1111-1111-1111-111111111111'::uuid
    AND mp.source_chunk_id = '33333333-3333-3333-3333-333333333332'::uuid
    AND mp.memory_type = 'year_ago'
);
