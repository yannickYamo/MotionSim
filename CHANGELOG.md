# Changelog

What each published version added for someone using the tool.

## 0.4.1

- A datasheet can be read with OpenAI, Gemini, Grok or a model you host, as well as Anthropic.
- The README says in one table how each kind of part is brought and where a language model comes in.

## 0.4.0

- The control is said as what it is: the operating point a field-oriented drive settles to. A part's pulsed current rating is checked at the drive's current limit; a sensorless start is told the speed the rotor can be read from with the part in use; where a motor's iron loss is given, the d-axis current that loses least is advised.
- A temperature range says which assumption the largest part of it comes from, and what would narrow it.
- A part whose datasheet gives no switching energy and no gate charges is modelled from its rise and fall times, and named as that estimate.
- The reader finds figures drawn with a grey grid and coloured curves, and recognises TO-252 and TOLL packages.
- The starting motor is made the size of the part under test.
- On the live page, the first step offers a made-up part, typed figures or a file; on a phone the verdict is said above the drawing.
- `motionsim trajectory` takes how the package is mounted; a design file says how the drive starts the motor.
- A case study on four real datasheets, a page on the design decisions and their costs, and a guide.

## 0.3.x

- The case-to-heatsink layer is part of the cooling and kept apart from the heating between chips; a pass that rests on losses beyond the datasheet's data is "undecided"; loads that come and go follow the package's own time constant.

## 0.3.0 and earlier

- From a datasheet, typed figures or measurements to losses, junction temperatures and a verdict, for seven kinds of motor, on a page and from the command line.
