# Front Panel Test V0.6

This release scans the original SpellTwister controls at 200 Hz and reports state over USB at 10 Hz. It keeps all four static DC output controls from V0.5, starts at normalized signal code 0, and does not read or write factory calibration storage. It does not flash itself.

## Build and install

Build with Arduino RP2040 core 3.9.5 and the 16 MB flash option:

```sh
ARDUINO_CLI=/home/gamer/bin/arduino-cli ./tools/build-front-panel-test.sh
```

If installation is desired, use the board's normal UF2 bootloader procedure with `FrontPanel-Test-V0.6.uf2`. This package does not automate flashing. The UF2 writes `0x10000000–0x10015700`; EEPROM emulation is reserved at `0x10FFF000–0x11000000`, so the payload does not overlap the reserved calibration sector. Keep the independent full-flash backups.

## Windows GUI

Install Python 3, connect the module, and run `run-gui.cmd`. The port picker defaults to COM9. The GUI sends `PROTO?`, answers with `HELLO GUI=0.6`, then asks for `SNAPSHOT`. It shows its own resolved GUI, telemetry and calibration module paths in the Serial tab to expose accidental imports from older folders.

The Live tab shows each pot's normalized value and raw ADC separately, both three-position mode switch states, encoder/buttons and four static outputs. `Lock` holds the selected pot; `Unlock` restores firmware last-moved selection. The Inputs tab shows CV, sync and the direct GPIO27/28 diagnostic. DC CAL sliders and presets command outputs immediately without an arming step. A normalized signal code is not a measured jack voltage; enter DMM readings manually before relying on gain/offset calculations.

## Bench checks (no oscilloscope required)

1. Connect USB and Eurorack power. Confirm the connection status reaches `Connected · FP06 / GUI 0.6` and that packet/age values advance.
2. Move A Time, B Time, A/B Slope and A/B Ratio individually. Check each live meter, raw ADC value, normalized value and last-moved indication. Raw Time readings correspond to direct GPIO27 and GPIO28.
3. Move both three-position switches through ENV, LFO and VCO. Confirm exactly one segment is active; a both-active reading is reported as INVALID.
4. Turn the encoder clockwise/counter-clockwise and press encoder and Follow buttons. Confirm position and button state.
5. Set each DC output to 0%, 25%, 50%, 75% and 100%. Use a DMM at the jack to record voltage; do not infer voltage from code or LED brightness. Verify the corresponding indicator follows commanded signal code.
6. Try LED startup, RGB, ring chase, one-pixel override and LED LIVE. Confirm the live state resumes after the override.
7. Disconnect/reconnect USB without removing Eurorack power. Confirm outputs remain at the last static setting and GUI re-handshakes.
8. Enter `DIAG` in Serial for raw min/max/noise, or `TIME DIAG` to compare scan, Arduino and SDK ADC reads. These advanced readings are not part of normal monitoring.

## Firmware commands

`HELP`, `INFO`, `PROTO?`, `HELLO GUI=0.6`, `SNAPSHOT`, `DC?`, `DC <channel 0..3> <percent 0..100>`, `REPORT LIVE`, `REPORT CHANGE`, `LED STARTUP`, `LED RGB`, `LED RING`, `LED LIVE`, `LED ONE <index 0..22> <r> <g> <b>`, `BRIGHTNESS <0..255>`, `INDICATOR <channel 0..3> <0..255>`, `INDICATOR LIVE`, `SYNC ON`, `SYNC OFF`, `SYNC?`, `TIME DIAG`, `ADC DIRECT`, `DIAG`, `STATS`, `RESET STATS`.

## Verification status

Automated tests cover parsing, normalized/raw Time state updates, all six pot states, switch decoding values, encoder/button/output state, selection lock, protocol handshake and recovery after malformed packets or injected GUI handler/poll errors. The only checked-in physical serial fixture is an older FP03 COM9 capture. A fresh FP05/FP06 COM9 capture and physical movement/switch checks remain required before installation recommendation. At the time this release was assembled, Windows enumerated `F:` as `RPI-RP2` (BOOTSEL) and exposed no COM9 serial port, preventing live capture. No hardware was flashed as part of this work.
