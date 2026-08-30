#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
LOCK_FILE="$ROOT_DIR/scripts/.stack.lock"

cleanup() {
  set +e
  rm -f "$LOCK_FILE"
}
trap cleanup EXIT INT TERM

if [[ -f "$LOCK_FILE" ]]; then
  echo "[local-test] lock file exists: $LOCK_FILE"
  echo "[local-test] another stack may already be running."
  echo "[local-test] remove lock if stale: rm -f '$LOCK_FILE'"
  exit 1
fi

echo "$BASHPID" > "$LOCK_FILE"

if ss -ltn "( sport = :$FRONTEND_PORT )" | grep -q LISTEN; then
  echo "[local-test] port $FRONTEND_PORT is already in use."
  echo "[local-test] stop old processes before starting a new stack."
  rm -f "$LOCK_FILE"
  exit 1
fi

echo "[local-test] root: $ROOT_DIR"

echo "[local-test] ensuring frontend deps"
(
  cd "$ROOT_DIR/frontend"
  if [[ ! -d node_modules ]]; then
    npm install >/dev/null
  fi
)

echo "[local-test] stack is up"
echo "[local-test] no mock bridge is started -- test against a real ESP32 bridge (see ../stikka-esp32) on your broker"
echo "[local-test] frontend config's mqtt.brokerURL must point at your broker's websocket listener"
echo "[local-test] frontend config's supabase.url/anonKey must point at a real Supabase project (see supabase/schema.sql)"
echo "[local-test] starting frontend dev server on http://$FRONTEND_HOST:$FRONTEND_PORT"

cd "$ROOT_DIR/frontend"
npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
