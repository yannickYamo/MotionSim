# Thermal model: what a datasheet gives, what it does not, and how the gap is filled

## What a datasheet's thermal resistance means

A datasheet's junction-to-case thermal resistance, Rth(j-c), is the temperature rise of one chip above the package case per watt dissipated **in that chip alone**. It is standard practice to characterise one chip of a multi-chip package by itself, usually the one that runs hottest, and to state a typical or a maximum value. The reference chip and the choice of typical or maximum vary between vendors.

Three things follow, and each affects a design:

1. **It says nothing about heating by neighbours.** With every chip dissipating, each junction runs hotter than `own loss × Rth(j-c)` predicts. How much hotter depends on how the package is built.
2. **The case is not at the heatsink temperature.** Between them sit an interface layer (grease or a pad) and the heatsink's own spreading. The usual bookkeeping is per package: case temperature is heatsink temperature plus the package's *total* loss times a case-to-heatsink resistance.
3. **A maximum is not a typical.** Using a maximum value gives a result on the safe side.

So the engine computes each junction as

    Tj = T_heatsink
       + (case-to-heatsink resistance) × (loss of the whole package)
       + Rth(j-c) × (this chip's loss)
       + (coupling) × (loss of every other chip in the package)

The datasheet supplies Rth(j-c). The case-to-heatsink resistance and the coupling are usually not on a datasheet. A user who knows them enters them. Otherwise they are computed as described below, and the result says so and gives a range.

This is the ordinary thermal-resistance-matrix view of a multi-chip package, reduced to the three numbers a datasheet-driven tool can support.

## Filling the gap from first principles

`motionsim.package` computes how chips in a package heat each other, starting from the package's construction. No measured device data goes in.

**The physics.** Power chips are soldered to copper: a leadframe pad, the copper of a ceramic substrate, or the tab of a discrete package. Under the copper is an insulating layer, then a surface taken to be at one temperature (the heatsink). The copper is thin compared with its width, so heat flows sideways in it and straight down through the insulation. Temperature rise `θ` then obeys

    k_copper · t_copper · ∇²θ − (k_ins / t_ins) · θ + q = 0

The length `sqrt(k_copper · t_copper · t_ins / k_ins)` is how far heat travels sideways before it has gone down. Chips closer than that heat each other; chips much further apart do not. The equation is solved on a grid for each piece of copper, giving a matrix: the rise under each chip per watt in each other chip. Each chip's own die and solder layers are added to its own term.

The solver is checked against two exact results: a chip covering its whole plate (pure one-dimensional conduction), and the temperature far from a small source on a large plate (the modified Bessel function solution).

**The package templates.** Each is a generic construction of its kind, not a vendor's product.

| Template | Copper | Insulation between copper and heatsink |
|---|---|---|
| Moulded leadframe module | 0.5 mm copper-alloy leadframe; high-side chips share one area, each low-side pair has its own | conductive moulding compound, then the interface layer |
| Ceramic-substrate module | 0.3 mm copper on the same layout | 0.38 mm alumina and its back copper, then the interface layer |
| TO-220, TO-247, TO-263 | the package's own tab, at the standard outline's size | the interface layer |

Chip size follows from the rated current through a current density. The interface is grease or an insulating pad.

Every one of those inputs has a low, typical and high value, because real packages differ and a datasheet does not say. The three cases are run together, low being the least heating and high the most.

**What comes out** (`motionsim package <template> --irated <amps>` prints it):

| Template, typical case | Heat spreads | Between chips | Interface alone |
|---|---|---|---|
| Moulded leadframe module, 15 A | 6.1 mm | 0.48 K/W (0.17 to 1.43) | 0.11 K/W |
| Ceramic-substrate module, 15 A | 2.8 mm | 0.08 K/W | 0.11 K/W |
| TO-247, 40 A, grease | 6.2 mm | 0.17 K/W | 0.19 K/W |
| TO-220, 20 A, grease | 5.0 mm | 0.35 K/W | 0.40 K/W |

Two things the physics explains without being told:

- A ceramic substrate conducts heat downward about ten times better than moulding compound, so heat does not travel sideways to the neighbours. Coupling nearly vanishes.
- On a discrete package's thick tab, the switch and its diode sit closer than the spreading length. They share the interface layer, and the coupling between them is close to that layer's resistance.

## How the engine uses it

- **Multi-chip package, no coupling given:** coupling is computed for the stated construction (leadframe, substrate, or unknown, which spans both and takes the leadframe case as typical).
- **Discrete package with its outline given, no case-to-heatsink resistance given:** it is computed for that outline and interface.
- **No transient thermal data on the datasheet:** the shape of the chip's thermal response is computed for the same generic package, by adding the heat capacity of the copper and the die to the plate equation and stepping it through time. That shape is applied to the datasheet's thermal resistance to get the temperature swing within an output period. The time-stepping is checked against the exact single-time-constant response of a fully covered plate.

A result that uses any of these lists them and reports the hottest junction as a range across the low, typical and high cases. A value the user enters always replaces a computed one.

The model's own estimate of a chip's thermal resistance is never used in place of the datasheet's. It is printed only as a sanity check, and can differ from a datasheet by a factor of two, because chip size is a guess.

## Through time

A motion is not a steady state. `motionsim cycle` follows temperature through it (`transient.py`):

- Each chip's junction-to-case network, the datasheet's or the computed one, is driven by the chip's loss at each instant, with the exact response to a constant power over each step.
- When the motor turns fast, many output periods fit in one instant of the motion: the slow state follows the mean loss, and the swing within the period, found as before, is added on top.
- When it turns slowly or stands still, the loss waveform is followed through the output period itself. Each time the motor slows to that point it is taken to arrive at the rotor position that loads the hottest chip most.
- Heating from neighbouring chips and the package-to-heatsink interface are taken to respond at once. That is the cautious side: in reality they lag.
- A heatsink given as a resistance to ambient and a heat capacity warms up as one thermal mass fed by the whole power stage's loss.

Losses at each instant are those the steady solution finds there, at the temperature that instant would settle at. While the junction is still cooler its real loss is slightly lower.

The spread across the thermal assumptions is not recomputed in time. The range found for the steady solution at the hottest instant is shifted by the same amount as the temperature.

## How it compares with a vendor's simulator

A cross-check, not a source. One vendor's public simulator was run for eight of its modules (kept locally, outside the repository). Its junction temperatures fit the same form as above, with coupling of 0.67 to 1.09 K/W for five fully moulded modules and zero for three ceramic-substrate ones. The first-principles figures are 0.48 K/W (0.17 to 1.43) and 0.08 K/W. Same order, same contrast between constructions, from independent reasoning.

For the one module whose datasheet has been read (module C), with construction left unknown and the transient response assumed, the hottest junction was within −5 to +4 °C of the simulator's at six operating points. With the datasheet's own transient curve and its energy curves now read, it is within −4 to +7 °C. The simulator's value lies inside the reported range at all six either way. The temperature swing within an output period comes out about a third smaller than the simulator's (2.2 against 3.5 °C at 50 Hz, 5.6 against 6.7 °C at 5 Hz).

## Limits

- The generic layouts are plausible, not surveyed. A package with a different chip arrangement will differ.
- Chips on separate pieces of copper are taken not to heat each other through the package. The heatsink surface is taken to be at one temperature.
- Baseplate power modules, press-fit and double-sided cooled packages have no template.
- Surface-mount packages cooled through a circuit board are represented only by the tab-to-interface model, which is wrong for them.
- The transient response is that of the generic package, junction to heatsink, applied to a datasheet resistance defined junction to case. The two are not the same thing; the comparison above suggests the swing is somewhat underestimated.
- Through time, neighbour heating and the interface have no delay, and the heatsink has no gradient across it.
- One vendor's simulator is the only external check.
