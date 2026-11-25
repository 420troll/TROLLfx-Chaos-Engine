#!/usr/bin/env python3
"""Compact seven-tab Windows diagnostic GUI for Front Panel Test V0.2."""
import math
import time
import tkinter as tk
from tkinter import messagebox, ttk
from telemetry import parse_live_line

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = list_ports = None

POTS = ("A_TIME", "A_RATIO", "A_SHAPE", "B_TIME", "B_RATIO", "B_SHAPE")
CVS = ("A_RATIO_CV", "A_SHAPE_CV", "A_MOD_CV", "A_EXP_CV", "B_RATIO_CV", "B_SHAPE_CV", "B_MOD_CV", "B_EXP_CV")
SWITCHES = ("A_SW1", "A_SW2", "B_SW1", "B_SW2")
OUTPUTS = ("A Primary", "A Secondary", "B Primary", "B Secondary")
SHAPES = ("sine", "triangle", "ramp", "square")
FREQUENCIES = ("0.5", "1", "2", "5")
ALL_INPUTS = POTS + CVS + SWITCHES
COLORS = {"A": "#ff9d24", "B": "#3488ff", "A_RATIO_CV": "#36d66b", "A_SHAPE_CV": "#08c7ba", "A_MOD_CV": "#e4d339", "A_EXP_CV": "#ff55c8", "B_RATIO_CV": "#7de65c", "B_SHAPE_CV": "#32d4ed", "B_MOD_CV": "#ba77ff", "B_EXP_CV": "#f06c43", "ENCODER": "#b56cff"}


class ScrollTab(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        canvas = tk.Canvas(self, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
        self.body = ttk.Frame(canvas, padding=8)
        win = canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(win, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")


class FrontPanelApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TROLLfx Front Panel Test V0.2")
        self.geometry("800x600")
        self.minsize(760, 540)
        self.port = None
        self.rx_buffer = bytearray()
        self.values = {}
        self.previous_raw = {}
        self.selected = "A_TIME"
        self.locked = False
        self.history = []
        self.last_packet_at = None
        self.last_seq = None
        self.packet_count = 0
        self.parse_errors = 0
        self.waveforms = [{"shape": "sine", "hz": 1.0, "start": time.monotonic(), "running": False} for _ in OUTPUTS]
        self._build()
        self.refresh_ports()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(80, self._poll)
        self.after(70, self._animate)
        self.after(250, self._health)

    def _build(self):
        top = ttk.Frame(self, padding=(6, 4))
        top.pack(fill="x")
        self.port_name = tk.StringVar(value="COM9")
        self.port_box = ttk.Combobox(top, textvariable=self.port_name, width=10)
        self.port_box.pack(side="left")
        ttk.Button(top, text="Refresh", command=self.refresh_ports).pack(side="left", padx=3)
        ttk.Button(top, text="Connect", command=self.connect).pack(side="left", padx=3)
        ttk.Button(top, text="Disconnect", command=self.disconnect).pack(side="left", padx=3)
        self.status = tk.StringVar(value="Disconnected · COM9 preselected")
        ttk.Label(top, textvariable=self.status).pack(side="left", padx=6)
        self.arm_state = tk.StringVar(value="Analog: DISARMED · Trigger: DISARMED")
        ttk.Label(top, textvariable=self.arm_state, foreground="#a52a2a").pack(side="right", padx=4)

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=5, pady=(0, 5))
        self.tab_frames = {}
        for name in ("Live activity", "All inputs", "LED tests", "Waveform outputs", "Encoder and buttons", "Sync", "Serial diagnostics"):
            page = ScrollTab(self.tabs)
            self.tabs.add(page, text=name)
            self.tab_frames[name] = page.body
        self._build_live(self.tab_frames["Live activity"])
        self._build_inputs(self.tab_frames["All inputs"])
        self._build_leds(self.tab_frames["LED tests"])
        self._build_outputs(self.tab_frames["Waveform outputs"])
        self._build_encoder(self.tab_frames["Encoder and buttons"])
        self._build_sync(self.tab_frames["Sync"])
        self._build_serial(self.tab_frames["Serial diagnostics"])

    def _build_live(self, p):
        selector = ttk.Frame(p)
        selector.pack(fill="x")
        self.live_name = tk.StringVar(value="A_TIME")
        self.live_lock = tk.BooleanVar(value=False)
        ttk.Label(selector, text="Watch:").pack(side="left")
        ttk.Combobox(selector, textvariable=self.live_name, values=ALL_INPUTS + ("ENCODER",), state="readonly", width=18).pack(side="left", padx=4)
        ttk.Checkbutton(selector, text="Lock selection", variable=self.live_lock, command=self._lock_changed).pack(side="left", padx=5)
        self.detect = tk.StringVar(value="Waiting for telemetry")
        ttk.Label(selector, textvariable=self.detect).pack(side="right")
        self.big_name = tk.StringVar(value="A_TIME")
        ttk.Label(p, textvariable=self.big_name, font=("Segoe UI", 24, "bold")).pack(anchor="w", pady=(8, 0))
        self.live_values = tk.StringVar(value="Raw ADC: —     Percent: —%     Observed min/max: — / —")
        ttk.Label(p, textvariable=self.live_values, font=("Segoe UI", 12)).pack(anchor="w", pady=3)
        self.meter = ttk.Progressbar(p, maximum=100, mode="determinate")
        self.meter.pack(fill="x", ipady=8, pady=5)
        lower = ttk.Frame(p)
        lower.pack(fill="both", expand=True, pady=5)
        ringbox = ttk.LabelFrame(lower, text="Physical 16 LED ring", padding=5)
        ringbox.pack(side="left", fill="y", padx=(0, 6))
        self.ring = tk.Canvas(ringbox, width=220, height=220, background="#202028", highlightthickness=0)
        self.ring.pack()
        self.ring_dots = []
        for i in range(16):
            angle = (i / 16) * math.tau - math.pi / 2
            x, y = 110 + 78 * math.cos(angle), 110 + 78 * math.sin(angle)
            dot = self.ring.create_oval(x-8, y-8, x+8, y+8, fill="#50505c", outline="#aaa")
            self.ring_dots.append(dot)
            self.ring.create_text(x, y, text=str(i), fill="white", font=("Segoe UI", 7))
        right = ttk.Frame(lower)
        right.pack(side="left", fill="both", expand=True)
        self.history_label = tk.StringVar(value="Recent movement: waiting")
        ttk.Label(right, textvariable=self.history_label, wraplength=400).pack(anchor="nw", pady=5)
        self.history_canvas = tk.Canvas(right, height=100, background="#f7f7f7", highlightthickness=1, highlightbackground="#bbb")
        self.history_canvas.pack(fill="x", pady=4)
        ttk.Label(right, text="A controls orange · B controls blue · CV inputs use distinct colours · encoder purple", wraplength=400).pack(anchor="nw", pady=4)

    def _build_inputs(self, p):
        ttk.Label(p, text="Live ADC readings · raw 0–4095 and normalized percent", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        self.input_rows = {}
        for group, names in (("Potentiometers", POTS), ("CV inputs", CVS), ("Mode switches (mux ADC)", SWITCHES)):
            box = ttk.LabelFrame(p, text=group, padding=5)
            box.pack(fill="x", pady=4)
            for name in names:
                row = ttk.Frame(box)
                row.pack(fill="x", pady=1)
                ttk.Label(row, text=name, width=17).pack(side="left")
                bar = ttk.Progressbar(row, maximum=100)
                bar.pack(side="left", fill="x", expand=True, padx=4)
                val = tk.StringVar(value="—")
                ttk.Label(row, textvariable=val, width=29).pack(side="right")
                self.input_rows[name] = (bar, val)
        self.direct_adc = tk.StringVar(value="GPIO27/28 comparison pending")
        ttk.Label(p, textvariable=self.direct_adc).pack(anchor="w", pady=5)

    def _build_leds(self, p):
        box = ttk.LabelFrame(p, text="LED modes", padding=6); box.pack(fill="x", pady=4)
        for title, cmd in (("Startup", "LED STARTUP"), ("RGB cycle", "LED RGB"), ("Ring chase", "LED RING"), ("Live", "LED LIVE")):
            ttk.Button(box, text=title, command=lambda c=cmd: self.send(c)).pack(side="left", padx=3)
        individual = ttk.LabelFrame(p, text="Individual LED / brightness", padding=6); individual.pack(fill="x", pady=4)
        self.led_index = tk.StringVar(value="0"); self.led_r=tk.StringVar(value="255"); self.led_g=tk.StringVar(value="255"); self.led_b=tk.StringVar(value="255")
        for label, var, width in (("Pixel 0–22",self.led_index,5),("R",self.led_r,4),("G",self.led_g,4),("B",self.led_b,4)):
            ttk.Label(individual,text=label).pack(side="left",padx=(3,1));ttk.Entry(individual,textvariable=var,width=width).pack(side="left")
        ttk.Button(individual,text="Set LED",command=self.set_led).pack(side="left",padx=4)
        self.brightness=tk.StringVar(value="80");ttk.Label(individual,text="Brightness").pack(side="left",padx=3);ttk.Entry(individual,textvariable=self.brightness,width=5).pack(side="left");ttk.Button(individual,text="Apply",command=lambda:self.send("BRIGHTNESS "+self.brightness.get())).pack(side="left",padx=3)
        out = ttk.LabelFrame(p, text="Output indicator LEDs", padding=6);out.pack(fill="x",pady=4)
        self.indicator=tk.StringVar(value="0");self.indicator_level=tk.StringVar(value="255")
        ttk.Combobox(out,textvariable=self.indicator,values=("0","1","2","3"),state="readonly",width=4).pack(side="left")
        ttk.Entry(out,textvariable=self.indicator_level,width=5).pack(side="left",padx=3)
        ttk.Button(out,text="Test indicator",command=lambda:self.send(f"INDICATOR {self.indicator.get()} {self.indicator_level.get()}")).pack(side="left",padx=3)
        ttk.Button(out,text="Indicator live",command=lambda:self.send("INDICATOR LIVE")).pack(side="left",padx=3)

    def _build_outputs(self, p):
        safety=ttk.LabelFrame(p,text="Outputs are independently disarmed on startup",padding=5);safety.pack(fill="x",pady=3)
        ttk.Button(safety,text="ARM ANALOG",command=self.arm_analog).pack(side="left",padx=3);ttk.Button(safety,text="ARM TRIGGER",command=self.arm_trigger).pack(side="left",padx=3);ttk.Button(safety,text="DISARM ALL",command=lambda:self.send("DISARM")).pack(side="left",padx=3)
        ttk.Label(safety,text="PWM code 0 is not assumed to equal zero jack voltage.",wraplength=250).pack(side="left",padx=8)
        box=ttk.LabelFrame(p,text="Four independent channels",padding=5);box.pack(fill="x",pady=4)
        self.output_controls=[]
        for ch,name in enumerate(OUTPUTS):
            row=ttk.Frame(box);row.pack(fill="x",pady=2)
            ttk.Label(row,text=f"{ch} · {name}",width=19).pack(side="left")
            shape=tk.StringVar(value="sine");freq=tk.StringVar(value="1")
            ttk.Combobox(row,textvariable=shape,values=SHAPES,state="readonly",width=9).pack(side="left",padx=2)
            ttk.Combobox(row,textvariable=freq,values=FREQUENCIES,state="readonly",width=5).pack(side="left",padx=2)
            ttk.Button(row,text="Preview + start",command=lambda c=ch,s=shape,f=freq:self.start_wave(c,s,f)).pack(side="left",padx=2)
            ttk.Button(row,text="Stop",command=lambda c=ch:self.stop_wave(c)).pack(side="left",padx=2)
            self.output_controls.append((shape,freq))
        ttk.Label(p,text="Software waveform preview (digital PWM values; independent of output arming)").pack(anchor="w",pady=(8,2))
        self.wave_canvas=tk.Canvas(p,height=150,background="#151922",highlightthickness=0);self.wave_canvas.pack(fill="x",expand=True)
        auto=ttk.LabelFrame(p,text="Automatic output cycle",padding=5);auto.pack(fill="x",pady=4)
        self.auto_shape=tk.StringVar(value="sine");self.auto_freq=tk.StringVar(value="1");self.auto_seconds=tk.StringVar(value="3")
        ttk.Combobox(auto,textvariable=self.auto_shape,values=SHAPES,state="readonly",width=9).pack(side="left");ttk.Combobox(auto,textvariable=self.auto_freq,values=FREQUENCIES,state="readonly",width=5).pack(side="left",padx=3);ttk.Entry(auto,textvariable=self.auto_seconds,width=4).pack(side="left");ttk.Label(auto,text="sec/channel").pack(side="left");ttk.Button(auto,text="Start cycle",command=lambda:self.send(f"AUTO ON {self.auto_shape.get()} {self.auto_freq.get()} {self.auto_seconds.get()}")).pack(side="left",padx=4);ttk.Button(auto,text="Stop cycle",command=lambda:self.send("AUTO OFF")).pack(side="left")

    def _build_encoder(self,p):
        self.encoder_text=tk.StringVar(value="Position: —")
        ttk.Label(p,textvariable=self.encoder_text,font=("Segoe UI",20,"bold")).pack(anchor="w",pady=7)
        self.button_text=tk.StringVar(value="Encoder button: —     Follow: —")
        ttk.Label(p,textvariable=self.button_text,font=("Segoe UI",14)).pack(anchor="w",pady=4)
        self.mode_text=tk.StringVar(value="A mode: —     B mode: —")
        ttk.Label(p,textvariable=self.mode_text,font=("Segoe UI",14)).pack(anchor="w",pady=4)
        self.switch_text=tk.StringVar(value="Switches: —")
        ttk.Label(p,textvariable=self.switch_text,wraplength=600).pack(anchor="w",pady=4)

    def _build_sync(self,p):
        ttk.Label(p,text="Conditioned sync inputs only (SIG_IN_A GPIO17, SIG_IN_B GPIO18)",font=("Segoe UI",12,"bold")).pack(anchor="w",pady=5)
        self.sync_text=tk.StringVar(value="Edges A: 0     B: 0")
        ttk.Label(p,textvariable=self.sync_text,font=("Segoe UI",20)).pack(anchor="w",pady=6)
        row=ttk.Frame(p);row.pack(anchor="w")
        for label,cmd in (("Enable counting","SYNC ON"),("Disable","SYNC OFF"),("Query","SYNC?")):
            ttk.Button(row,text=label,command=lambda c=cmd:self.send(c)).pack(side="left",padx=4)
        ttk.Label(p,text="Connect only signals already conditioned for the module's sync input. Incoming edges flash the trigger indicator LEDs.",wraplength=620).pack(anchor="w",pady=10)

    def _build_serial(self,p):
        self.health=tk.StringVar(value="Packets: 0 · parse errors: 0 · last packet age: —")
        ttk.Label(p,textvariable=self.health,font=("Segoe UI",11,"bold")).pack(anchor="w",pady=3)
        actions=ttk.Frame(p);actions.pack(fill="x")
        for label,cmd in (("HELP","HELP"),("INFO","INFO"),("STATS","STATS"),("Reset ranges","RESET STATS"),("ADC DIRECT","ADC DIRECT"),("SYNC?","SYNC?")):
            ttk.Button(actions,text=label,command=lambda c=cmd:self.send(c)).pack(side="left",padx=2)
        monitorbox=ttk.LabelFrame(p,text="Serial monitor",padding=4);monitorbox.pack(fill="both",expand=True,pady=4)
        self.monitor=tk.Text(monitorbox,height=12,wrap="none",font=("Consolas",9));scroll=ttk.Scrollbar(monitorbox,orient="vertical",command=self.monitor.yview);self.monitor.configure(yscrollcommand=scroll.set);self.monitor.pack(side="left",fill="both",expand=True);scroll.pack(side="right",fill="y")
        cmdrow=ttk.Frame(p);cmdrow.pack(fill="x")
        self.raw_command=tk.StringVar();ttk.Entry(cmdrow,textvariable=self.raw_command).pack(side="left",fill="x",expand=True);ttk.Button(cmdrow,text="Send command",command=self.send_custom).pack(side="left",padx=4)
        self.direct_debug=tk.StringVar(value="Direct ADC diagnostic: compare Arduino and RP2040 SDK values for GPIO27/28.")
        ttk.Label(p,textvariable=self.direct_debug,wraplength=620).pack(anchor="w",pady=4)

    def refresh_ports(self):
        if list_ports is None:
            self.port_box["values"]=["COM9"];self.status.set("Install pyserial · COM9 preselected");return
        ports=[port.device for port in list_ports.comports()];self.port_box["values"]=ports
        if "COM9" in ports or not ports:self.port_name.set("COM9")
        elif self.port_name.get() not in ports:self.port_name.set(ports[0])
        if not ports:self.status.set("No COM device found · COM9 remains editable")

    def connect(self):
        if serial is None: messagebox.showerror("Dependency missing","Install dependencies: py -m pip install -r requirements.txt");return
        try:
            self.port=serial.Serial(self.port_name.get().strip(),115200,timeout=0,write_timeout=1);self.port.reset_input_buffer();self.rx_buffer.clear();self.status.set(f"Connected: {self.port_name.get()} @ 115200")
        except Exception as exc:self.port=None;messagebox.showerror("Serial connection",str(exc))

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
        if self.raw_command.get().strip():self.send(self.raw_command.get());self.raw_command.set("")
    def _append(self,text):
        self.monitor.insert("end",text+"\n");self.monitor.see("end")
        if int(self.monitor.index("end-1c").split(".")[0])>2200:self.monitor.delete("1.0","500.0")
    def _poll(self):
        if self.port:
            try:
                data=self.port.read(self.port.in_waiting or 1);self.rx_buffer.extend(data)
                while b"\n" in self.rx_buffer:
                    raw,_,tail=self.rx_buffer.partition(b"\n");self.rx_buffer=bytearray(tail);line=raw.decode("utf-8","replace").strip()
                    if line:self._handle_line(line)
            except OSError as exc:self.disconnect();messagebox.showerror("Serial read",str(exc))
        self.after(80,self._poll)

    def _handle_line(self,line):
        self._append(line)
        if not line.startswith("LIVE "):return
        try:data=parse_live_line(line)
        except ValueError:self.parse_errors+=1;return
        self.packet_count+=1;self.last_packet_at=time.monotonic()
        seq=data.get("seq")
        if isinstance(seq,int):
            if self.last_seq is not None and seq>self.last_seq+1:self.parse_errors+=seq-self.last_seq-1
            self.last_seq=seq
        self.values={i["name"]:i for i in data.get("pots",[])+data.get("cvs",[])+data.get("switches",[]) if isinstance(i,dict) and "name" in i}
        changed=[]
        for name,item in self.values.items():
            prior=self.previous_raw.get(name,item.get("r",0));delta=abs(item.get("r",0)-prior)
            if delta>=14:
                changed.append((name,delta));self.previous_raw[name]=item.get("r",0)
            elif name not in self.previous_raw:self.previous_raw[name]=item.get("r",0)
            if name in getattr(self,"input_rows",{}):
                bar,val=self.input_rows[name];bar["value"]=item.get("p",0);val.set(f"{item.get('r',0):4d} · {item.get('p',0):3d}% · {item.get('lo',0)}–{item.get('hi',0)} · noise {item.get('n',0)}")
        if changed and not self.live_lock.get():
            candidate=max(changed,key=lambda item:item[1])[0]
            selected_delta=next((d for n,d in changed if n==self.selected),0)
            if self.selected not in self.values or selected_delta==0 or max(d for _,d in changed)>max(24,selected_delta*1.6):self.selected=candidate;self.live_name.set(candidate)
        if not self.live_lock.get() and "ENCODER" not in self.live_name.get() and int(data.get("last_moved",-1))==18 and data.get("encoder")!=getattr(self,"previous_encoder",None):
            self.selected="ENCODER";self.live_name.set("ENCODER")
        self.previous_encoder=data.get("encoder")
        self._update_live(data,changed)
        self.encoder_text.set(f"Encoder position: {data.get('encoder',0)}    Physical ring index: {data.get('ring',0)}")
        self.button_text.set(f"Encoder button: {'PRESSED' if data.get('encoder_button') else 'released'}    Follow: {'PRESSED' if data.get('follow_button') else 'released'}")
        self.mode_text.set(f"A mode: {data.get('mode_a','—')}    B mode: {data.get('mode_b','—')}")
        switches={x.get("name"):x.get("r",0) for x in data.get("switches",[])};self.switch_text.set("Switch ADC: "+"    ".join(f"{n} {switches.get(n,'—')}" for n in SWITCHES))
        self.sync_text.set(f"Edges A: {data.get('sync_a',0)}     B: {data.get('sync_b',0)}")
        self.arm_state.set(f"Analog: {'ARMED' if data.get('analog_armed') else 'DISARMED'} · Trigger: {'ARMED' if data.get('trigger_armed') else 'DISARMED'}")
        direct=data.get("direct_adc",[])
        if direct:
            self.direct_adc.set("Direct ADC: "+" · ".join(f"GPIO{x['gpio']} Arduino {x['arduino']} / SDK {x['sdk']} / Δ{abs(x['arduino']-x['sdk'])}" for x in direct))
            self.direct_debug.set(self.direct_adc.get())
        self._draw_ring(data.get("ring",0),data.get("last_moved",0))

    def _update_live(self,data,changed):
        name=self.live_name.get();item=self.values.get(name)
        if name=="ENCODER":
            raw=int(data.get("encoder",0));pct=(raw%64)*100//63;low=high=raw;noise=0;color=COLORS["ENCODER"]
        elif item:
            raw=item.get("r",0);pct=item.get("p",0);low=item.get("lo",0);high=item.get("hi",0);noise=item.get("n",0);color=COLORS.get(name, COLORS["A"] if name.startswith("A_") else COLORS["B"])
        else:return
        self.big_name.set(name);self.live_values.set(f"Raw ADC: {raw}     Percent: {pct}%     Observed min/max: {low} / {high}     Noise span: {noise}");self.meter["value"]=pct
        moved=any(n==name for n,_ in changed)
        self.detect.set("MOVEMENT DETECTED" if moved else ("Locked · monitoring" if self.live_lock.get() else "Stable · auto-detect active"))
        if moved:
            self.history.append((time.strftime("%H:%M:%S"),name,raw));self.history=self.history[-8:]
            self.history_label.set("Recent movement: "+"  →  ".join(f"{t} {n}={v}" for t,n,v in self.history))
        self.history_canvas.delete("all");w=max(80,self.history_canvas.winfo_width());h=98;self.history_canvas.create_line(0,h-4,w,h-4,fill="#bbb")
        vals=[v for _,n,v in self.history if n==name][-30:]
        if len(vals)>1:
            points=[]
            for i,v in enumerate(vals):points.extend((i*(w-8)/(len(vals)-1)+4,h-6-(v/4095)*(h-12)))
            self.history_canvas.create_line(*points,fill=color,width=2)
    def _draw_ring(self,index,last):
        if 0 <= int(last) < 6:
            name=POTS[int(last)];color=COLORS["A"] if name.startswith("A_") else COLORS["B"]
        elif 6 <= int(last) < 14:color=COLORS[CVS[int(last)-6]]
        elif int(last)==18 or int(last)==19:color=COLORS["ENCODER"]
        else:color="#bb72ff"
        for i,dot in enumerate(self.ring_dots):self.ring.itemconfigure(dot,fill=color if i==int(index)%16 else "#50505c")
    def _lock_changed(self):
        self.selected=self.live_name.get()
        if self.live_lock.get():self.detect.set("Locked · monitoring")
    def _health(self):
        age="—" if self.last_packet_at is None else f"{time.monotonic()-self.last_packet_at:.1f}s"
        self.health.set(f"Packets: {self.packet_count} · parse/sequence errors: {self.parse_errors} · last packet age: {age}")
        self.after(250,self._health)
    def _animate(self):
        if hasattr(self,"wave_canvas"):
            c=self.wave_canvas;c.delete("all");w=max(c.winfo_width(),200);h=max(c.winfo_height(),100)
            for ch,state in enumerate(self.waveforms):
                y0=8+ch*((h-16)/4);amp=max(10,(h-28)/8);color=("#ff9d24","#ffd64a","#3488ff","#42bdff")[ch];c.create_text(35,y0+amp,text=f"{ch} PWM",fill=color,anchor="w")
                pts=[]
                for x in range(0,w,3):
                    phase=((time.monotonic()-state["start"])*state["hz"]+x/max(w,1)*1.6)%1
                    shape=state["shape"]
                    if shape=="sine":v=.5+.5*math.sin(math.tau*phase)
                    elif shape=="triangle":v=2*phase if phase<.5 else 2-2*phase
                    elif shape=="ramp":v=phase
                    else:v=1 if phase<.5 else 0
                    pts.extend((x,y0+amp*(1-2*v)))
                if len(pts)>=4:c.create_line(*pts,fill=color,width=2)
                c.create_text(w-4,y0+amp,text="running" if state["running"] else "stopped",fill="#ddd",anchor="e")
        self.after(70,self._animate)
    def arm_analog(self):
        if messagebox.askyesno("Arm analogue outputs","Enable the four PWM driven outputs? PWM zero is not assumed to mean zero jack voltage."):self.send("ARM ANALOG")
    def arm_trigger(self):
        if messagebox.askyesno("Arm trigger outputs","Enable trigger pulses on the module?"):self.send("ARM TRIG")
    def start_wave(self,ch,shape,freq):
        self.waveforms[ch]={"shape":shape.get(),"hz":float(freq.get()),"start":time.monotonic(),"running":True};self.send(f"WAVE {ch} {shape.get()} {freq.get()}")
    def stop_wave(self,ch):self.waveforms[ch]["running"]=False;self.send(f"STOP {ch}")
    def set_led(self):self.send(f"LED ONE {self.led_index.get()} {self.led_r.get()} {self.led_g.get()} {self.led_b.get()}")


if __name__ == "__main__":
    FrontPanelApp().mainloop()
