"""Parser for Front Panel Test V0.6 serial lines and prior-release captures."""
PROTOCOL_VERSION = "FP06"


def _fields(line):
    return dict(word.split("=", 1) for word in line.split() if "=" in word)


def _adc(value, label):
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {label}") from exc
    if not 0 <= value <= 4095:
        raise ValueError(f"{label} outside 0..4095")
    return value


def parse_protocol_line(line):
    if not isinstance(line, str):
        raise ValueError("serial line must be text")
    line = line.strip()
    if line.startswith("PROTO="):
        return {"type": "protocol", "version": line.partition("=")[2]}
    if line.startswith("HELLO FW="):
        fields = _fields(line)
        if "FW" not in fields or "GUI" not in fields:
            raise ValueError("incomplete handshake")
        return {"type": "handshake", "firmware": fields["FW"], "gui": fields["GUI"]}
    if line.startswith("READY FrontPanel-Test-V0.") or line.startswith("LIVE {"):
        return {"type": "legacy", "text": line}
    if line[:2] in ("A ", "B "):
        side, fields = line[0], _fields(line[2:])
        # V0.5 used SHAPE; V0.6 calls the physical control SLOPE.
        if "SLOPE" not in fields and "SHAPE" in fields:
            fields["SLOPE"] = fields["SHAPE"]
        required = ("TIME", "SLOPE", "RATIO", "MODE")
        if any(k not in fields for k in required):
            raise ValueError("incomplete control line")
        values = {k: _adc(fields[k], k) for k in ("TIME", "SLOPE", "RATIO")}
        for key in ("TIME", "SLOPE", "RATIO"):
            if key + "_RAW" in fields:
                values[key + "_RAW"] = _adc(fields[key + "_RAW"], key + "_RAW")
        if fields["MODE"] not in ("ENV", "LFO", "VCO", "INVALID"):
            raise ValueError("invalid mode")
        result = {"type": "controls", "side": side, **values, "MODE": fields["MODE"]}
        for key in ("SW1_RAW", "SW2_RAW"):
            if key in fields: result[key] = _adc(fields[key], key)
        # V0.5 compatibility: binary switch states can be displayed as raw endpoints.
        if "SW1" in fields and "SW2" in fields:
            result["SW1_RAW"] = int(fields["SW1"]) * 4095
            result["SW2_RAW"] = int(fields["SW2"]) * 4095
        return result
    if line.startswith("CTRL ID="):
        fields = _fields(line)
        ident = fields.get("ID", "")
        if ident not in ("A_TIME", "A_SLOPE", "A_RATIO", "B_TIME", "B_SLOPE", "B_RATIO"):
            raise ValueError("unknown physical control ID")
        return {"type": "control", "id": ident, "raw": _adc(fields.get("RAW"), "RAW"),
                "value": _adc(fields.get("VALUE"), "VALUE")}
    if line.startswith("SWITCH "):
        fields = _fields(line)
        side = line.split(maxsplit=1)[1][0]
        if side not in ("A", "B") or fields.get("MODE") not in ("ENV", "LFO", "VCO", "INVALID"):
            raise ValueError("invalid switch state")
        return {"type": "switch", "side": side, "mode": fields["MODE"],
                "sw1_raw": _adc(fields.get("SW1_RAW"), "SW1_RAW"),
                "sw2_raw": _adc(fields.get("SW2_RAW"), "SW2_RAW")}
    if line.startswith("ENC="):
        f = _fields(line)
        if "BTN" not in f and "BUTTON" in f:
            return {"type": "legacy", "text": line}
        try:
            result = {"type": "encoder", "position": int(f["ENC"]),
                      "button": int(f["BTN"]), "follow": int(f["FOLLOW"])}
        except (KeyError, ValueError) as exc:
            raise ValueError("invalid encoder packet") from exc
        if result["button"] not in (0, 1) or result["follow"] not in (0, 1):
            raise ValueError("button state outside 0/1")
        return result
    if line.startswith("ENCODER "):
        try: return {"type": "encoder_position", "position": int(line.split()[1])}
        except (IndexError, ValueError) as exc: raise ValueError("invalid encoder position") from exc
    if line.startswith("ENCODER_BUTTON ") or line.startswith("FOLLOW_BUTTON "):
        name, value = line.split(maxsplit=1)
        if value not in ("ON", "OFF"): raise ValueError("invalid button state")
        return {"type": "button", "name": "ENCODER" if name.startswith("ENCODER") else "FOLLOW",
                "pressed": value == "ON"}
    if line.startswith("CV="):
        try:
            values = [_adc(v, "CV") for v in line[3:].split(",")]
        except ValueError as exc:
            raise ValueError("invalid CV packet") from exc
        if len(values) != 8:
            raise ValueError("CV packet must contain eight values")
        return {"type": "cv", "values": values}
    if line.startswith("OUT "):
        f = _fields(line[4:])
        if line.startswith("OUT PCT="):
            try:
                pct = [int(v) for v in f["PCT"].split(",")]
                codes = [int(v) for v in f["CODE"].split(",")]
                duty = [int(v) for v in f["DUTY"].split(",")]
            except (KeyError, ValueError) as exc:
                raise ValueError("invalid DC output packet") from exc
            if len(pct) != 4 or len(codes) != 4 or len(duty) != 4:
                raise ValueError("DC output packet requires four channels")
            if any(v < 0 or v > 100 for v in pct) or any(v < 0 or v > 2047 for v in codes + duty):
                raise ValueError("DC output value outside range")
            return {"type": "outputs", "percent": pct, "codes": codes, "duty": duty}
        if f.get("MODE") != "PWM" or "=" in line.split()[-1]:
            return {"type": "legacy", "text": line}
        values_text = line.split()[-1]
        try:
            values = [_adc(v, "output") for v in values_text.split(",")]
        except ValueError as exc:
            raise ValueError("invalid output packet") from exc
        if len(values) != 4 or f.get("MODE") not in ("PWM",):
            raise ValueError("invalid output packet shape/status")
        return {"type": "outputs", "mode": f["MODE"], "meter": f.get("METER", "AUTO"), "values": values}
    if line.startswith("MOVED="):
        return {"type": "moved", "name": line.partition("=")[2]}
    if line.startswith("TIMERAW="):
        try:
            values = [int(v) for v in line[8:].split(",")]
        except ValueError as exc:
            raise ValueError("invalid raw time packet") from exc
        if len(values) != 2 or any(v < 0 or v > 4095 for v in values):
            raise ValueError("raw time value outside range")
        return {"type": "timeraw", "a": values[0], "b": values[1]}
    if line.startswith("TIME "):
        fields = _fields(line[5:])
        try:
            result = {key: int(fields[key]) for key in
                      ("A_GPIO", "A_SCAN", "A_ARDUINO", "A_SDK", "B_GPIO", "B_SCAN", "B_ARDUINO", "B_SDK")}
        except (KeyError, ValueError) as exc:
            raise ValueError("invalid Time ADC diagnostic") from exc
        return {"type": "timediag", **result}
    if line.startswith("SYNC="):
        try:
            a, b = (int(x) for x in line[5:].split(","))
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid sync packet") from exc
        return {"type": "sync", "a": a, "b": b}
    if line.startswith("OK ") or line == "OK":
        return {"type": "ack", "text": line[3:] if len(line) > 3 else ""}
    if line.startswith("ERR "):
        return {"type": "error", "text": line[4:]}
    return {"type": "text", "text": line}
