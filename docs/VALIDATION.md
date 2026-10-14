# Validation

Every check the tool is held to, by how strong a claim it supports, strongest last. Vendor tools and charts are cross-checks, not ground truth.

- **A, mathematical**: closed-form solutions.
- **B, numerical**: independent numerical integration, written apart from the engine.
- **C, external**: a datasheet against itself, vendor charts, a vendor's public simulator.
- **D, physical**: measured inverter or double-pulse data. One published inverter loss measurement so far; no published measurement of junction temperature.

Modules A, B and C in this document are three 600 V, 15 A IGBT modules with built-in drivers from one vendor. They are not named.

## Level A: closed forms

All of these are in `tests/` and pass.

### Loss and temperature

For a device with on-state voltage `V0 + r·I` and switching energy `k·I`, under sinusoidal PWM with peak current `Ipk`, modulation index `m` and power factor `cos φ`:

| Quantity | Closed form |
|---|---|
| Switch conduction | `V0·Ipk·(1/2π + m·cos φ/8) + r·Ipk²·(1/8 + m·cos φ/3π)` |
| Diode conduction | `V0·Ipk·(1/2π − m·cos φ/8) + r·Ipk²·(1/8 − m·cos φ/3π)` |
| Switching | `fsw·k·Ipk/π·(Vdc/Vref)` |

The engine matches all three within 1% over 15 combinations of `m` (0.1, 0.6, 1.0) and power factor (1, 0.8, 0.3, 0, −0.7).

Also checked: steady-state temperatures, the self-consistent temperature for an on-state voltage that rises with temperature, detection of thermal runaway, the Foster step response, and the maximum-current solver.

### Modulation

- Every PWM scheme delivers the same fundamental voltage.
- Continuous schemes give the same switching loss as sine.
- The 60° discontinuous scheme halves switching loss at unity power factor.

### Field-effect transistors

- A resistive channel conducting in both directions loses `R·Irms²/2` per switch, independent of modulation index and power factor.
- Dead-time loss equals `2·t_dead·fsw·Vreverse·Ipk/π`, and channel conduction falls by the matching amount.
- Charge-based switching loss matches its closed form.

### The motor model

- Surface-magnet machine: torque current, voltages and frequency match the dq equations.
- Electrical power into the motor equals shaft power plus copper loss, for surface-magnet and salient machines.
- Salient machine: the chosen current is smaller than at neighbouring d-axis currents giving the same torque.
- Field weakening: voltage sits at the limit and torque is unchanged.

### Motor types

- Brushed DC on an H-bridge: conduction and switching loss of the chopping switch, the freewheeling position and the steering switch each match their formulas; a MOSFET bridge loses exactly `2·I²·R`.
- Brushless DC with block commutation: high-side and low-side positions match their formulas over the 120° windows.
- Induction motor: electrical input equals shaft power plus stator and rotor copper loss; slip matches its formula; at the voltage limit the flux falls and the voltage sits on the limit.
- Stepper: equals eight sinusoidal positions of the three-phase engine at the same leg modulation.

### Loads and motions

- Each load term (inertia, friction, fan law, gravity arm, vehicle on a slope) matches its formula.
- A gearbox multiplies speed and divides torque, and its loss is taken from whichever side is driving.
- A steady motion gives the single-point result.
- Spinning an inertia up and back down returns net zero shaft energy.
- A robot arm raised a quarter turn ends horizontal, holding its full gravity torque.

### The package model

- A chip covering its whole plate gives pure one-dimensional conduction through the insulation.
- Far from a small source on a large plate, the rise matches the Bessel-function solution within 5%.
- The thermal matrix is symmetric and falls with distance.

### Curves, transistors, time, braking

- A curve drawn as a staircase of 0.07 pt steps with repeated points, cut into pieces, comes back as one curve and reads the right value.
- Two curves per label are read as their upper envelope; a legend stroke in the plot is ignored.
- Transistor with tabulated energy: turn-on loss equals switching frequency times energy times peak current over pi. Output charge estimated from capacitance equals twice capacitance times voltage. Plateau from transconductance equals threshold plus rated current over gain.
- Through time, a short pulse on a constant-loss switch heats it by power times the transient impedance at that time, to six figures. Cooling after a pulse follows each stage's exponential.
- A long steady motion settles at the steady solution within 0.2 °C.
- A heatsink warms as ambient plus loss times resistance times (1 − exp(−t/RC)).
- Brushed DC braking: each position's conduction and switching loss against its formula; backwards running is the mirror image; braking near standstill draws from the supply. Brushless DC braking likewise. Electrical power equals shaft power plus winding loss in every quadrant.
- Stopping a flywheel returns the integral of back-EMF power less winding loss, and the capacitor voltage satisfies half C times the difference of the squared voltages.

### Pictures, charge, recommendations

- Pictures drawn in the tests: a plot area and its eleven grid lines found to 0.3 pt; one curve followed through the grid to within its stroke; two crossing curves each ending where they should; a branch that inherits the shared rise; a label with a leader line ignored; a dense log grid that neither breaks nor multiplies the curve.
- Plateau of a piecewise gate-charge curve found to 0.05 V and 1.5 nC.
- Output charge of a capacitance falling as one over root voltage equals twice capacitance times voltage, within 2%.
- Dead time from gate charge: the three intervals of turn-off written out by hand, a tenth longer, plus the mismatch between driver channels, times 1.2. For an IGBT, the tabulated delay plus fall time, a tenth longer, plus the driver mismatch, times 2.
- Gate resistors land on the slew-rate, overshoot or driver-current limit, whichever is largest, rounded up.
- Heatsink resistance equals the temperature room over the loss for a device whose loss does not depend on temperature.

### Trajectories

- A three-phase sine drive written out as a trajectory file reproduces the engine's direct result: loss and output power within 0.5%, peak junction temperatures within 0.3 °C, all six positions alike.
- Current out of a leg loads the high-side switch and low-side reverse path; current in loads the other two.
- A constant load from a cold start heats the switch by power times the transient impedance at the elapsed time, within 1%.

### Symmetry, balance and the page's interface

- Clamping every leg to the positive rail and clamping to the negative rail give the same total loss, with the high side of one equal to the low side of the other, at power factors 1, 0.6 and −0.9. Both sit below space-vector PWM.
- A stepper's electrical power equals winding loss plus shaft power at six points covering all four quadrants, standstill and zero torque.
- The output period of a permanent-magnet and an induction motor is the same forwards and backwards.
- The busiest package carries one third, two thirds or all of a three-leg stage's loss for one-leg, two-leg and three-leg packages.
- Recovery charge is zero at no current and follows the current below its test point.
- Output power stops at the stage's linear range.
- 3,400 calls through the page's interface, with speeds, torques, voltages and frequencies from negative to fifty times nominal, bad motor values, and impossible loads and motions, each returned a finite result or a stated refusal.

Checked term by term against hand calculation: IGBT and diode loss terms; FET conduction, overlap, output-charge and dead-time terms, to four digits; switching events in every symmetric scheme and in block and H-bridge drive in all quadrants; the temperature loop and the periodic peak against time stepping; permanent-magnet control against a brute-force search; induction, brushless DC and brushed DC power balance; the load model; the DC-link energy balance; the heat-spreading plate against its closed-form limit; and unit handling throughout.

### Ripple at the switching frequency, and the link capacitor

- The DC-link capacitor's ripple current, found from the switching sequence, against the closed form for three sinusoidal currents: within 2% at 32 combinations of modulation index (0.2 to 1.0), power factor (−0.9 to 1.0) and scheme (sine and space-vector). The mean link current equals the power balance.
- One leg chopping into a winding: capacitor current I·√(D(1−D)) and current ripple V·D(1−D)/(L·f), both exact, at three duty cycles.
- Three-phase ripple stays under one leg's bound V/(4·L·f) for three schemes and three modulation depths, and scales inversely with inductance.

### Life, per chip

- A single swing gives the model's own number of cycles; a swing twice as large lasts 2^5.039 times fewer.
- A motion held at 2 Hz electrical for a minute counts between 100 and 140 swings of the size of the swing within one turn, and lasts less than a tenth as long as the same current at high speed.

### What a device can drive

- At the torque limit the hottest junction is at its rating within 0.5 °C, and 2% more torque is over it.
- The limit falls with switching frequency and with heatsink temperature; past the motor's reach, the motor is what stops it.

### Parallel devices, the link, a hot motor

- Devices in parallel: two at 30 A are two stages of one at 15 A.
- A module with and without a stated case-to-heatsink resistance of the same value gives the same junction temperature.
- The DC link as a bucket: a short stretch of motoring between two brakings takes out only what it uses.
- A hot motor: current up by the inverse of the magnet factor, winding loss by the copper factor over its square.
- A magnet motor's back-EMF at speed against the supply and the rating.

### The motor and the stage, further

- Iron loss: the shaft gives the same, the motor loses the stated watts more plus the copper loss of the current that supplies them.
- Saturation: far below the saturation current nothing changes; at it, a reluctance motor needs over 5% more current for the same torque.
- A buried-magnet motor is found past the speed where full opposition of the magnet is not enough, with id beyond that point and the voltage within its limit.
- Ripple at the switching instants: turn-on loss falls and turn-off loss rises.
- Devices in parallel with a spread of 1.5: the hardest-worked of a pair has the temperature of 60% of the current, and the stage loses what 60% and 40% lose.
- A chosen gate resistor is never below the transistor's own.

### Ranking

A comparison has to put parts in the right order, not only give each a plausible loss. Level A, in `tests/test_ranking.py`:

- Two made-up parts alike but for this: one drops 0.9 V more when conducting and switches with a quarter of the energy. The frequency at which their losses are equal follows from the closed forms for conduction and switching loss. The comparison puts the slower part first at 0.8 of that frequency and the faster one first at 1.2, and the crossing found by sweeping the frequency is within 1% of the closed form.
- Parts whose losses are within 5% are returned as level, and the part beyond that is not.
- The margin to the junction limit is the rating less the top of the temperature range, at the design point and holding the torque at standstill; when the part that loses least is not the one with the most margin, the explanation says so with the figures.
- A part with measured switching energy beside one estimated from charge, and a part brought in proportion to a higher voltage than tested beside one that is not, are each said to be compared on unlike data.

In `tests/test_limits.py`: what the motor and the stage note about their own model does not make a data caution; a loss term outside its data does, once it could move the stage's loss by 5%; table points and an estimate from charge are a stated footing.

No ranking has been checked against measured parts.

### A part typed in, a dead time left open, cooling by air

Level A, in `tests/test_entry.py`:

- A transistor typed in holds each figure as typed, in SI units, and loses in conduction what its typed resistance gives in closed form, within 2%.
- Eight slips are each refused at the figure they sit in: an on-resistance a thousand times too large, a plateau below the threshold, a hot resistance below the cold one, a junction-to-ambient figure given as junction-to-case, a figure missing or not a number, an output charge with no voltage, a part with no name.
- A dead time left open is the one the dead-time rule gives for the gate drive in use, its loss is counted, and the caution for a missing dead time is gone; a dead time the user gave is left alone.
- The dead-time rule itself, in `tests/test_recommend.py`: the three intervals of turn-off from the gate charges, a tenth longer, plus the mismatch between driver channels, times 1.2, and never under the floor. The figures behind it are published ones: gate-driver delay matching from 4 to 60 ns across six common half-bridge drivers, a tenth longer switching for 100 K, and defaults of 100 to 800 ns in open motor-control firmware and driver chips.
- Copper and a shared board: the pad relation reproduces the figure printed for a TO-263 and agrees with the one printed for a DPAK within 3% as a ratio from 0.5 to 25 cm²; a 100 cm² board is 5 K/W to still air; on a shared board the hottest case sits at the air plus its own loss through its own path plus the others' loss through the board, and never under the board's own rise; past 120 °C the checks say so. Against a published rule of thumb (15.3 cm² of two-sided board a watt for a 40 K rise), the board term alone gives 33 K for the same area: the same order, a little cooler, with each part's own rise on top.
- A request superseded after its status arrived and before its body did is a superseded request, not an answer (`web/tests/api.test.ts`).
- A heatsink in air settles at the air's temperature plus its resistance times the stage's loss, and the junction is the same as with a heatsink held at that temperature. Two devices in parallel load it with both.
- With no heatsink the case of each package sits at the air's temperature plus its own resistance to air times its own loss.
- Through the page: each kind of cooling asks for the figure it needs and refuses without it, and the motion follows the same cooling.

One real 100 V transistor, typed in with the same table figures its read model holds, set beside that read model on a 48 V motor at 20 kHz: 1.98 W typed against 2.00 W read at 1 N·m, and 19.7 W against 19.8 W at 4 N·m. The read model has the body diode's curve and the output charge against voltage; the typed one has one figure for each, and at this voltage that costs under 1%. It says nothing about how well either matches the part.

## Level B: independent numerical integration

- The periodic thermal response is compared with a separate step-by-step integration of a three-stage network driven by half-sine power pulses. Peak temperature agrees within 0.5%.
- A motor turning at 1.5 rpm, followed through three ten-second output periods in time, reaches the peak that the frequency-domain periodic solution gives, within 0.5 °C. The two share the loss waveform and nothing else.
- The loss and temperature solver was set against a calculation written apart from it, by numerical integration over the output period: 421 operating points of an IGBT with its diode and 240 of a MOSFET, across six modulation schemes, modulation index 0.05 to 1.15, power factor -1 to 1, 2 to 40 kHz and 25 to 110 °C. Total loss agrees within 0.14%, each loss term within 0.4%, junction rise within 0.15%. The motors (currents, voltages, slip, field weakening found by a brute-force scan) agree within 0.01%; the link capacitor's current and the motor current's ripple, against a simulation of the switching itself, within 0.5%.

## Level C: external references

### Datasheets against their own tables

A curve and a table are two statements of the same quantity in one document. Agreement confirms the axis reading, the digitising and the curve matching. It does not confirm the device data itself, and the table values were used to choose which curve is which, so these are consistency checks, not independent ones.

**onsemi FGHL40T65MQD (discrete IGBT with diode), vector figures.**

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

**EPC2302 (GaN transistor).**

| Check | Result |
|---|---|
| Normalised on-resistance curve at 25 °C | 1.00 |
| Thermal impedance plateau after scaling | 0.196 K/W against 0.2 K/W tabulated |

The charge-based switching loss for this part has no reference of any kind.

**Vishay IRF540 (silicon MOSFET), vector figures.** On-resistance against temperature reads 1.0 at 25 °C as a normalised curve must. The single-pulse thermal curve, followed along the line the family merges into, reaches 0.94 K/W against a tabulated maximum of 1.0. The body-diode curve at 25 °C stays under the tabulated maximum. The gate-charge plateau starts at the tabulated gate-source charge. Output capacitance at 25 V is within 1.6% of the table.

**onsemi NVXK2TR80WDT (SiC module), figures stored as images.** Every table value was found on the page it was cited from. Every figure is a picture. Eleven plot areas found; curve counts are right on all eleven (7, 6, 1, 2, 3, 3, 3, 3, 2, 1, 1).

| Figure | Read | Datasheet says | Difference |
|---|---|---|---|
| On-resistance against temperature | 1.00 at 25 °C | 1 by definition | under 1% |
| Body-diode voltage, 25 °C curve at 10 A | 4.03 V | 3.9 V | 3.3% |
| Gate charge: start of the plateau | 18.0 nC | 18 nC gate-source charge | 0.1% |
| Output capacitance at 800 V | 79.9 pF | 79 pF | 1.1% |
| Thermal impedance plateau | 1.85 K/W | 1.84 K/W maximum | under 1% |

The datasheet prints its own six-stage thermal network beside the curve. The fit to the traced curve is five stages with a worst error of 2.2%.

One datasheet, one drawing style. Synthetic pictures cover the cases in `tests/test_raster.py`.

### Module A against its own datasheet chart

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


**The vendor chart lies inside the bracket at all ten points.** Limiting the average alone would allow 42 to 55% more current than the chart.

The bracket is wide, roughly 0.6 to 1.5 times the chart value. That is what this datasheet can support: without transient thermal data the tool cannot say more.

#### Diagnostic, not part of the model

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

### Module C against its vendor's public simulator

Six operating points at 300 V and modulation index 0.8, sinusoidal PWM. The model is built from the datasheet alone: its tables, and its on-state, diode, turn-on, recovery and transient thermal curves. Turn-off stays on the table, because the hot curve disagrees with it by 17%. Heating between chips is computed for a generic package with the construction left unknown. Nothing is fitted to the simulator. The simulator's temperatures start from the case, so the reference says that nothing lies between case and heatsink.

| Point | Total loss, ours against simulator | Hottest junction, ours against simulator | Ours, range | Inside |
|---|---|---|---|---|
| 50 Hz, 6 kHz, pf 0.8 | 24.1 against 22.8 W, +6% | 112.8 against 112.6 °C, +0.2 | 105 to 129 | yes |
| 50 Hz, 16 kHz, pf 0.8 | 35.7 against 31.7 W, +12% | 144.8 against 141.4 °C, +3.4 | 133 to 169 | yes |
| 50 Hz, 6 kHz, pf −0.8 | 24.9 against 23.8 W, +5% | 114.1 against 121.6 °C, −7.5 | 107 to 130 | yes |
| 50 Hz, 16 kHz, pf 0.3 | 35.8 against 32.0 W, +12% | 142.3 against 140.6 °C, +1.7 | 130 to 167 | yes |
| 5 Hz, 6 kHz, pf 0.8 | 24.1 against 22.8 W, +6% | 117.8 against 115.9 °C, +1.9 | 110 to 134 | yes |
| 200 Hz, 6 kHz, pf 0.8 | 24.1 against 22.7 W, +7% | 111.9 against 111.3 °C, +0.6 | 104 to 128 | yes |

Where the switch is the hottest chip the junction is 0.2 to 3.4 °C high, on a loss 6 to 12% high. Where the diode is, it is 7.5 °C low: the diode's junction is 8 to 11 °C low at every point, which a single coupling figure for switch and diode alike cannot mend (the simulator's own is half as large again for the diode). Heating between chips is reckoned over the package's own face, 0.36 K/W here against the simulator's 0.5.

Turn-on at 6 kHz is 0.55 W a switch against the simulator's 0.41 W, a third high. The curve used is the higher of the high-side and low-side curves, which explains some of it and not all. The range is wide because the construction is unknown and every package input is varied together.

Modules A and B could not be run in the same simulator. One part, one vendor, and the reference is a model, not a measurement. `motionsim validate` runs such a comparison from a file of reference points; the simulator's output is not redistributed here.

## Level D: one public measurement, and what it does and does not show

A measured inverter loss, from a published reference design: Texas Instruments TIDA-00364, design guide TIDUCB6, tables 7 and 8. A 48 V three-phase inverter with five CSD19536KTT in parallel at each switch (30 in all) on a heatsink, sinusoidal PWM into an induction motor on a dynamometer, loss measured with a power analyzer from DC input to motor terminals at 8 and at 10 kHz, from 27 to 131 A rms.

The model: the CSD19536KCS as read from its datasheet (the same die in another package), with its on-resistance scaled to the 2 mΩ the guide gives for the KTT; five in parallel; 12 V gate drive; turn-on through the guide's shared 24 Ω and 8.2 Ω a device, turn-off through 8.2 Ω; modulation index and power factor worked out from the table's own voltage, current and power at each row. The guide does not give the heatsink temperature or the dead time, so the model was run across 30 to 60 °C and 100 to 500 ns; that moves the result by 4% either way.

| Phase current | Measured, 8 kHz | Model | Model over measured | Measured, 10 kHz | Model | Model over measured |
|---|---|---|---|---|---|---|
| 27 A | 12.1 W | 10.1 W | 0.84 | 15.3 W | 12.4 W | 0.81 |
| 40 A | 17.9 W | 15.3 W | 0.85 | 21.1 W | 18.9 W | 0.90 |
| 54 A | 25.1 W | 21.1 W | 0.84 | 29.1 W | 26.1 W | 0.90 |
| 71 A | 35.0 W | 28.8 W | 0.82 | 40.8 W | 35.7 W | 0.88 |
| 93 A | 51.3 W | 39.3 W | 0.77 | 59.9 W | 49.2 W | 0.82 |
| 131 A | 92.4 W | 63.3 W | 0.69 | 99.8 W | 73.2 W | 0.73 |

(The two frequencies were measured at slightly different currents; the row label is their mean.)

What it shows:

- The model is 10 to 31% below the measured loss, and further below as the current rises.
- The measurement is of the whole inverter: board copper, connectors and snubbers are in it, and they are not in the model. The part of the measured loss that does not change with frequency is about three times the transistors' own conduction loss at 131 A, and grows with the square of the current: about 0.8 mΩ a phase of resistance outside the transistors would account for it. The guide gives no figure to check that against, so the conduction model is neither confirmed nor refuted by this.
- The part that changes with frequency can be separated, from the two rows measured at the same current. At 27 A the measured loss rises by 1.6 W for each kHz and the model's by 1.1 W; at 131 A, 3.7 W against 4.8 W. So the switching estimate from gate and output charge is about 30% low at low current and 30% high at high current on this board. The snubbers, which lose the same at any current, are part of the first.

What it does not show: anything about the junction temperature, about measured-energy parts, or about a board whose own resistance is known. One design, one part. The same source's companion (TIDA-010056, TIDUEQ9, the same transistor one to a switch, six-step, no heatsink) and the motor-drive boards published for the GaN part read here give further points and have not been run yet.

`motionsim validate` takes a file of measurements, for anyone with their own. A point can give each loss term on its own, how the stage was mounted, and a load that comes and goes with the junction's lowest and highest temperature once it repeats.

## Datasheets the reader has been tried on

No vendor's device data ships with this project, only made-up parts, and it favours no vendor. You bring the datasheets. This table says what the reader has been run on so far, so you can judge how far to trust it on yours.

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
| IGBT module with built-in driver, second vendor | onsemi (Fairchild) FNB41560B2 | 7 to 8 table values; six switching-energy curves from two plots under one caption | Builds. The datasheet tabulates no switching energy, so the curves are identified by their colour in the legend and say so. |
| Discrete IGBT, scanned datasheet | an older 600 V part whose datasheet is page images | 19 table values, read from page images | Builds from table values. Its figures are not read. Diode recovery energy is estimated from the tabulated recovery charge. |
| Rectifier (diode) bridge | not supported | | |

Each row is one run checked by hand. The reader uses a language model and its output can differ between runs.

## The page and the tests

The page is toured at four widths, from 1440 px down to 320 px, through every step and tab. It is also walked at random: a seeded sequence of whatever can be pressed, on a desk-width and a phone-width screen, with every placement check run after each press and nothing allowed to stay waiting. Six walks of thirty presses, about 180 surfaces a run. One fixed journey through the hosted page runs in CI at two widths: a first visit, a made-up part, every step to a verdict, a setting changed, a reload.

The cooling, dead-time and typed-part code is held by tests whose expected values are worked out apart from the code: closed forms, literals from the published figures, and one path through the engine checked against another. Among them (`tests/test_entry.py`, `tests/test_values.py`):

- A point held as a motion ends within 1 K of the steady solution, for seven combinations of motor and cooling: at standstill, on an H-bridge, on a shared board, on a heatsink in air, with devices in parallel. The two are worked out by different code.
- A motion that cannot settle in air says so.
- The junction-to-air figure the heatsink advice gives for doing without a heatsink, fed back as the cooling, puts the hottest junction on the limit, running and held still, for a permanent-magnet, a six-step and a brushed motor; a figure a fifth larger passes it.
- The dead time chosen is never under the rule's own least. Its loss is the body diode's voltage times the current it carries for both edges of each period, within 1%.
- A typed figure outside what a power transistor can have is refused with its unit; the page and the command line give the same loss for the same part with the dead time left open.
- Whether a motor fits a part, before any design point: the current it draws at its limit against the part's rating, and the speed it reaches against the speed asked.

A whole design run from one file (`motionsim design run`) gives the figures the page's own steps give, asked one by one (`tests/test_design.py`).

The figures the product exists for are held to the last digit (`tests/test_golden.py`): one operating point, three devices compared on one motor, the same comparison across switching frequency, a load's motion on two kinds of motor, what a device can drive, what to build around it, and a whole design with two devices. It says nothing about whether a figure is right, only that code moved or renamed has left it where it was; the same figures come out to the twelfth digit on Python 3.11 and 3.12.

What must hold at any operating point is tried at points drawn at random (`tests/test_properties.py`): no loss is negative, more current or a faster switch never loses less, a hotter heatsink never leaves a cooler junction, two devices in parallel carrying twice the current lose twice what one does, and a comparison does not depend on the order its parts are named in.

The engine is run as the hosted page loads it, with the datasheet reader's libraries absent, through every route the page calls (`tests/test_hosted.py`).

The page in its hosted form scores 100 for accessibility, best practices and search in Lighthouse at desk and phone widths, with no layout shift as it loads. The tour fails on a control with no name, a request that fails while the page loads, a layout shift at load, a sentence squeezed beside something else, a refusal shown away from its figure, a chart without named axes and units, or drawing text under 9.5 px. It runs at four widths, from 1440 px down to 320 px, and checks that each step opens at its heading.

What the page shows is held to what it would show afresh. A walk presses controls in an order nobody planned (tabs, steps, the device on the drawing, what is compared, values of a setting added and taken out), on two parts that differ so that one cannot pass for the other, and every fifth press it reloads the page from what it saved and compares every figure on show: a figure left over from before the last change, or one that belongs to another device, fails it. A second script chooses another device at four delays after one of the slow tabs is opened, in the local page and in the hosted one, and holds the page to the same test.

The engine the hosted page runs inside the browser is the same Python as the installed one, and is held to it: 44 figures (every kind of motor at its starting point, a motion, a map) agree to better than one part in a thousand million, checked on every change (`web/scripts/engine-check.mjs`).

## What these figures were produced with

The engine's figures in this document were last produced with Python 3.12.3 (the tests also run on 3.11), NumPy 2.5.3, SciPy 1.18.1 and Pydantic 2.13.5. The package itself asks only for lower bounds; the product's figures are held to the last digit by `tests/test_golden.py`, so a version of a library that moves one fails there before it reaches a result.

Reading a datasheet is different: it uses a language model, and two readings can differ. The model is named in `src/motionsim/observe/reader.py`; what was read is saved beside each device model, value by value with its page, and it is that saved reading, not a fresh one, that a result rests on.
