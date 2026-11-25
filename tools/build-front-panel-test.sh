#!/usr/bin/env bash
set -euo pipefail
CLI=${ARDUINO_CLI:-arduino-cli}
FQBN=${FRONT_PANEL_FQBN:-rp2040:rp2040:arduino_nano_connect}
cp upstream/src/hardware/pins.h front_panel_test/pins.h
mkdir -p build/front-panel-test
"$CLI" compile --fqbn "$FQBN" --board-options flash=16777216_0 --build-path build/front-panel-test front_panel_test
