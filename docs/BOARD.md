# The board file reader

The switching event rests on six figures of the board: the commutation loop's inductance, the inductance the gate and the power loop share, the gate loop's inductance, the loop's resistance, the decoupling capacitance and the capacitors' own inductance. Without a board they are assumed by the package's kind. The board reader works them out from the board's own design file, each with the range it is believed in and what it rests on. [GUIDE.md](GUIDE.md) says how to give a file on the page; [LIMITS.md](LIMITS.md) section 10 has what it leaves out.

It runs on your own machine only: on the local page (`motionsim serve`, `docker compose up`), through `POST /api/board`, or from Python:

```python
from motionsim import board

answer = board.read("examples/board_half_bridge.kicad_pcb")
answer["figures"]["l_loop_nh"]  # {"value": ..., "low": ..., "high": ..., "rests_on": [...]}
answer["layout"]  # the six figures as a layout file, for the switching event
```

## Formats

| File | What happens |
|---|---|
| KiCad board, `.kicad_pcb`, versions 6 to 9 | Read: the stack-up where the file has one, nets, footprints with their reference, value and pads, track segments and arcs, vias, zones with their filled polygons |
| IPC-2581, `.xml` or `.cvg`, as most layout tools export it | Read: copper layers and their heights from the stack-up, nets, parts with their values from the bill of materials, lines and polylines as tracks, contours as pours with their cut-outs, pads that name their pin, plated holes as vias |
| ODB++ (an archive) | Refused, with the way forward: export IPC-2581 from the layout tool, or give the KiCad file |
| STEP, `.step` or `.stp` | Refused: a STEP file holds shapes and no nets, so no loop can honestly be read from it. Where it holds one solid, its size is given back as geometry only |
| A layout tool's own binary board file | Refused as a closed format, with the export to make instead |
| Any other archive, or a file that is not a board | Refused in a line, with what to give |

Not taken from a KiCad file: text, graphics, keep-out areas, a custom pad's shape beyond the box around it, and the teardrops and thermal spokes a fill does not already hold. Not taken from an IPC-2581 file: a pad that names no pin (a via's land, a test point), text, and anything on a layer that is not copper.

A file may be 30 MB and hold 400 000 tracks, vias, pads and polygon corners together. Nothing is ever unpacked to disk: an archive is only listed, to say what it is. A file cut short, malformed or built to exhaust the reader is refused in a line.

Where the file has no stack-up, the usual one stands in (35 µm copper on a 1.6 mm board), the answer says so, and the band is wider.

## How the loop is found, and how to choose another

A commutation loop runs from a decoupling capacitor's positive pad through the high-side switch, the switch node and the low-side switch back to the capacitor's negative pad. So the reader looks, in the nets alone, for:

1. **The supply:** two nets joined by capacitors (parts on those two nets only) and by two transistor-like parts in series through a third net. Which is plus is told by the nets' names, else by where the switches' largest pads are (a transistor's tab is its drain), else the net with more pads is taken as minus. Names help and are never relied on alone.
2. **The legs:** every net a switch joins to plus and another joins to minus, straight or through one two-pad part that is not a capacitor (a current-sense resistor). A switch is a part on three or four nets, or a diode by its name. Paralleled switches are one leg.
3. **The capacitors of each leg:** the nearest by the way round the loop, at most eight.
4. **Each switch's gate drive:** the driver, the resistors between its output and the gate, and the net the gate current returns on, which is the switch's own source or a separate Kelvin source pad.

The answer lists what was taken and, under `candidates`, what else could have been. Anything can be named in its place under `choose`: `dc_plus`, `dc_minus`, `switch_nodes`, `high_side`, `low_side`, `capacitors`, `gate_driver`, and `leg` for the leg whose figures go into the layout. What is named is always taken over the guess. A board with no half bridge is refused with what was looked for. Up to 12 legs are worked out in one request.

## The method

**Partial inductances.** Every conductor is cut into straight pieces. A loop's inductance is the sum of each piece's own partial inductance and of the mutual partial inductance of every two, with the sign of their currents (Ruehli, 1972). Pieces at right angles have no mutual. The closed forms: two parallel filaments at any offset (Grover, 1946); a flat tape's own, which is the zero-thickness limit of Hoer and Love's bar (1965); two parallel flat tapes in parallel planes; a round wire's own (Rosa, 1908).

**The mesh.** A window round the loop's parts, with room about it, is cut into square cells of 0.1 to 1 mm, fine enough for the smallest part's pads to lie in different cells, about 10 000 cells for one leg and coarser past 40 000, which is then said. Each cell is one net's copper on one layer. Bars run along x and y between neighbouring cells of one net, and upright in vias (25 µm of plating assumed). A part's body between two of its pads is drawn as flat bars 0.1 mm off the copper, so the loop closes where its current is. Every cell under one pad is one point.

**Two current distributions.** The loop is driven where its capacitor (or its gate driver) is, and two currents are worked out:

- the one a steady voltage drives, shared out by the copper's resistance. It gives the loop's resistance and one figure for the inductance;
- the one a fast edge drives, shared out so that the magnetic energy is least, found by conjugate gradients among the currents that keep Kirchhoff's current law. This is the figure given.

Any current that keeps the current law gives an inductance at or above the least (Thomson's principle). A search stopped early therefore leaves the figure on the high side, never under, and the answer says when it was. All the legs of a board share 40 s by the clock, so on a busy machine a search can stop early that would have ended on an idle one: the figure is then a little higher and its band reaches 10 points further down.

The mutual of two flat bars depends only on how many cells apart they are, so the sum over all pairs is a convolution, taken with the fast Fourier transform.

**What is added to the board's share.** A switch's package adds the usual of its kind, told from its footprint's name: for the loop, 10 nH for a leaded TO-247, 7 for a TO-220, 4 for a D2PAK, 3 for a DPAK, 2 for a TOLL and 1 for a leadless or small-outline package, with their shares for the source path and the gate lead. A ceramic chip capacitor's own inductance is the usual of its case, from 0.3 nH for an 0201 to 1.2 nH for a 2220, with capacitors side by side taken in parallel. Each is marked `assumed`. Where a footprint's name gives no kind, nothing is added and that is said.

## The six figures and their bands

No figure is a bare number: each has `value`, `low`, `high`, `unit`, `assumed` and `rests_on`, or no value and the reason.

| Figure | What it is | The band |
|---|---|---|
| `l_loop_nh` | The commutation loop: the board's copper and the two packages | The board's share to a quarter either way where the file holds the stack-up and the poured copper. A package's share to half either way |
| `l_cs_nh` | What the gate return shares with the power loop, with the coupling of the two loops through the board. Nought where the gate returns on a Kelvin source pad of its own | Half either way |
| `l_gate_nh` | The gate loop: driver, resistors and switch, out on the gate net and back on its return | As the loop's |
| `r_loop_mohm` | The copper's own resistance round the loop at 20 °C with a steady current. The switches and the capacitors are not in it | From 0.8 of it to three times: at the ringing's frequency the current keeps to the copper's skin |
| `c_dc_uf` | The sum of the values written by the leg's capacitors | Down to 0.4 of it, for what a ceramic loses under its voltage, and up to 1.1 |
| `esl_nh` | The capacitors' own inductance, by their case | Half either way |

What widens the board's share past a quarter:

| Why | Added to the band |
|---|---|
| The file had no stack-up and the loop uses more than one layer: the heights between layers were assumed | 15 points |
| No stack-up, a loop on one layer: the copper's thickness was assumed | 5 points |
| A pour was taken from its outline, not its fill | 10 points |
| A fifth or more of the loop's steady current runs through a track thinner than the mesh's cell | 10 points |
| The search for the fast edge's current was stopped early | 10 points, on the low side only |

A leg's `l_gate_nh` and `l_cs_nh` are the larger of its two switches'; each switch's own two are under `gate_drive`.

For the made-up half bridge in `examples/board_half_bridge.kicad_pcb` (two D2PAK switches, two ceramic capacitors, a two-layer board with its stack-up in the file) the layout handed to the event reads:

```
l_loop_nh: 44.49    # nH, believed 31.37 to 57.61
l_cs_nh: 3.267    # nH, believed 1.633 to 5.1
l_gate_nh: 49.42    # nH, believed 31.67 to 67.17
r_loop_mohm: 5.652    # mΩ, believed 4.522 to 16.96
c_dc_uf: 4.8    # µF, believed 1.92 to 5.28
esl_nh: 0.4737    # nH, believed 0.2368 to 0.7105
```

Of the 44.5 nH of loop, 36.5 nH is the board's copper and 8 nH the two packages. Shared out as a steady current the copper would give 38.4 nH.

## What it is checked against

Closed forms from the textbooks, each worked out in the test apart from the code (`tests/test_board_inductance.py`):

| What | Held to |
|---|---|
| A rectangular bar's own inductance (Grover) | 1% on a 10 mm bar, 0.5% on a 100 mm bar |
| A square thin tape's own, the exact form | 1 part in 10 000 |
| A round wire's own (Rosa) | 0.5% |
| Two parallel filaments' mutual (Grover) | 2 parts in 100 000 |
| Bars far apart tend to filaments | 0.1% |
| A rectangular loop of track, 60 by 40 mm, meshed and solved, against the textbook's rectangle of bar | 5%, by both currents |
| That loop's resistance against its copper's | 5% |
| A pair of planes against µ0·h·l/w | 10%, and in proportion to the height within 10% |
| A track and its return side by side against the two-bar formula | 5% |

And the reader as a whole (`tests/test_board_loops.py`, `tests/test_board_parsers.py`, `tests/test_board_service.py`): the same made-up board in KiCad and in IPC-2581 gives the same six figures within 1%; the three legs of a made-up three-phase board, the same copper side by side, agree within 5%; a layout from a board moves the switching event's turn-off overshoot the way its loop inductance says, less for a loop on a plane and more for a tracked one; what was assumed widens the band and is said; a budget that runs short is said and the figure still given.

## Limits

- **Not compared with a field solver or a measurement.** The checks are closed forms on simple shapes. No figure from a real board has been set beside a solver's or a bench's.
- **Only made-up boards have been read.** The boards of the tests and the example are drawn for the purpose. A real board will have shapes these do not.
- **The current distribution is one of two idealisations.** The resistance is a steady current's. The inductance is the least-energy current's, which is the high-frequency limit with the current free to spread through the copper's width; there is no skin or proximity effect within a conductor's thickness, and no frequency in between.
- **Other nets' copper is ignored.** A plane of another net under the loop carries eddy currents that lower a real loop's inductance; here it is not there. Copper outside the window round the loop's parts is left out too.
- **A track thinner than a cell is drawn a cell wide.** The band says so, and the resistance is then understated for it.
- **Packages and capacitors are the usual of their kind,** told from a footprint's name. Give the maker's figure where you have it.
- **The switches and capacitors are not in the resistance,** and a capacitance is the value written, not what the part holds under its voltage.
- **One leg at a time.** Each leg's loop is solved alone; coupling between legs is not worked out.

## The request and the answer

`POST /api/board`, on the local page only.

```
{
  "name": "inverter.kicad_pcb",
  "text": "(kicad_pcb ...",          or "data_base64": "..." for a file that is not text
  "choose": {"dc_plus", "dc_minus", "switch_nodes", "high_side", "low_side",
             "capacitors", "gate_driver", "leg"}          optional
}
```

The answer gives `format`, `stackup` (with `assumed` and its layers), `nets`, `parts`, `bridges` (one for each leg, with its switches, capacitors, gate drives, six figures and mesh), `candidates`, `taken` (the leg `figures` and `layout` are of), `figures`, `layout` and `warnings`.

`layout` is the text of a layout file. Send it as it is, or after changing it, as `"event": {"layout": <that text>}` in a request to `/api/event`, or save it and give it to `motionsim event design.yaml --layout`. A figure not worked out is a comment line in it, and the event then assumes that figure as it does without a board.

A refusal is `{"refused", "fix", "field"}` with status 422. `field` is `board` where the file is at fault, `choose` or `choose.<name>` where what was chosen is.

The whole of both shapes, with every name, is the docstring of `src/motionsim/service/board.py`.
