#!/usr/bin/env bash
set -euo pipefail
CLI=${ARDUINO_CLI:-arduino-cli}
FQBN=${SPELLTWISTER_FQBN:-rp2040:rp2040:arduino_nano_connect}
mkdir -p build/benchlab
"$CLI" compile --fqbn "$FQBN" --board-options flash=16777216_0 --build-path build/benchlab benchlab/benchlab.ino
