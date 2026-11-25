import importlib.util
import struct
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

inspect=load("inspect_uf2","tools/inspect_uf2.py")
compare=load("compare_flash_uf2","tools/compare_flash_uf2.py")
netcheck=load("check_output_netlist","tools/check_output_netlist.py")
calc=load("output_calculations","tools/output_calculations.py")

def block(payload,address=0x10000000,number=0,total=1):
    used=len(payload)
    payload=payload.ljust(476,b"\0")
    return struct.pack("<8I",0x0A324655,0x9E5D5157,0x2000,address,used,number,total,0xE48BFF56)+payload+struct.pack("<I",0x0AB16F30)

class Uf2Tests(unittest.TestCase):
    def test_inspects_valid_uf2(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x.uf2";p.write_bytes(block(b"TEST!!"))
            result=inspect.inspect(p)
            self.assertEqual(result["block_count"],1);self.assertTrue(result["contiguous"])
            self.assertTrue(any(s.startswith("TEST") for s in result["strings"]))
    def test_rejects_bad_magic(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"bad.uf2";p.write_bytes(bytes(512))
            with self.assertRaises(ValueError):inspect.inspect(p)
    def test_compare_flash_payload(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);u=d/"x.uf2";f=d/"flash.bin";u.write_bytes(block(b"TEST"));f.write_bytes(b"TEST"+bytes(508))
            result=compare.compare(f,u,0x10000000)
            self.assertTrue(result["all_uf2_payload_matches"]);self.assertEqual(result["compared_payload_bytes"],4)
    def test_published_output_netlist_paths(self):
        result=netcheck.check(ROOT/"upstream/hardware design/production/netlist.ipc")
        self.assertEqual(set(result),{"A Primary","A Secondary","B Primary","B Secondary"})
        self.assertTrue(all(all(v[k] for k in ("pwm_to_input_resistor","series_resistor_to_output_net","output_net_to_jack")) for v in result.values()))
    def test_candidate_output_calculation(self):
        r=calc.calculate()
        self.assertAlmostEqual(r["feedback_ohm"],3030.303,places=2)
        self.assertAlmostEqual(r["ideal_output_at_pwm_0_v"],1.0,places=6)
        self.assertAlmostEqual(r["ideal_output_at_pwm_full_scale_v"],0.0,places=6)

if __name__=="__main__":unittest.main()
