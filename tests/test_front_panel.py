import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "front_panel_test"))
from telemetry import PROTOCOL_VERSION, parse_protocol_line


class FrontPanelProtocolTests(unittest.TestCase):
    def test_chaos_engine_uses_exact_upstream_pin_header(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual((root / "chaos-engine" / "pins.h").read_bytes(),
                         (root / "upstream" / "src" / "hardware" / "pins.h").read_bytes())

    def test_protocol_handshake(self):
        self.assertEqual(parse_protocol_line("PROTO=FP03"), {"type": "protocol", "version": PROTOCOL_VERSION})

    def test_control_line_keeps_normalized_values_and_switches(self):
        parsed = parse_protocol_line("A TIME=2048 SHAPE=1024 RATIO=3072 MODE=VCO SW1=0 SW2=1")
        self.assertEqual(parsed["side"], "A")
        self.assertEqual(parsed["TIME"], 2048)
        self.assertEqual(parsed["SHAPE"], 1024)
        self.assertEqual((parsed["SW1"], parsed["SW2"]), (0, 1))

    def test_encoder_and_buttons(self):
        self.assertEqual(parse_protocol_line("ENC=5 BUTTON=0 FOLLOW=1"),
                         {"type": "encoder", "position": 5, "button": 0, "follow": 1})

    def test_cv_line(self):
        parsed = parse_protocol_line("CV A_RATIO=1 A_SHAPE=2 A_MOD=3 A_EXP=4 B_RATIO=5 B_SHAPE=6 B_MOD=7 B_EXP=4095")
        self.assertEqual(parsed["B_EXP"], 4095)

    def test_output_levels_and_simulation_state(self):
        parsed = parse_protocol_line("OUT MODE=SIM METER=PEAK RELEASE=250 A_PRI=0 A_SEC=4095 B_PRI=120 B_SEC=240")
        self.assertEqual(parsed["mode"], "SIM")
        self.assertEqual((parsed["A_PRI"], parsed["A_SEC"]), (0, 4095))

    def test_invalid_value_rejected(self):
        with self.assertRaises(ValueError):
            parse_protocol_line("A TIME=4096 SHAPE=1024 RATIO=3072 MODE=VCO SW1=0 SW2=1")

    def test_legacy_json_is_not_mistaken_for_fp03(self):
        parsed = parse_protocol_line('LIVE {"seq":1,"pots":[]}')
        self.assertEqual(parsed["type"], "legacy")

    def test_real_com9_v02_packet_is_recognized_as_legacy_text(self):
        fixture = Path(__file__).parent / "fixtures" / "com9-frontpanel-v02.txt"
        captured_line = fixture.read_text(encoding="utf-8").strip()
        self.assertTrue(captured_line.startswith("LIVE {\"seq\":129"))
        self.assertEqual(parse_protocol_line(captured_line)["type"], "legacy")

    def test_real_com9_fp03_snapshot_parses_all_packet_types(self):
        fixture = Path(__file__).parent / "fixtures" / "com9-frontpanel-v03.txt"
        packets = [parse_protocol_line(line) for line in fixture.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(packets[0], {"type": "protocol", "version": PROTOCOL_VERSION})
        self.assertEqual({packet["type"] for packet in packets},
                         {"protocol", "controls", "encoder", "cv", "outputs", "moved", "state", "sync"})
        a = next(packet for packet in packets if packet.get("type") == "controls" and packet["side"] == "A")
        self.assertEqual(a["TIME"], 4089)

    def test_real_com9_simulated_output_level_is_parsed(self):
        fixture = Path(__file__).parent / "fixtures" / "com9-frontpanel-v03-output-sim.txt"
        packet = parse_protocol_line(fixture.read_text(encoding="utf-8").strip())
        self.assertEqual(packet["type"], "outputs")
        self.assertEqual(packet["mode"], "SIM")
        self.assertEqual(packet["A_PRI"], 246)
        self.assertEqual((packet["A_SEC"], packet["B_PRI"], packet["B_SEC"]), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
