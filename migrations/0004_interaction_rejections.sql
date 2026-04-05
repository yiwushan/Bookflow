-- Migration: 0004_interaction_rejections
-- Store rejected interaction events for quality diagnostics.

CREATE TABLE IF NOT EXISTS interaction_rejections (
  id BIGSERIAL PRIMARY KEY,
  trace_id TEXT NOT NULL,
  event_id TEXT,
  error_code TEXT NOT NULL,
  error_stage TEXT NOT NULL CHECK (error_stage IN ('api_validation', 'db_insert')),
  event_type TEXT,
  user_id TEXT,
  book_id TEXT,
  chunk_id TEXT,
  reason TEXT,
  raw_event JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interaction_rejections_created_at
  ON interaction_rejections (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_interaction_rejections_error
  ON interaction_rejections (error_stage, error_code, created_at DESC);
