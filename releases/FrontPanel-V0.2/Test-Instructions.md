# TROLLfx Front Panel Test V0.2

This diagnostic firmware is based on the SpellTwister upstream hardware initialization, pin assignments, LED strip, ADC multiplexers and encoder polarity. It is a separate sketch and does not read or write calibration EEPROM, config structs, filesystems or flash sectors. Analogue and trigger outputs start disarmed.

## Build and GUI

Build only; this script does not upload or flash:

```sh
ARDUINO_CLI=/home/gamer/bin/arduino-cli ./tools/build-front-panel-test.sh
```

The build uses Arduino-Pico 3.9.5, `rp2040:rp2040:arduino_nano_connect`, and `flash=16777216_0` (16 MB flash, no filesystem). Upstream `pins.h` is copied before compilation. The Windows GUI uses Python 3 with Tk support and pyserial:

```powershell
py -m pip install -r requirements.txt
py FrontPanel-GUI.py
```

The GUI starts at 800×600, defaults to COM9 and 115200 baud, can be resized, and has seven scrollable tabs. It sends `DISARM` on disconnect or close.

## Visual test sequence

1. Keep output jacks disconnected from downstream equipment. Start with outputs disarmed. At boot the firmware sets all four PWM levels to code 0 and both trigger pins low. This is a digital state only; **do not assume code 0 means zero volts at a jack**.
2. Confirm the startup ring animation. In **LED tests**, run RGB cycle, ring chase, each individual pixel 0–22, brightness and each of the four output indicators. Return to `LED LIVE` when finished.
3. In **Live activity**, slowly move each pot, then verify the large control name/value follows the last moving control. Noise rejection uses a 14-count GUI threshold and the firmware uses a 24-count movement threshold. Lock selection to keep watching one control. Check raw ADC, percentage, observed min/max, trend history, detection state and ring location/color. A pots are orange, B pots blue, CV inputs have individual colors, encoder position is purple.
4. In **All inputs**, move all six pots and inspect all eight mux CVs, all four mux switch readings, raw counts, percentages, observed limits and noise span. Exercise A/B switches and check decoded modes. Movement in either mode switch produces a brief white flash on its associated output indicator LED.
5. Move the encoder both directions and press its button; press Follow. Encoder/button states and signed position appear in **Encoder and buttons**. Button presses briefly flash the Follow pixel. The encoder uses pullups and active-low button detection; Follow uses an external active-high signal, matching upstream.
6. Inspect **Sync** with the module’s conditioned sync inputs only (GPIO17/18). Enable edge counting and confirm counts/trigger indicator flashes. Do not connect unconditioned external signals directly to those GPIOs.
7. Use `ADC DIRECT` in **Serial diagnostics** to compare `analogRead()` and raw RP2040 SDK conversion results on GPIO27/ADC1 and GPIO28/ADC2. Watch GPIO27's Arduino and SDK values while turning A Time. Both reads are consecutive samples of the same ADC input, so small count differences are expected. The board variant defines `A0=GPIO26` through `A3=GPIO29`; Arduino-Pico `analogRead(pin)` treats the supplied pin as the physical GPIO and selects ADC channel `pin-26`. This confirms the expected mapping but does not establish the physical pot wiring or prove the A Time circuit is healthy. If both values remain fixed, check the hardware path before concluding the pot is defective.
8. In **Waveform outputs**, choose sine, triangle, ramp or square at 0.5, 1, 2 or 5 Hz. The four animated preview traces are calculated in the GUI and remain active while hardware outputs are disarmed. Firmware output indicators also show the selected/generated digital value. Test automatic channel cycling while disarmed first.
9. Analogue and trigger outputs arm separately with explicit confirmation. Only arm after the jack and connected circuitry are known safe. A visual test cannot verify jack voltage, polarity, waveform quality, trigger level or load behaviour; use suitable analogue measurement equipment for those checks.

## Serial protocol summary

Commands are newline terminated and case sensitive. `HELP` on the device prints command syntax. The GUI has shortcuts for the commonly used commands and a raw command entry.

| Command | Effect |
|---|---|
| `HELP`, `INFO`, `STATS`, `RESET STATS` | Show syntax/state, input min/max/noise, or reset input extrema |
| `ADC DIRECT` | Compare Arduino and raw SDK ADC conversions on GPIO27 and GPIO28 |
| `ARM ANALOG`, `ARM TRIG`, `ARM ALL`, `DISARM` | Separately enable or disable PWM and trigger outputs |
| `WAVE ch shape hz`, `STOP ch`, `STOP ALL` | Select or stop channel 0–3; shape is sine/triangle/ramp/square; hz is 0.5/1/2/5 |
| `AUTO ON [shape hz seconds]`, `AUTO OFF` | Cycle output channels; seconds is 1–30; arming remains independent |
| `LED STARTUP`, `LED RGB`, `LED RING`, `LED LIVE` | Run LED diagnostic modes or return to activity mode |
| `LED ONE pixel r g b`, `BRIGHTNESS value` | Set pixel 0–22 RGB or strip brightness 0–255 |
| `INDICATOR ch value`, `INDICATOR LIVE` | Test output indicator channel 0–3 or restore live output indication |
| `SYNC ON`, `SYNC OFF`, `SYNC?` | Count conditioned sync input edges and query totals |

`LIVE` JSON packets carry monotonic sequence numbers, input records, physical encoder and buttons, switch modes, sync counts, ring selection, arming state, direct ADC comparisons and digital waveform values. The GUI reports received packets, missing sequence numbers, malformed JSON count and time since last valid packet.

## Hardware mapping and calibration protection

Pin values below are physical RP2040 GPIO numbers from `upstream/src/hardware/pins.h`.

| Function | GPIO / mux assignment |
|---|---|
| A/B mux analog signals | GPIO26 / GPIO29; shared select GPIO19, GPIO20, GPIO21 |
| A/B Time | GPIO27 (ADC1) / GPIO28 (ADC2) |
| Ratio/Shape pots | A mux 0/1; B mux 2/3 |
| Ratio/Shape/Mod/Exp CV | A mux 3/2/4/7; B mux 1/0/4/7 |
| A/B mode switches | Mux 5/6 on each side |
| Encoder phases / button / Follow | GPIO23/22, GPIO24 active-low, GPIO7 active-high |
| Analogue outputs | GPIO13, GPIO12, GPIO1, GPIO0 |
| Trigger outputs / conditioned sync inputs | GPIO8/5; GPIO17/18 |
| LED strip | GPIO25, 23 pixels; ring 0–15, Follow 16, B trigger/primary/secondary 17–19, A secondary/primary/trigger 20–22 |

The installed Arduino-Pico 3.9.5 board variant sets `A0` to 26 and `A3` to 29; core `analogRead()` validates that range, initializes the corresponding ADC GPIO and selects channel `pin - 26`. `analogReadResolution(12)` is set at boot. The firmware does not call EEPROM APIs or any flash write/filesystem functions, and the UF2 range is checked against the reserved EEPROM sector when packaged. No hardware is flashed by the build or release process.
