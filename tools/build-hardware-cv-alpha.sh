#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
CLI=${ARDUINO_CLI:-arduino-cli}
FQBN=${SPELLTWISTER_FQBN:-rp2040:rp2040:arduino_nano_connect}
SKETCH=build/hardware-cv-source/hardware_cv_alpha
mkdir -p "$SKETCH" build/hardware-cv-alpha
cp hardware-cv-alpha/hardware_cv_alpha.ino "$SKETCH/"
cp -R upstream/src "$SKETCH/"
"$CLI" compile --fqbn "$FQBN" --board-options flash=16777216_0 --build-path build/hardware-cv-alpha "$SKETCH"
mkdir -p /mnt/c/SpellTwisterBackup/Chaos-CV-Alpha
cp build/hardware-cv-alpha/hardware_cv_alpha.ino.uf2 /mnt/c/SpellTwisterBackup/Chaos-CV-Alpha/Chaos-CV-Alpha.uf2
sha256sum /mnt/c/SpellTwisterBackup/Chaos-CV-Alpha/Chaos-CV-Alpha.uf2
