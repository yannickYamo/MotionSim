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

- Motors are solved from steady-state equations at each instant. There is no control loop.
- Iron loss and saturation are modelled only if you give them: a no-load loss at a speed, split evenly between its two kinds and taken at full flux; and one saturation current for both axes. Without them the result says they are left out.
- Current ripple at the switching frequency is worked out where the motor's inductance is known. It adds to conduction loss and moves the current at the switching instants. The distortion dead time adds to the current at low speed is not modelled.
- Motor inverters only: no DC-DC, power-factor correction, three-level or soft-switching stages.
- Losses use each chip's average temperature over the output period.
- Measured switching energy follows the supply voltage along the datasheet's own figure where it has one. Without one it is scaled in proportion to voltage, which above the test voltage is the least a real device does; the result says how much more it could be. It follows your gate resistor only where the datasheet has a figure for that. Either figure, measured at one current, is applied at every current.
- Gate resistors chosen by the tool are totals. Where the datasheet gives the transistor's own gate resistance the choice is never below it; where it does not, a very small chosen value may not be reachable.
- Devices in parallel share as unevenly as the datasheet's maximum over typical allows, with the typical part among maximum ones carrying the most. That ignores how a hot transistor's rising resistance pushes current back to the others, so it is on the cautious side. Where the datasheet gives no maximum, sharing is taken as equal.
- An open-loop start is modelled by raising the current, not by simulating the controller.
- The usable voltage loses dead time, the shortest pulse you give, and the devices' drop at the peak current, taken at the heatsink temperature.
- A motor's working temperature is used only if you give it. The magnet coefficient is that of neodymium.
- The trip check assumes nothing shorts the motor or burns the energy. Short-circuit behaviour itself is not modelled: the withstand time is passed on where the datasheet gives it.
- Through time, heating between neighbouring chips and through the package-to-heatsink interface responds at once.

## 5. Life under thermal cycling is generic

The life estimate counts each chip's own temperature swings, those of every turn of the motor included, and uses a model fitted to modules with aluminium bond wires. It is applied to discrete parts too, which it was not fitted on. A real part may last several times longer or shorter. Use the manufacturer's power-cycling data where there is any.

## 6. The page

- The example motor keeps its size when it is wound for your device's voltage: on a large device it draws a small share of the rating until you enter your own motor.
- On a phone the drawing is wider than the screen and slides sideways.
- The report is laid out by your browser's print function.

## 7. Not yet

- Export of a device model to other simulators.
- A hosted version. The page needs a local install to read datasheets with your own key.
- The page can also be opened as plain files, with the engine running in the browser. In that mode the Python runtime is fetched once from cdn.jsdelivr.net; nothing you enter is sent anywhere. `motionsim serve` fetches nothing.
