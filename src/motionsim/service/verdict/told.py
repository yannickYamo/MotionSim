"""Devices at a current told outright, with no motor: one point, the largest current that
passes, several side by side, and currents read from a file."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

import numpy as np

from motionsim import guard
from motionsim.device.schema import ChipKind, Device
from motionsim.engine import OperatingPoint
from motionsim.engine.limits import hottest
from motionsim.engine.notes import Code
from motionsim.errors import Refusal
from motionsim.service.shapes import _checks, _gate_out, _result, level_of
from motionsim.service.validate import _number, conditions, electrical
from motionsim.service.verdict.common import _distinct, _free_air, _sound
from motionsim.service.workspace import Workspace
from motionsim.text import written


def _told(device: Device, given: dict) -> tuple[OperatingPoint, list[str], dict | None]:
    """The conditions for a device run at a current told outright, with no motor: checked,
    then completed with what the user left open, each completion said in a line, and the
    gate drive a transistor is run with.

    As a motor's point does: a transistor's gate drive left open is chosen for the lowest
    loss the limits allow at this current, and its dead time is the one a drive with that
    gate drive would be set to, so that the same part gives the same loss here and there.
    For an IGBT the dead time changes only the voltage a motor can be given, and a point
    told its modulation outright has no use for one.
    """
    from motionsim.engine.solver import hot_share
    from motionsim.recommend import choose_gate_drive

    op = electrical(given, conditions(given))
    lines: list[str] = []
    free = _free_air(device, given)
    if free is not None:
        op = replace(op, rth_free=free.rth_free, rth_board=free.rth_board)
        lines += free.lines
    gate = None
    if device.switch.kind is ChipKind.mosfet:
        # At no current told (the largest current is still to be found) the gate is chosen
        # for the part's rated current.
        i_peak = (op.i_rms or device.ratings.i_nominal) * math.sqrt(2) * hot_share(device, op.parallel)
        chosen = choose_gate_drive(device, op, max(i_peak, 1e-3))
        op = chosen.op
        lines += chosen.lines
        gate = _gate_out(chosen)
    _reachable(device, op)
    return op, lines, gate


def _reachable(device: Device, op: OperatingPoint) -> None:
    """A point told its modulation outright is held to the voltage the stage can give, as a
    motor's point is: a stage that keeps less than half of it is refused, and a modulation
    index that asks for more than it keeps is one the stage cannot make."""
    from motionsim.drivers import _usable

    usable = _usable(device, op, op.i_rms * math.sqrt(2))
    most = usable * op.pwm.max_modulation_index
    if op.modulation_index > most + 1e-9:
        raise Refusal(
            f"a modulation index of {written(op.modulation_index, 3)} asks for more than the stage can give: "
            f"dead time, the shortest pulse and the devices' drop leave {usable:.1%} of the ideal output voltage, "
            f"a modulation index of {written(most, 3)} at most",
            "lower the modulation index, shorten the dead time or the shortest pulse, or raise the supply",
            "m",
        )


def simulate(data: dict, workspace: Workspace) -> dict:
    """One device at one operating point told outright: current, modulation index and power
    factor. Its losses and temperatures, and the same checks a design is judged by."""
    from motionsim.engine import solve

    device = workspace.device(data["device"])
    op, lines, gate = _told(device, data["conditions"])
    result = solve(device, op)
    _sound(result)
    checks = _checks(guard.check(device, op, result, op.i_rms * math.sqrt(2)))
    return {
        "device": workspace.summary(data["device"], device),
        "taken": lines,
        "gate": gate,
        "result": _result(result, device.ratings.tj_max, op.parallel),
        "checks": checks,
        "level": level_of(checks),
    }


def _limit(data: dict, device: Device, op: OperatingPoint) -> tuple[float, str | None]:
    """The junction temperature the largest current is held to: the part's rating unless a
    lower one is asked for. One above the rating is not a limit the part has, so the rating
    is used and said to be."""
    rating = device.ratings.tj_max
    asked = data.get("tj_limit")
    limit = (
        rating
        if asked in ("", None)
        else _number(asked, "junction temperature limit", low=-40, high=1000, field="tj_limit")
    )
    said = None
    if limit > rating:
        said = (
            f"the junction temperature limit asked, {written(limit, 4)} °C, is above the part's "
            f"{written(rating, 4)} °C rating: the rating is used"
        )
        limit = rating
    if op.t_sink >= limit:
        cooling = (
            "the air around the part" if data["conditions"].get("cooling") in ("none", "board") else "the heatsink"
        )
        raise Refusal(
            f"{cooling} is at {written(op.t_sink, 4)} °C, not below the {written(limit, 4)} °C the junction "
            "is held to, so no current is small enough",
            "lower the heatsink temperature, or raise the limit up to the part's rating",
            "t_sink",
        )
    return limit, said


def largest_current(data: dict, workspace: Workspace) -> dict:
    """The largest phase current that passes: the one at which the top of the hottest
    junction's range, across the thermal assumptions and what the loss drawn beyond the data
    could add, reaches the limit. The current at which the typical estimate alone reaches it
    is given beside it, and how much of the answer the datasheet's data covers.

    On the average junction temperature, which has no range, the typical estimate is the
    answer."""
    from motionsim.engine.limits import max_current, supported_current

    device = workspace.device(data["device"])
    op, lines, gate = _told(device, {**data["conditions"], "i_rms": 0.0})
    limit, capped = _limit(data, device, op)
    peak = not data.get("average")
    typical, _ = max_current(device, op, tj_limit=limit, peak=peak)
    i_max, result = max_current(device, op, tj_limit=limit, peak=peak, bound=peak)
    # The stage's drop grows with the current, so the voltage it keeps is judged at the answer.
    _reachable(device, replace(op, i_rms=i_max))
    answer: dict[str, Any] = {
        "device": workspace.summary(data["device"], device),
        "taken": lines,
        "gate": gate,
        "i_max": i_max,
        "i_max_typical": typical,
        "tj_limit": limit,
        # Said where the limit asked for was above the rating, and the rating used instead.
        "limit_note": capped,
        "basis": "range" if peak else "average",
        "covered": supported_current(device, op, i_max),
        "result": None,
        "checks": [],
        "level": "ok",
    }
    if result is not None:
        _sound(result)
        at = replace(op, i_rms=i_max)
        # The junction is at its limit because that is what was asked for, so the margin to
        # it says nothing. A temperature check that does not pass is kept: it would mean the
        # answer is not one.
        found = [
            c
            for c in guard.check(device, at, result, i_max * math.sqrt(2))
            if c.topic != "temperature" or c.level in (guard.Level.fail, guard.Level.undecided)
        ]
        answer["checks"] = _checks(found)
        answer["level"] = level_of(answer["checks"])
        answer["result"] = _result(result, device.ratings.tj_max, op.parallel)
    return answer


def _row(key: str, device: Device, given: dict, workspace: Workspace) -> dict:
    """One device of a comparison at a current told outright."""
    from motionsim.engine import ThermalRunaway, solve
    from motionsim.propose import switching_footing

    op, lines, gate = _told(device, given)
    row = {
        "id": key,
        "name": f"{device.vendor} {device.part_number}",
        "part_number": device.part_number,
        "taken": lines,
        "gate": gate,
        "switching": switching_footing(device, op).text,
        "result": None,
        "margin": None,
        "checks": [],
        "level": "fail",
        "problem": None,
    }
    try:
        result = solve(device, op)
    except ThermalRunaway as exc:
        # Temperatures that settle far above the data are not a runaway, and are not said as one.
        return {**row, "problem": "thermal runaway" if exc.code is Code.thermal_runaway else str(exc)}
    _sound(result)
    checks = _checks(guard.check(device, op, result, op.i_rms * math.sqrt(2)))
    return {
        **row,
        "result": _result(result, device.ratings.tj_max, op.parallel),
        "margin": device.ratings.tj_max - hottest(result),
        "checks": checks,
        "level": level_of(checks),
    }


MOST_SWEEP = 50  # switching frequencies in one sweep


def _sweep(data: dict, devices: list[Device], given: dict) -> dict | None:
    """Loss against switching frequency for each device, and where two of them cross."""
    from motionsim.engine.compare import crossover, sweep_switching_frequency

    asked = data.get("sweep_f_sw")
    if asked in ("", None):
        return None
    if not isinstance(asked, list) or len(asked) != 2:
        raise Refusal("a sweep of the switching frequency is two figures: from and to, in Hz", "", "sweep_f_sw")
    low, high = (_number(v, "switching frequency", low=100, high=1e7, field="sweep_f_sw") for v in asked)
    count = int(_number(data.get("sweep_points", 10), "sweep points", low=2, high=MOST_SWEEP, field="sweep_points"))
    frequencies = np.linspace(low, high, count)
    # One set of conditions for every device: a sweep is of the frequency alone.
    table = sweep_switching_frequency(devices, electrical(given, conditions(given)), frequencies)
    crossings = []
    for a in range(len(devices)):
        for b in range(a + 1, len(devices)):
            at = crossover(frequencies, table[a], table[b])
            if at is not None:
                crossings.append({"a": devices[a].part_number, "b": devices[b].part_number, "f_sw": at})
    return {
        "f_sw": frequencies.tolist(),
        "loss": [[None if math.isnan(v) else float(v) for v in row] for row in table],
        "crossings": crossings,
    }


def compare(data: dict, workspace: Workspace) -> dict:
    """Several devices at one operating point told outright, least loss first, those with
    no stable temperature last."""
    keys = data.get("devices") or []
    devices = _distinct([workspace.device(k) for k in keys])
    rows = [_row(k, d, data["conditions"], workspace) for k, d in zip(keys, devices, strict=True)]
    rows.sort(key=lambda r: (r["result"] is None, r["result"]["loss"] if r["result"] else 0))
    ran = [r for r in rows if r["result"] is not None]
    passing = [r for r in ran if r["level"] in ("ok", "caution")]
    open_ = [r for r in ran if r["level"] == "undecided"]
    return {
        "rows": rows,
        "sweep": _sweep(data, devices, data["conditions"]),
        "level": "ok" if passing else "undecided" if open_ else "fail",
    }


def trajectory(data: dict, workspace: Workspace) -> dict:
    """One device along currents and duty cycles read from a file, taken to repeat without
    end, and run once from a cold start."""
    from motionsim.trajectory import parse_trajectory, run

    device = workspace.device(data["device"])
    given = data["conditions"]
    if (given.get("cooling") or "held") != "held":
        raise Refusal("a trajectory is followed on a heatsink at a known temperature", "give t_sink", "cooling")
    op = conditions(given)
    text = data.get("trajectory")
    if not isinstance(text, str):
        raise Refusal(
            "the trajectory comes as the text of its file", "see `motionsim template trajectory`", "trajectory"
        )
    followed = parse_trajectory(text)
    outcome = run(device, followed, op)
    _sound(outcome.result)
    # The check on current is against the most any leg carries at any instant.
    i_peak = max(float(np.abs(i).max()) for i in followed.current.values())
    checks = _checks(guard.check(device, op, outcome.result, i_peak))
    return {
        "device": workspace.summary(data["device"], device),
        "duration": followed.duration,
        "legs": len(followed.legs),
        "i_peak": i_peak,
        "peak_from_start": outcome.peak_from_start,
        "time": outcome.time.tolist(),
        "tj_from_start": outcome.tj_from_start.tolist(),
        "result": _result(outcome.result, device.ratings.tj_max, op.parallel),
        "checks": checks,
        "level": level_of(checks),
    }
