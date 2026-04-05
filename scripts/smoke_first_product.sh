#!/usr/bin/env bash
set -euo pipefail

BASE_URL="http://127.0.0.1:8000"
TOKEN="local-dev-token"
FEED_LIMIT="5"
REQUIRE_ITEMS=1

usage() {
  cat <<'EOF'
BookFlow first-product smoke check.

Usage:
  ./scripts/smoke_first_product.sh [options]

Options:
  --base-url <url>      API base URL (default: http://127.0.0.1:8000)
  --token <token>       Bearer token (default: local-dev-token)
  --feed-limit <n>      Feed limit (default: 5)
  --allow-empty-feed    Do not fail when feed.items is empty
  -h, --help            Show help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --base-url)
      BASE_URL="$2"
      shift 2
      ;;
    --token)
      TOKEN="$2"
      shift 2
      ;;
    --feed-limit)
      FEED_LIMIT="$2"
      shift 2
      ;;
    --allow-empty-feed)
      REQUIRE_ITEMS=0
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

echo "[Smoke] base_url=${BASE_URL}"

tmp_health="$(mktemp)"
tmp_feed="$(mktemp)"
tmp_app="$(mktemp)"
tmp_reader="$(mktemp)"
tmp_book="$(mktemp)"
trap 'rm -f "$tmp_health" "$tmp_feed" "$tmp_app" "$tmp_reader" "$tmp_book"' EXIT

health_code="$(curl -sS -o "$tmp_health" -w "%{http_code}" "${BASE_URL}/health")"
if [[ "$health_code" != "200" ]]; then
  echo "health check failed: http=${health_code}" >&2
  cat "$tmp_health" >&2
  exit 2
fi

health_status="$(python3 - "$tmp_health" <<'PY'
import json, sys
payload = json.loads(open(sys.argv[1], encoding='utf-8').read())
print(payload.get('status', ''))
PY
)"
if [[ "$health_status" != "ok" ]]; then
  echo "health payload status!=ok: ${health_status}" >&2
  cat "$tmp_health" >&2
  exit 2
fi

feed_code="$(curl -sS -o "$tmp_feed" -w "%{http_code}" -H "Authorization: Bearer ${TOKEN}" "${BASE_URL}/v1/feed?limit=${FEED_LIMIT}&mode=default")"
if [[ "$feed_code" != "200" ]]; then
  echo "feed check failed: http=${feed_code}" >&2
  cat "$tmp_feed" >&2
  exit 2
fi

feed_items_count="$(python3 - "$tmp_feed" <<'PY'
import json, sys
payload = json.loads(open(sys.argv[1], encoding='utf-8').read())
items = payload.get('items') or []
print(len(items))
PY
)"
if [[ "$REQUIRE_ITEMS" -eq 1 && "$feed_items_count" -le 0 ]]; then
  echo "feed.items is empty" >&2
  cat "$tmp_feed" >&2
  exit 2
fi

app_code="$(curl -sS -o "$tmp_app" -w "%{http_code}" "${BASE_URL}/app")"
reader_code="$(curl -sS -o "$tmp_reader" -w "%{http_code}" "${BASE_URL}/app/reader")"
book_code="$(curl -sS -o "$tmp_book" -w "%{http_code}" "${BASE_URL}/app/book")"

for pair in "app:${app_code}" "reader:${reader_code}" "book:${book_code}"; do
  name="${pair%%:*}"
  code="${pair##*:}"
  if [[ "$code" != "200" ]]; then
    echo "frontend page failed: ${name} http=${code}" >&2
    exit 2
  fi
done

echo "[Smoke] health=ok feed_items=${feed_items_count} frontend=ok"
