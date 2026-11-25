# Bench Lab V0.1 physical test instructions

## Before installing firmware

1. Confirm the board is the Arduino Nano RP2040 Connect (16 MB flash) and that the installed module PCB revision matches the published SpellTwister output schematic. Record both revisions.
2. Keep the verified full-flash backup (`original.bin`, 16,777,216 bytes) in two safe locations. Its matching verification copy had the same SHA-256 at preparation time. Verify the release manifest hashes before using a UF2.
3. Use Bench Lab UF2 only for this test. Do not use the original baseline UF2 as a test image. This release was not flashed or tested on physical hardware during preparation.
4. Disconnect external video gear. Power the module from its normal Eurorack supply with a current limit suitable for the unit. Connect oscilloscope ground to module ground and use 10×, high-impedance probes initially.

## Connect and confirm safe startup

1. Start `BenchLab-GUI.py` on Windows with Python 3 and `pyserial` installed (`py -m pip install -r requirements.txt`). Select **COM9** and connect at 115200 baud.
2. The firmware resets on USB serial open on some hosts. Wait for `TROLLfx Bench Lab READY; outputs DISARMED`; request `INFO` and confirm `armed=0`. If this line never appears, disconnect and check the selected COM port/driver before trying output commands.
3. Probe all four module output jacks with the outputs disarmed. Confirm no unexpected voltage before arming.
4. Press `ARM outputs` only after confirming the probes and loads. The GUI asks for confirmation. Startup codes are zero, but that does not imply zero volts at the inverting analog outputs; measure them.

## Characterization sequence

1. Select channel 0–3 and use `DC` at 0, 25, 50, 75 and 100 percent. Record DMM mean voltage and scope peak-to-peak ripple for each point in the GUI's manual calibration log. This CSV records measurements on the host; it does not calibrate or write device storage.
2. Repeat for A Primary J12 (GPIO13), A Secondary J11 (GPIO12), B Primary J20 (GPIO1), B Secondary J19 (GPIO0). Compare monotonicity, endpoints, settling and noise.
3. Before changing resolution or carrier, send `DISARM`; set `RES`/`CARRIER`, check `INFO`, and explicitly arm again. Repeat measurements at 6, 8 and 10 bits. Record actual carrier, measured update rate and overrun count.
4. Use `RIPPLE ch` at midscale and measure carrier ripple. Use `CROSSTALK ch` to drive one channel full scale while probing the other three.
5. Test `sine`, `triangle`, `saw`, `square`, `stair`, and `ramp` at conservative frequencies below `UPDATE/2`. Run `INFO` and record actual carrier, measured update rate and overrun count. The published analog feedback poles are approximately 4.08 kHz on primary and 1.85 kHz on secondary; expect substantial roll-off above those frequencies.
6. Try a low-to-high and high-to-low `SWEEP` within the update-rate limit. Record the highest clean measured frequency and any aliasing/overruns.
7. For `SYNC`, use only the module conditioned SIG inputs J6/J14 and begin with a current-limited 0–3.3 V source. Never connect modular-level external signals directly to GPIO17/18. Record edge counts with `SYNC?`.
8. Send `DISARM` before moving probes, loads, or patch leads. Save the GUI CSV, then disconnect; the GUI also sends `DISARM` on disconnect and exit.

## Storage and recovery

Bench Lab contains no `EEPROM` include, read/write calls, flash-sector erase calls, or filesystem writes. Its image maps only the low application region beginning at `0x10000000` and ends at `0x10014200`, far from the Arduino-Pico EEPROM emulation sector at `0x10FFF000` (the last 4 KiB of the 16 MiB device). This supports preservation of SpellTwister's EEPROM calibration during a normal UF2 write; it is not a substitute for the full-flash backup. A module PCB/flash variant mismatch remains possible until physically inspected.

To restore, enter BOOTSEL manually and use the verified original full-flash backup only after confirming the target device. No automatic flashing is performed by the GUI or release scripts.
