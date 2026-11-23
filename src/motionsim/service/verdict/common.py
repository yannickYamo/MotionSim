"""What every verdict reads: the cooling with no heatsink, the gate drive a device is run
with, what to change where the motor cannot do what is asked, and a result's figures held
to be numbers."""

from __future__ import annotations

import math
from dataclasses import replace

from motionsim.device.schema import Device
from motionsim.engine import OperatingPoint
from motionsim.engine.notes import Code
from motionsim.errors import Fault, Refusal
from motionsim.motor import Unreachable
from motionsim.service.validate import _number, point, turns_slower_than_switched


def _free_air(device, conditions: dict, packages: int | None = None):
    """With no heatsink: what lies between a package's case and the air, standing alone
    or soldered to a board with the others (see cooling.py)."""
    from motionsim.cooling import no_heatsink

    kind = conditions.get("cooling") or "held"
    if kind not in ("none", "board"):
        return None

    def given(key: str, name: str) -> float | None:
        return (
            None
            if conditions.get(key) in ("", None)
            else _number(conditions[key], name, low=0.01, high=100000, field=key)
        )

    area = given("board_area", "board area") if kind == "board" else None
    if kind == "board" and area is None:
        raise Refusal(
            "the board's area is needed", "give the area of the board the power stage is on, in cm²", "board_area"
        )
    copper = given("copper", "copper area") if kind == "board" else None
    copper_ref = given("copper_ref", "the datasheet's copper area") if kind == "board" else None
    # A figure that is missing or cannot be is refused by no_heatsink itself, with the name
    # of the figure at issue: nothing here reads its words or guesses which it was.
    return no_heatsink(
        device,
        given("rth_ja", "junction to air"),
        board_area=area,
        copper=copper,
        copper_ref=copper_ref,
        packages=packages,
    )


def _gate(device, op: OperatingPoint, motor, conditions: dict):
    """The gate drive this device is run with: the user's, or chosen for the lowest loss the
    limits allow where they left it open. The current is the design point's peak."""
    from motionsim.recommend import choose_gate_drive

    try:
        rpm, torque = point(conditions)
        asked = motor.stage(rpm, torque, op.v_dc, op.pwm)
        i_peak = asked.i_peak
        positions = sum(r.count for r in asked.roles)
        packages = -(-positions // device.package.topology.positions) * op.parallel
    except (Unreachable, Refusal, ValueError):
        i_peak, packages = device.ratings.i_nominal, None
    # Each device of those in parallel switches its own share in its own loop.
    from motionsim.engine.solver import hot_share

    free = _free_air(device, conditions, packages)
    if free is not None:
        op = replace(op, rth_free=free.rth_free, rth_board=free.rth_board)
    gate = choose_gate_drive(device, op, max(i_peak * hot_share(device, op.parallel), 1e-3))
    return gate if free is None else replace(gate, lines=[*gate.lines, *free.lines])


# What to change, by the limit that stops the motor. The motor (or the stage under it) says
# which limit that is with the code its refusal carries: its words are for the user, and
# may be reworded at any time.
FIXES: dict[Code, str] = {
    Code.reach_voltage: (
        "lower the speed or the torque, raise the supply voltage, or choose a motor wound for this voltage"
    ),
    Code.reach_drop: "raise the supply voltage, lower the current, or choose a device with a lower drop",
    Code.reach_current: "lower the torque, or raise the motor's current limit if the winding allows it",
    Code.reach_torque: "lower the torque or choose a larger stepper",
    Code.reach_timing: "lower the switching frequency, or give a shorter dead time",
    Code.reach_other: "change the speed or torque",
}


def _switched(motor, op: OperatingPoint, conditions: dict) -> None:
    """The design point's output against the switching frequency, before anything is solved:
    refused where the motor turns faster than the stage switches. A point the motor cannot
    reach is left for the solve to refuse with its own reason."""
    rpm, torque = point(conditions)
    try:
        asked = motor.stage(rpm, torque, op.v_dc, op.pwm)
    except (Unreachable, ValueError):
        return
    turns_slower_than_switched(asked, op.f_sw)


def _unreachable(exc: Unreachable, op: OperatingPoint) -> Refusal:
    fix = FIXES.get(exc.code, FIXES[Code.reach_other])
    return Refusal(f"this motor cannot do that from {op.v_dc:g} V: {exc}", fix, "point", exc.code)


def _sound(result) -> None:
    """A result with a figure that is not a number is no result: a fault of the tool, said
    as one, and never handed over as an answer with a status that reads as success."""
    figures = (result.p_inverter, result.tj_switch_peak, result.tj_diode_peak, result.t_case)
    if not all(math.isfinite(x) for x in figures):
        raise Fault("the losses or temperatures came out as not a number")


def _distinct(devices: list[Device]) -> list[Device]:
    """The devices, those whose name another before them has numbered by their place, so
    that two parts of one name are two rows a reader can tell apart."""
    seen: dict[str, int] = {}
    out = []
    for d in devices:
        name = f"{d.vendor} {d.part_number}"
        seen[name] = seen.get(name, 0) + 1
        out.append(d if seen[name] == 1 else d.model_copy(update={"part_number": f"{d.part_number} ({seen[name]})"}))
    return out
