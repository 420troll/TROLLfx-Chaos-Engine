# Handoff — TROLLfx Chaos Engine

## Verified state

- The preserved January original firmware UF2 is `firmware/original/spelltwister-01-25-25.uf2`. Its SHA-256 is recorded in its JSON sidecar.
- The unchanged upstream SpellTwister snapshot is under `upstream/`, with its MIT license.
- Arduino CLI 1.6.0, Arduino-Pico core 3.9.5 and the required libraries are installed in this WSL environment.
- The original SpellTwister source and Bench Lab compile for `rp2040:rp2040:arduino_nano_connect`, with an explicit 16 MB/no-filesystem flash option. The output UF2 ranges and size are recorded in `releases/BenchLab-V0.1/manifest.json`.
- Bench Lab maps output PWM GPIOs to match upstream: 13, 12, 1, 0. Startup leaves outputs disarmed; there is no EEPROM dependency or call in Bench Lab.
- Full-flash backup: `C:\SpellTwisterBackup\original.bin` (16 MiB), with `verify.bin` matching its SHA-256. Keep these full-flash copies separate from test release files.
- The Windows GUI, complete serial command reference, test procedure, UF2 artifacts, checksums and manifest are packaged under `releases/BenchLab-V0.1/`.

## Hardware verification boundary

- No Bench Lab UF2 has been flashed in this work.
- USB COM9 and the GUI connection have not been exercised on Windows hardware.
- The physical module PCB revision and component population have not been visually matched to the published production schematic.
- Jack output voltage, polarity, waveform quality, ripple, crosstalk and sync thresholds remain unmeasured on the physical module. Output jack voltage is bipolar on the published design; PWM code is not a calibrated voltage.
- The release UF2 starts at `0x10000000` and ends at `0x10014200`; EEPROM emulation occupies `0x10FFF000`–`0x10FFFFFF`. The generated payload does not overlap calibration storage. Maintain the verified full-flash backup before writing any firmware.

## Physical test and recovery

Follow `BENCHLAB_TEST_INSTRUCTIONS.md`; use `BENCHLAB_COMMANDS.md` for all serial commands. Begin with high-impedance probes, disarmed output checks, and disconnected downstream gear. Use only conditioned SIG inputs J6/J14 for sync tests. `STOP` holds the last output level; `DISARM` drives all PWM outputs low.

To restore original flash, enter BOOTSEL manually and use the verified full-flash image only after confirming the target device. The GUI and build scripts do not flash firmware.

## Hardware analysis

The published production IPC-D-356 netlist confirms four output paths and the upstream source assigns corresponding output pins. Gain, reference offset, filter poles and candidate 0–1 V component values in `OUTPUT_ANALYSIS.md` are calculated estimates, not measured values or approved rework instructions. The board-level schematic also includes a 24LC01; the checked-in SpellTwister NVM wrapper uses RP2040 EEPROM emulation and does not access that external device.
