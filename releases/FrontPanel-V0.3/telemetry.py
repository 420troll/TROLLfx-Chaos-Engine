"""Parser for the compact, line-oriented Front Panel Test FP03 protocol."""
PROTOCOL_VERSION = "FP03"


def _fields(line):
    result = {}
    for word in line.split():
        if "=" not in word:
            continue
        key, value = word.split("=", 1)
        result[key] = value
    return result


def parse_protocol_line(line):
    """Parse one FP03 line into typed values; unknown/legacy lines are text."""
    if not isinstance(line, str):
        raise ValueError("serial line must be text")
    line = line.strip()
    if line.startswith("PROTO="):
        return {"type": "protocol", "version": line.partition("=")[2]}
    if line.startswith("LIVE {") or line.startswith("READY FrontPanel-Test-V0."):
        return {"type": "legacy", "text": line}
    if line.startswith(("A ", "B ")):
        side = line[0]
        fields = _fields(line[2:])
        required = ("TIME", "SHAPE", "RATIO", "MODE", "SW1", "SW2")
        if any(key not in fields for key in required):
            raise ValueError(f"incomplete {side} control line")
        values = {key: int(fields[key]) for key in ("TIME", "SHAPE", "RATIO", "SW1", "SW2")}
        if any(not 0 <= values[key] <= 4095 for key in ("TIME", "SHAPE", "RATIO")):
            raise ValueError("pot value outside 0..4095")
        if any(values[key] not in (0, 1) for key in ("SW1", "SW2")):
            raise ValueError("switch state outside 0/1")
        if fields["MODE"] not in ("VCO", "LFO", "ENV"):
            raise ValueError("invalid mode")
        return {"type": "controls", "side": side, **values, "MODE": fields["MODE"]}
    if line.startswith("ENC="):
        fields = _fields(line)
        try:
            position = int(fields["ENC"])
            button, follow = int(fields["BUTTON"]), int(fields["FOLLOW"])
        except (KeyError, ValueError) as exc:
            raise ValueError("invalid encoder line") from exc
        if button not in (0, 1) or follow not in (0, 1):
            raise ValueError("button state outside 0/1")
        return {"type": "encoder", "position": position, "button": button, "follow": follow}
    if line.startswith("CV "):
        fields = _fields(line[3:])
        names = ("A_RATIO", "A_SHAPE", "A_MOD", "A_EXP", "B_RATIO", "B_SHAPE", "B_MOD", "B_EXP")
        try:
            values = {name: int(fields[name]) for name in names}
        except (KeyError, ValueError) as exc:
            raise ValueError("invalid CV line") from exc
        if any(not 0 <= value <= 4095 for value in values.values()):
            raise ValueError("CV value outside 0..4095")
        return {"type": "cv", **values}
    if line.startswith("OUT "):
        fields = _fields(line[4:])
        names = ("A_PRI", "A_SEC", "B_PRI", "B_SEC")
        if fields.get("MODE") not in ("SIM", "PWM") or fields.get("METER") not in ("INSTANT", "PEAK", "RMS"):
            raise ValueError("invalid output status")
        try:
            values = {name: int(fields[name]) for name in names}
        except (KeyError, ValueError) as exc:
            raise ValueError("invalid output level line") from exc
        if any(not 0 <= value <= 4095 for value in values.values()):
            raise ValueError("output level outside 0..4095")
        return {"type": "outputs", "mode": fields["MODE"], "meter": fields["METER"], **values}
    if line.startswith("MOVED="):
        return {"type": "moved", "name": line.partition("=")[2]}
    if line.startswith("STATE "):
        fields = _fields(line[6:])
        try:
            analog, trigger = int(fields["ANALOG"]), int(fields["TRIGGER"])
        except (KeyError, ValueError) as exc:
            raise ValueError("invalid state line") from exc
        if analog not in (0, 1) or trigger not in (0, 1):
            raise ValueError("arming state outside 0/1")
        return {"type": "state", "analog": analog, "trigger": trigger}
    if line.startswith("SYNC "):
        fields = _fields(line[5:])
        try:
            return {"type": "sync", "a": int(fields["A"]), "b": int(fields["B"])}
        except (KeyError, ValueError) as exc:
            raise ValueError("invalid sync line") from exc
    return {"type": "text", "text": line}
