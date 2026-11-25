# SpellTwister output hardware analysis

Source basis: upstream `main` tree at commit `59c67e4ae63814b56fc97dd985011026d1c87f16`, including the module schematic and production IPC-D-356 netlist. The upstream PCB source is 2.8 MB and was not returned by the connected GitHub file reader; the production IPC netlist is available and confirms the requested reference designators and nets. The physical module's silkscreen/revision has not been observed, so these checks establish the published production design, not the revision fitted to the connected unit.

## Four PWM-to-jack paths

The IPC-D-356 file confirms each RP2040 output pin feeds the listed 10 kΩ input resistor, and each corresponding 1 kΩ series resistor terminates at the named module jack net:

| Channel | RP2040 net | Input resistor | Output resistor | Jack | Feedback resistor | Feedback capacitor | DC reference leg |
|---|---|---:|---:|---|---:|---:|---|
| A Primary | `PWM_1_PRI` | R43 10 kΩ | R55 1 kΩ | J12 | R52 39 kΩ | C53 1 nF | R48 56 kΩ + R102 4.7 kΩ from REF−10 |
| A Secondary | `PWM_1_SEC` | R42 10 kΩ | R54 1 kΩ | J11 | R51 39 kΩ | C52 2.2 nF | R101 56 kΩ + R103 4.7 kΩ from REF−10 |
| B Primary | `PWM_2_PRI` | R78 10 kΩ | R93 1 kΩ | J20 | R90 39 kΩ | C36 1 nF | R82 56 kΩ + R84 4.7 kΩ from REF−10 |
| B Secondary | `PWM_2_SEC` | R77 10 kΩ | R92 1 kΩ | J19 | R89 39 kΩ | C35 2.2 nF | R83 56 kΩ + R85 4.7 kΩ from REF−10 |

The output amplifier is a TL074 channel per output. Each PWM input is buffered, then drives an inverting summing stage. The summing stage uses a 10 kΩ signal input resistor, a 39 kΩ feedback resistor, and a −10 V reference leg. Exact net membership is recorded in `upstream/hardware design/production/netlist.ipc`. The design has 1 kΩ output isolation resistors. Other resistor/capacitor positions around the buffer and offset legs are listed above.

## Nominal transfer and bandwidth

Assuming a 3.3 V RP2040 PWM swing and ideal op-amp operation, the current amplifier gain magnitude is 39 kΩ / 10 kΩ = 3.9. The REF−10 branch resistance is 56 kΩ + 4.7 kΩ = 60.7 kΩ, producing a nominal output offset of 39 kΩ × 10 V / 60.7 kΩ = 6.425 V. The PWM term spans 39 kΩ / 10 kΩ × 3.3 V = 12.87 V, so the ideal endpoints are approximately +6.43 V and −6.44 V. This range is bipolar and the real endpoints are limited by TL074 swing, loading, component tolerance, and calibration. Confirm on the bench before treating the estimate as a measured rating.

The inverting stage's feedback pole is approximately `1 / (2π Rf Cf)`:

- Primary: 1 / (2π × 39 kΩ × 1 nF) = **4.08 kHz**.
- Secondary: 1 / (2π × 39 kΩ × 2.2 nF) = **1.85 kHz**.

These figures are the feedback-network pole estimates. The buffer network, output load, op-amp response, and PCB parasitics also shape the measured response. These outputs are not full video bandwidth outputs as populated.

## Candidate 0–1 V modification

To preserve the existing feedback poles while reducing the bipolar output span and shifting the midpoint to +0.5 V, the first-pass matched values are:

| Ref set | Existing | Candidate | Reason |
|---|---:|---:|---|
| R52, R51, R90, R89 | 39 kΩ | **3.03 kΩ, 1%** | Gain becomes 0.303; 3.3 V PWM maps to 0.9999 V span. |
| C53, C36 | 1 nF | **12.87 nF equivalent** | `Rf×Cf` held constant; predicted pole 4.08 kHz. |
| C52, C35 | 2.2 nF | **28.32 nF equivalent** | `Rf×Cf` held constant; predicted pole 1.85 kHz. |
| R48, R101, R82, R83 | 56 kΩ | **25.6 kΩ, 1%** | With the existing 4.7 kΩ series leg, REF−10 gives a nominal 1.000 V summing offset. |
| R102, R103, R84, R85 | 4.7 kΩ | retain 4.7 kΩ | Keeps the reference leg total near 30.2 kΩ. |
| R43, R42, R78, R77 | 10 kΩ | retain | PWM input network remains unchanged. |
| R55, R54, R93, R92 | 1 kΩ | retain | Output isolation remains unchanged. |

With the nominal values, `Rf/Rin = 0.303`, and the adjusted reference leg is `25.6 kΩ + 4.7 kΩ = 30.3 kΩ`. The ideal output is `−0.303×Vin + 3.03k×10V/30.3k`, or approximately +1.000 V at PWM=0 V and +0.0001 V at PWM=3.3 V. The firmware's inversion maps code 0 toward the low end and full code toward 1 V. To preserve the feedback poles, the exact equivalent capacitor values are 12.87 nF (primary; e.g. 12 nF + 870 pF in parallel) and 28.32 nF (secondary; e.g. 27 nF + 1.3 nF). This candidate keeps the original two bandwidth limits and therefore does not increase video bandwidth. Component tolerance and measured output loading cause small shifts; recalibrate all four channels after modification.

These are calculated candidate values from the published design, not a modification authorization or proof that the physical module has the same revision. Before soldering, verify actual value markings/assembly BOM against the physical PCB; then measure REF−10, PWM high level, amplifier saturation, output span and loaded frequency response. The retained 1.85–4.1 kHz response deliberately filters the 44.1 kHz PWM carrier but is too narrow for full-resolution video-rate modulation. A higher-bandwidth redesign needs a substantially faster DAC/output stage, not simply removal of the filter capacitors.

### Bandwidth limits and possible improvements

At 125 MHz system clock, unprescaled edge-aligned PWM can reach about 61.0 kHz at 11 bits (`125 MHz / 2048`) or 1.95 MHz at 6 bits (`125 MHz / 64`). Increasing carrier requires sacrificing duty-cycle resolution; leaving the feedback capacitors unchanged keeps the analog poles far below video rates. Reducing the feedback capacitors to lift those poles would also pass more PWM carrier and ripple. A practical video path needs a multi-MS/s DAC or parallel R-2R converter with DMA/PIO, followed by a low-noise high-speed output amplifier and reconstruction filter. RP2040 PIO/DMA can service parallel data; the current four PWM pins and TL074 low-pass stages cannot provide full-resolution video bandwidth.

## External sync input

The published IPC netlist traces the A/B `SIG_CV` jacks J6/J14 through R14/R35 (100 kΩ) to MCP6004 U7A/U7C inverting stages. The noninverting inputs are grounded; R4/R53 (470 kΩ) feed back from each op-amp output. Those outputs also connect to RP2040 `SIG_1`/`SIG_2` (GPIO17/18). Nominal closed-loop gain is −4.7 while the op-amp is in its linear region; with a 0–3.3 V supply it saturates at the rails for inputs above roughly 0.7 V magnitude. The op-amp stage, rather than the MCU pin, receives the jack signal.

There are no external clamp diodes on these nets in the production IPC netlist. The 100 kΩ input resistor limits current; a ±10 V input would produce at most about 100 µA through that path, but it drives the MCP6004 input protection and is not a stated continuous input rating. Microchip's datasheet lists MCP6004 analog input absolute maximums of VSS−1 V to VDD+1 V and ±2 mA at analog input pins; these are stress limits, not a recommended operating range. Therefore the schematic suggests current limiting for modular-level trigger signals, but a guaranteed maximum input voltage cannot be claimed from the design files alone. Connect external sync to J6/J14, never directly to GPIO17/18. Begin bench characterization at 0–3.3 V through a current-limited source, then check polarity and thresholds before trying larger signals. [Microchip MCP6004 datasheet](https://ww1.microchip.com/downloads/aemDocuments/documents/MSLD/ProductDocuments/DataSheets/MCP6001-1R-1U-2-4-1-MHz-Low-Power-Op-Amp-DS20001733L.pdf)

## Diagrams

`hardware/original-output.svg` shows the published PWM/filter/inverting stage and reference network. `hardware/proposed-output.svg` shows the calculated component changes. The candidate schematic is not a PCB rework instruction until the physical revision is matched.
