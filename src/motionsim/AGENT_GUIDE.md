# Driving MotionSim from a terminal: a guide for coding agents

MotionSim estimates what a three-phase motor inverter loses and how hot its transistors
run, from a datasheet-level description of the part, the motor and the load. Everything
the web page does can be done with these commands; nothing needs a browser, a server or
an account. Only reading a datasheet PDF needs an API key, and you do not need that:
type the part's figures in instead.

It is an exploratory tool. Its results are estimates, not measurements. When you report
them to a person, carry the cautions and the "what this rests on" section with them.

## The loop

1. **Describe the part.** One of:
   - a made-up part to try things with: `example-mosfet` (100 V, 100 A) or `example` (600 V, 30 A IGBT module);
   - a device file the user already has (`*.device.yaml`);
   - a transistor typed from its datasheet: `motionsim template device -o part.yaml`,
     fill in the figures (units are the datasheet's: mΩ, nC, pF, V, A, K/W), and name
     `part.yaml` under `devices`. A figure that cannot be right is refused with its name.
2. **Start a design.** `motionsim design init --device part.yaml -o design.yaml` writes a
   design sized to the part: the supply it suits, the usual kind of motor wound for that
   supply, a design point, and the usual load for that motor.
3. **Put in what you know.** Edit `design.yaml`: the motor's catalogue figures, the supply
   voltage, the hardest speed and torque, switching frequency, cooling, the load and its
   motion. Leave the gate drive out and it is chosen and stated.
4. **Run it.** `motionsim design run design.yaml --json` prints one JSON document;
   add `--md report.md` to also write the report in Markdown for a person.
5. **Read the outcome and the reasons, change the design, run again.**

## Exit status of `design run`

| Status | Meaning |
|---|---|
| 0 | The part passes, with or without cautions. Read the cautions. |
| 3 | No part passes. `verdict.candidates[].checks` say which check failed and why. |
| 2 | The design was refused: it cannot be run as written. The output has `refused` (why), `fix` (what to change) and `field` (which figure). |
| 1 | A fault in the tool. Report it; do not work around it. |

## The design file

```yaml
devices: [part.yaml]          # one to five; the first that passes is followed further
motor:                        # `motionsim template pmsm|bldc|induction|dc|stepper` for the figures of each kind
  type: pmsm
  pole_pairs: 7
  kv: 100                     # rpm/V
  l: 0.00012                  # H, phase
  rs: 0.045                   # ohm, phase
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
  # cooling: none      ->  rth_ja (K/W junction to air, one package), t_ambient
  # cooling: board     ->  rth_ja, board_area (cm²), copper (cm² a part), t_ambient
  # optional: pwm, v_drive, rg_on, rg_off (ohm), t_dead (s), l_loop (H), t_motor (°C)
supply: one-way               # one-way (a power supply) | battery (takes braking energy back)
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

`motor`, `load` and `profile` may each be the path of a file instead.

## What comes back (`--json`)

| Key | What it holds |
|---|---|
| `outcome` | `passes`, `passes with cautions`, `does not pass`, or `refused` |
| `fit` | whether the motor fits the part before any design point: `level`, and `lines` with the reasons |
| `stage` | what the motor asks of the power stage at the design point: `i_peak`, shaft and electrical power |
| `verdict.candidates[]` | for each device: `level` (ok, caution, fail), `result.loss`, `.conduction`, `.switching` (W), `.tj_peak` (°C), `margin` and `stall_tj`, `checks[]` (`level`, `topic`, `message`), `gate` (the gate drive used and why), `needs`, `switching` (what its switching loss rests on) |
| `verdict.explain` | the comparison in sentences, including ties and parts compared on unlike data |
| `followed` | the device the next three keys are about |
| `motion.summary` | over the load's motion: `mean_loss`, `peak` junction, energies, braking; `motion.checks[]` |
| `build.items[]` | what to build around the device: gate resistors, dead time, modulation, heatsink; each with `value` and `lines` |
| `drive` | what the device can drive: `design` (torque it holds at the design speed and what stops it), `rpm` and `edge` across speed |

Any step that could not be run holds `refused`, `fix` and `field` in place of its answer.

## Questions and the command for each

| Question | Do this |
|---|---|
| Will this part do this job? | `design run`; read `outcome`, then every check that is not `ok` |
| Which of these parts is best? | list them all under `devices`; read `verdict.explain` and the margins, not only the lowest loss |
| What is the largest load this part can drive? | read `drive.design` and `drive.edge` |
| What does it need around it? | read `build.items` |
| What does the hottest junction do through the motion? | add `--traces` and read `motion.time`, `motion.tj` |
| A setting swept (frequency, voltage, cooling)? | run the design once for each value; each run is independent |

Single questions also have their own commands (`motionsim --help`): `simulate`, `motor`,
`map`, `propose`, `compare`, `recommend`, `cycle`, `max-current`.

## Rules for an agent

- Do not invent a part's figures. If the user has not given a datasheet value, ask for it
  or say it is assumed; the template marks which are required.
- A refusal is information: fix the named figure and run again. Do not retry unchanged.
- A caution is part of the answer. Report it with the result.
- The tool has been compared with one measured loss only. Say "estimate".
