# TROLLfx Front Panel Test V0.3

FP03 is a standalone hardware diagnostic based on the upstream SpellTwister pin map, ADC multiplexer layout, switch decoding, and button polarities. The test firmware and GUI do not access factory calibration EEPROM. The build does not upload or flash.

## Build and Windows GUI

```sh
ARDUINO_CLI=/home/gamer/bin/arduino-cli ./tools/build-front-panel-test.sh
```

This uses Arduino-Pico 3.9.5, `rp2040:rp2040:arduino_nano_connect`, and `flash=16777216_0` (16 MB flash, no filesystem). On Windows, install Python 3 with Tk and run:

```powershell
py -m pip install -r requirements.txt
py FrontPanel-GUI.py
```

The GUI defaults to COM9 at 115200 baud and requests a snapshot plus continuous reporting at connect. It requires the `FP03` protocol banner; it reports a protocol mismatch rather than interpreting an older firmware stream. The Live tab is designed for 800×600 and larger, with six meters arranged in two columns. Other tabs can scroll vertically.

## Control direction and upstream polarity

- Raw ADC samples are retained unchanged for the input statistics and `DIAG` command.
- Upstream `Waveformer::calc_shape()` and `calc_ratio()` subtract each raw pot reading from its calibration offset. Time/FM is likewise subtracted from the pitch path. The physical test showed clockwise turning decreased the displayed raw-based value, so FP03 maps the diagnostic pot display as `4095 - raw`. Only this normalized diagnostic value and its LED-ring index are inverted; EEPROM calibration is neither read nor changed.
- Upstream encoder direction is a calibration setting in EEPROM. FP03 does not read or write it. The observed diagnostic encoder direction was backward, so FP03 negates the live encoder count for clockwise-increasing display and ring direction.
- Upstream mode decoding is preserved: A switch pair high/low is ENV and low/high is VCO; B is wired with those states reversed. Both high or both low reports LFO. The encoder button remains active-low with pullup; Follow is active-high without an internal pullup.

## FP03 serial protocol

Normal telemetry is short, line-oriented ASCII with no timestamps, min/max or noise statistics. Example snapshot/stream lines:

```text
PROTO=FP03
A TIME=2048 SHAPE=1024 RATIO=3072 MODE=VCO SW1=0 SW2=1
B TIME=1024 SHAPE=2048 RATIO=4095 MODE=LFO SW1=1 SW2=0
ENC=5 BUTTON=0 FOLLOW=0
CV A_RATIO=1 A_SHAPE=2 A_MOD=3 A_EXP=4 B_RATIO=5 B_SHAPE=6 B_MOD=7 B_EXP=8
OUT MODE=SIM METER=INSTANT RELEASE=250 A_PRI=2048 A_SEC=0 B_PRI=1024 B_SEC=4095
MOVED=A_TIME
STATE ANALOG=0 TRIGGER=0
SYNC A=0 B=0
```

Pot values are normalized 0–4095, with clockwise increasing. `OUT MODE=SIM` means the waveform generator and indicator levels are active while PWM is disabled. `OUT MODE=PWM` reports the calculated signal levels associated with active PWM commands. These values are computed; they are not analogue jack measurements. The GUI labels the two cases distinctly.

| Command | Effect |
|---|---|
| `SNAPSHOT` | Send protocol banner and full current state, including CVs, switches, outputs and sync counters |
| `REPORT LIVE` | Stream changed/current state every 100 ms |
| `REPORT CHANGE` | Report only lines whose values changed; snapshot is sent when mode is selected |
| `DIAG` | Advanced input minimum/maximum/noise data and direct GPIO27/28 Arduino/SDK ADC comparison |
| `STATS`, `RESET STATS`, `ADC DIRECT`, `INFO`, `HELP` | Input ranges, reset ranges, direct ADC compare, firmware/arming info, command summary |
| `ARM ANALOG`, `ARM TRIG`, `ARM ALL`, `DISARM` | Independently arm or disarm analogue PWM and trigger outputs |
| `WAVE ch shape hz`, `STOP ch`, `STOP ALL` | Test channel 0–3, shape sine/triangle/ramp/square, frequency 0.5/1/2/5/10/20/50/100 Hz |
| `AUTO ON [shape hz seconds]`, `AUTO OFF` | Cycle through four outputs; arming remains explicit |
| `METER INSTANT`, `METER PEAK`, `METER RMS` | Select output indicator behavior |
| `METER RELEASE ms` | Set peak/RMS release time, 20–3000 ms; peak attack is immediate |
| `INDICATOR ch level`, `INDICATOR LIVE` | Manually override one output LED (0–3, brightness 0–255) or return to signal metering |
| `LED STARTUP`, `LED RGB`, `LED RING`, `LED LIVE`, `LED ONE pixel r g b`, `BRIGHTNESS n` | Strip tests, individual pixel (0–22), brightness (0–255) |
| `SYNC ON`, `SYNC OFF`, `SYNC?` | Count rising edges on conditioned sync inputs and query totals |

## Output indicator behavior

The four output indicator pixels are independent. A Primary and Secondary use orange; B Primary and Secondary use blue. Instant mode maps zero calculated signal to off and full scale to maximum brightness, with no minimum brightness floor. Peak mode has immediate attack and the configurable release; RMS uses the same release constant. Select PEAK for high-frequency activity that would be hard to see in instant mode. V0.3 adds 10–100 Hz wave test frequencies for that purpose.

The upstream production firmware compensates for the inverting analogue output stage by commanding inverted PWM duty (`PWM duty = top - signal code`). FP03 uses the same compensation. Indicators and GUI levels report the calculated signal after that compensation, never an independently measured voltage. PWM outputs start disarmed, and zero PWM code is not assumed to mean zero jack voltage. Manual output LED tests override the meter until `INDICATOR LIVE`.

The same PWM inversion compensation and instant/peak/RMS indicator behavior are added to the Chaos Engine prototype. Synthesis algorithms are unchanged.

## Visual and electrical test sequence

1. Keep output jacks disconnected from downstream equipment. Confirm `STATE ANALOG=0 TRIGGER=0` and output LEDs are dark when no waveform is selected in INSTANT mode.
2. Connect the GUI and confirm FP03 match, pot values, switch states, encoder/button state, and output mode arrive. Move each pot clockwise: its normalized value should increase and its physical ring position should move clockwise. Turn the encoder clockwise and verify its signed position and ring direction increase.
3. Verify the six potentiometers in the two Live meter columns. Check A/B modes while moving both switches on each side. The CV Inputs tab displays all eight mux values.
4. Run each LED test, including manual output-indicator override; use `INDICATOR LIVE` to return to the signal meter.
5. With hardware outputs disarmed, run each waveform shape on one channel at a time. Check its SIM label, output level meter and corresponding physical indicator. Try INSTANT for slow waveforms and PEAK/RMS with the higher test frequencies. Verify the other three indicators remain independent.
6. Only arm analogue or trigger outputs after confirming the connected loads are safe. Indicator brightness is computed signal level, not jack-voltage verification; analogue waveform, polarity, level and loading require suitable measurement equipment.
7. Use the Sync tab with conditioned inputs only. Incoming rising edges increment counts and flash the trigger LEDs.

## EEPROM and flash boundary

The sketch contains no EEPROM API, calibration commit, flash write, or filesystem operation. Its GPIO27/28 initialization only enables ADC access, and its normalized views do not modify the stored calibration or production state. The release manifest records the UF2 address range and checks it against the reserved 4 KiB calibration sector at `0x10FFF000–0x11000000`. This release is not flashed automatically.
