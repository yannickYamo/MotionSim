# Limits

What MotionSim does not do, or does only roughly, in order of how much it matters. Read this before trusting a result.

## 1. No measured loss behind it

The loss and temperature model is checked against closed-form solutions and an independent numerical integration, and against one vendor's simulator on one part. It has not been compared with a loss measured on hardware. Until it is, treat every result as an estimate to be confirmed on the bench.

## 2. Junction temperature inside a module is a range

A datasheet gives each chip's thermal resistance with that chip heated alone. How much the chips heat each other, and the transient response when no curve is given, are computed for a generic package of the stated construction. The result is shown as a range, often 30 °C wide, because the real layout is not known.

## 3. The datasheet reader misses things

- It uses a language model, and its output can differ between runs. Every value is checked against the page it was cited from; what fails is set aside and shown, never silently used.
- Quantities spread over several figures, and curves drawn against gate voltage, are not read.
- Scanned datasheets are read from page images: their tables only, not their figures, and the check on them is weaker.
- A datasheet that gives too little to model a device is refused with what is missing.

## 4. Simplifications in the model

- Motors are solved from steady-state equations at each instant. There is no control loop, no current ripple at the switching frequency, and no iron loss.
- Motor inverters only: no DC-DC, power-factor correction, three-level or soft-switching stages.
- Losses use each chip's average temperature over the output period.
- Measured switching energy is scaled in proportion to voltage. It follows your gate resistor only where the datasheet has a figure of energy against gate resistance, and that figure, measured at one current, is applied at every current.
- Gate resistors chosen by the tool are totals. A transistor's internal gate resistance is not read, so a very small chosen value may not be reachable.
- Devices in parallel are taken to share current equally. Real parts do not.
- An open-loop start is modelled by raising the current, not by simulating the controller.
- Through time, heating between neighbouring chips and through the package-to-heatsink interface responds at once.

## 5. Life under thermal cycling is generic

The life estimate uses a model fitted to modules with aluminium bond wires. A real part may last several times longer or shorter. Use the manufacturer's power-cycling data where there is any.

## 6. The page

- The example motor keeps its size when it is wound for your device's voltage: on a large device it draws a small share of the rating until you enter your own motor.
- On a phone the drawing is wider than the screen and slides sideways.
- The report is laid out by your browser's print function.

## 7. Not yet

- Export of a device model to other simulators.
- A hosted version. The page needs a local install to read datasheets with your own key.
