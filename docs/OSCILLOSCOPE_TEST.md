# Oscilloscope and calibration procedure

This procedure assumes the board has already been backed up and Bench Lab UF2 installation has been explicitly approved. Keep the module out of any video-chain input while testing.

## Equipment and setup

- Bench supply through the module's normal Eurorack power connector, with current limit appropriate to the unit.
- 4-channel oscilloscope, 10× probes, and a frequency counter or scope timebase.
- DMM, function generator with current limiting, short patch cables.
- Record module PCB revision, firmware hash, temperature, load resistance/capacitance, PWM resolution and carrier.

Connect scope ground to module ground. Use high-impedance probes first. Measure the four jacks individually: A Primary J12, A Secondary J11, B Primary J20, B Secondary J19. Do not connect the outputs to a video device until voltage bounds are established.

## Bench Lab sequence

1. Connect USB serial and issue `INFO`. Confirm outputs report disarmed. Leave them disarmed while probing or changing settings.
2. Arm outputs and set 11-bit resolution, 44.1 kHz PWM carrier. For each channel, command `DC channel 0`, `25`, `50`, `75`, and `100`; record actual mean voltage, p-p ripple and settling. Disarm between channels.
3. Repeat at 6, 8 and 10 bits. Record measured carrier and measured waveform update rate from `INFO`, plus overrun count.
4. At 50% DC, use `RIPPLE channel`; capture p-p ripple and spectrum. Measure with the normal load and then a 100 kΩ load. Do not use an unknown low-resistance load.
5. Use `CROSSTALK aggressor` on each channel in turn. Capture the inactive-channel peak and p-p noise with identical probe positions and grounding.
6. Run sine, triangle, saw, square, stair and ramp at 1 Hz, 100 Hz, 1 kHz and the highest stable test frequency. Verify amplitude and frequency at each jack; note the analog roll-off and distortion.
7. Run low-to-high and high-to-low frequency sweeps. Watch `INFO` for update overruns and record the highest clean output frequency.
8. For sync characterization, connect the current-limited generator only to J6 or J14 (SIG_CV), with common ground. Start at 0–3.3 V, then slowly vary amplitude and polarity while observing the conditioned GPIO-equivalent signal and trigger count. Do not connect to the RP2040 GPIO pad directly.
9. Enter the five measured DC points, ripple and crosstalk into the Python utility and save its CSV calibration record. Repeat after any analog component change.

## Hardware modification verification

After an approved rework, repeat the five DC points on all four channels. For the calculated 0–1 V candidate, the target is approximately 0 V at the low endpoint and 1.0 V at the high endpoint, with monotonic 11-bit steps. Verify no op-amp rail clipping, check the REF−10 offset contribution, and repeat loaded bandwidth/ripple measurements before connecting video gear.

The published feedback poles are about 4.08 kHz primary and 1.85 kHz secondary; these are expected filter limits, not video bandwidth. A useful video-bandwidth prototype needs a changed converter/output architecture. Do not infer bandwidth from a clean DC calibration.
