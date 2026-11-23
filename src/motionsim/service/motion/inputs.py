"""A motion as it is asked for, checked and put in the form the engine follows: the motor,
the conditions, the load and how it moves or a mission profile, the heatsink and the start."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from motionsim.device.schema import Device
from motionsim.engine import OperatingPoint
from motionsim.engine.notes import Code, code_of
from motionsim.errors import Refusal
from motionsim.load import Load, Profile
from motionsim.service.answers import reason_of
from motionsim.service.validate import MOST_SPEED, MOST_TORQUE, _conditions, _count, _motor, _number
from motionsim.service.verdict import _gate
from motionsim.service.workspace import Workspace
from motionsim.text import rounded, written

if TYPE_CHECKING:
    from motionsim.starting import Start
    from motionsim.transient import Heatsink
from motionsim.service.motion.start import _sensorless, _start

MOST_POINTS = 600  # of a mission profile: more are thinned, keeping every peak


def _mission(given) -> list | None:
    """A mission profile as the instants the engine steps through: time in s, motor speed
    in rpm and motor torque in N·m at each. Each instant stands until the next."""
    if not given:
        return None
    from motionsim.load import Sample

    try:
        time = [float(v) for v in given["time"]]
        rpm = [float(v) for v in given["rpm"]]
        torque = [float(v) for v in given["torque"]]
    except (KeyError, TypeError, ValueError):
        raise Refusal(
            "the mission profile is not three columns of numbers",
            "give time in seconds, speed in rpm and torque in N·m, one row an instant",
            "mission",
        ) from None
    if not (len(time) == len(rpm) == len(torque)) or len(time) < 2:
        raise Refusal(
            "the mission profile needs at least two rows, with all three columns filled", "check the file", "mission"
        )
    if any(b <= a for a, b in zip(time, time[1:], strict=False)) or not all(map(math.isfinite, time + rpm + torque)):
        raise Refusal("the mission profile's time does not run forward", "sort the rows by time", "mission")
    _within_any_motor(zip(time, rpm, torque, strict=True), "mission", time[0])
    if len(time) > MOST_POINTS:
        # Thin by keeping, in each stretch, the instant that asks the most torque.
        edges = np.linspace(0, len(time), MOST_POINTS + 1).astype(int)
        keep = sorted(
            {int(a + np.argmax(np.abs(torque[a:b]))) for a, b in zip(edges, edges[1:], strict=False) if b > a}
            | {0, len(time) - 1}
        )
        time, rpm, torque = [time[k] for k in keep], [rpm[k] for k in keep], [torque[k] for k in keep]
    spans = [b - a for a, b in zip(time, time[1:], strict=False)]
    spans.append(spans[-1])
    return [
        Sample(t - time[0], dt, n * math.pi / 30, 0.0, 0.0, n, tq)
        for t, dt, n, tq in zip(time, spans, rpm, torque, strict=True)
    ]


def _within_any_motor(instants, field: str, t0: float = 0.0) -> None:
    """A motion that asks of the motor a speed or a torque past any motor's is a slip, refused
    at the first instant that does: by the bounds a design point is held to, at the motor's
    shaft, so a gear between it and the load is counted."""
    for t, rpm, torque in instants:
        if abs(rpm) > MOST_SPEED or abs(torque) > MOST_TORQUE:
            asked, most = (
                (f"{rpm:.3g} rpm", f"{MOST_SPEED:,.0f} rpm")
                if abs(rpm) > MOST_SPEED
                else (
                    f"{torque:.3g} N·m",
                    f"{MOST_TORQUE:,.0f} N·m",
                )
            )
            raise Refusal(
                f"the motion asks {asked} of the motor at {written(t - t0, 3)} s, past any motor: {most} at most",
                "check the motion's speeds and torques, their units, and the gear ratio",
                field,
            )


MOST_SEGMENTS = 500  # stretches in one motion
MOST_INSTANTS = 40_000  # instants followed in one answer, the repeats counted


@dataclass(frozen=True)
class Motion:
    """A motion as asked, checked and ready to follow."""

    device: Device
    motor: Any  # one of the machines of motor.machines
    op: OperatingPoint  # with the gate drive in use
    load: Load | None
    profile: Profile | None
    mission: list | None  # a mission profile's own instants, in place of a load and its motion
    sink: Heatsink | None  # a heatsink followed as it warms
    repeats: int
    start: Start | None
    starting: dict
    per_segment: int
    taken: list[str] = field(default_factory=list)  # what was filled in for the user, said
    samples: list | None = None  # a duty's own instants, worked out once
    runups: list = field(default_factory=list)  # each stretch run up at the current limit
    method: dict = field(default_factory=dict)  # how the heatsink is followed, and why


def _load_and_profile(data: dict, mission) -> tuple[Load | None, Profile | None]:
    from pydantic import ValidationError

    segments = (data.get("profile") or {}).get("segments") if isinstance(data.get("profile"), dict) else None
    if isinstance(segments, list) and len(segments) > MOST_SEGMENTS:
        raise Refusal(
            f"the motion has {len(segments)} stretches, and {MOST_SEGMENTS} is the most followed",
            "join stretches, or give the motion as a mission profile of instants",
            "profile",
        )
    try:
        return Load.model_validate(data["load"]), Profile.model_validate(data["profile"])
    except (ValidationError, KeyError) as exc:  # figures that do not make a load or a motion
        if mission is None:
            said, field = _load_figure(exc) if isinstance(exc, ValidationError) else (reason_of(exc), "")
            raise Refusal(
                f"the load or motion values do not fit: {said}",
                "check the load and motion values",
                field,
            ) from None
        return None, None


# Each figure of a load by where it sits in it: the name of its box in the load's form, what
# it is in words, and its unit. A weight on an arm, a vehicle and a tumbling load each have a
# mass, and a refusal says which.
LOAD_FIGURES: dict[tuple[str, ...], tuple[str, str, str]] = {
    ("gear_ratio",): ("gear_ratio", "the gear ratio", ""),
    ("gear_efficiency",): ("gear_efficiency", "the gear efficiency", ""),
    ("motor_inertia",): ("motor_inertia", "the rotor inertia", "kg·m²"),
    ("inertia",): ("inertia", "the load inertia", "kg·m²"),
    ("constant_torque",): ("constant_torque", "the steady torque", "N·m"),
    ("friction_coulomb",): ("friction_coulomb", "the friction", "N·m"),
    ("friction_viscous",): ("friction_viscous", "the friction growing with speed", "N·m per rad/s"),
    ("fan_coefficient",): ("fan_coefficient", "the fan constant", "N·m per (rad/s)²"),
    ("gravity", "mass"): ("mass", "the weight on the arm", "kg"),
    ("gravity", "arm"): ("arm", "the arm length", "m"),
    ("vehicle", "mass"): ("v_mass", "the mass carried", "kg"),
    ("vehicle", "wheel_radius"): ("wheel_radius", "the wheel radius", "m"),
    ("vehicle", "rolling_resistance"): ("rolling_resistance", "the rolling resistance", ""),
    ("vehicle", "drag_area"): ("drag_area", "the drag area", "m²"),
    ("vehicle", "slope_percent"): ("slope_percent", "the slope", "%"),
    ("tumble", "mass"): ("tumble_mass", "the tumbling load", "kg"),
    ("tumble", "radius"): ("tumble_radius", "the drum radius", "m"),
    ("pulsation", "torque"): ("pulsation_torque", "the torque pulse", "N·m"),
    ("pulsation", "per_turn"): ("pulsation_per_turn", "the pulses in a turn", ""),
    ("breakaway", "torque"): ("breakaway_torque", "the break-away torque", "N·m"),
    ("breakaway", "rpm"): ("breakaway_rpm", "the speed the break-away torque is gone by", "rpm"),
}
BOUNDS = ("greater_than", "greater_than_equal", "less_than", "less_than_equal")  # refusals that end in a figure


def _load_figure(exc) -> tuple[str, str]:
    """What a load's or a motion's figures were refused for, and the box of the figure: a
    load's own figure by its name in the load's form, with its unit after the bound."""
    from motionsim.text import plain_error

    error = exc.errors()[0]
    place = tuple(str(part) for part in error.get("loc", ()))
    if exc.title != "Load" or place not in LOAD_FIGURES:
        return reason_of(exc), ""
    field, words, unit = LOAD_FIGURES[place]
    said, _ = plain_error(error, {place[-1]: words})
    return (f"{said} {unit}" if unit and error.get("type") in BOUNDS else said), field


# A heatsink in air given without its heat capacity is taken to reach 63% of its rise in this
# time. Extruded aluminium heatsinks hold about 500 to 800 cm³ for each K/W in still air and
# 100 to 300 with a fan, a third of it metal at 2.4 J/(cm³·K): R·C comes to 370 to 580 s in
# still air and 70 to 220 s with a fan, whatever the size. 300 s lies between, on the warm
# side of a heatsink in still air.
SINK_TAU = 300.0  # s
# A motion shorter than this share of the heatsink's time constant moves it by little within
# one run: it is followed at the temperature its mean loss puts it at. Longer, or held until
# steady, the heatsink is followed from cold.
PERIODIC_SHARE = 0.1


def sink_method(op: OperatingPoint, given: dict, length: float, steady: bool) -> tuple[dict, float | None]:
    """How a heatsink in air is followed through a motion of this length, and the heat
    capacity taken for it where none was given: the rule, in figures and words."""
    capacity = (
        None
        if given.get("capacity") in ("", None)
        else _number(given["capacity"], "heatsink heat capacity", low=0.1, field="capacity")
    )
    tau = op.rth_sink * capacity if capacity and op.rth_sink else SINK_TAU
    if op.rth_sink is None:
        return {"method": "held" if op.rth_free is None else "own air", "tau": None}, None
    short = length <= PERIODIC_SHARE * tau and not steady
    if capacity is not None:
        return {"method": "from cold", "tau": tau, "capacity": capacity, "assumed": False}, capacity
    if short:
        return {"method": "periodic", "tau": tau, "capacity": None, "assumed": False, "length": length}, None
    return {
        "method": "from cold",
        "tau": tau,
        "capacity": rounded(SINK_TAU / op.rth_sink, 3),
        "assumed": True,
        "length": length,
    }, rounded(SINK_TAU / op.rth_sink, 3)


def _heatsink(data: dict, op: OperatingPoint, length: float = 0.0, steady: bool = False):
    """The heatsink to follow as it warms, where its heat capacity is given or the motion is
    long beside a heatsink's time constant: one in air from cold, or one held at a
    temperature given its own way to the air. Returns it, and how it is followed."""
    from motionsim.transient import Heatsink

    h = data.get("heatsink")
    h = h if isinstance(h, dict) else {}
    # Each figure given is held to what it can be, whether or not this motion's cooling comes
    # to use it: a resistance below nought is a slip wherever it was typed. Nought itself is
    # refused too, since the heatsink's time constant is its resistance times its capacity.
    rth = (
        None
        if h.get("rth") in ("", None)
        else _number(h["rth"], "heatsink resistance", low=0.01, high=500, field="rth")
    )
    method, capacity = sink_method(op, h, length, steady)
    given = (
        None
        if h.get("capacity") in ("", None)
        else _number(h["capacity"], "heatsink heat capacity", low=0.1, field="capacity")
    )
    own = op.rth_sink is None and op.rth_free is None and rth is not None and given is not None
    # Followed, the heatsink cools to this air: up to 150 °C. Not followed, the figure may be
    # the heatsink's own temperature, handed on where no air was given: up to its 200 °C.
    ambient = (
        None
        if h.get("t_ambient") in ("", None)
        else _number(h["t_ambient"], "ambient temperature", low=-40, high=150 if own else 200, field="t_ambient")
    )
    if op.rth_sink is not None and capacity:
        return Heatsink(
            rth=op.rth_sink, capacity=capacity, t_ambient=op.t_sink, assumed=method.get("assumed", False)
        ), method
    if own:
        assert rth is not None and given is not None
        return Heatsink(
            rth=rth,
            capacity=given,
            # The air is where the heatsink starts from, where no other is given.
            t_ambient=_number(op.t_sink, "ambient temperature", low=-40, high=150, field="t_ambient")
            if ambient is None
            else ambient,
        ), {"method": "from cold", "tau": None}
    return None, method


def motion_inputs(data: dict, workspace: Workspace) -> Motion:
    """Everything a motion is followed with, checked: the motor and conditions, the device
    and its gate drive, the load and its motion or a mission profile, the heatsink, how
    often it repeats and how the drive starts."""
    motor = _motor(data["motor"])
    op = _conditions(data["conditions"], motor)
    device = workspace.device(data["device"])
    gate = _gate(device, op, motor, data["conditions"])
    op = gate.op
    taken = [line for line in gate.lines if code_of(line) in (Code.dead_time_taken, Code.dead_time_estimated)]
    mission = _mission(data.get("mission"))
    load, profile = _load_and_profile(data, mission)
    repeats = _count(data.get("repeats", 1), "repeats", low=1, high=50, field="repeats")
    per_segment = 6 if data.get("coarse") else 12
    samples: list | None = None
    runups: list = []
    if mission is None and load is not None and profile is not None:
        from motionsim import guard
        from motionsim.duty import limited
        from motionsim.load import sample

        if any(s.at_limit for s, _ in profile.stretches()):
            profile, runups = limited(profile, load, motor, op.v_dc, op.pwm, guard.current_limit(motor))
        found = sample(load, profile, per_segment if profile.is_duty else 2)
        _within_any_motor(((x.time, x.motor_rpm, x.motor_torque) for x in found), "profile")
        if profile.is_duty or any(s.until_steady or s.slope_percent is not None for s, _ in profile.stretches()):
            samples = found
    stretches = 0 if profile is None else len(profile.stretches())
    counted = len(samples) if samples is not None else stretches * per_segment
    instants = (len(mission) if mission is not None else counted) * repeats
    if instants > MOST_INSTANTS:
        raise Refusal(
            f"this motion is {instants} instants with its repeats, and {MOST_INSTANTS} is the most followed",
            "run it fewer times, or describe it in fewer stretches",
            "repeats",
        )
    start, starting = _start(data, motor, op)
    _sensorless(starting, device, motor, op, data["conditions"])
    length = (
        mission[-1].time + mission[-1].duration
        if mission is not None
        else (profile.duration if profile is not None else 0.0)
    )
    steady = profile is not None and any(s.until_steady for s, _ in profile.stretches())
    sink, method = _heatsink(data, op, length * repeats, steady)
    if sink is not None and sink.assumed:
        taken.append(
            f"heatsink heat capacity taken as {written(sink.capacity, 3)} J/K, the usual for {written(sink.rth, 3)} K/W: "
            f"it reaches 63% of its rise in {SINK_TAU / 60:g} minutes. Give yours to replace it"
        )
    return Motion(
        device,
        motor,
        op,
        load,
        profile,
        mission,
        sink,
        repeats,
        start,
        starting,
        per_segment,
        taken,
        samples=samples,
        runups=runups,
        method=method,
    )
