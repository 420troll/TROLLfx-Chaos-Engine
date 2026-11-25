"""Canonical host-side model for Front Panel Test control telemetry."""
from dataclasses import dataclass


CONTROL_META = (
    ("A_TIME", "A", "pot"), ("A_SLOPE", "A", "pot"), ("A_RATIO", "A", "pot"),
    ("B_TIME", "B", "pot"), ("B_SLOPE", "B", "pot"), ("B_RATIO", "B", "pot"),
    ("A_RATIO_CV", "A", "cv"), ("A_SLOPE_CV", "A", "cv"), ("A_MOD_CV", "A", "cv"), ("A_EXP_CV", "A", "cv"),
    ("B_RATIO_CV", "B", "cv"), ("B_SLOPE_CV", "B", "cv"), ("B_MOD_CV", "B", "cv"), ("B_EXP_CV", "B", "cv"),
    ("A_SW1", "A", "switch"), ("A_SW2", "A", "switch"), ("B_SW1", "B", "switch"), ("B_SW2", "B", "switch"),
)
POT_IDS = tuple(item[0] for item in CONTROL_META[:6])
OUTPUT_IDS = ("A_PRIMARY", "A_SECONDARY", "B_PRIMARY", "B_SECONDARY")


@dataclass
class ControlValue:
    control_id: str
    side: str
    kind: str
    raw: int | None = None
    value: int | None = None


class PanelState:
    def __init__(self):
        self.controls = {ident: ControlValue(ident, side, kind) for ident, side, kind in CONTROL_META}
        self.modes = {"A": "UNKNOWN", "B": "UNKNOWN"}
        self.switch_raw = {"A": (None, None), "B": (None, None)}
        self.encoder = 0
        self.encoder_button = False
        self.follow_button = False
        self.outputs = {ident: {"percent": 0, "signal_code": 0, "pwm_code": 2047, "voltage": None}
                        for ident in OUTPUT_IDS}
        self.active_id = "A_TIME"
        self.active_locked = False
        self.firmware_protocol = None
        self.last_valid_packet = None
        self.packet_count = 0
        self.parse_errors = 0
        self.last_error = ""
        self.sync = (0, 0)

    def select_control(self, control_id, lock=False):
        if control_id not in self.controls and control_id not in ("ENCODER", "ENCODER_BUTTON", "FOLLOW_BUTTON"):
            raise KeyError(control_id)
        self.active_id = control_id
        self.active_locked = bool(lock)

    def unlock_control(self):
        self.active_locked = False

    def accept(self, packet, now=None):
        """Apply one parsed packet. Returns False for unsupported packet types."""
        kind = packet["type"]
        if kind == "protocol":
            self.firmware_protocol = packet["version"]
            return True
        if kind == "controls":
            side = packet["side"]
            aliases = (("TIME", "TIME"), ("SLOPE", "SLOPE"), ("RATIO", "RATIO"))
            for field, control_name in aliases:
                raw = packet.get(f"{field}_RAW", packet.get(f"{field}_raw"))
                value = packet[field]
                if raw is None:  # FP05 compatibility used normalized-only control values.
                    raw = value if field not in ("TIME", "SLOPE", "RATIO") else 4095 - value
                self.controls[f"{side}_{control_name}"].raw = raw
                self.controls[f"{side}_{control_name}"].value = value
            if "MODE" in packet:
                self.modes[side] = packet["MODE"]
            if "SW1_RAW" in packet and "SW2_RAW" in packet:
                self.switch_raw[side] = (packet["SW1_RAW"], packet["SW2_RAW"])
            return True
        if kind == "control":
            item = self.controls[packet["id"]]
            item.raw, item.value = packet["raw"], packet["value"]
            return True
        if kind == "switch":
            self.modes[packet["side"]] = packet["mode"]
            self.switch_raw[packet["side"]] = (packet["sw1_raw"], packet["sw2_raw"])
            return True
        if kind == "cv":
            for meta, raw in zip(CONTROL_META[6:14], packet["values"]):
                self.controls[meta[0]].raw = raw
                self.controls[meta[0]].value = raw
            return True
        if kind == "encoder":
            self.encoder = packet["position"]
            self.encoder_button = bool(packet["button"])
            self.follow_button = bool(packet["follow"])
            return True
        if kind == "encoder_position":
            self.encoder = packet["position"]
            return True
        if kind == "button":
            if packet["name"] == "ENCODER": self.encoder_button = packet["pressed"]
            if packet["name"] == "FOLLOW": self.follow_button = packet["pressed"]
            return True
        if kind == "outputs":
            for ident, pct, signal, pwm in zip(OUTPUT_IDS, packet["percent"], packet["codes"], packet["duty"]):
                self.outputs[ident].update(percent=pct, signal_code=signal, pwm_code=pwm)
            return True
        if kind == "voltage":
            if packet["channel"] in self.outputs:
                self.outputs[packet["channel"]]["voltage"] = packet["volts"]
            return True
        if kind == "timeraw":
            # Raw Time fields are authoritative raw readings and update the same controls as CTRL packets.
            self.controls["A_TIME"].raw = packet["a"]
            self.controls["B_TIME"].raw = packet["b"]
            return True
        if kind == "moved":
            if not self.active_locked and packet["name"] in self.controls:
                self.active_id = packet["name"]
            elif not self.active_locked and packet["name"] in ("ENCODER", "ENCODER_BUTTON", "FOLLOW_BUTTON"):
                self.active_id = packet["name"]
            return True
        if kind == "sync":
            self.sync = (packet["a"], packet["b"])
            return True
        if kind in ("ack", "error", "timediag", "text", "legacy", "handshake"):
            return True
        return False

    def projection(self):
        """Widget-ready values; raw and normalized control readings stay distinct."""
        return {
            "controls": {key: {"raw": item.raw, "value": item.value, "side": item.side, "kind": item.kind}
                         for key, item in self.controls.items()},
            "modes": dict(self.modes), "switch_raw": dict(self.switch_raw),
            "active_id": self.active_id, "active_locked": self.active_locked,
            "encoder": self.encoder, "encoder_button": self.encoder_button,
            "follow_button": self.follow_button,
            "outputs": {key: dict(value) for key, value in self.outputs.items()},
            "sync": self.sync,
        }
