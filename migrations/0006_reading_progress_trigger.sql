-- Migration: 0006_reading_progress_trigger
-- Incrementally update reading_progress after section_complete insert.

CREATE OR REPLACE FUNCTION fn_update_reading_progress_on_interaction()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
  total_sections_val INTEGER;
  section_cnt INTEGER;
  chunk_cnt INTEGER;
  completion NUMERIC(6,4);
BEGIN
  IF NEW.event_type <> 'section_complete' THEN
    RETURN NEW;
  END IF;

  SELECT COUNT(DISTINCT COALESCE(i.payload->>'section_id', ''))::int
  INTO section_cnt
  FROM interactions i
  WHERE i.user_id = NEW.user_id
    AND i.book_id = NEW.book_id
    AND i.event_type = 'section_complete'
    AND COALESCE(i.payload->>'section_id', '') <> '';

  SELECT COUNT(DISTINCT i.chunk_id)::int
  INTO chunk_cnt
  FROM interactions i
  WHERE i.user_id = NEW.user_id
    AND i.book_id = NEW.book_id
    AND i.event_type = 'section_complete';

  SELECT COALESCE(b.total_sections, 0)
  INTO total_sections_val
  FROM books b
  WHERE b.id = NEW.book_id;

  IF total_sections_val > 0 THEN
    completion := ROUND(LEAST(1.0, section_cnt::numeric / total_sections_val::numeric), 4);
  ELSE
    completion := 0.0;
  END IF;

  INSERT INTO reading_progress (
    user_id,
    book_id,
    section_completed_count,
    chunk_completed_count,
    completion_rate,
    latest_chunk_id,
    latest_event_ts,
    updated_at
  ) VALUES (
    NEW.user_id,
    NEW.book_id,
    section_cnt,
    chunk_cnt,
    completion,
    NEW.chunk_id,
    NEW.event_ts,
    NOW()
  )
  ON CONFLICT (user_id, book_id) DO UPDATE SET
    section_completed_count = EXCLUDED.section_completed_count,
    chunk_completed_count = EXCLUDED.chunk_completed_count,
    completion_rate = EXCLUDED.completion_rate,
    latest_chunk_id = EXCLUDED.latest_chunk_id,
    latest_event_ts = GREATEST(
      COALESCE(reading_progress.latest_event_ts, EXCLUDED.latest_event_ts),
      EXCLUDED.latest_event_ts
    ),
    updated_at = NOW();

  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_update_reading_progress_on_interaction ON interactions;

CREATE TRIGGER trg_update_reading_progress_on_interaction
AFTER INSERT ON interactions
FOR EACH ROW
EXECUTE FUNCTION fn_update_reading_progress_on_interaction();
