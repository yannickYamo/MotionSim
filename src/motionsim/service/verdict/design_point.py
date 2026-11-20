"""Devices on a motor at its design point: one with its checks, or several ranked."""

from __future__ import annotations

from motionsim import guard
from motionsim.engine import OperatingPoint
from motionsim.engine.limits import hottest
from motionsim.errors import Refusal
from motionsim.motor import Unreachable
from motionsim.propose import NO_GATE_DRIVE, RUNAWAY
from motionsim.service.answers import GATE_FIX
from motionsim.service.shapes import LEVEL_WORD, _checks, _gate_out, _result, _stage, level_of
from motionsim.service.validate import _conditions, _motor, point
from motionsim.service.verdict.common import _distinct, _gate, _sound, _unreachable
from motionsim.service.workspace import Workspace


def hardest_period(device, design, op: OperatingPoint) -> tuple[dict, float]:
    """One PWM period of the hottest switch at its hardest instant, and the junction
    temperature its energies are taken at: what the loss chart and the event plot draw."""
    from motionsim.engine.solver import switching_period

    roles = design.result.roles
    k = max(range(len(roles)), key=lambda n: roles[n].tj_switch_peak)
    out = switching_period(device, design.stage.roles[k], op, roles[k].tj_switch, roles[k].tj_diode)
    return {**out, "position": roles[k].name}, roles[k].tj_switch


def _switching_period(device, design, op: OperatingPoint) -> dict:
    """One PWM period of the hottest switch at its hardest instant, for drawing."""
    return hardest_period(device, design, op)[0]


PROBLEM_FIX = {
    NO_GATE_DRIVE: GATE_FIX,
    RUNAWAY: "this device overheats here: lower the current or switching frequency, or pick a larger part",
}


def _candidate(c, key: str, gate) -> dict:
    """One device of a comparison, as the page and the report read it."""
    ran = c.design is not None
    return {
        "id": key,
        "name": f"{c.device.vendor} {c.device.part_number}",
        "technology": c.device.technology,
        "level": LEVEL_WORD[c.level],
        "problem": c.problem,
        "fix": PROBLEM_FIX.get(c.cause, "") if c.problem else "",
        "result": _result(c.design.result, c.device.ratings.tj_max, gate.op.parallel) if ran else None,
        "stall_tj": None if c.stall is None else hottest(c.stall.result),
        "margin": c.margin,
        "stall_margin": c.stall_margin,
        "switching": None if c.footing is None else {"kind": c.footing.kind, "text": c.footing.text},
        "efficiency": c.design.system_efficiency if ran else None,
        "checks": _checks(c.checks),
        "needs": c.needs,
        "gate": _gate_out(gate),
        "pwm": _switching_period(c.device, c.design, gate.op) if ran else None,
        "link": {"capacitor_rms": c.design.capacitor_rms, "ripple_pp": c.design.ripple_pp} if ran else None,
    }


def proposal(data: dict, workspace: Workspace) -> dict:
    """Several devices on one motor at its design point: each with its losses, margins and
    checks, ranked, and the ranking in sentences."""
    from motionsim.propose import LEVEL, explain, level_with_best, propose

    motor = _motor(data["motor"])
    op = _conditions(data["conditions"], motor)
    rpm, torque = point(data["conditions"])
    keys = data.get("devices") or []
    if not keys:
        raise Refusal("no device chosen", "pick at least one device in the Devices step")
    devices = _distinct([workspace.device(k) for k in keys])
    gates = {id(d): _gate(d, op, motor, data["conditions"]) for d in devices}
    try:
        candidates = propose(devices, motor, rpm, torque, op, tune=lambda d: gates[id(d)].op)
    except Unreachable as exc:
        raise _unreachable(exc, op) from None
    by_object = {id(d): k for d, k in zip(devices, keys, strict=True)}
    return {
        "candidates": [_candidate(c, by_object[id(c.device)], gates[id(c.device)]) for c in candidates],
        "explain": explain(candidates),
        "level": LEVEL,
        # Those that lose so nearly what the best loses that the model does not tell them apart.
        "tied": [by_object[id(c.device)] for c in level_with_best(candidates)],
        "motor": {"name": motor.name, "type": motor.type},
    }


def motor_point(data: dict, workspace: Workspace) -> dict:
    """One device on one motor at a speed and torque: what the motor asks, what the device
    loses, and the checks on it there."""
    from motionsim.drivers import at_speed_and_torque

    motor = _motor(data["motor"])
    op = _conditions(data["conditions"], motor)
    rpm, torque = point(data["conditions"])
    device = workspace.device(data["device"])
    gate = _gate(device, op, motor, data["conditions"])
    op = gate.op
    try:
        found = at_speed_and_torque(device, motor, rpm, torque, op)
    except Unreachable as exc:
        raise _unreachable(exc, op) from None
    _sound(found.result)
    checks = guard.check(
        device, op, found.result, found.stage.i_peak, i_limit=guard.current_limit(motor, found.ripple_pp)
    )
    checks += guard.ripple_checks(found, op)
    tripped = guard.trip_check(motor, rpm, op.v_dc, device.ratings.v_max)
    if tripped is not None:
        checks.append(tripped)
    said = _checks(checks)
    return {
        "device": workspace.summary(data["device"], device),
        "motor": {"name": motor.name, "type": motor.type, "fixed_scheme": motor.fixed_scheme},
        "stage": _stage(found.stage, motor, op.pwm),
        "efficiency": found.system_efficiency,
        "gate": _gate_out(gate),
        "result": _result(found.result, device.ratings.tj_max, op.parallel),
        "checks": said,
        "level": level_of(said),
    }
