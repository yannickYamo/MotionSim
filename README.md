# MotionSim

Bring a power transistor's datasheet, your motor and your load. See what the power stage loses, how hot it gets, and whether the part suits the job.

MotionSim is a local web page with a loss and temperature engine behind it. It works from any vendor's datasheet, shows the equations it uses, and says in every result what the data supports and what it leaves out.

**Status: early, and exploratory.** It has been checked against formulas, an independent numerical integration and one vendor's own simulator on one part (total loss 5 to 13% high). It has not been checked against a measured loss. [docs/VALIDATION.md](docs/VALIDATION.md) has the numbers; [docs/LIMITS.md](docs/LIMITS.md) says where it falls short.

## Who it is for

People with a motor to drive and a power stage to choose, who are not power-electronics specialists: hobbyists, and early-stage teams in robotics and similar fields.

## Why

Every semiconductor vendor has a loss calculator, and each one knows only that vendor's parts. Comparing an IGBT from one vendor with a MOSFET from another means building the models yourself, usually by typing a datasheet into a simulator by hand.

MotionSim starts from the datasheet itself, or from your own measurements. Each value in a device model records the page it came from, and each result says what it rests on.

## What you do with it

Five steps on one page, with the power stage drawn on screen the whole time:

1. **The device.** Drop its datasheet (PDF), a device file, or your own double-pulse measurements. Nothing is listed that you did not bring.
2. **The motor.** Seven kinds: permanent-magnet (magnets on, set into or buried in the rotor), reluctance, induction, brushless DC, brushed DC with a magnet or a series field, and stepper. The kinds that suit your device's voltage come first, and one is recommended.
3. **The supply and the design point.** Voltage, speed, torque, switching frequency, devices in parallel.
4. **The load.** Pick a kind (fan, compressor, robot joint, vehicle, washer drum, positioning axis, power tool) sized to your motor, or bring a mission profile as a CSV file. Choose how the drive starts the motor.
5. **The results.**
   - A verdict with plain-language checks, and what the part needs around it.
   - Conduction and switching loss, and junction temperature as a range where values are assumed.
   - Temperature through the whole motion, the motor current, and a life estimate under thermal cycling.
   - A speed-torque map, in the motor's units or the load's.
   - Starting values for gate resistors, dead time, modulation and heatsink.
   - Up to five devices, or up to five loads, compared side by side.
   - A report you can save as a PDF.

An input that cannot work is refused with the reason and what to change. The equations behind every figure are one press away.

## Install and run

MotionSim runs on your own machine. There is no hosted version and no account.

```
git clone <this repository>
cd MotionSim
python -m venv .venv && . .venv/bin/activate
pip install .
motionsim serve
```

The page opens at `http://127.0.0.1:4310/`. It answers only requests from your own machine.

### Reading datasheets needs your own API key, and that is why it is local

Reading a datasheet PDF is done by a language model, and that is a paid call. MotionSim makes it from your machine, with your own Anthropic API key, straight to Anthropic. The project has no server of its own, keeps no key and sees none of your files.

```
export ANTHROPIC_API_KEY=your-key
motionsim serve
```

- The key is read from your environment each time the page starts. It is never written to disk, never sent to the page, and never leaves your machine except in the call to Anthropic.
- A datasheet takes a minute or two and costs about what a long chat message does. The page says so before it starts.
- What was read is saved beside the device model, value by value with its page number, so you can check it against the datasheet. Open "Check what was read" on any part.
- Without a key everything else works: device files, your own measurements, and a made-up part to try the tool with.

Datasheets are their vendors' property. None is distributed here, and no device data ships with the project.

## Example

Without a datasheet or a key, from the command line:

```
motionsim simulate examples/synthetic_igbt_600v_30a.yaml --vdc 300 --irms 10 --m 0.9 --pf 0.85 --fsw 8000 --tsink 60
```

```
synthetic LINEAR-600V-30A (Si IGBT)
  switch   conduction    4.593 W
           turn-on       0.878 W
           turn-off      0.698 W
  diode    conduction    1.081 W
           recovery      0.282 W
  power-stage loss       45.19 W
  efficiency             98.18 %
  Tj switch  average      79.8 °C   peak   84.2 °C
  Tj diode   average      75.6 °C   peak   77.8 °C
  hottest junction        76.8 to 109.2 °C across the thermal assumptions
  data support        interpolated
```

With a datasheet of your own:

```
motionsim extract my_part.pdf -o my_part.observations.yaml
motionsim build my_part.observations.yaml -o my_part.device.yaml
motionsim serve --devices .
```

Everything the page does is also a command: `motionsim --help` lists them.

## How it works

1. A language model copies the datasheet's tabulated values exactly as printed and says what each plot's axes mean. It produces no model values.
2. Deterministic code checks that every number appears on the page it was cited from, converts units, reads curve coordinates from the PDF's own drawing commands (or traces them when a figure is a picture), and checks each curve against the tables. What fails a check is set aside and shown.
3. The device model is built from what passed. Where a datasheet gives single points, the assumed shape is written into the model.
4. The engine averages conduction and switching loss over an output period and iterates until the junction temperatures agree with the losses. Motors are solved from their steady-state equations, and a motion is followed through the device's thermal network in time.

[docs/THERMAL_MODEL.md](docs/THERMAL_MODEL.md) explains the thermal part. The page's "The equations" button shows all of it.

## Why it was built

Choosing a power semiconductor usually means trusting each vendor's calculator for that vendor's parts, or building a model by hand. This project asks whether the datasheet itself can be the model, with the tool stating how far that data supports a design decision.

## How it compares

| | Vendor web tools | General circuit simulators | MotionSim |
|---|---|---|---|
| Parts covered | One vendor's | Any, if you build the model | Any, from its datasheet |
| Model source | Not shown | Entered by hand | Recorded per value, with its page |
| Assumptions and gaps | Not shown | Not shown | Listed in each result |
| Accuracy | Calibrated on the vendor's own measurements | As good as your model | Unproven against measurement; a range where data is missing |
| Control loop, ripple, other topologies | Some | Yes | No: motor inverters, steady state at each instant |
| Lifetime | Vendor's own cycling data | With your own model | A generic model, named as such |

The vendors' tools and the circuit simulators are ahead on accuracy and breadth. What MotionSim adds is the path from any datasheet to a result, in the open.

## More

- [docs/VALIDATION.md](docs/VALIDATION.md): every check, including the ones that fail, and the datasheets the reader has been tried on.
- [docs/LIMITS.md](docs/LIMITS.md): what it does not do, in order of importance.
- [docs/THERMAL_MODEL.md](docs/THERMAL_MODEL.md): what a datasheet's thermal resistance means and how the rest is computed.
- [docs/ROADMAP.md](docs/ROADMAP.md): what is planned.

The models follow from published physics and handbook material properties. Device data comes only from datasheets you supply. No vendor's internal data or models are used.

## Author

MotionSim is designed and maintained by Yannick Maurice.

## Disclaimer

MotionSim is an exploratory engineering aid. Its results are estimates built from datasheet values, stated assumptions and simplified models, and they can be wrong.

Do not rely on it alone to design, size or approve hardware. Power electronics can start fires, destroy equipment and injure or kill. Check every result against the manufacturer's data, verify by measurement on real hardware, and follow the safety standards that apply to your product. The authors and contributors accept no responsibility for any design error, damage, injury or loss arising from use of this software. See [DISCLAIMER.md](DISCLAIMER.md).

## Licence

Apache-2.0, which provides the software as is, without warranty and without liability.
