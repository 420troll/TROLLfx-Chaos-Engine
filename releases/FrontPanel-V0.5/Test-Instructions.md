# TROLLfx Front Panel Test V0.5 — DC Calibration

V0.5 replaces waveform tests with four independent static PWM outputs. At reset each channel is held at 0% signal code. Moving a slider or pressing a preset sends a new code; there is no waveform task, arming state, or EEPROM write. The setting is volatile and returns to 0% after reset.

## Stage and launch

Copy the release directory to `C:\SpellTwisterBackup\FrontPanel-V0.5\`. Install the Python dependency and run the GUI in PowerShell:

```powershell
cd C:\SpellTwisterBackup\FrontPanel-V0.5
py -m pip install -r requirements.txt
py .\FrontPanel-GUI.py
```

Connect to COM9 at 115200 baud and confirm `FP05 matched`. The DC CAL tab has four sliders, five presets per channel, signal-code and raw PWM-code readouts, and a 4×5 manual DMM measurement grid. Enter signed voltages for every output/preset, then calculate each channel's least-squares gain, zero-percent offset, polarity, maximum residual from the fitted line, percent-of-measured-span error, and R². Values are not saved by the app or firmware.

## DC signal and PWM codes

`DC channel percent` accepts channel 0–3 and integer percent 0–100. The signal code is `round(percent × 2047 / 100)`. The inverting published output stage is compensated with raw PWM code `2047 - signal code`. Telemetry reports `OUT PCT=... CODE=... DUTY=...`; DUTY is the raw code written to the RP2040 PWM peripheral. The output LEDs follow the commanded signal percentage, not a jack measurement.

The physical test report supplied for this build says the outputs appear to swing approximately −6 V to +6 V. No per-channel preset measurements were supplied, so the GUI fit is intentionally blank until DMM values are entered. **0% is not 0 V:** it is a static PWM endpoint, and the module's inverting/reference network can place the jack near one rail. Measure each jack relative to module ground with a DMM before connecting downstream equipment. Do not leave a meter in current mode across an output.

## Manual measurements and calculations

For each channel, select 0%, 25%, 50%, 75%, and 100%, wait for the reading to settle, and enter the signed DC voltage shown by the meter. The fit uses:

`V = offset + gain × (slider_percent / 100)`

Gain is reported in volts per full slider span. Positive/negative polarity follows the measured slope. Linearity error is the largest absolute residual against the least-squares line, shown in volts and as a percentage of the measured voltage span. R² is also shown. Enter at least two distinct preset points; five points are recommended for useful linearity information.

## Candidate 0–1 V network

The GUI calculates and displays the first-pass values from the published SpellTwister schematic assumptions: 3.3 V PWM, 10 kΩ summing input, 39 kΩ feedback, and −10 V reference. For a 0–1 V span, the candidate is approximately:

- Feedback resistors R52/R51/R90/R89: 39 kΩ → 3.03 kΩ.
- Reference legs R48/R101/R82/R83: 56 kΩ → 25.6 kΩ; retain series R102/R103/R84/R85 at 4.7 kΩ.
- To preserve the published filter poles, primary feedback capacitors 1 nF → about 12.87 nF and secondary 2.2 nF → about 28.32 nF.

These are ideal calculated candidates, not confirmed fitted values or instructions to modify the connected PCB. Verify its revision and component population first; measure the actual PWM high level, −10 V reference, op-amp endpoints, and all four transfer curves before considering rework. The former approximate ±6 V observation is not precise enough to replace per-channel DMM readings.

## Time control investigation

The input scan and all other control handling are unchanged from V0.4. The INPUTS tab's Time ADC diagnostic reports the stored scan reading and direct Arduino/SDK ADC readings for GPIO27/ADC1 and GPIO28/ADC2. These pins map to A1/A2 in the selected Nano RP2040 Connect variant. The standard DIAG command reports raw min/max/noise history. Compare values while turning each Time control; this release does not alter calibration or add filtering to any potentiometer.

## Serial commands

| Command | Effect |
|---|---|
| `SNAPSHOT` | Full FP05 state snapshot |
| `DC ch percent` | Set one channel's static output position, ch 0–3 and percent 0–100 |
| `DC?` | Report current percent, signal code, and raw PWM code |
| `TIME DIAG` | Compare the two scanned Time values with direct Arduino and SDK reads |
| `DIAG`, `STATS`, `RESET STATS` | Advanced input ranges and direct ADC diagnostics |
| `REPORT LIVE`, `REPORT CHANGE` | Select continuous or changed-only telemetry |
| `LED STARTUP`, `LED RGB`, `LED RING`, `LED LIVE`, `LED ONE ...` | LED diagnostics; output indicators continue tracking DC command |
| `SYNC ON`, `SYNC OFF`, `SYNC?` | Test conditioned sync inputs |

`WAVE`, `AUTO`, and waveform commands are absent. `ARM`/`DISARM` are not used; a DC command applies immediately. No firmware code accesses factory calibration storage.

## Validation limits

Build and automated tests are recorded in `manifest.json`. The firmware was compiled and the DC protocol/calculation parser tests passed. Physical V0.5 telemetry, Time movement, channel-by-channel DC readings, and resistor-network modifications still require hands-on confirmation. V0.5 is staged for multimeter testing and has not been flashed by this build step.
