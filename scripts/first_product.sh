#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

HOST="127.0.0.1"
PORT="8000"
INPUT_DIR="${REPO_ROOT}/data/books/inbox"
LANGUAGE="zh"
TOKEN="${BOOKFLOW_TOKEN:-local-dev-token}"
DATABASE_URL_VALUE="${DATABASE_URL:-}"
BOOK_TYPE_STRATEGY="auto"
DEFAULT_BOOK_TYPE="general"
FIXED_BOOK_TYPE="technical"
IMPORT_LIMIT=""
RECURSIVE=0
DRY_RUN_IMPORT=0
SKIP_DB_BOOTSTRAP=0
SKIP_IMPORT=0
NO_SERVER=0
PDF_SECTION_STORAGE="${BOOKFLOW_PDF_SECTION_STORAGE:-precut}"

usage() {
  cat <<'EOF'
BookFlow First Product Runner

Usage:
  ./scripts/first_product.sh [options]

Options:
  --host <host>                  Server host (default: 127.0.0.1)
  --port <port>                  Server port (default: 8000)
  --input-dir <path>             Library dir to import (default: data/books/inbox)
  --database-url <dsn>           Override DATABASE_URL
  --token <token>                API token for frontend/API (default: local-dev-token)
  --language <lang>              Import language tag (default: zh)
  --book-type-strategy <auto|fixed>
  --default-book-type <general|fiction|technical>
  --fixed-book-type <general|fiction|technical>
  --import-limit <n>             Import at most N files
  --recursive                    Recursively scan input-dir
  --dry-run-import               Run import pipeline without DB writes
  --pdf-section-storage <mode>   PDF章节存储: precut 或 on_demand（默认: precut）
  --skip-db-bootstrap            Do not run scripts/dev_postgres.sh
  --skip-import                  Do not run scripts/import_library.py
  --no-server                    Exit after bootstrap/import; do not start API server
  -h, --help                     Show help

Examples:
  ./scripts/first_product.sh
  ./scripts/first_product.sh --input-dir data/books/inbox --book-type-strategy auto
  ./scripts/first_product.sh --skip-db-bootstrap --database-url postgresql://bookflow:bookflow@127.0.0.1:55432/bookflow
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)
      HOST="$2"
      shift 2
      ;;
    --port)
      PORT="$2"
      shift 2
      ;;
    --input-dir)
      INPUT_DIR="$2"
      shift 2
      ;;
    --database-url)
      DATABASE_URL_VALUE="$2"
      shift 2
      ;;
    --token)
      TOKEN="$2"
      shift 2
      ;;
    --language)
      LANGUAGE="$2"
      shift 2
      ;;
    --book-type-strategy)
      BOOK_TYPE_STRATEGY="$2"
      shift 2
      ;;
    --default-book-type)
      DEFAULT_BOOK_TYPE="$2"
      shift 2
      ;;
    --fixed-book-type)
      FIXED_BOOK_TYPE="$2"
      shift 2
      ;;
    --import-limit)
      IMPORT_LIMIT="$2"
      shift 2
      ;;
    --recursive)
      RECURSIVE=1
      shift
      ;;
    --dry-run-import)
      DRY_RUN_IMPORT=1
      shift
      ;;
    --pdf-section-storage)
      PDF_SECTION_STORAGE="$2"
      shift 2
      ;;
    --skip-db-bootstrap)
      SKIP_DB_BOOTSTRAP=1
      shift
      ;;
    --skip-import)
      SKIP_IMPORT=1
      shift
      ;;
    --no-server)
      NO_SERVER=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 2
fi

if [[ -z "${DATABASE_URL_VALUE}" ]]; then
  DATABASE_URL_VALUE="postgresql://bookflow:bookflow@127.0.0.1:55432/bookflow"
fi

export BOOKFLOW_TOKEN="${TOKEN}"
export DATABASE_URL="${DATABASE_URL_VALUE}"
export BOOKFLOW_PDF_SECTION_STORAGE="${PDF_SECTION_STORAGE}"

cd "${REPO_ROOT}"

echo "[BookFlow First Product]"
echo "repo_root=${REPO_ROOT}"
echo "input_dir=${INPUT_DIR}"
echo "database_url=${DATABASE_URL}"

if [[ "${SKIP_DB_BOOTSTRAP}" -eq 0 ]]; then
  if ! command -v docker >/dev/null 2>&1; then
    echo "docker is required for --skip-db-bootstrap=0" >&2
    exit 2
  fi
  echo "[1/3] Bootstrapping local Postgres"
  ./scripts/dev_postgres.sh
else
  echo "[1/3] Skipped Postgres bootstrap"
fi

if [[ "${SKIP_IMPORT}" -eq 0 ]]; then
  echo "[2/3] Importing library"
  import_cmd=(
    python3 scripts/import_library.py
    --input-dir "${INPUT_DIR}"
    --database-url "${DATABASE_URL}"
    --book-type-strategy "${BOOK_TYPE_STRATEGY}"
    --default-book-type "${DEFAULT_BOOK_TYPE}"
    --fixed-book-type "${FIXED_BOOK_TYPE}"
    --language "${LANGUAGE}"
    --pdf-section-storage "${PDF_SECTION_STORAGE}"
  )
  if [[ "${RECURSIVE}" -eq 1 ]]; then
    import_cmd+=(--recursive)
  fi
  if [[ "${DRY_RUN_IMPORT}" -eq 1 ]]; then
    import_cmd+=(--dry-run)
  fi
  if [[ -n "${IMPORT_LIMIT}" ]]; then
    import_cmd+=(--limit "${IMPORT_LIMIT}")
  fi
  "${import_cmd[@]}"
else
  echo "[2/3] Skipped library import"
fi

if [[ "${NO_SERVER}" -eq 1 ]]; then
  echo "[3/3] Skipped server start"
  echo "You can run manually:"
  echo "  BOOKFLOW_TOKEN='${TOKEN}' DATABASE_URL='${DATABASE_URL}' python3 server/app.py --host ${HOST} --port ${PORT}"
  exit 0
fi

echo "[3/3] Starting API server"
echo "Open feed:   http://${HOST}:${PORT}/app"
echo "Open reader: http://${HOST}:${PORT}/app/reader"
echo "Open mosaic: http://${HOST}:${PORT}/app/book"
echo "Token:       ${TOKEN}"
echo ""
exec python3 server/app.py --host "${HOST}" --port "${PORT}"
