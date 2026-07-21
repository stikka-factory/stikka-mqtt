#!/usr/bin/env bash

./scripts/build-firmware.sh
./scripts/stop-stack.sh
./scripts/run-stack.sh