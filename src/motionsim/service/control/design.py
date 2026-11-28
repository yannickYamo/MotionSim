"""The design a control-lab request describes: the motor, the conditions, the device and the
load brought to what the schemes are tuned from, and the controller's own figures of the
stage read from the loss engine's answer."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

from motionsim import guard
from motionsim.control.plant import simple_load
from motionsim.control.presets import BUILDERS, Design, chosen
from motionsim.control.scheme import Scheme, scheme_from
from motionsim.control.stage import StageModel
from motionsim.errors import Refusal
from motionsim.service.validate import _conditions, _motor, _number, point
from motionsim.service.workspace import Workspace
from motionsim.text import written

# Each kind of motor the lab does not simulate, as it is said.
OTHER_MOTORS = {
    "induction": "an induction motor",
    "bldc": "a block-commutated brushless motor",
    "dc": "a brushed DC motor",
    "stepper": "a stepper motor",
    "synrm": "a synchronous reluctance motor",
}


def _pmsm(data: dict):
    motor = _motor(data["motor"])
    if motor.type != "pmsm":
        named = OTHER_MOTORS.get(motor.type, "of another kind")
        raise Refusal(
            f"the control lab simulates permanent-magnet synchronous motors, and this motor is {named}",
            "the lab opens once the motor on step 2 is a permanent-magnet synchronous one",
            "motor",
        )
    return motor


def _shaft(data: dict, taken: list[str]) -> tuple[float | None, Any]:
    """The inertia at the motor's shaft and the load's torque there, from the tool's own load
    description or from four figures at the shaft. (None, None) where neither is given."""
    simple = data.get("shaft")
    if simple is not None:
        if not isinstance(simple, dict):
            raise Refusal("the shaft is not a set of names and values", "give its figures by name", "shaft")
        unknown = [k for k in simple if k not in ("inertia", "constant", "viscous", "quadratic")]
        if unknown:
            raise Refusal(
                f"the shaft has no figure called {unknown[0]}", "inertia, constant, viscous or quadratic", "shaft"
            )
        inertia = _number(
            simple.get("inertia"), "the shaft's inertia", low=1e-12, high=1e9, field="shaft.inertia", unit="kg·m²"
        )
        terms = [
            _number(simple.get(k, 0.0), f"the shaft's {k} torque", low=0, high=1e9, field=f"shaft.{k}", unit="")
            for k in ("constant", "viscous", "quadratic")
        ]
        return inertia, terms
    if data.get("load") is None:
        return None, None
    from pydantic import ValidationError

    from motionsim.load import Load
    from motionsim.service.answers import reason_of

    try:
        load = Load.model_validate(data["load"])
    except ValidationError as exc:
        raise Refusal(f"the load values do not fit: {reason_of(exc)}", "check the load values", "load") from None
    gear = load.gear_ratio
    # What one more rad/s² at the load asks of the motor, over what that is at the motor.
    inertia = (load.at_motor(0.0, 2.0)[1] - load.at_motor(0.0, 1.0)[1]) / gear
    taken.append(
        f"the load is brought to the motor's shaft through its {gear:g}:1 gear: {written(inertia, 3)} kg·m² of "
        "inertia, and the torque it asks at each speed and angle with nothing accelerating"
    )
    return (inertia if inertia > 0 else None), load


def _application(data: dict, taken: list[str]) -> str | None:
    """The application the design is for: the one given, or, for a made-up part with none
    given, the application that part is tried on (the page sends one only once a load has
    been picked)."""
    from motionsim.service.applications import APPLICATIONS
    from motionsim.service.workspace import USES

    given = data.get("application")
    if isinstance(given, str) and given:
        return given
    device = data.get("device")
    use = USES.get(device) if isinstance(device, str) else None
    if use is None:
        return None
    taken.append(
        f"no application is given: the one this made-up part is tried on, {APPLICATIONS[use.application].label.lower()}, "
        "is taken for the scheme it starts on"
    )
    return use.application


def _weight(load: Any) -> float:
    """N·m at the motor's shaft that a weight on the load asks with its arm level, where it asks the
    most: the load's torque there less its torque hanging, which leaves its friction out."""
    if load is None or isinstance(load, list) or getattr(load, "gravity", None) is None:
        return 0.0
    return float(load.at_motor(0.0, 0.0, math.pi / 2)[1] - load.at_motor(0.0, 0.0, 0.0)[1])


def _standstill(load: Any, mean: bool = False) -> float:
    """N·m the load asks of a shaft that is just leaving rest, at the motor's shaft: what an
    open-loop start has to overcome before there is any speed to speak of. The most it asks
    anywhere in a turn, or (`mean`) its mean over the turn, which is what the shaft's inertia
    is run up against while a torque that pulses with the angle is ridden through."""
    if isinstance(load, list):
        return float(load[0])
    if load is not None:
        # Creeping forward: a torque that pulses with the angle has to be passed at its peak.
        creep = 1e-3
        asked = [abs(float(load.at_motor(creep, 0.0, 2.0 * math.pi * k / 72.0)[1])) for k in range(72)]
        return sum(asked) / len(asked) if mean else max(asked)
    return 0.0  # the load taken where none is given asks nothing at rest


def _mean_load(load: Any, design: Design, peak: bool = False):
    """N·m the load asks at a shaft speed, its mean over a turn of the load (or the most it
    asks in the turn): what a default test is worked out against (scenario.sized)."""
    asked = _load_torque(load, design, [])
    if load is None or isinstance(load, list):
        return lambda speed: float(asked(speed, 0.0, 0.0))
    angles = [2.0 * math.pi * k / 24.0 for k in range(24)]
    gear = load.gear_ratio

    def over_a_turn(speed: float) -> float:
        found = [float(asked(speed, a * gear, 0.0)) for a in angles]
        return max(found) if peak else sum(found) / len(found)

    return over_a_turn


def _load_torque(load: Any, design: Design, taken: list[str]):
    """The torque the load asks at the motor's shaft, as the plant calls it."""
    if isinstance(load, list):
        constant, viscous, quadratic = load
        return simple_load(constant, viscous, quadratic, still=max(abs(design.omega), 1.0) * 1e-3)
    if load is not None:
        gear = load.gear_ratio
        return lambda speed, angle, t: load.at_motor(speed / gear, 0.0, angle / gear)[1]
    if design.torque * design.omega < 0:
        # A regenerating point: no load that opposes the motion asks that of the drive.
        taken.append(
            "no load is given, and the design point regenerates: a load that drives the shaft with the design "
            "torque at every speed is taken, as a mass being lowered does"
        )
        return lambda speed, angle, t: design.torque
    taken.append(
        "no load is given: one whose torque grows with the speed and asks the design torque at the design "
        "speed is taken"
    )
    return simple_load(viscous=abs(design.torque) / max(abs(design.omega), 1e-9) if design.omega else 0.0)


def _designed(data: dict, workspace: Workspace) -> tuple[Design, dict]:
    """The design a request describes, as the presets are tuned from it, and what else the
    run needs: the device, the conditions with the gate drive in use, and what was taken."""
    from motionsim.drivers import _usable
    from motionsim.service.verdict.common import _gate, _switched

    motor = _pmsm(data)
    given = data["conditions"]
    op = _conditions(given, motor)
    rpm, torque = point(given)
    _switched(motor, op, given)
    taken: list[str] = []
    device = gate = None
    if isinstance(data.get("device"), str) and data["device"]:
        device = workspace.device(data["device"])
        gate = _gate(device, op, motor, given)
        op = gate.op
    if motor.i_sat:
        taken.append("the motor's inductances are taken as constants: saturation is left out of the control lab")
    # Iron loss is torque the shaft never sees: the windings supply it, as in the loss engine.
    w = abs(rpm) * math.pi / 30.0
    iron = motor.iron_loss(rpm) if w > 0 else 0.0
    asked = torque + (math.copysign(iron / w, rpm) if iron else 0.0)
    plain = motor.model_copy(update={"i_sat": None})
    usable = 1.0 - 2.0 * (op.t_dead + op.t_min_pulse) * op.f_sw
    if device is not None:
        usable = _usable(device, op, plain.stage(rpm, asked, op.v_dc, op.pwm).i_peak)
    state = plain.model_copy(update={"usable_voltage": usable}).state(rpm, asked, op.v_dc, op.pwm)
    inertia, load = _shaft(data, taken)
    application = _application(data, taken)
    i_design = math.hypot(state.i_d, state.i_q)
    design = Design(
        rs=motor.rs,
        ld=motor.ld,
        lq=motor.lq,
        psi=motor.flux_linkage,
        pole_pairs=motor.pole_pairs,
        v_dc=op.v_dc,
        f_sw=op.f_sw,
        pwm=op.pwm,
        rpm=rpm,
        torque=asked,
        i_design=i_design,
        i_limit=guard.current_limit(motor),
        inertia=inertia,
        usable=usable,
        application=application if isinstance(application, str) else None,
        t_dead=op.t_dead,
        v_drop=_drop(device, op, i_design)[0] if device is not None else 0.0,
        stage=stage_model(device, motor, rpm, torque, op) if device is not None else None,
        iron=motor.iron_loss if motor.iron_loss(1000.0) > 0 else None,
        load_standstill=_standstill(load),
        load_rest_mean=_standstill(load, mean=True),
        weight=_weight(load),
        gear=float(getattr(load, "gear_ratio", 1.0)) if load is not None and not isinstance(load, list) else 1.0,
    )
    if inertia is None:
        taken.append(
            f"no inertia is given: {written(design.shaft_inertia, 3)} kg·m² is taken, which the torque limit runs "
            "up to the design speed in a quarter of a second"
        )
    if design.i_limit is None:
        taken.append(
            f"the motor gives no current limit: the drive is set to {written(design.limit / math.sqrt(2), 3)} A rms, "
            "1.5 times the design point's current"
        )
    design = replace(design, inertia=design.shaft_inertia, inertia_assumed=inertia is None)
    design = replace(design, load_at=_mean_load(load, design), load_peak_at=_mean_load(load, design, peak=True))
    return design, {
        "motor": motor,
        "torque": torque,
        "op": op,
        "device": device,
        "gate": gate,
        "load": load,
        "taken": taken,
        "supply": _supply_kind(data, workspace),
    }


def _drop(device, op, current: float) -> tuple[float, float]:
    """The device's own conduction curve as a line through its drop at half and at all of a
    current: the knee in V and the slope in ohm of one switch position."""
    import numpy as np

    from motionsim.engine.losses import voltage

    share = max(int(op.parallel), 1)
    half, whole = (float(v) for v in voltage(device.switch, np.array([0.5, 1.0]) * current / share, op.t_sink))
    slope = max(2.0 * (whole - half) / max(current, 1e-9), 0.0)
    return max(whole - slope * current, 0.0), slope


def _lines(device, motor, rpm: float, torque: float, op) -> tuple[float, float, float, float] | None:
    """The stage's conduction and switching as two lines in the current (v0, r, e0, e1),
    through the loss engine's own answer at the design point and at half its torque."""
    from motionsim.drivers import at_speed_and_torque
    from motionsim.service.shapes import _result

    points = []
    for share in (1.0, 0.5):
        found = at_speed_and_torque(device, motor, rpm, share * torque, op, spread=False)
        shaped = _result(found.result, device.ratings.tj_max, op.parallel)
        points.append((found.stage.i_peak, shaped["conduction"], shaped["switching"]))
    (i1, c1, s1), (i2, c2, s2) = points
    if not (i1 > i2 > 0 and op.f_sw > 0):
        return None
    # Conduction of a sine of peak i: 3·(v0·2i/π + r·i²/2). Switching: 3·f·(e0 + e1·2i/π).
    r = max(2.0 * (c1 / i1 - c2 / i2) / (3.0 * (i1 - i2)), 0.0)
    v0 = max((c1 / 3.0 - 0.5 * r * i1 * i1) * math.pi / (2.0 * i1), 0.0)
    e1 = max((s1 - s2) * math.pi / (6.0 * op.f_sw * (i1 - i2)), 0.0)
    e0 = max(s1 / (3.0 * op.f_sw) - e1 * 2.0 * i1 / math.pi, 0.0)
    return v0, r, e0, e1


def stage_model(device, motor, rpm: float, torque: float, op) -> StageModel | None:
    """The controller's own figures of the stage (control/stage.py), read from the loss
    engine: two lines through its answer at the design point and at half its torque, and the
    junction's thermal network down to the sink. The network's terms faster than two sampling
    periods are taken together as one with no delay, which is all a sampled estimate can
    make of them. None where the engine cannot answer at the design point."""
    from motionsim.engine.paths import case_sink
    from motionsim.engine.solver import shared_time, thermal_network

    try:
        lines = _lines(device, motor, rpm, torque, op)
    except Refusal:
        lines = None
    if lines is None:
        return None
    network = thermal_network(device, device.switch)[0]
    taus = network.tau or [0.0] * len(network.r)
    terms = [(r, tau) for r, tau in zip(network.r, taus, strict=True)]
    under = op.rth_free if op.rth_free is not None else case_sink(device, "typical", op)
    if under > 0:
        terms.append((under, shared_time(device, op)))
    if op.rth_sink:
        terms.append((6.0 * op.rth_sink, 0.0))  # every switch's loss through the one heatsink, taken alike
    fast = 2.0 / op.f_sw
    kept = [(r, tau) for r, tau in terms if tau >= fast]
    at_once = sum(r for r, tau in terms if tau < fast)
    if at_once > 0:
        kept.append((at_once, 0.0))
    return StageModel(
        *lines,
        f_sw=op.f_sw,
        t_sink=op.t_sink,
        r_th=tuple(r for r, _ in kept),
        tau=tuple(tau for _, tau in kept),
        tj_max=float(device.ratings.tj_max),
        reverse_in_switch=device.diode is None,
    )


def _schemes_named(design: Design) -> str:
    """Every scheme there is for a design, each by its label with its id in parentheses."""
    return "; ".join(build(design).named for build in BUILDERS.values())


def _scheme(data: dict, design: Design) -> Scheme:
    given = data.get("scheme")
    if given in (None, ""):
        return BUILDERS[chosen(design)[0]](design)
    if isinstance(given, str):
        if given not in BUILDERS:
            raise Refusal(f"there is no scheme called {given}", f"one of {_schemes_named(design)}", "scheme")
        return BUILDERS[given](design)
    return scheme_from(given)


def _design_out(design: Design) -> dict:
    return {
        "rpm": design.rpm,
        "torque": design.torque,
        "v_dc": design.v_dc,
        "f_sw": design.f_sw,
        "f_out": design.f_out,
        "carrier_ratio": design.f_sw / design.f_out if design.f_out > 0 else None,
        "i_design": design.i_design,
        "i_limit": design.limit,
        "torque_limit": design.torque_limit,
        "inertia": design.shaft_inertia,
        "load_standstill": design.load_standstill,
        "usable": design.usable,
        "pwm": design.pwm.value,
    }


def _supply_kind(data: dict, workspace: Workspace) -> str:
    """Whether the supply takes energy back, as the lab reads it: a mains front end that
    returns energy counts as a battery does. Where the request names no stage, the one
    recommended is the one the link is run with, and is the one read here too."""
    from motionsim.front_end import TOPOLOGIES
    from motionsim.service.validate import supply

    if data.get("supply") != "mains":
        # Any other word is kept as the page sent it, as before: only a battery is read as taking energy back.
        return data.get("supply") or "one-way"
    if (data.get("front_end") or {}).get("topology"):
        return supply(data)
    from motionsim.service.front_end import front_end

    try:
        chosen = front_end(data, workspace)["chosen"]
    except Refusal:
        return "one-way"
    return "battery" if TOPOLOGIES[chosen].returns else "one-way"
