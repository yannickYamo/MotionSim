# MotionSim

[![ci](https://github.com/yannickYamo/MotionSim/actions/workflows/ci.yml/badge.svg)](https://github.com/yannickYamo/MotionSim/actions/workflows/ci.yml)

Compare any power transistor, from any maker, against your own motor and load, and take an answer into the design review that you can defend: what the part loses, how hot it runs, and what that rests on. Where the datasheet cannot settle the question, MotionSim tells you what to measure instead of guessing.

Choosing a part at the start of a design should take minutes, not a week.

Live page: https://yannickyamo.github.io/MotionSim/

**Try it in the browser, then bring your own parts.** The live page comes with seven made-up parts, each opening on the application such a part is found in, from a robot joint to an electric car. There is nothing to install and no key to give. To run MotionSim on your own datasheets, start it on your own machine with one command and give it an API key for a model you choose: Anthropic, OpenAI, Gemini, Grok, or one you host. The project ships no key and runs no server, so the call goes from your machine to your model and nowhere else. The local page also has what the live page cannot: the control lab, and a reader for your board's own design file. [How to set it up](#bringing-your-part-and-where-a-language-model-comes-in).

The device model is built from the part's own datasheet, so there is no vendor library to wait for, and an IGBT from one maker sits beside a GaN transistor from another on the same terms. Every value records the page it came from, the equations are on show, and every result says what the data supports and what it leaves out. It works in both directions: the power stage a load needs, or the load a part can drive. [docs/LIMITS.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/LIMITS.md) says what it cannot read yet.

No browser needed: the same five steps run from a terminal with one command, `motionsim design run design.yaml`, and a coding agent can drive it that way. See [docs/GUIDE.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/GUIDE.md).

![The MotionSim page for a 650 V SiC MOSFET driving a compressor from the mains: the front end and the inverter drawn on the left with each switch's loss and temperature; on the right the verdict in one word, then loss, hottest junction and load margin](https://raw.githubusercontent.com/yannickYamo/MotionSim/main/docs/images/page.png)

The live page runs the engine in your browser. Pick one of the seven made-up parts below, type in a transistor's figures from its datasheet, or bring a device file. Nothing you enter leaves your browser. The first visit fetches about 26 MB (the Python runtime and its numerical libraries, 39 MB once unpacked); later visits use the browser's copy.

### Seven parts to try

None of them is a real part: the figures are made up to be what a part of that kind would print. Each opens on its own application, with the motor and the supply such products have, and runs it from start-up to thermal steady state.

| Made-up part | Opens on | What it shows |
|---|---|---|
| 100 V silicon MOSFET | A robot joint on 48 V, lifting and lowering a load | Short current peaks, and the energy the joint returns as it lowers what it lifted |
| 600 V IGBT module | A direct-drive washing machine on rectified mains | The slow tumble that strains the junction most, and the energy the spin returns as it stops |
| 40 V silicon MOSFET | A cordless power tool on a battery | A hard start, and the current a bind draws as it slows the motor |
| 100 V GaN transistor | A vacuum cleaner at 100 000 rpm on a battery | Fast switching against an electrical frequency above 1 kHz |
| 80 V silicon MOSFET | A drone's propeller motor at 50 000 rpm on a 12-cell battery | Under 30 switching periods a turn, and a propeller whose torque rises with the square of its speed |
| 650 V SiC MOSFET | An air-conditioner compressor on rectified mains | A torque pulse every turn, strongest at low speed |
| 1200 V SiC half-bridge module | An electric car on an 800 V battery | A town ride with a hill, and the energy braking puts back in the battery |

Change any figure and the answer follows. Pick another application or motor and the part is judged on that instead.

**Status: early, and exploratory.** It has been checked against formulas, an independent numerical integration and one vendor's own simulator on one part (total loss 5 to 13% high). Against four reference designs their makers publish, it is low on loss (10 to 31% on a 48 V inverter whose measurement includes the board's own resistance, and lower on a six-step board) and runs hot on a board with no heatsink: with the datasheet's standard junction-to-air figure, the hottest case's rise comes out up to about twice the measured, and up to 3.8 times on one board at its highest currents. [docs/VALIDATION.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/VALIDATION.md) has the numbers; [docs/LIMITS.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/LIMITS.md) says where it falls short.

Losses are worked out from the datasheet's typical values, so a part at the edge of its spread loses more and runs hotter than the figure shown; where the datasheet prints a maximum on-state voltage the result says by how much, and a junction-to-case resistance is taken at its maximum where one is printed.

## One question, start to finish

*Can a 650 V SiC MOSFET run an air-conditioner compressor from a wall socket?* Here is that question on the page, with the made-up 650 V part. Every figure below is the tool's own, and the part is made up: bring yours and the same five steps answer for it.

**1. Pick the part.** It opens on the application such a part is found in: a six-pole compressor motor at 4200 rpm and 2.05 N·m, about 900 W at the shaft.

**2. Put it on the mains.** On step 3, press **AC mains**. MotionSim works out the stage between the socket and the DC link and recommends one, with the reason: here a totem-pole PFC, 16.6 W lost against 24.5 W for a boost stage, holding the link at 390 V. It also sees that the motor needs only 262 V at this point, and offers to hold 375 V and save 1.73 W.

![Step 3 with AC mains chosen: 230 V, one phase, a totem-pole PFC recommended with its loss and the reason, and the offer to hold a lower link](https://raw.githubusercontent.com/yannickYamo/MotionSim/main/docs/images/supply.png)

**3. Read the verdict.** Passes. The inverter loses 12.7 W, the hottest junction reaches 71 °C, 104 K under its rating, and the load could be 1.28 times heavier before the open-loop start becomes the limit. Seven checks stand behind the word, each one press away, and the front end's 16.6 W is counted on top.

**4. Follow it through an hour.** A compressor starts, pulls down, holds and stops, three times an hour. The Motion tab draws the junction through all of it, with the start marked and the heatsink beside it.

![The Motion tab: the junction temperature through an hour of three compressor runs, the start marked, against the heatsink](https://raw.githubusercontent.com/yannickYamo/MotionSim/main/docs/images/motion.png)

**5. Close the loop.** A compressor has no encoder, so the control lab starts on a back-EMF observer with an open-loop start, tunes every gain for this motor and load, and runs the loop switch by switch with the PFC stage holding the link. It passes: the link holds within 5.3 V, the current is 1.49 % off a sine, and two design actions are offered, the first a clamped modulation that takes the switching loss toward 6.4 W.

![The control lab: the scheme as a block diagram from the command to the motor, the mains and the PFC stage under it, the verdict of the run and the phase currents](https://raw.githubusercontent.com/yannickYamo/MotionSim/main/docs/images/control.png)

Change any figure, and every answer above follows.

## Who it is for

Motor-drive and power-electronics engineers who need an answer on their own part, motor and duty:

- **Will it survive?** Your part, your motor, your operating point and duty cycle; if not, what limits it and what to change.
- **Choose fast.** The part, the control scheme and the starting values, in one pass.
- **Compare.** Parts, motors and control schemes side by side.
- **Learn.** Every figure opens on its equation, its assumptions and its sources.

## Why

Every semiconductor vendor has a loss calculator, and each one knows only that vendor's parts. It takes an operating point a specialist has to work out, and gives back one number with no word on what it rests on. Comparing an IGBT from one vendor with a MOSFET from another means building the models yourself, usually by typing a datasheet into a simulator by hand.

MotionSim starts from the datasheet itself, or from your own measurements. You give it a motor, a supply and a load, not a modulation index. Each value in a device model records the page it came from, and each result says what it rests on. Where the data cannot decide, it says so.

[docs/DESIGN_DECISIONS.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/DESIGN_DECISIONS.md) goes through the problems it starts from, the decisions behind it and what each one costs.

## What you do with it

Five steps on one page, with the power stage drawn on screen the whole time:

1. **The device.** Type six figures from a MOSFET, SiC or GaN transistor's datasheet (an IGBT's from its first page and switching table), drop a datasheet or a device file (any supported part, IGBTs and modules included), or bring your own double-pulse measurements.
2. **The motor.** One of seven kinds, from its catalogue figures. It starts on the motor such a part usually drives, picked from the part's voltage, current, technology and package: a 1200 V, 100 A module starts on an induction motor, a 100 V, 2 A MOSFET on a small brushless one, each with a typical motor's real figures.
3. **The supply and the design point.** A power supply, a battery or the AC mains, then speed, torque, switching frequency, how fast the edges may switch, and how the stage is cooled. On the mains, one phase or three, the stage that makes the DC link is worked out too, from a plain rectifier to an active front end: one is recommended with its loss and the reason, and the others are a press away.
4. **The load.** An application, each run through its real duty from start-up to thermal steady state: a direct-drive washing machine, a vacuum cleaner, a ceiling fan, an air-conditioner compressor, a pump, a conveyor, a vehicle, a robot joint, a positioning axis or a power tool. Or a mission profile from a file.
5. **The results.** A verdict with plain-language checks, losses and junction temperatures, the temperature through the whole motion, one switching event zoomed in to nanoseconds, what to build around the part, what the part can drive, and up to five parts, loads or motors side by side, or one setting tried at several values.

A part passes, with any cautions listed, is ruled out, or is "undecided on this data" where the datasheet leaves the answer open, with what would settle it. An input that cannot work is refused with the reason and what to change. The equations behind every figure are one press away.

### Real applications, from start-up to steady state

A heatsink takes minutes to warm, so a few seconds of motion cannot tell you how hot a part runs. Each application runs its own duty for as long as it really lasts, with its own load physics, and says where every figure comes from:

| Application | What it runs | What it stresses |
|---|---|---|
| Washing machine, direct drive | a wash tumbling each way at 45 rpm, two rinses, a spin to 1400 rpm held 5 min: about 32 min on a 48-pole motor | each tumble reversal at a few hertz, where one switch carries the peak current for a long half-period |
| Vacuum cleaner | 80 000 rpm on a two-pole motor, run until steady, then a boost to 100 000 | the switching frequency against an electrical frequency of over 1 kHz |
| Ceiling fan | heavy blades brought up at the drive's current limit, then three speeds | seconds at the current limit to start |
| Air-conditioner compressor | a break-away and an open-loop start, a pull-down, a hold, and off, three times in an hour | a torque pulse every turn, strongest at low speed |
| Pump, conveyor | a soft or loaded start, then running until the junction is steady | the steady state itself |
| Vehicle | the class its motor's power suits, from a small cart to a car, on an 11-minute town ride with a hill and braking | the hill, and the energy braking returns to the supply |
| Robot joint, positioning axis, power tool | their short cycles, back to back for an hour | the peaks of each move |

The Motion tab draws the whole run in minutes with its phases named, marks the start-up's current and junction peak, says when each phase got steady, finds the worst swing of the junction, and gives the life that cycling leaves in years of the product's own use.

### One switching event, zoomed in

Press a spike on the chart of power lost in the switch and the turn-on and turn-off open through time, as an oscilloscope would show them: gate voltage, the switch's voltage and current, and power, with di/dt, dv/dt, the recovery current peak, the voltage overshoot and the ringing. They come from the datasheet's own figures through a model of the gate, the part's capacitances and the loop's inductance, matched to the energies the loss model counts. An IGBT's tail, a silicon MOSFET's recovery, a SiC MOSFET's fast edges and a GaN transistor's absent recovery each show as such parts do. Every figure assumed (loop inductance, gate resistors, driver levels) is named, with a box to give your own or a board layout to estimate it from. Each plot opens full screen to explore and save as a PDF.

On your own machine the event also takes the board's design file, as KiCad or IPC-2581. MotionSim finds the half bridge in its nets and works out the loop, common-source and gate inductance, the loop's resistance and the decoupling capacitance from the copper, each with the range it is believed in and what it rests on. [docs/BOARD.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/BOARD.md) has the method and its limits.

![A switching event zoomed in: the turn-on and turn-off of an IGBT through time, voltage, current, gate voltage and power, with the recovery peak and the turn-off overshoot marked](https://raw.githubusercontent.com/yannickYamo/MotionSim/main/docs/images/event.png)

### The control lab, on your own machine

Under the results, the whole control loop of the drive as a block diagram: sampling, the changes of frame, the regulators, the modulator, the stage and the motor. MotionSim picks a scheme for the design, tunes every gain by a stated rule, and simulates the closed loop in time, switch by switch. Press a block to read what it does and its mathematics. Run a test (hold the design point, step the torque or the speed, start from rest, step the load, stall). Change a gain and read what it costs the power stage: loss, ripple, junction temperature, set beside the settled result and the run before. Twenty-four schemes come ready, from the usual cascade to predictive control, a servo that rejects its load, a notch and input shaping for a shaft that twists, three observers with no encoder and active thermal control. Choosing another re-tunes every gain for your motor and load. A library of 32 explorations asks the questions worth a sweep. Where the drive is fed from the mains, the front end's own control runs on the same link, and both export as C.

What it is: a time-domain simulation of a permanent-magnet motor, a three-leg stage and a sampled controller, whose currents and commutations go to the same loss and thermal model as everything else here. A second view gives each loop's Bode plot, margins and poles; the switched run in time is the answer. What it is not: a tool to tune a real drive on, or a proof that your control will hold. The motor's iron saturates only where you ask it to, it has no cogging or back-EMF harmonics, only permanent-magnet motors are simulated, and nothing in it has been compared with a measured drive. The five steps above do not depend on it: they use the settled result, as before. [docs/CONTROL.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/CONTROL.md) has the model, block by block.

[docs/GUIDE.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/GUIDE.md) describes each step and every result in detail.

## Install and run

The live page needs no install. To read your own datasheets, to open the control lab, to read a board file or to work offline, run MotionSim on your own machine. There is no account, and nothing is sent to this project.

With Docker, one command from a clone, then open `http://127.0.0.1:4310/`:

```
git clone https://github.com/yannickYamo/MotionSim.git
cd MotionSim
docker compose up
```

The page is published to your machine alone, and what you bring and save stays in a volume.

With [uv](https://docs.astral.sh/uv/), one line and nothing to clone:

```
uvx --from git+https://github.com/yannickYamo/MotionSim motionsim serve
```

Or from a clone, with pip:

```
git clone https://github.com/yannickYamo/MotionSim.git
cd MotionSim
python3 -m venv .venv && . .venv/bin/activate
pip install ".[app,reader]"  # the engine, the command line, the page, its local app and the datasheet reader
motionsim serve
```

The page opens at `http://127.0.0.1:4310/`. It needs Python 3.11 or later, on Linux, macOS or Windows (there, `.venv\Scripts\activate`). `pip install .` alone gives the engine, the command line and the page on Python's own server; the `app` extra adds what keeps a key, schemes and runs on your machine, and `reader` what reads a datasheet PDF.

To read datasheets, set your model's key under **Settings** (the "⋯" menu at the top right of the page).

### Your coding agent, on the same design

The local app runs an MCP server at `http://localhost:4310/mcp`. Connect Claude Code (or any MCP client) with the access code shown under **Settings**, and the agent reads and changes the same design and control lab your page shows:

```
claude mcp add --transport http motionsim http://localhost:4310/mcp --header "Authorization: Bearer <code>"
```

Each change it makes shows on the page as it happens, in a quiet notice with **Undo**, and is listed in the agent's activity. See [docs/MCP.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/MCP.md).

### The control law on a microcontroller

The lab exports a scheme as C, proved against the simulation by a replay, and ports it to the chip you pick (STM32G4, STM32F4, C2000 F28004x and F2837x, MCX A, MCX N, i.MX RT1170, dsPIC33CK, SAM E70, RA6T2, ESP32-S3, RP2350, or any part you type). The peripheral code is written by your own language model with your key. The cross-compilers are optional, in a service of their own:

```
make firmware-token          # once: the token the page and the service share
docker compose --profile firmware up
```

With it, the port is compiled for the chip and its size and warnings are said. Without it, you get the source and its replay, in Docker too. The C2000 compiler and XC16 cannot be redistributed, so those ports are source only. A port is at best "compiles / not run on hardware". See [docs/EXPORT_C.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/EXPORT_C.md).

## Bringing your part, and where a language model comes in

Every kind of part simulates the same way once it is a device model: IGBT, silicon, SiC or GaN MOSFET, discrete or module. What differs is how the model gets made, and only one way needs a language model.

| Way to bring a part | On the live page | Needs a key | Parts it covers |
|---|---|---|---|
| A made-up part | Yes | No | Seven, from a 40 V MOSFET to a 1200 V SiC module, to see what the tool does |
| Figures typed from the datasheet | Yes | No | MOSFET, SiC and GaN transistors, and IGBTs with their diode |
| A device file (`.device.yaml`) | Yes | No | Any part: made once, kept, shared, dropped onto the page |
| A datasheet PDF, read for you | No: on your own machine | Yes, your own | Any supported part, IGBTs and modules included |

**Reading a PDF with your own model.** The reading is done by a language model: yours, with your own key, or one you run yourself. The call goes from your machine straight to it: the project has no server, keeps no key and sees none of your files. That is why the live page cannot do it. With a maker's model it is a paid call, about what a long chat message costs.

```
pip install ".[app,reader]"
motionsim serve                 # set the key under Settings, then drop the PDF onto the page
```

The key given under Settings is Anthropic's. It is kept in a file on your machine that only your account can read, and is never sent back to the page. A key in the environment (`export ANTHROPIC_API_KEY=your-key`, or any of the table below) works as before and comes first.

or from the terminal, which leaves you a device file you can also drop onto the live page:

```
motionsim extract my_part.pdf -o my_part.observations.yaml
motionsim build my_part.observations.yaml -o my_part.device.yaml
```

Typing the figures in works from the terminal too, and needs no key:

```
motionsim template device -o my_part.yaml      # a MOSFET, SiC or GaN transistor
motionsim template igbt -o my_igbt.yaml        # an IGBT and its diode, from the figures printed hot
motionsim build my_part.yaml -o my_part.device.yaml
```

A figure marked optional may be left out: the tool takes one by a stated rule, says so in the results, and holds the verdict at a caution until the datasheet's is given.

The model only copies what the datasheet prints; ordinary code checks every value against its page and builds the model. Open "Check what was read" on any part to see it value by value.

Any of these reads a datasheet:

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


**Driving it from your own coding agent.** This needs no key of ours and works with any agent that can run a command. `motionsim agent` prints a guide written for one: the design file, the one command that runs every step, what comes back and what each exit status means. [AGENTS.md](https://github.com/yannickYamo/MotionSim/blob/main/AGENTS.md) points to it.

Datasheets are their vendors' property: none is distributed here, and no vendor's device data ships with the project.

## Example

Without a datasheet, a key or a clone, from the command line. The made-up parts are `example-mosfet`, `example` (the 600 V IGBT module), `example-mosfet-40v`, `example-mosfet-80v`, `example-gan`, `example-sic` and `example-sic-module`; `motionsim examples` lists their files.

```
motionsim simulate example --vdc 300 --irms 10 --m 0.9 --pf 0.85 --fsw 8000 --tsink 60
```

```
made-up 600 V IGBT (Si IGBT)
  switch   conduction    4.602 W
           turn-on       0.888 W
           turn-off      0.708 W
  diode    conduction    1.079 W
           recovery      0.286 W
  power-stage loss       45.37 W
  efficiency             98.17 %
  Tj switch  average      80.9 °C   peak   85.4 °C
  Tj diode   average      76.9 °C   peak   79.1 °C
  T case                  64.5 °C
  margin to Tj max        45.3 °C
  hottest junction        76.9 to 104.7 °C across the thermal assumptions
    - heating between chips computed for a generic module, construction not given: 0.21 K/W (0.00 to 0.68) per watt in each other chip
  data support        interpolated
```

The margin is counted from the top of the range.

Everything the page does is also a command, one file runs every step (`motionsim design run design.yaml`), and the exit status carries the verdict, so a coding agent can drive it: `motionsim agent` prints the guide written for one, and [AGENTS.md](https://github.com/yannickYamo/MotionSim/blob/main/AGENTS.md) points to it. [docs/GUIDE.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/GUIDE.md) has the commands.

## How it works

![How MotionSim is put together: what you bring goes through a reader and checks into a device model; the engine takes that with your motor and load and gives the results](https://raw.githubusercontent.com/yannickYamo/MotionSim/main/docs/images/architecture.svg)

A language model copies the datasheet's values as printed and produces no model values. Deterministic code checks them, reads the curves and builds the device model, setting aside whatever fails a check. One engine averages conduction and switching loss over an output period and iterates until the junction temperatures agree with the losses; motors are solved from their steady-state equations, and a motion is followed through the thermal network in time. The page and the command line show what that engine gives and have no model of their own.

## For power-electronics and drives engineers

The same tool, in the terms you would use.

- **Device models.** IGBT, Si, SiC and GaN MOSFET, discrete or module. On-state from V_CE(I, T_j) or R_DS(on)(T_j) curves. Switching from E_on, E_off and E_rr against current and temperature, scaled with voltage, and E_on and E_off with gate resistance, along the datasheet's own figures where it has them; or, where only charges are given, from a gate-charge model through the Miller plateau with the Q_oss loss at hard turn-on; or, for a part with its gate drive built in that gives neither, from its rise and fall times. Double-pulse measurements replace the datasheet's switching energy. Thermal from Z_th(j-c) fitted as a Foster network; with no transient curve, a response computed from the package's copper and die heat capacity, as a low, typical and high range.
- **Loss engine.** Averaged over the output period for each switch and diode under sinusoidal, third-harmonic, space-vector and discontinuous PWM, block commutation and H-bridge drive. Dead-time and reverse conduction, recovery, and switching-frequency current ripple from the motor's inductance. Junction temperatures solved self-consistently with temperature-dependent loss, thermal runaway detected. Coupling between chips in a module and between packages on one board; case to heatsink as its own term.
- **Motors.** Steady-state dq models for surface, inset and interior PMSM with MTPA and field weakening; SynRM; induction under rotor-flux orientation; BLDC with 120° block commutation; brushed DC with a magnet or a series field; hybrid stepper with microstepping. Iron loss and saturation where given; magnet and copper temperature.
- **Switching transients.** A behavioural model of each edge: the gate charged through its resistance to the Miller plateau, a nonlinear output capacitance, the loop inductance ringing with it, the diode's recovery, an IGBT's tail current, each technology with its own shape. Calibrated to the loss model's energy at the operating point, and named indicative where it would have to be moved far to match. An edge speed limit (5 V/ns for a motor on a cable, 20 V/ns close to the drive, or none, held then by the driver's current and the part's channel) sets the gate resistors chosen.
- **Control.** In the five steps: the operating point field-oriented control settles to, not a simulated loop. Alignment and I/f start. The pulsed rating checked at the drive's current limit, or with an allowance for current-loop overshoot where none is given; the lowest sensorless speed from the dead-time and device-drop voltage error; a loss-minimising d-axis current with inverter loss included. Imported phase currents and duty cycles for anything a loop does beyond that.
- **Control lab** (local). A dq model of the PMSM integrated through each switching state of a triangular carrier, or averaged; a sampled controller of blocks with single or double update and one sample of delay; PI, discrete-time complex-vector, deadbeat, finite-control-set predictive and direct torque control; space-vector and discontinuous modulation with the clamp placed online; variable switching frequency; three sensorless observers with an I-f start; an active thermal supervisor. Loop transfer functions in z with margins and poles. Each switch's conduction intervals and commutations go to the loss engine. [docs/CONTROL.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/CONTROL.md).
- **Front end.** Seven stages between the mains and the DC link: a rectifier with a capacitor, boost, interleaved boost and totem-pole PFC on one phase; a six-pulse rectifier, a Vienna rectifier and an active front end on three. Each with its inductor, its capacitor's ripple, its loss in the same device model, and a control that holds the link and can take the motor's power as a feed-forward.
- **Board parasitics** (local). Partial inductances over a mesh of the board's copper from a KiCad or IPC-2581 file, the current shared for least magnetic energy, each figure with a band. [docs/BOARD.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/BOARD.md).
- **Motion and reliability.** Load models (inertia, friction, fan law, gravity, vehicle drag and slope, a tumbling drum, a compressor's pulse once a turn, a break-away at standstill) behind a gear; duties in named phases, with run-ups at the drive's current limit and stretches held until the junction moves less than 0.5 K a minute; the heatsink followed from cold over minutes, with a usual heat capacity for its K/W where none is given; the junction's swing within one output period at low speed; rainflow counting and a LESIT-based power-cycling estimate; braking energy into the DC link; DC-link capacitor ripple current.
- **Validation.** Closed-form loss integrals, an independent numerical integration, datasheet curves against their own tables, one vendor simulator, and four published reference designs: two measured stage losses and three boards' measured case temperature. [docs/VALIDATION.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/VALIDATION.md).

## How it compares

| | Vendor web tools | General circuit simulators | MotionSim |
|---|---|---|---|
| Parts covered | One vendor's | Any, if you build the model | Any vendor's, from its datasheet where it gives enough, or a few typed figures |
| Model source | Not shown | Entered by hand | Recorded per value, with its page |
| Assumptions and gaps | Not shown | Not shown | Listed in each result |
| Accuracy | Calibrated on the vendor's own measurements | As good as your model | Four published boards: loss low (10 to 31% on one, with the board's resistance in it), and on a bare board the case up to about twice as warm as measured with the standard junction-to-air figure; a range where data is missing |
| Control loop, other topologies | Some | Yes | Motor inverters, and the stage that feeds one from the mains. The five steps take the steady state at each instant, with ripple worked out from the switching sequence; the control lab, on your own machine, simulates the loop of a permanent-magnet motor from ready schemes of blocks |
| Both directions | The load is given | The load is given | What a load needs, and what a device can drive |
| Comparing parts | Within one vendor | Any, model by model | Any vendors, with each part's test conditions beside it and a tie called a tie |
| Lifetime | Vendor's own cycling data | With your own model | A generic model, named as such |

The vendors' tools and the circuit simulators are ahead on accuracy and breadth. What MotionSim adds is the path from a datasheet to a result, in the open.

## More

- [docs/GUIDE.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/GUIDE.md): every step, every result, the command line and coding agents.
- [docs/CASE_STUDY.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/CASE_STUDY.md): four real datasheets from four makers, from PDF to verdict, with what was refused and why.
- [docs/DESIGN_DECISIONS.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/DESIGN_DECISIONS.md): the problems it starts from, the decisions and their trade-offs.
- [docs/CONTROL.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/CONTROL.md): the control lab's model, its blocks, schemes and limits. [docs/CONTROL_RESEARCH.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/CONTROL_RESEARCH.md): the published work behind them.
- [docs/MCP.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/MCP.md): connecting a coding agent to the local app, its tools, and how its changes are undone.
- [docs/BOARD.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/BOARD.md): how a board file is read for its switching loop.
- [docs/THERMAL_MODEL.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/THERMAL_MODEL.md): what a datasheet's thermal resistance means and how the rest is computed.
- [docs/VALIDATION.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/VALIDATION.md): every check, including the ones that fail, and the datasheets the reader has been tried on.
- [docs/LIMITS.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/LIMITS.md): what it does not do, in order of importance.
- [docs/ROADMAP.md](https://github.com/yannickYamo/MotionSim/blob/main/docs/ROADMAP.md): what is planned.
- [CHANGELOG.md](https://github.com/yannickYamo/MotionSim/blob/main/CHANGELOG.md): what each version added. [SECURITY.md](https://github.com/yannickYamo/MotionSim/blob/main/SECURITY.md): what the tool handles of yours, and how to report a fault in it. [THIRD_PARTY.md](https://github.com/yannickYamo/MotionSim/blob/main/THIRD_PARTY.md): what it ships and loads that is not ours.

To work on the code, or to report a figure you think is wrong: [CONTRIBUTING.md](https://github.com/yannickYamo/MotionSim/blob/main/CONTRIBUTING.md). To cite it: [CITATION.cff](https://github.com/yannickYamo/MotionSim/blob/main/CITATION.cff).

The models follow from published physics and handbook material properties. Device data comes only from datasheets you supply. No vendor's internal data or models are used.

## Author

MotionSim is designed and maintained by Yannick Maurice.

## Disclaimer

MotionSim is an exploratory engineering aid. Its results are estimates built from datasheet values, stated assumptions and simplified models, and they can be wrong.

Do not rely on it alone to design, size or approve hardware. Power electronics can start fires, destroy equipment and injure or kill. Check every result against the manufacturer's data, verify by measurement on real hardware, and follow the safety standards that apply to your product. The authors and contributors accept no responsibility for any design error, damage, injury or loss arising from use of this software. See [DISCLAIMER.md](https://github.com/yannickYamo/MotionSim/blob/main/DISCLAIMER.md).

## Licence

Apache-2.0, which provides the software as is, without warranty and without liability.
