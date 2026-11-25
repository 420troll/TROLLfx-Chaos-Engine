import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "front_panel_test"))
from telemetry import PROTOCOL_VERSION, parse_protocol_line


class FrontPanelProtocolTests(unittest.TestCase):
    def test_fp04_snapshot_packets(self):
        sample = (
            "PROTO=FP04",
            "A TIME=2048 SHAPE=1024 RATIO=3072 MODE=ENV SW1=1 SW2=0",
            "B TIME=1234 SHAPE=3456 RATIO=2345 MODE=VCO SW1=1 SW2=0",
            "ENC=5 BTN=0 FOLLOW=1",
            "CV=1,2,3,4,5,6,7,4095",
            "OUT MODE=PWM METER=AUTO RELEASE=250 120,240,180,90",
            "MOVED=A_TIME", "SYNC=12,8", "OK wave running", "ERR invalid command",
        )
        packets = [parse_protocol_line(line) for line in sample]
        self.assertEqual(packets[0], {"type": "protocol", "version": PROTOCOL_VERSION})
        self.assertEqual(packets[1]["MODE"], "ENV")
        self.assertEqual(packets[3]["button"], 0)
        self.assertEqual(packets[4]["values"], [1, 2, 3, 4, 5, 6, 7, 4095])
        self.assertEqual(packets[5]["values"], [120, 240, 180, 90])
        self.assertEqual(packets[7], {"type": "sync", "a": 12, "b": 8})
        self.assertEqual(packets[8]["type"], "ack")
        self.assertEqual(packets[9]["type"], "error")

    def test_bad_packets_count_as_parse_errors(self):
        for line in ("A TIME=4096 SHAPE=1 RATIO=2 MODE=ENV SW1=0 SW2=0",
                     "ENC=0 BTN=2 FOLLOW=0", "CV=1,2", "OUT MODE=PWM 1,2,3"):
            with self.subTest(line=line), self.assertRaises(ValueError):
                parse_protocol_line(line)

    def test_real_com9_v03_is_identified_as_legacy(self):
        fixture = ROOT / "tests/fixtures/com9-frontpanel-v03.txt"
        lines = fixture.read_text(encoding="utf-8").splitlines()
        packets = [parse_protocol_line(line) for line in lines]
        self.assertEqual(packets[0], {"type": "protocol", "version": "FP03"})
        self.assertNotEqual(packets[0]["version"], PROTOCOL_VERSION)
        self.assertEqual(packets[1]["type"], "controls")
        self.assertEqual(packets[3]["type"], "legacy")
        self.assertEqual(packets[5]["type"], "legacy")

    def test_exact_upstream_pin_header_and_no_calibration_storage(self):
        upstream = ROOT / "upstream/src/hardware/pins.h"
        self.assertEqual((ROOT / "front_panel_test/pins.h").read_bytes(), upstream.read_bytes())
        source = (ROOT / "front_panel_test/front_panel_test.ino").read_text(encoding="utf-8")
        self.assertNotIn("EEPROM.READ", source.upper())
        self.assertNotIn("EEPROM.WRITE", source.upper())
        self.assertNotIn("NVM", source.upper())
        self.assertNotIn("analogArmed", source)
        self.assertNotIn("triggerArmed", source)
        self.assertIn("for(uint8_t i=0;i<kChannelCount;++i) setWave(i,WAVE_SINE,1.0f)", source)
        self.assertIn("pwm_set_gpio_level(kOutputPins[i], pwmCommand)", source)


if __name__ == "__main__":
    unittest.main()
