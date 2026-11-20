"""The motor before any device is set against it: what it asks of the stage, and whether it
fits the part under test at all."""

from __future__ import annotations

import math
from typing import Any

from motionsim.motor import Unreachable
from motionsim.service.shapes import _stage
from motionsim.service.validate import _conditions, _motor, _number, point
from motionsim.service.validate import supply as _supply
from motionsim.service.verdict.common import _unreachable
from motionsim.service.workspace import Workspace
from motionsim.text import rounded, written


def _reach(motor, v_dc: float, *, rpm: float | None = None, torque: float | None = None) -> tuple[float, Any]:
    """The most of one thing a motor can do from a supply, with the other held: the top
    speed at a torque, or the top torque at a speed. Found by asking the motor, kind by
    kind, whether it can be there: no formula of its own to disagree with the engine."""
    pwm = motor.default_pwm

    def at(value: float):
        try:
            return motor.stage(value if rpm is None else rpm, torque if rpm is None else value, v_dc, pwm)
        except (Unreachable, ValueError, ZeroDivisionError, FloatingPointError):
            return None

    low, best = 0.0, at(0.0)
    high = 1.0
    while high < 1e7 and at(high) is not None:
        low, best, high = high, at(high), high * 2
    if high >= 1e7:
        return float("inf"), best
    for _ in range(40):
        mid = 0.5 * (low + high)
        found = at(mid)
        if found is not None:
            low, best = mid, found
        else:
            high = mid
    return low, best


def _speed_lines(asked, top_rpm: float, v_dc: float) -> list[dict]:
    """Speed: only against the speed asked for. How fast a motor could turn with its field
    weakened to nothing is a figure of the model, not of the motor."""
    if asked in ("", None):
        return []
    asked = abs(_number(asked, "speed", field="rpm"))
    if top_rpm >= asked:
        return [{"level": "ok", "text": f"from {v_dc:g} V this motor reaches the {asked:,.0f} rpm of the design point"}]
    return [
        {
            "level": "caution",
            "text": f"from {v_dc:g} V this motor reaches about {rounded(top_rpm, 2):,.0f} rpm with no load, short of the "
            f"{asked:,.0f} rpm of the design point: it is wound for a higher voltage than this part suits. Lower the "
            "speed in the next step, or use a motor wound for this voltage",
        }
    ]


def _current_line(device, parallel: int, i_peak: float, torque: float, limited: bool) -> dict:
    """The most current the motor can ask for, against what the part is rated to carry."""
    rated = device.ratings.i_nominal * parallel
    what = "at its current limit" if limited else "held still with nothing but its winding resistance to limit it"
    if i_peak <= rated * 1.02:
        return {
            "level": "ok",
            "text": f"{what} this motor draws {written(i_peak, 3)} A peak for {written(torque, 3)} N·m, within the part's {rated:g} A rating",
        }
    fix = (
        f"use {math.ceil(i_peak / device.ratings.i_nominal)} of this part in parallel, a part rated for {rounded(i_peak, 2):g} A, "
        "or a current limit in the drive at what the part can carry"
    )
    return {
        "level": "caution",
        "text": f"{what} this motor draws {written(i_peak, 3)} A peak, and the part is rated {rated:g} A"
        + (f" ({parallel} in parallel)" if parallel > 1 else "")
        + f": the part can take it to about {100 * rated / i_peak:.0f}% of the {written(torque, 3)} N·m it can give. To use all of the motor, {fix}",
    }


def motor_fit(data: dict, workspace: Workspace) -> dict:
    """Whether the motor as described fits the part under test, before any design point is
    given: what the motor can ask of a power stage at most, set against what the part is
    rated for. Said at the motor step, so that a motor too large for the part, or wound for
    another voltage, is known before the user goes on."""
    from motionsim.advise import motors_for
    from motionsim.motor_class import part_figures

    motor = _motor(data["motor"])
    device = workspace.device(data["device"])
    parallel = int(_number(data.get("parallel") or 1, "devices in parallel", low=1, high=12, field="parallel"))
    bus, fits = motors_for(*part_figures(device))
    given = data.get("v_dc") not in ("", None)
    v_dc = _number(data["v_dc"], "supply voltage", low=1, high=2000, field="v_dc") if given else float(bus)
    lines: list[dict] = []
    say = lambda level, text: lines.append({"level": level, "text": text})  # noqa: E731
    kind = data["motor"].get("type")
    if kind in fits and fits[kind].fit == "unusual":
        say("caution", fits[kind].why)

    top_rpm, _ = _reach(motor, v_dc, torque=0.0)
    if top_rpm <= 1.0:
        say(
            "caution",
            f"from {v_dc:g} V this motor does not turn at all: it is wound for a much higher voltage, or one of its "
            "figures is in the wrong unit",
        )
        return {
            "v_supply": v_dc,
            "top_rpm": 0.0,
            "i_peak": None,
            "i_rated": device.ratings.i_nominal * parallel,
            "level": "caution",
            "lines": lines,
        }
    # The most current it can ask for is at standstill, where no back-EMF opposes it.
    torque, hardest = _reach(motor, v_dc, rpm=0.0)
    i_peak = None if hardest is None else float(hardest.i_peak)
    rated = device.ratings.i_nominal * parallel
    limited = getattr(motor, "i_max", None) is not None or getattr(motor, "i_phase", None) is not None
    lines += _speed_lines(data.get("rpm"), top_rpm, v_dc)
    if i_peak is not None and torque not in (0.0, float("inf")):
        lines.append(_current_line(device, parallel, i_peak, torque, limited))
    level = "caution" if any(x["level"] == "caution" for x in lines) else "ok"
    return {
        "v_supply": v_dc,
        "top_rpm": None if top_rpm == float("inf") else top_rpm,
        "i_peak": i_peak,
        "i_rated": rated,
        "torque": None if torque == float("inf") else torque,
        "level": level,
        "lines": lines,
    }


def stage(data: dict) -> dict:
    """What the motor asks of the power stage, before any device is chosen."""
    from motionsim.advise import advise

    motor = _motor(data["motor"])
    op = _conditions(data["conditions"], motor)
    rpm, torque = point(data["conditions"])
    try:
        st = motor.stage(rpm, torque, op.v_dc, op.pwm)
        advice = advise(motor, rpm, torque, op.v_dc, op.f_sw, supply=_supply(data))
    except Unreachable as exc:
        raise _unreachable(exc, op) from None
    return {
        "stage": _stage(st, motor, op.pwm),
        "advice": {
            "lines": advice.lines,
            "v_minimum": advice.v_minimum,
            "v_comfortable": advice.v_comfortable,
            "i_peak": advice.i_peak,
            "i_stall": advice.i_stall,
        },
    }
