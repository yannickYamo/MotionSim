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

The two belong to different things. The coupling belongs to the package: it is reckoned over the package's own face, so nothing done to the mounting moves it. The case-to-heatsink resistance belongs to the build: the same module on grease and on a pad has two values. It can therefore be given with the cooling (`--rth-case-sink`, or `--interface pad`), and a figure given there replaces the device's own.

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
| TO-220, TO-247, TO-263, TO-252, TOLL | the package's own tab or pad, at the standard outline's size | the interface layer |

Chip size follows from the rated current through a current density. The interface is grease or an insulating pad.

The interface layer is where the constructions differ most:

- Under a discrete package's tab, and under a ceramic substrate, it is about 50 µm of grease. The substrate's back copper spreads the heat over a face wider than the copper the chips sit on.
- Under a moulded module it is about 100 µm. The body is held by a screw at each end and its face is not flat; module makers' mounting notes ask for a layer of that order. Nothing below the leadframe spreads the heat, so it crosses the layer under the copper and nowhere else.

Every one of those inputs has a low, typical and high value, because real packages differ and a datasheet does not say. The three cases are run together, low being the least heating and high the most.

**What comes out** (`motionsim package <template> --irated <amps>` prints it):

| Template, typical case | Heat spreads | Between chips, over the package face | Case to heatsink |
|---|---|---|---|
| Moulded leadframe module, 15 A | 6.6 mm | 0.36 K/W (0.14 to 1.10) | 0.36 K/W (0.07 to 0.87) |
| Ceramic-substrate module, 15 A | 2.8 mm | 0.01 K/W | 0.11 K/W (0.04 to 0.29) |
| TO-247, 40 A, grease | 6.2 mm | 0.17 K/W | 0.19 K/W |
| TO-220, 20 A, grease | 5.0 mm | 0.35 K/W | 0.40 K/W |

For a module, "between chips" is found with the package's face held at one temperature. For a discrete package it is found from the heatsink, and is not used: a package with one switch has its own case.

Two things the physics explains without being told:

- A ceramic substrate conducts heat downward about ten times better than moulding compound, so heat does not travel sideways to the neighbours. Coupling nearly vanishes.
- On a discrete package's thick tab, the switch and its diode sit closer than the spreading length. They share the interface layer, and the coupling between them is close to that layer's resistance.

## How the engine uses it

- **Multi-chip package, no coupling given:** coupling is computed for the stated construction (leadframe, substrate, or unknown, which spans both and takes the leadframe case as typical).
- **No case-to-heatsink resistance given, for the build or by the device:** it is computed for the module's construction or the discrete package's outline, and for the layer named (grease unless a pad is). The range is wide for a moulded module, because how it is mounted decides it: a measured figure narrows the result more than anything else on this page.
- **No transient thermal data on the datasheet:** the shape of the chip's thermal response is computed for the same generic package, by adding the heat capacity of the copper and the die to the plate equation and stepping it through time. That shape is applied to the datasheet's thermal resistance to get the temperature swing within an output period. The time-stepping is checked against the exact single-time-constant response of a fully covered plate.

A result that uses any of these lists them and reports the hottest junction as a range across the low, typical and high cases. A value the user enters always replaces a computed one.

The model's own estimate of a chip's thermal resistance is never used in place of the datasheet's. It is printed only as a sanity check, and can differ from a datasheet by a factor of two, because chip size is a guess.

## Through time

A motion is not a steady state. `motionsim cycle` follows temperature through it (`transient.py`):

- Each chip's junction-to-case network, the datasheet's or the computed one, is driven by the chip's loss at each instant, with the exact response to a constant power over each step.
- When the motor turns fast, many output periods fit in one instant of the motion: the slow state follows the mean loss, and the swing within the period, found as before, is added on top.
- When it turns slowly or stands still, the loss waveform is followed through the output period itself. Each time the motor slows to that point it is taken to arrive at a rotor position that loads a chip most. The motion is followed from each such position, one per chip, and the one that leaves a junction hottest is kept.
- What a chip shares with the rest of its package, the heating from its neighbours and the rise across the layer under the package, follows the package's loss with one time constant: that of the copper under the chips, charged through the layers beneath it (about half a second for a moulded module, a third for a TO-247 on grease). Only the copper's heat capacity is counted. The body around it and the heatsink's surface under the package slow a real one further, so over a burst of a few seconds this is the warm side.
- An imported trajectory (`motionsim trajectory`) is treated the same way: through a burst the case and the neighbours heat with the burst's loss, not with the mean over the whole trajectory.
- A heatsink given as a resistance to ambient and a heat capacity warms up as one thermal mass fed by the whole power stage's loss.

Losses at each instant are those the steady solution finds there, at the temperature that instant would settle at. While the junction is still cooler its real loss is slightly lower.

The spread across the thermal assumptions is not recomputed in time. The range found for the steady solution at the hottest instant is shifted by the same amount as the temperature.

## How it compares with a vendor's simulator

A cross-check, not a source. For the one module compared (module C in [VALIDATION.md](VALIDATION.md)), the simulator's junction temperatures fit the same form as above, with heating between chips of about 0.5 K/W for the switch against the 0.36 K/W (0.14 to 1.10) computed here: the same order, from independent reasoning.

With that module's curves read from its datasheet and the construction left unknown, the hottest junction is 0.2 to 3.4 °C above the simulator's at the five operating points where the switch is the hottest chip, and 7.5 °C below at the one where the diode is. The simulator's value lies inside the reported range at all six.

## Limits

- The generic layouts are plausible, not surveyed. A package with a different chip arrangement will differ.
- Chips on separate pieces of copper are taken not to heat each other through the package. The heatsink surface is taken to be at one temperature.
- Baseplate power modules, press-fit and double-sided cooled packages have no template.
- Surface-mount packages (TO-263, TO-252, TOLL) are represented by their pad and the layer under it. On a heatsink through a circuit board the board is most of the path, and it is not in this model: give the case-to-heatsink resistance of your own build, or use the cooling for parts soldered to one board.
- No public library of package thermal data was found to draw on. The outlines here are the tool's own short table, from published outline drawings; a package not in it gets no computed default.
- The transient response is that of the generic package, junction to heatsink, applied to a datasheet resistance defined junction to case. The two are not the same thing.
- Through time, neighbour heating and the interface follow the loss as fast as the copper alone allows, and the heatsink has no gradient across it. A burst of seconds on a moulded module comes out warm.
- One vendor's simulator, on one part, is the only external check on temperature.
