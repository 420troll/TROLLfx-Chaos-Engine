#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
CLI=${ARDUINO_CLI:-arduino-cli}
FQBN=${SPELLTWISTER_FQBN:-rp2040:rp2040:arduino_nano_connect}
SKETCH=build/hardware-alpha-source/hardware_alpha
mkdir -p "$SKETCH" build/hardware-alpha
cp hardware-alpha/hardware_alpha.ino hardware-alpha/video_cv.h "$SKETCH/"
cp -R upstream/src "$SKETCH/"
"$CLI" compile --fqbn "$FQBN" --board-options flash=16777216_0 --build-path build/hardware-alpha "$SKETCH"
find build/hardware-alpha -maxdepth 1 -name '*.uf2' -exec sha256sum {} \;
