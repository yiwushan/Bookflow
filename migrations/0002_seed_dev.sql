-- Development seed data for local verification.
-- Safe to run multiple times.

INSERT INTO users (id, name)
VALUES ('11111111-1111-1111-1111-111111111111', 'local-dev-user')
ON CONFLICT (id) DO NOTHING;

INSERT INTO books (
  id,
  title,
  author,
  language,
  book_type,
  source_format,
  source_path,
  processing_status,
  total_pages,
  total_sections
)
VALUES (
  '22222222-2222-2222-2222-222222222222',
  '深度学习导论（样例）',
  'BookFlow',
  'zh',
  'technical',
  'pdf',
  '/tmp/sample.pdf',
  'ready',
  120,
  2
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO book_chunks (
  id,
  book_id,
  section_id,
  chunk_index_in_section,
  global_index,
  title,
  text_content,
  teaser_text,
  content_version,
  render_mode,
  render_reason,
  source_anchor,
  read_time_sec_est,
  has_formula,
  has_code,
  has_table,
  quality_score,
  fidelity_score
)
VALUES
(
  '33333333-3333-3333-3333-333333333331',
  '22222222-2222-2222-2222-222222222222',
  'sec_01',
  1,
  1,
  '2.1 梯度下降的核心直觉',
  '我们先从一个非常简单的二次函数开始。设损失函数为 L(w)=w^2。w_{t+1}=w_t-η∂L/∂w。',
  '为什么梯度会收敛？',
  'chunking_v1',
  'crop',
  ARRAY['text_reflow_friendly','technical_formula_bias'],
  '{"page_start": 12, "page_end": 12, "bbox_union": [0.08, 0.18, 0.92, 0.52]}'::jsonb,
  260,
  TRUE,
  FALSE,
  FALSE,
  0.92,
  0.98
),
(
  '33333333-3333-3333-3333-333333333332',
  '22222222-2222-2222-2222-222222222222',
  'sec_02',
  1,
  2,
  '2.2 一个最小实现',
  'for step in range(10): grad = 2*w; w = w - lr*grad。这段代码展示了最基本的梯度下降流程。',
  '30 秒读懂最小实现',
  'chunking_v1',
  'reflow',
  ARRAY['text_reflow_friendly'],
  '{"page_start": 13, "page_end": 13, "bbox_union": [0.08, 0.20, 0.92, 0.58]}'::jsonb,
  210,
  FALSE,
  TRUE,
  FALSE,
  0.91,
  0.99
)
ON CONFLICT (id) DO NOTHING;

