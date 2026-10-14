# Case study: four datasheets from four makers, unnamed

What happens when MotionSim is given four real parts whose datasheets differ in what they give. Four public datasheets, one journey each from PDF to verdict, and what the tool could and could not say.

This is a demonstration of the method and not a ranking of makers, so neither the makers nor the part numbers are named: each part is called by a letter and described by what it is. No device data ships with the project: the datasheets are their makers' property, and what was read from them stays with whoever read them. The figures below are estimates, with the limits of [LIMITS.md](LIMITS.md).

## The parts

| Part | What it is |
|---|---|
| A | 200 V GaN transistor, 8 mΩ, chip-scale |
| B | 200 V silicon MOSFET, 5.5 mΩ, TOLL package |
| C | 650 V GaN transistor, 55 mΩ, gate interface built in |
| D | 600 V, 15 A IGBT module with drivers, six switches |

Two jobs, because no one voltage suits all four: a 96 V robot joint for the two 200 V parts, and a 310 V fan drive for the two 600 V-class parts.

## Step 1: from datasheet to model

Each PDF was read (`motionsim extract`), then built into a device model (`motionsim build`). Every table value was found on the page it was cited from; none was flagged.

| Part | Read | Built? |
|---|---|---|
| A | 15 table values, 7 curves | Yes |
| B | 22 table values, 6 curves; the thermal curve set aside | Not at first: refused, then built after one correction by a person |
| C | 16 table values, 3 curves | Yes, on its switching times, with its rise time entered by hand: it gives no switching energy and no gate charges |
| D | 8 table values, 6 switching-energy curves; 2 pages read from their image | Yes |

Two of the four are the useful part of this study: one that was refused until a person settled a definition, and one that gives so little about its switching that the model stands on a third, weaker footing and says so.

**The silicon MOSFET: a definition, not a misreading.** The build stopped with: *gate charge at threshold cannot exceed gate-source charge*. The values were read correctly: 25.5 nC at threshold and 4.3 nC gate to source. This datasheet gives the gate-source charge from the threshold on (its note and its figure of gate-charge definitions say so), where most give it from zero. The conventional figure is the sum, 29.8 nC. A person put that in the observations file, marked it verified, and the build went through. The tool did not guess which definition was meant; its refusal says what the figure probably is.

This datasheet's figures are pictures with a grey grid and coloured curves. On-resistance against temperature, output capacitance (within 0.1% of the table) and the body diode's voltage (within 0.3%) were read from them. The transient thermal curve was set aside: its axis limits matched only 71% of the grid lines drawn, so the model assumes the shape of the thermal response for its package, a TOLL, and every result says so.

**The GaN part with its gate interface built in: a third footing.** The datasheet gives no switching energy, and no gate-source or gate-drain charge, because the gate the user drives is not the transistor's own. A conduction-only answer would have looked like a result and been wrong by the whole switching loss. What the datasheet does give is its rise and fall times (7 ns each at 400 V and 10 A) and its output charge. From those the tool estimates the energy of each switching event: half the voltage times the current for as long as they cross, and the output charge taken through the full voltage at turn-on. The result calls this what it is, *estimated from the datasheet's rise and fall times*, never measured, and a gate resistor does not move it. A datasheet with none of the three is refused, with what a model would need.

## Step 2: a 96 V robot joint, GaN against silicon

One design file, both parts: a surface-magnet motor (7 pole pairs, 50 rpm/V, 0.48 mH, 0.18 Ω, 20 A rms limit), 96 V, 2000 rpm and 3 N·m at the design point, a 50:1 joint lifting 26 kg on a 0.25 m arm, on a heatsink held at 60 °C. Gate drive and dead time left open, so the tool chose them for each part.

| | A (GaN) | B (Si) |
|---|---|---|
| **At 20 kHz** | | |
| Verdict | passes | passes |
| Power-stage loss | 6.1 W | 9.9 W |
| of which conduction / switching | 3.9 / 2.3 W | 3.2 / 6.7 W |
| Margin to the junction limit | 89 °C | 112 °C |
| **At 100 kHz** | | |
| Power-stage loss | 16.2 W | 37.8 W |
| of which conduction / switching | 4.8 / 11.4 W | 4.3 / 33.5 W |
| Margin to the junction limit | 88 °C | 104 °C |
| **Chosen for each part** | | |
| Gate resistors, on / off | 27 / 20 Ω at 5 V | 22 / 27 Ω at 10 V |
| Dead time | 87 ns | 240 ns |
| **If started without a sensor** | | |
| Back-EMF readable from about | 104 rpm | 197 rpm |

What the tool says, and what it does not:

- **The GaN part loses less at both frequencies**, by 3.7 W at 20 kHz and 22 W at 100 kHz. The silicon part conducts better and switches worse.
- **The silicon part has more margin and headroom**: 23 °C more margin to its junction limit, and a 151 A rating against 32 A for a design that peaks at 18 A. The comparison says both, and does not fold them into one score.
- **Both switching figures are estimates from gate and output charge**, not measured energy, and the result says so for each. They are like for like, and rough: the first public measurement this estimate was held to came out 30% off in either direction ([VALIDATION.md](VALIDATION.md)).
- **The gate resistors are set by a 5 V/ns limit on voltage slew**, a common figure for a motor's insulation. That holds back the faster part. A design that allows more would move this comparison, and the result names the limit that set each value.
- **A curve the reader gets is worth a fifth of the conduction loss here.** The silicon part's on-resistance rises with temperature, and its figure for that was read. With the 25 °C table value alone its conduction would come out at 2.6 W in place of 3.2 W, and the tool would raise a caution on the data for it, as it does for any part whose datasheet gives one temperature only.
- **The transistor shows in the control.** Left without correction for dead time, a sensorless drive can read the rotor from about 104 rpm with the GaN part and 197 rpm with the silicon one, because the chosen dead times differ. An estimate, and stated as one.

Through the joint's own motion the two differ less than at the design point: 2.1 W against 5.1 W of mean loss, with the junction within two degrees of the heatsink in both.

## Step 3: a 310 V fan drive, a module against a transistor

The tool's own starting motor for the module, sized so that the motor's current limit sits just inside the module's 15 A rating: 2000 rpm and 2 N·m at the design point, 310 V, a heatsink held at 60 °C.

| | D (IGBT module) | C (GaN) |
|---|---|---|
| Switching loss rests on | measured energy, from the datasheet's curves | an estimate from rise and fall times |
| **At 6 kHz** | | |
| Power-stage loss | 9.5 W | 1.5 W |
| Hottest junction | 71 °C (65 to 83 °C) | 60 °C |
| **At 16 kHz** | | |
| Power-stage loss | 15.7 W | 2.2 W |
| Hottest junction | 79 °C (69 to 99 °C) | 61 °C |
| Margin to the junction limit | 51 °C | 89 °C |
| Gate drive | inside the module | its own interface; six parts and six driver channels |

- **The comparison says it rests on unlike data**, in those words: one part's switching loss is measured and the other's is estimated from two printed times taken in a clean test at 10 A. The six- to sevenfold difference in loss is the direction to expect of the two technologies and not a figure to design on.
- **The module's junction temperature is a range, and the range says where it comes from.** A module's chips share copper and warm each other; the datasheet does not say by how much. The tool computes it for a generic module and reports 69 to 99 °C at 16 kHz, the largest part of it from the heating between chips. The maker's figure would narrow it.
- **What each needs around it is listed and not scored.** The module has its drivers inside; the transistor needs six packages and a driver channel each.
- **At 6 kHz both carry a caution on ripple**: the motor current's ripple is a large share of its peak, and the tool says the motor wants a higher switching frequency or a series inductor. At 16 kHz that caution is gone.

## What this shows

- **A thin datasheet does not get a confident answer.** One part was refused until a person settled a definition, one stands on an estimate from two printed times and is said to, one had a curve set aside for failing its axis check, one gives a range. None was given a number it had no right to.
- **The tool's differences from a calculator are visible on real parts**: the page each value came from, a refusal that says what is missing, a caution only where the gap matters, and a comparison that keeps loss, margin and data support apart.
- **Where it fell short**: one thermal curve could not be confirmed against its own grid and was left out, so that model assumes a shape its datasheet draws; one rise time printed in a table was entered by hand; and three of the four switching figures are estimates, not measured energy.

## To reproduce

With the four datasheets of parts like these and your own key. For each part:

```
motionsim extract part_a.pdf -o part_a.observations.yaml
motionsim build part_a.observations.yaml -o part_a.device.yaml
```

Two of the four need a hand before they build. For the silicon MOSFET, set the gate-source charge in its observations file to the charge at threshold plus the figure printed, and mark it verified. For the GaN part with its gate interface built in, check that the rise time printed in its table is among the observations, and add it if it is not.

The 96 V joint:

```
motionsim design init --device part_a.device.yaml -o joint.yaml
# in joint.yaml: add the second device file under devices, set torque: 3.0, and give the
# load an inertia of 1.6, a friction_coulomb of 7.5 and a gravity mass of 26
motionsim design run joint.yaml --md joint.md
```

For the 100 kHz rows set `f_sw: 100000`. For the sensorless figures add `start: {method: open_loop}`.

The 310 V fan:

```
motionsim design init --device part_d.device.yaml -o fan.yaml
# in fan.yaml: add the second device file under devices, set v_dc: 310, and f_sw: 6000 or 16000
motionsim design run fan.yaml --md fan.md
```

A reading uses a language model, and two readings can differ.
