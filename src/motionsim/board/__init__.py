"""A board's own design file read for the figures of its switching loop.

    from motionsim import board
    answer = board.read("inverter.kicad_pcb")
    answer["figures"]["l_loop_nh"]   # {"value": ..., "low": ..., "high": ..., "rests_on": [...]}
    answer["layout"]                 # the six figures as a layout file, for the switching event

KiCad's .kicad_pcb (versions 6 to 9) and IPC-2581 are read. ODB++, STEP and Altium's own
format are refused in words that say what to give instead. The shapes of what comes back are
set out in motionsim.service.board, which answers the page with the same thing.
"""

from __future__ import annotations

from difflib import get_close_matches
from pathlib import Path

from motionsim.board import ipc2581, kicad
from motionsim.board.bridge import Found, Hint, Leg, find, shown
from motionsim.board.drive import Drive
from motionsim.board.figures import UNITS, Clock, leg_figures
from motionsim.board.formats import recognise, step_size
from motionsim.board.model import MOST_BYTES, Board, clean
from motionsim.errors import Refusal

__all__ = ["CHOICES", "load", "read", "step_size"]

MOST_LEGS = 12  # worked out for one request

# What "choose" may name, and what each is.
CHOICES = {
    "dc_plus": "the supply's positive net",
    "dc_minus": "the supply's negative net",
    "switch_nodes": "the switch-node nets of the legs wanted",
    "high_side": "the high-side switches, by reference designator",
    "low_side": "the low-side switches",
    "capacitors": "the decoupling capacitors to take for the loop",
    "gate_driver": "the gate drivers",
    "leg": "the switch node of the leg whose figures go into the layout",
}


def load(data: str | bytes | Path, name: str | None = None) -> Board:
    """The board a file holds: its layers, parts, tracks, vias and pours. data is the file's
    path, or what it holds as bytes; text is taken as a path."""
    if isinstance(data, (str, Path)):
        path = Path(data)
        name = name or path.name
        try:
            with open(path, "rb") as f:
                data = f.read(MOST_BYTES + 1)
        except OSError as exc:
            raise Refusal(
                f"cannot read the board file {path.name}: {exc.strerror or type(exc).__name__}", "", "board"
            ) from None
    # The file's name is said in every answer about it: on one line, and no longer than a name is.
    name = clean(name or "", 200) or None
    try:
        kind, text = recognise(data, name or "board")
        return (
            kicad.read(text, name or "board.kicad_pcb") if kind == "kicad" else ipc2581.read(text, name or "board.xml")
        )
    except RecursionError:  # nothing here calls itself by depth, but a refusal is the answer if anything did
        raise Refusal(f"the board file {name} is nested deeper than any board file is", "", "board") from None
    except MemoryError:
        raise Refusal(
            f"the board file {name} needs more memory to read than this machine has for it",
            "give the board of the power stage alone",
            "board",
        ) from None


def _checked(choose) -> dict:
    if choose is None:
        return {}
    if not isinstance(choose, dict):
        raise Refusal(
            "what was chosen is not a set of names and values",
            f"it takes {', '.join(f'{k} ({v})' for k, v in CHOICES.items())}",
            "choose",
        )
    for key in choose:
        if key not in CHOICES:
            near = get_close_matches(str(key)[:40], CHOICES, n=1)
            hint = (
                f"did you mean {near[0]}, {CHOICES[near[0]]}?"
                if near
                else f"it takes {', '.join(f'{k} ({v})' for k, v in CHOICES.items())}"
            )
            raise Refusal(f"what was chosen holds {shown(key)}, which is not a choice there is", hint, "choose")
    return choose


def _drive_out(drive: Drive | str, figures: dict | None) -> dict:
    if isinstance(drive, str):
        return {"found": False, "why": drive}
    return {
        "figures": figures,
        "found": True,
        "switch": drive.switch,
        "driver": drive.driver,
        "resistors": drive.resistors,
        "gate_net": drive.gate_net,
        "return_net": drive.return_net,
        "kelvin": drive.kelvin,
    }


def _bridge(board: Board, found: Found, leg: Leg, choose: dict, clock: Clock) -> tuple[dict, list[str]]:
    worked = leg_figures(board, found, leg, choose, clock)
    out = {
        "leg": leg.switch_node,
        "switch_node": leg.switch_node,
        "high_side": leg.high_side,
        "low_side": leg.low_side,
        "capacitors": leg.capacitors,
        "series": leg.series,
        "gate_drive": {side: _drive_out(drive, worked["each"].get(side)) for side, drive in worked["drives"].items()},
        "figures": worked["figures"],
        "mesh": worked["mesh"],
    }
    return out, worked["said"]


def layout_text(figures: dict, name: str, leg: str) -> str:
    """The figures as the layout file the switching event takes: each on a line with its band,
    one not worked out or outside what a layout file takes left as a comment."""
    from motionsim.event.layout import FIGURES

    lines = [
        f"# The switching loop of {clean(name) or 'the board'}, leg {clean(leg)}: worked out from the board file.",
        "# Each figure is yours to change. What each rests on came with the answer.",
    ]
    for key in UNITS:
        fig, (unit, _, low, high, _) = figures[key], FIGURES[key]
        if fig["value"] is None or not low <= fig["value"] <= high:
            why = (
                fig["rests_on"][0]
                if fig["value"] is None
                else f"{fig['value']:g} {unit} is outside what a layout file takes"
            )
            lines.append(f"# {key}:    # {clean(why, 120)}")
        else:
            lines.append(f"{key}: {fig['value']:g}    # {unit}, believed {fig['low']:g} to {fig['high']:g}")
    # Each line is one line whatever a name in it holds: a name can add no line, and so no figure.
    return "\n".join(" ".join(line.splitlines()) for line in lines) + "\n"


def describe(board: Board, choose: dict | None = None) -> dict:
    """The whole answer for a board already read."""
    choose = _checked(choose)
    found = find(board, choose)
    warnings = [*board.warnings, *found.said]
    if len(found.legs) > MOST_LEGS:
        left = ", ".join(leg.switch_node for leg in found.legs[MOST_LEGS:])
        warnings.append(
            Hint(
                f"{len(found.legs)} legs were found and {MOST_LEGS} are worked out at once. Choose the legs "
                f"wanted to have the others worked out: {left}",
                "switch_nodes",
            )
        )
    clock = Clock(3 * min(len(found.legs), MOST_LEGS))
    bridges = []
    for leg in found.legs[:MOST_LEGS]:
        bridge, said = _bridge(board, found, leg, choose, clock)
        bridges.append(bridge)
        warnings += said
    wanted = choose.get("leg")
    if wanted is not None and wanted not in [b["leg"] for b in bridges]:
        raise Refusal(
            f"there is no leg at {shown(wanted)}",
            f"the legs found are at {', '.join(b['leg'] for b in bridges)}",
            "choose.leg",
        )
    taken = (
        next(b for b in bridges if b["leg"] == wanted)
        if wanted
        else max(bridges, key=lambda b: round(b["figures"]["l_loop_nh"]["value"] or 0.0, 1))
    )
    if len(bridges) > 1 and not wanted:
        warnings.append(
            Hint(
                f"{len(bridges)} legs were found: the layout holds the figures of the one at {taken['leg']}, "
                "whose loop inductance is the largest. Another leg can be chosen",
                "leg",
            )
        )
    nets = board.nets()
    said = list(dict.fromkeys(w for w in warnings if w))
    return {
        "format": board.format,
        "name": board.name,
        "stackup": {
            "assumed": board.stackup.assumed,
            "said": board.stackup.said,
            "layers": [
                {"name": layer.name, "copper_um": round(layer.thickness * 1000, 3), "depth_mm": round(layer.z, 4)}
                for layer in board.stackup.layers
            ],
        },
        "nets": {
            "count": len(nets),
            "dc_plus": found.dc_plus,
            "dc_minus": found.dc_minus,
            "largest": [
                {"name": net, "pads": pads} for net, pads in sorted(nets.items(), key=lambda item: -item[1])[:12]
            ],
        },
        "parts": len(board.components),
        "bridges": bridges,
        "candidates": found.candidates,
        "taken": taken["leg"],
        "figures": taken["figures"],
        "layout": layout_text(taken["figures"], board.name, taken["leg"]),
        "warnings": said,
        # Which of the cautions a choice answers, and which choice: the name of one of CHOICES.
        "hints": [{"said": str(w), "field": w.field} for w in said if isinstance(w, Hint)],
    }


def read(path_or_bytes: str | bytes | Path, name: str | None = None, choose: dict | None = None) -> dict:
    """A board file's switching-loop figures: the format it is in, its stack-up, the half
    bridges found with what else could have been taken, the six figures of a layout file each
    with its band and what it rests on, the layout file's text, and warnings.

    path_or_bytes: the file's path, or what it holds. name: the file's name, which helps to
    tell its kind. choose: what to take in place of what is guessed (see CHOICES).
    Raises motionsim.errors.Refusal, with a reason, a fix and the field at issue, for a file
    that cannot be read and for a board no half bridge is found on.
    """
    return describe(load(path_or_bytes, name), choose)
