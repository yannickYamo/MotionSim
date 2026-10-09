# Validation

Modules A, B and C in this document are three 600 V, 15 A IGBT modules with built-in drivers from one vendor. They are not named.

Four levels, strongest claim last. Vendor tools and charts are cross-checks, not ground truth.

- **A, mathematical**: closed-form solutions.
- **B, numerical**: an independent integrator. Not built yet.
- **C, external**: vendor charts, vendor tools, other simulators.
- **D, physical**: measured inverter or double-pulse data. None available yet.

## Level A (passing, in `tests/`)

For a device with on-state voltage `V0 + r·I` and switching energy `k·I`, under sinusoidal PWM with peak current `Ipk`, modulation index `m` and power factor `cos φ`:

| Quantity | Closed form |
|---|---|
| Switch conduction | `V0·Ipk·(1/2π + m·cos φ/8) + r·Ipk²·(1/8 + m·cos φ/3π)` |
| Diode conduction | `V0·Ipk·(1/2π − m·cos φ/8) + r·Ipk²·(1/8 − m·cos φ/3π)` |
| Switching | `fsw·k·Ipk/π·(Vdc/Vref)` |

The engine matches all three within 1% over 15 combinations of `m` (0.1, 0.6, 1.0) and power factor (1, 0.8, 0.3, 0, −0.7).

Also checked: steady-state temperatures, the self-consistent temperature for an on-state voltage that rises with temperature, detection of thermal runaway, the Foster step response, and the maximum-current solver.

## Level B (passing, in `tests/`)

The periodic thermal response is compared with a separate step-by-step integration of a three-stage network driven by half-sine power pulses. Peak temperature agrees within 0.5%.

## Level C: module A against its own datasheet chart

The datasheet's Figure 15 gives maximum RMS current against case temperature at 300 V, modulation index 0.8, power factor 0.8, sinusoidal PWM, junction temperature at most 150 °C. The model was built only from the table values in the same datasheet. Chart values were read by eye, to about ±0.3 A. Output frequency is taken as 50 Hz; the chart does not state it.

The datasheet has no transient thermal data, so the model cannot place the peak junction temperature. It gives two limits: the current if the peak is taken at its upper bound, and the current if only the average is limited.

| Case temperature | Switching | Peak at upper bound | Vendor chart | Average only |
|---|---|---|---|---|
| 60 °C | 6 kHz | 7.2 A | 11.5 A | 16.3 A |
| 80 °C | 6 kHz | 5.9 A | 9.6 A | 13.9 A |
| 100 °C | 6 kHz | 4.6 A | 7.5 A | 11.2 A |
| 110 °C | 6 kHz | 3.9 A | 6.4 A | 9.6 A |
| 120 °C | 6 kHz | 3.1 A | 5.2 A | 7.9 A |
| 60 °C | 16 kHz | 5.9 A | 9.4 A | 14.0 A |
| 80 °C | 16 kHz | 4.8 A | 7.8 A | 11.7 A |
| 100 °C | 16 kHz | 3.6 A | 6.1 A | 9.2 A |
| 110 °C | 16 kHz | 3.0 A | 5.1 A | 7.8 A |
| 120 °C | 16 kHz | 2.3 A | 4.0 A | 6.2 A |

**The vendor chart lies inside the bracket at all ten points.** The first version of this comparison limited the average only and allowed 42 to 55% more current than the chart.

The bracket is wide, roughly 0.6 to 1.5 times the chart value. That is what this datasheet can support: without transient thermal data the tool cannot say more.

### Diagnostic, not part of the model

As a test of the explanation, a single thermal time constant was tried in place of the missing transient data:

| Time constant | Model against chart, across the ten points |
|---|---|
| 3 ms | 20 to 26% low |
| 5 ms | 8 to 13% low |
| 8 ms | 2 to 5% high |
| 12 ms | 12 to 16% high |
| 20 ms | 22 to 28% high |

One value near 7 to 8 ms brings all ten points within the chart-reading error. That is consistent with the chart limiting peak junction temperature, and plausible for a small chip. It does not prove the explanation is complete: heating between chips is still not modelled and could trade off against the time constant. The value is not used anywhere in the tool, since it would be calibrating to the vendor's answer.

Still unverified: the assumed curve shapes away from the 7.5 A test point, and any margin the vendor applied.

## Level C: onsemi FGHL40T65MQD, digitised curves against its own tables

| Check | Digitised | Tabulated | Difference |
|---|---|---|---|
| IGBT thermal impedance plateau | 0.621 K/W | 0.63 K/W (maximum) | −1.5% |
| Diode thermal impedance plateau | 1.641 K/W | 1.6 K/W (maximum) | +2.5% |
| On-state voltage at 40 A, 25 °C | 1.444 V | 1.45 V | −0.4% |
| On-state voltage at 40 A, 175 °C | 1.738 V | 1.77 V | −1.8% |
| Turn-on energy, 25 °C, worst of 20 A and 40 A | | | 1.2% |
| Turn-on energy, 175 °C, worst of 20 A and 40 A | | | 2.5% |
| Turn-off energy, 25 °C, worst of 20 A and 40 A | | | 1.7% |
| Turn-off energy, 175 °C, worst of 20 A and 40 A | | | 2.6% |
| Diode forward voltage at 40 A, 25 °C | 2.501 V | 2.55 V | −1.9% |
| Diode forward voltage at 40 A, 175 °C | 2.384 V | 2.3 V | +3.6% |

The curve and the table are two statements of the same quantity in one document. Agreement confirms the axis reading, the digitising and the curve matching. It does not confirm the device data itself, and the same table values were used to choose which curve is which, so this is a consistency check, not an independent one.

There is no external reference yet for this part's losses or temperatures.

## Level A additions

- Every PWM scheme delivers the same fundamental voltage.
- Continuous schemes give the same switching loss as sine.
- The 60° discontinuous scheme halves switching loss at unity power factor.

## Level A additions for field-effect transistors

- A resistive channel conducting in both directions loses `R·Irms²/2` per switch, independent of modulation index and power factor.
- Dead-time loss equals `2·t_dead·fsw·Vreverse·Ipk/π`, and channel conduction falls by the matching amount.
- Charge-based switching loss matches its closed form.

## Level C: EPC2302 self-checks

| Check | Result |
|---|---|
| Normalised on-resistance curve at 25 °C | 1.00 |
| Thermal impedance plateau after scaling | 0.196 K/W against 0.2 K/W tabulated |

Both are self-consistency checks. The charge-based switching loss for this part has no reference of any kind.

## Level A additions for the motor model

- Surface-magnet machine: torque current, voltages and frequency match the dq equations.
- Electrical power into the motor equals shaft power plus copper loss, for surface-magnet and salient machines.
- Salient machine: the chosen current is smaller than at neighbouring d-axis currents giving the same torque.
- Field weakening: voltage sits at the limit and torque is unchanged.

## Level C, attempted: vendor web simulator

Two of the modules read here (module A, module B) fail inside the one vendor simulator with a missing-model error. module C runs; its comparison is below.

## Level A additions for motor types

- Brushed DC on an H-bridge: conduction and switching loss of the chopping switch, the freewheeling position and the steering switch each match their formulas; a MOSFET bridge loses exactly `2·I²·R`.
- Brushless DC with block commutation: high-side and low-side positions match their formulas over the 120° windows.
- Induction motor: electrical input equals shaft power plus stator and rotor copper loss; slip matches its formula; at the voltage limit the flux falls and the voltage sits on the limit.
- Stepper: equals eight sinusoidal positions of the three-phase engine at the same leg modulation.
- The engine change from one position to a set of roles left all earlier results unchanged.

## Level A additions for loads and motions

- Each load term (inertia, friction, fan law, gravity arm, vehicle on a slope) matches its formula.
- A gearbox multiplies speed and divides torque, and its loss is taken from whichever side is driving.
- A steady motion gives the single-point result.
- Spinning an inertia up and back down returns net zero shaft energy.
- A robot arm raised a quarter turn ends horizontal, holding its full gravity torque.

## Level C: module C against the vendor's public simulator

The first comparison with anything outside this project. Conditions: sine PWM, 50 Hz, 300 V, modulation index 0.8, power factor 0.8. Our model: table values only, case temperature set to the simulator's. Reference data: a local file kept out of the repository.

Losses, ours against the simulator:

| Point | Switch conduction | Turn-on | Turn-off | Diode conduction | Diode recovery | Inverter total |
|---|---|---|---|---|---|---|
| 6 kHz, 5 A | +4% | +47% | +13% | −2% | −12% | +8% |
| 16 kHz, 5 A | +4% | +47% | +15% | −3% | −10% | +13% |
| 6 kHz, 10 A | −4% | +12% | +23% | +8% | +15% | +2% |
| 16 kHz, 8 A | 0% | +32% | +25% | +3% | +3% | +11% |

The last two points put the junction above 200 °C in the simulator, far beyond the part's rating; they are useful for losses only.

Average junction rise over case, in K:

| Point | Switch, simulator | Switch, ours | Diode, simulator | Diode, ours |
|---|---|---|---|---|
| 6 kHz, 5 A | 24.0 | 15.1 | 21.2 | 4.6 |
| 16 kHz, 5 A | 33.2 | 22.9 | 28.6 | 5.3 |
| 6 kHz, 10 A | 70.8 | 42.1 | 60.1 | 12.1 |
| 16 kHz, 8 A | 66.6 | 44.7 | 56.1 | 10.2 |

The simulator's rises fit, at all four points, the chip's own tabulated thermal resistance plus a coupling term times the loss of every other chip in the package: 0.49 to 0.52 K/W for the switch and 0.74 to 0.76 K/W for the diode. With our single coupling input set to 0.5 K/W, the switch comes to 132.5 °C against 130.2 °C and 142.8 °C against 136.7 °C at the two in-rating points; the diode needs 0.75 K/W to match.

Peak above average junction temperature: the simulator gives 3.6 to 12.3 K. Our upper bound, used because the transient thermal figure was not digitised, gives 39 to 115 K.

Limits of this comparison: one part, one vendor, and the reference is a model, not a measurement.

## Survey of the vendor simulator's module thermal models

Eight modules, five operating points each (a local file kept out of the repository, a local script). Average junction rise over case fits `R_self × own loss + R_mutual × other chips' loss` within 0.1 K for every part.

| Part family | R_self switch | R_mutual switch | R_self diode | R_mutual diode |
|---|---|---|---|---|
| Moulded, 5 parts | 2.19 to 4.45 | 0.67 to 0.83 | 2.48 to 6.22 | 0.67 to 1.09 |
| Ceramic substrate, 3 parts | 1.50 to 1.84 | 0.00 | 2.20 to 2.84 | 0.00 |

All in K/W.

## Level C: module C with surveyed thermal assumptions

Model from the datasheet alone; package construction unknown; six operating points; case temperature set to the simulator's.

| Point | Simulator, hottest junction | Ours, typical | Ours, range | Inside |
|---|---|---|---|---|
| 50 Hz, 6 kHz, pf 0.8 | 112.6 °C | 123.5 °C | 103 to 138 | yes |
| 50 Hz, 16 kHz, pf 0.8 | 141.4 °C | 161.9 °C | 131 to 185 | yes |
| 50 Hz, 6 kHz, pf −0.8 | 121.6 °C | 124.4 °C | 104 to 139 | yes |
| 50 Hz, 16 kHz, pf 0.3 | 140.6 °C | 159.4 °C | 128 to 181 | yes |
| 5 Hz, 6 kHz, pf 0.8 | 115.9 °C | 132.0 °C | 112 to 148 | yes |
| 200 Hz, 6 kHz, pf 0.8 | 111.3 °C | 119.2 °C | 101 to 129 | yes |

Typical is 3 to 20 °C high. Before the assumptions it was 9 to 25 °C low, with no range. With the higher temperatures, total loss is now 6 to 18% above the simulator's, where it was 2 to 13% above with the case temperature alone. The range is wide, 35 to 55 °C, because the construction is unknown and the transient response is assumed.

The assumptions were derived from the same simulator this comparison uses, on a set that includes this part, so this shows the defaults are sensible for this vendor's moulded modules and nothing more.

## Level A additions for the package model

- A chip covering its whole plate gives pure one-dimensional conduction through the insulation.
- Far from a small source on a large plate, the rise matches the Bessel-function solution within 5%.
- The thermal matrix is symmetric and falls with distance.

## Level C: module C with first-principles thermal defaults

These replace the survey-based defaults of the previous section. Coupling between chips and the shape of the transient response are both computed for a generic package; package construction is left unknown. Nothing is fitted to the simulator.

| Point | Simulator, hottest junction | Ours, typical | Difference | Ours, range | Inside |
|---|---|---|---|---|---|
| 50 Hz, 6 kHz, pf 0.8 | 112.6 °C | 112.9 °C | +0.3 | 103 to 134 | yes |
| 50 Hz, 16 kHz, pf 0.8 | 141.4 °C | 145.5 °C | +4.1 | 131 to 178 | yes |
| 50 Hz, 6 kHz, pf −0.8 | 121.6 °C | 116.6 °C | −5.0 | 107 to 137 | yes |
| 50 Hz, 16 kHz, pf 0.3 | 140.6 °C | 143.5 °C | +2.9 | 129 to 177 | yes |
| 5 Hz, 6 kHz, pf 0.8 | 115.9 °C | 116.3 °C | +0.4 | 108 to 137 | yes |
| 200 Hz, 6 kHz, pf 0.8 | 111.3 °C | 112.3 °C | +1.0 | 103 to 133 | yes |

Swing of the switch junction within an output period: 2.2 °C against the simulator's 3.5 at 50 Hz, 5.6 against 6.7 at 5 Hz, 1.8 against 2.3 at 200 Hz.

The agreement is partly luck. Our loss is 5 to 16% above the simulator's, and the datasheet's maximum thermal resistance is above the simulator's typical one; both push temperature up, while a lower computed coupling (0.48 against the simulator's 0.79 K/W) pushes it down. At power factor −0.8, where the diode is the hottest chip, the result is 5 °C low. The range is wide, about 30 to 45 °C, because construction is unknown and every package input is varied together.

One part, one vendor, and the reference is a model.

## Level C: module C with its curves read

The datasheet's on-state, diode, turn-on and recovery curves and its transient thermal curve are now used. Turn-off stays on the table (the hot curve disagrees with it by 17%). Thermal coupling between chips is still computed for a generic package, construction unknown.

| Point | Total loss, ours against simulator | Hottest junction, ours against simulator | Ours, range | Inside |
|---|---|---|---|---|
| 50 Hz, 6 kHz, pf 0.8 | 24.2 against 22.8 W, +6% | 115.3 against 112.6 °C, +2.7 | 105 to 136 | yes |
| 50 Hz, 16 kHz, pf 0.8 | 35.8 against 31.7 W, +13% | 148.6 against 141.4 °C, +7.2 | 134 to 181 | yes |
| 50 Hz, 6 kHz, pf −0.8 | 24.9 against 23.8 W, +5% | 117.3 against 121.6 °C, −4.3 | 108 to 138 | yes |
| 50 Hz, 16 kHz, pf 0.3 | 35.9 against 32.0 W, +12% | 146.2 against 140.6 °C, +5.6 | 131 to 179 | yes |
| 5 Hz, 6 kHz, pf 0.8 | 24.2 against 22.8 W, +6% | 120.3 against 115.9 °C, +4.4 | 110 to 141 | yes |
| 200 Hz, 6 kHz, pf 0.8 | 24.2 against 22.7 W, +7% | 114.4 against 111.3 °C, +3.1 | 104 to 135 | yes |

Reading the curves moved total loss from 5 to 16% high to 5 to 13% high. Turn-on at 6 kHz is 0.55 W a switch against the simulator's 0.41 W, still a third high. The curve used is the higher of the high-side and low-side curves, which explains some of it and not all. Temperature moved from −5 to +4 °C to −4 to +7 °C: the earlier figure used an assumed transient response and was helped by errors that cancelled.

Run locally with `motionsim validate`; the reference file is not in the repository.

## Level C: two transistor datasheets against their own tables

- **Silicon MOSFET (Vishay IRF540).** On-resistance against temperature reads 1.0 at 25 °C as a normalised curve must. The single-pulse thermal curve, followed along the line the family merges into, reaches 0.94 K/W against a tabulated maximum of 1.0. The body-diode figure failed its axis check and is unused.
- **SiC module (onsemi NVXK2TR80WDT).** 17 table values, each found on the page it was cited from. No curve could be checked: the figures are images.

Neither has an external reference.

## Level A additions: curves, transistors, time, braking

- A curve drawn as a staircase of 0.07 pt steps with repeated points, cut into pieces, comes back as one curve and reads the right value.
- Two curves per label are read as their upper envelope; a legend stroke in the plot is ignored.
- Transistor with tabulated energy: turn-on loss equals switching frequency times energy times peak current over pi. Output charge estimated from capacitance equals twice capacitance times voltage. Plateau from transconductance equals threshold plus rated current over gain.
- Through time, a short pulse on a constant-loss switch heats it by power times the transient impedance at that time, to six figures. Cooling after a pulse follows each stage's exponential.
- A long steady motion settles at the steady solution within 0.2 °C.
- A heatsink warms as ambient plus loss times resistance times (1 − exp(−t/RC)).
- Brushed DC braking: each position's conduction and switching loss against its formula; backwards running is the mirror image; braking near standstill draws from the supply. Brushless DC braking likewise. Electrical power equals shaft power plus winding loss in every quadrant.
- Stopping a flywheel returns the integral of back-EMF power less winding loss, and the capacitor voltage satisfies half C times the difference of the squared voltages.

## Level B addition

- A motor turning at 1.5 rpm, followed through three ten-second output periods in time, reaches the peak that the frequency-domain periodic solution gives, within 0.5 °C. The two share the loss waveform and nothing else.

## Level D: still empty

`motionsim validate` takes a file of measurements. None exists yet.

## Level C: figures stored as images, against the same datasheet's tables

onsemi NVXK2TR80WDT. Every figure is a picture. Eleven plot areas found; curve counts are right on all eleven (7, 6, 1, 2, 3, 3, 3, 3, 2, 1, 1).

| Figure | Read | Datasheet says | Difference |
|---|---|---|---|
| On-resistance against temperature | 1.00 at 25 °C | 1 by definition | under 1% |
| Body-diode voltage, 25 °C curve at 10 A | 4.03 V | 3.9 V | 3.3% |
| Gate charge: start of the plateau | 18.0 nC | 18 nC gate-source charge | 0.1% |
| Output capacitance at 800 V | 79.9 pF | 79 pF | 1.1% |
| Thermal impedance plateau | 1.85 K/W | 1.84 K/W maximum | under 1% |

The datasheet prints its own six-stage thermal network beside the curve. The fit to the traced curve is five stages with a worst error of 2.2%.

One datasheet, one drawing style. Synthetic pictures cover the cases in `tests/test_raster.py`.

## Level C: silicon MOSFET figures against its tables

Vishay IRF540, vector figures. Body-diode curve at 25 °C stays under the tabulated maximum. Gate-charge plateau starts at the tabulated gate-source charge. Output capacitance at 25 V within 1.6% of the table.

## Level A additions: pictures, charge, recommendations

- Pictures drawn in the tests: a plot area and its eleven grid lines found to 0.3 pt; one curve followed through the grid to within its stroke; two crossing curves each ending where they should; a branch that inherits the shared rise; a label with a leader line ignored; a dense log grid that neither breaks nor multiplies the curve.
- Plateau of a piecewise gate-charge curve found to 0.05 V and 1.5 nC.
- Output charge of a capacitance falling as one over root voltage equals twice capacitance times voltage, within 2%.
- Dead time from gate charge equals 1.5 times the sum of three intervals written out by hand, plus driver mismatch. For an IGBT, twice the tabulated delay plus fall time.
- Gate resistors land on the slew-rate, overshoot or driver-current limit, whichever is largest, rounded up.
- Heatsink resistance equals the temperature room over the loss for a device whose loss does not depend on temperature.

## Level A and B additions for trajectories

- A three-phase sine drive written out as a trajectory file reproduces the engine's direct result: loss and output power within 0.5%, peak junction temperatures within 0.3 °C, all six positions alike.
- Current out of a leg loads the high-side switch and low-side reverse path; current in loads the other two.
- A constant load from a cold start heats the switch by power times the transient impedance at the elapsed time, within 1%.

## Level A and B additions from the full check

- Clamping every leg to the positive rail and clamping to the negative rail give the same total loss, with the high side of one equal to the low side of the other, at power factors 1, 0.6 and −0.9. Both sit below space-vector PWM.
- A stepper's electrical power equals winding loss plus shaft power at six points covering all four quadrants, standstill and zero torque.
- The output period of a permanent-magnet and an induction motor is the same forwards and backwards.
- The busiest package carries one third, two thirds or all of a three-leg stage's loss for one-leg, two-leg and three-leg packages.
- Recovery charge is zero at no current and follows the current below its test point.
- Output power stops at the stage's linear range.
- 3,400 calls through the page's interface, with speeds, torques, voltages and frequencies from negative to fifty times nominal, bad motor values, and impossible loads and motions, each returned a finite result or a stated refusal.

An independent line-by-line audit against first principles confirmed: IGBT and diode loss terms; FET conduction, overlap, output-charge and dead-time terms, to four digits against hand calculation; switching events in every symmetric scheme and in block and H-bridge drive in all quadrants; the temperature loop and the periodic peak against time stepping; permanent-magnet control against a brute-force search; induction, brushless DC and brushed DC power balance; the load model; the DC-link energy balance; the heat-spreading plate against its closed-form limit; and unit handling throughout.

## Datasheets the reader has been tried on

No device data ships with this project and it favours no vendor. You bring the datasheets. This table says what the reader has been run on so far, so you can judge how far to trust it on yours.

| Kind of device | Datasheet tried | What was read | Outcome |
|---|---|---|---|
| IGBT module with built-in driver | three 600 V, 15 A modules from one vendor | 15 to 16 table values each; on one, on-state, diode, switching-energy, recovery and thermal curves | All table values match the page. Two have no curves at all. On the third, 10 of 11 curves agree with its tables within 8%; its hot turn-off curve disagrees with its table by 17%, so the table is used there. That one was compared with its vendor's simulator. |
| Discrete IGBT with diode | onsemi FGHL40T65MQD | 26 table values, on-state, diode, switching-energy and thermal curves | Curves agree with the datasheet's own tables within 4%. |
| GaN transistor | EPC EPC2302 | 12 table values, on-resistance against temperature, thermal curve | All match. Switching loss is estimated from charge. |
| Silicon MOSFET | Vishay IRF540, TI CSD19536KCS, Nexperia PSMN1R0-40YLD, Alpha and Omega AOT66916L | 14 to 17 table values each; on-resistance against temperature, body-diode, gate-charge, capacitance and thermal curves | Table values match the page. 19 of 25 curves accepted, within 11% of the tables and most within 3%. The first of the four gives maximums only, so its model is on the high side. Switching loss is estimated from charge. |
| SiC MOSFET, discrete | Wolfspeed C3M0075120K, ROHM SCT3040KL | 17 and 20 table values; thermal, capacitance, gate-charge and switching-energy curves | Table values match. 7 of 14 curves accepted. On the first, the switching-energy and body-diode figures are laid out in ways the reader does not handle (several figures a quantity, curves by gate voltage). |
| SiC MOSFET module | onsemi NVXK2TR80WDT (H-bridge) | 19 table values; five curves, from figures stored as images | Curves agree with the tables within 4%. Switching and recovery energy are tabulated at one current only, so their shape away from it is assumed. |
| GaN transistor, cascode | Nexperia GAN063-650WSA | 18 table values; thermal, on-resistance, capacitance and reverse-conduction curves | Read, but no model is built: the datasheet gives no gate plateau, threshold charge or transconductance to estimate switching from, and no switching energy. The tool says so and stops. |
| Discrete IGBT with diode, second vendor | STMicroelectronics STGW40H65DFB | 25 table values; on-state, diode, switching-energy, energy-against-gate-resistance and thermal curves | 10 of 13 curves accepted, within 1.1% of the tables. The diode thermal-impedance figure is too cluttered to confirm, so the table value is used. |
| Superjunction MOSFET | STMicroelectronics STW48N60M2 | 14 table values; gate-charge, capacitance, on-resistance, body-diode and thermal curves | Builds. The gate plateau is read from a figure that also draws the drain voltage. Switching loss is estimated from charge. |
| IGBT module with built-in driver, second vendor | onsemi (Fairchild) FNB41560B2 | 7 table values; six switching-energy curves from two plots under one caption | Builds. The datasheet tabulates no switching energy, so the curves are identified by their colour in the legend and say so. |
| Discrete IGBT, scanned datasheet | an older 600 V part whose datasheet is page images | 19 table values, read from page images | Builds from table values. Its figures are not read. Diode recovery energy is estimated from the tabulated recovery charge. |
| Rectifier (diode) bridge | not supported | | |

Each row is one run checked by hand. The reader uses a language model and its output can differ between runs.
