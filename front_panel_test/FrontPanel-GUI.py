#!/usr/bin/env python3
"""Compact Windows serial monitor and control panel for FP04."""
import time
import tkinter as tk
from tkinter import messagebox, ttk
from collections import deque
from telemetry import PROTOCOL_VERSION, parse_protocol_line

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
SHAPES = ("sine", "triangle", "ramp", "square")
FREQUENCIES = ("0.5", "1", "2", "5", "10", "20", "50", "100")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TROLLfx Front Panel Test V0.4")
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
        for name in ("LIVE", "LED TEST", "OUTPUT TEST", "CV INPUTS", "SERIAL"):
            frame = ttk.Frame(self.tabs, padding=7); self.tabs.add(frame, text=name); self.pages[name] = frame
        self._live(self.pages["LIVE"]); self._led(self.pages["LED TEST"])
        self._outputs(self.pages["OUTPUT TEST"]); self._cv(self.pages["CV INPUTS"])
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

    def _outputs(self, p):
        ttk.Label(p, text="Four independent, continuously driven PWM outputs. Defaults are 1 Hz sine after boot.", wraplength=720).pack(anchor="w")
        self.wave = []
        box = ttk.LabelFrame(p, text="Waveform controls", padding=5); box.pack(fill="x", pady=6)
        for ch, name in enumerate(OUT_LABELS):
            row = ttk.Frame(box); row.pack(fill="x", pady=4)
            ttk.Label(row, text=f"{ch} · {name}", width=17).pack(side="left")
            shape, freq = tk.StringVar(value="sine"), tk.StringVar(value="1")
            ttk.Combobox(row, textvariable=shape, values=SHAPES, state="readonly", width=10).pack(side="left", padx=3)
            ttk.Combobox(row, textvariable=freq, values=FREQUENCIES, state="readonly", width=7).pack(side="left", padx=3)
            ttk.Button(row, text="Start", command=lambda c=ch,s=shape,f=freq:self.send(f"WAVE {c} {s.get()} {f.get()}")).pack(side="left", padx=3)
            ttk.Button(row, text="Stop", command=lambda c=ch:self.send(f"STOP {c}")).pack(side="left", padx=3)
            self.wave.append((shape, freq))
        meter = ttk.LabelFrame(p, text="Live calculated signal levels", padding=4); meter.pack(fill="x")
        meter.columnconfigure((0, 1), weight=1)
        self.output_test_bars = []
        for i, name in enumerate(OUT_LABELS): self.output_test_bars.append(self._meter(meter, name, i // 2, i % 2, color="#d97b22" if i < 2 else "#367bd1"))
        ttk.Button(p, text="STOP ALL", command=lambda:self.send("STOP ALL")).pack(anchor="e", pady=6)

    def _cv(self, p):
        ttk.Label(p, text="Eight raw 12-bit CV inputs and conditioned sync edge counts.").pack(anchor="w")
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
                           ("Changes only", "REPORT CHANGE"), ("Advanced diagnostics", "DIAG")):
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
            self._status("Connected · waiting for FP04")
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
            self._status("FP04 matched" if self.protocol_version == PROTOCOL_VERSION else f"Protocol mismatch: {self.protocol_version}")
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
            self.output = packet["values"]
            for (bar, val), raw in zip(self.out_bars, self.output): bar["value"] = raw; val.set(str(raw))
            for (bar, val), raw in zip(self.output_test_bars, self.output): bar["value"] = raw; val.set(str(raw))
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
        elif kind == "sync": self.sync_text.set(f"A edges: {packet['a']}    B edges: {packet['b']}")

    def _focus_pot(self, side, key):
        packet = self.control.get(side, {}).get(key)
        if packet is None: return
        self.focus_name.set(f"{side} {key}"); self.focus_value.set(f"Raw ADC {packet}  ·  {packet * 100 // 4095}%")
        self.focus_bar["value"] = packet


if __name__ == "__main__":
    App().mainloop()
