#!/usr/bin/env python3
"""Windows control and diagnostic GUI for TROLLfx Front Panel Test V0.3."""
import math
import time
import tkinter as tk
from tkinter import messagebox, ttk
from telemetry import PROTOCOL_VERSION, parse_protocol_line

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = list_ports = None

POT_KEYS = (("A", "TIME"), ("A", "SHAPE"), ("A", "RATIO"), ("B", "TIME"), ("B", "SHAPE"), ("B", "RATIO"))
POT_NAMES = tuple(f"{side}_{name}" for side, name in POT_KEYS)
CV_NAMES = ("A_RATIO", "A_SHAPE", "A_MOD", "A_EXP", "B_RATIO", "B_SHAPE", "B_MOD", "B_EXP")
OUTPUT_NAMES = ("A_PRI", "A_SEC", "B_PRI", "B_SEC")
OUTPUT_LABELS = ("A Primary", "A Secondary", "B Primary", "B Secondary")
SHAPES = ("sine", "triangle", "ramp", "square")
FREQUENCIES = ("0.5", "1", "2", "5", "10", "20", "50", "100")
SIDE_COLORS = {"A": "#ed8b22", "B": "#3986ed"}


class ScrollTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        canvas = tk.Canvas(self, highlightthickness=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.body = ttk.Frame(canvas, padding=8)
        window = canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")


class FrontPanelApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TROLLfx Front Panel Test V0.3")
        self.geometry("800x600")
        self.minsize(760, 540)
        self.port = None
        self.rx = bytearray()
        self.protocol_version = None
        self.packet_errors = 0
        self.paused_log = False
        self.log_lines = 0
        self.controls = {side: {} for side in ("A", "B")}
        self.switches = {side: {} for side in ("A", "B")}
        self.cv_values = {}
        self.output_values = {name: 0 for name in OUTPUT_NAMES}
        self.output_mode = "SIM"
        self.moved = "NONE"
        self.waveforms = [{"shape": "sine", "hz": 1.0, "start": time.monotonic(), "running": False} for _ in range(4)]
        self._build()
        self.refresh_ports()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(60, self._poll)
        self.after(70, self._animate)

    def _build(self):
        top = ttk.Frame(self, padding=(6, 3))
        top.pack(fill="x")
        self.port_name = tk.StringVar(value="COM9")
        self.port_box = ttk.Combobox(top, textvariable=self.port_name, width=9)
        self.port_box.pack(side="left")
        ttk.Button(top, text="Refresh", command=self.refresh_ports).pack(side="left", padx=2)
        ttk.Button(top, text="Connect", command=self.connect).pack(side="left", padx=2)
        ttk.Button(top, text="Disconnect", command=self.disconnect).pack(side="left", padx=2)
        self.status = tk.StringVar(value="Disconnected · COM9 default · FP03 required")
        ttk.Label(top, textvariable=self.status).pack(side="left", padx=5)
        self.arm_status = tk.StringVar(value="Outputs DISARMED")
        ttk.Label(top, textvariable=self.arm_status, font=("Segoe UI", 9, "bold")).pack(side="right")

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        self.pages = {}
        for name in ("Live", "CV Inputs", "LED Tests", "Waveforms", "Sync", "Serial Diagnostics"):
            page = ScrollTab(self.tabs)
            self.tabs.add(page, text=name)
            self.pages[name] = page.body
        self._build_live(self.pages["Live"])
        self._build_cvs(self.pages["CV Inputs"])
        self._build_leds(self.pages["LED Tests"])
        self._build_waves(self.pages["Waveforms"])
        self._build_sync(self.pages["Sync"])
        self._build_serial(self.pages["Serial Diagnostics"])

    def _build_live(self, parent):
        head = ttk.Frame(parent)
        head.pack(fill="x")
        focus = ttk.LabelFrame(head, text="LAST MOVED CONTROL", padding=(8, 5))
        focus.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.focus_name = tk.StringVar(value="Waiting for control movement")
        ttk.Label(focus, textvariable=self.focus_name, font=("Segoe UI", 21, "bold")).pack(anchor="w")
        self.focus_value = tk.StringVar(value="Normalized: — / 4095")
        ttk.Label(focus, textvariable=self.focus_value, font=("Segoe UI", 15)).pack(anchor="w")
        self.focus_bar = ttk.Progressbar(focus, maximum=4095)
        self.focus_bar.pack(fill="x", pady=(4, 1), ipady=4)

        ringbox = ttk.LabelFrame(head, text="16 LED ring", padding=3)
        ringbox.pack(side="right")
        self.ring = tk.Canvas(ringbox, width=150, height=140, background="#202028", highlightthickness=0)
        self.ring.pack()
        self.ring_dots = []
        for i in range(16):
            angle = i * math.tau / 16 - math.pi / 2
            x, y = 75 + 51 * math.cos(angle), 70 + 51 * math.sin(angle)
            dot = self.ring.create_oval(x-5, y-5, x+5, y+5, fill="#45454f", outline="#aaa")
            self.ring_dots.append(dot)
            self.ring.create_text(x, y, text=str(i), fill="white", font=("Segoe UI", 6))
        self.last_moved_state = tk.StringVar(value="Detection: awaiting telemetry")
        ttk.Label(parent, textvariable=self.last_moved_state).pack(anchor="w", pady=(3, 1))

        meters = ttk.LabelFrame(parent, text="Six potentiometers · clockwise increases", padding=4)
        meters.pack(fill="x", pady=2)
        self.pot_bars = {}
        for i, (side, key) in enumerate(POT_KEYS):
            col = i // 3
            row = i % 3
            cell = ttk.Frame(meters)
            cell.grid(row=row, column=col, sticky="ew", padx=3, pady=2)
            meters.columnconfigure(col, weight=1)
            name = f"{side}_{key}"
            ttk.Label(cell, text=f"{side} {key.title()}", width=10, foreground=SIDE_COLORS[side]).pack(side="left")
            bar = ttk.Progressbar(cell, maximum=4095)
            bar.pack(side="left", fill="x", expand=True, padx=3)
            value = tk.StringVar(value="—")
            ttk.Label(cell, textvariable=value, width=5, anchor="e").pack(side="right")
            self.pot_bars[name] = (bar, value)

        bottom = ttk.Frame(parent)
        bottom.pack(fill="x", pady=3)
        switchbox = ttk.LabelFrame(bottom, text="Modes and switches", padding=4)
        switchbox.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.mode_labels = {}
        for side in ("A", "B"):
            self.mode_labels[side] = tk.StringVar(value=f"{side}: —")
            ttk.Label(switchbox, textvariable=self.mode_labels[side], font=("Segoe UI", 10, "bold"), foreground=SIDE_COLORS[side]).pack(anchor="w")
        self.encoder_state = tk.StringVar(value="Encoder —  ·  Button —  ·  Follow —")
        ttk.Label(bottom, textvariable=self.encoder_state, font=("Segoe UI", 10)).pack(side="right", padx=5)

    def _build_cvs(self, parent):
        ttk.Label(parent, text="Multiplexer CV inputs · raw 12-bit ADC scale", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.cv_bars = {}
        for name in ("A_RATIO", "A_SHAPE", "A_MOD", "A_EXP", "B_RATIO", "B_SHAPE", "B_MOD", "B_EXP"):
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=name, width=14).pack(side="left")
            bar = ttk.Progressbar(row, maximum=4095)
            bar.pack(side="left", fill="x", expand=True, padx=5)
            value = tk.StringVar(value="—")
            ttk.Label(row, textvariable=value, width=6, anchor="e").pack(side="right")
            self.cv_bars[name] = (bar, value)

    def _build_leds(self, parent):
        modes = ttk.LabelFrame(parent, text="LED strip tests", padding=6)
        modes.pack(fill="x", pady=4)
        for title, cmd in (("Startup", "LED STARTUP"), ("RGB", "LED RGB"), ("Ring chase", "LED RING"), ("Live", "LED LIVE")):
            ttk.Button(modes, text=title, command=lambda c=cmd: self.send(c)).pack(side="left", padx=3)
        one = ttk.LabelFrame(parent, text="Manual pixel override", padding=6)
        one.pack(fill="x", pady=4)
        self.led_vars = {key: tk.StringVar(value=val) for key, val in (("index", "0"), ("r", "255"), ("g", "255"), ("b", "255"))}
        for key, label in (("index", "Pixel 0–22"), ("r", "R"), ("g", "G"), ("b", "B")):
            ttk.Label(one, text=label).pack(side="left", padx=(4, 1))
            ttk.Entry(one, textvariable=self.led_vars[key], width=5).pack(side="left")
        ttk.Button(one, text="Set pixel", command=self.set_led).pack(side="left", padx=4)
        self.brightness = tk.StringVar(value="80")
        ttk.Label(one, text="Brightness").pack(side="left", padx=4)
        ttk.Entry(one, textvariable=self.brightness, width=5).pack(side="left")
        ttk.Button(one, text="Apply", command=lambda: self.send(f"BRIGHTNESS {self.brightness.get()}")).pack(side="left", padx=3)

        override = ttk.LabelFrame(parent, text="Manual output indicator override", padding=6)
        override.pack(fill="x", pady=4)
        self.ind_ch = tk.StringVar(value="0")
        self.ind_level = tk.StringVar(value="255")
        ttk.Combobox(override, textvariable=self.ind_ch, values=("0", "1", "2", "3"), state="readonly", width=5).pack(side="left")
        ttk.Entry(override, textvariable=self.ind_level, width=5).pack(side="left", padx=3)
        ttk.Button(override, text="Set indicator", command=lambda: self.send(f"INDICATOR {self.ind_ch.get()} {self.ind_level.get()}")).pack(side="left", padx=3)
        ttk.Button(override, text="Return to signal meter", command=lambda: self.send("INDICATOR LIVE")).pack(side="left", padx=3)

    def _build_waves(self, parent):
        safety = ttk.LabelFrame(parent, text="Separate output arming", padding=5)
        safety.pack(fill="x", pady=3)
        ttk.Button(safety, text="ARM ANALOG", command=self.arm_analog).pack(side="left", padx=3)
        ttk.Button(safety, text="ARM TRIGGER", command=self.arm_trigger).pack(side="left", padx=3)
        ttk.Button(safety, text="DISARM", command=lambda: self.send("DISARM")).pack(side="left", padx=3)
        self.output_mode_label = tk.StringVar(value="Waiting for output telemetry")
        ttk.Label(safety, textvariable=self.output_mode_label, wraplength=280).pack(side="left", padx=6)

        self.output_bars = {}
        box = ttk.LabelFrame(parent, text="Calculated output signal levels · 0 off, full scale bright", padding=5)
        box.pack(fill="x", pady=4)
        for i, name in enumerate(OUTPUT_NAMES):
            row = ttk.Frame(box)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=OUTPUT_LABELS[i], width=15, foreground=SIDE_COLORS["A" if i < 2 else "B"]).pack(side="left")
            bar = ttk.Progressbar(row, maximum=4095)
            bar.pack(side="left", fill="x", expand=True, padx=4)
            value = tk.StringVar(value="0")
            ttk.Label(row, textvariable=value, width=5, anchor="e").pack(side="right")
            self.output_bars[name] = (bar, value)

        controls = ttk.LabelFrame(parent, text="Waveform tests", padding=5)
        controls.pack(fill="x", pady=4)
        self.wave_controls = []
        for ch, label in enumerate(OUTPUT_LABELS):
            row = ttk.Frame(controls)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=f"{ch} · {label}", width=16).pack(side="left")
            shape, hz = tk.StringVar(value="sine"), tk.StringVar(value="1")
            ttk.Combobox(row, textvariable=shape, values=SHAPES, state="readonly", width=9).pack(side="left", padx=2)
            ttk.Combobox(row, textvariable=hz, values=FREQUENCIES, state="readonly", width=6).pack(side="left", padx=2)
            ttk.Button(row, text="Start", command=lambda c=ch,s=shape,f=hz:self.start_wave(c,s,f)).pack(side="left", padx=2)
            ttk.Button(row, text="Stop", command=lambda c=ch:self.stop_wave(c)).pack(side="left", padx=2)
            self.wave_controls.append((shape, hz))
        self.preview = tk.Canvas(parent, height=132, background="#151922", highlightthickness=0)
        self.preview.pack(fill="x", pady=5)
        auto = ttk.LabelFrame(parent, text="Automatic channel cycle", padding=5)
        auto.pack(fill="x", pady=3)
        self.auto_shape, self.auto_hz, self.auto_sec = tk.StringVar(value="sine"), tk.StringVar(value="1"), tk.StringVar(value="3")
        ttk.Combobox(auto,textvariable=self.auto_shape,values=SHAPES,state="readonly",width=9).pack(side="left")
        ttk.Combobox(auto,textvariable=self.auto_hz,values=FREQUENCIES,state="readonly",width=6).pack(side="left",padx=3)
        ttk.Entry(auto,textvariable=self.auto_sec,width=4).pack(side="left")
        ttk.Label(auto,text="sec/channel").pack(side="left",padx=2)
        ttk.Button(auto,text="Start cycle",command=lambda:self.send(f"AUTO ON {self.auto_shape.get()} {self.auto_hz.get()} {self.auto_sec.get()}")).pack(side="left",padx=3)
        ttk.Button(auto,text="Stop cycle",command=lambda:self.send("AUTO OFF")).pack(side="left")
        meter = ttk.LabelFrame(parent, text="Output LED signal meter", padding=5)
        meter.pack(fill="x", pady=3)
        self.meter_mode = tk.StringVar(value="INSTANT")
        ttk.Combobox(meter,textvariable=self.meter_mode,values=("INSTANT","PEAK","RMS"),state="readonly",width=10).pack(side="left")
        ttk.Button(meter,text="Set mode",command=lambda:self.send("METER "+self.meter_mode.get())).pack(side="left",padx=3)
        self.release = tk.StringVar(value="250")
        ttk.Label(meter,text="Release ms").pack(side="left",padx=(8,2))
        ttk.Entry(meter,textvariable=self.release,width=6).pack(side="left")
        ttk.Button(meter,text="Apply",command=lambda:self.send("METER RELEASE "+self.release.get())).pack(side="left",padx=3)
        ttk.Label(parent,text="Signal indicators show calculated level after compensating for the inverting output stage; they do not measure jack voltage.",wraplength=650).pack(anchor="w",pady=4)

    def _build_sync(self, parent):
        ttk.Label(parent,text="Conditioned sync inputs only · SIG A GPIO17 · SIG B GPIO18",font=("Segoe UI",12,"bold")).pack(anchor="w",pady=5)
        self.sync_value=tk.StringVar(value="Edges A: 0    B: 0")
        ttk.Label(parent,textvariable=self.sync_value,font=("Segoe UI",20)).pack(anchor="w",pady=5)
        row=ttk.Frame(parent);row.pack(anchor="w")
        for label,cmd in (("Enable","SYNC ON"),("Disable","SYNC OFF"),("Query","SYNC?")):
            ttk.Button(row,text=label,command=lambda c=cmd:self.send(c)).pack(side="left",padx=3)
        ttk.Label(parent,text="Incoming conditioned edges flash the trigger indicator LEDs. Do not connect unconditioned signals directly to these GPIOs.",wraplength=650).pack(anchor="w",pady=8)

    def _build_serial(self, parent):
        buttons=ttk.Frame(parent);buttons.pack(fill="x",pady=2)
        for label,cmd in (("Snapshot","SNAPSHOT"),("Live report","REPORT LIVE"),("Changes only","REPORT CHANGE"),("Advanced DIAG","DIAG"),("HELP","HELP")):
            ttk.Button(buttons,text=label,command=lambda c=cmd:self.send(c)).pack(side="left",padx=2)
        self.pause_button=ttk.Button(buttons,text="Pause log",command=self.toggle_log)
        self.pause_button.pack(side="right",padx=2)
        ttk.Button(buttons,text="Clear log",command=self.clear_log).pack(side="right",padx=2)
        self.log= tk.Text(parent,height=20,wrap="word",font=("Consolas",9),undo=False)
        scroll=ttk.Scrollbar(parent,orient="vertical",command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side="left",fill="both",expand=True)
        scroll.pack(side="right",fill="y")
        cmdrow=ttk.Frame(parent);cmdrow.pack(fill="x",pady=4)
        self.command=tk.StringVar()
        ttk.Entry(cmdrow,textvariable=self.command).pack(side="left",fill="x",expand=True)
        ttk.Button(cmdrow,text="Send",command=self.send_custom).pack(side="left",padx=3)

    def refresh_ports(self):
        ports=[p.device for p in list_ports.comports()] if list_ports else []
        self.port_box["values"]=ports or ["COM9"]
        if "COM9" in ports or not ports:self.port_name.set("COM9")
        elif self.port_name.get() not in ports:self.port_name.set(ports[0])

    def connect(self):
        if serial is None:
            messagebox.showerror("Missing dependency","Install with: py -m pip install -r requirements.txt");return
        try:
            self.port=serial.Serial(self.port_name.get().strip(),115200,timeout=0,write_timeout=1)
            self.port.reset_input_buffer();self.rx.clear();self.protocol_version=None
            self.status.set("Connected · waiting for FP03 snapshot")
            self.send("SNAPSHOT");self.send("REPORT LIVE")
        except Exception as exc:
            self.port=None;messagebox.showerror("Serial connection",str(exc))

    def disconnect(self):
        if self.port:
            try:self.port.write(b"DISARM\n");self.port.close()
            except Exception:pass
        self.port=None;self.status.set("Disconnected")
    def close(self):self.disconnect();self.destroy()
    def send(self,command):
        if not self.port:self.status.set("Not connected");return
        try:self.port.write((command.strip()+"\n").encode("ascii"));self._append("> "+command.strip())
        except (OSError,UnicodeError) as exc:self.disconnect();messagebox.showerror("Serial write",str(exc))
    def send_custom(self):
        if self.command.get().strip():self.send(self.command.get());self.command.set("")
    def _append(self,line):
        if self.paused_log:return
        self.log.insert("end",line+"\n");self.log.see("end");self.log_lines+=1
        if self.log_lines>2000:self.log.delete("1.0","500.0");self.log_lines-=500
    def clear_log(self):self.log.delete("1.0","end");self.log_lines=0
    def toggle_log(self):
        self.paused_log=not self.paused_log
        self.pause_button.configure(text="Resume log" if self.paused_log else "Pause log")
    def _poll(self):
        if self.port:
            try:
                self.rx.extend(self.port.read(self.port.in_waiting or 1))
                while b"\n" in self.rx:
                    raw,_,tail=self.rx.partition(b"\n");self.rx=bytearray(tail)
                    line=raw.decode("utf-8","replace").strip()
                    if line:self._handle_line(line)
            except OSError as exc:self.disconnect();messagebox.showerror("Serial read",str(exc))
        self.after(60,self._poll)

    def _handle_line(self,line):
        self._append(line)
        try:packet=parse_protocol_line(line)
        except ValueError:self.packet_errors+=1;return
        kind=packet["type"]
        if kind=="protocol":
            self.protocol_version=packet["version"]
            if self.protocol_version==PROTOCOL_VERSION:self.status.set("Connected · FP03 protocol matched")
            else:self.status.set(f"Protocol mismatch · expected {PROTOCOL_VERSION}, got {self.protocol_version}")
            return
        if kind=="legacy":
            self.status.set(f"Firmware/GUI mismatch · received legacy telemetry; need {PROTOCOL_VERSION}")
            return
        if kind=="text":return
        if self.protocol_version!=PROTOCOL_VERSION:
            self.status.set("Telemetry received before FP03 handshake" if self.protocol_version is None else "Firmware/GUI protocol mismatch")
            return
        if kind=="controls":
            side=packet["side"]
            self.controls[side]=packet
            for key in ("TIME","SHAPE","RATIO"):
                name=f"{side}_{key}";value=packet[key]
                bar,label=self.pot_bars[name];bar["value"]=value;label.set(str(value))
            self.switches[side]={"SW1":packet["SW1"],"SW2":packet["SW2"]}
            self.mode_labels[side].set(f"{side}: {packet['MODE']} · SW1={packet['SW1']} SW2={packet['SW2']}")
            self._refresh_focus()
        elif kind=="encoder":
            self.encoder_state.set(f"Encoder {packet['position']}  ·  Button {'DOWN' if packet['button'] else 'UP'}  ·  Follow {'DOWN' if packet['follow'] else 'UP'}")
        elif kind=="cv":
            self.cv_values=packet
            for key,(bar,label) in self.cv_bars.items():bar["value"]=packet[key];label.set(str(packet[key]))
        elif kind=="outputs":
            self.output_mode=packet["mode"]
            for key in OUTPUT_NAMES:
                self.output_values[key]=packet[key]
                bar,label=self.output_bars[key];bar["value"]=packet[key];label.set(str(packet[key]))
            if packet["mode"]=="SIM":self.output_mode_label.set(f"SIMULATED · outputs disarmed · {packet['meter']} meter")
            else:self.output_mode_label.set(f"PWM COMMAND · armed · calculated signal after inversion · {packet['meter']} meter")
        elif kind=="moved":
            self.moved=packet["name"];self._refresh_focus()
        elif kind=="state":
            self.arm_status.set(f"Analog {'ARMED' if packet['analog'] else 'DISARMED'} · Trigger {'ARMED' if packet['trigger'] else 'DISARMED'}")
        elif kind=="sync":self.sync_value.set(f"Edges A: {packet['a']}    B: {packet['b']}")

    def _refresh_focus(self):
        name=self.moved
        if name in POT_NAMES:
            side,key=name.split("_",1);value=self.controls.get(side,{}).get(key)
            if value is None:return
            self.focus_name.set(name.replace("_"," "));self.focus_value.set(f"Normalized: {value} / 4095")
            self.focus_bar["value"]=value;self.last_moved_state.set("Last moved · potentiometer polarity normalized clockwise")
            self._draw_ring((value*16)//4096,SIDE_COLORS[side]);return
        if name in CV_NAMES:
            value=self.cv_values.get(name,0);self.focus_name.set(name.replace("_"," "));self.focus_value.set(f"CV ADC: {value} / 4095")
            self.focus_bar["value"]=value;self.last_moved_state.set("Last moved · CV input");self._draw_ring((value*16)//4096,"#35c8a5");return
        if name=="ENCODER":
            self.focus_name.set("ENCODER");self.focus_value.set(self.encoder_state.get());self.last_moved_state.set("Last moved · clockwise increases")
            try:position=int(self.encoder_state.get().split()[1])
            except (ValueError,IndexError):position=0
            self.focus_bar["value"]=(position%64)*4095//63;self._draw_ring((position//4)%16,"#b66cff");return
        self.focus_name.set(name.replace("_"," ") if name!="NONE" else "Waiting for control movement")
        self.focus_value.set("Normalized: — / 4095");self.focus_bar["value"]=0
        self.last_moved_state.set("Detection active · no control movement yet" if name=="NONE" else "Button or switch activity")

    def _draw_ring(self,index,color):
        for i,dot in enumerate(self.ring_dots):self.ring.itemconfigure(dot,fill=color if i==int(index)%16 else "#45454f")
    def _animate(self):
        canvas=self.preview;canvas.delete("all");width=max(canvas.winfo_width(),200);height=max(canvas.winfo_height(),100)
        for ch,state in enumerate(self.waveforms):
            base=7+ch*(height-14)/4;amplitude=max(8,(height-24)/8);color=("#ed8b22","#ffc444","#3986ed","#5ab9ff")[ch]
            points=[]
            for x in range(0,width,3):
                phase=((time.monotonic()-state["start"])*state["hz"]+x/max(width,1)*1.5)%1
                if state["shape"]=="sine":v=.5+.5*math.sin(math.tau*phase)
                elif state["shape"]=="triangle":v=2*phase if phase<.5 else 2-2*phase
                elif state["shape"]=="ramp":v=phase
                else:v=1 if phase<.5 else 0
                points.extend((x,base+amplitude*(1-2*v)))
            if points:canvas.create_line(*points,fill=color,width=2)
            canvas.create_text(34,base+amplitude,text=f"{ch} {OUTPUT_LABELS[ch]}",fill=color,anchor="w")
            canvas.create_text(width-3,base+amplitude,text="preview" if state["running"] else "stopped",fill="#ddd",anchor="e")
        self.after(70,self._animate)
    def arm_analog(self):
        if messagebox.askyesno("Arm analogue outputs","Enable four PWM output commands? Indicator values are calculated, not measured; PWM zero is not assumed to mean zero jack voltage."):self.send("ARM ANALOG")
    def arm_trigger(self):
        if messagebox.askyesno("Arm trigger outputs","Enable trigger pulses?"):self.send("ARM TRIG")
    def start_wave(self,ch,shape,hz):
        self.waveforms[ch]={"shape":shape.get(),"hz":float(hz.get()),"start":time.monotonic(),"running":True}
        self.send(f"WAVE {ch} {shape.get()} {hz.get()}")
    def stop_wave(self,ch):self.waveforms[ch]["running"]=False;self.send(f"STOP {ch}")
    def set_led(self):
        v=self.led_vars;self.send(f"LED ONE {v['index'].get()} {v['r'].get()} {v['g'].get()} {v['b'].get()}")


if __name__=="__main__":FrontPanelApp().mainloop()
