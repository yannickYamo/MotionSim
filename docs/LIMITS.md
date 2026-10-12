# Limits

What MotionSim does not do, or does only roughly, in order of how much it matters. Read this before trusting a result.

## 1. One measured loss behind it, and it does not settle much

The loss and temperature model is checked against closed-form solutions and an independent numerical integration, and against one vendor's simulator on one part. It has been compared with one loss measured on hardware, a published 48 V reference design: 10 to 31% below a measurement that includes the board's own resistance, with the switching estimate from charge 30% low at low current and 30% high at high current. No junction temperature has been compared with a measured one. Treat every result as an estimate to be confirmed on the bench.

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

## 7. A part typed in by hand, and cooling by air

- A typed part is a transistor only (silicon, SiC or GaN), one to a package. Its switching loss is estimated from its charges, never measured energy; its output charge is one figure carried to other voltages as a junction's charge goes; its thermal path is one resistance with no response in time. An IGBT or a module still needs its datasheet read, or a device file.
- The figures are checked for slips, not for truth: nothing compares them with the datasheet.
- A dead time left open is what a drive with that gate drive would be set to at the least: the turn-off time from the charges, a tenth longer for a hot part, 50 ns for the two gate-driver channels not answering together (10 ns for GaN), a margin of 1.2, and no shorter than 100 ns (20 ns for GaN). Firmware is often left at 300 to 800 ns; the advice says what 500 ns would cost, and the result uses yours when you give it. How much of the dead time the body diode really conducts for is not modelled: all of it is counted.
- A heatsink in air is one thermal resistance carrying the whole stage's loss. With devices in parallel the loss is counted as if each lost what the hardest-worked one does, which errs warm.
- With no heatsink and each part standing in the air, each package has one figure from junction to air and feels nothing of its neighbours. Where no figure is given, 62 K/W is used for a TO-220, 40 for a TO-247 and 43 for a TO-263 on a square inch of copper.
- With the parts soldered to one board, the datasheet's figure is brought to the copper each part has, along the curve datasheets print for the TO-263 and the DPAK (26.51 + 128/(1.69 + A), A in cm², as a ratio), and every watt the stage loses warms every part through the board's own path to still air, 10 W/(m²·K) from both faces. Left out: the number of copper layers and vias, which help by 20 K and more at half a watt a part; how close the parts are, where the inner ones run 3 to 20 K hotter; airflow, an enclosure, and heat leaving by the wires. The board is one temperature for the neighbours' share, which is on the warm side for a single-layer board. A check says when the board under a part passes 120 °C.
- Through a motion, a heatsink in air sits where the motion's mean loss puts it, and with no heatsink each package sits where its own mean loss puts it (at standstill, the loss of the rotor position that works it hardest), as if the motion repeated without end. The motion is then followed from the hottest package, so the others are shown a little warm. A heatsink given with its heat capacity is followed as it warms instead.
- The junction-to-air figure the heatsink advice gives for doing without a heatsink is worked out for a package alone in the air, running and held still; on a shared board it is the upper bound.

## 8. Comparing parts from different datasheets

- Each part's switching energy was measured by its own vendor, on that vendor's fixture, at its own gate resistor, gate voltage and test voltage. The comparison shows those conditions beside each part and says when one part's figure is measured and another's is estimated from charge, or when one is brought in proportion to a higher voltage than it was measured at. It cannot remove the difference.
- Losses within 5% of each other are marked level: the model does not tell them apart. There is no range on loss beyond that.
- A caution on the data is raised when the operating point is outside what the datasheet gives for a loss term, and that could move the stage's loss by 5% or more: the term's share of the loss, times how much of the term is in doubt. A table measured at one temperature is taken to drift by up to 0.5% a kelvin away from it. Below that the note is still listed and the verdict does not change.
- Table points with an assumed shape between them, and switching loss estimated from charge, are stated under data support and are not a caution by themselves.

## 9. Not yet

- Export of a device model to other simulators.
- Reading a datasheet on the hosted page. That needs your own key and a local install.
- The page can also be opened as plain files, with the engine running in the browser. In that mode the Python runtime is fetched once from cdn.jsdelivr.net; nothing you enter is sent anywhere. `motionsim serve` fetches nothing.
