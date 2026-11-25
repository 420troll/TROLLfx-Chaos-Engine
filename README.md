# TROLLfx Chaos Engine

Development workspace built on the MIT-licensed SpellTwister RP2040 source. The original application is kept as an unchanged snapshot under `upstream/`; Bench Lab is a separate Arduino-Pico build target; Chaos Engine DSP is an experimental separate target. See [HANDOFF](docs/HANDOFF.md), [hardware analysis](docs/OUTPUT_ANALYSIS.md), and [build environment](docs/BUILD_ENVIRONMENT.md).

Bench Lab V0.1 release files and physical test procedures are documented in [the command reference](docs/BENCHLAB_COMMANDS.md) and [test instructions](docs/BENCHLAB_TEST_INSTRUCTIONS.md). Compiled UF2s, hashes, and build manifest are packaged in `releases/BenchLab-V0.1/`.

The separate Front Panel Test V0.1 branch provides visual LED, switch, encoder, potentiometer, mux/CV and sync diagnostics without reading or writing EEPROM calibration. See `docs/FRONT_PANEL_TEST_INSTRUCTIONS.md` and `releases/FrontPanel-V0.1/`.

Do not flash a target until its complete installed flash has been read and verified. The January UF2 is a preserved download, not a live device backup.
