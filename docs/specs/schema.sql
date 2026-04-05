-- BookFlow schema.sql
-- PostgreSQL 15+

CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'book_type_enum') THEN
    CREATE TYPE book_type_enum AS ENUM ('general', 'fiction', 'technical');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'source_format_enum') THEN
    CREATE TYPE source_format_enum AS ENUM ('pdf', 'epub', 'txt');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'processing_status_enum') THEN
    CREATE TYPE processing_status_enum AS ENUM ('pending', 'processing', 'ready', 'failed');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'render_mode_enum') THEN
    CREATE TYPE render_mode_enum AS ENUM ('reflow', 'crop');
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'event_type_enum') THEN
    CREATE TYPE event_type_enum AS ENUM (
      'impression',
      'enter_context',
      'backtrack',
      'section_complete',
      'skip',
      'confusion',
      'like',
      'comment'
    );
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS books (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title TEXT NOT NULL,
  author TEXT,
  language TEXT DEFAULT 'zh',
  book_type book_type_enum NOT NULL DEFAULT 'general',
  source_format source_format_enum NOT NULL,
  source_path TEXT,
  processing_status processing_status_enum NOT NULL DEFAULT 'pending',
  total_pages INTEGER,
  total_sections INTEGER DEFAULT 0,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_books_type_status ON books (book_type, processing_status);

CREATE TABLE IF NOT EXISTS users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT,
  profile JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS book_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  section_id TEXT NOT NULL,
  chunk_index_in_section INTEGER NOT NULL,
  global_index INTEGER NOT NULL,
  title TEXT,
  text_content TEXT NOT NULL,
  teaser_text TEXT,
  recap_text TEXT,
  content_version TEXT NOT NULL DEFAULT 'chunking_v1',
  render_mode render_mode_enum NOT NULL DEFAULT 'reflow',
  render_reason TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  source_anchor JSONB NOT NULL DEFAULT '{}'::jsonb,
  read_time_sec_est INTEGER,
  has_formula BOOLEAN NOT NULL DEFAULT FALSE,
  has_code BOOLEAN NOT NULL DEFAULT FALSE,
  has_table BOOLEAN NOT NULL DEFAULT FALSE,
  quality_score NUMERIC(5,4),
  fidelity_score NUMERIC(5,4),
  prerequisite_chunk_ids UUID[] NOT NULL DEFAULT ARRAY[]::UUID[],
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (book_id, section_id, chunk_index_in_section),
  UNIQUE (book_id, global_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_book_global ON book_chunks (book_id, global_index);
CREATE INDEX IF NOT EXISTS idx_chunks_render_mode ON book_chunks (render_mode);
CREATE INDEX IF NOT EXISTS idx_chunks_has_tech ON book_chunks (has_formula, has_code, has_table);
CREATE INDEX IF NOT EXISTS idx_chunks_source_anchor_gin ON book_chunks USING GIN (source_anchor);

CREATE TABLE IF NOT EXISTS tags (
  id BIGSERIAL PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  category TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chunk_tags (
  chunk_id UUID NOT NULL REFERENCES book_chunks(id) ON DELETE CASCADE,
  tag_id BIGINT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  score NUMERIC(5,4) NOT NULL DEFAULT 0.5,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (chunk_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_chunk_tags_tag ON chunk_tags (tag_id, score DESC);

CREATE TABLE IF NOT EXISTS user_tag_profile (
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  tag_id BIGINT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  weight NUMERIC(6,4) NOT NULL DEFAULT 0.0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, tag_id)
);

CREATE TABLE IF NOT EXISTS interactions (
  id BIGSERIAL PRIMARY KEY,
  event_id UUID NOT NULL DEFAULT gen_random_uuid(),
  event_type event_type_enum NOT NULL,
  event_ts TIMESTAMPTZ NOT NULL,
  event_date DATE GENERATED ALWAYS AS ((event_ts AT TIME ZONE 'UTC')::date) STORED,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_id TEXT NOT NULL,
  book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  chunk_id UUID NOT NULL REFERENCES book_chunks(id) ON DELETE CASCADE,
  position_in_chunk NUMERIC(4,3) NOT NULL DEFAULT 0.0 CHECK (position_in_chunk >= 0 AND position_in_chunk <= 1),
  platform TEXT NOT NULL,
  app_version TEXT NOT NULL,
  device_id TEXT,
  idempotency_key TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (event_id),
  UNIQUE (user_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_interactions_user_ts ON interactions (user_id, event_ts DESC);
CREATE INDEX IF NOT EXISTS idx_interactions_book_ts ON interactions (book_id, event_ts DESC);
CREATE INDEX IF NOT EXISTS idx_interactions_chunk_type_ts ON interactions (chunk_id, event_type, event_ts DESC);
CREATE INDEX IF NOT EXISTS idx_interactions_payload_gin ON interactions USING GIN (payload);

-- section_complete 日级去重（ADR-005）
CREATE UNIQUE INDEX IF NOT EXISTS uniq_section_complete_daily
ON interactions (
  user_id,
  book_id,
  COALESCE(payload->>'section_id', ''),
  event_date
)
WHERE event_type = 'section_complete';

CREATE TABLE IF NOT EXISTS reading_progress (
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  section_completed_count INTEGER NOT NULL DEFAULT 0,
  chunk_completed_count INTEGER NOT NULL DEFAULT 0,
  completion_rate NUMERIC(6,4) NOT NULL DEFAULT 0.0,
  latest_chunk_id UUID REFERENCES book_chunks(id) ON DELETE SET NULL,
  latest_event_ts TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, book_id)
);

CREATE INDEX IF NOT EXISTS idx_reading_progress_book_rate ON reading_progress (book_id, completion_rate DESC);

CREATE TABLE IF NOT EXISTS memory_posts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  source_book_id UUID NOT NULL REFERENCES books(id) ON DELETE CASCADE,
  source_chunk_id UUID NOT NULL REFERENCES book_chunks(id) ON DELETE CASCADE,
  source_date DATE NOT NULL,
  memory_type TEXT NOT NULL CHECK (memory_type IN ('month_ago', 'year_ago')),
  post_text TEXT,
  inserted_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'inserted', 'skipped', 'failed')),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memory_posts_user_status ON memory_posts (user_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_posts_source_date ON memory_posts (source_date);
