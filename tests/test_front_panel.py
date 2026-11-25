import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "front_panel_test"))
from telemetry import PROTOCOL_VERSION, parse_protocol_line
from calibration import fit_transfer, candidate_network


class FrontPanelProtocolTests(unittest.TestCase):
    def test_fp05_snapshot_packets(self):
        sample = (
            "PROTO=FP05",
            "A TIME=2048 SHAPE=1024 RATIO=3072 MODE=ENV SW1=1 SW2=0",
            "B TIME=1234 SHAPE=3456 RATIO=2345 MODE=VCO SW1=1 SW2=0",
            "ENC=5 BTN=0 FOLLOW=1",
            "CV=1,2,3,4,5,6,7,4095",
            "OUT PCT=0,25,50,100 CODE=0,512,1024,2047 DUTY=2047,1535,1023,0",
            "TIMERAW=120,3400", "TIME A_GPIO=27 A_SCAN=120 A_ARDUINO=121 A_SDK=122 B_GPIO=28 B_SCAN=3400 B_ARDUINO=3399 B_SDK=3400",
            "MOVED=A_TIME", "SYNC=12,8", "OK DC channel=0 percent=25 code=512 duty=1535", "ERR invalid command",
        )
        packets = [parse_protocol_line(line) for line in sample]
        self.assertEqual(packets[0], {"type": "protocol", "version": "FP05"})
        self.assertNotEqual(packets[0]["version"], PROTOCOL_VERSION)
        self.assertEqual(packets[1]["MODE"], "ENV")
        self.assertEqual(packets[3]["button"], 0)
        self.assertEqual(packets[4]["values"], [1, 2, 3, 4, 5, 6, 7, 4095])
        self.assertEqual(packets[5]["percent"], [0, 25, 50, 100])
        self.assertEqual(packets[5]["codes"], [0, 512, 1024, 2047])
        self.assertEqual(packets[6], {"type": "timeraw", "a": 120, "b": 3400})
        self.assertEqual(packets[7]["type"], "timediag")
        self.assertEqual(packets[9], {"type": "sync", "a": 12, "b": 8})
        self.assertEqual(packets[10]["type"], "ack")
        self.assertEqual(packets[11]["type"], "error")

    def test_bad_packets_count_as_parse_errors(self):
        for line in ("A TIME=4096 SHAPE=1 RATIO=2 MODE=ENV SW1=0 SW2=0",
                     "ENC=0 BTN=2 FOLLOW=0", "CV=1,2", "OUT PCT=0,25 CODE=0 DUTY=2047"):
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
        self.assertNotIn("updateWaves", source)
        self.assertNotIn("setWave(", source)
        self.assertIn("setOutputPercent(i,0)", source)
        self.assertIn("pwm_set_gpio_level(kOutputPins[channel], (uint16_t)(kPwmTop - outputCode[channel]))", source)

    def test_calibration_fit_and_candidate_network(self):
        fit = fit_transfer([(0,-6),(25,-3),(50,0),(75,3),(100,6)])
        self.assertAlmostEqual(fit["gain_v_per_100pct"], 12.0)
        self.assertAlmostEqual(fit["offset_v"], -6.0)
        self.assertEqual(fit["polarity"], "positive")
        self.assertAlmostEqual(fit["max_linearity_error_v"], 0.0)
        network = candidate_network()
        self.assertAlmostEqual(network["feedback_ohms"], 3030.303, places=2)
        self.assertAlmostEqual(network["reference_upper_ohms"], 25603.03, places=1)

    def test_calibration_fit_rejects_too_few_or_nonfinite_values(self):
        with self.assertRaises(ValueError): fit_transfer([(50, 2.5)])
        with self.assertRaises(ValueError): fit_transfer([(0, 0), (100, float("nan"))])


if __name__ == "__main__":
    unittest.main()
