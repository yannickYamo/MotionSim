# Roadmap

## What works today

- A MOSFET, SiC or GaN transistor typed in from six datasheet figures, or an IGBT and its diode from the figures printed hot, becomes a device model, on the page or from the command line, with no key.
- A datasheet PDF becomes a device model: IGBT, silicon MOSFET, SiC MOSFET or GaN, discrete or module, with or without built-in drivers. Your own double-pulse measurements can replace its switching energy.
- Seven kinds of motor, each from its catalogue figures, braking included where the machine can brake.
- A load and its motion, or a mission profile from a file, with junction and heatsink temperature followed through time, the way the drive starts the motor, and braking energy turned into a DC-link voltage.
- Cooling as a heatsink at a known temperature, a heatsink in air, or no heatsink: parts standing free, or soldered to one board and warming each other.
- Losses, junction temperatures, plain-language checks, a speed-torque map, a rough indicator of life under thermal cycling, and starting values for gate resistors, dead time, modulation and heatsink.
- What to build around the device: heatsink, link capacitor and its ripple current, gate drive, protection. And the question turned round: what a device can drive, and how much heavier the load could be.
- Up to five devices, loads or motors side by side, or one setting at two to five values, with each one's margin, every loss and temperature of its hottest switch position, and the test conditions its switching loss rests on; a setup saved to a file; a report.
- All of it from a local page and from the command line, where one file runs every step and a guide tells a coding agent how to drive it. The result as a report in Markdown or as a PDF.
- The local page started with one command, `docker compose up` or `motionsim serve`, with the datasheet reader's key set under Settings and a small store on the machine for what is kept.
- The control lab, on the local page and from `motionsim control`: the control loop of a permanent-magnet motor simulated in time, from 18 schemes of swappable blocks tuned for the design, through seven tests, a window of the design's own motion among them, with each run's loss, ripple and junction temperature from the tool's own loss and thermal model; each loop's Bode plot, margins and poles beside it; and 23 explorations ready to sweep. A run holds the device's pulsed rating to the overshoot its own loop made, and sets a sensorless scheme's speeds beside its observer's floor, with an open-loop hand-back to take a reversal through standstill.
- A drive fed from the mains: its front end (a rectifier, a boost, an interleaved boost or a totem-pole stage on one phase; a six-pulse rectifier, a Vienna rectifier or an active front end on three), one recommended for the design with its reason and any other a press away, with its loss, inductor, capacitor current, power factor and harmonics against the limit. In the control lab its control runs on the same DC link as the motor's, tied by the power the motor is about to draw, and both leave as C, each replayed against its simulation.
- A board's own design file (KiCad or IPC-2581) read on the local page for the switching loop's inductances, resistance and decoupling capacitance, each with the range it is believed in.

## Next, in order

1. **Accuracy, shown.** Four published reference designs are compared today ([VALIDATION.md](VALIDATION.md), Level D): two measured stage losses, and the measured case temperature of three boards in still air, a six-step 54 V stage and two GaN motor boards. Their largest error is the path from a board to the air, taken from a datasheet's junction-to-air figure: up to two to four times the measured rise, always on the hot side. Next: that path worked out from a board's layers and copper; a published board measured on a heatsink of known resistance; the switching estimate from charge against a double-pulse measurement. The vendors' own calculators at the same points are not done: none publishes its result where it can be cited.
2. **The control lab, held to a measured drive.** A held design point already ends on the settled result ([VALIDATION.md](VALIDATION.md)). Next: a run compared with a measured drive's phase currents, where a public record of one, with the motor's figures and the drive's settings, can be found and cited.
3. **The board reader, held to more.** A figure from a board set beside a field solver's and a measured ringing frequency; ODB++; copper of other nets; coupling between legs.
4. **Export of device models** to the formats circuit simulators read, so a model built from a datasheet can be used elsewhere.
5. **Typing in, further.** Switching energy typed in where the datasheet tabulates it.
6. **The reader, further.** Quantities spread over several figures, curves drawn against gate voltage, and the figures of scanned datasheets.
7. **The page, further.** The datasheet's own page shown beside what was read from it; the printed report laid out by the tool; the Markdown report carrying what is compared on screen; a setting drawn as a curve against its values.
8. **The model, further.** Copper layers and spacing on a board, for cooling. A braking resistor, iron loss that follows the flux, saturation curves instead of one figure, thermal rebalancing between devices in parallel.
9. **The control lab, further.** Six-step and overmodulation; a position loop.
10. **The mains front end, further.** The link's voltage fed back into the motor's run (today the motor is run on a steady link and the link on what it drew); a mains as flags on the command line (a design file carries one today); the inductor's core loss; start-up from an uncharged link; a braking chopper.
11. **The control lab for other motors.** Induction first (rotor-flux field-oriented control), then block-commutated brushless.

## Not planned

- Power stages other than a motor's inverter and the front end that feeds it from the mains: no general power supplies or chargers.
- A built-in device database. You bring the datasheets.
- A free-form editor for control diagrams. The control lab's schemes are fixed wirings whose blocks can be swapped and set; a scheme of your own is plain data sent to the engine.
- The control lab and the board reader on the hosted page. All calculation of both is done by the engine on your own machine.
- A database server. What is kept is one SQLite file in your own folder.
- Reading STEP for parasitics: it holds shapes and no nets.

[LIMITS.md](LIMITS.md) lists what the present version leaves out.
