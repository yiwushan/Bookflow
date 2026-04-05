#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${CONTAINER_NAME:-bookflow-pg}"
PG_IMAGE="${PG_IMAGE:-ghcr.io/cloudnative-pg/postgresql:16.6}"
PG_USER="${PG_USER:-bookflow}"
PG_PASSWORD="${PG_PASSWORD:-bookflow}"
PG_DB="${PG_DB:-bookflow}"
PG_PORT="${PG_PORT:-55432}"

echo "[1/9] Start Postgres container: ${CONTAINER_NAME}"
docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
docker run -d \
  --name "${CONTAINER_NAME}" \
  -e POSTGRES_USER="${PG_USER}" \
  -e POSTGRES_PASSWORD="${PG_PASSWORD}" \
  -e POSTGRES_DB="${PG_DB}" \
  -p "${PG_PORT}:5432" \
  "${PG_IMAGE}" >/dev/null

echo "[2/9] Wait for readiness"
for i in $(seq 1 60); do
  if docker exec "${CONTAINER_NAME}" pg_isready -U "${PG_USER}" -d "${PG_DB}" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "[3/9] Apply core migration"
docker exec -i "${CONTAINER_NAME}" psql -U "${PG_USER}" -d "${PG_DB}" < migrations/0001_init.sql >/dev/null

echo "[4/9] Apply extension migrations"
docker exec -i "${CONTAINER_NAME}" psql -U "${PG_USER}" -d "${PG_DB}" < migrations/0003_metrics_materialized.sql >/dev/null
docker exec -i "${CONTAINER_NAME}" psql -U "${PG_USER}" -d "${PG_DB}" < migrations/0004_interaction_rejections.sql >/dev/null
docker exec -i "${CONTAINER_NAME}" psql -U "${PG_USER}" -d "${PG_DB}" < migrations/0006_reading_progress_trigger.sql >/dev/null

echo "[5/9] Apply dev seed"
docker exec -i "${CONTAINER_NAME}" psql -U "${PG_USER}" -d "${PG_DB}" < migrations/0002_seed_dev.sql >/dev/null

echo "[6/9] Apply tag seed"
docker exec -i "${CONTAINER_NAME}" psql -U "${PG_USER}" -d "${PG_DB}" < migrations/0005_seed_tags.sql >/dev/null

echo "[7/9] Apply memory post seed (minimal)"
docker exec -i "${CONTAINER_NAME}" psql -U "${PG_USER}" -d "${PG_DB}" < migrations/0007_seed_memory_posts.sql >/dev/null

echo "[8/9] Apply memory post seed (realistic)"
docker exec -i "${CONTAINER_NAME}" psql -U "${PG_USER}" -d "${PG_DB}" < migrations/0008_seed_memory_posts_realistic.sql >/dev/null

echo "[9/9] Done"
echo "DATABASE_URL=postgresql://${PG_USER}:${PG_PASSWORD}@127.0.0.1:${PG_PORT}/${PG_DB}"
echo "Use with:"
echo "  export DATABASE_URL=postgresql://${PG_USER}:${PG_PASSWORD}@127.0.0.1:${PG_PORT}/${PG_DB}"
echo "  python3 server/app.py --host 127.0.0.1 --port 8000"
