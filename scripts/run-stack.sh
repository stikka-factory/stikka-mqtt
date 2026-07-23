#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PRINTER_NAME="${PRINTER_NAME:-stikka-test}"
BROKER_HOST="${BROKER_HOST:-127.0.0.1}"
BROKER_PORT="${BROKER_PORT:-1883}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
LOCK_FILE="$ROOT_DIR/scripts/.stack.lock"

BRIDGE_PID=""

cleanup() {
  set +e
  if [[ -n "$BRIDGE_PID" ]]; then
    kill "$BRIDGE_PID" 2>/dev/null || true
  fi
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
echo "[local-test] this script no longer starts a local broker — point BROKER_HOST/BROKER_PORT"
echo "[local-test] at an already-running MQTT broker (default: $BROKER_HOST:$BROKER_PORT)"

echo "[local-test] starting mock ESP bridge for printer '$PRINTER_NAME'"
(
  cd "$ROOT_DIR"
  if [[ "${SKIP_UV_SYNC:-0}" != "1" ]]; then
    uv sync >/dev/null
  fi
  uv run python esp32/tools/mock_bridge_server.py \
    --broker-host "$BROKER_HOST" \
    --broker-port "$BROKER_PORT" \
    --printer-name "$PRINTER_NAME"
) &
BRIDGE_PID=$!

echo "[local-test] ensuring frontend deps"
(
  cd "$ROOT_DIR/frontend"
  if [[ ! -d node_modules ]]; then
    npm install >/dev/null
  fi
)

echo "[local-test] stack is up"
echo "[local-test] frontend config's mqtt.brokerURL must point at your broker's websocket listener"
echo "[local-test] command topic: /$PRINTER_NAME/command/"
echo "[local-test] status topic:  /$PRINTER_NAME/status/"
echo "[local-test] starting frontend dev server on http://$FRONTEND_HOST:$FRONTEND_PORT"

cd "$ROOT_DIR/frontend"
npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
