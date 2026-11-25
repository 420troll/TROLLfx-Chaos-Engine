# Roadmap

## Stage 1 — hardware inventory

- [x] Locate the January UF2 in Windows Downloads and inspect it read-only.
- [x] Record WSL, Windows interop and USB visibility failures.
- [ ] Enter BOOTSEL manually; capture VID/PID, device mode, flash ID/capacity and serial/mass-storage interfaces.
- [ ] Install or use a verified USB-capable picotool build.

## Stage 2 — preserve original state and baseline

- [x] Import upstream firmware/source snapshot and preserve MIT license.
- [x] Preserve the original downloaded UF2 and SHA-256.
- [ ] Read and verify the complete installed flash, including EEPROM-emulated calibration/configuration.
- [ ] Compare installed flash to January UF2 and record differences.
- [ ] Build the unchanged original source as a baseline with the exact RP2040 Arduino core/libraries.

## Stage 3 — hardware characterization

- [x] Trace four output nets in the upstream production IPC-D-356 netlist.
- [x] Calculate initial gain, offset, and feedback-pole modifications for 0–1 V.
- [ ] Verify the actual module revision against production PCB assembly, component marks and netlist.
- [ ] Measure all four DC transfer curves, loaded bandwidth, carrier ripple, crosstalk, and sync thresholds.
- [ ] Recalculate and authorize exact component changes from measured rail/swing/load data.

## Stage 4 — Bench Lab

- [x] Create separate serial diagnostic sketch and Python GUI/calibration record utility.
- [x] Add raw PWM, DC percentages, waveforms, sweep, 6–11-bit resolution, carrier/update timing, ripple/crosstalk setup, sync monitoring, arming, and overrun accounting.
- [ ] Compile Bench Lab to UF2 with verified RP2040 platform.
- [ ] Bench-test disconnected from sensitive video gear; record calibrated transfer and timing.

## Stage 5 — Chaos Engine branch

- [x] Add four algorithm-bank DSP prototype and native bounds/determinism tests.
- [x] Create a `chaos-engine` feature branch from the imported baseline.
- [ ] Integrate algorithm-bank selection into the existing `Waveformer`, `Modulator`, encoder/LED, CV, trigger and calibration architecture.
- [ ] Port hot paths to fixed-point Q format, profile both cores, then evaluate DMA/PIO without assuming video bandwidth.
- [ ] Build a separate Chaos Engine UF2 only after Bench Lab hardware mapping and backup gates pass.

## Stage 6 — release package

- [x] Add an oscilloscope procedure; measured plots remain pending.
- [ ] Record exact physical board revision and final resistor/capacitor population.
- [ ] Store verified flash backup and its checksum securely.
- [ ] Complete handoff and rebuild steps; commit each stage to the local repository.
