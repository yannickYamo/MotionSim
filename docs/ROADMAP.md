# Roadmap

## What works today

- A datasheet PDF becomes a device model: IGBT, silicon MOSFET, SiC MOSFET or GaN, discrete or module, with or without built-in drivers. Your own double-pulse measurements can replace its switching energy.
- Seven kinds of motor, each from its catalogue figures, braking included where the machine can brake.
- A load and its motion, or a mission profile from a file, with junction and heatsink temperature followed through time, the way the drive starts the motor, and braking energy turned into a DC-link voltage.
- Losses, junction temperatures, plain-language checks, a speed-torque map, a life estimate under thermal cycling, and starting values for gate resistors, dead time, modulation and heatsink.
- What to build around the device: heatsink, link capacitor and its ripple current, gate drive, protection. And the question turned round: what a device can drive, and how much heavier the load could be.
- Up to five devices, loads or motors side by side, or one setting at up to five values, with each part's margin and the test conditions its switching loss rests on; a setup saved to a file; a report.
- All of it from a local page and from the command line.

## Next, in order

1. **Accuracy, shown.** Run public datasheets through MotionSim and through their vendors' own calculators at the same operating points, and publish the differences part by part. Then a measured inverter loss, from any source.
2. **Export of device models** to the formats circuit simulators read, so a model built from a datasheet can be used elsewhere.
3. **The reader, further.** Quantities spread over several figures, curves drawn against gate voltage, and the figures of scanned datasheets.
4. **The page, further.** The datasheet's own page shown beside what was read from it; the printed report laid out by the tool.
5. **The model, further.** A braking resistor, iron loss that follows the flux, saturation curves instead of one figure, thermal rebalancing between devices in parallel.
6. **The command line, further.** A comparison written to a table file, motors compared on one device, and devices compared over a whole motion, as the page does.

## Not planned

- Topologies other than motor inverters.
- A built-in device database. You bring the datasheets.
- A simulation of the control loop. Currents and duty cycles from another simulator or a drive's log can be imported from the command line instead.

[LIMITS.md](LIMITS.md) lists what the present version leaves out.
