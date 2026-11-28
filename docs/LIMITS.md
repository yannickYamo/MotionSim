# Limits

What MotionSim does not do, or does only roughly, in order of how much it matters. Read this before trusting a result.

## 1. Four published boards behind it, and they do not settle much

The loss and temperature model is checked against closed-form solutions and an independent numerical integration, and against one vendor's simulator on one part. It has been compared with four reference designs their makers publish ([VALIDATION.md](VALIDATION.md), Level D), and on these it reads low on loss and hot on temperature:

- **Loss.** 10 to 31% below a 48 V inverter's measurement that includes the board's own resistance, with the switching estimate from charge 30% low at low current and 30% high at high current. On a six-step board the model has no figure for the 2 W the driver and the supplies take, and half of what PWM adds there.
- **Temperature on a board with no heatsink.** With the datasheet's junction-to-air figure from its standard test board, the one the tool asks for, the hottest case's rise came out about twice the measured on one board at every point; on a second, within 7% at its lowest switching frequency and up to twice at its highest; on the third, from about the measured at 9 A to 3.8 times at 27 A, and past that loss and temperature fed each other into no steady state at a current the board carried. These boards spread the heat through copper in several layers, which that figure does not see. Where a datasheet also gives the figure on its maker's own evaluation board, it came closer on the first board (1.15 to 1.35 times) and read 19 to 26% low on the second at its lowest frequency. Few boards, two parts, all in still air: take this as the direction of the error, not its size.

What was compared is the case temperature; no junction temperature has been compared with a measured one. Treat every result as an estimate to be confirmed on the bench, and on a board with no heatsink, one temperature reading at a known load in place of the datasheet's junction-to-air figure.

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

## 4. The control: settled in the five steps, simulated in the control lab

A modern drive runs field-oriented control: a current loop, a speed or position loop, and an estimate of where the rotor is. MotionSim treats it in two ways, and they are kept apart.

- **The five steps, the comparison, the motion, the report and every command but `motionsim control`** use the settled result. No loop is simulated. The tool works out the currents the loops settle to, at every instant of the motion, and gives those to the loss and temperature engine. For a permanent-magnet motor that is the d- and q-axis current making the torque with least current, and field weakening where the voltage runs out. Every verdict, loss and temperature of the five steps is this. [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) says why.
- **The control lab** simulates the loop in time: a permanent-magnet motor, the stage switch by switch, and a sampled controller wired from blocks, with the run's currents and commutations handed to the same loss and thermal model. It is on the local page and in `motionsim control`, not on the hosted page. Nothing it finds changes a verdict of the five steps. Its own limits are at the end of this section; [CONTROL.md](CONTROL.md) has the model.

Held at a steady point under field-oriented control, the lab ends where the settled result is: [VALIDATION.md](VALIDATION.md) has the figures.

### The settled result

What it covers, and how:

| What a drive does | How it is represented |
|---|---|
| Steady running at a speed and torque | The currents and voltages field-oriented control settles to, exactly |
| A motion, second by second | Each instant solved as settled; junction temperature followed through time |
| Standstill and stall | The same torque at zero speed, with the rotor where the hottest chip is loaded most |
| A sensored start | Only the current the torque needs, from the first instant |
| A sensorless start | Open loop: alignment at a held current, a ramp at that current, then handover. With signal injection: only the current the torque needs. The current is set; the loop is not simulated |
| Braking | The energy returned to the DC link and the voltage it reaches, as a worst case |
| Ripple at the switching frequency | Worked out from the switching sequence and the motor's inductance |

What it leaves out, and what each could cost you. The control lab shows several of these for a permanent-magnet motor; the five steps still leave them out.

- **The current loop's transient.** A step in torque makes the current pass its reference for about a millisecond. That is too short to move a junction temperature much, but a pulsed current rating has no moment to give. Where the motor's current limit is given, the check on that rating is made at the limit, which is where a drive's current sits in a hard acceleration or a stall. Where none is given, it is made at the settled current with 15% allowed for overshoot, and the switching ripple on top of that where it is known: a common figure and not your drive's, and a loop tuned for speed overshoots more. The check says that the 15% is this fixed allowance. A run in the control lab holds the same rating to its own loop instead: after a torque step, to the overshoot that run's current made; after any other test, to the 15%, said as such.
- **Whether the control holds.** That the rotor follows an open-loop ramp under the load, that an observer keeps the rotor, that the loops are stable: all taken as given. A start against full load can fail in ways this tool will not show.
- **Low speed without a sensor.** The tool gives the speed below which the back-EMF cannot be read through the voltage this device and dead time get wrong. It is a closed-form figure for firmware that corrects for neither, with the back-EMF taken as readable at four times the error. Firmware that corrects for dead time reads lower; an observer in a noisy drive may need more, and a winding hotter than the drive was set for adds an error that is not counted. It is an estimate with nothing independent behind it yet. Permanent-magnet motors under sinusoidal control only. The control lab sets a floor of its own beside each observer, from the stage, the current samples' noise and resolution and a wrong resistance, and beside it the design speed and the slowest the motion turns; it is held to the simulated run, not to hardware.
- **What the drive does to protect itself.** A real drive brakes more slowly to hold the link voltage and cuts its current when hot. The tool reports what happens without either, which is the harder case.
- **Torque ripple.** From the back-EMF's harmonics, cogging and dead time. Not modelled, so neither is its heating.
- **The d-axis current that loses least.** Advised at the design point where the motor's iron loss is given, with iron loss taken to follow the square of the flux. The results themselves stay on least current, which is what a drive runs unless it is told otherwise.

Where the loop's own behaviour decides the answer (a fault, a hard reversal, an aggressive tuning), run it in the control lab if the motor is a permanent-magnet one, or bring its currents and duty cycles from a control simulation or a drive's log: `motionsim trajectory` takes them as they are.

### The control lab

- **Not compared with a measured drive.** It is held to closed forms, to the settled engine at steady points and to linear theory. No waveform, loss or temperature from it has been set beside hardware. Comparing two schemes on the same device and board is on firmer ground than either one's watts, since what the model gets wrong is common to both; the exception is a scheme that moves the current at the switching instant (a clamp placed on the current, a predictive cost), whose gain rests on the shape of the switching-energy curve.
- **Permanent-magnet motors only.** Any other kind is refused.
- **No saturation.** The simulated motor's inductances are constants.
- **No cogging, no back-EMF harmonics, no iron loss in the simulated motor.** The torque ripple shown is the current's alone. Iron loss is counted afterwards from the motor's one figure, taken to follow the square of the stator flux; without that figure the least-loss reference is the least-current one.
- **The averaged stage has no ripple.** It misses the ripple's share of conduction loss and the current at each commutation. It is for a loop's dynamics; a figure of loss wants the switched stage.
- **The stage is ideal unless asked.** The dead time and the devices' drop are left out of the simulated voltage until switched on. The loss model charges the dead time either way.
- **The Laplace view is a second lens.** It takes each axis alone, no voltage or current limit, the angle known exactly and a shaft with inertia alone (or the twisting shaft given, its play left out). It knows nothing of ripple, sensors or observers, and gives nothing for a predictive, deadbeat or direct torque controller. Where it and the run in time part, the run is the answer.
- **Unstable gains are run, not refused.** Gains with a pole outside the unit circle run with a caution, since the voltage limit holds such a loop in an oscillation. A current that runs away ends the run as a refusal.
- **A start with no encoder is open loop to the hand-over.** The observers read the back-EMF and cannot start from rest. The simulated rotor starts aligned, and no signal injection is modelled. A reversal through standstill is taken open loop only where the start's hand-back is set; it is off by default, and the C export refuses a scheme that sets it. The open-loop stretch holds the rotor only where the starting current covers the load and the ramp: on a fast motor with little current to spare the rotor falls behind the ramp and is lost there, and the run says so.
- **The observer's floor is an estimate.** Four times the voltage it reads through wrong, a margin taken over from the closed form; a wrong inductance turns the angle at any speed and is not counted in it.
- **The controller's own figures of the stage are two straight lines** (conduction and switching energy against current) with no temperature in them. The thermal supervisor, the loss-weighted predictive cost and the least-loss reference work from those, as firmware would, and are only as good.
- **Losses are read in bins of whole sampling periods,** at each bin's mean currents. A run of more than 8192 sampling periods has several to a bin.
- **A run is at most 5 s and 500 000 sampling instants,** a sweep at most 12 variants.
- **Tuning rules are starting points.** Each gain comes from a stated rule, and several say they are this tool's own choice. None was tuned on a drive.
- **The DC link, on the mains only, and one way.** For a drive fed from the mains the lab runs the front end's control on what the motor's run drew, and shows the link. The motor's run itself is made on a steady link: a link that falls under what the motor needs is said, not simulated in the current loop. On a supply or a battery the link does not move.
- **A six-pulse rectifier's link is run with no choke.** The settled result takes a link choke and a smooth current; the link through a test has only the capacitor, so its ripple and its current pulses are larger there.
- **The front end is sized for the drive's torque limit.** Its capacitor (where none is given), its gains and its limits come from the design point's power by the torque limit over the design torque, whatever the test. Its controller is sampled once a switching period, up to 100 kHz. In the simulation the feed-forward is exactly what the inverter draws, with no delay: a figure made in a controller holds the link a little less well.
- **The front end's control is averaged.** Its stage is simulated over a switching period's mean (no ripple of its own, no dead time), on a stiff, balanced mains; start-up from an uncharged link and its protections are not written. Its gains come from stated rules and were tuned on no drive.
- **Left out:** six-step and overmodulation, optimised pulse patterns, a position loop, a braking chopper.

## 5. Simplifications in the model

- Iron loss and saturation are modelled only if you give them: a no-load loss at a speed, split evenly between its two kinds and taken at full flux; and one saturation current, by which both of a permanent-magnet motor's inductances fall with the magnitude of the current (the motor keeps its saliency; cross-saturation between the axes is not modelled). Without them the result says they are left out.
- Current ripple at the switching frequency is worked out where the motor's inductance is known. It adds to conduction loss and moves the current at the switching instants, and half of it, peak to peak, is added to the peak current held against the continuous and pulsed ratings. That takes the largest ripple of the output period to ride on the fundamental's peak, the worst case; a point told outright, with no motor, has no ripple and is checked on its fundamental alone. The distortion dead time adds to the current at low speed is not modelled.
- Motor inverters only: no DC-DC, power-factor correction, three-level or soft-switching stages.
- Within an output period each chip's loss is read at its own temperature at each instant. Through a motion or a trajectory it is read at the temperature the instant would settle at (see below).
- Losses are worked out from the datasheet's typical values. A part at the maximum of its spread loses more: the result says by how much its on-state voltage can differ where the datasheet prints a maximum, and there is no worst-case run. A junction-to-case resistance is taken at its maximum where one is printed.
- A transistor's on-resistance given at 25 °C alone, typed in, read from a datasheet or written in a device file as one curve, is taken to rise as its technology usually does (as the power 1.9 of the absolute temperature for silicon to 250 V, 2.4 above, 1.0 for silicon carbide, 2.2 for GaN). It is said to be assumed and the conduction loss is held in doubt by the spread between parts of its kind, about a tenth at 100 °C. The datasheet's hot figure removes it.
- A recovery charge is tabulated at one current and 25 °C. Away from that current it is taken to follow the square root of the current, and for a silicon transistor to rise by 0.7% a kelvin. Parts show a power between a half and nearly one: above the test current a real part may grow faster, and below it the square root is the high end of what is left, the safe one for a loss. How fast the current is turned over is not in it, and a silicon carbide part's charge is not raised with temperature, though it does rise: its tabulated charge is mostly capacitance, which is counted once more with the output charge, and for the usual part that outweighs the rise. The datasheet's own hot figure is not read.
- A measured turn-on energy is taken, at no current, as the output charge times the test voltage where the charge is known; an IGBT's goes to nothing.
- Measured switching energy follows the supply voltage along the datasheet's own figure where it has one. Without one it is scaled in proportion to voltage, which above the test voltage is the least a real device does; the result says how much more it could be. It follows your gate resistor only where the datasheet has a figure for that. Either figure, measured at one current, is applied at every current.
- Gate resistors chosen by the tool are totals. Where the datasheet gives the transistor's own gate resistance the choice is never below it; where it does not, a very small chosen value may not be reachable.
- Devices in parallel share as unevenly as the datasheet's maximum over typical allows, with the typical part among maximum ones carrying the most. That ignores how a hot transistor's rising resistance pushes current back to the others, so it is on the cautious side. Where the datasheet gives no maximum, sharing is taken as equal.
- The usable voltage loses dead time, the shortest pulse you give, and the devices' drop at the peak current, taken at the heatsink temperature. A stage left with less than half its voltage is refused as a point the motor cannot reach. Every kind of motor is held to it, a block-commutated or brushed one included, though such a drive can sometimes go to full duty and lose only the drop. One thing is not taken off: the voltage a drive without dead-time compensation loses to the dead time itself (about 8/π times the dead time times the switching frequency, in place of twice). A field-oriented drive weakens the field from 95% of that voltage, the 5% the control lab's regulator keeps in hand; a drive that keeps less reaches a little further than the settled result says, one that keeps more draws more current there. A d-axis current you hold yourself is held up to the full voltage.
- The gate-drain charge is the datasheet's at its test voltage. On a lower supply it is taken to fall as the square root of the voltage, the charge of an abrupt junction, which makes the edge faster and the gate resistors chosen for a slew limit larger; a real part's curve is not read, so check the edge on the bench where the supply is under about half the test voltage. Above the test voltage the charge is kept as tabulated, and the dead time is worked out with the tabulated charge at any supply: each is the safe side.
- A chip's own thermal network is stacked on the case's, and each is heated by the chip's whole loss at once. The heat really reaches the case through the chip's network, a little later: the mean temperature is exact, and peaks and swings come out up to about 2% high.
- A motor's working temperature is used only if you give it. The magnet coefficient is that of neodymium.
- The trip check assumes nothing shorts the motor or burns the energy. Short-circuit behaviour itself is not modelled: the withstand time is passed on where the datasheet gives it.
- Through time, heating between neighbouring chips and across the layer under the package follows the loss as fast as the copper under the chips can. The package body and the heatsink's surface slow a real one further, so a burst of a few seconds comes out warm, by up to the whole rise across that layer.
- The layer between a package and its heatsink is worked out for a generic mounting unless you give it. For a moulded module the range is wide (0.07 to 0.87 K/W at 15 A), and it is the largest single unknown in such a module's temperature: measure it, or give the range its due.
- An imported trajectory, and a load that comes and goes in a reference file, have their losses worked at each chip's mean temperature over the whole pattern. With long pauses between bursts the junction is far hotter than that while it works, and the loss reads low: about a tenth on a silicon IGBT whose junction swings 100 °C.
- Above the last current a datasheet's table gives, an on-state voltage is drawn midway between staying where it is and rising in proportion. The result says how far off that can be, and a pass that would not survive it is reported as undecided.

### The front end

- A stage that shapes the current is taken to draw a sine in phase with the voltage; what its control adds is the control lab's.
- The part under test is the front end's switch too, in every position; a diode that is not that part drops a usual figure (1.0 V in a mains bridge, 1.5 V for a fast diode).
- The inductor is sized for a stated ripple and its copper is not sized: its core and copper loss are not counted, and the result says so.
- The harmonic limit is IEC 61000-3-2 class A, up to 16 A a phase, stated and not enforced: a product of another class has other limits.
- From a design file the recommendation is made before the motion is run, so it does not know whether the motion brakes: name a stage that returns energy (`totem_pole`, `active`) where it does. The page knows, and weighs it.
- The recommendation weighs loss, the limit and braking. It does not weigh cost, size or the number of parts.

## 6. Life under thermal cycling is generic

The life estimate counts each chip's own temperature swings, those of every turn of the motor included, and uses a model fitted to modules with aluminium bond wires. It is applied to discrete parts too, which it was not fitted on. A real part may last several times longer or shorter. Use the manufacturer's power-cycling data where there is any. The model was fitted to swings of 30 to 80 K: a life whose wear comes from a swing outside them is an extrapolation, and the result says so.

## 7. The page

- The example motor is wound for your device's voltage and made the size whose current limit is 90% of the part's rated current (for a motor with no limit, a design point at 30% of it). It is a starting size, not your motor.
- On a phone the drawing is wider than the screen and slides sideways.
- The report is laid out by your browser's print function.
- The Markdown report covers the devices, the motion, what to build and what the device can drive. What is set beside them on screen (loads, motors, the values of a setting) is in the printed report only.
- The motor opened as the starting point for a device is a template, picked by voltage and by how many switches the package holds. It is not a recommendation: the application decides the kind of motor, and nothing in a transistor's datasheet ranks motors. The loads listed for a kind of motor are the common ones, not the only ones it can drive.
- Trying a setting holds two to five values. Once a value is added, the starting ones no longer follow the design point.
- What the page holds is kept in your browser. Open in two tabs, the one you return to takes up what the other changed.
- `motionsim serve` keeps one session, the one the page shares with a coding agent: two browsers on one server work on the same design, and each takes up what the other changed. It is a tool for one person on one machine.

## 8. A part typed in by hand, and cooling by air

- A typed transistor (silicon, SiC or GaN) is one to a package. Its switching loss is estimated from its charges, never measured energy; its output charge is one figure carried to other voltages as a junction's charge goes; its thermal path is one resistance, and its response in time is computed for the column under its die (see [THERMAL_MODEL.md](THERMAL_MODEL.md)): the estimate is the fast, warm side of what real parts do, and the top of the range is a bound.
- A typed IGBT and its diode are drawn from the figures printed hot: each on-state line is straight from its knee to the point printed and held at the hot temperature at every temperature, and each energy is straight through zero in current and in proportion to the voltage. Typed from the made-up module's own figures it loses 1.2% more than the module's file, which draws a 25 °C line as well; with the hot figures alone, the knees taken at half the voltage and the energies held hot, 16% more. Its thermal path is one resistance for the IGBT and one for the diode, with no figure for their response in time.
- A figure a typed part may leave empty is taken by a rule and said: the highest junction temperature by its kind (175 °C for silicon and SiC, 150 °C for GaN and an IGBT), the plateau as the threshold plus 2 V, the gate-source charge as 1.4 times the gate-drain charge, an IGBT's knees as half its voltages and its energies at 25 °C as the hot ones. Each one holds the verdict at a caution until the datasheet's figure replaces it. On the typed template a plateau a volt off moves the switching loss by −4% to +13%, and a gate-source charge half or double by −12% to +24%.
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
- Board inductances are yours to give, from a layout file, a box or the estimate from the loop's size. The estimate is a parallel-plane or flat-trace formula, not a field solution.
- On the local page a board's own design file is read for those figures (KiCad and IPC-2581; [BOARD.md](BOARD.md)). What that reading is and is not:
  - It has not been compared with a field solver or with a measurement. It is checked against closed forms on simple shapes: a bar, a loop of track, a pair of planes.
  - Only made-up boards have been read.
  - The resistance is a steady current's, at 20 °C. The inductance is the current of least magnetic energy, the limit of a fast edge free to spread across the copper; there is no skin or proximity effect within the copper's thickness and nothing in between the two.
  - Copper of other nets is ignored, a plane under the loop that is not the loop's own included, and so is copper outside the window round the loop's parts. Each leg is solved alone.
  - A package's and a capacitor's own inductance are the usual of their kind, told from the footprint's name, to half either way.
  - Each figure comes with a band, a quarter either way at best for the board's copper and wider where a stack-up was assumed, a pour was read from its outline or a track is thinner than the mesh. The event uses the value; the band is shown and is not carried into the event's figures.
  - ODB++ and STEP are refused. A STEP file has no nets, so no loop can be read from it.
- The verdict's overshoot check is the quick L·I/t_fall estimate whatever the event shows.
- Snubbers, a second switch in parallel, the gate driver's own output stage and its supply's droop, and a diode's forward recovery are left out.

## 11. Applications and their duties

The applications' duties, loads and motors are those of typical products of each kind, worked out from public figures of such products, not measured on one. A real product's programme, wash load or fan blades will differ. A start at the current limit is the drive's limit held while the load is brought to speed; a real drive's speed loop and a sensorless start's own current profile are not followed. A heatsink in air given no heat capacity is taken as a typical one, said as assumed. The rule for steady state is on the junction's rate of change, so a duty with very little loss is called steady while its heatsink still has up to about 2.5 °C to rise.

## 12. Not yet

- Export of a device model to other simulators.
- Reading a datasheet on the hosted page. That needs your own key and a local install.
- The control lab and the board reader on the hosted page. Both run on a local install only.
- Reading ODB++.
- The hosted page runs the engine in the browser. In that mode the Python runtime is fetched once from cdn.jsdelivr.net; nothing you enter is sent anywhere. `motionsim serve` fetches nothing.
