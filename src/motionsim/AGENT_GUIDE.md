# Driving MotionSim from a terminal: a guide for coding agents

MotionSim estimates what a motor's power stage loses and how hot its transistors
run, from a datasheet-level description of the part, the motor and the load. Everything
the web page does can be done with these commands; nothing needs a browser, a server or
an account. Only reading a datasheet PDF needs an API key, and you do not need that:
type the part's figures in instead.

It is an exploratory tool. Its results are estimates, not measurements. When you report
them to a person, carry the cautions and the "what this rests on" section with them.

If the person has MotionSim open in the local app, connect to its MCP server instead
(`http://localhost:4310/mcp`, with the access code from Settings; see docs/MCP.md): you
then read and change the design their page shows, and they see and can undo each change.

## The loop

1. **Describe the part.** One of:
   - a made-up part to try things with, each opening on the application such a part is found in: `example-mosfet` (100 V, 100 A, a robot joint), `example` (600 V, 30 A IGBT module, a direct-drive washer), `example-mosfet-40v` (40 V, 120 A, a power tool), `example-mosfet-80v` (80 V, 80 A, drone propulsion at 50 000 rpm), `example-gan` (100 V GaN, a vacuum cleaner), `example-sic` (650 V SiC, an air-conditioner compressor) or `example-sic-module` (1200 V SiC half-bridge, a car on 800 V);
   - a device file the user already has (`*.device.yaml`);
   - a transistor typed from its datasheet: `motionsim template device -o part.yaml` (`template igbt` for an IGBT and its diode),
     fill in the figures (units are the datasheet's: mΩ, nC, pF, V, A, K/W), and name
     `part.yaml` under `devices`. A figure that cannot be right is refused with its name.
2. **Start a design.** `motionsim design init --device part.yaml -o design.yaml` writes a
   design sized to the part: the supply it suits, the kind of motor the drives of its class
   run (by its voltage, current, technology and package) wound for that supply, its rated
   point as the design point, and the usual load for that motor.
3. **Put in what you know.** Edit `design.yaml`: the motor's catalogue figures, the supply
   voltage, the hardest speed and torque, switching frequency, cooling, the load and its
   motion. Leave the gate drive out and it is chosen and stated.
4. **Run it.** `motionsim design run design.yaml --json` prints one JSON document;
   add `--md report.md` to also write the report in Markdown for a person.
5. **Read the outcome and the reasons, change the design, run again.**

## Exit status

Every command exits with one of these, and `motionsim --help` prints the same table:

```
{EXIT_STATUS}
```

What each means for `design run`, and what to read next:

- **0.** The part passes, with or without cautions. Read the cautions.
- **3.** No part passes, or the part followed passes at the design point and fails a check through the motion, or has no stable junction temperature in it. `verdict.candidates[].checks` and `motion.checks` say which check failed and why.
- **4.** Undecided: the estimate is under the rating and the top of its range is over it, so what the datasheet leaves out decides; or it passes as drawn on losses taken beyond the datasheet's last data point, and would not if they were as far off as they can be. `outcome` is `undecided`; the temperature check says what would narrow it. Do not treat it as a pass.
- **2.** The design cannot be run as written, in whole or in one step, and `outcome` is `refused` even where the steps that ran passed. The output has `refused` (why), `fix` (what to change) and `field` (which figure) at the top, for the first step refused, and `refusals` lists every such step by name; each of those steps holds its own three in its place. Also a file that cannot be read, or a report that cannot be written where it was asked for.
- **1.** A fault in the tool. Report it; do not work around it. `MOTIONSIM_TRACE=1` shows where it happened.

With `--json` the output is always one JSON document: the answer, or
`{"outcome": "refused", "refused": ..., "fix": ..., "field": ...}`, or
`{"outcome": "fault", "error": ...}`. Without it a refusal or a fault is one or two lines
on the error stream.

## The design file

```yaml
devices: [part.yaml]          # one to five; the first that passes is followed further
motor:                        # `motionsim template pmsm|bldc|induction|dc|stepper` for the figures of each kind
  type: pmsm
  pole_pairs: 7
  kv: 100                     # rpm/V; or kt in N·m per A rms (bldc and dc: kt in N·m/A, or kv)
  l: 0.00012                  # H, phase: half the line-to-line figure (bldc takes line to line)
  rs: 0.045                   # ohm, phase: half the line-to-line figure
  i_max: 40                   # A rms; leave out if unknown
conditions:
  v_dc: 48                    # V
  rpm: 2000                   # the hardest point the motor has to hold
  torque: 1.0                 # N·m
  f_sw: 20000                 # Hz
  parallel: 1                 # devices side by side at each switch
  cooling: held               # held | heatsink | none | board
  t_sink: 60                  # °C, with cooling: held
  # cooling: heatsink  ->  rth_sink (K/W, every device on it), t_ambient (°C)
  # on a heatsink, either cooling: interface (grease | pad, the layer under each package) and
  #   rth_case_sink (K/W case to heatsink of one package, where measured); left out, worked out
  # cooling: none      ->  rth_ja (K/W junction to air, one package), t_ambient
  # cooling: board     ->  rth_ja, board_area (cm²), copper (cm² a part), t_ambient
  # optional: v_drive, rg_on, rg_off (ohm), t_dead (s), l_loop (H), t_min_pulse (s),
  #   t_motor (°C, the winding's temperature), t_sink_max (°C, the most a heatsink sized may reach: 100),
  #   t_ambient (°C, the air a heatsink is sized for: 40),
  #   pwm: sine | third-harmonic | space-vector | discontinuous | discontinuous-high | discontinuous-low,
  #   edge_limit: cable (5 V/ns, the default) | close (20 V/ns) | none: how fast an edge chosen gate resistors allow
supply: one-way               # one-way (a power supply) | battery (takes braking energy back) | mains
# fed from the mains (supply: mains), the stage in front of the DC link is worked out first:
#   mains: {v: 230, f: 50, phases: 1}   # V rms (line to line on three phases), Hz, 1 or 3
#   front_end:                # optional: left out, the stage recommended is taken and named in the answer
#     topology: boost         # one phase: rectifier | boost | interleaved | totem_pole; three: six_pulse | vienna | active
#     f_sw: 65000             # Hz, the front end's own; feed_forward: off unties its control from the motor's
#   leave conditions.v_dc out and the link is the stage's (390 V from 230 V); given, it is the stage's set point
# optional, with a load and profile:
#   repeats: 1                # the motion run this many times back to back, 1 to 50
#   start:                    # how the drive starts the motor: left out, with a position sensor
#     method: open_loop       # sensor | injection | open_loop (sensorless, aligned then ramped)
#     current: 10             # A rms held through an open-loop start; handover_rpm, align_time (s)
#   c_link: 0.001             # F, the DC-link capacitance: what braking does to the link voltage
#   heatsink: {capacity: 500} # J/K, with cooling: heatsink: it is followed as it warms from the air's temperature
#   heatsink: {rth: 1.0, capacity: 500, t_ambient: 40}   # the same with cooling: held
load:                         # leave load and profile out to judge the design point alone
  gear_ratio: 50
  gear_efficiency: 0.85
  inertia: 0.54               # kg·m² at the load
  motor_inertia: 0.0001
  friction_coulomb: 2.5       # N·m
  gravity: {mass: 8.7, arm: 0.25}
profile:
  start_angle_deg: 0
  segments:                   # load speed in straight lines
    - {duration: 0.3, speed_start: 0, speed_end: 20}
    - {duration: 0.45, speed_start: 20, speed_end: 20}
```

`motor`, `load` and `profile` may each be the path of a file instead. A name the tool does
not know, in the design or in its conditions, is refused with the names it does know: a
mistyped name is never passed over. One to five devices.

To compare motors on one inverter, give `motors:` in place of `motor:`, a list of motors
(or of paths), and not both. The first is the one the rest of the design is about; each is
then run at the design point on the device that was followed.

## What comes back (`--json`)

| Key | What it holds |
|---|---|
| `outcome` | `passes`, `passes with cautions`, `undecided`, `does not pass`, or `refused` |
| `fit` | whether the motor fits the part before any design point: `level`, and `lines` with the reasons |
| `stage.stage` | what the motor asks of the power stage at the design point: `i_peak`, `p_shaft`, `p_electrical`; `stage.advice` says what kind of device to look for |
| `verdict.candidates[]` | for each device: `level` (ok, caution, fail), `result.loss`, `.conduction`, `.switching` (W), `.tj_peak` (°C), `margin` and `stall_tj`, `checks[]` (`level`, `topic`, `message`), `gate` (the gate drive used and why), `needs`, `switching` (what its switching loss rests on) |
| `verdict.explain` | the comparison in sentences, including ties and parts compared on unlike data |
| `followed` | the device the next three keys are about |
| `motion.summary` | over the load's motion: `mean_loss`, `peak` junction, energies, braking; `motion.checks[]` |
| `build.items[]` | what to build around the device: gate resistors, dead time, modulation, heatsink; each with `value` and `lines` |
| `motions` | with more than one device: each device through the same motion, by its name, as `motion` is |
| `motors[]` | with `motors:` given: for each, `i_peak`, `loss`, `tj_peak`, `margin`, `capacitor_rms`, `level`, or `refused` |
| `marks` | a short mark of the design as given and of each device file: the same marks mean the same inputs |
| `drive` | what the device can drive: `design` (torque it holds at the design speed and what stops it), `rpm` and `edge` across speed |

Any step that could not be run holds `refused`, `fix` and `field` in place of its answer,
and is named in `refusals` at the top.

## Questions and the command for each

| Question | Do this |
|---|---|
| Will this part do this job? | `design run`; read `outcome`, then every check that is not `ok` |
| Which of these parts is best? | list them all under `devices`; read `verdict.explain` and the margins, not only the lowest loss |
| What is the largest load this part can drive? | read `drive.design` and `drive.edge` |
| What does it need around it? | read `build.items` |
| What does the hottest junction do through the motion? | add `--traces` and read `motion.time`, `motion.tj` |
| Which motor on this inverter? | list them under `motors`; read `motors[]` |
| Which part over the whole duty, not one point? | list them under `devices` with a load and profile; read `motions` |
| The comparison in a spreadsheet? | `--csv table.csv`: a row a device, a row a motor |
| A setting swept (frequency, voltage, cooling)? | run the design once for each value; each run is independent |
| How fast does it switch, and how far does it overshoot and ring? | `motionsim event design.yaml --json` (`--layout` a file from `motionsim template layout`); read `turn_on`, `turn_off` and `assumed` |

Single questions also have their own commands (`motionsim --help`): `simulate`, `motor`,
`map`, `propose`, `compare`, `recommend`, `cycle`, `max-current`, `trajectory`, `advise`.
Each takes a device as a file or as a made-up part such as `example-mosfet` or `example`, checks its conditions as
a design's are checked, takes `--json`, and exits with the statuses above. `motionsim
examples` lists the made-up parts, motors, loads and motions that come with the tool, with
where they are; a command takes any of them by its bare name.

`max-current` gives the largest current that passes: the one at which the top of the hottest
junction's range, across the thermal assumptions and what a loss drawn past the data could
add, reaches the limit. The current at which the typical estimate alone would reach it is
printed beside it (`i_max_typical`); a point between the two is undecided. The limit is the
part's rating, or a lower one given with `--tj`; a heatsink at or above it is refused.

## Rules for an agent

- Do not invent a part's figures. If the user has not given a datasheet value, ask for it
  or say it is assumed; the template marks which are required.
- A refusal is information: fix the named figure and run again. Do not retry unchanged.
- A caution is part of the answer. Report it with the result.
- The tool has been compared with one measured loss only. Say "estimate".
