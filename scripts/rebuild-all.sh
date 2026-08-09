#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$REPO_ROOT/../stikka-esp32/scripts/build-firmware.sh"
./scripts/stop-stack.sh
./scripts/run-stack.sh