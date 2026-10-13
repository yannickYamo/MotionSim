"""Cooling with no heatsink: one package in the air, or several soldered to one board.

A datasheet gives a transistor's thermal resistance from junction to air for the way it was
tested: a leaded package standing free, or a surface-mount one on a stated area of copper,
alone on its board. A power stage is six or more of them. Two things then differ from the
datasheet, and both are worked out here from published figures.

The copper each package has. Datasheets print how junction-to-air falls as the copper pad
grows; the relations printed for the TO-263 and for the DPAK are the same curve to within
3% when each is taken as a ratio to its value at one square inch, so one curve is used for
any surface-mount package:

    R(A) proportional to 26.51 + 128 / (1.69 + A),  A in cm²

The neighbours. A board loses heat to still air from both faces at about 10 W/(m²·K),
convection and radiation together, so all the stage's loss warms the whole board by
P / (2 h A_board). A package sits above the air by its own loss through its own resistance
plus what its neighbours put into the board, and never less than the board's own rise.

Left out: the number of copper layers and vias (which help), how close the packages are
(the inner ones run a few kelvin hotter), any airflow or enclosure, and heat leaving by the
wires. The board is taken as one temperature for the neighbours' share, which is on the
warm side for a single-layer board and close for one with copper planes.
"""

from __future__ import annotations

from dataclasses import dataclass

from motionsim.device.schema import Device
from motionsim.text import written

# Junction to still air of one package, K/W, as datasheets give it: the leaded outlines
# standing free, the surface-mount one on a square inch of copper.
FREE_AIR = {"TO-220": 62.0, "TO-247": 40.0, "TO-263": 43.0}
REFERENCE_COPPER = 6.45  # cm², one square inch: what most datasheets take the figure on
STILL_AIR = 10.0  # W/(m²·K), a board's face to still air, convection and radiation
BOARD_LIMIT = 120.0  # °C, above which ordinary board material is past its rating
# °C, the most a heatsink is let reach when one is sized: the junctions may stand more, but
# the board, the capacitors, the connectors and the plastic fixed to it do not.
HEATSINK_LIMIT = 100.0


def _pad(area_cm2: float) -> float:
    """How junction-to-air follows the copper pad's area, up to a constant factor."""
    return 26.51 + 128.0 / (1.69 + area_cm2)


def on_copper(rth_ja: float, copper: float, reference: float = REFERENCE_COPPER) -> float:
    """The datasheet's junction-to-air figure, taken on `reference` cm² of copper, brought
    to a pad of `copper` cm²."""
    return rth_ja * _pad(copper) / _pad(reference)


def board_to_air(area_cm2: float) -> float:
    """K/W from a board of this area to still air, both faces."""
    return 1.0 / (2.0 * STILL_AIR * area_cm2 * 1e-4)


@dataclass(frozen=True)
class NoHeatsink:
    rth_free: float  # K/W, one package's case to the air
    rth_board: float | None  # K/W, what each watt lost anywhere on the board adds; None: alone
    rth_ja: float  # K/W, junction to air as used
    lines: list[str]


def no_heatsink(
    device: Device,
    rth_ja: float | None = None,
    *,
    board_area: float | None = None,
    copper: float | None = None,
    copper_ref: float | None = None,
    packages: int | None = None,
) -> NoHeatsink:
    """What lies between a package's case and the air with no heatsink.

    board_area, in cm², says the packages are soldered to one board of that size; left
    out, each stands alone in the air. copper is the pad each package has, cm², and
    copper_ref the pad the datasheet's figure was taken on; packages is how many share the
    board, where known, so that pads that cannot all fit are refused. Raises ValueError with what
    is missing or cannot be.
    """
    lines: list[str] = []
    usual = FREE_AIR.get(device.package.outline or "")
    if rth_ja is None:
        if usual is None:
            raise ValueError(
                "with no heatsink, the thermal resistance from junction to air is needed: RthJA from "
                "the datasheet, in K/W (about 62 for a TO-220 standing free, 40 for a TO-247, 40 to "
                "50 for a surface-mount part on a square inch of copper)"
            )
        rth_ja = usual
        lines.append(f"junction to air taken as {usual:g} K/W, usual for a {device.package.outline}")
    inside = max(c.thermal.rth for c in (device.switch, device.diode) if c is not None)
    reference = REFERENCE_COPPER if copper_ref is None else copper_ref
    if board_area is None:
        if copper is not None:
            raise ValueError("a copper area needs the board's area as well: the packages then share a board")
        used, rth_board = rth_ja, None
    else:
        pad = reference if copper is None else copper
        if pad <= 0 or reference <= 0 or board_area <= 0:
            raise ValueError("the copper and board areas have to be above zero")
        count = max(int(packages or 1), 1)
        if pad * count > board_area:
            each = "one package" if count == 1 else f"each of {count} packages"
            raise ValueError(f"{pad:g} cm² of copper for {each} does not fit on a {board_area:g} cm² board")
        used = on_copper(rth_ja, pad, reference)
        rth_board = board_to_air(board_area)
        if abs(pad - reference) > 1e-9:
            lines.append(
                f"junction to air {rth_ja:g} K/W on {reference:g} cm² of copper is {written(used, 3)} K/W on the "
                f"{pad:g} cm² each package has"
            )
        lines.append(
            f"the packages share a {board_area:g} cm² board, which still air cools at {written(rth_board, 3)} K/W: "
            "each one is warmed by its neighbours' loss through that"
        )
    if used <= inside:
        raise ValueError(
            f"junction to air of {written(used, 3)} K/W is not above this part's {inside:g} K/W from junction "
            "to case: give the junction-to-air figure, RthJA"
        )
    return NoHeatsink(used - inside, rth_board, used, lines)
