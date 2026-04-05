-- Migration: 0005_seed_tags
-- Minimal tag seeds + cold-start mapping for local/dev usage.

INSERT INTO tags (name, category)
VALUES
  ('干货', 'general'),
  ('睡前故事', 'fiction'),
  ('心理学', 'general'),
  ('算法', 'technical'),
  ('编程', 'technical'),
  ('小说', 'fiction')
ON CONFLICT (name) DO NOTHING;

-- Seed chunk tags for existing dev sample chunks.
INSERT INTO chunk_tags (chunk_id, tag_id, score)
SELECT
  '33333333-3333-3333-3333-333333333331'::uuid,
  t.id,
  v.score
FROM (VALUES ('算法', 0.95::numeric), ('干货', 0.75::numeric)) AS v(name, score)
JOIN tags t ON t.name = v.name
ON CONFLICT (chunk_id, tag_id) DO UPDATE SET
  score = EXCLUDED.score;

INSERT INTO chunk_tags (chunk_id, tag_id, score)
SELECT
  '33333333-3333-3333-3333-333333333332'::uuid,
  t.id,
  v.score
FROM (VALUES ('编程', 0.95::numeric), ('干货', 0.70::numeric)) AS v(name, score)
JOIN tags t ON t.name = v.name
ON CONFLICT (chunk_id, tag_id) DO UPDATE SET
  score = EXCLUDED.score;

-- Seed default profile for local dev user.
INSERT INTO user_tag_profile (user_id, tag_id, weight)
SELECT
  '11111111-1111-1111-1111-111111111111'::uuid,
  t.id,
  v.weight
FROM (
  VALUES
    ('算法', 1.20::numeric),
    ('编程', 1.00::numeric),
    ('干货', 0.80::numeric),
    ('心理学', 0.40::numeric),
    ('睡前故事', 0.20::numeric),
    ('小说', 0.20::numeric)
) AS v(name, weight)
JOIN tags t ON t.name = v.name
ON CONFLICT (user_id, tag_id) DO UPDATE SET
  weight = EXCLUDED.weight,
  updated_at = NOW();
