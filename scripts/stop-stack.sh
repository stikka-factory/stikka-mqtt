#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_FILE="$ROOT_DIR/scripts/.stack.lock"

echo "[local-test] stopping known stack processes"
pkill -f "vite --host 127.0.0.1 --port 5173" 2>/dev/null || true
pkill -f "esp32/tools/mock_bridge_server.py" 2>/dev/null || true

rm -f "$LOCK_FILE"

echo "[local-test] remaining listeners on 5173:"
ss -ltn '( sport = :5173 )' || true
