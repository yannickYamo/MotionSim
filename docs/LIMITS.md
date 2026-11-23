# Limits

What MotionSim does not do, or does only roughly, in order of how much it matters. Read this before trusting a result.

## 1. One measured loss behind it, and it does not settle much

The loss and temperature model is checked against closed-form solutions and an independent numerical integration, and against one vendor's simulator on one part. It has been compared with one loss measured on hardware, a published 48 V reference design: 10 to 31% below a measurement that includes the board's own resistance, with the switching estimate from charge 30% low at low current and 30% high at high current. No junction temperature has been compared with a measured one. Treat every result as an estimate to be confirmed on the bench.

## 2. Junction temperature inside a module is a range

A datasheet gives each chip's thermal resistance with that chip heated alone. How much the chips heat each other, and the transient response when no curve is given, are computed for a generic package of the stated construction. The result is shown as a range, often 30 °C wide, because the real layout is not known.

## 3. The datasheet reader misses things

- It uses a language model, and its output can differ between runs. Anthropic's is the one every figure in these documents was read with. OpenAI's, Gemini's, Grok's and a model you host can be set in its place and have not been run on real datasheets here: expect more values set aside with a weaker model, and check what was read. Every value is checked against the page it was cited from; what fails is set aside and shown, never silently used.
- Quantities spread over several figures, and curves drawn against gate voltage, are not read.
- Scanned datasheets are read from page images: their tables only, not their figures, and the check on them is weaker.
- Figures stored as pictures are read where they have a grid to find them by, drawn dark or in grey. A picture with no grid is not read.
- Switching loss estimated from charge takes the gate current at turn-off as the plateau voltage over the gate resistance throughout. Through the plateau that is what it is. Below it, while the current falls, the gate falls as a capacitor does and its current with it, and how the drain current follows the gate is not printed: a current that follows it in a straight line loses 7 to 30% more there than the figure taken, and one that follows its square 20 to 30% less, for a threshold at 0.4 to 0.8 of the plateau. The figure taken lies between them, and the share of the turn-off energy this part holds is what can be off.
- Where a datasheet gives no switching energy and no gate charges, switching loss is estimated from its rise and fall times and output charge: two printed times from a clean test, taken not to move with current. It is the weakest of the three footings and is named in every result that uses it.
- A datasheet that gives too little to model a device is refused with what is missing.

## 4. The control is its settled result, not a loop

A modern drive runs field-oriented control: a current loop, a speed or position loop, and an estimate of where the rotor is. MotionSim does not simulate those loops. It works out the currents they settle to, at every instant of the motion, and gives those to the loss and temperature engine. For a permanent-magnet motor that is the d- and q-axis current making the torque with least current, and field weakening where the voltage runs out. [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) says why.

What that covers, and how:

| What a drive does | How it is represented |
|---|---|
| Steady running at a speed and torque | The currents and voltages field-oriented control settles to, exactly |
| A motion, second by second | Each instant solved as settled; junction temperature followed through time |
| Standstill and stall | The same torque at zero speed, with the rotor where the hottest chip is loaded most |
| A sensored start | Only the current the torque needs, from the first instant |
| A sensorless start | Open loop: alignment at a held current, a ramp at that current, then handover. With signal injection: only the current the torque needs. The current is set; the loop is not simulated |
| Braking | The energy returned to the DC link and the voltage it reaches, as a worst case |
| Ripple at the switching frequency | Worked out from the switching sequence and the motor's inductance |

What it leaves out, and what each could cost you:

- **The current loop's transient.** A step in torque makes the current pass its reference for about a millisecond. That is too short to move a junction temperature much, but a pulsed current rating has no moment to give. Where the motor's current limit is given, the check on that rating is made at the limit, which is where a drive's current sits in a hard acceleration or a stall. Where none is given, it is made at the settled current with 15% allowed for overshoot, and the switching ripple on top of that where it is known: a common figure and not your drive's, and a loop tuned for speed overshoots more. How far a loop really overshoots has not been worked out here.
- **Whether the control holds.** That the rotor follows an open-loop ramp under the load, that an observer keeps the rotor, that the loops are stable: all taken as given. A start against full load can fail in ways this tool will not show.
- **Low speed without a sensor.** The tool gives the speed below which the back-EMF cannot be read through the voltage this device and dead time get wrong. It is a closed-form figure for firmware that corrects for neither, with the back-EMF taken as readable at four times the error. Firmware that corrects for dead time reads lower; an observer in a noisy drive may need more, and a winding hotter than the drive was set for adds an error that is not counted. It is an estimate with nothing independent behind it yet. Permanent-magnet motors under sinusoidal control only.
- **What the drive does to protect itself.** A real drive brakes more slowly to hold the link voltage and cuts its current when hot. The tool reports what happens without either, which is the harder case.
- **Torque ripple.** From the back-EMF's harmonics, cogging and dead time. Not modelled, so neither is its heating.
- **The d-axis current that loses least.** Advised at the design point where the motor's iron loss is given, with iron loss taken to follow the square of the flux. The results themselves stay on least current, which is what a drive runs unless it is told otherwise.

Where the loop's own behaviour decides the answer (a fault, a hard reversal, an aggressive tuning), bring its currents and duty cycles from a control simulation or a drive's log: `motionsim trajectory` takes them as they are.

## 5. Simplifications in the model

- Iron loss and saturation are modelled only if you give them: a no-load loss at a speed, split evenly between its two kinds and taken at full flux; and one saturation current for both axes. Without them the result says they are left out.
- Current ripple at the switching frequency is worked out where the motor's inductance is known. It adds to conduction loss and moves the current at the switching instants, and half of it, peak to peak, is added to the peak current held against the continuous and pulsed ratings. That takes the largest ripple of the output period to ride on the fundamental's peak, the worst case; a point told outright, with no motor, has no ripple and is checked on its fundamental alone. The distortion dead time adds to the current at low speed is not modelled.
- Motor inverters only: no DC-DC, power-factor correction, three-level or soft-switching stages.
- Within an output period each chip's loss is read at its own temperature at each instant. Through a motion or a trajectory it is read at the temperature the instant would settle at (see below).
- Losses are worked out from the datasheet's typical values. A part at the maximum of its spread loses more: the result says by how much its on-state voltage can differ where the datasheet prints a maximum, and there is no worst-case run. A junction-to-case resistance is taken at its maximum where one is printed.
- A transistor's on-resistance given at 25 °C alone, typed in, read from a datasheet or written in a device file as one curve, is taken to rise as its technology usually does (as the power 1.9 of the absolute temperature for silicon to 250 V, 2.4 above, 1.0 for silicon carbide, 2.2 for GaN). It is said to be assumed and the conduction loss is held in doubt by the spread between parts of its kind, about a tenth at 100 °C. The datasheet's hot figure removes it.
- A recovery charge is tabulated at one current and 25 °C. Above that current it is taken to grow as the square root of the current, and for a silicon transistor by 0.7% a kelvin; a real part may grow faster with current. The datasheet's own hot figure is not read.
- A measured turn-on energy is taken, at no current, as the output charge times the test voltage where the charge is known; an IGBT's goes to nothing.
- Measured switching energy follows the supply voltage along the datasheet's own figure where it has one. Without one it is scaled in proportion to voltage, which above the test voltage is the least a real device does; the result says how much more it could be. It follows your gate resistor only where the datasheet has a figure for that. Either figure, measured at one current, is applied at every current.
- Gate resistors chosen by the tool are totals. Where the datasheet gives the transistor's own gate resistance the choice is never below it; where it does not, a very small chosen value may not be reachable.
- Devices in parallel share as unevenly as the datasheet's maximum over typical allows, with the typical part among maximum ones carrying the most. That ignores how a hot transistor's rising resistance pushes current back to the others, so it is on the cautious side. Where the datasheet gives no maximum, sharing is taken as equal.
- The usable voltage loses dead time, the shortest pulse you give, and the devices' drop at the peak current, taken at the heatsink temperature. A stage left with less than half its voltage is refused as a point the motor cannot reach. Every kind of motor is held to it, a block-commutated or brushed one included, though such a drive can sometimes go to full duty and lose only the drop.
- A motor's working temperature is used only if you give it. The magnet coefficient is that of neodymium.
- The trip check assumes nothing shorts the motor or burns the energy. Short-circuit behaviour itself is not modelled: the withstand time is passed on where the datasheet gives it.
- Through time, heating between neighbouring chips and across the layer under the package follows the loss as fast as the copper under the chips can. The package body and the heatsink's surface slow a real one further, so a burst of a few seconds comes out warm, by up to the whole rise across that layer.
- The layer between a package and its heatsink is worked out for a generic mounting unless you give it. For a moulded module the range is wide (0.07 to 0.87 K/W at 15 A), and it is the largest single unknown in such a module's temperature: measure it, or give the range its due.
- An imported trajectory, and a load that comes and goes in a reference file, have their losses worked at each chip's mean temperature over the whole pattern. With long pauses between bursts the junction is far hotter than that while it works, and the loss reads low: about a tenth on a silicon IGBT whose junction swings 100 °C.
- Above the last current a datasheet's table gives, an on-state voltage is drawn midway between staying where it is and rising in proportion. The result says how far off that can be, and a pass that would not survive it is reported as undecided.

## 6. Life under thermal cycling is generic

The life estimate counts each chip's own temperature swings, those of every turn of the motor included, and uses a model fitted to modules with aluminium bond wires. It is applied to discrete parts too, which it was not fitted on. A real part may last several times longer or shorter. Use the manufacturer's power-cycling data where there is any.

## 7. The page

- The example motor is wound for your device's voltage and made the size whose current limit is 90% of the part's rated current (for a motor with no limit, a design point at 30% of it). It is a starting size, not your motor.
- On a phone the drawing is wider than the screen and slides sideways.
- The report is laid out by your browser's print function.
- The Markdown report covers the devices, the motion, what to build and what the device can drive. What is set beside them on screen (loads, motors, the values of a setting) is in the printed report only.
- The motor opened as the starting point for a device is a template, picked by voltage and by how many switches the package holds. It is not a recommendation: the application decides the kind of motor, and nothing in a transistor's datasheet ranks motors. The loads listed for a kind of motor are the common ones, not the only ones it can drive.
- Trying a setting holds two to five values. Once a value is added, the starting ones no longer follow the design point.
- What the page holds is kept in your browser. Open in two tabs, the one you return to takes up what the other changed.

## 8. A part typed in by hand, and cooling by air

- A typed transistor (silicon, SiC or GaN) is one to a package. Its switching loss is estimated from its charges, never measured energy; its output charge is one figure carried to other voltages as a junction's charge goes; its thermal path is one resistance, and its response in time is computed for the column under its die (see [THERMAL_MODEL.md](THERMAL_MODEL.md)): the estimate is the fast, warm side of what real parts do, and the top of the range is a bound.
- A typed IGBT and its diode are drawn from the figures printed hot: each on-state line is straight from its knee to the point printed and held at the hot temperature at every temperature, and each energy is straight through zero in current and in proportion to the voltage (D161). Typed from the made-up module's own figures it loses 1.2% more than the module's file, which draws a 25 °C line as well; with the hot figures alone, the knees taken at half the voltage and the energies held hot, 16% more. Its thermal path is one resistance for the IGBT and one for the diode, with no figure for their response in time.
- A figure a typed part may leave empty is taken by a rule and said: the highest junction temperature by its kind (175 °C for silicon and SiC, 150 °C for GaN and an IGBT), the plateau as the threshold plus 2 V, the gate-source charge as 1.4 times the gate-drain charge, an IGBT's knees as half its voltages and its energies at 25 °C as the hot ones. Each one holds the verdict at a caution until the datasheet's figure replaces it. On the typed template a plateau a volt off moves the switching loss by −4% to +13%, and a gate-source charge half or double by −12% to +24% (D160).
- A heatsink or a board the page offers for a box left empty is worked out from the loss at the design point alone: the heatsink that holds itself at 60 °C, or the smallest board that keeps the top of the junction's range under its rating. It knows nothing of the motion, the enclosure or another limit, and a verdict on it is held at a caution and says the cooling was sized by the tool.
- The figures are checked for slips, not for truth: nothing compares them with the datasheet.
- An IGBT's dead time left open is worked out from its datasheet's turn-off times where it gives them, and is 1 µs where it does not; for an IGBT it costs voltage, not loss. A module with its own gate drivers sets its own, and none is assumed for it.
- A heatsink is sized to stay at or below 100 °C unless another limit is given. That is a default design target, not a rating: what a heatsink may reach depends on the board, the capacitors, the insulation and the life wanted, and the junctions would often stand more.
- A dead time left open is worked out for the gate drive in use: the turn-off time from the charges, a tenth longer for a hot part, 50 ns for the two gate-driver channels not answering together (10 ns for GaN), a margin of 1.2, and no shorter than 100 ns (20 ns for GaN). The delay before the switch begins to turn off needs the total gate charge. Where the device model has it (a typed part can give it; a datasheet read from a PDF does not carry it yet) the figure is the least such a drive would be set to. Where it has not, the gate is taken to hold the most usual for its kind above the plateau and the figure is an estimate, said to be one, that a bench has to confirm. Firmware is often left at 300 to 800 ns; the advice says what 500 ns would cost, and the result uses yours when you give it. How much of the dead time the body diode really conducts for is not modelled: all of it is counted. A transistor whose datasheet gives no curve for its reverse path is taken to drop, in the dead time, its kind's usual figure (0.8 V for silicon, 3 V for silicon carbide, 2 V for GaN) or what its channel would, whichever is more; it is said to be assumed and the term is held in doubt by the spread between parts of its kind.
- A heatsink in air is one thermal resistance carrying the whole stage's loss. With devices in parallel the loss is counted as if each lost what the hardest-worked one does, which errs warm.
- With no heatsink and each part standing in the air, each package has one figure from junction to air and feels nothing of its neighbours. Where no figure is given, 62 K/W is used for a TO-220, 40 for a TO-247 and 43 for a TO-263 on a square inch of copper. What lies between case and air is that figure less the smaller of the chips' junction-to-case figures.
- With the parts soldered to one board, the datasheet's figure is brought to the copper each part has, along the curve datasheets print for the TO-263 and the DPAK (26.51 + 128/(1.69 + A), A in cm², as a ratio), and every watt the stage loses warms every part through the board's own path to still air, 10 W/(m²·K) from both faces. Left out: the number of copper layers and vias, which help by 20 K and more at half a watt a part; how close the parts are, where the inner ones run 3 to 20 K hotter; airflow, an enclosure, and heat leaving by the wires. The board is one temperature for the neighbours' share, which is on the warm side for a single-layer board. A check says when the board under a part passes 120 °C.
- Through a motion, a heatsink in air sits where the motion's mean loss puts it, and with no heatsink each package sits where its own mean loss puts it (at standstill, the loss of the rotor position that works it hardest), as if the motion repeated without end. The motion is then followed from the hottest package, so the others are shown a little warm. A heatsink given with its heat capacity is followed as it warms instead.
- The junction-to-air figure the heatsink advice gives for doing without a heatsink is worked out for a package alone in the air, running and held still; on a shared board it is the upper bound.

## 9. Comparing parts from different datasheets

- Each part's switching energy was measured by its own vendor, on that vendor's fixture, at its own gate resistor, gate voltage and test voltage. The comparison shows those conditions beside each part and says when one part's figure is measured and another's is estimated from charge, or when one is brought in proportion to a higher voltage than it was measured at. It cannot remove the difference.
- Losses within 5% of each other are marked level: the model does not tell them apart. There is no range on loss beyond that.
- A caution on the data is raised when the operating point is outside what the datasheet gives for a loss term, and that could move the stage's loss by 5% or more: the term's share of the loss, times how much of the term is in doubt. A table measured at one temperature is taken to drift by up to 0.5% a kelvin away from it; an on-resistance whose rise is the technology's usual one, by the spread between parts of that technology. Below that the note is still listed and the verdict does not change.
- Table points with an assumed shape between them, and switching loss estimated from charge, are stated under data support and are not a caution by themselves.

## 10. The switching event

- The event plot under the chart of power lost in the switch is a behavioural circuit, not a device model: a square-law channel, capacitances from the datasheet's charges, a diode that holds its charge until it is out, an IGBT's tail shaped by one time. Its energy is made the loss model's by one free factor on the gate-drain charge (and the tail time for an IGBT), so the energy agrees with the chart by construction; the shape, the slopes and the peaks rest on the figures assumed and are named as such.
- Its times are held to a datasheet's only where the datasheet gives them; on the made-up IGBT sheets the turn-off delay comes within three times and the fall time within five, the fall short.
- Board inductances are yours to give, from a layout file, a box or the estimate from the loop's size. Board files are not read. The estimate is a parallel-plane or flat-trace formula, not a field solution.
- The verdict's overshoot check is the quick L·I/t_fall estimate whatever the event shows.
- Snubbers, a second switch in parallel, the gate driver's own output stage and its supply's droop, and a diode's forward recovery are left out.

## 11. Applications and their duties

The applications' duties, loads and motors are those of typical products of each kind, worked out from public figures of such products, not measured on one. A real product's programme, wash load or fan blades will differ. A start at the current limit is the drive's limit held while the load is brought to speed; a real drive's speed loop and a sensorless start's own current profile are not followed. A heatsink in air given no heat capacity is taken as a typical one, said as assumed. The rule for steady state is on the junction's rate of change, so a duty with very little loss is called steady while its heatsink still has up to about 2.5 °C to rise.

## 12. Not yet

- Export of a device model to other simulators.
- Reading a datasheet on the hosted page. That needs your own key and a local install.
- The hosted page runs the engine in the browser. In that mode the Python runtime is fetched once from cdn.jsdelivr.net; nothing you enter is sent anywhere. `motionsim serve` fetches nothing.
