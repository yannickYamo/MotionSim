# Roadmap

## What works today

- A transistor typed in from a dozen datasheet figures becomes a device model, on the page or from the command line, with no key.
- A datasheet PDF becomes a device model: IGBT, silicon MOSFET, SiC MOSFET or GaN, discrete or module, with or without built-in drivers. Your own double-pulse measurements can replace its switching energy.
- Seven kinds of motor, each from its catalogue figures, braking included where the machine can brake.
- A load and its motion, or a mission profile from a file, with junction and heatsink temperature followed through time, the way the drive starts the motor, and braking energy turned into a DC-link voltage.
- Cooling as a heatsink at a known temperature, a heatsink in air, or no heatsink: parts standing free, or soldered to one board and warming each other.
- Losses, junction temperatures, plain-language checks, a speed-torque map, a life estimate under thermal cycling, and starting values for gate resistors, dead time, modulation and heatsink.
- What to build around the device: heatsink, link capacitor and its ripple current, gate drive, protection. And the question turned round: what a device can drive, and how much heavier the load could be.
- Up to five devices, loads or motors side by side, or one setting at two to five values, with each one's margin, every loss and temperature of its hottest switch position, and the test conditions its switching loss rests on; a setup saved to a file; a report.
- All of it from a local page and from the command line, where one file runs every step and a guide tells a coding agent how to drive it. The result as a report in Markdown or as a PDF.

## Next, in order

1. **Accuracy, shown.** One public measured loss is compared today. Next: the other published reference designs for parts already read (a six-step 54 V stage, two GaN motor boards with measured temperature rise), then public datasheets through their vendors' own calculators at the same operating points, part by part.
2. **Export of device models** to the formats circuit simulators read, so a model built from a datasheet can be used elsewhere.
3. **Typing in, further.** An IGBT with its diode from typed figures, and switching energy typed in where the datasheet tabulates it.
4. **The reader, further.** Quantities spread over several figures, curves drawn against gate voltage, and the figures of scanned datasheets.
5. **The page, further.** The datasheet's own page shown beside what was read from it; the printed report laid out by the tool; the Markdown report carrying what is compared on screen; a setting drawn as a curve against its values.
6. **The model, further.** Copper layers and spacing on a board. A braking resistor, iron loss that follows the flux, saturation curves instead of one figure, thermal rebalancing between devices in parallel.

## Not planned

- Topologies other than motor inverters.
- A built-in device database. You bring the datasheets.
- A simulation of the control loop. Currents and duty cycles from another simulator or a drive's log can be imported from the command line instead.

[LIMITS.md](LIMITS.md) lists what the present version leaves out.
