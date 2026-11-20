"""The cooling figure the tool can offer where the user chose a cooling and left its figure
empty: worked out from the loss at the design point, never put in the box by itself (D160).

- A heatsink in air: the heatsink-to-air resistance that holds the heatsink at the
  temperature a held heatsink starts at, 60 °C. With the heatsink held there, the stage loses
  P; a heatsink of (60 − T_air) / P in air of T_air then sits at 60 °C with the same loss,
  which is the same answer. It is rounded down, so the heatsink is never warmer than that.
- A board: the smallest board area on which the verdict's own check of the junction is
  decided: the hottest junction, at the top of its range across the thermal assumptions and
  with what the loss drawn beyond the datasheet's data could add, under its rating at the
  design point. Found by halving in the logarithm of the area, by the board model of
  cooling.py: the loss grows with temperature, so there is no closed form. Rounded up.

The figure is the user's to take: a verdict on it says it was sized by the tool, and is held
at a caution, since a cooling sized to the answer cannot also confirm it.
"""

from __future__ import annotations

import math

from motionsim.engine import ThermalRunaway
from motionsim.engine.caveats import SIZED_SINK
from motionsim.errors import Refusal
from motionsim.guard import Level, temperature_check
from motionsim.motor import Unreachable
from motionsim.service.validate import _conditions, _motor, _number, point
from motionsim.service.verdict.common import _free_air, _gate, _unreachable
from motionsim.service.workspace import Workspace

LEAST_AREA, MOST_AREA = 1.0, 10000.0  # cm²: from a postage stamp to a metre square
HALVINGS = 14  # of the logarithm of that span: to under 0.06% of the area


def _rounded(x: float, way) -> float:
    """x to two significant figures, rounded the way given (math.floor or math.ceil)."""
    places = 1 - math.floor(math.log10(x))
    return round(way(round(x * 10.0**places, 9)) / 10.0**places, max(places, 0))


def _down(x: float) -> float:
    """x to two significant figures, never above it."""
    return _rounded(x, math.floor)


def _up(x: float) -> float:
    """x to two significant figures, never below it."""
    return _rounded(x, math.ceil)


def _solved(data: dict, conditions: dict, workspace: Workspace, *, spread: bool):
    """The device at the design point with these conditions, and the operating point it ran at."""
    from motionsim.drivers import at_speed_and_torque

    motor = _motor(data["motor"])
    op = _conditions(conditions, motor)
    device = workspace.device(data["device"])
    rpm, torque = point(conditions)
    gate = _gate(device, op, motor, conditions)
    try:
        return at_speed_and_torque(device, motor, rpm, torque, gate.op, spread=spread).result, gate.op
    except Unreachable as exc:
        raise _unreachable(exc, op) from None


def _air(conditions: dict) -> float:
    air = conditions.get("t_ambient")
    return _number(40 if air in ("", None) else air, "air temperature", low=-40, high=120, field="t_ambient")


def heatsink_offer(data: dict, workspace: Workspace) -> dict:
    """The heatsink in air that holds the heatsink at 60 °C at the design point."""
    c = data["conditions"]
    air = _air(c)
    held = {**c, "cooling": "held", "t_sink": SIZED_SINK, "sized": ""}
    result, _ = _solved(data, held, workspace, spread=False)
    loss = result.p_inverter
    offer = {"cooling": "heatsink", "figure": "rth_sink", "held": SIZED_SINK, "t_ambient": air, "loss": loss}
    if air >= SIZED_SINK:
        return {
            **offer,
            "value": None,
            "why": f"the air is at {air:g} °C: no heatsink in it is held at {SIZED_SINK:g} °C",
        }
    if not loss > 0:
        return {**offer, "value": None, "why": "the stage loses nothing here, so any heatsink does"}
    exact = (SIZED_SINK - air) / loss
    return {**offer, "value": _down(exact), "exact": exact}


def _board(data: dict, c: dict, area: float, workspace: Workspace) -> Level:
    """The verdict's own check of the junction on a board of this area: failed where the
    junction runs away or the packages' copper does not fit."""
    device = workspace.device(data["device"])
    try:
        result, op = _solved(data, {**c, "board_area": area, "sized": ""}, workspace, spread=True)
    except ThermalRunaway:
        return Level.fail
    except Refusal as exc:
        if exc.field == "copper":  # the packages' copper does not fit on a board this small
            return Level.fail
        raise
    return temperature_check(device, op, result, junction_margin=0.0).level


def board_offer(data: dict, workspace: Workspace) -> dict:
    """The smallest board on which the verdict on the junction is decided at the design point."""
    c = data["conditions"]
    device = workspace.device(data["device"])
    offer = {"cooling": "board", "figure": "board_area", "tj_max": device.ratings.tj_max}
    _free_air(device, {**c, "board_area": MOST_AREA})  # what else the board needs is refused here, in its words

    def fits(area: float) -> bool:
        return _board(data, c, area, workspace) not in (Level.fail, Level.undecided)

    largest = _board(data, c, MOST_AREA, workspace)
    if largest is Level.fail:
        return {**offer, "value": None, "why": "no board keeps the junction under its rating here: it needs a heatsink"}
    if largest is Level.undecided:
        why = (
            "no board gives a decided verdict here: part of the loss is drawn beyond the datasheet's data, "
            "and on any board it could take the junction over its rating. A heatsink, or the datasheet's "
            "own curve up to this current, would settle it"
        )
        return {**offer, "value": None, "why": why}
    low, high = math.log(LEAST_AREA), math.log(MOST_AREA)
    if fits(LEAST_AREA):
        return {**offer, "value": LEAST_AREA, "exact": LEAST_AREA}
    for _ in range(HALVINGS):
        middle = (low + high) / 2
        low, high = (low, middle) if fits(math.exp(middle)) else (middle, high)
    return {**offer, "value": _up(math.exp(high)), "exact": math.exp(high)}


def cooling_offer(data: dict, workspace: Workspace) -> dict:
    """The figure to offer for the cooling chosen: a heatsink in air or a board."""
    kind = data["conditions"].get("cooling") or "held"
    if kind == "heatsink":
        return heatsink_offer(data, workspace)
    if kind == "board":
        return board_offer(data, workspace)
    raise Refusal("only a heatsink in air and a board are sized by the tool", "choose one of those coolings", "cooling")
