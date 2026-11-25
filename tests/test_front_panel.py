import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "front_panel_test"))
from telemetry import parse_live_line


class FrontPanelTelemetryTests(unittest.TestCase):
    def test_valid_live_packet(self):
        packet = parse_live_line('LIVE {"seq":7,"pots":[],"cvs":[],"switches":[]}')
        self.assertEqual(packet["seq"], 7)

    def test_malformed_json_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "malformed"):
            parse_live_line('LIVE {"seq":1,')

    def test_missing_required_array_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "cvs"):
            parse_live_line('LIVE {"seq":1,"pots":[],"switches":[]}')

    def test_non_live_line_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not a LIVE"):
            parse_live_line("OK analog=DISARMED")


if __name__ == "__main__":
    unittest.main()
