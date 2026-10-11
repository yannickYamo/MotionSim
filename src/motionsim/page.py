"""What the page asks of the engine, and the shape of each answer.

These functions are the page's whole interface to the engine. They run in two
places without change: behind the local server that `motionsim serve` starts,
and inside the browser itself, where the page loads this package and calls
them directly. Either way every number comes from the engine; what is added
here is the shape the page needs, and the reason and the fix when an input
cannot work.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import replace
from pathlib import Path

import numpy as np
import yaml

from motionsim import guard
from motionsim.device import load_device
from motionsim.device.schema import Device
from motionsim.engine import OperatingPoint, Pwm, ThermalRunaway
from motionsim.engine.limits import hottest
from motionsim.load import LOAD_TEMPLATE, PROFILE_TEMPLATE, Load, Profile
from motionsim.motor import TEMPLATES, Unreachable
from motionsim.motor.machines import _ADAPTER

EXAMPLE = Path(__file__).parent / "example_device.yaml"

# What the page shows beside each motor value. The values themselves come from the
# templates, so the page and `motionsim template` never drift apart.
FIELDS = {
    "pmsm": [
        ("magnets", "Magnets", "", "surface: on the rotor face, inner or outer rotor alike. inset: set into the face. interior: buried, adds reluctance torque", ["surface", "inset", "interior"]),
        ("pole_pairs", "Pole pairs", "", "Number of magnet poles divided by two", None),
        ("kv", "Speed constant Kv", "rpm/V", "From the motor's catalogue page", None),
        ("l", "Phase inductance", "H", "Line-to-line inductance divided by two", None),
        ("rs", "Phase resistance", "Ω", "Line-to-line resistance divided by two", None),
        ("i_max", "Current limit", "A rms", "The winding's rated current, if you know it", None),
    ],
    "synrm": [
        ("pole_pairs", "Pole pairs", "", "", None),
        ("ld", "Easy-axis inductance Ld", "H", "The larger of the two", None),
        ("lq", "Cross-axis inductance Lq", "H", "Must be smaller than Ld; the difference makes the torque", None),
        ("rs", "Phase resistance", "Ω", "", None),
        ("i_max", "Current limit", "A rms", "", None),
    ],
    "induction": [
        ("pole_pairs", "Pole pairs", "", "Two pole pairs turn at about 1500 rpm on 50 Hz", None),
        ("rs", "Stator resistance", "Ω", "Per phase", None),
        ("rr", "Rotor resistance", "Ω", "Referred to the stator", None),
        ("lm", "Magnetising inductance", "H", "", None),
        ("lls", "Stator leakage", "H", "", None),
        ("llr", "Rotor leakage", "H", "", None),
        ("i_magnetising", "Magnetising current", "A peak", "About the no-load current", None),
        ("i_max", "Current limit", "A rms", "The winding's rated current, if you know it", None),
    ],
    "bldc": [
        ("pole_pairs", "Pole pairs", "", "Number of magnet poles divided by two", None),
        ("kt", "Torque constant Kt", "N·m/A", "9.55 divided by Kv in rpm per volt", None),
        ("r", "Resistance", "Ω", "Phase to phase", None),
        ("l", "Inductance", "H", "Phase to phase. Sets the current ripple; leave empty if unknown", None),
        ("i_max", "Current limit", "A", "", None),
    ],
    "dc": [
        ("kt", "Torque constant Kt", "N·m/A", "", None),
        ("r", "Armature resistance", "Ω", "", None),
        ("l", "Armature inductance", "H", "Sets the current ripple; leave empty if unknown", None),
        ("i_max", "Current limit", "A", "", None),
        ("drive", "Drive", "", "unipolar: one leg chops, lower loss. bipolar: both legs switch", ["unipolar", "bipolar"]),
    ],
    "dc_series": [
        ("k", "Torque constant", "N·m/A²", "Torque over current squared, from one point of the motor's curve", None),
        ("r", "Resistance", "Ω", "Armature and field together", None),
        ("i_max", "Current limit", "A", "", None),
        ("drive", "Drive", "", "unipolar: one leg chops, lower loss. bipolar: both legs switch", ["unipolar", "bipolar"]),
    ],
    "stepper": [
        ("steps_per_rev", "Steps per turn", "", "200 for a 1.8 degree motor", None),
        ("i_phase", "Set phase current", "A peak", "What the driver is set to", None),
        ("r", "Phase resistance", "Ω", "", None),
        ("l", "Phase inductance", "H", "", None),
        ("holding_torque", "Holding torque", "N·m", "At the set current", None),
    ],
}
# Figures a motor may be given beyond its catalogue ones. All optional: left empty, the
# effect they describe is left out, and the result says so.
OPTIONAL = {
    "p_iron": ("Iron loss", "W", "No-load loss in the motor's steel, at the speed below. From a no-load test or the maker."),
    "n_iron": ("at speed", "rpm", "The speed that iron loss was measured at."),
    "i_sat": ("Saturation current", "A peak", "Where an inductance has fallen to about 70% of its small-current value."),
}
OPTIONAL_FOR = {"pmsm": ["p_iron", "n_iron", "i_sat"], "synrm": ["p_iron", "n_iron", "i_sat"],
                "induction": ["p_iron", "n_iron"], "bldc": ["p_iron", "n_iron"]}
# Family, name and what it is, in the order the page lists them: the usual tree of motor
# types, from machines fed with alternating current to those with brushes.
MOTOR_NAMES = {
    "pmsm": ("Synchronous", "Permanent-magnet", "Magnets on or in the rotor, sinusoidal currents: robot joints, e-bikes, compressors, washers"),
    "bldc": ("Synchronous", "Brushless DC", "The same kind of motor driven in six steps (block, or trapezoidal, commutation)"),
    "synrm": ("Synchronous", "Reluctance", "A shaped steel rotor with no magnets: pumps and fans where magnets are unwanted"),
    "induction": ("Induction", "Three-phase induction", "Squirrel-cage rotor: industrial pumps, fans, conveyors"),
    "dc": ("Brushed DC", "Permanent-magnet DC", "Two wires, brushes, magnets in the stator; also a separately excited field"),
    "dc_series": ("Brushed DC", "Series-wound DC", "Field winding in series with the armature: power tools, starters, universal motors"),
    "stepper": ("Stepper", "Bipolar stepper", "Two phases on two H-bridges, microstepped"),
}
# A design point that works with each example motor, so no screen opens on an error.
STARTING = {
    "pmsm": dict(v_dc=48, rpm=2000, torque=1.0, f_sw=20000),
    "bldc": dict(v_dc=48, rpm=2000, torque=1.0, f_sw=20000),
    "synrm": dict(v_dc=540, rpm=1500, torque=5.0, f_sw=8000),
    "induction": dict(v_dc=540, rpm=1400, torque=6.0, f_sw=8000),
    "dc": dict(v_dc=24, rpm=2500, torque=0.4, f_sw=20000),
    "dc_series": dict(v_dc=24, rpm=3000, torque=1.0, f_sw=20000),
    "stepper": dict(v_dc=48, rpm=300, torque=0.8, f_sw=30000),
}


class Refused(Exception):
    """An input that cannot work. Carries the reason and what to change."""

    def __init__(self, reason: str, fix: str = "", field: str = "") -> None:
        super().__init__(reason)
        self.reason, self.fix, self.field = reason, fix, field


def _number(value, name: str, *, low: float | None = None, high: float | None = None) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        raise Refused(f"{name} is not a number", f"enter a value for {name}", name) from None
    if not math.isfinite(x):
        raise Refused(f"{name} is not a number", f"enter a value for {name}", name)
    if low is not None and x < low:
        raise Refused(f"{name} cannot be below {low:g}", f"raise {name}", name)
    if high is not None and x > high:
        raise Refused(f"{name} cannot be above {high:g}", f"lower {name}", name)
    return x


def _motor(data: dict):
    from pydantic import ValidationError

    cleaned = {k: v for k, v in data.items() if v not in ("", None)}
    # A working temperature comes with the motor's figures and is not one of them.
    hot = cleaned.pop("t_motor", None)
    try:
        machine = _ADAPTER.validate_python(cleaned)
        if hot is None:
            return machine
        from motionsim.motor.machines import at_temperature

        return at_temperature(machine, _number(hot, "motor temperature", low=-40, high=250))
    except ValidationError as exc:
        first = exc.errors()[0]
        field = str(first["loc"][-1]) if first["loc"] else ""
        field = {"ld": "l", "lq": "l", "flux_linkage": "kv"}.get(field, field)  # as the form names them
        label = next(
            (lab for key, lab, *_ in FIELDS.get(str(cleaned.get("type")), []) if key == field), field
        )
        message = first["msg"].removeprefix("Value error, ")
        known = FIELDS.get(str(cleaned.get("type")), [])
        if not field or field == str(cleaned.get("type")):
            # A check across several values names the one at fault in its message.
            field = next((key for key, *_ in known if message.startswith(key)), "")
            label = next((lab for key, lab, *_ in known if key == field), "")
            if field:
                message = message.removeprefix(field).strip()
        message = message.lower()
        if first["type"] == "missing":
            message = "is needed"
        elif message.startswith("input should be"):
            message = "should be" + message.removeprefix("input should be")
        subject = label.lower() if label else "a motor value"
        raise Refused(f"{subject} {message}" if label else message,
                      "correct the motor's values in step 1", field) from None


def _conditions(data: dict, motor) -> OperatingPoint:
    pwm = data.get("pwm") or motor.default_pwm.value
    floor = {"rg_on": 0.01, "rg_off": 0.01, "v_drive": 0.1}  # a gate resistance is never nothing
    optional = lambda key: (  # noqa: E731
        None if data.get(key) in ("", None) else _number(data[key], key, low=floor.get(key, 0))
    )
    return OperatingPoint(
        v_dc=_number(data.get("v_dc"), "supply voltage", low=1, high=2000),
        i_rms=0.0, modulation_index=0.0, power_factor=1.0,
        f_sw=_number(data.get("f_sw"), "switching frequency", low=100, high=2e6),
        t_sink=_number(data.get("t_sink", 60), "heatsink temperature", low=-40, high=200),
        pwm=Pwm(pwm), t_dead=_number(data.get("t_dead", 0) or 0, "dead time", low=0, high=1e-4),
        t_min_pulse=_number(data.get("t_min_pulse", 0) or 0, "shortest pulse", low=0, high=1e-4),
        v_drive=optional("v_drive"), rg_on=optional("rg_on"), rg_off=optional("rg_off"),
        l_loop=optional("l_loop"),
        parallel=int(_number(data.get("parallel") or 1, "devices in parallel", low=1, high=12)),
    )


def _gate(device, op: OperatingPoint, motor, conditions: dict):
    """The gate drive this device is run with: the user's, or chosen for the lowest loss the
    limits allow where they left it open. The current is the design point's peak."""
    from motionsim.recommend import choose_gate_drive

    try:
        rpm = _number(conditions.get("rpm"), "speed")
        torque = _number(conditions.get("torque"), "torque")
        i_peak = motor.stage(rpm, torque, op.v_dc, op.pwm).i_peak
    except (Unreachable, Refused, ValueError):
        i_peak = device.ratings.i_nominal
    # Each device of those in parallel switches its own share in its own loop.
    from motionsim.engine.solver import hot_share

    return choose_gate_drive(device, op, max(i_peak * hot_share(device, op.parallel), 1e-3))


def _switching_period(device, design, op: OperatingPoint) -> dict:
    """One PWM period of the hottest switch at its hardest instant, for drawing."""
    from motionsim.engine.solver import switching_period

    roles = design.result.roles
    k = max(range(len(roles)), key=lambda n: roles[n].tj_switch_peak)
    out = switching_period(device, design.stage.roles[k], op, roles[k].tj_switch, roles[k].tj_diode)
    return {**out, "position": roles[k].name}


def _gate_out(gate) -> dict:
    return {"kind": gate.kind, "v_drive": gate.v_drive, "rg_on": gate.rg_on, "rg_off": gate.rg_off,
            "lines": gate.lines}


def _unreachable(exc: Unreachable, v_dc: float) -> Refused:
    text = str(exc)
    if "more than the DC link" in text or "more voltage" in text:
        fix = "lower the speed or the torque, raise the supply voltage, or choose a motor wound for this voltage"
    elif "limit" in text:
        fix = "lower the torque, or raise the motor's current limit if the winding allows it"
    elif "holding torque" in text:
        fix = "lower the torque or choose a larger stepper"
    else:
        fix = "change the speed or torque"
    return Refused(f"this motor cannot do that from {v_dc:g} V: {text}", fix, "point")


def _losses(sw, d) -> dict:
    return {
        "conduction": sw.conduction, "turn_on": sw.turn_on, "turn_off": sw.turn_off,
        "dead_time": sw.dead_time, "recovery": sw.recovery,
        "diode_conduction": d.conduction, "diode_recovery": d.recovery,
        "total": sw.total + d.total,
    }


def _result(r, tj_max: float, parallel: int = 1) -> dict:
    # The roles hold one device of each position; with devices in parallel there are more.
    conduction = parallel * sum(x.count * (x.switch.conduction + x.switch.dead_time + x.diode.conduction) for x in r.roles)
    switching = parallel * sum(
        x.count * (x.switch.turn_on + x.switch.turn_off + x.switch.recovery + x.diode.recovery)
        for x in r.roles
    )
    return {
        "loss": r.p_inverter, "conduction": conduction, "switching": switching,
        "efficiency": r.efficiency, "tj_peak": hottest(r), "tj_range": r.tj_peak_range,
        "tj_max": tj_max, "t_case": r.t_case, "validity": r.validity.value, "notes": r.notes,
        "limits": r.limits, "assumptions": r.assumptions, "warnings": r.rating_warnings,
        "hottest": _losses(r.switch, r.diode),
        "positions": [
            {"name": x.name, "count": x.count, **_losses(x.switch, x.diode),
             "tj": x.hottest, "tj_switch": x.tj_switch_peak, "tj_diode": x.tj_diode_peak}
            for x in r.roles
        ],
    }


def _checks(checks) -> list[dict]:
    word = {guard.Level.ok: "ok", guard.Level.caution: "caution", guard.Level.fail: "fail"}
    return [{"level": word[c.level], "topic": c.topic, "message": c.message} for c in checks]


def _stage(stage, motor, pwm: Pwm) -> dict:
    return {
        "positions": sum(r.count for r in stage.roles), "i_peak": stage.i_peak,
        "p_shaft": stage.p_shaft, "p_electrical": stage.p_electrical,
        "p_motor_loss": stage.p_motor_loss, "scheme": motor.scheme(pwm),
        "summary": [{"label": a, "value": b, "unit": c} for a, b, c in stage.summary],
        "notes": stage.notes,
        "roles": [
            {"name": r.name, "count": r.count,
             "forward": float(np.mean(r.d_switch * (r.current > 0))),
             "reverse": float(np.mean(r.d_reverse * (r.current > 0))),
             "switching": float(np.mean(r.switch_events + r.reverse_events) > 0)}
            for r in stage.roles
        ],
    }


class Workspace:
    """Device files the page can use: the user's folder, plus the synthetic example."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)

    def paths(self) -> dict[str, Path]:
        found = {"example": EXAMPLE} if EXAMPLE.exists() else {}
        for path in sorted(self.folder.glob("*.device.yaml")):
            found[path.name.removesuffix(".device.yaml")] = path
        return found

    def device(self, key: str) -> Device:
        paths = self.paths()
        if key not in paths:
            raise Refused(f"no device called {key}", "add its datasheet again")
        return load_device(paths[key])

    def summary(self, key: str, device: Device) -> dict:
        sw = device.switch
        tables = [sw.conduction, sw.e_on, sw.e_off, sw.reverse]
        if device.diode is not None:
            tables += [device.diode.conduction, device.diode.e_rr]
        point = any(t is not None and t.basis.value == "point" for t in tables)
        measured = sw.e_on is not None and sw.e_off is not None
        return {
            "id": key, "name": f"{device.vendor} {device.part_number}",
            "technology": device.technology, "v_max": device.ratings.v_max,
            "i_nominal": device.ratings.i_nominal, "tj_max": device.ratings.tj_max,
            "i_pulsed": device.ratings.i_pulsed, "t_sc": device.ratings.t_sc,
            "positions": device.package.topology.positions,
            "integrated_driver": device.package.integrated_driver,
            "example": key == "example",
            "switching": "measured energy from the datasheet" if measured else "estimated from gate and output charge",
            "support": "table points and assumed shapes" if point else "curves",
            "needs_gate_drive": not measured,
        }

    def listing(self) -> list[dict]:
        out = []
        for key, path in self.paths().items():
            try:
                out.append(self.summary(key, load_device(path)))
            except Exception:  # an unreadable file is not the page's problem
                continue
        return out


def setup(workspace: Workspace) -> dict:
    motors = {}
    for kind, (family, label, about) in MOTOR_NAMES.items():
        values = yaml.safe_load(TEMPLATES[kind])
        motor = _ADAPTER.validate_python(values)
        motors[kind] = {
            "family": family, "label": label, "about": about, "start": STARTING[kind],
            "values": {k: v for k, v in values.items() if k not in ("name",)},
            "fields": [
                {"key": key, "label": lab, "unit": unit, "help": text_, "options": options}
                for key, lab, unit, text_, options in FIELDS[kind]
            ],
            "fixed_scheme": motor.fixed_scheme, "default_pwm": motor.default_pwm.value,
            "optional": [{"key": key, "label": OPTIONAL[key][0], "unit": OPTIONAL[key][1], "help": OPTIONAL[key][2]}
                         for key in OPTIONAL_FOR.get(kind, [])],
        }
    return {
        "motors": motors, "pwm": [p.value for p in Pwm],
        "load": yaml.safe_load(LOAD_TEMPLATE), "profile": yaml.safe_load(PROFILE_TEMPLATE),
        "devices": workspace.listing(),
        "can_read": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


# How each catalogue value changes when the same motor is wound for k times the voltage:
# the power of k it scales with. Turns go up by k, so voltage constants go up by k,
# resistances and inductances by k squared, and currents down by k. Power and torque stay.
REWIND = {
    "kv": -1, "kt": 1, "ke": 1, "flux_linkage": 1, "k": 2,
    "l": 2, "ld": 2, "lq": 2, "lm": 2, "lls": 2, "llr": 2, "rs": 2, "rr": 2, "r": 2,
    "i_max": -1, "i_magnetising": -1, "i_phase": -1, "i_sat": -1,
}


def rewound(kind: str, values: dict, v_supply: float) -> dict:
    """The example motor of a kind, wound for another supply voltage. The same machine:
    same speed, torque and power, with the winding changed to suit the voltage."""
    k = v_supply / STARTING[kind]["v_dc"]
    out = {}
    for key, value in values.items():
        power = REWIND.get(key)
        out[key] = value if power is None or not isinstance(value, (int, float)) else float(f"{value * k**power:.4g}")
    return out


def suggest(data: dict, workspace: Workspace) -> dict:
    """For the device under test: the supply it suits, how each kind of motor fits it, and
    each example motor wound for that supply, so the first numbers the user sees belong
    with their device."""
    from motionsim.advise import motors_for

    device = workspace.device(data["device"])
    bus, fits = motors_for(device.ratings.v_max, device.package.topology.positions)
    base = setup(workspace)["motors"]
    return {
        "v_supply": bus,
        "motors": {
            kind: {
                "fit": fit.fit, "why": fit.why,
                "values": rewound(kind, base[kind]["values"], bus),
                "start": {**STARTING[kind], "v_dc": bus},
            }
            for kind, fit in fits.items()
        },
    }


# Which kinds of load each kind of motor usually drives, most usual first.
# The same, for a motor fed at mains level (from about 150 V): a robot joint or a light
# vehicle is a low-voltage job, a compressor or a washer a mains one.
LOADS_MAINS = {
    "pmsm": ["fan", "conveyor", "drum", "vehicle", "joint"],
    "bldc": ["fan", "conveyor", "tool", "vehicle"],
    "dc": ["conveyor", "vehicle", "joint"],
}
LOADS_FOR = {
    "pmsm": ["joint", "fan", "vehicle", "drum", "conveyor"],
    "bldc": ["fan", "vehicle", "tool", "conveyor"],
    "synrm": ["fan", "conveyor", "drum"],
    "induction": ["fan", "conveyor", "drum"],
    "dc": ["conveyor", "joint", "vehicle"],
    "dc_series": ["tool", "conveyor"],  # a series motor cannot brake a vehicle by itself
    "stepper": ["axis", "conveyor"],
}
G = 9.81


def _round_gear(ratio: float) -> float:
    """A gear ratio as one would be bought: at least 1, to two figures."""
    return float(f"{max(ratio, 1.0):.2g}")


def load_presets(kind: str, rpm: float, torque: float, v_dc: float | None = None) -> list[dict]:
    """Loads a motor of this kind usually drives, each sized from the design point so that
    it asks the motor for about what the user said the motor can give: the speed is
    reached, and the torque stays within the design torque.

    Each is a starting point with the few figures that describe that kind of load; the
    user changes them to their own.
    """
    w = max(abs(rpm), 1.0) * math.pi / 30  # rad/s at the motor
    t = max(abs(torque), 1e-6)
    r = lambda x: float(f"{x:.3g}")  # noqa: E731
    rotor = r(0.05 * t * 0.1 / w)  # a rotor that half a tenth of the torque spins up in 0.1 s

    def ramp(top: float, up: float, hold: float, down: float) -> list[dict]:
        # Rounded towards zero, so that a rounded gear ratio never asks the motor for a
        # hair more than its design speed.
        scale = 10 ** (math.floor(math.log10(abs(top))) - 2) if top else 1.0
        top = math.trunc(top / scale) * scale
        top = float(f"{top:.6g}")
        return [
            {"duration": up, "speed_start": 0, "speed_end": top},
            {"duration": hold, "speed_start": top, "speed_end": top},
            {"duration": down, "speed_start": top, "speed_end": 0},
        ]

    every = {}
    every["fan"] = {
        "label": "Fan or pump", "about": "Torque grows with the square of speed; light at the start, full at top speed",
        "load": {"gear_ratio": 1, "gear_efficiency": 1, "motor_inertia": rotor, "inertia": r(0.15 * t * 4 / w),
                 "fan_coefficient": r(0.8 * t / w**2), "friction_coulomb": r(0.02 * t)},
        "fields": ["fan_coefficient", "inertia", "friction_coulomb", "gear_ratio"],
        "segments": ramp(rpm, 4, 6, 4), "start_angle_deg": 0,
    }
    every["conveyor"] = {
        "label": "Conveyor or compressor", "about": "A steady torque at any speed, there from the first turn",
        "load": {"gear_ratio": 1, "gear_efficiency": 1, "motor_inertia": rotor, "inertia": r(0.2 * t * 2 / w),
                 "constant_torque": r(0.7 * t)},
        "fields": ["constant_torque", "inertia", "gear_ratio", "gear_efficiency"],
        "segments": ramp(rpm, 2, 6, 2), "start_angle_deg": 0,
    }
    # Gear ratios follow the motor's speed, so the load turns at the speed such a load does:
    # a joint at some tens of rpm, a drum at about 1200, a wheel at a road speed for the power.
    n = max(abs(rpm), 1.0)
    power = t * w
    gear, eff, arm = _round_gear(min(max(0.5 * n / 20, 5), 200)), 0.85, 0.25
    mass = 0.5 * t * gear * eff / (G * arm)
    every["joint"] = {
        "label": "Robot joint", "about": "A weight on an arm behind a gearbox: swings up, then holds against gravity",
        "load": {"gear_ratio": gear, "gear_efficiency": eff, "motor_inertia": rotor, "inertia": r(mass * arm**2),
                 "friction_coulomb": r(0.05 * t * gear), "gravity": {"mass": r(mass), "arm": arm}},
        "fields": ["mass", "arm", "gear_ratio", "gear_efficiency", "inertia", "friction_coulomb", "start_angle_deg"],
        "segments": ramp(0.5 * rpm / gear, 0.3, 0.45, 0.3) + [{"duration": 2.0, "speed_start": 0, "speed_end": 0}],
        "start_angle_deg": 0,
    }
    radius = 0.15 if power < 1500 else 0.3
    road = 25 / 3.6 if power < 1500 else 60 / 3.6 if power < 15000 else 110 / 3.6  # m/s at the design speed
    gear, eff, up = _round_gear(w * radius / road), 0.95, 6.0
    v = w / gear * radius
    carried = 0.55 * t * gear * eff / (radius * (v / up))
    every["vehicle"] = {
        "label": "Wheeled vehicle", "about": "A mass on wheels: pulls away, cruises against drag, brakes and gives energy back",
        "load": {"gear_ratio": gear, "gear_efficiency": eff, "motor_inertia": rotor,
                 "vehicle": {"mass": r(carried), "wheel_radius": radius, "rolling_resistance": 0.015,
                             "drag_area": r(0.2 * t * gear / (radius * 0.6 * v**2)), "slope_percent": 0}},
        "fields": ["v_mass", "wheel_radius", "gear_ratio", "rolling_resistance", "drag_area", "slope_percent"],
        "segments": ramp(rpm / gear, up, 6, 3), "start_angle_deg": 0,
    }
    gear, eff = _round_gear(n / 1200), 0.9
    spin, tumble = rpm / gear, (45 if n / gear > 300 else 0.08 * n / gear) * (1 if rpm >= 0 else -1)
    every["drum"] = {
        "label": "Washer drum", "about": "A heavy drum on a belt: tumbles one way and the other, then spins up",
        "load": {"gear_ratio": gear, "gear_efficiency": eff, "motor_inertia": rotor,
                 "inertia": r(0.4 * t * gear * eff * 8 / (w / gear)), "friction_coulomb": r(0.3 * t * gear)},
        "fields": ["inertia", "friction_coulomb", "gear_ratio", "gear_efficiency"],
        "segments": ramp(tumble, 1, 3, 1) + ramp(-tumble, 1, 3, 1) + ramp(spin, 8, 4, 8), "start_angle_deg": 0,
    }
    every["axis"] = {
        "label": "Positioning axis", "about": "Short moves there and back with a pause between: a slide, a screw, a turntable",
        "load": {"gear_ratio": 1, "gear_efficiency": 1, "motor_inertia": rotor, "inertia": r(0.5 * t * 0.1 / w),
                 "friction_coulomb": r(0.1 * t)},
        "fields": ["inertia", "friction_coulomb", "gear_ratio"],
        "segments": ramp(rpm, 0.1, 0.3, 0.1) + [{"duration": 0.5, "speed_start": 0, "speed_end": 0}] + ramp(-rpm, 0.1, 0.3, 0.1),
        "start_angle_deg": 0,
    }
    every["tool"] = {
        "label": "Power tool", "about": "Short bursts at nearly full torque, with rests between",
        "load": {"gear_ratio": 1, "gear_efficiency": 1, "motor_inertia": rotor, "inertia": r(0.1 * t * 0.3 / w),
                 "constant_torque": r(0.85 * t)},
        "fields": ["constant_torque", "inertia", "gear_ratio"],
        "segments": ramp(rpm, 0.3, 2, 0.3) + [{"duration": 1.0, "speed_start": 0, "speed_end": 0}], "start_angle_deg": 0,
    }
    # In words, how each load's speed comes from the motor's: the two must be seen to agree.
    for key, item in every.items():
        g = item["load"]["gear_ratio"]
        top = max(abs(sg["speed_end"]) for sg in item["segments"])
        via = "directly on the motor shaft" if g == 1 else f"through a {g:g}:1 gear"
        say = lambda v: f"{v:,.0f}" if abs(v) >= 100 else f"{v:.3g}"  # noqa: E731
        item["link"] = (
            f"Driven {via}: the load's top speed of {say(top)} rpm is {say(top * g)} rpm at the motor, "
            f"against your design speed of {say(n)} rpm."
        )
        if key == "vehicle":
            item["link"] += f" That is {top * math.pi / 30 * item['load']['vehicle']['wheel_radius'] * 3.6:.3g} km/h on the road."
    mains = v_dc is not None and v_dc >= 150
    order = (LOADS_MAINS if mains else {}).get(kind) or LOADS_FOR.get(kind, ["conveyor"])
    return [{"id": key, **every[key]} for key in order]


def loads(data: dict) -> dict:
    kind = data.get("kind", "pmsm")
    rpm = _number(data.get("rpm"), "speed")
    torque = _number(data.get("torque"), "torque")
    v_dc = data.get("v_dc")
    return {"loads": load_presets(kind, rpm, torque, None if v_dc in ("", None) else _number(v_dc, "supply voltage"))}


def stage(data: dict) -> dict:
    """What the motor asks of the power stage, before any device is chosen."""
    from motionsim.advise import advise

    motor = _motor(data["motor"])
    op = _conditions(data["conditions"], motor)
    rpm = _number(data["conditions"].get("rpm"), "speed")
    torque = _number(data["conditions"].get("torque"), "torque")
    try:
        st = motor.stage(rpm, torque, op.v_dc, op.pwm)
        advice = advise(motor, rpm, torque, op.v_dc, op.f_sw, supply=data.get("supply", "one-way"))
    except Unreachable as exc:
        raise _unreachable(exc, op.v_dc) from None
    return {
        "stage": _stage(st, motor, op.pwm),
        "advice": {
            "lines": advice.lines, "v_minimum": advice.v_minimum,
            "v_comfortable": advice.v_comfortable, "i_peak": advice.i_peak,
            "i_stall": advice.i_stall,
        },
    }


def proposal(data: dict, workspace: Workspace) -> dict:
    from motionsim.propose import LEVEL, explain, propose

    motor = _motor(data["motor"])
    op = _conditions(data["conditions"], motor)
    rpm = _number(data["conditions"].get("rpm"), "speed")
    torque = _number(data["conditions"].get("torque"), "torque")
    keys = data.get("devices") or []
    if not keys:
        raise Refused("no device chosen", "pick at least one device in the Devices step")
    devices = [workspace.device(k) for k in keys]
    gates = {id(d): _gate(d, op, motor, data["conditions"]) for d in devices}
    try:
        candidates = propose(devices, motor, rpm, torque, op, tune=lambda d: gates[id(d)].op)
    except Unreachable as exc:
        raise _unreachable(exc, op.v_dc) from None
    word = {guard.Level.ok: "ok", guard.Level.caution: "caution", guard.Level.fail: "fail"}
    by_object = {id(d): k for d, k in zip(devices, keys)}
    out = []
    for c in candidates:
        problem, fix = c.problem, ""
        if problem and "gate drive" in problem:
            fix = "open Gate drive under Supply and point, and give the drive voltage and gate resistors"
        elif problem and "no stable temperature" in problem:
            fix = "this device overheats here: lower the current or switching frequency, or pick a larger part"
        out.append({
            "id": by_object[id(c.device)], "name": f"{c.device.vendor} {c.device.part_number}",
            "technology": c.device.technology, "level": word[c.level], "problem": problem, "fix": fix,
            "result": None if c.design is None else _result(c.design.result, c.device.ratings.tj_max, gates[id(c.device)].op.parallel),
            "stall_tj": None if c.stall is None else hottest(c.stall.result),
            "margin": c.margin, "stall_margin": c.stall_margin,
            "switching": None if c.footing is None else {"kind": c.footing.kind, "text": c.footing.text},
            "efficiency": None if c.design is None else c.design.system_efficiency,
            "checks": _checks(c.checks), "needs": c.needs,
            "gate": _gate_out(gates[id(c.device)]),
            "pwm": None if c.design is None else _switching_period(c.device, c.design, gates[id(c.device)].op),
            "link": None if c.design is None else {"capacitor_rms": c.design.capacitor_rms, "ripple_pp": c.design.ripple_pp},
        })
    return {"candidates": out, "explain": explain(candidates), "level": LEVEL}


def _inrush(data: dict, op: OperatingPoint) -> dict | None:
    from motionsim.starting import inrush

    c_link = data.get("c_link")
    if not c_link:
        return None
    r = data.get("precharge")
    found = inrush(op.v_dc, _number(c_link, "DC-link capacitance", low=1e-9),
                   _number(r, "precharge resistance", low=1e-3) if r else None)
    return {"energy": found.energy, "peak": found.peak, "time": found.time}


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
        raise Refused("the mission profile is not three columns of numbers",
                      "give time in seconds, speed in rpm and torque in N·m, one row an instant", "mission") from None
    if not (len(time) == len(rpm) == len(torque)) or len(time) < 2:
        raise Refused("the mission profile needs at least two rows, with all three columns filled",
                      "check the file", "mission")
    if any(b <= a for a, b in zip(time, time[1:])) or not all(map(math.isfinite, time + rpm + torque)):
        raise Refused("the mission profile's time does not run forward", "sort the rows by time", "mission")
    if len(time) > MOST_POINTS:
        # Thin by keeping, in each stretch, the instant that asks the most torque.
        edges = np.linspace(0, len(time), MOST_POINTS + 1).astype(int)
        keep = sorted({int(a + np.argmax(np.abs(torque[a:b]))) for a, b in zip(edges, edges[1:]) if b > a} | {0, len(time) - 1})
        time, rpm, torque = [time[k] for k in keep], [rpm[k] for k in keep], [torque[k] for k in keep]
    spans = [b - a for a, b in zip(time, time[1:])]
    spans.append(spans[-1])
    return [Sample(t - time[0], dt, n * math.pi / 30, 0.0, 0.0, n, tq) for t, dt, n, tq in zip(time, spans, rpm, torque)]


def _life(trace, tj, duration: float) -> dict:
    """Thermal-cycling life of the chip that wears out first, from its own temperature
    trace, by a generic model."""
    from motionsim.lifetime import estimate, worst_of

    life = worst_of(trace.chips, trace.swings) or estimate(np.asarray([v for v in tj if math.isfinite(v)]))
    endless = not math.isfinite(life.repeats)
    return {
        "repeats": None if endless else life.repeats,
        "hours": None if endless else life.repeats * duration / 3600,
        "swing": life.swing, "swing_mean": life.swing_mean, "swing_share": life.swing_share, "swings": life.swings,
        "chip": life.chip, "within_turn": life.within_turn,
    }


SENSORLESS = ("pmsm", "bldc", "synrm")  # motors whose drive must find the rotor to start


def _start(data: dict, motor, op: OperatingPoint):
    """How the drive starts this motor, with what the user left open filled in, and the
    same in words. Returns (Start or None, description for the page)."""
    from motionsim.starting import Start

    given = data.get("start") or {}
    kind = data["motor"]["type"]
    c = data["conditions"]
    lines: list[str] = []
    number = lambda key, name, **limits: (  # noqa: E731
        None if given.get(key) in ("", None) else _number(given[key], name, **limits)
    )
    if kind == "induction":
        lr = motor.lm + motor.llr
        usual = 3 * lr / motor.rr if motor.rr > 0 else 0.0
        flux = number("flux_time", "flux build-up time", low=0, high=30)
        flux = usual if flux is None else flux
        lines.append(
            f"before any torque, the magnetising current is held for {flux:.2g} s to build the "
            "rotor flux" + ("" if given.get("flux_time") not in ("", None) else ": three rotor time constants")
        )
        return Start(flux_time=flux), {"applies": "flux", "method": "sensor", "flux_time": flux, "lines": lines}
    if kind not in SENSORLESS:
        why = "a stepper is driven open loop at its set current all the time" if kind == "stepper" else \
            "a brushed motor commutates itself, so the drive has no rotor position to find"
        return None, {"applies": "none", "method": "sensor", "lines": [why]}
    method = given.get("method") or "sensor"
    if method not in ("sensor", "injection", "open_loop"):
        raise Refused("that way of starting is not known", "pick one of the three listed", "start")
    if method != "open_loop":
        lines.append(
            "the drive knows where the rotor is from the first instant, so it applies only the "
            "current the torque needs" if method == "sensor" else
            "the rotor position is found at standstill by injecting a test signal, so the drive "
            "applies only the current the torque needs; this needs a rotor whose inductance "
            "differs along and across its poles, which magnets on the rotor face barely give"
        )
        return Start(method=method), {"applies": "method", "method": method, "lines": lines}
    try:
        design = motor.stage(_number(c.get("rpm"), "speed"), _number(c.get("torque"), "torque"), op.v_dc, op.pwm).i_peak
    except Unreachable:
        design = 0.0
    current = number("current", "start current", low=0)
    peak = design if current is None else current * math.sqrt(2)
    align = number("align_time", "alignment time", low=0, high=30)
    align = 0.5 if align is None else align
    handover = number("handover_rpm", "handover speed", low=0)
    handover = 0.1 * abs(_number(c.get("rpm"), "speed")) if handover is None else handover
    lines += [
        f"alignment: {peak / math.sqrt(2):.3g} A rms held still for {align:g} s, to swing the rotor to a known position",
        f"open-loop ramp: the same current up to {handover:.3g} rpm, whatever the load asks for",
        "above that the drive reads the rotor from the back-EMF and the current drops to what the torque needs",
    ]
    if current is None:
        lines.append("start current taken as the current at your design point; a drive is usually set between half and all of the rated current")
    start = Start(method="open_loop", current=peak, align_time=align, handover_rpm=handover)
    return start, {"applies": "method", "method": method, "current": peak / math.sqrt(2), "align_time": align,
                   "handover_rpm": handover, "lines": lines}


def cycle(data: dict, workspace: Workspace) -> dict:
    from motionsim import dclink
    from motionsim.transient import Heatsink, follow

    motor = _motor(data["motor"])
    op = _conditions(data["conditions"], motor)
    device = workspace.device(data["device"])
    op = _gate(device, op, motor, data["conditions"]).op
    mission = _mission(data.get("mission"))
    try:
        load = Load.model_validate(data["load"])
        profile = Profile.model_validate(data["profile"])
    except Exception as exc:
        if mission is None:
            raise Refused(f"the load or motion values do not fit: {str(exc).splitlines()[-1].strip()}",
                          "check the load and motion values") from None
        load = profile = None
    sink = None
    h = data.get("heatsink") or {}
    if h.get("rth") and h.get("capacity"):
        sink = Heatsink(
            rth=_number(h["rth"], "heatsink resistance", low=0.01),
            capacity=_number(h["capacity"], "heatsink heat capacity", low=0.1),
            t_ambient=_number(h.get("t_ambient", op.t_sink), "ambient temperature", low=-40, high=150),
        )
    repeats = int(_number(data.get("repeats", 1), "repeats", low=1, high=50))
    start, starting = _start(data, motor, op)
    try:
        run, trace = follow(device, motor, load, profile, op, heatsink=sink, repeats=repeats, start=start,
                            samples=mission, per_segment=6 if data.get("coarse") else 12)
    except ValueError as exc:
        raise Refused(str(exc), "open Gate drive under Supply and point" if "gate" in str(exc) else "") from None
    if not run.solved:
        problem = next(s.problem for s in run.steps if s.problem)
        raise Refused(f"no instant of this motion can be reached: {problem}",
                      "slow the motion, lighten the load or raise the supply voltage", "motion")
    count = len(run.steps)
    start = len(trace.time) - count
    worst = run.steps[trace.peak_index % count]
    if worst.point is None:
        worst = run.worst
    result = worst.point.result
    shift = trace.peak - hottest(result)
    span = result.tj_peak_range
    reached = replace(
        result, tj_switch_peak=result.tj_switch_peak + shift,
        tj_diode_peak=result.tj_diode_peak + shift,
        tj_peak_range=None if span is None else (span[0] + shift, span[1] + shift),
    )
    checks = guard.check(device, op, reached, max(s.point.stage.i_peak for s in run.solved))
    c_link = data.get("c_link")
    link = dclink.returned(run, op.v_dc, device.ratings.v_max,
                           capacitance=_number(c_link, "DC-link capacitance", low=1e-9) if c_link else None)
    checks += dclink.check(link, op.v_dc, device.ratings.v_max, supply=data.get("supply", "one-way"))
    # Over the motion: the instant with the most ripple, what the capacitor carries on
    # average (which is what heats it), and a trip at the motion's top speed.
    hardest = max(run.solved, key=lambda s: s.point.ripple_pp or 0.0).point
    most = max(run.solved, key=lambda s: s.point.capacitor_rms or 0.0).point
    checks += [c for c in guard.ripple_checks(hardest, op) if c.topic == "ripple"]
    checks += [c for c in guard.ripple_checks(most, op) if c.topic == "link capacitor"]
    lasting = sum(s.sample.duration for s in run.solved)
    capacitor_mean = math.sqrt(sum((s.point.capacitor_rms or 0.0) ** 2 * s.sample.duration for s in run.solved) / lasting) if lasting else 0.0
    tripped = guard.trip_check(motor, max(abs(s.sample.motor_rpm) for s in run.steps), op.v_dc, device.ratings.v_max)
    if tripped is not None:
        checks.append(tripped)
    failed = [s for s in run.steps if s.point is None]
    if failed:
        checks.append(guard.Check(guard.Level.fail, "motion",
                                  f"the motor cannot follow part of this motion: {failed[0].problem}"))
    clean = lambda a: [None if not math.isfinite(v) else float(v) for v in a]  # noqa: E731
    return {
        "time": clean(trace.time[start:] - (trace.time[start] - run.steps[0].sample.duration)),
        "tj": clean(trace.tj[start:]), "steady": clean(trace.steady[start:]),
        "t_sink": clean(trace.t_sink[start:]),
        "rpm": [s.sample.motor_rpm for s in run.steps],
        "torque": [s.sample.motor_torque for s in run.steps],
        "p_stage": [None if s.point is None else s.point.result.p_inverter for s in run.steps],
        "i_peak": [None if s.point is None else s.point.stage.i_peak for s in run.steps],
        "start": starting,
        "life": _life(trace, trace.tj[start:], run.duration),
        "inrush": _inrush(data, op),
        "p_dc": [None if s.point is None else s.point.stage.p_electrical + s.point.result.p_inverter
                 for s in run.steps],
        "summary": {
            "duration": run.duration, "peak": trace.peak, "forever": float(np.nanmax(trace.steady)),
            "tj_max": device.ratings.tj_max, "mean_loss": run.mean_loss,
            "shaft_energy": run.shaft_energy, "loss_energy": run.loss_energy,
            "rms_torque": run.rms_torque, "returned": link.energy, "returned_peak": link.peak_power,
            "v_link_peak": link.v_peak, "c_needed": link.capacitance_needed,
            "sink_peak": float(trace.t_sink.max()),
            "capacitor_rms": capacitor_mean if most.capacitor_rms is not None else None,
            "capacitor_rms_worst": most.capacitor_rms, "ripple_pp_worst": hardest.ripple_pp,
        },
        "checks": _checks(checks),
    }


def speed_torque(data: dict, workspace: Workspace) -> dict:
    from motionsim.drivers import speed_torque_map

    motor = _motor(data["motor"])
    op = _conditions(data["conditions"], motor)
    device = workspace.device(data["device"])
    op = _gate(device, op, motor, data["conditions"]).op
    n = int(_number(data.get("n", 9), "grid size", low=3, high=15))
    rpm_top = _number(data.get("rpm_max"), "top speed", low=1)
    torque_top = _number(data.get("torque_max"), "top torque", low=1e-6)
    rpm = np.linspace(rpm_top / n, rpm_top, n)
    torque = np.linspace(torque_top / n, torque_top, n)
    try:
        m = speed_torque_map(device, motor, rpm, torque, op)
    except ValueError as exc:
        raise Refused(str(exc), "open Gate drive under Supply and point" if "gate" in str(exc) else "") from None
    grid = lambda a: [[None if not math.isfinite(v) else float(v) for v in row] for row in a]  # noqa: E731
    return {"rpm": rpm.tolist(), "torque": torque.tolist(), "loss": grid(m.p_inverter),
            "tj": grid(m.tj_peak), "efficiency": grid(m.efficiency), "reason": m.reason,
            "tj_max": device.ratings.tj_max}


def capability(data: dict, workspace: Workspace) -> dict:
    """What this device can drive on this motor and cooling: the torque it holds at each
    speed with every junction within its rating, and how that limit moves with the
    switching frequency and the heatsink temperature."""
    from motionsim.capability import against, envelope, torque_limit

    motor = _motor(data["motor"])
    op = _conditions(data["conditions"], motor)
    device = workspace.device(data["device"])
    op = _gate(device, op, motor, data["conditions"]).op
    rpm = abs(_number(data["conditions"].get("rpm"), "speed")) or 1.0
    torque = abs(_number(data["conditions"].get("torque"), "torque")) or 1.0
    speeds = [rpm if k == 1.0 else float(f"{rpm * k:.4g}") for k in (0.0, 0.1, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)]
    edge = envelope(device, motor, speeds, op, torque)
    here = edge[speeds.index(rpm)] if rpm in speeds else torque_limit(device, motor, rpm, op, torque)
    frequencies = [float(f"{op.f_sw * k:.3g}") for k in (0.25, 0.5, 1.0, 2.0, 4.0)]
    sinks = [op.t_sink + k for k in (-20.0, 0.0, 20.0, 40.0)]
    words = {"junction": "a junction reaches its rating", "motor": "the motor itself: its current limit, or its reach on this supply",
             "current rating": "the device's current rating", "none found": "nothing within reach"}
    row = lambda found: {"torque": found.torque, "why": words.get(found.reason, found.reason), "tj": found.tj, "current": found.current}  # noqa: E731
    return {
        "rpm": speeds, "edge": [row(x) for x in edge],
        "design": {"rpm": rpm, "torque": torque, **row(here), "share": torque / here.torque if here.torque > 0 else None,
                   "power": here.torque * rpm * math.pi / 30, "rated": device.ratings.i_nominal},
        "f_sw": frequencies, "by_f_sw": [row(x) for x in against(device, motor, rpm, op, "f_sw", frequencies, torque)],
        "t_sink": sinks, "by_t_sink": [row(x) for x in against(device, motor, rpm, op, "t_sink", sinks, torque)],
    }


GROWS = ("inertia", "friction_coulomb", "friction_viscous", "constant_torque", "fan_coefficient")


def _scaled(data: dict, k: float) -> dict:
    """The same request with the load made k times as heavy: what it asks of the motor
    grows with it, the motion and the gearing stay."""
    load = dict(data.get("load") or {})
    for key in GROWS:
        if load.get(key):
            load[key] = load[key] * k
    if load.get("gravity"):
        load["gravity"] = {**load["gravity"], "mass": load["gravity"]["mass"] * k}
    if load.get("vehicle"):
        load["vehicle"] = {**load["vehicle"], "mass": load["vehicle"]["mass"] * k,
                           "drag_area": (load["vehicle"].get("drag_area") or 0.0) * k}
    out = {**data, "load": load}
    if data.get("mission"):
        out["mission"] = {**data["mission"], "torque": [t * k for t in data["mission"]["torque"]]}
    return out


def largest(data: dict, workspace: Workspace) -> dict:
    """How much heavier the load could be before the device, the motor or the link gives:
    the load is scaled up until a check fails, and what failed is named."""
    def tried(k: float, coarse: bool = True) -> tuple[bool, str, dict | None]:
        # The search steps through the motion in half as many instants; the answer it
        # settles on is then worked out in full.
        try:
            out = cycle({**_scaled(data, k), "coarse": coarse}, workspace)
        except Refused as exc:
            return False, exc.reason, None
        except ThermalRunaway:
            return False, "no stable junction temperature", None
        failing = [c["message"] for c in out["checks"] if c["level"] == "fail"]
        return (not failing), (failing[0] if failing else ""), out

    fine, why, at = tried(1.0)
    if not fine:
        low, high = 0.0, 1.0
    else:
        low, high = 1.0, 2.0
        for _ in range(9):
            fine, why_high, found = tried(high)
            if not fine:
                why = why_high
                break
            low, at, high = high, found, 2 * high
        else:
            return {"scale": low, "open": True, "why": "", "peak": at["summary"]["peak"], "tj_max": at["summary"]["tj_max"]}
    for _ in range(6):  # to a part in sixty of the last doubling: finer says nothing more
        middle = (low + high) / 2
        fine, why_middle, found = tried(middle)
        if fine:
            low, at = middle, found
        else:
            high, why = middle, why_middle
    if low > 0:
        fine, _, full = tried(low, coarse=False)
        at = full if fine else at
    return {"scale": low, "open": False, "why": why,
            "peak": None if at is None else at["summary"]["peak"], "tj_max": None if at is None else at["summary"]["tj_max"]}


def recommendations(data: dict, workspace: Workspace) -> dict:
    from motionsim import recommend
    from motionsim.drivers import at_speed_and_torque

    motor = _motor(data["motor"])
    op = _conditions(data["conditions"], motor)
    device = workspace.device(data["device"])
    rpm = _number(data["conditions"].get("rpm"), "speed")
    torque = _number(data["conditions"].get("torque"), "torque")
    try:
        st = motor.stage(rpm, torque, op.v_dc, op.pwm)
    except Unreachable as exc:
        raise _unreachable(exc, op.v_dc) from None
    gate = _gate(device, op, motor, data["conditions"])
    asked = op
    op = gate.op
    if gate.kind in ("datasheet", "built in"):
        resistors = recommend.Recommendation("gate resistors", lines=gate.lines)
    else:
        # Worked out with what the user gave, plus the usual values where they gave none.
        probe = replace(op, l_loop=op.l_loop if op.l_loop is not None else recommend.USUAL_LOOP)
        resistors = recommend.gate_resistors(device, probe, st.i_peak,
                                             driver_peak=data.get("driver_peak") or None)
        resistors = recommend.Recommendation(
            resistors.topic, resistors.value,
            [ln for ln in gate.lines if ln.startswith(("gate drive taken", "loop inductance taken"))] + resistors.lines
            + ([f"you gave {asked.rg_on:g} ohm on and {asked.rg_off:g} ohm off; the results use yours"]
               if asked.rg_on is not None and asked.rg_off is not None else
               ["the results use these values, since you gave none"]),
        )
    out = [
        resistors,
        recommend.dead_time(device, op),
    ]
    losses = {}
    if motor.fixed_scheme is None:
        for scheme in Pwm:
            try:
                losses[scheme.value] = at_speed_and_torque(
                    device, motor, rpm, torque, replace(op, pwm=scheme)
                ).result.p_inverter
            except (Unreachable, ThermalRunaway, ValueError):
                continue
    out.append(recommend.modulation(losses, motor.default_pwm.value))

    def evaluate(t_sink: float) -> tuple[float, float]:
        worst, loss = float("-inf"), 0.0
        for speed in (rpm, 0.0):
            try:
                point = at_speed_and_torque(device, motor, speed, torque, replace(op, t_sink=t_sink))
            except Unreachable:
                continue
            top = point.result.tj_peak_range[1] if point.result.tj_peak_range else hottest(point.result)
            worst, loss = max(worst, top), max(loss, point.result.p_inverter)
        return worst, loss

    try:
        ambient = _number(data.get("t_ambient", 40), "ambient temperature", low=-40, high=120)
        out.append(recommend.heatsink(device, ambient, evaluate))
    except ValueError as exc:
        out.append(recommend.Recommendation("heatsink", lines=[str(exc)]))
    return {"items": [{"topic": r.topic, "value": r.value, "lines": r.lines} for r in out]}


def curves(key: str, workspace: Workspace) -> dict:
    """The tables of a device model, for drawing what was read."""
    device = workspace.device(key)

    def table(model, unit: str) -> dict | None:
        if model is None:
            return None
        return {
            "unit": unit, "basis": model.basis.value, "assumption": model.assumption,
            "source": model.source.note, "page": model.source.page,
            "curves": [{"tj": c.tj, "x": c.current, "y": c.value} for c in model.curves],
        }

    sw, d = device.switch, device.diode
    out = {
        "summary": workspace.summary(key, device),
        "conduction": table(sw.conduction, "V"), "e_on": table(sw.e_on, "J"),
        "e_off": table(sw.e_off, "J"), "reverse": table(sw.reverse, "V"),
        "diode": None if d is None else table(d.conduction, "V"),
        "e_rr": table((d or sw).e_rr, "J"),
        "thermal": {"r": sw.thermal.r, "tau": sw.thermal.tau, "source": sw.thermal.source.note},
        "reading": _reading(key, workspace),
    }
    return out


def _reading(key: str, workspace: Workspace) -> dict | None:
    """What the reader took from the datasheet this device was built from, value by value,
    or None for a device that came as a file."""
    path = workspace.folder / f"{key}.observations.yaml"
    if not path.is_file():
        return None
    from motionsim.observe import load_observations

    obs = load_observations(path)

    def conditions(o) -> str:
        parts = []
        if o.current_a is not None:
            parts.append(f"{o.current_a:g} A")
        if o.voltage_v is not None:
            parts.append(f"{o.voltage_v:g} V")
        if o.tj_c is not None:
            parts.append(f"{o.tj_c:g} °C")
        return ", ".join(parts)

    def printed(o) -> str:
        parts = []
        if o.printed_typ is not None:
            parts.append(f"typ {o.printed_typ}")
        if o.printed_max is not None:
            parts.append(f"max {o.printed_max}")
        return (", ".join(parts) or "none") + f" {o.unit}"

    return {
        "document": obs.document.file, "pages": obs.document.pages,
        "from_images": len(obs.document.transcribed),
        "values": [
            {"what": o.quantity.value, "printed": printed(o), "at": conditions(o), "page": o.page,
             "flags": o.flags}
            for o in obs.observations
        ],
        "figures": [
            {"what": c.quantity.value, "label": c.label, "page": c.page, "tj": c.tj_c,
             "points": len(c.x), "flags": c.flags, "notes": c.notes,
             "within": c.anchor_error, "method": c.method}
            for c in obs.curves
        ],
    }


ROUTES = {
    "/api/stage": lambda data, ws: stage(data),
    "/api/proposal": proposal,
    "/api/capability": capability,
    "/api/largest": largest,
    "/api/suggest": suggest,
    "/api/loads": lambda data, ws: loads(data),
    "/api/cycle": cycle,
    "/api/map": speed_torque,
    "/api/recommend": recommendations,
}


def add_device(name: str, text: str, workspace: Workspace) -> dict:
    """Put a device file the user supplied into the workspace, after checking it loads."""
    import re

    from pydantic import ValidationError

    key = re.sub(r"[^a-z0-9]+", "-", name.lower().removesuffix(".yaml").removesuffix(".device")).strip("-")
    if not key or key == "example":
        key = "device"
    try:
        device = Device.model_validate(yaml.safe_load(text))
    except (ValidationError, yaml.YAMLError, TypeError) as exc:
        detail = str(exc).splitlines()[0][:160]
        raise Refused(
            f"that file is not a device model: {detail}",
            "choose a .device.yaml file written by `motionsim build`",
        ) from None
    (workspace.folder / f"{key}.device.yaml").write_text(text, encoding="utf-8")
    return {"device": workspace.summary(key, device)}


def add_measurement(key: str, name: str, text: str, workspace: Workspace) -> dict:
    """Replace a device's datasheet switching energy with the user's own double-pulse data.

    The device as read from its datasheet is kept; the measured one is added beside it.
    """
    from pydantic import ValidationError

    from motionsim.device import save_device
    from motionsim.measured import DoublePulse, apply_double_pulse

    device = workspace.device(key)
    try:
        data = DoublePulse.model_validate(json.loads(text))
    except (ValidationError, json.JSONDecodeError, TypeError) as exc:
        raise Refused(
            f"that file is not double-pulse data: {str(exc).splitlines()[0][:160]}",
            "it needs v_dc and a list of points, each with tj, current, e_on and e_off",
        ) from None
    try:
        measured = apply_double_pulse(device, data, name)
    except ValueError as exc:
        raise Refused(f"this measurement cannot be used: {exc}", "check the file's points") from None
    new_key = f"{key}-measured"
    save_device(measured, workspace.folder / f"{new_key}.device.yaml")
    return {"device": workspace.summary(new_key, measured)}


def call(route: str, payload: str, workspace: Workspace) -> str:
    """One request as text in, text out: the form the browser's own copy of the engine uses.

    Returns JSON with a status the page reads the way it reads an HTTP status:
    200 with the answer, 422 with a refusal, 500 with a fault of ours.
    """
    try:
        data = json.loads(payload or "{}")
        if route == "/api/setup":
            body = setup(workspace)
        elif route == "/api/device":
            body = add_device(data["name"], data["text"], workspace)
        elif route == "/api/measure":
            body = add_measurement(data["device"], data["name"], data["text"], workspace)
        elif route.startswith("/api/device/"):
            body = curves(route.rsplit("/", 1)[1], workspace)
        elif route in ROUTES:
            body = ROUTES[route](data, workspace)
        else:
            return json.dumps({"status": 404, "body": {"error": "no such address"}})
        return json.dumps({"status": 200, "body": body})
    except Refused as exc:
        return json.dumps({"status": 422, "body": {"refused": exc.reason, "fix": exc.fix, "field": exc.field}})
    except ThermalRunaway:
        return json.dumps({"status": 422, "body": RUNAWAY})
    except Exception as exc:  # a fault of ours: say so plainly
        return json.dumps({"status": 500, "body": {"error": f"{type(exc).__name__}: {exc}"}})


RUNAWAY = {
    "refused": "no stable temperature: the losses grow faster than the heat can leave",
    "fix": "lower the current or switching frequency, cool the heatsink, or pick a larger device",
    "field": "",
}
