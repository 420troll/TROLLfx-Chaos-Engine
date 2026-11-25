#!/usr/bin/env python3
"""Ideal inverting-stage component calculator used in the hardware guide."""
import argparse
import json
import math

def calculate(rin=10000.0, pwm_span=3.3, desired_span=1.0, reference=10.0,
              desired_offset=1.0, old_rf=39000.0, old_cf=1e-9):
    rf=rin*desired_span/pwm_span
    rref=rf*abs(reference)/desired_offset
    cf=old_rf*old_cf/rf
    fc=1.0/(2.0*math.pi*rf*cf)
    return {"feedback_ohm":rf,"reference_leg_total_ohm":rref,"feedback_cap_f":cf,"feedback_pole_hz":fc,
            "ideal_output_at_pwm_0_v":rf*abs(reference)/rref,
            "ideal_output_at_pwm_full_scale_v":rf*abs(reference)/rref-rf/rin*pwm_span}

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--rin",type=float,default=10000);p.add_argument("--pwm",type=float,default=3.3);p.add_argument("--span",type=float,default=1);p.add_argument("--reference",type=float,default=10);p.add_argument("--offset",type=float,default=1);p.add_argument("--old-rf",type=float,default=39000);p.add_argument("--old-cf",type=float,default=1e-9)
    a=p.parse_args();print(json.dumps(calculate(a.rin,a.pwm,a.span,a.reference,a.offset,a.old_rf,a.old_cf),indent=2))
