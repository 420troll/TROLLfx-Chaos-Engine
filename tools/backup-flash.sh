#!/usr/bin/env bash
# Read-only flash save. Run only after picotool sees the RP2040 in BOOTSEL.
set -euo pipefail
PICOTOOL=${PICOTOOL:-picotool}
OUT=${1:-firmware/backup/installed-flash.bin}
mkdir -p "$(dirname "$OUT")"
"$PICOTOOL" info -a
"$PICOTOOL" save -a -v "$OUT"
sha256sum "$OUT" | tee "$OUT.sha256"
"$(dirname "$0")/compare_flash_uf2.py" "$OUT" firmware/original/spelltwister-01-25-25.uf2 | tee "${OUT}.uf2-compare.json"
