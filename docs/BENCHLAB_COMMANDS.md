# Bench Lab V0.1 serial command reference

Serial settings: **115200 baud, 8 data bits, no parity, 1 stop bit**. Send one ASCII command per line. Commands and waveform names are uppercase/lowercase sensitive as shown. Channels are `0` A Primary (GPIO13), `1` A Secondary (GPIO12), `2` B Primary (GPIO1), and `3` B Secondary (GPIO0).

## Startup and output safety

At reset all four stored output codes are initialized to zero and the PWM pins are driven low. The firmware reports `TROLLfx Bench Lab READY; outputs DISARMED`; it does not arm outputs unless it receives `ARM`. `ARM` applies the stored codes to all four channels. `DISARM` forces all four outputs to zero immediately. Disconnecting or closing the Python GUI sends `DISARM` before closing the serial port. Reset returns to the disarmed startup state.

`STOP` stops waveform updates but holds the last output code. It does **not** disarm the outputs. `DISARM` is the command that guarantees the PWM levels are zero. Re-arming restores the stored raw codes, so use `DISARM` before changing test leads or loads.

## Commands

| Command | Purpose / limits |
|---|---|
| `HELP` | Print command summary. |
| `INFO` | Report arm state, resolution, PWM top, requested/actual carrier, requested/target/measured update rate, update count and overruns. |
| `ARM` | Explicitly enable all four outputs at their stored codes. |
| `DISARM` | Set all four PWM levels to zero; stored codes remain available for later arm. |
| `RES bits` | Set PWM resolution to 6–11 bits. PWM top becomes `2^bits-1`; codes must be in this range. Outputs must be disarmed first. |
| `CARRIER hz` | Set requested PWM carrier (minimum request 100 Hz). Outputs must be disarmed first. Hardware divider limits can make the reported actual rate differ; check `INFO`. |
| `UPDATE hz` | Set waveform update rate to 1–50000 updates/s. A running waveform or sweep must fit at or below half the requested update rate; otherwise the command is rejected. |
| `RAW ch code` | Hold one channel at an integer PWM code from 0 through current PWM top. Stops the selected waveform. |
| `DC ch percent` | Hold one channel at 0–100 percent of current PWM top. Stops the selected waveform. |
| `WAVE ch shape hz [lowCode highCode]` | Generate `sine`, `triangle`, `saw`, `square`, `stair`, or `ramp`; frequency must be positive and no greater than half the current update rate. Optional low/high codes must be ordered and within the current PWM range. Defaults are 0 and PWM top. |
| `SWEEP ch startHz stopHz durationMs` | Logarithmic sine sweep between positive endpoints for a positive duration. Both frequencies must be no greater than half the update rate. |
| `STOP ch` | Stop waveform updates for one channel and hold its most recent PWM code. `ch` is 0–3. |
| `STOP ALL` | Stop updates on all channels and hold their most recent codes. Outputs remain armed if they were armed. |
| `RIPPLE ch` | Stop waveform on the selected channel and set it to midscale DC, allowing measurement of PWM-carrier ripple after the module output stage. |
| `CROSSTALK ch` | Set the selected channel to full scale and all other channels to zero. |
| `SYNC ON` | Count rising edges on the module's conditioned SIG inputs at GPIO17/18. Use only the module's conditioned inputs (J6/J14); do not connect raw external signals directly to GPIO. |
| `SYNC OFF` | Disable the sync interrupts. |
| `SYNC?` | Report the A/B edge counts and last edge timestamps in microseconds since boot. Counts are cumulative until reset. |

The output stage on the published module design inverts and scales PWM into a bipolar jack voltage. PWM `RAW`/`DC` values are not direct jack-voltage calibration values. Confirm voltage and polarity on a scope/DMM with a high-impedance load before connecting downstream equipment.

## Waveform definitions

`sine` is a 0-to-full-scale sine; `triangle` rises and falls linearly; `saw` and `ramp` both rise linearly then wrap; `square` is half-cycle low then high; `stair` is a 16-step rising staircase. Optional low/high PWM codes map the waveform into a restricted code range. All waveform output is sampled at the configured update rate, so frequencies above update-rate/2 are rejected; analog output-stage filtering further limits measured bandwidth.
