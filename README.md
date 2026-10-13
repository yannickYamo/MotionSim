# MotionSim

Bring a power transistor's datasheet, or nine figures typed from it, your motor and your load. See what the power stage loses, how hot it gets, and whether the part suits the job.

MotionSim is a web page with a loss and temperature engine behind it. It needs no vendor's model library: the device model is built from the part's own datasheet, whichever vendor's, where the datasheet gives enough ([docs/LIMITS.md](docs/LIMITS.md) says what the reader cannot read yet). It shows the equations it uses, and says in every result what the data supports and what it leaves out. It answers two questions: what power stage a load needs, and what load a device can drive.

Live page: https://yannickyamo.github.io/MotionSim/

No browser needed: the same five steps run from a terminal with one command, `motionsim design run design.yaml`, and a coding agent can drive it that way. See [docs/GUIDE.md](docs/GUIDE.md).

![The MotionSim page: the power stage drawn on the left with each switch's loss and temperature, the verdict and its checks on the right](docs/images/page.png)

The live page runs the engine in your browser. Type in a transistor from its datasheet, bring a device file, or try one of two made-up parts: a 100 V MOSFET and a 600 V IGBT. Nothing you enter leaves your browser. The first visit fetches about 20 MB. It does not read datasheet PDFs: that needs your own key and a local install, as below.

**Status: early, and exploratory.** It has been checked against formulas, an independent numerical integration and one vendor's own simulator on one part (total loss 5 to 12% high). Against the one measured inverter loss found in public, a 48 V reference design, it is 10 to 31% low on a measurement that includes the board's own resistance. [docs/VALIDATION.md](docs/VALIDATION.md) has the numbers; [docs/LIMITS.md](docs/LIMITS.md) says where it falls short.

## Who it is for

People with a motor to drive and a power stage to choose, who are not power-electronics specialists: hobbyists, and early-stage teams in robotics and similar fields.

## Why

Every semiconductor vendor has a loss calculator, and each one knows only that vendor's parts. It takes an operating point a specialist has to work out, and gives back one number with no word on what it rests on. Comparing an IGBT from one vendor with a MOSFET from another means building the models yourself, usually by typing a datasheet into a simulator by hand.

MotionSim starts from the datasheet itself, or from your own measurements. You give it a motor, a supply and a load, not a modulation index. Each value in a device model records the page it came from, and each result says what it rests on. Where the data cannot decide, it says so.

[docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md) goes through the problems it starts from, the decisions behind it and what each one costs.

## What you do with it

Five steps on one page, with the power stage drawn on screen the whole time:

1. **The device.** Type nine figures from a MOSFET, SiC or GaN transistor's datasheet, drop a datasheet or a device file (any supported part, IGBTs and modules included), or bring your own double-pulse measurements.
2. **The motor.** One of seven kinds, from its catalogue figures.
3. **The supply and the design point.** Voltage, speed, torque, switching frequency, and how the stage is cooled.
4. **The load.** A fan, a robot joint, a vehicle and others, sized to your motor, or a mission profile from a file.
5. **The results.** A verdict with plain-language checks, losses and junction temperatures, the temperature through the whole motion, what to build around the part, what the part can drive, and up to five parts, loads or motors side by side, or one setting tried at several values.

A part passes, with any cautions listed, is ruled out, or is "undecided on this data" where the datasheet leaves the answer open, with what would settle it. An input that cannot work is refused with the reason and what to change. The equations behind every figure are one press away.

![The first step: a transistor typed in from its datasheet figures, with the made-up parts and the device file drop beside it](docs/images/device.png)

![What to build: the device, the heatsink, the DC-link capacitor with its ripple current, the gate drive and the protection, on one sheet](docs/images/build.png)

[docs/GUIDE.md](docs/GUIDE.md) describes each step and every result in detail.

## Install and run

The live page needs no install. To read your own datasheets, or to work offline, run MotionSim on your own machine. There is no account, and nothing is sent to this project.

```
git clone https://github.com/yannickYamo/MotionSim.git
cd MotionSim
python -m venv .venv && . .venv/bin/activate
pip install .
motionsim serve
```

The page opens at `http://127.0.0.1:4310/`. It needs Python 3.11 or later.

Reading a datasheet PDF is done by a language model, and that is a paid call. It is made from your machine with your own Anthropic API key (`export ANTHROPIC_API_KEY=your-key`), straight to Anthropic: the project has no server, keeps no key and sees none of your files. Without a key everything else works. Datasheets are their vendors' property: none is distributed here, and no vendor's device data ships with the project.

## Example

Without a datasheet or a key, from the command line:

```
motionsim simulate examples/synthetic_igbt_600v_30a.yaml --vdc 300 --irms 10 --m 0.9 --pf 0.85 --fsw 8000 --tsink 60
```

```
synthetic LINEAR-600V-30A (Si IGBT)
  switch   conduction    4.595 W
           turn-on       0.881 W
           turn-off      0.701 W
  diode    conduction    1.080 W
           recovery      0.285 W
  power-stage loss       45.25 W
  efficiency             98.17 %
  Tj switch  average      80.9 °C   peak   85.3 °C
  Tj diode   average      76.9 °C   peak   79.0 °C
  T case                  64.5 °C
  margin to Tj max        45.4 °C
  hottest junction        76.9 to 104.6 °C across the thermal assumptions
    - heating between chips computed for a generic module, construction not given: 0.21 K/W (0.00 to 0.68) per watt in each other chip
  data support        interpolated
  not modelled
    - losses use each chip's average temperature over the output period
```

The margin is counted from the top of the range.

Everything the page does is also a command, one file runs every step (`motionsim design run design.yaml`), and the exit status carries the verdict, so a coding agent can drive it: `motionsim agent` prints the guide written for one, and [AGENTS.md](AGENTS.md) points to it. [docs/GUIDE.md](docs/GUIDE.md) has the commands.

## How it works

![How MotionSim is put together: what you bring goes through a reader and checks into a device model; the engine takes that with your motor and load and gives the results](docs/images/architecture.svg)

A language model copies the datasheet's values as printed and produces no model values. Deterministic code checks them, reads the curves and builds the device model, setting aside whatever fails a check. One engine averages conduction and switching loss over an output period and iterates until the junction temperatures agree with the losses; motors are solved from their steady-state equations, and a motion is followed through the thermal network in time. The page and the command line show what that engine gives and have no model of their own.

## How it compares

| | Vendor web tools | General circuit simulators | MotionSim |
|---|---|---|---|
| Parts covered | One vendor's | Any, if you build the model | Any vendor's, from its datasheet where it gives enough, or nine typed figures |
| Model source | Not shown | Entered by hand | Recorded per value, with its page |
| Assumptions and gaps | Not shown | Not shown | Listed in each result |
| Accuracy | Calibrated on the vendor's own measurements | As good as your model | One public measurement, 10 to 31% low with the board's resistance in it; a range where data is missing |
| Control loop, other topologies | Some | Yes | No: motor inverters, steady state at each instant, with ripple at the switching frequency worked out from the switching sequence |
| Both directions | The load is given | The load is given | What a load needs, and what a device can drive |
| Comparing parts | Within one vendor | Any, model by model | Any vendors, with each part's test conditions beside it and a tie called a tie |
| Lifetime | Vendor's own cycling data | With your own model | A generic model, named as such |

The vendors' tools and the circuit simulators are ahead on accuracy and breadth. What MotionSim adds is the path from a datasheet to a result, in the open.

## More

- [docs/GUIDE.md](docs/GUIDE.md): every step, every result, the command line and coding agents.
- [docs/DESIGN_DECISIONS.md](docs/DESIGN_DECISIONS.md): the problems it starts from, the decisions and their trade-offs.
- [docs/THERMAL_MODEL.md](docs/THERMAL_MODEL.md): what a datasheet's thermal resistance means and how the rest is computed.
- [docs/VALIDATION.md](docs/VALIDATION.md): every check, including the ones that fail, and the datasheets the reader has been tried on.
- [docs/LIMITS.md](docs/LIMITS.md): what it does not do, in order of importance.
- [docs/ROADMAP.md](docs/ROADMAP.md): what is planned.

To work on the code: `pip install -e ".[dev]"`, then `pytest`; [AGENTS.md](AGENTS.md) has the rest.

The models follow from published physics and handbook material properties. Device data comes only from datasheets you supply. No vendor's internal data or models are used.

## Author

MotionSim is designed and maintained by Yannick Maurice.

## Disclaimer

MotionSim is an exploratory engineering aid. Its results are estimates built from datasheet values, stated assumptions and simplified models, and they can be wrong.

Do not rely on it alone to design, size or approve hardware. Power electronics can start fires, destroy equipment and injure or kill. Check every result against the manufacturer's data, verify by measurement on real hardware, and follow the safety standards that apply to your product. The authors and contributors accept no responsibility for any design error, damage, injury or loss arising from use of this software. See [DISCLAIMER.md](DISCLAIMER.md).

## Licence

Apache-2.0, which provides the software as is, without warranty and without liability.
