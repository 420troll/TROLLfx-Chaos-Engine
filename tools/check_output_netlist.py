#!/usr/bin/env python3
"""Assert published IPC-D-356 connectivity for SpellTwister outputs."""
import argparse
import json
import re
from pathlib import Path

EXPECTED={
 "A Primary":{"pwm":"PWM_1_PRI","input":"R43","series":"R55","jack":"J12","output_fragment":"ODULE1/PRI_OUT"},
 "A Secondary":{"pwm":"PWM_1_SEC","input":"R42","series":"R54","jack":"J11","output_fragment":"ODULE1/SEC_OUT"},
 "B Primary":{"pwm":"PWM_2_PRI","input":"R78","series":"R93","jack":"J20","output_fragment":"ODULE2/PRI_OUT"},
 "B Secondary":{"pwm":"PWM_2_SEC","input":"R77","series":"R92","jack":"J19","output_fragment":"ODULE2/SEC_OUT"},
}

def check(path):
    lines=path.read_text(encoding="utf-8").splitlines()
    rows=[]
    for line in lines:
        fields=line.split()
        if len(fields)>=3 and fields[0].startswith(("317","327")):
            rows.append((fields[0][3:] if fields[0].startswith("327") else fields[0][3:],fields[1],fields[2].lstrip("-")))
    result={}
    for channel,e in EXPECTED.items():
        input_pins=[r for r in rows if r[1]==e["input"]]
        output_pins=[r for r in rows if r[1]==e["series"]]
        jack_pins=[r for r in rows if r[1]==e["jack"]]
        pwm=any(e["pwm"] in net and ref==e["input"] and pin=="1" for net,ref,pin in rows)
        reaches_output=any(e["output_fragment"] in net and ref==e["series"] and pin=="2" for net,ref,pin in rows)
        reaches_jack=any(e["output_fragment"] in net and ref==e["jack"] and pin in ("T","TIP") for net,ref,pin in rows)
        result[channel]={"pwm_to_input_resistor":pwm,"series_resistor_to_output_net":reaches_output,"output_net_to_jack":reaches_jack,
                         "input_resistor_pads":[pin for _,ref,pin in input_pins],"series_resistor_pads":[pin for _,ref,pin in output_pins],"jack_pads":[pin for _,ref,pin in jack_pins]}
        if not (pwm and reaches_output and reaches_jack): raise ValueError(f"IPC netlist path mismatch: {channel}: {result[channel]}")
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument("netlist",type=Path,nargs="?",default=Path("upstream/hardware design/production/netlist.ipc"));a=p.parse_args()
    print(json.dumps(check(a.netlist),indent=2))
if __name__=="__main__":main()
