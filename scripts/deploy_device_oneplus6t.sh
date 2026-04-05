#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

HOST="127.0.0.1"
PORT="8000"
TOKEN="${BOOKFLOW_TOKEN:-local-dev-token}"
ENV_FILE="${REPO_ROOT}/config/bookflow.device.env"
VENV_DIR="${REPO_ROOT}/.venv"

PG_MODE="local" # local | docker | skip
PG_HOST="127.0.0.1"
PG_PORT=""
PG_DB="bookflow"
PG_USER="bookflow"
PG_PASSWORD="bookflow"

INSTALL_DEPS=1
INSTALL_SYSTEMD=0
RUN_SMOKE=1

SERVICE_NAME="bookflow"
SERVICE_USER="$(id -un)"
TEMP_SERVER_PID=""
TEMP_SERVER_LOG="${REPO_ROOT}/logs/deploy_temp_server.log"

msg() { echo "[deploy] $*"; }
warn() { echo "[deploy][warn] $*" >&2; }
err() { echo "[deploy][error] $*" >&2; }

cleanup() {
  if [[ -n "${TEMP_SERVER_PID:-}" ]]; then
    if kill -0 "${TEMP_SERVER_PID}" >/dev/null 2>&1; then
      kill "${TEMP_SERVER_PID}" >/dev/null 2>&1 || true
      sleep 0.2
      if kill -0 "${TEMP_SERVER_PID}" >/dev/null 2>&1; then
        kill -9 "${TEMP_SERVER_PID}" >/dev/null 2>&1 || true
      fi
    fi
    TEMP_SERVER_PID=""
  fi
}
trap cleanup EXIT

usage() {
  cat <<'EOF'
BookFlow device deploy helper (Ubuntu ARM friendly).

Usage:
  ./scripts/deploy_device_oneplus6t.sh [options]

Options:
  --host <host>                 API host (default: 127.0.0.1)
  --port <port>                 API port (default: 8000)
  --token <token>               BOOKFLOW_TOKEN (default: local-dev-token)
  --env-file <path>             Env file output path (default: config/bookflow.device.env)
  --venv-dir <path>             Python venv path (default: .venv)

  --pg-mode <local|docker|skip> Postgres mode (default: local)
  --pg-host <host>              Postgres host (default: 127.0.0.1)
  --pg-port <port>              Postgres port (default: local=5432, docker=55432)
  --pg-db <name>                Postgres DB name (default: bookflow)
  --pg-user <name>              Postgres user (default: bookflow)
  --pg-password <pwd>           Postgres password (default: bookflow)

  --no-install-deps             Skip apt/pip dependency install
  --no-smoke                    Skip smoke check
  --install-systemd             Install and enable systemd service
  --service-name <name>         systemd service name (default: bookflow)
  --service-user <name>         systemd service user (default: current user)

  -h, --help                    Show this help

Examples:
  ./scripts/deploy_device_oneplus6t.sh
  ./scripts/deploy_device_oneplus6t.sh --install-systemd
  ./scripts/deploy_device_oneplus6t.sh --pg-mode docker --pg-port 55432
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) HOST="$2"; shift 2 ;;
    --port) PORT="$2"; shift 2 ;;
    --token) TOKEN="$2"; shift 2 ;;
    --env-file) ENV_FILE="$2"; shift 2 ;;
    --venv-dir) VENV_DIR="$2"; shift 2 ;;
    --pg-mode) PG_MODE="$2"; shift 2 ;;
    --pg-host) PG_HOST="$2"; shift 2 ;;
    --pg-port) PG_PORT="$2"; shift 2 ;;
    --pg-db) PG_DB="$2"; shift 2 ;;
    --pg-user) PG_USER="$2"; shift 2 ;;
    --pg-password) PG_PASSWORD="$2"; shift 2 ;;
    --no-install-deps) INSTALL_DEPS=0; shift ;;
    --no-smoke) RUN_SMOKE=0; shift ;;
    --install-systemd) INSTALL_SYSTEMD=1; shift ;;
    --service-name) SERVICE_NAME="$2"; shift 2 ;;
    --service-user) SERVICE_USER="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *)
      err "Unknown option: $1"
      usage
      exit 2
      ;;
  esac
done

if [[ "${PG_MODE}" != "local" && "${PG_MODE}" != "docker" && "${PG_MODE}" != "skip" ]]; then
  err "--pg-mode must be one of local|docker|skip"
  exit 2
fi

if [[ -z "${PG_PORT}" ]]; then
  if [[ "${PG_MODE}" == "docker" ]]; then
    PG_PORT="55432"
  else
    PG_PORT="5432"
  fi
fi

if ! command -v python3 >/dev/null 2>&1; then
  err "python3 not found"
  exit 2
fi

if [[ ! -d "${REPO_ROOT}/server" || ! -f "${REPO_ROOT}/server/app.py" ]]; then
  err "Invalid repo root: ${REPO_ROOT}"
  exit 2
fi

ensure_dirs() {
  mkdir -p \
    "${REPO_ROOT}/data/books/inbox" \
    "${REPO_ROOT}/data/books/derived" \
    "${REPO_ROOT}/data/cache" \
    "${REPO_ROOT}/data/toc" \
    "${REPO_ROOT}/data/users/export" \
    "${REPO_ROOT}/logs" \
    "${REPO_ROOT}/config"
}

server_up() {
  curl -fsS -m 2 "http://${HOST}:${PORT}/health" >/dev/null 2>&1
}

wait_server_ready() {
  local max_rounds="${1:-60}"
  for _i in $(seq 1 "${max_rounds}"); do
    if server_up; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

start_temp_server_for_smoke() {
  if [[ -n "${TEMP_SERVER_PID:-}" ]]; then
    return 0
  fi
  msg "Start temporary server for smoke on http://${HOST}:${PORT}"
  (
    cd "${REPO_ROOT}"
    set -a
    # shellcheck source=/dev/null
    source "${ENV_FILE}"
    set +a
    exec "${VENV_DIR}/bin/python" server/app.py --host "${HOST}" --port "${PORT}"
  ) >"${TEMP_SERVER_LOG}" 2>&1 &
  TEMP_SERVER_PID="$!"
  if ! wait_server_ready 80; then
    err "Temporary server did not become ready in time"
    if [[ -f "${TEMP_SERVER_LOG}" ]]; then
      warn "Last server log lines:"
      tail -n 120 "${TEMP_SERVER_LOG}" >&2 || true
    fi
    exit 2
  fi
}

install_system_packages() {
  if [[ "${INSTALL_DEPS}" -ne 1 ]]; then
    msg "Skip apt dependencies (--no-install-deps)"
    return 0
  fi
  if ! command -v apt-get >/dev/null 2>&1; then
    warn "apt-get not found, skip system package install"
    return 0
  fi
  if ! command -v sudo >/dev/null 2>&1; then
    err "sudo is required for dependency install"
    exit 2
  fi
  msg "Install apt dependencies"
  sudo apt-get update
  sudo apt-get install -y \
    python3-venv \
    python3-pip \
    python3-dev \
    build-essential \
    poppler-utils \
    postgresql \
    postgresql-contrib \
    libpq-dev
}

install_python_dependencies() {
  if [[ "${INSTALL_DEPS}" -ne 1 ]]; then
    msg "Skip pip dependencies (--no-install-deps)"
    return 0
  fi
  msg "Create/update venv: ${VENV_DIR}"
  python3 -m venv "${VENV_DIR}"
  "${VENV_DIR}/bin/pip" install --upgrade pip setuptools wheel
  "${VENV_DIR}/bin/pip" install \
    psycopg[binary] \
    pypdf \
    rapidocr_onnxruntime \
    beautifulsoup4 \
    pyyaml
}

setup_pg_local() {
  msg "Setup local Postgres (${PG_HOST}:${PG_PORT}/${PG_DB})"
  if ! command -v psql >/dev/null 2>&1; then
    err "psql not found; install postgres client first"
    exit 2
  fi
  if ! command -v sudo >/dev/null 2>&1; then
    err "sudo is required for local postgres bootstrap"
    exit 2
  fi
  sudo systemctl enable --now postgresql

  if ! sudo -u postgres pg_isready -h "${PG_HOST}" -p "${PG_PORT}" >/dev/null 2>&1; then
    err "Postgres is not reachable at ${PG_HOST}:${PG_PORT}"
    err "Try --pg-port 5432 for local Postgres, or switch to --pg-mode docker"
    exit 2
  fi

  local user_exists
  user_exists="$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${PG_USER}'" || true)"
  if [[ "${user_exists}" != "1" ]]; then
    sudo -u postgres psql -c "CREATE ROLE ${PG_USER} WITH LOGIN PASSWORD '${PG_PASSWORD}';"
  fi

  local db_exists
  db_exists="$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${PG_DB}'" || true)"
  if [[ "${db_exists}" != "1" ]]; then
    sudo -u postgres psql -c "CREATE DATABASE ${PG_DB} OWNER ${PG_USER};"
  fi
}

setup_pg_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    err "docker not found for --pg-mode docker"
    exit 2
  fi
  msg "Setup docker Postgres via scripts/dev_postgres.sh"
  (
    cd "${REPO_ROOT}"
    CONTAINER_NAME="bookflow-pg" \
    PG_USER="${PG_USER}" \
    PG_PASSWORD="${PG_PASSWORD}" \
    PG_DB="${PG_DB}" \
    PG_PORT="${PG_PORT}" \
    ./scripts/dev_postgres.sh
  )
}

apply_migrations() {
  local dsn="postgresql://${PG_USER}:${PG_PASSWORD}@${PG_HOST}:${PG_PORT}/${PG_DB}"
  msg "Apply migrations to ${dsn}"
  for m in \
    0001_init.sql \
    0003_metrics_materialized.sql \
    0004_interaction_rejections.sql \
    0006_reading_progress_trigger.sql \
    0002_seed_dev.sql \
    0005_seed_tags.sql \
    0007_seed_memory_posts.sql \
    0008_seed_memory_posts_realistic.sql
  do
    psql "${dsn}" -f "${REPO_ROOT}/migrations/${m}" >/dev/null
  done
}

write_env_file() {
  local dsn="postgresql://${PG_USER}:${PG_PASSWORD}@${PG_HOST}:${PG_PORT}/${PG_DB}"
  msg "Write env file: ${ENV_FILE}"
  cat > "${ENV_FILE}" <<EOF
BOOKFLOW_TOKEN=${TOKEN}
DATABASE_URL=${dsn}
BOOKFLOW_PDF_SECTION_STORAGE=on_demand
BOOKFLOW_STARTUP_BOOTSTRAP_ENABLED=1
BOOKFLOW_STARTUP_BOOTSTRAP_INPUT_DIR=${REPO_ROOT}/data/books/inbox
BOOKFLOW_STARTUP_BOOTSTRAP_INTERVAL_SEC=1800
BOOKFLOW_STARTUP_BOOTSTRAP_SKIP_EXISTING=1
BOOKFLOW_STARTUP_BOOTSTRAP_RESCAN_APPROVED=0
BOOKFLOW_STARTUP_BOOTSTRAP_AUTO_APPROVE_IMPORTED=0
BOOKFLOW_STARTUP_BOOTSTRAP_WARM_COVER_LIMIT=6
BOOKFLOW_CACHE_ROOT=${REPO_ROOT}/data/cache
BOOKFLOW_USER_EXPORT_DIR=${REPO_ROOT}/data/users/export
EOF
}

install_systemd_service() {
  if [[ "${INSTALL_SYSTEMD}" -ne 1 ]]; then
    return 0
  fi
  if ! command -v sudo >/dev/null 2>&1; then
    err "sudo is required for --install-systemd"
    exit 2
  fi
  local unit_file="/etc/systemd/system/${SERVICE_NAME}.service"
  msg "Install systemd unit: ${unit_file}"
  sudo tee "${unit_file}" >/dev/null <<EOF
[Unit]
Description=BookFlow V0 Service
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=${SERVICE_USER}
Group=${SERVICE_USER}
WorkingDirectory=${REPO_ROOT}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/python ${REPO_ROOT}/server/app.py --host ${HOST} --port ${PORT}
Restart=always
RestartSec=3
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable --now "${SERVICE_NAME}.service"
}

run_smoke_if_needed() {
  if [[ "${RUN_SMOKE}" -ne 1 ]]; then
    msg "Skip smoke check (--no-smoke)"
    return 0
  fi
  if ! server_up; then
    if [[ "${INSTALL_SYSTEMD}" -eq 1 ]]; then
      msg "Wait systemd service health on http://${HOST}:${PORT}"
      if ! wait_server_ready 80; then
        err "Service is not reachable for smoke (http://${HOST}:${PORT}/health)"
        if command -v sudo >/dev/null 2>&1; then
          sudo systemctl --no-pager -l status "${SERVICE_NAME}.service" || true
        fi
        exit 2
      fi
    else
      start_temp_server_for_smoke
    fi
  fi
  msg "Run smoke check"
  (
    cd "${REPO_ROOT}"
    ./scripts/smoke_first_product.sh --base-url "http://${HOST}:${PORT}" --token "${TOKEN}" --allow-empty-feed
  )
}

print_next_steps() {
  local dsn="postgresql://${PG_USER}:${PG_PASSWORD}@${PG_HOST}:${PG_PORT}/${PG_DB}"
  cat <<EOF

[deploy] Done.

Env file:
  ${ENV_FILE}

Run manually (without systemd):
  cd ${REPO_ROOT}
  set -a && source ${ENV_FILE} && set +a
  ${VENV_DIR}/bin/python server/app.py --host ${HOST} --port ${PORT}

Open:
  http://${HOST}:${PORT}/app
  http://${HOST}:${PORT}/app/toc

DB:
  ${dsn}
EOF
}

main() {
  msg "Repo root: ${REPO_ROOT}"
  msg "Device arch: $(uname -m)"
  msg "Mode: pg=${PG_MODE}, host=${HOST}, port=${PORT}, systemd=${INSTALL_SYSTEMD}"

  ensure_dirs
  install_system_packages
  install_python_dependencies

  case "${PG_MODE}" in
    local)
      setup_pg_local
      apply_migrations
      ;;
    docker)
      setup_pg_docker
      ;;
    skip)
      warn "Skip Postgres setup (--pg-mode skip); ensure DATABASE_URL points to a ready DB."
      ;;
  esac

  write_env_file
  install_systemd_service
  run_smoke_if_needed
  print_next_steps
}

main "$@"
