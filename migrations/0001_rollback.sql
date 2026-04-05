-- Rollback for migrations/0001_init.sql
-- Warning: destructive, drops all BookFlow tables/types.

DROP TABLE IF EXISTS memory_posts;
DROP TABLE IF EXISTS reading_progress;
DROP TABLE IF EXISTS interactions;
DROP TABLE IF EXISTS user_tag_profile;
DROP TABLE IF EXISTS chunk_tags;
DROP TABLE IF EXISTS tags;
DROP TABLE IF EXISTS book_chunks;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS books;

DROP TYPE IF EXISTS event_type_enum;
DROP TYPE IF EXISTS render_mode_enum;
DROP TYPE IF EXISTS processing_status_enum;
DROP TYPE IF EXISTS source_format_enum;
DROP TYPE IF EXISTS book_type_enum;

