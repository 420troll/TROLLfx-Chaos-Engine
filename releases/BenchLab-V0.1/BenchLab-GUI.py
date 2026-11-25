#!/usr/bin/env python3
"""Windows serial control and manual calibration log for TROLLfx Bench Lab."""
import csv
import datetime as dt
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None


CHANNELS = ("A Primary", "A Secondary", "B Primary", "B Secondary")
WAVES = ("sine", "triangle", "saw", "square", "stair", "ramp")


def component_candidate(rin, desired_span, pwm_span, ref_voltage, desired_offset):
    if rin <= 0 or desired_span <= 0 or pwm_span <= 0 or ref_voltage < 0 or desired_offset <= 0:
        raise ValueError("Rin, spans, and offset must be positive; reference magnitude cannot be negative")
    rf = rin * desired_span / pwm_span
    ref_leg = rf * ref_voltage / desired_offset
    return rf, ref_leg


class BenchLabApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TROLLfx Bench Lab V0.1")
        self.geometry("1020x760")
        self.minsize(900, 650)
        self.port = None
        self._ui()
        self.refresh_ports()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(80, self._poll)

    def _ui(self):
        conn = ttk.LabelFrame(self, text="USB serial (firmware: 115200 baud)")
        conn.pack(fill="x", padx=8, pady=6)
        self.port_name = tk.StringVar(value="COM9")
        self.port_box = ttk.Combobox(conn, textvariable=self.port_name, width=18)
        self.port_box.pack(side="left", padx=4, pady=4)
        ttk.Button(conn, text="Refresh", command=self.refresh_ports).pack(side="left", padx=4)
        ttk.Button(conn, text="Connect", command=self.connect).pack(side="left", padx=4)
        ttk.Button(conn, text="Disconnect", command=self.disconnect).pack(side="left", padx=4)
        self.status = tk.StringVar(value="Disconnected; COM9 is preselected")
        ttk.Label(conn, textvariable=self.status).pack(side="left", padx=12)

        ctl = ttk.LabelFrame(self, text="Output and waveform controls")
        ctl.pack(fill="x", padx=8, pady=6)
        self.channel = tk.StringVar(value=CHANNELS[0])
        ttk.Label(ctl, text="Channel").grid(row=0, column=0, sticky="e", padx=4)
        ttk.Combobox(ctl, textvariable=self.channel, values=CHANNELS, state="readonly", width=18).grid(row=0, column=1, sticky="w")
        ttk.Button(ctl, text="ARM outputs", command=self.arm).grid(row=0, column=2, padx=4)
        ttk.Button(ctl, text="DISARM", command=lambda: self.send("DISARM")).grid(row=0, column=3, padx=4)
        ttk.Button(ctl, text="INFO", command=lambda: self.send("INFO")).grid(row=0, column=4, padx=4)
        ttk.Button(ctl, text="HELP", command=lambda: self.send("HELP")).grid(row=0, column=5, padx=4)

        ttk.Label(ctl, text="Resolution bits").grid(row=1, column=0, sticky="e", padx=4, pady=5)
        self.bits = tk.StringVar(value="11")
        ttk.Combobox(ctl, textvariable=self.bits, values=[str(i) for i in range(6, 12)], state="readonly", width=8).grid(row=1, column=1, sticky="w")
        ttk.Button(ctl, text="Set RES", command=lambda: self.send("RES " + self.bits.get())).grid(row=1, column=2, sticky="w")
        ttk.Label(ctl, text="Carrier Hz").grid(row=1, column=3, sticky="e")
        self.carrier = tk.StringVar(value="44100")
        ttk.Entry(ctl, textvariable=self.carrier, width=12).grid(row=1, column=4, sticky="w")
        ttk.Button(ctl, text="Set CARRIER", command=lambda: self.send("CARRIER " + self.carrier.get())).grid(row=1, column=5, sticky="w")

        ttk.Label(ctl, text="Update Hz").grid(row=2, column=0, sticky="e", padx=4)
        self.update_hz = tk.StringVar(value="1000")
        ttk.Entry(ctl, textvariable=self.update_hz, width=12).grid(row=2, column=1, sticky="w")
        ttk.Button(ctl, text="Set UPDATE", command=lambda: self.send("UPDATE " + self.update_hz.get())).grid(row=2, column=2, sticky="w")
        ttk.Label(ctl, text="DC %").grid(row=2, column=3, sticky="e")
        self.percent = tk.StringVar(value="50")
        ttk.Entry(ctl, textvariable=self.percent, width=12).grid(row=2, column=4, sticky="w")
        ttk.Button(ctl, text="Apply DC", command=lambda: self.send(f"DC {self.ch()} {self.percent.get()}")).grid(row=2, column=5, sticky="w")

        ttk.Label(ctl, text="Raw code").grid(row=3, column=0, sticky="e", padx=4)
        self.raw = tk.StringVar(value="1024")
        ttk.Entry(ctl, textvariable=self.raw, width=12).grid(row=3, column=1, sticky="w")
        ttk.Button(ctl, text="Apply RAW", command=lambda: self.send(f"RAW {self.ch()} {self.raw.get()}")).grid(row=3, column=2, sticky="w")
        self.wave = tk.StringVar(value="sine")
        ttk.Combobox(ctl, textvariable=self.wave, values=WAVES, state="readonly", width=12).grid(row=3, column=3, sticky="e")
        self.wavefreq = tk.StringVar(value="100")
        ttk.Entry(ctl, textvariable=self.wavefreq, width=12).grid(row=3, column=4, sticky="w")
        ttk.Button(ctl, text="Start WAVE", command=self.start_wave).grid(row=3, column=5, sticky="w")

        ttk.Label(ctl, text="Sweep Hz start / stop / duration ms").grid(row=4, column=0, columnspan=2, sticky="e", padx=4)
        self.sweep_start = tk.StringVar(value="1")
        self.sweep_stop = tk.StringVar(value="400")
        self.sweep_ms = tk.StringVar(value="10000")
        for col, var in ((2, self.sweep_start), (3, self.sweep_stop), (4, self.sweep_ms)):
            ttk.Entry(ctl, textvariable=var, width=12).grid(row=4, column=col, sticky="w")
        ttk.Button(ctl, text="Start SWEEP", command=self.start_sweep).grid(row=4, column=5, sticky="w")

        ttk.Button(ctl, text="STOP selected", command=lambda: self.send(f"STOP {self.ch()}")).grid(row=5, column=0, padx=4, pady=5)
        ttk.Button(ctl, text="STOP ALL", command=lambda: self.send("STOP ALL")).grid(row=5, column=1, padx=4)
        ttk.Button(ctl, text="RIPPLE DC", command=lambda: self.send(f"RIPPLE {self.ch()}")).grid(row=5, column=2, padx=4)
        ttk.Button(ctl, text="CROSSTALK", command=lambda: self.send(f"CROSSTALK {self.ch()}")).grid(row=5, column=3, padx=4)
        ttk.Button(ctl, text="SYNC ON", command=self.sync_on).grid(row=5, column=4, padx=4)
        ttk.Button(ctl, text="SYNC OFF", command=lambda: self.send("SYNC OFF")).grid(row=5, column=5, padx=4)
        ttk.Button(ctl, text="SYNC?", command=lambda: self.send("SYNC?")).grid(row=5, column=6, padx=4)

        cal = ttk.LabelFrame(self, text="Manual calibration log — enter measured output-jack voltage (V); this does not write device storage")
        cal.pack(fill="x", padx=8, pady=6)
        self.measurements = []
        for i, pct in enumerate((0, 25, 50, 75, 100)):
            ttk.Label(cal, text=f"DC {pct}% (V)").grid(row=0, column=i * 2, padx=3, pady=5)
            value = tk.StringVar()
            self.measurements.append(value)
            ttk.Entry(cal, textvariable=value, width=10).grid(row=0, column=i * 2 + 1, padx=3)
        self.cross = tk.StringVar()
        ttk.Label(cal, text="Crosstalk peak V").grid(row=1, column=0, columnspan=2, sticky="e")
        ttk.Entry(cal, textvariable=self.cross, width=10).grid(row=1, column=2, sticky="w")
        self.ripple = tk.StringVar()
        ttk.Label(cal, text="Ripple p-p V").grid(row=1, column=3, sticky="e")
        ttk.Entry(cal, textvariable=self.ripple, width=10).grid(row=1, column=4, sticky="w")
        ttk.Button(cal, text="Save CSV record", command=self.save_record).grid(row=1, column=7, padx=5)

        calc = ttk.LabelFrame(self, text="Ideal inverting-stage component estimate")
        calc.pack(fill="x", padx=8, pady=6)
        self.rin = tk.StringVar(value="10000")
        self.span = tk.StringVar(value="1")
        self.pwmspan = tk.StringVar(value="3.3")
        self.ref = tk.StringVar(value="10")
        self.offset = tk.StringVar(value="1")
        for i, (label, var) in enumerate((("Rin Ω", self.rin), ("Output span V", self.span), ("PWM span V", self.pwmspan), ("Reference magnitude V", self.ref), ("Offset V", self.offset))):
            ttk.Label(calc, text=label).grid(row=0, column=i * 2, padx=3)
            ttk.Entry(calc, textvariable=var, width=10).grid(row=0, column=i * 2 + 1, padx=3)
        ttk.Button(calc, text="Calculate", command=self.calculate).grid(row=1, column=0, padx=4, pady=5)
        self.calc_out = tk.StringVar(value="Calculated ideal values appear here; verify against the actual board")
        ttk.Label(calc, textvariable=self.calc_out).grid(row=1, column=1, columnspan=9, sticky="w")

        log = ttk.LabelFrame(self, text="Device response")
        log.pack(fill="both", expand=True, padx=8, pady=6)
        self.output = tk.Text(log, height=10, wrap="word")
        self.output.pack(fill="both", expand=True, padx=4, pady=4)

    def ch(self):
        return CHANNELS.index(self.channel.get())

    def refresh_ports(self):
        if list_ports is None:
            self.port_box["values"] = ["COM9"]
            self.status.set("Install pyserial to connect; COM9 is preselected")
            return
        ports = [p.device for p in list_ports.comports()]
        self.port_box["values"] = ports
        if "COM9" in ports:
            self.port_name.set("COM9")
        elif ports and self.port_name.get() not in ports:
            self.port_name.set(ports[0])
        elif not ports:
            self.port_name.set("COM9")
            self.status.set("No serial port detected; COM9 is ready for manual selection")

    def connect(self):
        if serial is None:
            messagebox.showerror("Missing dependency", "Install pyserial: py -m pip install -r requirements.txt")
            return
        try:
            self.port = serial.Serial(self.port_name.get().strip(), 115200, timeout=0, write_timeout=1)
            self.port.reset_input_buffer()
            self.status.set(f"Connected to {self.port_name.get().strip()} at 115200 baud")
        except Exception as exc:
            self.port = None
            messagebox.showerror("Serial error", str(exc))

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
            self.output.insert("end", "> " + command + "\n")
            self.output.see("end")
        except (OSError, UnicodeError) as exc:
            self.status.set("Serial write failed; disconnected")
            messagebox.showerror("Serial error", str(exc))
            self.disconnect()

    def arm(self):
        if messagebox.askyesno("Arm outputs", "This enables all four analog outputs. Verify scope probes and loads first. Continue?"):
            self.send("ARM")

    def sync_on(self):
        if messagebox.askyesno("Enable sync monitor", "Use only the module's conditioned SIG inputs at J6/J14. Never connect modular-level signals directly to GPIO17/18. Continue?"):
            self.send("SYNC ON")

    def _poll(self):
        if self.port:
            try:
                waiting = self.port.in_waiting
                if waiting:
                    self.output.insert("end", self.port.read(waiting).decode("utf-8", "replace"))
                    self.output.see("end")
            except OSError as exc:
                self.status.set("Serial read failed; disconnected")
                self.disconnect()
                messagebox.showerror("Serial error", str(exc))
        self.after(80, self._poll)

    def start_wave(self):
        self.send(f"WAVE {self.ch()} {self.wave.get()} {self.wavefreq.get()}")

    def start_sweep(self):
        self.send(f"SWEEP {self.ch()} {self.sweep_start.get()} {self.sweep_stop.get()} {self.sweep_ms.get()}")

    def calculate(self):
        try:
            rf, leg = component_candidate(*(float(x.get()) for x in (self.rin, self.span, self.pwmspan, self.ref, self.offset)))
            self.calc_out.set(f"Feedback resistor ≈ {rf:.1f} Ω; reference-leg total ≈ {leg:.1f} Ω")
        except ValueError as exc:
            messagebox.showerror("Inputs", str(exc))

    def save_record(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        values = [v.get().strip() for v in self.measurements]
        try:
            with open(path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                if f.tell() == 0:
                    writer.writerow(["utc", "channel", "resolution_bits", "carrier_requested_hz", "dc_0_v", "dc_25_v", "dc_50_v", "dc_75_v", "dc_100_v", "crosstalk_peak_v", "ripple_pp_v"])
                writer.writerow([dt.datetime.now(dt.timezone.utc).isoformat(), self.channel.get(), self.bits.get(), self.carrier.get(), *values, self.cross.get(), self.ripple.get()])
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc))


if __name__ == "__main__":
    BenchLabApp().mainloop()
