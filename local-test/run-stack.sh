#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BROKER_CONF="$ROOT_DIR/local-test/mosquitto.conf"
PRINTER_NAME="${PRINTER_NAME:-stikka-test}"
BROKER_HOST="${BROKER_HOST:-127.0.0.1}"
BROKER_PORT="${BROKER_PORT:-1883}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
LOCK_FILE="$ROOT_DIR/local-test/.stack.lock"

MOSQ_PID=""
BRIDGE_PID=""

cleanup() {
  set +e
  if [[ -n "$BRIDGE_PID" ]]; then
    kill "$BRIDGE_PID" 2>/dev/null || true
  fi
  if [[ -n "$MOSQ_PID" ]]; then
    kill "$MOSQ_PID" 2>/dev/null || true
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

if ss -ltn '( sport = :5173 or sport = :1883 or sport = :9001 )' | grep -q LISTEN; then
  echo "[local-test] one of required ports (5173,1883,9001) is already in use."
  echo "[local-test] stop old processes before starting a new stack."
  rm -f "$LOCK_FILE"
  exit 1
fi

echo "[local-test] root: $ROOT_DIR"
echo "[local-test] starting mosquitto (mqtt://$BROKER_HOST:1883, ws://$BROKER_HOST:9001)"
mosquitto -c "$BROKER_CONF" -v &
MOSQ_PID=$!

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
echo "[local-test] frontend config should use ws://localhost:9001 and mode=mqtt"
echo "[local-test] command topic: /command/$PRINTER_NAME"
echo "[local-test] status topic:  /status/$PRINTER_NAME"
echo "[local-test] starting frontend dev server on http://$FRONTEND_HOST:$FRONTEND_PORT"

cd "$ROOT_DIR/frontend"
npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
