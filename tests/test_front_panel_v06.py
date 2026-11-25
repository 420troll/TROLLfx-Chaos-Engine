import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
FP=ROOT/'front_panel_test'
sys.path.insert(0,str(FP))
from panel_state import PanelState
from telemetry import parse_protocol_line

# These packets exercise the byte->parser->state path. The checked-in COM9 capture
# is the only physical fixture currently available (FP03); FP05/FP06 capture requires
# the module to leave BOOTSEL and enumerate as COM9.
def feed(state, lines):
    for line in lines:
        state.accept(parse_protocol_line(line))

class FrontPanelV06StateTests(unittest.TestCase):
    def test_current_com9_fp03_fixture_still_parses(self):
        lines=(ROOT/'tests/fixtures/com9-frontpanel-v03.txt').read_text().splitlines()
        packets=[parse_protocol_line(x) for x in lines]
        self.assertEqual(packets[0]['version'],'FP03')
        self.assertEqual(packets[1]['type'],'controls')
        self.assertEqual(packets[1]['TIME'],4089)

    def test_all_six_pots_switch_modes_encoder_outputs_and_time_raw(self):
        s=PanelState()
        feed(s,[
          'PROTO=FP06','HELLO FW=FP06 GUI=0.6',
          'CTRL ID=A_TIME RAW=1000 VALUE=3095','CTRL ID=A_SLOPE RAW=1100 VALUE=2995','CTRL ID=A_RATIO RAW=1200 VALUE=2895',
          'CTRL ID=B_TIME RAW=2000 VALUE=2095','CTRL ID=B_SLOPE RAW=2100 VALUE=1995','CTRL ID=B_RATIO RAW=2200 VALUE=1895',
          'SWITCH A MODE=ENV SW1_RAW=4095 SW2_RAW=0','SWITCH A MODE=LFO SW1_RAW=0 SW2_RAW=0','SWITCH A MODE=VCO SW1_RAW=0 SW2_RAW=4095','SWITCH A MODE=INVALID SW1_RAW=4095 SW2_RAW=4095',
          'SWITCH B MODE=VCO SW1_RAW=4095 SW2_RAW=0','SWITCH B MODE=LFO SW1_RAW=0 SW2_RAW=0','SWITCH B MODE=ENV SW1_RAW=0 SW2_RAW=4095',
          'CV=1,2,3,4,5,6,7,4095','ENCODER -8','ENCODER_BUTTON ON','FOLLOW_BUTTON OFF',
          'OUT PCT=0,25,50,100 CODE=0,512,1024,2047 DUTY=2047,1535,1023,0',
          'TIMERAW=999,1999'])
        p=s.projection()
        self.assertEqual([p['controls'][i]['value'] for i in ('A_TIME','A_SLOPE','A_RATIO','B_TIME','B_SLOPE','B_RATIO')],[3095,2995,2895,2095,1995,1895])
        self.assertEqual(p['controls']['A_TIME']['raw'],999)
        self.assertEqual(p['controls']['B_TIME']['raw'],1999)
        self.assertEqual(p['modes'],{'A':'INVALID','B':'ENV'})
        self.assertEqual(p['controls']['A_RATIO_CV']['raw'],1); self.assertEqual(p['controls']['B_EXP_CV']['raw'],4095)
        self.assertEqual(p['encoder'],-8); self.assertTrue(p['encoder_button']); self.assertFalse(p['follow_button'])
        self.assertEqual([x['percent'] for x in p['outputs'].values()],[0,25,50,100])
        self.assertEqual(s.firmware_protocol,'FP06')

    def test_active_selection_lock_and_malformed_recovery(self):
        s=PanelState()
        s.select_control('A_TIME',lock=False)
        s.accept(parse_protocol_line('MOVED=B_TIME'))
        self.assertEqual(s.active_id,'B_TIME')
        s.select_control('A_TIME',lock=True); s.accept(parse_protocol_line('MOVED=B_TIME'))
        self.assertEqual(s.active_id,'A_TIME')
        for bad in ('CTRL ID=A_TIME RAW=9999 VALUE=2','A TIME=bad SLOPE=2 RATIO=3 MODE=LFO','OUT PCT=1,2 CODE=3 DUTY=4'):
            with self.assertRaises(ValueError): parse_protocol_line(bad)
        s.accept(parse_protocol_line('CTRL ID=A_TIME RAW=123 VALUE=3972'))
        self.assertEqual(s.controls['A_TIME'].raw,123)

    def test_protocol_handshake_packets(self):
        p=parse_protocol_line('HELLO FW=FP06 GUI=0.6')
        self.assertEqual(p,{'type':'handshake','firmware':'FP06','gui':'0.6'})

class FrontPanelV06GuiRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=FP/'FrontPanel-GUI.py'
        # Headless runner does not ship Tk; stub only import-time base/widget namespaces.
        import types
        tk=types.ModuleType('tkinter'); tk.Tk=type('Tk',(object,),{})
        ttk=types.ModuleType('tkinter.ttk'); tk.ttk=ttk
        messagebox=types.ModuleType('tkinter.messagebox'); tk.messagebox=messagebox
        prior={name:sys.modules.get(name) for name in ('tkinter','tkinter.ttk','tkinter.messagebox')}
        sys.modules.update({'tkinter':tk,'tkinter.ttk':ttk,'tkinter.messagebox':messagebox})
        spec=importlib.util.spec_from_file_location('front_panel_gui_v06',path)
        cls.mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(cls.mod)
        for name,value in prior.items():
            if value is None: sys.modules.pop(name,None)
            else: sys.modules[name]=value

    def test_handler_error_does_not_prevent_next_valid_packet(self):
        app=self.mod.App.__new__(self.mod.App)
        app.state=PanelState(); app.packet_count=0; app.parse_errors=0; app.last_valid_at=None
        app.pending_ack=[]; app.protocol_version=None; app.last_moved='NONE'
        app.log=[]; app.paused=False; app.log_count=0
        app._append=lambda line: app.log.append(line)
        app._status=lambda message: None
        app.send=lambda command: None
        app._update_widgets=lambda packet: (_ for _ in ()).throw(RuntimeError('injected widget exception')) if packet.get('type')=='control' else None
        app._handle('CTRL ID=A_TIME RAW=100 VALUE=3995')
        self.assertEqual(app.parse_errors,1)
        app._update_widgets=lambda packet: None
        app._handle('CTRL ID=A_TIME RAW=100 VALUE=3995')
        self.assertEqual(app.packet_count,2)
        self.assertEqual(app.state.controls['A_TIME'].raw,100)

    def test_poll_reschedules_after_unexpected_failure(self):
        app=self.mod.App.__new__(self.mod.App)
        app.port=None; app.last_valid_at=None; app.packet_count=0; app.parse_errors=0
        app.counter=type('Var',(),{'set':lambda self,value:None})()
        app._polling=False; app.callbacks=[]; app.log=[]
        app.after=lambda delay,callback: app.callbacks.append((delay,callback))
        app._append=lambda line:app.log.append(line)
        original=app.counter.set
        app.counter.set=lambda value: (_ for _ in ()).throw(RuntimeError('injected counter error'))
        app.poll()
        self.assertEqual(len(app.callbacks),1)
        self.assertTrue(any('GUI poll error' in line for line in app.log))
        app.counter.set=original
        delay,callback=app.callbacks.pop(); self.assertEqual(delay,40)
        callback()
        self.assertEqual(len(app.callbacks),1)

if __name__=='__main__': unittest.main()
