# TROLLfx Chaos Shape Lab 0.1

Open index.html in Chrome, Edge or Firefox with WebGL enabled. No server or installation required.

Controls: Time A/B adjusts animation rate; Slope A/B adjusts distortion; Ratio A/B adjusts spatial frequency and symmetry. Follow locks B phase to A. Select one of 12 patterns; adjust hue, saturation, scanlines, mask, curvature, colour bleed and glow. F toggles fullscreen, Space pauses phase evolution, arrow keys select patterns when controls are not focused. Save/load JSON presets; PNG exports a rendered frame.

This is a procedural raster visualizer with original GLSL CRT-style effects, not a circuit-accurate CRT, composite encoder, Mainbow emulator, or RP2040 DSP model. Pixel-domain spatial functions require a raster coordinate source and cannot all be generated directly by four scalar CV outputs. No external shader code is incorporated. Browser execution and GPU performance have not been verified by the authoring environment. Physical firmware and calibration files are unchanged.
