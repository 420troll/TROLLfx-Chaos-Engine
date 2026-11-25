# TROLLfx Bench Lab V0.1

Release package for supervised physical characterization of the TROLLfx SpellTwister module.

Contents:

- `BenchLab-V0.1.uf2`: diagnostic firmware, built for Arduino Nano RP2040 Connect with 16 MB flash/no filesystem.
- `SpellTwister-Baseline-Core3.9.5.uf2`: rebuilt original firmware baseline for comparison/recovery reference. It is not the diagnostic test image.
- `BenchLab-GUI.py` and `requirements.txt`: Windows COM9 control and host-side measurement log.
- `Serial-Command-Reference.md`: complete command syntax and behavior.
- `Test-Instructions.md`: startup, scope and test procedure.
- `manifest.json` and `SHA256SUMS`: build properties, UF2 address ranges and file checksums.

On Windows, install Python 3 with Tk support, run `py -m pip install -r requirements.txt`, then launch with `py BenchLab-GUI.py`. COM9 is preselected; select the module's actual COM port if Windows assigns a different one.

No firmware is flashed by this package. Read the test instructions and confirm the physical module revision before installation. Keep the verified full-flash backup separate from these release files. Bench Lab outputs start disarmed; always measure the output jacks before connecting other equipment.
