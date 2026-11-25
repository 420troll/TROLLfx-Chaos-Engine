# TROLLfx Chaos CV Lab V0.1

Open index.html directly in a modern browser. No dependencies or hardware connections required.

Two independent engines, four normalized 0–1 V outputs, eleven algorithms. Time controls frequency, slope changes algorithm complexity, ratio changes secondary oscillator rate. Timing reference selects free running or ideal NTSC H/V frequency with division/multiplication. Follow locks B primary phase to A; secondary phase remains independent. Reset clears phase and attractor state. Oscilloscope uses a 2 ms–2 s time window; XY selects any output pair. Generic video preview illustrates four voltage destinations, not Mainbow emulation. JSON presets and scope CSV export are supported.

The model steps at 44.1 kHz. Free rate tops out near 15.1 kHz; primary frequencies are capped at 19.845 kHz. High harmonics and secondary rates can alias. Sync is a frequency reference, not a simulated pulse-input circuit. Chaos update rates are separately limited. Quantization is normalized, not a simulation of the PWM carrier or ripple. Analogue filters use three discrete first-order stages approximating the equal-RC input filter and final feedback pole; original mode retains normalized voltage for comparison, not the original bipolar physical swing. Modified feedback uses 3.01 kΩ. No measured hardware response is incorporated. The DSP is JavaScript, not yet shared with the RP2040 C++ implementation.

Validation: JavaScript syntax compiled; 11 modes exercised for 88,200 sample steps each with both engines active, checking 3,880,800 output values for finiteness and range. All passed. This is a bounded-output smoke test, not frequency, attractor fidelity, browser UI, or hardware validation. Browser rendering has not been tested in the authoring environment.

No physical firmware, calibration, or Shape Lab files modified.
