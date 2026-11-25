# TROLLfx Front Panel Test V0.4

This is a standalone diagnostic build for the SpellTwister panel. It starts four 1 Hz sine PWM signals during boot and keeps generating them without USB. The host GUI is optional. `STOP ALL` halts the generated waveforms for diagnostics; starting a channel resumes it.

## Build and GUI

Built with Arduino CLI 1.6.0, Arduino-Pico 3.9.5, `rp2040:rp2040:arduino_nano_connect`, and the 16 MB `flash=16777216_0` option. The used libraries are Encoder 1.4.4, Adafruit NeoPXL8 1.2.6, Adafruit NeoPixel 1.12.0, and Analog-Digital Multiplexers 3.0.0.

Install and launch the Windows GUI:

```powershell
py -m pip install -r requirements.txt
py FrontPanel-GUI.py
```

It defaults to COM9 at 115200 baud. Connect and check that the status reports `FP04 matched` and the packet counter advances. The available V0.3 COM9 capture is included as `Serial-Capture-COM9-V0.3.txt`; the GUI/parser recognizes that real capture as a protocol mismatch. No V0.4 firmware has yet been installed on the device, so physical V0.4 telemetry remains unverified.

## Hardware input scan

The four mux channel maps and GPIO/LED assignments are copied from `upstream/src/hardware/pins.h`. The scanner follows upstream `Waveformer::read_all()` order for both sides: mux channel 7 (EXP/pitch), direct Time ADC, Shape pot, Shape CV, Ratio pot, Ratio CV, modulation CV; switch channels 5 and 6 are then sampled as in upstream `get_mode()`. The installed Mux 3.0.0 implementation changes the select pins and immediately calls `analogRead()`; there is no library settling delay, and this firmware preserves that behavior. No extra settling delay or calibration transform is added to raw diagnostic samples.

Time A/B are read with `analogRead(27)` and `analogRead(28)`, corresponding to RP2040 GPIO27/28 and Nano RP2040 Connect variant aliases A1/A2. Setup selects 12-bit ADC resolution and calls `adc_gpio_init()` for both direct pins. The diagnostic `ADC DIRECT` compares Arduino reads with SDK channel 1/2 reads. Mode decoding matches upstream: A high/low is ENV and low/high is VCO; B reverses those two labels; both-high or both-low is LFO. Encoder button is active-low with pullup; Follow is active-high without an internal pullup, matching upstream initialization.

Raw pot and CV ADC readings stay unmodified in firmware. Pot displays use `4095 - raw` so clockwise movement increases the normalized display; no factory calibration values are loaded or changed. `DIAG` and `STATS` are verbose advanced reports; ordinary live telemetry excludes min/max/noise.

## Output behavior and limits

All four PWM outputs start generating 1 Hz sine waves at boot, independently of USB, serial, GUI, LED ring mode, and any arming state. A Primary/Secondary indicators are orange; B indicators are blue. The same generated waveform code feeds PWM command, calculated output level telemetry, and the indicator. The output stage is inverting, so the command uses `PWM top - signal code`. Zero calculated signal turns the indicator off; full scale uses maximum configured LED brightness. Slow signals follow instantaneous level, while 20 Hz and faster use the peak envelope in automatic meter mode. The release default is 250 ms.

These are calculated signal levels, not jack-voltage measurements. In particular, `STOP` commands a static PWM value and must not be interpreted as an electrically zero jack voltage. No oscilloscope verification is included in this release. Do not use these output tests as proof of safe voltage or load compatibility.

Manual `LED ONE` test lasts 1.8 seconds; `LED LIVE` returns the ring to live input indication. Channel output LEDs continue to follow the signal during ring animations and individual pixel tests. Button/switch feedback is drawn last so output LED updates cannot cover it.

## Serial command reference

The protocol banner is `PROTO=FP04`. A connection or `SNAPSHOT` emits A/B control lines, encoder/buttons, eight CV values, four calculated output levels, last moved control, and sync counts. Continuous telemetry is sent every 100 ms; `REPORT CHANGE` suppresses unchanged lines. `REPORT LIVE` restores continuous reports.

| Command | Result |
|---|---|
| `SNAPSHOT` | Acknowledge and send complete state snapshot |
| `REPORT LIVE` / `REPORT CHANGE` | Select 100 ms all-state or change-only reports; emits a snapshot |
| `WAVE ch shape hz` | Run channel 0–3 with sine/triangle/ramp/square at 0.5, 1, 2, 5, 10, 20, 50 or 100 Hz |
| `STOP ch` / `STOP ALL` | Stop one channel or all waveform generation |
| `AUTO ON [shape hz seconds]` / `AUTO OFF` | Cycle one active output at a time, or stop the cycle |
| `LED STARTUP`, `LED RGB`, `LED RING`, `LED LIVE` | Run LED animation or restore live ring feedback |
| `LED ONE pixel r g b` | Set a temporary pixel override (pixel 0–22, RGB 0–255) |
| `BRIGHTNESS n` | Set LED brightness 0–255 |
| `INDICATOR ch level` / `INDICATOR LIVE` | Manually set a channel indicator level or restore signal-following levels |
| `SYNC ON` / `SYNC OFF` / `SYNC?` | Count rising edges on the conditioned sync inputs, stop counting, or query totals |
| `DIAG` | Acknowledge then print raw input ranges and direct GPIO27/28 Arduino/SDK comparison |
| `STATS` / `RESET STATS` | Print or reset input min/max/noise measurements |
| `ADC DIRECT` | Print the direct GPIO27/28 Arduino and SDK reads |
| `METER INSTANT` / `METER PEAK` / `METER RMS` | Select indicator behavior; automatic mode uses instant below 20 Hz and peak at/above 20 Hz |
| `METER RELEASE ms` | Set peak/RMS release to 20–3000 ms |
| `INFO` / `HELP` | Print build state or command summary |

The old `ARM` and `DISARM` commands are rejected with an explanation; outputs are continuous. No firmware command accesses EEPROM or factory calibration storage.

## Validation status

- Automated parser/source checks: see build manifest and `python3 -m unittest discover -s tests -v`.
- Python syntax: `python3 -m py_compile FrontPanel-GUI.py telemetry.py`.
- Build: see manifest for exact UF2 range, checksum, and EEPROM-sector comparison.
- Physical V0.4 control scan, output indicators, USB disconnect/reconnect, and serial acknowledgements: pending installation and hands-on observation. The V0.3 capture is protocol compatibility evidence only.
