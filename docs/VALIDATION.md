# Validation

Every check the tool is held to, by how strong a claim it supports, strongest last. Vendor tools and charts are cross-checks, not ground truth.

- **A, mathematical**: closed-form solutions.
- **B, numerical**: independent numerical integration, written apart from the engine.
- **C, external**: a datasheet against itself, vendor charts, a vendor's public simulator.
- **D, physical**: measured inverter or double-pulse data. Four published reference designs so far: two inverters' measured loss, and three boards' measured temperature of the hottest transistor case.

Modules A, B and C in this document are three 600 V, 15 A IGBT modules with built-in drivers from one vendor. They are not named.

## What holds each claim

A count of tests below is of test functions; a function run over several cases counts once.

A claim here is held in one of three ways. A **test in CI** runs on every change and fails if the claim stops being true. A **script, not in CI** is in the repository and is run by hand. A **one-off** was done once, by hand or with a script and data that are not in the repository, usually because it needs a datasheet or a vendor's output that is not ours to distribute: it cannot be reproduced from the repository alone, and nothing fails if it stops being true.

| Claim | How it is held | Where |
|---|---|---|
| Level A: the closed forms | test in CI, except two lines marked one-off | `tests/`, by the file each section names |
| Level B: the periodic thermal response against time stepping; a slowly turning motor against the periodic solution | test in CI | `tests/test_ripple.py`, `tests/test_transient.py` |
| Level B: 421 and 240 operating points against a separate calculation | one-off | script and points not in the repository |
| Level C: datasheets against their own tables | plot areas and part of the curves by a test that runs only where the datasheets are present, so not in CI; the rest one-off | `tests/test_real_datasheets.py` |
| Level C: Module A against its datasheet chart, Module C against its vendor's simulator | one-off, Module A's with an earlier state of the tool | the chart readings and the simulator's output are not in the repository |
| Level C: the published boards' transistors through their makers' own calculators at the same points | not done | no maker publishes such a calculator's result at these points where it can be cited, and the calculators themselves are interactive |
| The same three currents on the made-up module of the examples, as the code gives them today | rerun by hand on this version; no test holds them | the section on Module A |
| Level D: the first published inverter loss measurement | one-off | the measured figures are in the table below; the model's inputs are not in the repository |
| Level D: three published boards, measured case temperature and stage loss | test that runs only where the device models are present, so not in CI | `tests/test_published_boards.py`, with the device models in a `runs/validation/` folder that is not in the repository |
| The datasheets the reader has been tried on | one-off, one run each, checked by hand | nothing in the repository |
| The reader's checks on recorded readings of made-up datasheets | test in CI, no key and no model call | `evals/reader`, the tests marked `reader_eval`; see "Reader accuracy eval" |
| A typed part beside its read model | one-off | needs the datasheet |
| 3,400 calls through the page's interface | one-off | script not in the repository |
| The product's figures stay where they are | test in CI, to a relative 1e-9 | `tests/test_golden.py` |
| What must hold at any operating point | test in CI | `tests/test_properties.py` |
| A whole design from one file gives the page's figures | test in CI | `tests/test_design.py` |
| The engine without the reader's libraries, through every route the page calls | test in CI | `tests/test_hosted.py` |
| The engine in the browser gives the installed engine's figures | script in CI, to a relative 1e-9 | `web/scripts/engine-check.mjs` |
| One fixed journey through the hosted page | script in CI | `web/scripts/journey.mjs` |
| A device changed while an answer is on its way, the search for the largest load cancelled partway (the engine in the browser holds to having stopped), and two short random walks, on the local and the hosted page | script in CI | `web/scripts/race.mjs`, `walk.mjs` |
| The search for the largest load reports each probe and ends in the answer it gave before; a page that stops waiting stops it on the server | test in CI | `tests/test_heavier_probes.py`, `tests/test_streamed.py` |
| An answer kept for the report is the one worked out afresh, and never one for another request or device file | test in CI | `tests/test_remembered.py` |
| The control lab: a held point against the settled engine, the loops against linear theory and a calculation by hand, the blocks against closed forms, every exploration's direction | test in CI | `tests/test_control_*.py`, 422 tests |
| The motor's saturating iron, the twisting shaft and the disturbance-observer speed loop: the iron map gives back its calibration and is reciprocal, the plant keeps the terminal energy, a free shaft swings at √(K(1/Jm+1/Jl)) and decays at c/2Jeq, the speed loop's poles are its control law's and its observer's | A, B; test in CI | `tests/test_control_magnetics.py`, `tests/test_control_shaft.py`, `tests/test_control_adrc.py` |
| The board reader: partial inductances and meshed loops against closed forms, the half bridge found in made-up boards, files that cannot be read refused | test in CI | `tests/test_board_*.py`, 98 tests |
| The local app: every address answered as the service's own dispatch answers it, the key never sent back, the store, the streams | test in CI | `tests/test_app_*.py`, 145 tests |
| The control lab or the board reader against a measured drive, a field solver or a measured board | not done | nothing |
| The tour at four widths, and the long random walk | script, not in CI | `web/scripts/measure.mjs`, `walk.mjs` |
| Lighthouse scores | one-off measurement | nothing in the repository |

## Level A: closed forms

All of these are in `tests/` and run in CI, except the two lines that say they were checked once.

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
- Recovery charge is zero at no current, follows the current below its test point and grows as the square root above it.
- Output power stops at the stage's linear range.
- Checked once, with a script that is not in the repository: 3,400 calls through the page's interface, with speeds, torques, voltages and frequencies from negative to fifty times nominal, bad motor values, and impossible loads and motions, each returned a finite result or a stated refusal.

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

Figures left empty and a typed IGBT (`tests/test_typed_defaults.py`, `tests/test_typed_igbt.py`, `tests/test_cooling_offer.py`):

- A typed transistor's highest junction temperature left empty is 175 °C for silicon and SiC and 150 °C for GaN; its plateau is 3.0 + 2 = 5.0 V and its gate-source charge 1.4 × 14 = 19.6 nC on the template, with the charge at threshold following as 11.76 nC. Each one taken is a note with its own code naming the value used, holds a verdict that otherwise passes at a caution, and names the box it goes in; a part with every figure given carries nothing taken, and its file is as before.
- A typed IGBT built from the made-up module's figures holds its on-state lines and energies as typed. Its IGBT conduction is the hand formula for sine PWM with 0.80 V and 45 mΩ, 4.738 W, to 0.2%; its energies are the file's to 0.5%; its loss is the file's plus 1.2% ± 0.3%, the difference being the 25 °C line the file draws and the typed part does not. With the hot figures alone, the knee is 1.075 V, the energies are held hot, and the loss is 16% ± 1% above the file's, with the five figures taken said and the verdict held. Eleven slips are each refused at their box, among them a knee above its voltage, a cold energy above the hot one, a test voltage above the rating and an energy typed in joules. The command line builds the same part from `motionsim template igbt`.
- The heatsink offered at 40 °C air is 20 W over the loss with the heatsink held at 60 °C, to 1e-12, and that heatsink, used, settles at 60 °C to 1 mK with the same loss to 1e-4; none is offered in air at 60 °C. The board offered keeps the top of the junction's range under 175 °C, and a board 2% smaller than the area found does not; where every board keeps it cool, the offer is the area the six packages' copper needs, 6 × 6.45 cm². A cooling taken from the offer gives the same loss as the same figure typed, and its verdict is held at a caution that names the box.

Checked once, on a datasheet that is not in the repository: one real 100 V transistor, typed in with the same table figures its read model holds, set beside that read model on a 48 V motor at 20 kHz: 1.98 W typed against 2.00 W read at 1 N·m, and 19.7 W against 19.8 W at 4 N·m. The read model has the body diode's curve and the output charge against voltage; the typed one has one figure for each, and at this voltage that costs under 1%. It says nothing about how well either matches the part.

## Level B: independent numerical integration

- The periodic thermal response is compared with a separate step-by-step integration of a three-stage network driven by half-sine power pulses. Peak temperature agrees within 0.5%. In CI (`tests/test_ripple.py`).
- A motor turning at 1.5 rpm, followed through three ten-second output periods in time, reaches the peak that the frequency-domain periodic solution gives, within 0.5 °C. The two share the loss waveform and nothing else. In CI (`tests/test_transient.py`).
- Checked once, with a script and points that are not in the repository: the loss and temperature solver was set against a calculation written apart from it, by numerical integration over the output period: 421 operating points of an IGBT with its diode and 240 of a MOSFET, across six modulation schemes, modulation index 0.05 to 1.15, power factor -1 to 1, 2 to 40 kHz and 25 to 110 °C. Total loss agrees within 0.14%, each loss term within 0.4%, junction rise within 0.15%. The motors (currents, voltages, slip, field weakening found by a brute-force scan) agree within 0.01%; the link capacitor's current and the motor current's ripple, against a simulation of the switching itself, within 0.5%.

## Level C: external references

### Datasheets against their own tables

A curve and a table are two statements of the same quantity in one document. Agreement confirms the axis reading, the digitising and the curve matching. It does not confirm the device data itself, and the table values were used to choose which curve is which, so these are consistency checks, not independent ones.

The datasheets are their makers' property and are not in the repository, so the figures in this section cannot be reproduced from it. `tests/test_real_datasheets.py` holds the plot areas found and some of the curves below wherever a `datasheets/` folder has the files, and skips where it does not, as it does in CI. The rest are readings made once.

**A 650 V discrete IGBT with its diode, vector figures.**

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

**A 100 V GaN transistor.**

| Check | Result |
|---|---|
| Normalised on-resistance curve at 25 °C | 1.00 |
| Thermal impedance plateau after scaling | 0.196 K/W against 0.2 K/W tabulated |

The charge-based switching loss for this part has no reference of any kind.

**A 100 V silicon MOSFET, vector figures.** On-resistance against temperature reads 1.0 at 25 °C as a normalised curve must. The single-pulse thermal curve, followed along the line the family merges into, reaches 0.94 K/W against a tabulated maximum of 1.0. The body-diode curve at 25 °C stays under the tabulated maximum. The gate-charge plateau starts at the tabulated gate-source charge. Output capacitance at 25 V is within 1.6% of the table.

**A 1200 V SiC module, figures stored as images.** Every table value was found on the page it was cited from. Every figure is a picture. Eleven plot areas found; curve counts are right on all eleven (7, 6, 1, 2, 3, 3, 3, 3, 2, 1, 1).

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

**This comparison cannot be rerun from this repository.** The module's device file is not in it (the datasheet is its maker's), and the figures below are as recorded with an earlier state of the tool, before heating between chips and an assumed transient response were modelled. They are kept as a record of what was found, not as a statement of what the code gives today.

The datasheet's Figure 15 gives maximum RMS current against case temperature at 300 V, modulation index 0.8, power factor 0.8, sinusoidal PWM, junction temperature at most 150 °C. The model was built only from the table values in the same datasheet. Chart values were read by eye, to about ±0.3 A. Output frequency is taken as 50 Hz; the chart does not state it.

The datasheet has no transient thermal data. Two limits were computed: the current if the junction follows the loss at once (peak loss times the whole resistance, which is the top of the range the tool reports today), and the current if only the average is limited (`max_current(..., peak=False)`).

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

The vendor chart lay inside the bracket at all ten points; limiting the average alone would have allowed 42 to 55% more current than the chart. The bracket was wide, roughly 0.6 to 1.5 times the chart value.

#### What the code does today, on a part that is in the repository

The same three figures for the made-up 600 V, 30 A module of the examples with its transient curve taken away, at 300 V, modulation index 0.8, power factor 0.8, 6 kHz, 50 Hz out, against the current its own curve allows. They are the output of `engine.limits.max_current` and of `solve(...).tj_peak_range`, and can be rerun:

| Heatsink | Junction follows the loss at once (top of the range) | Assumed response (the estimate) | With its own transient curve | Average only |
|---|---|---|---|---|
| 60 °C | 13.7 A | 25.0 A | 25.3 A | 28.3 A |
| 80 °C | 11.4 A | 21.1 A | 21.3 A | 24.0 A |
| 100 °C | 8.8 A | 16.7 A | 16.8 A | 19.1 A |

The estimate is within 1.5% of what the part's own curve gives. The top of the range is far below both because it also carries the widest heating between chips and the worst mounting, not the response alone.

#### Diagnostic, not part of the model

As a test of the explanation, a single thermal time constant was tried in place of the missing transient data, with the earlier state of the tool:

| Time constant | Model against chart, across the ten points |
|---|---|
| 3 ms | 20 to 26% low |
| 5 ms | 8 to 13% low |
| 8 ms | 2 to 5% high |
| 12 ms | 12 to 16% high |
| 20 ms | 22 to 28% high |

One value near 7 to 8 ms brought all ten points within the chart-reading error. That is consistent with the chart limiting peak junction temperature, and plausible for a small chip. It does not prove the explanation is complete: heating between chips was not modelled then and trades off against the time constant. The value is not used anywhere in the tool, since it would be calibrating to the vendor's answer.

How the response the tool now assumes compares, for a module of this size: on a ceramic substrate the junction reaches 63% of its resistance in about 17 ms (0.20, 0.50 and 0.99 of it at 1, 10 and 100 ms); as a moulded leadframe module, which is what Module A is, in about 0.2 s. A single 7 to 8 ms is faster than either. The leadframe figure is therefore slow against this one piece of evidence, with the caveat above about what the single time constant was standing in for, and it is the top of the range that covers such a module. This is the weakest point of the thermal model and is listed in its limits.

Still unverified: the assumed curve shapes away from the 7.5 A test point, and any margin the vendor applied.

### Module C against its vendor's public simulator

A comparison made once. The simulator's output is not redistributed, so the table cannot be reproduced from the repository.

Six operating points at 300 V and modulation index 0.8, sinusoidal PWM. The model is built from the datasheet alone: its tables, and its on-state, diode, turn-on, recovery and transient thermal curves. Turn-off stays on the table, because the hot curve disagrees with it by 17%. Heating between chips is computed for a generic package with the construction left unknown. Nothing is fitted to the simulator. The simulator's temperatures start from the case, so the reference says that nothing lies between case and heatsink.

| Point | Total loss, ours against simulator | Hottest junction, ours against simulator | Ours, range | Inside |
|---|---|---|---|---|
| 50 Hz, 6 kHz, pf 0.8 | 24.1 against 22.8 W, +6% | 112.8 against 112.6 °C, +0.2 | 105 to 129 | yes |
| 50 Hz, 16 kHz, pf 0.8 | 35.7 against 31.7 W, +13% | 144.8 against 141.4 °C, +3.4 | 133 to 169 | yes |
| 50 Hz, 6 kHz, pf −0.8 | 24.9 against 23.8 W, +5% | 114.1 against 121.6 °C, −7.5 | 107 to 130 | yes |
| 50 Hz, 16 kHz, pf 0.3 | 35.8 against 32.0 W, +12% | 142.3 against 140.6 °C, +1.7 | 130 to 167 | yes |
| 5 Hz, 6 kHz, pf 0.8 | 24.1 against 22.8 W, +6% | 117.8 against 115.9 °C, +1.9 | 110 to 134 | yes |
| 200 Hz, 6 kHz, pf 0.8 | 24.1 against 22.7 W, +6% | 111.9 against 111.3 °C, +0.6 | 104 to 128 | yes |

Where the switch is the hottest chip the junction is 0.2 to 3.4 °C high, on a loss 6 to 13% high. Where the diode is, it is 7.5 °C low: the diode's junction is 8 to 11 °C low at every point, which a single coupling figure for switch and diode alike cannot mend (the simulator's own is half as large again for the diode). Heating between chips is reckoned over the package's own face, 0.36 K/W here against the simulator's 0.5.

Turn-on at 6 kHz is 0.55 W a switch against the simulator's 0.41 W, a third high. The curve used is the higher of the high-side and low-side curves, which explains some of it and not all. The range is wide because the construction is unknown and every package input is varied together.

Modules A and B could not be run in the same simulator. One part, one vendor, and the reference is a model, not a measurement. `motionsim validate` runs such a comparison from a file of reference points; the simulator's output is not redistributed here.

## Level D: published measurements, and what they do and do not show

Four reference designs that semiconductor makers publish with design guides, each with what was measured on it. None is named; the device models were read from the transistors' public datasheets and are not in the repository.

### A 48 V inverter, 30 MOSFETs on a heatsink: loss

A comparison made once. The measured figures below are from the published guide; the device model and the run that gave the model's column are not in the repository, since the model was read from a datasheet.

A measured inverter loss, from a reference design a semiconductor maker publishes with its design guide. A 48 V three-phase inverter with five 100 V MOSFETs in parallel at each switch (30 in all) on a heatsink, sinusoidal PWM into an induction motor on a dynamometer, loss measured with a power analyzer from DC input to motor terminals at 8 and at 10 kHz, from 27 to 131 A rms.

The model: the same transistor as read from its datasheet in another package (the same die), with its on-resistance scaled to the 2 mΩ the guide gives for the one on the board; five in parallel; 12 V gate drive; turn-on through the guide's shared 24 Ω and 8.2 Ω a device, turn-off through 8.2 Ω; modulation index and power factor worked out from the table's own voltage, current and power at each row. The guide does not give the heatsink temperature or the dead time, so the model was run across 30 to 60 °C and 100 to 500 ns; that moves the result by 4% either way.

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
- The part that changes with frequency can be separated, from the two rows measured at the same current. At 27 A the measured loss rises by 1.6 W for each kHz and the model's by 1.15 W; at 131 A, 3.7 W against 4.95 W. So the switching estimate from gate and output charge is about 30% low at low current and about a third high at high current on this board. The snubbers, which lose the same at any current, are part of the first.

What it does not show: anything about the junction temperature, about measured-energy parts, or about a board whose own resistance is known. One design, one part. The three boards below add temperature and a second loss measurement.

### Three boards without a heatsink: case temperature, and one stage's loss

Held by `tests/test_published_boards.py`, which runs where the two device models are present in `runs/validation/` and skips where they are not, as in CI: it holds the model's figure at every measured point to 0.5% and the ratios drawn from them below. The measured figures are in the test as the guides give them. Nothing is fitted to the measurements: every figure the model is given is the datasheet's or the guide's, and where a guide leaves one open the choice is said.

The three boards stand in still air with no heatsink, so what the guides measure is the whole chain the tool works out for such a stage: the loss, and the path from the transistor to the air through the board. The tool takes that path from the datasheet's junction-to-air figure and the board's area (the board cooling of Level A). The guides measure the hottest transistor's case, by infrared camera; on the GaN boards the case top is 0.2 K/W from the junction, under 0.6 K at these losses, and the model's case temperature is what is set beside it.

**Board A: six 100 V GaN transistors, one a switch.** A 130 by 100 mm board, 48 V, sinusoidal, 50 ns dead time, a motor on a bench at 5 Hz, 25 °C air. The guide's chart of the hottest case's rise against phase current at 50 and 100 kHz, read from its pixels (±0.2 A, ±0.7 K). The model: the transistor as read from its datasheet; its gate resistors chosen by the tool for the 5 V/ns it allows a motor on a cable (the guide measures edges under 10 V/ns); each package on a square inch of copper, the area the datasheet's junction-to-air figure is taken on. The datasheet gives two such figures: 45 K/W on the standard test board, which is the one the tool asks for, and 21 K/W on its maker's own evaluation board. Both are shown. The guides do not give modulation index or power factor; this transistor's conduction does not depend on them, and moving them from 0.2 and 0.5 to 0.9 and 1 moves the rise by under 0.1 K.

| Switching | Phase current | Measured rise | Model, 45 K/W | Over measured | Model, 21 K/W | Over measured |
|---|---|---|---|---|---|---|
| 50 kHz | 5.1 A | 8.6 K | 16.2 K | 1.89 | 10.1 K | 1.18 |
| 50 kHz | 10.2 A | 14.6 K | 29.0 K | 1.99 | 17.9 K | 1.23 |
| 50 kHz | 15.7 A | 26.7 K | 50.8 K | 1.90 | 30.8 K | 1.15 |
| 50 kHz | 19.6 A | 38.5 K | 75.1 K | 1.95 | 44.4 K | 1.15 |
| 50 kHz | 24.9 A | 58.9 K | 121.6 K | 2.06 | 67.6 K | 1.15 |
| 100 kHz | 5.0 A | 16.7 K | 31.0 K | 1.86 | 19.4 K | 1.16 |
| 100 kHz | 10.2 A | 25.7 K | 53.3 K | 2.08 | 32.9 K | 1.28 |
| 100 kHz | 14.3 A | 38.0 K | 78.6 K | 2.07 | 47.7 K | 1.26 |
| 100 kHz | 19.5 A | 58.4 K | 131.8 K | 2.26 | 77.1 K | 1.32 |
| 100 kHz | 22.9 A | 74.9 K | 178.8 K | 2.39 | 101.4 K | 1.35 |

**Board B: 24 of the same transistor, four in parallel a switch.** A 135 by 100 mm board, the same conditions, a larger motor, 25.5 °C air, at 20, 50 and 100 kHz. Each package's copper is its share of the board, 5.6 cm².

| Switching | Phase current | Measured rise | Model, 45 K/W | Over measured | Model, 21 K/W | Over measured |
|---|---|---|---|---|---|---|
| 20 kHz | 25.8 A | 18.4 K | 18.5 K | 1.01 | 14.9 K | 0.81 |
| 20 kHz | 41.1 A | 31.2 K | 31.2 K | 1.00 | 24.9 K | 0.80 |
| 20 kHz | 56.4 A | 54.2 K | 50.8 K | 0.94 | 40.0 K | 0.74 |
| 50 kHz | 36.0 A | 35.6 K | 54.5 K | 1.53 | 43.7 K | 1.23 |
| 50 kHz | 51.1 A | 60.3 K | 82.1 K | 1.36 | 64.7 K | 1.07 |
| 100 kHz | 15.4 A | 25.3 K | 54.8 K | 2.16 | 44.3 K | 1.75 |
| 100 kHz | 30.6 A | 44.3 K | 88.1 K | 1.99 | 70.8 K | 1.60 |
| 100 kHz | 46.1 A | 74.5 K | 130.8 K | 1.76 | 103.6 K | 1.39 |

**The switching part, with the board's path taken out.** At one current the path from a transistor to the air is the same at every switching frequency, so the ratio of two rises at that current says how much of the loss comes with switching, whatever the path is. The model's ratio barely moves with the junction-to-air figure (under 3%).

| Board, current | Rise at the higher frequency over the lower | Measured | Model |
|---|---|---|---|
| A, 5 A | 100 over 50 kHz | 1.95 | 1.93 |
| A, 10.2 A | 100 over 50 kHz | 1.76 | 1.84 |
| A, 19.5 A | 100 over 50 kHz | 1.53 | 1.77 |
| B, 41.1 A | 50 over 20 kHz | 1.41 | 2.01 |
| B, 41.1 A | 100 over 20 kHz | 2.08 | 3.71 |

**Board C: six 100 V silicon MOSFETs, six-step.** The same maker's companion to the 48 V design above: the same transistor in a D2PAK, one a switch, on a 70 by 69 mm four-layer board with no heatsink, 54 V, block commutation. At 95% duty the high side chops at 20 kHz and the low side freewheels actively; at 100% nothing chops. Dead time 100 ns. The guide tabulates the whole stage's loss (DC input less output power) at six currents for each, and charts the hottest MOSFET's temperature, read here from the chart's own drawn path. The air's temperature is not stated; its thermal images read 24 to 26 °C, taken as 25 °C. The model: the read transistor scaled to the 2 mΩ the guide gives, as above; the datasheet's 62 K/W junction to air; a brushless motor of no winding resistance at 50 Hz, wound so that the duty is its back-EMF; 100% duty taken as 99% (the most the stage passes) at 200 Hz, whose switching is a hundredth of 20 kHz's.

First the loss alone, with every case held at the temperature the guide measured at that current (beyond the chart's last point, its last temperature):

| Winding current | Measured, 100% | Model | Measured, 95% | Model |
|---|---|---|---|---|
| 7.3 and 8.1 A | 2.57 W | 0.34 W | 3.60 W | 0.96 W |
| 11.4 and 11.6 A | 3.42 W | 0.85 W | 4.48 W | 1.64 W |
| 15.5 and 15.9 A | 4.91 W | 1.66 W | 7.35 W | 2.89 W |
| 20.5 and 21.4 A | 6.81 W | 3.16 W | 10.87 W | 5.37 W |
| 25.5 and 25.7 A | 9.42 W | 5.52 W | 14.48 W | 8.16 W |
| 27.7 and 27.6 A | 10.73 W | 6.96 W | 16.74 W | 9.33 W |

Then the whole chain on the board's own path, against the chart:

| Winding current | Measured rise, 100% | Model | Over measured |
|---|---|---|---|
| 5.5 A | 6.8 K | 3.6 K | 0.53 |
| 8.6 A | 8.8 K | 8.8 K | 1.00 |
| 12.5 A | 16.7 K | 20.1 K | 1.20 |
| 16.9 A | 26.8 K | 40.9 K | 1.53 |
| 21.1 A | 42.1 K | 77.5 K | 1.84 |
| 24.0 A | 54.2 K | 126.8 K | 2.34 |
| 27.0 A | 69.1 K | 263.3 K | 3.81 |
| 29.5 A | 86.1 K | no steady temperature | |

At 95% duty the model is 1.2 times the measured rise at 8 A, 1.9 times at 18 A and 4 times at 26 A.

What they show:

- **The path to the air is the larger error, and it is on the hot side.** With the standard test board's junction-to-air figure, the one the tool asks for, the model is about twice the measured rise on board A at every current and both frequencies, and on board C from 1.2 times at 12 A to 3.8 times at 27 A, where the loss and the temperature feed each other until there is no steady state at 29.5 A, a current the board carried at 111 °C. These boards have copper planes in several layers spreading the heat; the board model leaves out layers and vias (said in its limits) and takes the datasheet's figure, from a board made to a standard, as each package's own path. With the figure the datasheet gives on its maker's own evaluation board, board A comes to 1.15 to 1.35 times. No tool figure is fitted to this; the datasheet's second figure is a choice a user can make by typing it.
- **At the lowest frequency the chain can land close.** Board B at 20 kHz is within 6% with the standard figure; board C at 8.6 A agrees. That is agreement of a sum, not of each part: the 21 K/W figure, nearer on board A, is 19 to 26% low on board B at 20 kHz.
- **The switching estimate from charge grows faster with frequency than the boards do.** With the path taken out, board A agrees at 5 A, and at 19.5 A the rise at 100 kHz is 1.77 times the 50 kHz rise in the model against 1.53 measured; on board B the rise at 100 kHz is 3.71 times the 20 kHz rise in the model against 2.08 measured. Two things can make that, and the measurement cannot tell them apart: the estimate is high (the output charge of each of the four devices in parallel is taken through the full voltage at every hard turn-on; with the gate resistors at their least and a 1 nH loop the ratio still comes to 2.9), or loss outside the transistors that does not change with frequency, in the copper and shunts carrying 41 A, adds to the measured rise at every frequency alike and lowers the measured ratio. The second is what the first 48 V board above showed.
- **Board C's loss, the path set aside, is low: a fixed 2 W the model does not draw, and half of what PWM adds.** Without PWM the measured loss is 2.0 W fixed plus a part in the square of the current; the fixed part is the gate driver, the supplies and the controller, which the guide puts at about 0.6 W for the driver alone and which nothing in the model draws. Of the part in the square of the current the model has 81%; the guide's 0.5 mΩ shunt in the link accounts for a third of the rest, and the board's copper can account for the remainder. What 20 kHz PWM adds, 95% against 100% duty at the same current, is 3.6 and 4.9 W measured at 21 and 26 A and half of that in the model: the switching estimate from charge, low here as it was at low current on the first board, with the snubbers' 0.2 W and the diode's conduction at each commutation, which the model leaves out, on the measured side.

What they do not show: a junction temperature measured under the case, a part with measured switching energy, or a board whose own resistance or thermal path is known. Two parts, two makers' boards, all in still air. The guides' charts are read, not tabulated, and the readings are said with each.

`motionsim validate` takes a file of measurements, for anyone with their own. A point can give each loss term on its own, how the stage was mounted, and a load that comes and goes with the junction's lowest and highest temperature once it repeats.

## What a figure can claim, loss by loss

There is no one accuracy figure for this tool, and none is given. What a result can claim depends on which loss it is and what it was worked out from. The published comparisons this rests on are listed, with their own conditions, in [CONTROL_RESEARCH.md](CONTROL_RESEARCH.md) section 4; they are other people's models on other people's hardware, and say what a datasheet-based method can reach, not what this tool has reached. This tool's own measured points are Level D above: four boards, two of them measured for loss and three for temperature.

| Loss component | From the datasheet alone | What one measurement or a board file buys |
|---|---|---|
| Conduction, at a known current and junction temperature | The strongest footing: the curve is printed. What is left is the reading of typical values and the temperature. The spread between parts up to the datasheet's maximum is larger than the model's error and is shown apart from it | A measured on-resistance or forward drop of the actual part removes the spread |
| Switching, from printed energy curves, at the datasheet's own gate resistor | Weaker, and the split between turn-on and turn-off is weaker than their sum: the datasheet's test fixture, its loop inductance and its opposite switch are not the application's. Published comparisons of datasheet-based models with double-pulse measurements find the sum closer than either part, the two errors partly cancelling | One double-pulse measurement on the real layout, given to `motionsim measure`, replaces the datasheet's energy. It is the measurement most worth making |
| Switching, estimated from charges or from rise and fall times | The weakest. At Level D this estimate was about 30% low at low current and about a third high at high current on the first board, about half of what PWM added on the six-step board, and grew faster with frequency than two GaN boards did | The same double-pulse measurement |
| Dead-time conduction | To first order from printed data, where the datasheet gives the reverse path's curve; a usual figure by technology where it does not. Counted for the whole dead time | The dead time the firmware really uses, which you know |
| Board copper, connectors, shunts, capacitor loss, snubbers | Not in a device datasheet, and not in the model. At Level D the part of the measured loss that does not change with frequency was about three times the transistors' own conduction loss at the highest current | The board file gives the loop's copper resistance for a steady current, and the inductances that set the event's overshoot and ringing. It does not add the board's loss to the stage's. One resistance measurement a phase would |
| The split of switching loss with layout | The loop inductance is assumed by the package's kind unless given. It moves turn-on and turn-off energy in opposite directions; the loss model's energy stays the datasheet's | The board file replaces the assumed inductances in the switching event with ones worked out from the copper, each with a band. The loss model's energy is still the datasheet's or yours |
| Junction temperature rise | The loss's error carries through in proportion, and the thermal path adds its own: junction to case is printed, what lies beyond is yours, and heating between chips is a range. With no heatsink, a datasheet's junction-to-air figure from a standard test board put two published GaN boards up to 2.4 times their measured rise, and a silicon one up to 3.8 times and then into no steady state, while one board at 20 kHz came within 6% | One temperature reading at a known load fixes the path from case to air |

For the control lab the same holds, with one thing added. Two schemes compared on the same device, board and motor share what the model gets wrong, so the difference between them is on firmer ground than either one's watts. The exception is a scheme that moves the current at the switching instant (a clamp placed on the current's peak, a predictive cost that charges commutations by their energy): its gain rests on the shape of the switching-energy curve against current, where the split between turn-on and turn-off matters.

## The control lab

Held by tests in CI (`tests/test_control_*.py`). Every expected value is a closed form, the tool's own settled engine, or linear theory worked apart from the run; none is a figure the lab gave before. None is a measurement.

Against the settled engine, on the six made-up parts, each at its own starting design, held under torque control (`tests/test_control_engine.py`):

- The mean d- and q-axis currents of the run are the engine's settled currents within 0.5% of the current's size, with the stage averaged and switched.
- The switched run's total loss is the engine's within 1%, its conduction and its switching loss each within 1.5%, and the junction's peak rise over the heatsink within 1%. The six switches' own losses add up to the total, and the mean switching frequency is the design's within 0.1%.
- On the part whose design switches 24 times in a turn of its output, sampling once a carrier period reads the current high and leaves the loss within 1.3% of the engine's; sampling twice closes it to 0.6%.
- The switched run's current ripple, peak to peak, is the engine's analytic ripple within 5%, at five points on three parts. The averaged stage shows under 1% of it.
- The power into the motor is the shaft power and the copper loss, ripple included, within 0.5%.

The motor alone, against its equations by hand (`tests/test_control_plant.py`): a voltage step on a still rotor rises with L/R to 1 part in a million on the d axis; the back-EMF is the speed times the flux; the torque is the magnet's and the reluctance torque; the energy put in is the heat, the field, the motion and the load within 0.5%.

Against linear theory (`tests/test_control_loops.py`):

- A current step rises in the time the analysis predicts within 10%, with the overshoot within 1 point of the step, at standstill and at 2000 rpm, averaged and switched.
- The closed current loop's gain, measured in time with a sine, falls to −3 dB at the frequency the analysis gives within 10%.
- The phase margin is the one a calculation by hand gives within 0.1°, and the crossover within 0.2%; the tuning rule's gains are the rule worked by hand.
- A speed step rises and settles as predicted within 10%, with the overshoot within 2 points, for the cascade sampled once and twice a period.
- Each design starts on the scheme its kind calls for; a scheme goes to plain data and back unchanged; a parameter out of its bounds is refused by its place in the scheme.

The blocks, each against what can be worked out by hand (`tests/test_control_blocks.py`, `tests/test_control_predictive.py`, `tests/test_control_schemes.py`):

- An observer started knowing nothing finds the angle, and with its phase compensation off lags by its filter's phase.
- A discontinuous modulation switches the share of the current the published analysis gives, 1 − ½·cos φ for a clamp on the voltage's peak and a half with the clamp on the current's, to 2 parts in 1000.
- Deadbeat control is on its reference two samples after it is asked; with a wrong inductance its error shrinks by the textbook's factor, 1 − L̂/L, within 0.06; past twice the inductance it diverges.
- The pair of least loss never loses more than the pair of least current, and makes the same torque.
- The variable switching frequency holds the ripple to its limit within 3% with a mean frequency under 85% of the fixed one and under 90% of its switching loss, at the same torque within 0.5%.
- At a stall, the thermal supervisor holds the junction under a limit the plain scheme passes by more than 3 K, and pays for it in torque; with the limit out of reach it changes nothing.
- The predictive controller tracks its currents within 1% with no modulator; a heavier weight switches less and ripples more; at the same mean switching frequency it switches a smaller current than the modulated drive.
- Every scheme offered holds the design point of unlike designs, and says where each figure it sets comes from.

The explorations (`tests/test_control_explore.py`): each of the 23 is run on two unlike made-up designs, inside 60 s, and its headline moves the way the physics says, with the reason written beside the assertion.

The service (`tests/test_control_run.py`): gains past the gain margin are run with a caution and a current that runs away is refused; a run of too many sampling instants is refused before it starts; a run with noise is the same run for the same seed; a second of switched simulation at 20 kHz takes under 8 s.

The pulsed rating, the observer's floor, the hand-back and a window of the motion (`tests/test_control_held_more.py`):

- After a torque step, the overshoot the pulsed rating is held to is the run's torque overshoot, read apart by the step-response metric, within half a point, and the current held is the run's own peak per switch within 2%. A rating between the two is cautioned in the run's words; a hold, with no step, is cautioned with the 15% allowance, said as one; the five steps' check says the same.
- With an ideal stage the back-EMF observer's floor is its lock floor, 300/p rpm. With the dead time on it is four times t_dead·f_sw·V_dc over ψ, to 1 part in 1000; with noise on the samples it is that noise through √(R² + (g·L)²), worked by hand.
- A motion that reverses through the floor is found to reverse, with its share of time under the floor counted by hand, and the verdict offers the hand-back.
- With the hand-back set, a held design point is the run without it to the last figure, and its loss and junction rise are the settled engine's within 1%. A reversal from half the design speed to half the other way, which loses the rotor on the sliding-mode observer alone, ends within 1% of the speed asked for, with the angle within 10° of the rotor's wherever the scheme is on the observer.
- A window of peak torque is centred on the motion's spike; under torque control the mean torque made over it is the mean of the motion's triangle by hand within 1%. A window of fastest change is centred on the steepest stretch; a speed scheme holds the motion's speed within 2% through the load's step.

What this does not show: that the lab matches a real drive. No measured current, loss or temperature has been set beside a run: no public record of a permanent-magnet drive's measured phase currents, with the motor's figures and the drive's settings and a licence to use them, has been found.

## The board reader

Held by tests in CI (`tests/test_board_*.py`). The expected values are published closed forms, worked out in the test or by hand beside it.

| What | Held to |
|---|---|
| A rectangular bar's own inductance | 1% on a 10 mm bar, 0.5% on a 100 mm bar |
| A square thin tape's own, the exact form | 1 part in 10 000 |
| A round wire's own | 0.5% |
| Two parallel filaments' mutual | 2 parts in 100 000 |
| A 60 by 40 mm rectangular loop of track, meshed and solved, against the rectangle-of-bar formula | 5%, by the steady and by the least-energy current |
| That loop's resistance against its copper's | 5% |
| A pair of planes against µ0·h·l/w | 10%; in proportion to the height within 10% |
| A track and its return side by side against the two-bar formula | 5% |
| A return on the next layer under the track | under 0.4 of the loop with the return beside it, and the least-energy figure under the steady one |
| The same made-up board as KiCad and as IPC-2581 | the six figures within 1% |
| The three legs of a made-up three-phase board | their loops within 5% of each other |

Besides: the half bridge, its capacitors and each switch's gate drive are found on the made-up boards, with what the user names taken over the guess; a board with no bridge is refused with what was looked for; a file cut short anywhere, malformed or built to exhaust the reader is refused in a line; a layout from a board moves the switching event's turn-off overshoot the way its loop inductance says.

What this does not show: that a figure from a real board is right. No board has been compared with a field solver or a measurement, and only made-up boards have been read.

## Datasheets the reader has been tried on

No vendor's device data ships with this project, only made-up parts, and it favours no vendor. You bring the datasheets. This table says what the reader has been run on so far, so you can judge how far to trust it on yours.

| Kind of device | Datasheet tried | What was read | Outcome |
|---|---|---|---|
| IGBT module with built-in driver | three 600 V, 15 A modules from one vendor | 15 to 16 table values each; on one, on-state, diode, switching-energy, recovery and thermal curves | All table values match the page. Two have no curves at all. On the third, 10 of 11 curves agree with its tables within 8%; its hot turn-off curve disagrees with its table by 17%, so the table is used there. That one was compared with its vendor's simulator. |
| Discrete IGBT with diode | a 650 V, 40 A part | 26 table values, on-state, diode, switching-energy and thermal curves | Curves agree with the datasheet's own tables within 4%. |
| GaN transistor | a 100 V part | 12 table values, on-resistance against temperature, thermal curve | All match. Switching loss is estimated from charge. |
| Silicon MOSFET | four parts from 40 V to 100 V, from four makers | 14 to 17 table values each; on-resistance against temperature, body-diode, gate-charge, capacitance and thermal curves | Table values match the page. 19 of 25 curves accepted, within 11% of the tables and most within 3%. The first of the four gives maximums only, so its model is on the high side. Switching loss is estimated from charge. |
| SiC MOSFET, discrete | two 1200 V parts from two makers | 17 and 20 table values; thermal, capacitance, gate-charge and switching-energy curves | Table values match. 7 of 14 curves accepted. On the first, the switching-energy and body-diode figures are laid out in ways the reader does not handle (several figures a quantity, curves by gate voltage). |
| SiC MOSFET module | a 1200 V H-bridge | 19 table values; five curves, from figures stored as images | Curves agree with the tables within 4%. Switching and recovery energy are tabulated at one current only, so their shape away from it is assumed. |
| GaN transistor, cascode | a 650 V part | 18 table values; thermal, on-resistance, capacitance and reverse-conduction curves | Read, but no model is built: the datasheet gives no gate plateau, threshold charge or transconductance to estimate switching from, and no switching energy. The tool says so and stops. |
| Discrete IGBT with diode, second maker | a 650 V, 40 A part | 25 table values; on-state, diode, switching-energy, energy-against-gate-resistance and thermal curves | 10 of 13 curves accepted, within 1.1% of the tables. The diode thermal-impedance figure is too cluttered to confirm, so the table value is used. |
| Superjunction MOSFET | a 600 V part | 14 table values; gate-charge, capacitance, on-resistance, body-diode and thermal curves | Builds. The gate plateau is read from a figure that also draws the drain voltage. Switching loss is estimated from charge. |
| IGBT module with built-in driver, second maker | a 600 V, 15 A module | 7 to 8 table values; six switching-energy curves from two plots under one caption | Builds. The datasheet tabulates no switching energy, so the curves are identified by their colour in the legend and say so. |
| Discrete IGBT, scanned datasheet | an older 600 V part whose datasheet is page images | 19 table values, read from page images | Builds from table values. Its figures are not read. Diode recovery energy is estimated from the tabulated recovery charge. |
| Rectifier (diode) bridge | not supported | | |

Each row is one run checked by hand. The reader uses a language model and its output can differ between runs. The readings and the datasheets are not in the repository, so the table records what was seen once and nothing holds it.

## Reader accuracy eval

The reader is scored offline on thirteen made-up datasheets whose right answers are known, since each is drawn by code from a part made of closed-form curves: an IGBT with its diode, silicon, silicon carbide and gallium nitride transistors, and a six-pack module, written the ways real sheets differ (typical and maximum columns, units, footnoted conditions, logarithmic axes, a page that is only a picture, a table that runs on, a line that tries to give the reader orders). For each sheet there is one faithful recorded reading and twelve to sixteen readings with one named mistake each: 190 recordings in all. Each faithful reading is played again through the chat-completions path, a service on the same machine standing in for the model. Replaying them asks no model and needs no key; `evals/README.md` says how they are built and what they do not prove.

The replay on this version (`python -m evals.reader.run`; the tests marked `reader_eval` hold it to the bars in CI):

| Score | What it is | Bar | Replay |
|---|---|---|---|
| `values_read` | table values read exactly and left unflagged, faithful recordings | 1 | 1 |
| `right_left_alone` | right values not flagged, all recordings | 1 | 1 |
| `wrong_flagged` | wrong values flagged, all recordings | at least 0.95 | 1 |
| `frames_found` | drawn plot areas found within 1 pt | 1 | 1 |
| `curves_read` | drawn curves digitised and unflagged | at least 0.95 | 1 |
| `curve_worst` | largest relative error of a digitised curve | at most 0.03 | 0.0104 |
| `curve_rms` | largest root-mean-square relative error of a curve | at most 0.01 | 0.0015 |
| `silently_wrong_curves` | curves more than 10% off and not flagged | 0 | 0 |
| `loss_error` | inverter loss from the reading against loss from the part | at most 0.02 | 0.0001 |
| `rise_error` | junction rise above the heatsink, likewise | at most 0.02 | 0.00008 |

3,101 right values and 163 wrong ones were reported, and a device was built from each of the thirteen sheets. This shows that, given these answers, right and wrong, the checks behave. It says nothing of how often a real model reads a value wrong: that is the live mode, which costs money, is run by no test, and has not been run.

## The page and the tests

The page is toured at four widths, from 1440 px down to 320 px, through every step and tab. It is also walked at random: a seeded sequence of whatever can be pressed, on a desk-width and a phone-width screen, with every placement check run after each press and nothing allowed to stay waiting. Six walks of twenty-five presses, about 150 surfaces a run. The tour (`web/scripts/measure.mjs`) and the full walk (`web/scripts/walk.mjs`) are run by hand against the local page; CI runs two walks of fifteen presses against the local page and the hosted one. One fixed journey through the hosted page runs in CI at two widths (`web/scripts/journey.mjs`): a first visit, a made-up part, every step to a verdict, a setting changed, a reload.

The cooling, dead-time and typed-part code is held by tests whose expected values are worked out apart from the code: closed forms, literals from the published figures, and one path through the engine checked against another. Among them (`tests/test_entry.py`, `tests/test_values.py`):

- A point held as a motion ends within 1 K of the steady solution, for seven combinations of motor and cooling: at standstill, on an H-bridge, on a shared board, on a heatsink in air, with devices in parallel. The two are worked out by different code.
- A motion that cannot settle in air says so.
- The junction-to-air figure the heatsink advice gives for doing without a heatsink, fed back as the cooling, puts the hottest junction on the limit, running and held still, for a permanent-magnet, a six-step and a brushed motor; a figure a fifth larger passes it.
- The dead time chosen is never under the rule's own least. Its loss is the body diode's voltage times the current it carries for both edges of each period, within 1%.
- A typed figure outside what a power transistor can have is refused with its unit; the page and the command line give the same loss for the same part with the dead time left open.
- Whether a motor fits a part, before any design point: the current it draws at its limit against the part's rating, and the speed it reaches against the speed asked.

A whole design run from one file (`motionsim design run`) gives the figures the page's own steps give, asked one by one (`tests/test_design.py`).

The figures the product exists for are held to a relative difference of 1e-9 (`tests/test_golden.py`): one operating point, three devices compared on one motor, the same comparison across switching frequency, a load's motion on two kinds of motor, what a device can drive, what to build around it, and a whole design with two devices. It says nothing about whether a figure is right, only that code moved or renamed has left it where it was. The same recorded figures are the reference on every Python version CI runs, 3.11 to 3.13, so the versions agree with each other to that tolerance.

What must hold at any operating point is tried at points drawn at random (`tests/test_properties.py`): no loss is negative, more current or a faster switch never loses less, a hotter heatsink never leaves a cooler junction, two devices in parallel carrying twice the current lose twice what one does, and a comparison does not depend on the order its parts are named in.

The engine is run as the hosted page loads it, with the datasheet reader's libraries absent, through every route the page calls (`tests/test_hosted.py`).

The page in its hosted form scored 100 for accessibility, best practices and search in Lighthouse at desk and phone widths, with no layout shift as it loads. That is a measurement made by hand, not a check in CI. The tour fails on a control with no name, a request that fails while the page loads, a layout shift at load, a sentence squeezed beside something else, a refusal shown away from its figure, a chart without named axes and units, or drawing text under 9.5 px. It runs at four widths, from 1440 px down to 320 px, and checks that each step opens at its heading.

What the page shows is held to what it would show afresh. A walk presses controls in an order nobody planned (tabs, steps, the device on the drawing, what is compared, values of a setting added and taken out), on two parts that differ so that one cannot pass for the other, and every fifth press it reloads the page from what it saved and compares every figure on show: a figure left over from before the last change, or one that belongs to another device, fails it. A second script (`web/scripts/race.mjs`) chooses another device at two delays after one of the slow tabs is opened, in the local page and in the hosted one, and holds the page to the same test. The same script asks for the largest load, cancels it after two probes, and holds the page to the probes it drew, the button and the focus given back at once, the stop said, and the engine free: in the browser, the engine says it stopped and posts at most the probe it was on; then the search asked again runs to its answer. CI runs the race and two short walks on both; the long walk is run by hand.

The engine the hosted page runs inside the browser is the same Python as the installed one, and is held to it: 44 figures (every kind of motor at its starting point, a motion, a map) agree to a relative 1e-9, checked in CI on every change (`web/scripts/engine-check.mjs`).

## What these figures were produced with

The engine's figures in this document were last produced with Python 3.12.3, NumPy 2.5.3, SciPy 1.18.1 and Pydantic 2.13.5. The tests run in CI on Python 3.11, 3.12 and 3.13, and once more on the oldest release of each library the package allows (NumPy 1.26.0, SciPy 1.11.1, Pydantic 2.6.0, PyYAML 6.0). The package itself asks only for lower bounds; the product's figures are held to a relative 1e-9 by `tests/test_golden.py`, so a version of a library that moves one fails there before it reaches a result.

Reading a datasheet is different: it uses a language model, and two readings can differ. The model is named in `src/motionsim/observe/reader.py`; what was read is saved beside each device model, value by value with its page, and it is that saved reading, not a fresh one, that a result rests on.
