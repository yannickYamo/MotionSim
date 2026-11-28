"""What to build the stage with at the design point: gate resistors, dead time, the PWM
scheme, the field current, and the heatsink. Starting values for a first prototype."""

from __future__ import annotations

from dataclasses import replace

from motionsim.engine import OperatingPoint, Pwm, ThermalRunaway
from motionsim.engine.limits import hottest
from motionsim.engine.mosfet import MissingGateDrive
from motionsim.engine.notes import Code, coded
from motionsim.errors import BadFigure
from motionsim.motor import Unreachable
from motionsim.service.validate import _conditions, _motor, _number, point
from motionsim.service.verdict import _gate, _unreachable
from motionsim.service.workspace import Workspace
from motionsim.text import written

# Why one way of running the stage has no loss to compare: the motor cannot be there, the
# part overheats, or it has no gate drive to switch with. Anything else is a fault.
NO_ANSWER = (Unreachable, ThermalRunaway, MissingGateDrive, BadFigure)


def _optional(data: dict, key: str, name: str, low: float, high: float) -> float | None:
    return None if data.get(key) in ("", None) else _number(data[key], name, low=low, high=high, field=key)


def _resistors(data: dict, device, gate, asked: OperatingPoint, i_peak: float):
    """Gate resistors: the datasheet's or the built-in driver's where those are in use,
    worked out otherwise with what the user gave and the usual values where they gave none."""
    from motionsim import recommend
    from motionsim.engine.solver import hot_share

    op = gate.op
    if gate.kind in ("datasheet", "built in"):
        return recommend.Recommendation("gate resistors", lines=gate.lines)
    probe = replace(op, l_loop=op.l_loop if op.l_loop is not None else recommend.USUAL_LOOP)
    limits = {}
    if (dvdt := _optional(data, "dvdt", "switching speed limit", 0.01, 1000)) is not None:
        limits["dvdt_max"] = dvdt * 1e9  # given in V/ns
    # Each device of those in parallel switches its own share in its own loop: the same
    # current the gate drive in use was chosen at, so the two never say different things.
    found = recommend.gate_resistors(
        device,
        probe,
        max(i_peak * hot_share(device, op.parallel), 1e-3),
        driver_peak=_optional(data, "driver_peak", "gate driver peak current", 1e-3, 1000),
        **limits,
    )
    yours = asked.rg_on is not None and asked.rg_off is not None
    return recommend.Recommendation(
        found.topic,
        found.value,
        [*coded(gate.lines, Code.gate_drive_taken, Code.loop_inductance_taken)]
        + found.lines
        + (
            [f"you gave {asked.rg_on:g} ohm on and {asked.rg_off:g} ohm off; the results use yours"]
            if yours
            else ["the results use these values, since you gave none"]
        ),
    )


def _dead_time(data: dict, device, motor, rpm: float, torque: float, op: OperatingPoint):
    """The dead time, and for a transistor run shorter than firmware's usual default, what
    that default would cost."""
    from motionsim import recommend
    from motionsim.drivers import at_speed_and_torque

    mismatch = _optional(data, "driver_mismatch", "driver delay mismatch", 0, 1e-5)
    dead = recommend.dead_time(device, op, **({} if mismatch is None else {"driver_mismatch": mismatch}))
    if not (dead.value.get("t_dead") and op.t_dead < recommend.COMMON_FIRMWARE and device.diode is None):
        return dead
    try:
        now = at_speed_and_torque(device, motor, rpm, torque, op, spread=False).result.p_inverter
        then = at_speed_and_torque(
            device, motor, rpm, torque, replace(op, t_dead=recommend.COMMON_FIRMWARE), spread=False
        ).result.p_inverter
    except NO_ANSWER:
        return dead
    return recommend.Recommendation(
        dead.topic,
        {**dead.value, "loss_at_common": then},
        dead.lines
        + [
            f"open motor-control firmware often runs 300 to 800 ns by default: at {recommend.COMMON_FIRMWARE * 1e9:.0f} ns "
            f"the stage would lose {written(then, 3)} W, {written(then - now, 2)} W more than at the {op.t_dead * 1e9:.0f} ns used here",
        ],
    )


def _schemes(device, motor, rpm: float, torque: float, op: OperatingPoint):
    """The loss with each PWM scheme the motor can be driven with."""
    from motionsim import recommend
    from motionsim.drivers import at_speed_and_torque

    losses = {}
    if motor.fixed_scheme is None:
        for scheme in Pwm:
            try:
                found = at_speed_and_torque(device, motor, rpm, torque, replace(op, pwm=scheme))
            except NO_ANSWER:
                continue
            losses[scheme.value] = found.result.p_inverter
    return recommend.modulation(losses, motor.default_pwm.value)


ALONE = (
    "With no heatsink at all, a package may have up to {alone:.0f} K/W from junction to air (RthJA on the "
    "datasheet) for its hottest junction to stay 25 K under its rating, counting the hardest-worked one, running and held still. A TO-220 "
    "standing free has about 62, a TO-247 about 40, a surface-mount part on its copper 40 to 60"
)
NEVER_ALONE = "With no heatsink at all the hardest-worked package's junction would come within 25 °C of its rating whatever its path to the air"


def _heatsink(data: dict, device, motor, rpm: float, torque: float, op: OperatingPoint):
    """The heatsink the design point needs, running and held still, and what a package
    standing alone in air would need in its place."""
    from motionsim import recommend
    from motionsim.drivers import at_speed_and_torque

    def evaluate(t_sink: float) -> tuple[float, float]:
        worst, loss = float("-inf"), 0.0
        held = replace(op, t_sink=t_sink, rth_sink=None, rth_free=None, rth_board=None)
        for speed in (rpm, 0.0):
            try:
                at = at_speed_and_torque(device, motor, speed, torque, held)
            except Unreachable:
                continue
            # The top of the spread across the thermal assumptions: the heatsink has to do for all of them.
            top = at.result.tj_peak_range[1] if at.result.tj_peak_range else hottest(at.result)
            worst, loss = max(worst, top), max(loss, at.result.p_inverter)
        return worst, loss

    # Cooled to air, the air is the one given with the cooling; with a heatsink held at
    # a temperature it is the one given for sizing a heatsink. Zero is a temperature.
    in_air = (data["conditions"].get("cooling") or "held") != "held"
    air = data["conditions"].get("t_ambient") if in_air else data.get("t_ambient")
    ambient = _number(40 if air in ("", None) else air, "air temperature", low=-40, high=120, field="t_ambient")
    sink = recommend.heatsink(
        device,
        ambient,
        evaluate,
        sink_limit=_optional(data["conditions"], "t_sink_max", "highest heatsink temperature", -40, 250),
    )
    if not sink.value.get("loss"):
        return sink
    alone = _alone_in_air(device, motor, rpm, torque, op, ambient)
    if alone is None:
        return recommend.Recommendation(sink.topic, sink.value, [*sink.lines, NEVER_ALONE])
    return recommend.Recommendation(
        sink.topic, {**sink.value, "rth_ja": alone}, [*sink.lines, ALONE.format(alone=alone)]
    )


def recommendations(data: dict, workspace: Workspace) -> dict:
    """Starting values for building the stage, each with the lines that say where it came from."""
    from motionsim import recommend

    motor = _motor(data["motor"])
    asked = _conditions(data["conditions"], motor)
    device = workspace.device(data["device"])
    rpm, torque = point(data["conditions"])
    try:
        st = motor.stage(rpm, torque, asked.v_dc, asked.pwm)
    except Unreachable as exc:
        raise _unreachable(exc, asked) from None
    gate = _gate(device, asked, motor, data["conditions"])
    op = gate.op
    out = [
        _resistors(data, device, gate, asked, st.i_peak),
        _dead_time(data, device, motor, rpm, torque, op),
        _schemes(device, motor, rpm, torque, op),
    ]
    if (d_axis := recommend.least_loss_d_axis(device, motor, rpm, torque, op)) is not None:
        out.append(d_axis)
    out.append(_heatsink(data, device, motor, rpm, torque, op))
    return {"items": [{"topic": r.topic, "value": r.value, "lines": r.lines} for r in out]}


def _alone_in_air(device, motor, rpm: float, torque: float, op: OperatingPoint, ambient: float) -> float | None:
    """The largest junction-to-air resistance of one package, K/W, that keeps the hottest
    junction 25 K under its rating with no heatsink, at the design point and held still.

    Found by solving with the package in air, not by sharing the loss out evenly: at
    standstill, and on a motor driven in six steps or through an H-bridge, one package does
    far more than its share.
    """
    from motionsim.drivers import at_speed_and_torque

    limit = device.ratings.tj_max - 25.0
    inside = max(c.thermal.rth for c in (device.switch, device.diode) if c is not None)

    def worst(case_to_air: float) -> float:
        air = replace(op, t_sink=ambient, rth_sink=None, rth_board=None, rth_free=case_to_air)
        top = float("-inf")
        for speed in (rpm, 0.0):
            try:
                top = max(top, hottest(at_speed_and_torque(device, motor, speed, torque, air, spread=False).result))
            except Unreachable:
                continue
            except ThermalRunaway:
                return float("inf")
        return top

    low, high = 0.0, 1000.0
    if worst(1e-3) > limit:
        return None
    if worst(high) <= limit:
        return high + inside
    for _ in range(24):
        mid = 0.5 * (low + high)
        low, high = (mid, high) if worst(mid) <= limit else (low, mid)
    return low + inside
