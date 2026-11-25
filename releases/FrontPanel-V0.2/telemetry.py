"""Small, UI-independent parser for Front Panel Test LIVE telemetry."""
import json


def parse_live_line(line):
    """Return a LIVE JSON object, or raise ValueError for an invalid packet."""
    if not isinstance(line, str) or not line.startswith("LIVE "):
        raise ValueError("not a LIVE packet")
    try:
        packet = json.loads(line[5:])
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("malformed LIVE JSON") from exc
    if not isinstance(packet, dict) or not isinstance(packet.get("seq"), int):
        raise ValueError("LIVE packet missing integer sequence")
    for key in ("pots", "cvs", "switches"):
        if not isinstance(packet.get(key), list):
            raise ValueError(f"LIVE packet missing {key} list")
    return packet
