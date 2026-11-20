# Guide

How to use MotionSim in detail: the five steps of the page, installing it, reading datasheets, the command line, and how it works inside. The [README](../README.md) is the short version. [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md) says why it is built this way.

## The five steps

Five steps on one page, with the power stage drawn on screen the whole time:

1. **The device.** Type in nine figures from a MOSFET, SiC or GaN transistor's datasheet (ratings, on-resistance, threshold and plateau voltage, gate-source and gate-drain charge, thermal resistance), drop its datasheet (PDF) or a device file, or bring your own double-pulse measurements. A figure that cannot be right, such as an on-resistance in the wrong unit, is refused where it sits. Nothing is listed that you did not bring.
2. **The motor.** Seven kinds: permanent-magnet (magnets on, set into or buried in the rotor), reluctance, induction, brushless DC, brushed DC with a magnet or a series field, and stepper. The kinds that suit your device's voltage come first, and one is opened as the starting point: the kind the drives of your part's class run, picked by its voltage, its current, its technology and how many switches the package holds, with a line under it that says why ("1200 V, 100 A IGBT module: industrial drives of this size run induction motors"). A 1200 V part of 50 A or more starts on a 4-pole industrial induction motor, a smaller one on a servo motor; a 600 to 900 V part on a permanent-magnet motor of a compressor or fan under about 10 A, of a servo from 10 to 100 A and of a traction drive above; a part of 200 V or less on a small brushless DC motor under about 10 A and a permanent-magnet motor of an e-bike, a robot or a power tool above; a two-leg package at low voltage on a brushed motor. The motor has the figures of a typical one of its class: its poles, its rated speed, which is the design point's, a back-EMF at that speed of 80% of what the inverter gives from the supply, and a current limit just inside the part's rating. It is a template to begin from, not a recommendation of a motor, which the application decides: the kind, and every figure, can be changed, and what you pick or type stays when another part is brought in.
3. **The supply and the design point.** Voltage, speed, torque, switching frequency (up to 10 MHz, for GaN), devices in parallel. And the cooling: a heatsink at a temperature you know, a heatsink in air from its K/W figure, or no heatsink, with each part standing in the air or all of them soldered to one board, where they warm each other. On a heatsink you can say what lies under each package, grease or a pad, or give its case-to-heatsink figure where you have measured it; left alone it is worked out, with a range. In the gate drive's fold, whose face says it ("edges ≤ 5 V/ns"), the edge speed limit says how fast an edge the gate resistors the tool chooses may allow: a motor on a cable, 5 V/ns (the default); a motor close to the drive, 20 V/ns; or no limit, as fast as the part allows, where the turn-off overshoot, a gate driver's peak current (a usual one for the kind where none is given) and the current the part's channel can carry hold the resistors up. A faster edge loses less in switching, and stresses the motor's insulation and bearings and radiates more. The results say where the limit set a resistor, and a limit above 5 V/ns adds a caution to check the motor's insulation rating and cable length. A gate resistor you type is used whatever the limit. On the command line it is `--edge-limit cable|close|none`, and in a design file `edge_limit` under `conditions`.
4. **The load.** Pick an application, each with a line saying what it is and how long it runs: a direct-drive washer's quick programme (wash, rinses and spin, about half an hour), a vacuum cleaner, a ceiling fan, a compressor that cycles on and off, a pump or fan, a conveyor, a vehicle's urban ride with a hill, the vehicle being the one its motor's power suits (a small cart, an e-bike, a scooter, a small car or a car), a robot joint, a positioning axis or a power tool. Each runs its own load and duty, with a start-up, and those held running are run until the junction is steady. A pump, a conveyor, a vehicle and the short cycles are sized to your motor; a washer, a vacuum, a ceiling fan and a compressor have a size of their own, and step 4 offers the motor such products usually have: pressed, it fills in the motor's figures and the design point you have not typed, and nothing you typed changes. Where your motor cannot run the application, it says why. Under the load, "Where these figures come from" gives the reason for each figure. Or bring a mission profile as a CSV file. Each kind of motor is offered the loads it commonly drives; any load can be entered by its figures, a duty's phases are listed with their repeats, and changing a stretch makes the motion those stretches alone. Choose how the drive starts the motor; an application picked brings its own start (a compressor's is sensorless). With a heatsink in air and no heat capacity given, a motion a few minutes long or longer takes the usual one for its K/W and says so.
5. **The results.** They open on the verdict in one line, then four tabs: Verdict, Losses, Motion and Limits. Under the tabs, the comparison.
   - **Verdict**: a verdict with plain-language checks, and what the part needs around it. Where the temperature range crosses the rating the verdict is "undecided on this data", not a pass or a fail. It names the assumption that widens the range most (how the package is mounted, how its chips heat each other, or a missing transient curve) and what would settle it. So is a pass that rests on losses drawn beyond the datasheet's last point, when being as far off as they can be would undo it. A caution on the data means the operating point is outside what the datasheet gives, for a loss that matters there. A gate drive and a dead time you did not give are chosen, counted and stated, and the dead-time advice says what a firmware default of 500 ns would cost.
   - **Losses**: conduction and switching loss, and junction temperature as a range where values are assumed. A range says which assumption most of it comes from.
   - **One switching event, zoomed in.** Under the chart of power lost in the switch, a press (or Enter) on a turn-on or turn-off spike opens that event through time: the gate voltage, the switch's voltage and current, and the power, for the turn-on and the turn-off side by side (one above the other on a phone). The wheel or a pinch zooms about the pointer, in proportion to how far it turns, once the pointer has rested on the plot for a moment (a page scrolled past it scrolls on); a drag pans, a double-click or 0 resets, + and − zoom by a fifth from the keyboard, and the time axis rescales from µs to ns. A press on a plot (or Enter, or its Voltage and Gate buttons) opens it full screen at its zoom, drawn at the screen's size, to zoom, pan and read the same way, with a crosshair that reads every trace; Export PDF there saves that plot at its zoom as a vector PDF for print, with its axes, a key of its traces, the figures read from the edge, the device, the operating point and what was assumed. Escape or Close goes back, keeping the zoom. Beside it: di/dt and dv/dt, the turn-on current peak from the other switch's recovery, the turn-off voltage peak and its overshoot over the supply, the ringing frequency, the rise and fall times and the energies, which are the chart's own. Every figure the tool had to assume is named on the plot ("Loop inductance assumed 20 nH (a TO-220 on a compact board): give yours") with a link to its box in Event detail: the loop, common-source and gate-loop inductances, the gate resistors and the driver's levels, a layout file, and an estimate of the loop's inductance from its length, width and layer spacing. A figure you give replaces the assumption. Where the edge speed limit chose a gate resistor, the line says so with a link to raise the limit, and a note above the edges gives the event's own dv/dt and says what set it: the limit, with how much faster the part could switch without it, or, where the edges are well under the limit, the gate charge and the loss model's energy. The traces are coloured with their axis and their peak: voltage in bone, current in lilac, the gate in teal, power in orange. Where the datasheet gives switching times, the event's own in the same test are set beside them.
   - Where the control bears on the part: the pulsed current rating checked at the drive's current limit where the motor gives one, and with room for a current loop's overshoot where it does not; for a sensorless start, the speed below which the rotor cannot be read through this device's dead time and voltage drop; and, where the motor's iron loss is given, the d-axis current that loses least in motor and power stage together. The control itself is not simulated: [LIMITS.md](LIMITS.md) says what that leaves out.
   - **Motion**: temperature through the whole motion, the speed, torque and motor current, in minutes for a long duty, with its phases named in bands behind each chart. Marked on them: the start-up's junction peak and its current ("start current 0.45 A for 3.5 s"), where each phase run until steady got steady ("steady after 11 min 4 s"), and the worst swing within one output period or one turn. A press on a chart opens it full screen to zoom, read with a crosshair and save as a PDF, as the switching event's plots. Under the charts, how the heatsink was followed and why: from cold for a motion long beside its time constant, or at its mean temperature for a short cycle. Then a rough indicator of life under thermal cycling, in years of the application's own use: a generic model, named as one, which can be several times off.
   - A speed-torque map, in the motor's units or the load's, on the Losses tab behind Show the map.
   - **Limits**, in two parts. **What to build**: the heatsink (sized to a default target of 100 °C, which you can change; it is a design assumption, not a rating), the DC-link capacitor and the ripple current it must carry, the gate drive, and the protection the design needs, on one sheet.
     **What it can drive**: the question turned round. The torque the device holds at each speed, how that moves with switching frequency and heatsink temperature, and how much heavier your load could be.
   - **The comparison**: one table, a column each, beside the design. **+ Add** sets one more beside it: another device (made-up, typed in or from a file), another load, this motor with a change, or one setting (switching frequency, supply voltage, heatsink or air temperature, devices in parallel) at two to five values. One kind is compared at a time, up to five columns; adding another kind asks first, since it clears the table. Each column's own menu edits it, makes a device the design, or removes it, with Undo for a few seconds. On a phone the table slides sideways under its first column. The table gives each one's verdict, its margin to the junction limit running and held still, and every loss and temperature of the hottest switch position: the switch conducting, turning on and turning off, the diode, each junction's peak, average and swing, the case, and what the switching does to the link capacitor and the motor current. Losses too close to tell apart are marked level, and devices compared on unlike data are said to be.
   - A setup you can save to a file, and the whole result as a report: a PDF, or a Markdown file to keep or to hand to a coding agent.

An input that cannot work is refused with the reason and what to change. The equations behind every figure are one press away. What you enter is kept in your browser from one visit to the next; Reset, at the top right, clears it.

## Install and run

To read your own datasheets, run MotionSim on your own machine. There is no account, and nothing is sent to this project.

```
git clone https://github.com/yannickYamo/MotionSim.git
cd MotionSim
python3 -m venv .venv && . .venv/bin/activate
pip install .                # the engine, the command line and the page
pip install ".[reader]"      # the same, with what it takes to read a datasheet PDF
motionsim serve
```

With [uv](https://docs.astral.sh/uv/) there is nothing to clone: `uvx --from git+https://github.com/yannickYamo/MotionSim motionsim serve`, and for the reader `uvx --from "motionsim[reader] @ git+https://github.com/yannickYamo/MotionSim" motionsim serve`.

The page opens at `http://127.0.0.1:4310/`. It answers only requests from your own machine. It needs Python 3.11 or later.

The same install gives the `motionsim` command: `motionsim --help` lists what it does, and `motionsim design init` followed by `motionsim design run` takes a part from datasheet figures to a verdict without opening the page.

### Reading datasheets needs your own model, and that is why it is local

Reading a datasheet PDF is done by a language model: a maker's, with your own key, or one you run yourself. MotionSim makes the call from your machine, straight to it. The project has no server of its own, keeps no key and sees none of your files.

```
pip install ".[reader]"
export ANTHROPIC_API_KEY=your-key
motionsim serve
```

- The key is read from your environment each time the page starts. It is never written to disk, never sent to the page, and never leaves your machine except in the call to the model.
- Other models read too:

  | Model | What to set |
  |---|---|
  | Anthropic (the one this tool was built and checked on) | `ANTHROPIC_API_KEY` |
  | OpenAI | `OPENAI_API_KEY` and `MOTIONSIM_LLM_MODEL` |
  | Google Gemini | `GEMINI_API_KEY` and `MOTIONSIM_LLM_MODEL` |
  | xAI Grok | `XAI_API_KEY` and `MOTIONSIM_LLM_MODEL` |
  | A model you host (Ollama, vLLM, llama.cpp, or any chat-completions service) | `MOTIONSIM_LLM_URL` and `MOTIONSIM_LLM_MODEL`, with `MOTIONSIM_LLM_KEY` if it wants one |

  `MOTIONSIM_LLM_MODEL` is the name the service knows the model by. The model has to read pictures, for figures and scanned pages, and to answer in a set form. The first of these that is set is used, a service of your own before any maker's key.

  ```
  export MOTIONSIM_LLM_URL=http://localhost:11434/v1      # a model on your own machine: nothing leaves it
  export MOTIONSIM_LLM_MODEL=the-name-of-your-model
  motionsim serve
  ```

  Whatever reads, the same checks hold every value to the page it was cited from, so a weaker reader has more set aside, not more believed. Only Anthropic's model has been run on real datasheets here: the others are held to the interface they share, by a test that stands in for the service.

- A datasheet takes a minute or two and costs about what a long chat message does. The page says so before it starts.
- What was read is saved beside the device model, value by value with its page number, so you can check it against the datasheet. Open "Check what was read" on any part.
- Without a key everything else works: a transistor typed in from its datasheet, device files, your own measurements, and the made-up parts.

Datasheets are their vendors' property. None is distributed here, and no device data ships with the project.

## From the command line

The README's example runs one operating point of a made-up module with no datasheet and no key: `motionsim simulate example --vdc 300 --irms 10 --m 0.9 --pf 0.85 --fsw 8000 --tsink 60`. The made-up parts are known by name wherever a device is asked for: `example` is a 600 V IGBT module, `example-mosfet` a 100 V MOSFET.

With a datasheet of your own (this needs the `reader` extra and a key):

```
motionsim extract my_part.pdf -o my_part.observations.yaml
motionsim build my_part.observations.yaml -o my_part.device.yaml
motionsim serve --devices .
```

Or with a transistor typed in by hand, no key needed:

```
motionsim template device -o my_part.yaml      # fill in the figures from the datasheet (template igbt for an IGBT)
motionsim build my_part.yaml -o my_part.device.yaml
```

Everything the page does is also a command: `motionsim --help` lists them. To rank several parts on one motor from the command line:

```
motionsim propose a.device.yaml b.device.yaml --vdc 48 --motor motor.yaml \
    --fsw 20000 --tsink 50 --tdead 2e-7 --rpm 1000 --torque 1
```

`motor.yaml` is a motor's catalogue figures (`motionsim template pmsm -o motor.yaml` writes one to fill in; `motionsim examples` lists the made-up motors, loads and parts that come with the tool, and any command takes one by its bare name, such as `--motor motor_robot_joint_pmsm.yaml`). A gate drive left open is chosen for each part, as on the page. `--parallel`, `--tmin` and `--tmotor` set devices in parallel, the shortest pulse and the winding temperature. In place of `--tsink`, cooling to air is `--tair` with `--rth-heatsink` (a heatsink's K/W), or with `--rth-ja` or `--no-heatsink` for none (add `--board-area` and `--copper` for parts soldered to one board). On a heatsink, `--interface pad` or `--rth-case-sink` says how the packages are mounted. A dead time left open is filled in, as on the page.

## One file for every step, and coding agents

Every step of the page can be run from one file, with no browser and no server:

```
motionsim design init --device my_part.yaml -o design.yaml   # a design sized to the part
motionsim design run design.yaml --md report.md              # fit, verdict, motion, what to build, what it can drive
motionsim design run design.yaml --json                      # the same, for a program to read
```

`my_part.yaml` is a device file, or the figures typed from a datasheet (`motionsim template device`). A design may name up to five devices, which are compared at the design point and through the motion, and several motors under `motors:`, which are compared on one inverter; `--csv table.csv` writes the comparison as a table. The exit status says how it went: 0 the part passes, 3 it does not (at the design point, or through the motion), 4 the data cannot decide (the temperature range crosses the rating), 2 the design cannot be run as written, with the reason and the figure at issue in the output.

The switching event of a design's hottest switch, as the page zooms into it, is `motionsim event design.yaml` (`--layout layout.yaml` for the board's figures, from `motionsim template layout`; `--csv` for both edges through time; `--json`).

`motionsim agent` prints a guide written for coding agents: the loop, the design file, what comes back, and what to do with a refusal. There is no service to host and nothing to register: an agent that can run a command can use the tool. [AGENTS.md](../AGENTS.md) points to it.

## How it works

![How MotionSim is put together: what you bring goes through a reader and checks into a device model; the engine takes that with your motor and load and gives the results](images/architecture.svg)

1. A language model copies the datasheet's tabulated values exactly as printed and says what each plot's axes mean. It produces no model values.
2. Deterministic code checks that every number appears on the page it was cited from (for a scanned datasheet the check is weaker, and the result says so), converts units, reads curve coordinates from the PDF's own drawing commands (or traces them when a figure is a picture), and checks each curve against the tables. What fails a check is set aside and shown.
3. The device model is built from what passed. Where a datasheet gives single points, the assumed shape is written into the model.
4. The engine averages conduction and switching loss over an output period and iterates until the junction temperatures agree with the losses. Motors are solved from their steady-state equations, and a motion is followed through the device's thermal network in time.

[docs/THERMAL_MODEL.md](THERMAL_MODEL.md) explains the thermal part. The page's "The equations" button shows all of it.
