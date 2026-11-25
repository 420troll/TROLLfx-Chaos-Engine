#!/usr/bin/env bash
set -euo pipefail
CLI=${ARDUINO_CLI:-arduino-cli}
FQBN=${SPELLTWISTER_FQBN:-rp2040:rp2040:arduino_nano_connect}
mkdir -p build/original-baseline
SKETCH=build/original-source/spelltwister
rm -rf "$SKETCH"
mkdir -p "$SKETCH"
cp upstream/spelltwister.ino "$SKETCH/spelltwister.ino"
cp -R upstream/src "$SKETCH/src"
"$CLI" compile --fqbn "$FQBN" --board-options flash=16777216_0 --build-path build/original-baseline "$SKETCH"
