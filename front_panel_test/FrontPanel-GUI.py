#!/usr/bin/env python3
"""Windows COM-port GUI for TROLLfx Front Panel Test V0.1."""
import json
import math
import tkinter as tk
from tkinter import messagebox, ttk

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None


POTS = ("A_TIME", "A_RATIO", "A_SHAPE", "B_TIME", "B_RATIO", "B_SHAPE")
CVS = ("A_RATIO_CV", "A_SHAPE_CV", "A_MOD_CV", "A_EXP_CV", "B_RATIO_CV", "B_SHAPE_CV", "B_MOD_CV", "B_EXP_CV")
SWITCHES = ("A_SW1", "A_SW2", "B_SW1", "B_SW2")
OUTPUTS = ("A Primary", "A Secondary", "B Primary", "B Secondary")
SHAPES = ("sine", "triangle", "ramp", "square")
FREQUENCIES = ("0.5", "1", "2", "5")


class FrontPanelApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TROLLfx Front Panel Test V0.1")
        self.geometry("1120x900")
        self.minsize(980, 760)
        self.port = None
        self.rx_buffer = bytearray()
        self.values = {}
        self._build_ui()
        self.refresh_ports()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(80, self._poll)

    def _build_ui(self):
        connection = ttk.LabelFrame(self, text="USB serial")
        connection.pack(fill="x", padx=8, pady=5)
        self.port_name = tk.StringVar(value="COM9")
        self.port_box = ttk.Combobox(connection, textvariable=self.port_name, width=18)
        self.port_box.pack(side="left", padx=4, pady=4)
        ttk.Button(connection, text="Refresh", command=self.refresh_ports).pack(side="left", padx=4)
        ttk.Button(connection, text="Connect", command=self.connect).pack(side="left", padx=4)
        ttk.Button(connection, text="Disconnect", command=self.disconnect).pack(side="left", padx=4)
        self.status = tk.StringVar(value="Disconnected; COM9 preselected")
        ttk.Label(connection, textvariable=self.status).pack(side="left", padx=10)

        safety = ttk.LabelFrame(self, text="Output arming — output jack voltage is not zero when PWM code is zero")
        safety.pack(fill="x", padx=8, pady=5)
        ttk.Button(safety, text="ARM ANALOG", command=self.arm_analog).pack(side="left", padx=5, pady=5)
        ttk.Button(safety, text="ARM TRIGGER", command=self.arm_trigger).pack(side="left", padx=5)
        ttk.Button(safety, text="ARM ALL", command=self.arm_all).pack(side="left", padx=5)
        ttk.Button(safety, text="DISARM ALL", command=lambda: self.send("DISARM")).pack(side="left", padx=5)
        ttk.Button(safety, text="INFO", command=lambda: self.send("INFO")).pack(side="left", padx=5)
        ttk.Button(safety, text="STATS", command=lambda: self.send("STATS")).pack(side="left", padx=5)
        ttk.Button(safety, text="RESET STATS", command=lambda: self.send("RESET STATS")).pack(side="left", padx=5)
        ttk.Button(safety, text="SYNC ON", command=lambda: self.send("SYNC ON")).pack(side="left", padx=3)
        ttk.Button(safety, text="SYNC OFF", command=lambda: self.send("SYNC OFF")).pack(side="left", padx=3)
        ttk.Button(safety, text="SYNC?", command=lambda: self.send("SYNC?")).pack(side="left", padx=3)
        ttk.Button(safety, text="HELP", command=lambda: self.send("HELP")).pack(side="left", padx=3)
        self.arm_state = tk.StringVar(value="State unknown until LIVE data arrives")
        ttk.Label(safety, textvariable=self.arm_state).pack(side="left", padx=10)

        live = ttk.Frame(self)
        live.pack(fill="x", padx=8, pady=4)
        pots = ttk.LabelFrame(live, text="Six potentiometers — raw ADC / percent / observed min–max")
        pots.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.pot_rows = {}
        for row, name in enumerate(POTS):
            ttk.Label(pots, text=name, width=13).grid(row=row, column=0, sticky="w", padx=4, pady=3)
            bar = ttk.Progressbar(pots, maximum=100, length=160)
            bar.grid(row=row, column=1, sticky="ew", padx=4)
            text = tk.StringVar(value="raw 0 / 0% / 0–0")
            ttk.Label(pots, textvariable=text, width=23).grid(row=row, column=2, sticky="w", padx=4)
            self.pot_rows[name] = (bar, text)

        cvs = ttk.LabelFrame(live, text="Multiplexer CV inputs — raw ADC / percent / observed min–max")
        cvs.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self.cv_rows = {}
        for row, name in enumerate(CVS):
            ttk.Label(cvs, text=name, width=14).grid(row=row, column=0, sticky="w", padx=4, pady=2)
            bar = ttk.Progressbar(cvs, maximum=100, length=145)
            bar.grid(row=row, column=1, sticky="ew", padx=4)
            text = tk.StringVar(value="0 / 0% / 0–0")
            ttk.Label(cvs, textvariable=text, width=20).grid(row=row, column=2, sticky="w", padx=4)
            self.cv_rows[name] = (bar, text)

        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=8, pady=4)
        panel = ttk.LabelFrame(controls, text="Encoder, buttons, mode switches and LED ring")
        panel.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.encoder_text = tk.StringVar(value="Encoder: —")
        ttk.Label(panel, textvariable=self.encoder_text, font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", padx=5, pady=4)
        self.button_text = tk.StringVar(value="Encoder button: —    Follow button: —")
        ttk.Label(panel, textvariable=self.button_text).grid(row=1, column=0, columnspan=3, sticky="w", padx=5)
        self.mode_text = tk.StringVar(value="A mode: —    B mode: —")
        ttk.Label(panel, textvariable=self.mode_text).grid(row=2, column=0, columnspan=3, sticky="w", padx=5)
        self.switch_text = tk.StringVar(value="A_SW1 —  A_SW2 —  B_SW1 —  B_SW2 —")
        ttk.Label(panel, textvariable=self.switch_text).grid(row=3, column=0, columnspan=3, sticky="w", padx=5)
        self.ring = tk.Canvas(panel, width=215, height=215, background="#202028", highlightthickness=0)
        self.ring.grid(row=0, column=3, rowspan=5, padx=6, pady=4)
        self.ring_dots = []
        cx = cy = 107
        for i in range(16):
            angle = (i / 16.0) * 6.28318530718 - 1.57079632679
            x, y = cx + 78 * math.cos(angle), cy + 78 * math.sin(angle)
            self.ring_dots.append(self.ring.create_oval(x-8, y-8, x+8, y+8, fill="#50505c", outline="#a0a0aa"))
            self.ring.create_text(x, y, text=str(i), fill="white", font=("Segoe UI", 7))
        ttk.Label(panel, text="Rotate the encoder to move the physical ring and GUI marker.").grid(row=4, column=0, columnspan=3, sticky="w", padx=5)

        outputs = ttk.LabelFrame(controls, text="Four output waveform selectors")
        outputs.pack(side="left", fill="both", expand=True, padx=(4, 0))
        self.output_controls = []
        for row, name in enumerate(OUTPUTS):
            ttk.Label(outputs, text=f"{row}: {name}", width=14).grid(row=row, column=0, padx=3, pady=4, sticky="w")
            shape = tk.StringVar(value="sine")
            ttk.Combobox(outputs, textvariable=shape, values=SHAPES, state="readonly", width=10).grid(row=row, column=1, padx=3)
            freq = tk.StringVar(value="1")
            ttk.Combobox(outputs, textvariable=freq, values=FREQUENCIES, state="readonly", width=7).grid(row=row, column=2, padx=3)
            ttk.Button(outputs, text="Start", command=lambda ch=row, sh=shape, hz=freq: self.start_wave(ch, sh, hz)).grid(row=row, column=3, padx=3)
            ttk.Button(outputs, text="Stop", command=lambda ch=row: self.send(f"STOP {ch}")).grid(row=row, column=4, padx=3)
            self.output_controls.append((shape, freq))
        auto = ttk.Frame(outputs)
        auto.grid(row=4, column=0, columnspan=5, sticky="w", padx=4, pady=5)
        self.auto_shape = tk.StringVar(value="sine")
        self.auto_freq = tk.StringVar(value="1")
        self.auto_seconds = tk.StringVar(value="3")
        ttk.Label(auto, text="Cycle outputs:").pack(side="left")
        ttk.Combobox(auto, textvariable=self.auto_shape, values=SHAPES, state="readonly", width=9).pack(side="left", padx=3)
        ttk.Combobox(auto, textvariable=self.auto_freq, values=FREQUENCIES, state="readonly", width=5).pack(side="left", padx=3)
        ttk.Entry(auto, textvariable=self.auto_seconds, width=4).pack(side="left", padx=3)
        ttk.Label(auto, text="s/output").pack(side="left")
        ttk.Button(auto, text="Start auto cycle", command=self.start_auto).pack(side="left", padx=4)
        ttk.Button(auto, text="Stop auto", command=lambda: self.send("AUTO OFF")).pack(side="left", padx=3)

        ledtests = ttk.LabelFrame(self, text="LED diagnostics")
        ledtests.pack(fill="x", padx=8, pady=5)
        for label, command in (("Startup animation", "LED STARTUP"), ("RGB cycle", "LED RGB"), ("Ring chase", "LED RING"), ("Live", "LED LIVE")):
            ttk.Button(ledtests, text=label, command=lambda c=command: self.send(c)).pack(side="left", padx=4, pady=5)
        self.led_index = tk.StringVar(value="0")
        self.led_r = tk.StringVar(value="255")
        self.led_g = tk.StringVar(value="255")
        self.led_b = tk.StringVar(value="255")
        for label, var, width in (("LED #", self.led_index, 4), ("R", self.led_r, 4), ("G", self.led_g, 4), ("B", self.led_b, 4)):
            ttk.Label(ledtests, text=label).pack(side="left", padx=(8, 2))
            ttk.Entry(ledtests, textvariable=var, width=width).pack(side="left")
        ttk.Button(ledtests, text="Set individual LED", command=self.set_led).pack(side="left", padx=5)
        ttk.Label(ledtests, text="Brightness").pack(side="left", padx=(10, 3))
        self.brightness = tk.StringVar(value="80")
        ttk.Entry(ledtests, textvariable=self.brightness, width=5).pack(side="left")
        ttk.Button(ledtests, text="Set", command=lambda: self.send("BRIGHTNESS " + self.brightness.get())).pack(side="left", padx=3)
        self.indicator = tk.StringVar(value="0")
        self.indicator_level = tk.StringVar(value="255")
        ttk.Label(ledtests, text="Output LED ch / level").pack(side="left", padx=(8, 2))
        ttk.Combobox(ledtests, textvariable=self.indicator, values=["0", "1", "2", "3"], state="readonly", width=3).pack(side="left")
        ttk.Entry(ledtests, textvariable=self.indicator_level, width=5).pack(side="left")
        ttk.Button(ledtests, text="Test indicator", command=lambda: self.send(f"INDICATOR {self.indicator.get()} {self.indicator_level.get()}")).pack(side="left", padx=3)
        ttk.Button(ledtests, text="Indicator live", command=lambda: self.send("INDICATOR LIVE")).pack(side="left", padx=3)

        monitor = ttk.LabelFrame(self, text="Serial monitor")
        monitor.pack(fill="both", expand=True, padx=8, pady=5)
        self.monitor = tk.Text(monitor, height=10, wrap="none", font=("Consolas", 9))
        scroll = ttk.Scrollbar(monitor, orient="vertical", command=self.monitor.yview)
        self.monitor.configure(yscrollcommand=scroll.set)
        self.monitor.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        scroll.pack(side="right", fill="y", pady=4)
        command = ttk.Frame(self)
        command.pack(fill="x", padx=8, pady=(0, 6))
        self.raw_command = tk.StringVar()
        ttk.Entry(command, textvariable=self.raw_command).pack(side="left", fill="x", expand=True)
        ttk.Button(command, text="Send", command=self.send_custom).pack(side="left", padx=4)

    def refresh_ports(self):
        if list_ports is None:
            self.port_box["values"] = ["COM9"]
            self.status.set("Install pyserial; COM9 preselected")
            return
        ports = [p.device for p in list_ports.comports()]
        self.port_box["values"] = ports
        if "COM9" in ports or not ports:
            self.port_name.set("COM9")
        elif self.port_name.get() not in ports:
            self.port_name.set(ports[0])
        if not ports:
            self.status.set("No COM port found; COM9 is available for manual entry")

    def connect(self):
        if serial is None:
            messagebox.showerror("Missing dependency", "Install pyserial with: py -m pip install -r requirements.txt")
            return
        try:
            self.port = serial.Serial(self.port_name.get().strip(), 115200, timeout=0, write_timeout=1)
            self.port.reset_input_buffer()
            self.rx_buffer.clear()
            self.status.set(f"Connected: {self.port_name.get().strip()} at 115200 baud")
        except Exception as exc:
            self.port = None
            messagebox.showerror("Serial connection", str(exc))

    def disconnect(self):
        if self.port:
            try:
                self.port.write(b"DISARM\n")
                self.port.flush()
                self.port.close()
            except Exception:
                pass
        self.port = None
        self.status.set("Disconnected")

    def close(self):
        self.disconnect()
        self.destroy()

    def send(self, command):
        if not self.port:
            self.status.set("Not connected")
            return
        try:
            command = command.strip()
            self.port.write((command + "\n").encode("ascii"))
            self._append("> " + command)
        except (OSError, UnicodeError) as exc:
            self.disconnect()
            messagebox.showerror("Serial write", str(exc))

    def send_custom(self):
        command = self.raw_command.get().strip()
        if command:
            self.send(command)
            self.raw_command.set("")

    def _append(self, text):
        self.monitor.insert("end", text + "\n")
        self.monitor.see("end")
        if int(self.monitor.index("end-1c").split(".")[0]) > 3000:
            self.monitor.delete("1.0", "500.0")

    def _poll(self):
        if self.port:
            try:
                data = self.port.read(self.port.in_waiting or 1)
                if data:
                    self.rx_buffer.extend(data)
                    while b"\n" in self.rx_buffer:
                        raw, _, tail = self.rx_buffer.partition(b"\n")
                        self.rx_buffer = bytearray(tail)
                        line = raw.decode("utf-8", "replace").strip()
                        if line:
                            self._handle_line(line)
            except OSError as exc:
                self.disconnect()
                messagebox.showerror("Serial read", str(exc))
        self.after(80, self._poll)

    def _handle_line(self, line):
        self._append(line)
        if not line.startswith("LIVE "):
            return
        try:
            data = json.loads(line[5:])
        except json.JSONDecodeError:
            return
        for item in data.get("pots", []):
            self._update_meter(self.pot_rows, item)
        for item in data.get("cvs", []):
            self._update_meter(self.cv_rows, item)
        self.encoder_text.set(f"Encoder position: {data.get('encoder', 0)}    LED ring index: {data.get('ring', 0)}")
        self.button_text.set(f"Encoder button: {'PRESSED' if data.get('encoder_button') else 'released'}    Follow button: {'PRESSED' if data.get('follow_button') else 'released'}")
        self.mode_text.set(f"A mode: {data.get('mode_a', '—')}    B mode: {data.get('mode_b', '—')}")
        switches = {item['name']: item['r'] for item in data.get('switches', [])}
        self.switch_text.set("    ".join(f"{name} {switches.get(name, 0)}" for name in SWITCHES))
        ring_index = int(data.get("ring", 0)) % 16
        for i, dot in enumerate(self.ring_dots):
            self.ring.itemconfigure(dot, fill="#ffb020" if i == ring_index else "#50505c")
        self.arm_state.set(f"Analog {'ARMED' if data.get('analog_armed') else 'disarmed'} | Trigger {'ARMED' if data.get('trigger_armed') else 'disarmed'} | Sync A/B {data.get('sync_a',0)}/{data.get('sync_b',0)}")

    @staticmethod
    def _update_meter(rows, item):
        name = item.get("name")
        if name not in rows:
            return
        bar, text = rows[name]
        percent = item.get("p", 0)
        bar["value"] = percent
        text.set(f"raw {item.get('r',0)} / {percent}% / {item.get('lo',0)}–{item.get('hi',0)} (Δ{item.get('n',0)})")

    def arm_analog(self):
        if messagebox.askyesno("Arm analogue outputs", "This enables four PWM-driven module outputs. Confirm probes and loads are safe; zero PWM is not zero jack voltage."):
            self.send("ARM ANALOG")

    def arm_trigger(self):
        if messagebox.askyesno("Arm trigger outputs", "This enables trigger output pulses on the module. Continue?"):
            self.send("ARM TRIG")

    def arm_all(self):
        if messagebox.askyesno("Arm all outputs", "This enables analogue and trigger outputs. Confirm the module is connected safely."):
            self.send("ARM ALL")

    def start_wave(self, channel, shape, frequency):
        self.send(f"WAVE {channel} {shape.get()} {frequency.get()}")

    def start_auto(self):
        self.send(f"AUTO ON {self.auto_shape.get()} {self.auto_freq.get()} {self.auto_seconds.get()}")

    def set_led(self):
        self.send(f"LED ONE {self.led_index.get()} {self.led_r.get()} {self.led_g.get()} {self.led_b.get()}")


if __name__ == "__main__":
    FrontPanelApp().mainloop()
