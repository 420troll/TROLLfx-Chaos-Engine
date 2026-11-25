# Build environment and reproducible firmware builds

## Verified local toolchain

- Arduino CLI 1.6.0 at `/home/gamer/bin/arduino-cli`.
- Arduino-Pico RP2040 core 3.9.5, matching the preserved January firmware strings.
- Board FQBN: `rp2040:rp2040:arduino_nano_connect` (Arduino Nano RP2040 Connect).
- Board menu: `flash=16777216_0` (16 MB flash, no filesystem). This leaves the final 4 KiB for EEPROM emulation.
- Original source libraries: Adafruit NeoPXL8 1.2.6, Adafruit NeoPixel 1.12.0, Analog-Digital Multiplexers 3.0.0, Encoder 1.4.4, OneButton 2.6.2. NeoPXL8/NeoPixel newer releases call PIO SDK functions absent from core 3.9.5. Arduino CLI installs any transitive dependencies.
- Bench Lab uses only the Arduino-Pico core and C/C++ standard libraries.

Install the platform and libraries using:

```sh
arduino-cli config add board_manager.additional_urls https://github.com/earlephilhower/arduino-pico/releases/download/global/package_rp2040_index.json
arduino-cli core install rp2040:rp2040@3.9.5
arduino-cli lib install 'Adafruit NeoPXL8@1.2.6' 'Adafruit NeoPixel@1.12.0' 'Analog-Digital Multiplexers@3.0.0' 'Encoder@1.4.4' 'OneButton@2.6.2'
```

Build both UF2s without uploading:

```sh
ARDUINO_CLI=/home/gamer/bin/arduino-cli ./tools/build-baseline.sh
ARDUINO_CLI=/home/gamer/bin/arduino-cli ./tools/build-benchlab.sh
```

Outputs: `build/original-baseline/spelltwister.ino.uf2` and `build/benchlab/benchlab.ino.uf2`. Both scripts explicitly use the 16 MB no-filesystem board option. `SPELLTWISTER_FQBN` may override the FQBN, but the flash-size option and pinout must match the selected device.

## Flash and calibration boundaries

For the configured 16 MB target, the memory map is `0x10000000` through `0x10FFFFFF`. Arduino-Pico places its EEPROM emulation sector at `0x10FFF000` through `0x10FFFFFF`. Original SpellTwister calls `EEPROM.begin/get` during startup and commits calibration/configuration only on explicit calibration/save actions. Bench Lab does not include or call EEPROM APIs.

The January original UF2 maps `0x10000000`–`0x10021400`; the locally rebuilt original baseline maps `0x10000000`–`0x10029800`; Bench Lab maps `0x10000000`–`0x10014200`. These generated payload ranges do not overlap the EEPROM sector. The separately saved full-flash backup is 16,777,216 bytes; `original.bin` and `verify.bin` matched by SHA-256 when inspected. Keep both backup copies independently of this release.

## Physical hardware state

The original 16 MiB flash backup and matching verification copy are present at `C:\SpellTwisterBackup\original.bin` and `C:\SpellTwisterBackup\verify.bin`. No release UF2 was flashed during build/release preparation. COM9, physical waveform response, output-jack rails, and the fitted module PCB revision have not been inspected in this run. Consult `BENCHLAB_TEST_INSTRUCTIONS.md` and `BENCHLAB_COMMANDS.md` before physical testing.

The firmware UF2s are compiled artifacts; use the `SHA256SUMS` and `manifest.json` alongside them to verify copies. This build configuration does not use a filesystem and keeps the 16 MB EEPROM sector outside the UF2 payload ranges.
