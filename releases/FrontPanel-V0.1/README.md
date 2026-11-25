# TROLLfx Front Panel Test V0.1

Separate control/input/LED diagnostic firmware for the SpellTwister front panel.

- `FrontPanel-Test-V0.1.uf2`: diagnostic firmware for Arduino Nano RP2040 Connect, Arduino-Pico core 3.9.5, 16 MB flash/no filesystem.
- `FrontPanel-GUI.py`: Windows serial GUI, COM9 preselected.
- `requirements.txt`: Python serial dependency.
- `Test-Instructions.md`: build notes, visual checks, command map and safety boundary.
- `manifest.json` and `SHA256SUMS`: build configuration, pin mappings, UF2 flash range and hashes.

Install `pyserial` with `py -m pip install -r requirements.txt`, then run `py FrontPanel-GUI.py`. This release does not flash firmware automatically and contains no calibration-storage writes. Keep analogue and trigger outputs disarmed during input/LED testing.
