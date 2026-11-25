#!/usr/bin/env python3
"""Compact Windows serial monitor and DC calibration panel for FP05."""
import time
import tkinter as tk
from tkinter import messagebox, ttk
from collections import deque
from telemetry import PROTOCOL_VERSION, parse_protocol_line
from calibration import fit_transfer, candidate_network

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = list_ports = None

POTS = (("A", "TIME"), ("A", "SHAPE"), ("A", "RATIO"),
        ("B", "TIME"), ("B", "SHAPE"), ("B", "RATIO"))
POT_LABELS = ("A TIME", "A SLOPE", "A RATIO", "B TIME", "B SLOPE", "B RATIO")
CV_LABELS = ("A Ratio CV", "A Slope CV", "A Mod CV", "A Exp CV",
             "B Ratio CV", "B Slope CV", "B Mod CV", "B Exp CV")
OUT_LABELS = ("A Primary", "A Secondary", "B Primary", "B Secondary")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TROLLfx Front Panel Test V0.5 · DC Calibration")
        self.geometry("800x600")
        self.minsize(680, 500)
        self.port = None
        self.rx = bytearray()
        self.protocol_version = None
        self.packet_count = self.parse_errors = 0
        self.paused = False
        self.log_count = 0
        self.tx = deque()
        self.pending_ack = deque()
        self.last_moved = "NONE"
        self.control = {"A": {}, "B": {}}
        self.cv = [0] * 8
        self.output = [0] * 4
        self.output_codes = [0] * 4
        self.output_duty = [2047] * 4
        self.updating_dc = False
        self._build()
        self.refresh_ports()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(40, self.poll)

    def _build(self):
        top = ttk.Frame(self, padding=(5, 4)); top.pack(fill="x")
        self.port_var = tk.StringVar(value="COM9")
        self.port_box = ttk.Combobox(top, textvariable=self.port_var, width=9)
        self.port_box.pack(side="left")
        ttk.Button(top, text="Refresh", command=self.refresh_ports).pack(side="left", padx=2)
        ttk.Button(top, text="Connect", command=self.connect).pack(side="left", padx=2)
        ttk.Button(top, text="Disconnect", command=self.disconnect).pack(side="left", padx=2)
        self.status = tk.StringVar(value="● Disconnected · COM9 default")
        ttk.Label(top, textvariable=self.status, font=("Segoe UI", 10, "bold")).pack(side="left", padx=6)
        self.counter = tk.StringVar(value="Packets 0 · errors 0")
        ttk.Label(top, textvariable=self.counter).pack(side="right")

        self.tabs = ttk.Notebook(self); self.tabs.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self.pages = {}
        for name in ("LIVE", "DC CAL", "INPUTS", "LED TEST", "SERIAL"):
            frame = ttk.Frame(self.tabs, padding=7); self.tabs.add(frame, text=name); self.pages[name] = frame
        self._live(self.pages["LIVE"]); self._led(self.pages["LED TEST"])
        self._dc_cal(self.pages["DC CAL"]); self._cv(self.pages["INPUTS"])
        self._serial(self.pages["SERIAL"])

    def _meter(self, parent, name, row, column, maximum=4095, color=None):
        cell = ttk.Frame(parent); cell.grid(row=row, column=column, sticky="ew", padx=4, pady=4)
        ttk.Label(cell, text=name, width=13, foreground=color).pack(side="left")
        bar = ttk.Progressbar(cell, maximum=maximum); bar.pack(side="left", fill="x", expand=True, padx=4)
        val = tk.StringVar(value="—")
        ttk.Label(cell, textvariable=val, width=5, anchor="e").pack(side="right")
        return bar, val

    def _live(self, p):
        focus = ttk.LabelFrame(p, text="Last moved", padding=5); focus.pack(fill="x")
        self.focus_name = tk.StringVar(value="Waiting for telemetry")
        ttk.Label(focus, textvariable=self.focus_name, font=("Segoe UI", 20, "bold")).pack(side="left")
        self.focus_value = tk.StringVar(value="Raw ADC —  ·  0%")
        ttk.Label(focus, textvariable=self.focus_value, font=("Segoe UI", 13)).pack(side="right")
        self.focus_bar = ttk.Progressbar(focus, maximum=4095); self.focus_bar.pack(fill="x", pady=(4, 0))
        self.time_raw_text = tk.StringVar(value="Time ADC raw · A GPIO27: —  B GPIO28: —")
        ttk.Label(p, textvariable=self.time_raw_text).pack(anchor="w")
        pots = ttk.LabelFrame(p, text="Potentiometers · clockwise increases", padding=4); pots.pack(fill="x", pady=5)
        pots.columnconfigure((0, 1), weight=1)
        self.pot_bars = {}
        for i, ((side, key), label) in enumerate(zip(POTS, POT_LABELS)):
            self.pot_bars[(side, key)] = self._meter(pots, label, i % 3, i // 3, color="#d97b22" if side == "A" else "#367bd1")
        lower = ttk.Frame(p); lower.pack(fill="x")
        switches = ttk.LabelFrame(lower, text="Mode switches", padding=4); switches.pack(side="left", fill="both", expand=True)
        self.mode_text = {s: tk.StringVar(value=f"{s}: — · SW1 — · SW2 —") for s in ("A", "B")}
        for s in ("A", "B"):
            ttk.Label(switches, textvariable=self.mode_text[s], font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=3)
        self.enc_text = tk.StringVar(value="Encoder —   Encoder button —   Follow —")
        ttk.Label(lower, textvariable=self.enc_text, font=("Segoe UI", 10), wraplength=220).pack(side="left", padx=7)
        out = ttk.LabelFrame(p, text="Output signal · commanded PWM level, not measured jack voltage", padding=3); out.pack(fill="x", pady=5)
        out.columnconfigure((0, 1), weight=1); self.out_bars = []
        for i, label in enumerate(OUT_LABELS):
            self.out_bars.append(self._meter(out, label, i // 2, i % 2, color="#d97b22" if i < 2 else "#367bd1"))

    def _led(self, p):
        box = ttk.LabelFrame(p, text="Strip diagnostics", padding=7); box.pack(fill="x", pady=4)
        for label, cmd in (("Startup animation", "LED STARTUP"), ("RGB cycle", "LED RGB"),
                           ("Ring chase", "LED RING"), ("Return to normal", "LED LIVE")):
            ttk.Button(box, text=label, command=lambda c=cmd: self.send(c)).pack(side="left", padx=3, pady=4)
        manual = ttk.LabelFrame(p, text="Temporary individual pixel test", padding=7); manual.pack(fill="x", pady=4)
        self.pixel = tk.StringVar(value="0"); self.rgb = [tk.StringVar(value="255") for _ in range(3)]
        ttk.Label(manual, text="Pixel 0–22").pack(side="left"); ttk.Entry(manual, textvariable=self.pixel, width=5).pack(side="left", padx=3)
        for label, var in zip(("R", "G", "B"), self.rgb):
            ttk.Label(manual, text=label).pack(side="left"); ttk.Entry(manual, textvariable=var, width=5).pack(side="left", padx=2)
        ttk.Button(manual, text="Test pixel", command=self.pixel_test).pack(side="left", padx=5)
        ttk.Label(p, text="Manual pixel feedback expires after 1.8 seconds; channel signal LEDs stay live.").pack(anchor="w", pady=5)

    def _dc_cal(self, p):
        ttk.Label(p, text="Static DC only · 0–100% commanded signal position. No waveform generation or arming.",
                  font=("Segoe UI", 10, "bold"), wraplength=740).pack(anchor="w")
        ttk.Label(p, text="At boot each channel holds PWM code 0. The inverted analog stage can produce a nonzero jack voltage even at code 0.",
                  wraplength=740).pack(anchor="w", pady=(2, 5))
        box = ttk.LabelFrame(p, text="Four independent static outputs", padding=4); box.pack(fill="x")
        self.dc_scales = []; self.code_text = []; self.duty_text = []
        presets = (0, 25, 50, 75, 100)
        for ch, name in enumerate(OUT_LABELS):
            row = ttk.Frame(box); row.pack(fill="x", pady=2)
            ttk.Label(row, text=name, width=13, foreground="#d97b22" if ch < 2 else "#367bd1").pack(side="left")
            var = tk.IntVar(value=0); self.dc_scales.append(var)
            scale = tk.Scale(row, from_=0, to=100, orient="horizontal", resolution=1, showvalue=True,
                             variable=var, length=220, command=lambda value,c=ch:self.dc_changed(c, value))
            scale.pack(side="left", fill="x", expand=True, padx=3)
            code, duty = tk.StringVar(value="SIGNAL 0"), tk.StringVar(value="PWM CODE 2047")
            self.code_text.append(code); self.duty_text.append(duty)
            ttk.Label(row, textvariable=code, width=10, anchor="e").pack(side="left")
            ttk.Label(row, textvariable=duty, width=11, anchor="e").pack(side="left")
            for pct in presets:
                ttk.Button(row, text=f"{pct}%", width=4,
                           command=lambda c=ch,v=pct:self.set_dc(c,v)).pack(side="left", padx=1)

        cal = ttk.LabelFrame(p, text="Manual DMM measurements (volts) · enter a value for each channel/preset", padding=4)
        cal.pack(fill="x", pady=5)
        ttk.Label(cal, text="Output").grid(row=0, column=0, sticky="w")
        self.measurements = []
        for j, pct in enumerate(presets): ttk.Label(cal, text=f"{pct}%").grid(row=0, column=j+1, padx=3)
        for ch, name in enumerate(OUT_LABELS):
            ttk.Label(cal, text=name, width=13).grid(row=ch+1, column=0, sticky="w")
            row_vars = []
            for j in range(5):
                v = tk.StringVar(value=""); row_vars.append(v)
                ttk.Entry(cal, textvariable=v, width=9).grid(row=ch+1, column=j+1, padx=2, pady=1)
            self.measurements.append(row_vars)
        self.cal_results = []
        result_box = ttk.LabelFrame(p, text="Measured transfer fit", padding=4); result_box.pack(fill="x")
        for ch, name in enumerate(OUT_LABELS):
            result = tk.StringVar(value=f"{name}: enter at least two measurements")
            self.cal_results.append(result)
            ttk.Label(result_box, textvariable=result, font=("Consolas", 9), wraplength=720, justify="left").pack(anchor="w")
        ttk.Button(p, text="Calculate gain, offset, polarity and linearity", command=self.calculate_all).pack(anchor="w", pady=3)
        network_primary = candidate_network(existing_feedback_cap_f=1e-9)
        network_secondary = candidate_network(existing_feedback_cap_f=2.2e-9)
        self.network_text = tk.StringVar(value=(
            "Calculated 0–1 V candidate (published assumptions): Rf 39k→"
            f"{network_primary['feedback_ohms']/1000:.2f}k; reference leg "
            f"{network_primary['reference_upper_ohms']/1000:.2f}k+4.70k; preserve poles with primary Cf "
            f"{network_primary['feedback_cap_f']*1e9:.2f}nF, secondary Cf {network_secondary['feedback_cap_f']*1e9:.2f}nF."))
        ttk.Label(p, textvariable=self.network_text, wraplength=740).pack(anchor="w", pady=2)
        ttk.Label(p, text="Calculated starting values only. Confirm PCB revision, resistor population, supplies and DMM readings before any hardware modification.",
                  foreground="#9a4d00", wraplength=740).pack(anchor="w")

    def dc_changed(self, ch, value):
        if self.updating_dc: return
        pct = int(float(value)); code = round(pct * 2047 / 100); duty = 2047 - code
        self.code_text[ch].set(f"SIGNAL {code}"); self.duty_text[ch].set(f"PWM CODE {duty}")
        self.send(f"DC {ch} {pct}")

    def set_dc(self, ch, percent):
        self.updating_dc = True
        self.dc_scales[ch].set(percent)
        self.updating_dc = False
        code = round(percent * 2047 / 100); duty = 2047 - code
        self.code_text[ch].set(f"SIGNAL {code}"); self.duty_text[ch].set(f"PWM CODE {duty}")
        self.send(f"DC {ch} {percent}")

    def calculate_all(self):
        presets = (0, 25, 50, 75, 100)
        for ch, row in enumerate(self.measurements):
            pts = []
            try:
                for pct, var in zip(presets, row):
                    if var.get().strip(): pts.append((pct, float(var.get().strip())))
                fit = fit_transfer(pts)
                self.cal_results[ch].set(
                    f"{OUT_LABELS[ch]}: gain {fit['gain_v_per_100pct']:+.4f} V/100% · offset {fit['offset_v']:+.4f} V · "
                    f"{fit['polarity']} · max linearity error {fit['max_linearity_error_v']:.4f} V "
                    f"({fit['max_linearity_error_pct_span']:.2f}% span) · R² {fit['r_squared']:.5f}")
            except ValueError as exc:
                self.cal_results[ch].set(f"{OUT_LABELS[ch]}: {exc}")

    def _cv(self, p):
        ttk.Label(p, text="Eight raw 12-bit CV inputs; Time controls are direct GPIO27/28 ADC reads.").pack(anchor="w")
        self.time_diag = tk.StringVar(value="Time diagnostic: not queried")
        time_row = ttk.Frame(p); time_row.pack(fill="x", pady=3)
        ttk.Button(time_row, text="Read Time ADC diagnostics", command=lambda:self.send("TIME DIAG")).pack(side="left")
        ttk.Label(time_row, textvariable=self.time_diag).pack(side="left", padx=7)
        box = ttk.LabelFrame(p, text="Multiplexer CV inputs", padding=4); box.pack(fill="x", pady=5)
        box.columnconfigure((0, 1), weight=1); self.cv_bars = []
        for i, label in enumerate(CV_LABELS): self.cv_bars.append(self._meter(box, label, i % 4, i // 4))
        sync = ttk.LabelFrame(p, text="Conditioned sync inputs", padding=6); sync.pack(fill="x", pady=5)
        self.sync_text = tk.StringVar(value="A edges: 0    B edges: 0")
        ttk.Label(sync, textvariable=self.sync_text, font=("Segoe UI", 15)).pack(side="left", padx=5)
        ttk.Button(sync, text="Enable", command=lambda:self.send("SYNC ON")).pack(side="left", padx=3)
        ttk.Button(sync, text="Disable", command=lambda:self.send("SYNC OFF")).pack(side="left", padx=3)
        ttk.Button(sync, text="Query", command=lambda:self.send("SYNC?")).pack(side="left", padx=3)

    def _serial(self, p):
        row = ttk.Frame(p); row.pack(fill="x", pady=(0, 4))
        for label, cmd in (("Snapshot", "SNAPSHOT"), ("Live report", "REPORT LIVE"),
                           ("Changes only", "REPORT CHANGE"), ("Time ADC", "TIME DIAG"), ("Advanced diagnostics", "DIAG")):
            ttk.Button(row, text=label, command=lambda c=cmd:self.send(c)).pack(side="left", padx=2)
        ttk.Button(row, text="Clear log", command=self.clear).pack(side="right", padx=2)
        self.pause_btn = ttk.Button(row, text="Pause log", command=self.toggle_pause); self.pause_btn.pack(side="right", padx=2)
        self.log = tk.Text(p, height=20, wrap="word", font=("Consolas", 9)); scroll = ttk.Scrollbar(p, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set); self.log.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y")
        entry = ttk.Frame(p); entry.pack(fill="x", pady=4)
        self.command = tk.StringVar(); ttk.Entry(entry, textvariable=self.command).pack(side="left", fill="x", expand=True)
        ttk.Button(entry, text="Send", command=self.send_custom).pack(side="left", padx=3)

    def refresh_ports(self):
        found = [p.device for p in list_ports.comports()] if list_ports else []
        self.port_box["values"] = found or ["COM9"]
        if "COM9" in found or not found: self.port_var.set("COM9")
        elif self.port_var.get() not in found: self.port_var.set(found[0])

    def connect(self):
        if serial is None:
            messagebox.showerror("Dependency missing", "Install dependencies with: py -m pip install -r requirements.txt"); return
        try:
            self.port = serial.Serial(self.port_var.get().strip(), 115200, timeout=0, write_timeout=1)
            self.rx.clear(); self.protocol_version = None; self.packet_count = self.parse_errors = 0
            self._status("Connected · waiting for FP05")
            self.send("SNAPSHOT")
        except Exception as exc:
            self.port = None; messagebox.showerror("Serial connection", str(exc))

    def disconnect(self):
        if self.port:
            try: self.port.close()
            except Exception: pass
        self.port = None; self._status("Disconnected")

    def close(self): self.disconnect(); self.destroy()
    def _status(self, message): self.status.set(("● " if self.port else "○ ") + message)

    def send(self, command):
        if not self.port: self._status("Not connected"); return
        command = command.strip()
        if command.startswith("DC "):
            parts = command.split()
            if len(parts) == 3:
                self.tx = deque(c for c in self.tx if not c.startswith(f"DC {parts[1]} "))
        self.tx.append(command)
        self._append("> " + command)

    def send_custom(self):
        if self.command.get().strip(): self.send(self.command.get()); self.command.set("")

    def pixel_test(self):
        try:
            index = int(self.pixel.get()); rgb = [int(v.get()) for v in self.rgb]
            if not 0 <= index <= 22 or any(not 0 <= c <= 255 for c in rgb): raise ValueError
        except ValueError:
            messagebox.showerror("Invalid pixel", "Use pixel 0–22 and RGB values 0–255."); return
        self.send(f"LED ONE {index} {rgb[0]} {rgb[1]} {rgb[2]}")

    def _append(self, line):
        if self.paused: return
        self.log.insert("end", line + "\n"); self.log.see("end"); self.log_count += 1
        if self.log_count > 1200: self.log.delete("1.0", "300.0"); self.log_count -= 300

    def clear(self): self.log.delete("1.0", "end"); self.log_count = 0
    def toggle_pause(self):
        self.paused = not self.paused; self.pause_btn.configure(text="Resume log" if self.paused else "Pause log")

    def poll(self):
        if self.port:
            try:
                if self.tx and (not self.pending_ack or time.monotonic() - self.pending_ack[0][1] > .08):
                    cmd = self.tx.popleft(); self.port.write((cmd + "\n").encode("ascii")); self.pending_ack.append((cmd, time.monotonic()))
                data = self.port.read(max(1, self.port.in_waiting)); self.rx.extend(data)
                while b"\n" in self.rx:
                    raw, _, tail = self.rx.partition(b"\n"); self.rx = bytearray(tail)
                    line = raw.decode("utf-8", "replace").strip()
                    if line: self._handle(line)
                if self.pending_ack and time.monotonic() - self.pending_ack[0][1] > 2.0:
                    cmd, _ = self.pending_ack.popleft(); self._append(f"! no acknowledgement: {cmd}")
                if self.pending_ack and self.tx and time.monotonic() - self.pending_ack[0][1] > .08:
                    pass
            except (OSError, UnicodeError) as exc:
                self.disconnect(); self._append(f"! serial disconnected: {exc}")
        self.counter.set(f"Packets {self.packet_count} · errors {self.parse_errors}")
        self.after(40, self.poll)

    def _handle(self, line):
        self._append(line)
        try: packet = parse_protocol_line(line)
        except ValueError:
            self.parse_errors += 1; return
        kind = packet["type"]
        if kind == "protocol":
            self.protocol_version = packet["version"]
            self._status("FP05 matched" if self.protocol_version == PROTOCOL_VERSION else f"Protocol mismatch: {self.protocol_version}")
            return
        if kind == "legacy":
            self._status(f"Firmware mismatch · expected {PROTOCOL_VERSION}, received legacy stream"); return
        if kind == "text": return
        self.packet_count += 1
        if kind in ("ack", "error"):
            if self.pending_ack: self.pending_ack.popleft()
            if kind == "error": self._status("Command error · " + packet["text"])
            elif packet["text"]: self._status("OK · " + packet["text"])
            return
        if self.protocol_version != PROTOCOL_VERSION: return
        if kind == "controls":
            s = packet["side"]; self.control[s] = packet
            for k in ("TIME", "SHAPE", "RATIO"):
                bar, val = self.pot_bars[(s, k)]; raw = packet[k]; bar["value"] = raw; val.set(str(raw))
            self.mode_text[s].set(f"{s}: {packet['MODE']} · SW1 {'HIGH' if packet['SW1'] else 'LOW'} · SW2 {'HIGH' if packet['SW2'] else 'LOW'}")
            if self.last_moved.startswith(s + "_"): self._focus_pot(s, self.last_moved.split("_", 1)[1])
        elif kind == "encoder":
            self.enc_text.set(f"Encoder {packet['position']}   Encoder button {'DOWN' if packet['button'] else 'UP'}   Follow {'DOWN' if packet['follow'] else 'UP'}")
        elif kind == "cv":
            self.cv = packet["values"]
            for (bar, val), raw in zip(self.cv_bars, self.cv): bar["value"] = raw; val.set(str(raw))
        elif kind == "outputs":
            self.output = packet["percent"]
            self.output_codes, self.output_duty = packet["codes"], packet["duty"]
            for ch, pct in enumerate(self.output):
                if not self.updating_dc:
                    self.updating_dc = True; self.dc_scales[ch].set(pct); self.updating_dc = False
                self.code_text[ch].set(f"SIGNAL {self.output_codes[ch]}")
                self.duty_text[ch].set(f"PWM CODE {self.output_duty[ch]}")
            for (bar, val), pct in zip(self.out_bars, self.output):
                level = pct * 4095 // 100; bar["value"] = level; val.set(f"{pct}%")
        elif kind == "moved":
            self.last_moved = packet["name"]
            name = packet["name"]
            for side in ("A", "B"):
                for key in ("TIME", "SHAPE", "RATIO"):
                    if name == f"{side}_{key}": self._focus_pot(side, key); return
            if name in ("A_SW1", "A_SW2", "B_SW1", "B_SW2", "ENCODER_BUTTON", "FOLLOW_BUTTON"):
                self.focus_name.set(name.replace("_", " ")); self.focus_value.set("Input changed"); self.focus_bar["value"] = 0
            elif name.startswith("ENCODER"):
                self.focus_name.set("ENCODER"); self.focus_value.set(self.enc_text.get()); self.focus_bar["value"] = 0
        elif kind == "timeraw":
            self.time_raw_text.set(f"Time ADC raw · A GPIO27: {packet['a']}  B GPIO28: {packet['b']}")
        elif kind == "timediag":
            self.time_diag.set(f"A scan/direct/SDK {packet['A_SCAN']}/{packet['A_ARDUINO']}/{packet['A_SDK']} · "
                               f"B {packet['B_SCAN']}/{packet['B_ARDUINO']}/{packet['B_SDK']}")
        elif kind == "sync": self.sync_text.set(f"A edges: {packet['a']}    B edges: {packet['b']}")

    def _focus_pot(self, side, key):
        packet = self.control.get(side, {}).get(key)
        if packet is None: return
        self.focus_name.set(f"{side} {key}"); self.focus_value.set(f"Raw ADC {packet}  ·  {packet * 100 // 4095}%")
        self.focus_bar["value"] = packet


if __name__ == "__main__":
    App().mainloop()
