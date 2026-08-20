#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

cleanup() {
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
}

cd "$PROJECT_ROOT"
if [[ ! -x "$PROJECT_ROOT/frontend/node_modules/.bin/next" ]]; then
  (
    cd "$PROJECT_ROOT/frontend"
    npm ci
  )
fi

./scripts/start.sh &
BACKEND_PID=$!

(
  cd "$PROJECT_ROOT/frontend"
  exec env ADMIN_API_BASE_URL="${ADMIN_API_BASE_URL:-http://127.0.0.1:8790}" npm run dev
) &
FRONTEND_PID=$!

xdg-open "http://localhost:3000" &

trap cleanup EXIT INT TERM
wait -n "$BACKEND_PID" "$FRONTEND_PID"
