"""The six figures of a layout file, worked out for one leg of a board: each with the band it
is believed in and what it rests on, never a bare number.

The bands (see docs by the service): the board's loop inductance is given to a quarter either
way where the file holds the stack-up and the poured copper, and wider where either was
assumed, where a track is thinner than the mesh's cell, or where the search for the fast
edge's current was stopped early. That search is given work, not time: so many steps for the
size of its mesh, the same on any machine, so that a board's figures never say how busy the
machine was. Time is only a ceiling: a board not done by then is refused, never answered in part. A package's own inductance is the usual of its kind, to half
either way. The resistance is the copper's at 20 °C with a steady current; the skin effect at
the ringing's frequency raises it severalfold, so its band reaches to three times. A
capacitance is the sum of the values written, down to 0.4 of it for what a ceramic loses
under its voltage.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

from motionsim.board import values
from motionsim.board.bridge import Found, Leg
from motionsim.board.drive import Drive, find_drive, power_links
from motionsim.board.mesh import BODY, Grid, Link, Unsolved, network, rasterise
from motionsim.board.model import Board
from motionsim.board.solve import Kernel, Loop, coupling, solve
from motionsim.errors import Refusal

TARGET_CELLS = 10_000  # of one leg's window, where the mesh is as fine as it needs to be
MOST_CELLS = 40_000  # past this the mesh is made coarser, and that is said
FINEST, COARSEST = 0.1, 1.0  # mm: the mesh's cell
# What the searches of all the legs of a board may cost together, and the least and the most
# one of them is given, in cells transformed (see solve._Circuit.cost): some forty seconds,
# a third of one and four on the machine these were set on. A search stopped at its share
# leaves its figure on the high side, and says so.
WORK = 2.0e9
LEAST_WORK = 1.5e7
MOST_WORK = 2.0e8
CEILING = 120.0  # seconds a board may take on a machine however slow or busy: past it, a refusal
UNITS = {"l_loop_nh": "nH", "l_cs_nh": "nH", "l_gate_nh": "nH", "r_loop_mohm": "mΩ", "c_dc_uf": "µF", "esl_nh": "nH"}


def figure(key: str, value, low=None, high=None, rests_on=(), assumed: bool = False) -> dict:
    """One figure as it is handed over: a value with its band, or no value and why."""

    def tidy(v):
        return None if v is None else float(f"{v:.4g}")

    return {
        "value": tidy(value),
        "low": tidy(low),
        "high": tidy(high),
        "unit": UNITS[key],
        "assumed": assumed,
        "rests_on": list(rests_on),
    }


def missing(key: str, why: str) -> dict:
    return figure(key, None, rests_on=[f"not worked out: {why}"])


@dataclass
class Clock:
    """The work left for a board's searches, shared out among those still to do, and the time
    by which the board must be done or refused."""

    solves: int
    left: float = field(default_factory=lambda: WORK)
    end: float = field(default_factory=lambda: time.monotonic() + CEILING)

    def share(self) -> float:
        """What the next search may cost. Nothing here asks the time: the shares, and so the
        figures, are the same on any machine."""
        self.solves = max(self.solves - 1, 1)
        return min(max(self.left / (self.solves + 1), LEAST_WORK), MOST_WORK)

    def spent(self, work: float) -> None:
        self.left -= work

    def alive(self) -> None:
        """Refuses the board where it has taken longer than any machine should need."""
        if time.monotonic() > self.end:
            raise Refusal(
                f"working out this board's loops took longer than {CEILING:g} s on this machine, and was stopped: "
                "no figure of it is given",
                "choose the one leg wanted, or give the board of the power stage alone; a machine that is "
                "less busy may also finish it",
                "board",
            )


def _window(links: list[Link], board: Board) -> tuple[float, float, float, float]:
    """The box round every part of the loops, with room about it for the copper between."""
    pads = [pad for ref in {link.ref for link in links} for pad in board.component(ref).pads]  # type: ignore[union-attr]
    x0, x1 = min(p.x - p.w / 2 for p in pads), max(p.x + p.w / 2 for p in pads)
    y0, y1 = min(p.y - p.h / 2 for p in pads), max(p.y + p.h / 2 for p in pads)
    room = max(3.0, 0.15 * max(x1 - x0, y1 - y0))
    return x0 - room, y0 - room, x1 + room, y1 + room


def _pitch(window, links: list[Link]) -> tuple[float, bool]:
    """The cell's size, mm: fine enough for the smallest driving part's pads to lie in
    different cells, coarse enough for the budget. True where the budget made it coarser."""
    area = (window[2] - window[0]) * (window[3] - window[1])
    pitch = min(max(math.sqrt(area / TARGET_CELLS), FINEST), COARSEST)
    spans = [max(abs(link.a.x - link.b.x), abs(link.a.y - link.b.y)) for link in links]
    pitch = min(pitch, max(min(spans) / 2, FINEST)) if spans else pitch
    least = math.sqrt(area / MOST_CELLS)
    return (least, True) if least > pitch else (pitch, False)


def _band(board: Board, grid: Grid, loop: Loop, nets: list[str]) -> tuple[float, float, list[str]]:
    """How far under and over the board's inductance is believed, as shares, and why."""
    share, why = 0.25, []
    layered = (
        bool(loop.fields[2].any())
        or sum(bool(loop.fields[0][k].any() or loop.fields[1][k].any()) for k in range(len(grid.layers))) > 1
    )
    if board.stackup.assumed:
        share += 0.15 if layered else 0.05
        why.append("the heights between the layers were assumed" if layered else "the copper's thickness was assumed")
    if any(not zone.filled for zone in board.zones if zone.net in nets):
        share += 0.10
        why.append("a pour was taken from its outline, not its fill")
    if grid.through_thin(loop.steady):
        share += 0.10
        why.append(
            f"it runs through tracks down to {grid.narrowest:g} mm, drawn as wide as the mesh's {grid.pitch:.2g} mm cells"
        )
    under = share + (0.0 if loop.settled else 0.10)
    if not loop.settled:
        why.append("the search for the fast edge's current was stopped early, which leaves the figure high")
    return under, share, why


def _layers(grid: Grid, loop: Loop) -> str:
    used = [layer.name for k, layer in enumerate(grid.layers) if loop.fields[0][k].any() or loop.fields[1][k].any()]
    return " and ".join(used) + (
        f" through {int((loop.fields[2] != 0).sum())} via positions" if loop.fields[2].any() else ""
    )


def _packages(board: Board, refs: list[str], column: int) -> tuple[float, list[str]]:
    """What the switches' packages add, nH, by the kind each footprint's name gives."""
    total: float = 0.0
    said: list[str] = []
    for ref in refs:
        part = board.component(ref)
        kind = values.package(part.footprint) if part else None
        if kind is None:
            said.append(f"{ref}'s package is not known from its footprint's name: nothing is added for it, add its own")
        else:
            added = float(kind[column])
            total += added
            said.append(f"{added:g} nH assumed for {ref}, {kind[0]}")
    return total, said


def _loop_figure(board: Board, grid: Grid, loop: Loop, leg: Leg, nets: list[str]) -> dict:
    board_nh = loop.l * 1e9
    under, over, why = _band(board, grid, loop, nets)
    package_nh, said = _packages(board, [leg.high_side[0], leg.low_side[0]], 1)
    rests = [
        f"the board's copper gives {board_nh:.3g} nH: from {', '.join(leg.capacitors)} through {', '.join(leg.high_side)}, "
        f"{leg.switch_node} and {', '.join(leg.low_side)} and back, on {_layers(grid, loop)}, as {loop.bars} bars of "
        f"{grid.pitch:.2g} mm",
        f"the current is shared out as a fast edge shares it, for the least magnetic energy; shared out as a steady "
        f"current it would give {loop.l_dc * 1e9:.3g} nH, and a fast edge's own sharing can only give less",
        f"each part's body is drawn as flat bars between its pads, {BODY:g} mm off the copper; copper of other nets and "
        "copper outside the window round the loop's parts is left out",
        *said,
        f"the board's share is believed to {under:.0%} under and {over:.0%} over"
        + (": " + "; ".join(why) if why else ": the stack-up and the fills are the file's own")
        + "; a package's to half either way",
    ]
    low = board_nh * (1 - under) + 0.5 * package_nh
    high = board_nh * (1 + over) + 1.5 * package_nh
    out = figure("l_loop_nh", board_nh + package_nh, low, high, rests, assumed=package_nh > 0)
    out["parts"] = {"board_nh": float(f"{board_nh:.4g}"), "package_nh": package_nh}
    return out


def _resistance(grid: Grid, loop: Loop) -> dict:
    mohm = loop.r * 1e3
    rests = [
        "the copper's own resistance round the loop at 20 °C with a steady current (1.724e-8 Ω·m), the vias plated "
        "25 µm; the switches and the capacitors are not in it",
        "at the ringing's frequency the current keeps to the copper's skin and the resistance is severalfold this: "
        "the band reaches to three times",
    ]
    if grid.through_thin(loop.steady):
        rests.append(
            f"it runs through tracks down to {grid.narrowest:g} mm, drawn as wide as the mesh's {grid.pitch:.2g} mm "
            "cells: understated for them"
        )
    return figure("r_loop_mohm", mohm, 0.8 * mohm, 3.0 * mohm, rests)


def _capacitance(board: Board, leg: Leg) -> tuple[dict, dict]:
    """The decoupling capacitance and the capacitors' own inductance, from what is written by them."""
    farads: list[float] = []
    unread: list[str] = []
    cases: list[str | None] = []
    for ref in leg.capacitors:
        part = board.component(ref)
        assert part is not None
        value = values.capacitance(part.value)
        if value:
            farads.append(value)
        else:
            unread.append(ref)
        cases.append(values.case(part.footprint))
    if farads:
        total = sum(farads) * 1e6
        rests = [f"the sum of the values written by {', '.join(r for r in leg.capacitors if r not in unread)}"]
        rests += [f"no value could be read by {', '.join(unread)}: not counted"] if unread else []
        rests.append(
            "a ceramic capacitor holds less under its voltage: the band reaches down to 0.4 of the values written"
        )
        c_dc = figure("c_dc_uf", total, 0.4 * total, 1.1 * total, rests)
    else:
        c_dc = missing("c_dc_uf", f"no capacitance could be read from the values by {', '.join(leg.capacitors)}")
    known = [c for c in cases if c]
    if len(known) == len(cases):
        nh = 1.0 / sum(1.0 / values.ESL_BY_CASE[c] for c in known)
        rests = [
            f"{len(cases)} ceramic chip capacitors side by side, each its case's usual ({', '.join(sorted(set(known)))}): assumed, "
            "to half either way; give the maker's figure",
            "the board's loop already spans each capacitor's length with a flat bar, so the two overlap by a fraction "
            "of a nanohenry: on the high side",
        ]
        esl = figure("esl_nh", nh, 0.5 * nh, 1.5 * nh, rests, assumed=True)
    else:
        esl = missing(
            "esl_nh", "a capacitor's case is not known from its footprint's name: give the capacitor's own inductance"
        )
    return c_dc, esl


def _gate_figures(
    board: Board, grid: Grid, kernel: Kernel, power: Loop, drive: Drive, clock: Clock
) -> tuple[dict, dict]:
    """The gate loop and the common-source inductance of one switch."""
    loop = solve(network(grid, drive.nets, drive.links), kernel, clock.share(), clock.alive)
    clock.spent(loop.work)
    gate_nh = loop.l * 1e9
    pkg_gate, said_gate = _packages(board, [drive.switch], 3)
    under, over, why = _band(board, grid, loop, drive.nets)
    path = " and ".join([drive.driver, *drive.resistors, drive.switch])
    rests = [
        f"the board's copper gives {gate_nh:.3g} nH: {path}, out on {drive.gate_net} and back on {drive.return_net}, on {_layers(grid, loop)}",
        *said_gate,
        f"the board's share is believed to {under:.0%} under and {over:.0%} over"
        + (": " + "; ".join(why) if why else ""),
    ]
    l_gate = figure(
        "l_gate_nh",
        gate_nh + pkg_gate,
        gate_nh * (1 - under) + 0.5 * pkg_gate,
        gate_nh * (1 + over) + 1.5 * pkg_gate,
        rests,
        assumed=pkg_gate > 0,
    )
    shared = coupling(power, loop, kernel) * 1e9
    if drive.kelvin:
        rests = [
            f"the gate current of {drive.switch} returns on {drive.return_net}, a Kelvin source pad of its own: nothing is shared with the power loop",
            f"the two loops still couple through the board by {shared:.2g} nH, which the band holds",
        ]
        return l_gate, figure("l_cs_nh", 0.0, 0.0, max(abs(shared), 0.2), rests)
    pkg_shared, said_shared = _packages(board, [drive.switch], 2)
    board_nh = max(shared, 0.0)
    rests = [
        f"the board's copper shared by the power loop and the gate return of {drive.switch} on {drive.return_net}, with "
        f"the coupling of the two loops through the board: {shared:.2g} nH"
        + (", taken as nought" if shared < 0 else ""),
        *said_shared,
        "believed to half either way",
    ]
    total = board_nh + pkg_shared
    return l_gate, figure("l_cs_nh", total, 0.5 * total, 1.5 * total + 0.2, rests, assumed=pkg_shared > 0)


def _meshed(board: Board, nets: list[str], links: list[Link], said: list[str]) -> Grid:
    window = _window(links, board)
    pitch, coarser = _pitch(window, links)
    if pitch > COARSEST * 4:
        raise Unsolved(
            f"the loop's parts lie {window[2] - window[0]:.0f} mm by {window[3] - window[1]:.0f} mm apart, more than is meshed"
        )
    for _ in range(3):
        try:
            grid = rasterise(board, nets, window, pitch)
            break
        except Unsolved:
            pitch, coarser = pitch * 1.6, True
    else:
        raise Unsolved("more vias in the loop's window than the mesh takes")
    if coarser:
        said.append(
            f"the loop's window was meshed coarser than its copper asks, in cells of {pitch:.2g} mm, to stay within the budget"
        )
    return grid


def _worse(a: dict | None, b: dict) -> dict:
    return b if a is None or (b["value"] or 0) > (a["value"] or 0) else a


def leg_figures(board: Board, found: Found, leg: Leg, choose: dict, clock: Clock) -> dict:
    """One leg's figures, its gate drives as found, and what was said on the way."""
    said: list[str] = []
    nets, links = power_links(board, found, leg)
    drives: dict[str, Drive | str] = {
        side: find_drive(board, found, leg, refs[0], choose)
        for side, refs in (("high_side", leg.high_side), ("low_side", leg.low_side))
    }
    every = links + [link for d in drives.values() if isinstance(d, Drive) for link in d.links]
    all_nets = list(dict.fromkeys(nets + [n for d in drives.values() if isinstance(d, Drive) for n in d.nets]))
    figures = {key: missing(key, "the loop was not solved") for key in UNITS}
    figures["c_dc_uf"], figures["esl_nh"] = _capacitance(board, leg)
    mesh: dict = {}
    try:
        clock.alive()
        grid = _meshed(board, all_nets, every, said)
        kernel = Kernel(grid)
        power = solve(network(grid, nets, links), kernel, clock.share(), clock.alive)
        clock.spent(power.work)
    except Unsolved as exc:
        why = f"{exc} for the leg at {leg.switch_node}"
        said.append(f"the commutation loop at {leg.switch_node} was not worked out: {exc}")
        figures |= {key: missing(key, why) for key in ("l_loop_nh", "r_loop_mohm", "l_gate_nh", "l_cs_nh")}
        return {"figures": figures, "drives": drives, "said": said, "mesh": mesh, "each": {}}
    mesh = {
        "pitch_mm": float(f"{grid.pitch:.3g}"),
        "cells": [grid.nx, grid.ny],
        "bars": power.bars,
        "settled": power.settled,
    }
    figures["l_loop_nh"] = _loop_figure(board, grid, power, leg, nets)
    figures["r_loop_mohm"] = _resistance(grid, power)
    gate, shared, reasons = None, None, []
    each: dict[str, dict] = {}
    for side, drive in drives.items():
        if isinstance(drive, str):
            reasons.append(drive)
            continue
        try:
            one_gate, one_shared = _gate_figures(board, grid, kernel, power, drive, clock)
        except Unsolved as exc:
            reasons.append(f"the gate loop of {drive.switch} was not worked out: {exc}")
            continue
        gate, shared = _worse(gate, one_gate), _worse(shared, one_shared)
        each[side] = {"l_gate_nh": one_gate, "l_cs_nh": one_shared}
        said += [drive.said] if drive.said else []
    said += reasons
    figures["l_gate_nh"] = gate or missing("l_gate_nh", "; ".join(reasons))
    figures["l_cs_nh"] = shared or missing("l_cs_nh", "; ".join(reasons))
    return {"figures": figures, "drives": drives, "said": said, "mesh": mesh, "each": each}
