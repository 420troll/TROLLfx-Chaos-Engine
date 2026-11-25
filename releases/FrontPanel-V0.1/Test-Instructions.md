# TROLLfx Front Panel Test V0.1

This is a separate visual and input diagnostic firmware based on the upstream SpellTwister pin map, ADC multiplexers, LED strip and Nano RP2040 Connect build configuration. It does not read or write EEPROM, calibration structs, filesystem data, or flash sectors.

## Build and Windows GUI

Build without uploading:

```sh
ARDUINO_CLI=/home/gamer/bin/arduino-cli ./tools/build-front-panel-test.sh
```

This selects Arduino-Pico 3.9.5, `rp2040:rp2040:arduino_nano_connect`, and `flash=16777216_0` (16 MB flash, no filesystem). The GPIO/LED/mux definitions are copied from `upstream/src/hardware/pins.h` at build time.

On Windows, install Python 3 with Tk support, then from the release folder run:

```powershell
py -m pip install -r requirements.txt
py FrontPanel-GUI.py
```

The GUI selects COM9 by default, uses 115200 baud, and lets you choose another enumerated port. Connect to receive live readings. The `DISARM ALL` button and GUI disconnect/exit send `DISARM`.

## Safe visual sequence

1. Keep all output jacks disconnected from downstream equipment. Start with outputs disarmed. At boot the firmware sets all four PWM levels and both trigger pins low; this does **not** imply zero volts at the analogue jacks.
2. Confirm the startup LED sweep. Use `LED ONE 0 255 0 0` through `LED ONE 22 255 255 255` to illuminate each strip position; use `LED RGB`, `LED RING`, and `BRIGHTNESS 0..255` for the other LED tests. `INDICATOR ch 255` tests output indicators individually; `INDICATOR LIVE` restores activity display.
3. Turn the six potentiometers and confirm A Time/Ratio/Shape and B Time/Ratio/Shape raw values and percentages change. The GUI also displays observed minimum, maximum and range/noise since boot. Request `STATS` for one `RANGE` record per input; `RESET STATS` starts new extrema.
4. Rotate the encoder in both directions. Confirm the signed position changes, the ring marker follows, and the encoder-button state changes when pressed. Test the Follow button. Move each A/B three-position switch and confirm its two raw ADC values and decoded VCO/LFO/ENV state change.
5. Patch only safe, expected control voltages into the module CV jacks. Confirm the eight multiplexed CV meters change. `SYNC ON` counts rising edges through the module's conditioned SIG inputs; use only J6/J14 and never wire an external signal directly to GPIO17/18. Trigger LEDs flash on input edges. Use `SYNC?` to read counts.
6. Select `sine`, `triangle`, `ramp` or `square` at 0.5, 1, 2 or 5 Hz on each output. `AUTO ON [shape hz seconds]` cycles through the four outputs, which can be observed from the corresponding output indicator LEDs while analogue outputs remain disarmed.
7. The hardware test requests separate `ARM ANALOG` and `ARM TRIG` commands. Do not arm either output group unless the jacks and connected circuitry are known safe. An oscilloscope or voltmeter is still required to verify analogue jack voltage, polarity, waveform shape, trigger levels and output loading. This visual release does not establish those analog specifications.

## Upstream mapping

| Function | Upstream mapping |
|---|---|
| A/B input multiplexers | Signal GPIO26/GPIO29; select GPIO19/20/21; 8 inputs per side |
| Six potentiometers | A time GPIO27, ratio mux 0, shape mux 1; B time GPIO28, ratio mux 2, shape mux 3 |
| CVs per side | Ratio mux 3/1, shape mux 2/0, modulation mux 4, exp/pitch mux 7 |
| Mode switches | A mux 5/6; B mux 5/6; decoded using upstream side-specific wiring |
| Encoder, encoder button, Follow button | GPIO23/22, GPIO24, GPIO7 |
| Analogue outputs | GPIO13, GPIO12, GPIO1, GPIO0 |
| Trigger outputs and sync inputs | GPIO8/5 outputs; GPIO17/18 conditioned inputs |
| LED strip | 23 pixels on GPIO25; ring pixels 0–15; Follow 16; B trigger/primary/secondary 17/18/19; A secondary/primary/trigger 20/21/22 |

The firmware has no code path for SpellTwister EEPROM initialization, config reads/writes, or calibration commits. It does not alter calibration data. It requires a manual `ARM ANALOG`, `ARM TRIG`, or `ARM ALL`; LED/input diagnostics work while disarmed.
