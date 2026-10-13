# Guide

How to use MotionSim in detail: the five steps of the page, installing it, reading datasheets, the command line, and how it works inside. The [README](../README.md) is the short version. [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) says why it is built this way.

## The five steps

Five steps on one page, with the power stage drawn on screen the whole time:

1. **The device.** Type in nine figures from a MOSFET, SiC or GaN transistor's datasheet (ratings, on-resistance, gate and output charge, thermal resistance), drop its datasheet (PDF) or a device file, or bring your own double-pulse measurements. A figure that cannot be right, such as an on-resistance in the wrong unit, is refused where it sits. Nothing is listed that you did not bring.
2. **The motor.** Seven kinds: permanent-magnet (magnets on, set into or buried in the rotor), reluctance, induction, brushless DC, brushed DC with a magnet or a series field, and stepper. The kinds that suit your device's voltage come first, and one is opened as the starting point. That is a template to begin from, picked by voltage and by how many switches the package holds; it is not a recommendation of a motor, which the application decides.
3. **The supply and the design point.** Voltage, speed, torque, switching frequency (up to 10 MHz, for GaN), devices in parallel. And the cooling: a heatsink at a temperature you know, a heatsink in air from its K/W figure, or no heatsink, with each part standing in the air or all of them soldered to one board, where they warm each other. On a heatsink you can say what lies under each package, grease or a pad, or give its case-to-heatsink figure where you have measured it; left alone it is worked out, with a range.
4. **The load.** Pick a kind (fan, compressor, robot joint, vehicle, washer drum, positioning axis, power tool) sized to your motor, or bring a mission profile as a CSV file. Each kind of motor is offered the loads it commonly drives (a reluctance motor a pump or a compressor); any load can be entered by its figures. Choose how the drive starts the motor.
5. **The results.**
   - A verdict with plain-language checks, and what the part needs around it. Where the temperature range crosses the rating the verdict is "undecided on this data", not a pass or a fail. It names the assumption that widens the range most (how the package is mounted, how its chips heat each other, or a missing transient curve) and what would settle it. So is a pass that rests on losses drawn beyond the datasheet's last point, when being as far off as they can be would undo it. A caution on the data means the operating point is outside what the datasheet gives, for a loss that matters there. A gate drive and a dead time you did not give are chosen, counted and stated, and the dead-time advice says what a firmware default of 500 ns would cost.
   - Conduction and switching loss, and junction temperature as a range where values are assumed.
   - Temperature through the whole motion, the motor current, and a rough indicator of life under thermal cycling: a generic model, named as one, which can be several times off.
   - A speed-torque map, in the motor's units or the load's.
   - **What to build**: the heatsink (sized to a default target of 100 °C, which you can change; it is a design assumption, not a rating), the DC-link capacitor and the ripple current it must carry, the gate drive, and the protection the design needs, on one sheet.
   - **What it can drive**: the question turned round. The torque the device holds at each speed, how that moves with switching frequency and heatsink temperature, and how much heavier your load could be.
   - Up to five devices, loads or motors compared side by side, or one setting (switching frequency, supply voltage, heatsink or air temperature, devices in parallel) tried at two to five values, each added as a column. The table gives each one's verdict, its margin to the junction limit running and held still, and every loss and temperature of the hottest switch position: the switch conducting, turning on and turning off, the diode, each junction's peak, average and swing, the case, and what the switching does to the link capacitor and the motor current. Losses too close to tell apart are marked level, and devices compared on unlike data are said to be.
   - A setup you can save to a file, and the whole result as a report: a PDF, or a Markdown file to keep or to hand to a coding agent.

An input that cannot work is refused with the reason and what to change. The equations behind every figure are one press away. What you enter is kept in your browser from one visit to the next; Reset, at the top right, clears it.

## Install and run

To read your own datasheets, run MotionSim on your own machine. There is no account, and nothing is sent to this project.

```
git clone https://github.com/yannickYamo/MotionSim.git
cd MotionSim
python -m venv .venv && . .venv/bin/activate
pip install .
motionsim serve
```

The page opens at `http://127.0.0.1:4310/`. It answers only requests from your own machine. It needs Python 3.11 or later.

The same install gives the `motionsim` command: `motionsim --help` lists what it does, and `motionsim design init` followed by `motionsim design run` takes a part from datasheet figures to a verdict without opening the page.

### Reading datasheets needs your own API key, and that is why it is local

Reading a datasheet PDF is done by a language model, and that is a paid call. MotionSim makes it from your machine, with your own Anthropic API key, straight to Anthropic. The project has no server of its own, keeps no key and sees none of your files.

```
export ANTHROPIC_API_KEY=your-key
motionsim serve
```

- The key is read from your environment each time the page starts. It is never written to disk, never sent to the page, and never leaves your machine except in the call to Anthropic.
- A datasheet takes a minute or two and costs about what a long chat message does. The page says so before it starts.
- What was read is saved beside the device model, value by value with its page number, so you can check it against the datasheet. Open "Check what was read" on any part.
- Without a key everything else works: a transistor typed in from its datasheet, device files, your own measurements, and the made-up parts.

Datasheets are their vendors' property. None is distributed here, and no device data ships with the project.

## From the command line

The README's example runs one operating point of a made-up module with no datasheet and no key.

With a datasheet of your own:

```
motionsim extract my_part.pdf -o my_part.observations.yaml
motionsim build my_part.observations.yaml -o my_part.device.yaml
motionsim serve --devices .
```

Or with a transistor typed in by hand, no key needed:

```
motionsim template device -o my_part.yaml      # fill in the figures from the datasheet
motionsim build my_part.yaml -o my_part.device.yaml
```

Everything the page does is also a command: `motionsim --help` lists them. To rank several parts on one motor from the command line:

```
motionsim propose a.device.yaml b.device.yaml --vdc 48 --motor examples/motor_robot_joint_pmsm.yaml \
    --fsw 20000 --tsink 50 --tdead 2e-7 --rpm 1000 --torque 1
```

A gate drive left open is chosen for each part, as on the page. `--parallel`, `--tmin` and `--tmotor` set devices in parallel, the shortest pulse and the winding temperature. In place of `--tsink`, cooling to air is `--tair` with `--rth-heatsink` (a heatsink's K/W), or with `--rth-ja` or `--no-heatsink` for none (add `--board-area` and `--copper` for parts soldered to one board). On a heatsink, `--interface pad` or `--rth-case-sink` says how the packages are mounted. A dead time left open is filled in, as on the page.

## One file for every step, and coding agents

Every step of the page can be run from one file, with no browser and no server:

```
motionsim design init --device my_part.yaml -o design.yaml   # a design sized to the part
motionsim design run design.yaml --md report.md              # fit, verdict, motion, what to build, what it can drive
motionsim design run design.yaml --json                      # the same, for a program to read
```

`my_part.yaml` is a device file, or the figures typed from a datasheet (`motionsim template device`). A design may name up to five devices, which are compared at the design point and through the motion, and several motors under `motors:`, which are compared on one inverter; `--csv table.csv` writes the comparison as a table. The exit status says how it went: 0 the part passes, 3 it does not (at the design point, or through the motion), 4 the data cannot decide (the temperature range crosses the rating), 2 the design cannot be run as written, with the reason and the figure at issue in the output.

`motionsim agent` prints a guide written for coding agents: the loop, the design file, what comes back, and what to do with a refusal. There is no service to host and nothing to register: an agent that can run a command can use the tool. [AGENTS.md](../AGENTS.md) points to it.

## How it works

![How MotionSim is put together: what you bring goes through a reader and checks into a device model; the engine takes that with your motor and load and gives the results](images/architecture.svg)

1. A language model copies the datasheet's tabulated values exactly as printed and says what each plot's axes mean. It produces no model values.
2. Deterministic code checks that every number appears on the page it was cited from (for a scanned datasheet the check is weaker, and the result says so), converts units, reads curve coordinates from the PDF's own drawing commands (or traces them when a figure is a picture), and checks each curve against the tables. What fails a check is set aside and shown.
3. The device model is built from what passed. Where a datasheet gives single points, the assumed shape is written into the model.
4. The engine averages conduction and switching loss over an output period and iterates until the junction temperatures agree with the losses. Motors are solved from their steady-state equations, and a motion is followed through the device's thermal network in time.

[docs/THERMAL_MODEL.md](THERMAL_MODEL.md) explains the thermal part. The page's "The equations" button shows all of it.
