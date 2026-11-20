"""Where a design starts: the form the page draws, the example motor of each kind wound and
sized for the part at hand, and the loads each kind of motor usually drives."""

from __future__ import annotations

import math
from typing import Any

import yaml

from motionsim import guard
from motionsim.device.schema import Device
from motionsim.engine import Pwm
from motionsim.errors import Refusal
from motionsim.load import LOAD_TEMPLATE, PROFILE_TEMPLATE, Load, Profile
from motionsim.motor import TEMPLATES, Unreachable
from motionsim.motor.machines import ADAPTER
from motionsim.motor_class import APPLICATION_MOTORS, Start, class_motor, part_figures, starting_class
from motionsim.service.applications import APPLICATIONS, Point
from motionsim.service.catalogue import (
    FIELDS,
    LIMIT_AT,
    LOADS_FOR,
    LOADS_MAINS,
    MOTOR_NAMES,
    OPTIONAL,
    OPTIONAL_FOR,
    RESIZE,
    REWIND,
    STARTING,
    WORKED_AT,
)
from motionsim.service.validate import _motor, _number, point
from motionsim.service.workspace import Workspace
from motionsim.text import rounded, written


def setup(workspace: Workspace) -> dict:
    motors = {}
    for kind, (family, label, about) in MOTOR_NAMES.items():
        values = yaml.safe_load(TEMPLATES[kind])
        motor = ADAPTER.validate_python(values)
        motors[kind] = {
            "family": family,
            "label": label,
            "about": about,
            "start": STARTING[kind],
            "values": {k: v for k, v in values.items() if k not in ("name",)},
            "fields": [
                # A figure the motor can be described without may be left empty on the page.
                {
                    "key": key,
                    "label": lab,
                    "unit": unit,
                    "help": text_,
                    "options": options,
                    "required": key not in type(motor).model_fields or type(motor).model_fields[key].is_required(),
                }
                for key, lab, unit, text_, options in FIELDS[kind]
            ],
            "fixed_scheme": motor.fixed_scheme,
            "default_pwm": motor.default_pwm.value,
            "optional": [
                {"key": key, "label": OPTIONAL[key][0], "unit": OPTIONAL[key][1], "help": OPTIONAL[key][2]}
                for key in OPTIONAL_FOR.get(kind, [])
            ],
        }
    return {
        "motors": motors,
        "pwm": [p.value for p in Pwm],
        "load": yaml.safe_load(LOAD_TEMPLATE),
        "profile": yaml.safe_load(PROFILE_TEMPLATE),
        "devices": workspace.listing(),
        "typed": typed_form(),
        "can_read": _can_read(),
    }


def _can_read() -> bool:
    """Whether a language model is set up to read a datasheet with. Where the reader's own
    libraries are not there, as in the browser, there is none."""
    try:
        from motionsim.observe import provider
    except ImportError:
        return False
    return provider.available()


def rewound(kind: str, values: dict, v_supply: float, v_from: float | None = None) -> dict:
    """The example motor of a kind, wound for another supply voltage. The same machine:
    same speed, torque and power, with the winding changed to suit the voltage. v_from: the
    supply the figures are for, where they are not the kind's own example's."""
    k = v_supply / (v_from or STARTING[kind]["v_dc"])
    out = {}
    for key, value in values.items():
        power = REWIND.get(key)
        out[key] = value if power is None or not isinstance(value, (int, float)) else rounded(value * k**power, 4)
    return out


def resized(values: dict, s: float) -> dict:
    """The same kind of motor, s times as large: for the same supply and speed it gives s
    times the torque on s times the current."""
    return {
        key: rounded(value * s ** RESIZE[key], 4)
        if key in RESIZE and isinstance(value, (int, float)) and not isinstance(value, bool)
        else value
        for key, value in values.items()
    }


def _sized_to(device: Device, kind: str, values: dict, start: dict) -> tuple[dict, dict]:
    """The example motor and its design point made the size that belongs with the part: its
    current limit just inside what the part is rated for, so the part can use all of the
    motor and the first verdict says something about the part. A motor that gives no limit
    is sized by its design point. One the size cannot be worked out for is left as it is."""
    try:
        motor = _motor({"type": kind, **values})
        i_peak = motor.stage(start["rpm"], start["torque"], start["v_dc"], motor.default_pwm).i_peak
    except (Refusal, Unreachable, ValueError):
        return values, start
    if not i_peak > 0:
        return values, start
    limit = guard.current_limit(motor)
    rated = device.ratings.i_nominal
    s = float(f"{(LIMIT_AT * rated / limit if limit else WORKED_AT * rated / i_peak):.2g}")
    if not 0.01 <= s <= 1000 or s == 1:
        return values, start
    return resized(values, s), {**start, "torque": rounded(start["torque"] * s, 3)}


def _example(kind: str, start: Start, base: dict, bus: float) -> tuple[dict, dict]:
    """A kind's motor for the part, wound for its supply: the typical motor of the part's
    class of drive where the kind has one there, the kind's own example where it has not."""
    if kind not in start.classes:
        return rewound(kind, base[kind]["values"], bus), {**STARTING[kind], "v_dc": bus}
    values, rated = class_motor(start.classes[kind])
    # In the order of the kind's own example, as a design file and the page set them out.
    example = base[kind]["values"]
    values = {k: example[k] if k == "type" else values[k] for k in example if k in values or k == "type"}
    return rewound(kind, values, bus, rated["v_dc"]), {**rated, "v_dc": bus, "f_sw": start.f_sw}


def suggest(data: dict, workspace: Workspace) -> dict:
    """For the device under test: the supply it suits, how each kind of motor fits it, and
    each kind's motor wound for that supply and sized to the part's current, so the first
    numbers the user sees belong with their device. The kind it starts on, and its motor,
    are those of the part's class of drive (motor_class), with the line that says why."""
    from motionsim.advise import motors_for

    device = workspace.device(data["device"])
    v_rated, positions, i_rated, technology = part_figures(device)
    bus, fits = motors_for(v_rated, positions, i_rated, technology)
    start = starting_class(v_rated, bus, i_rated, technology, positions)
    base = setup(workspace)["motors"]
    motors = {}
    for kind, fit in fits.items():
        values, point = _sized_to(device, kind, *_example(kind, start, base, bus))
        motors[kind] = {"fit": fit.fit, "why": fit.why, "values": values, "start": point}
    return {"v_supply": bus, "why": start.why, "motors": motors}


def _link(item: dict, n: float) -> str:
    """In words, how a load's speed comes from the motor's: the two must be seen to agree."""
    g = item["load"]["gear_ratio"]
    top = max(abs(sg.speed_end) for sg, _ in Profile.model_validate(item["profile"]).stretches())
    via = "directly on the motor shaft" if g == 1 else f"through a {g:g}:1 gear"

    def say(v: float) -> str:
        return f"{v:,.0f}" if abs(v) >= 100 else f"{written(v, 3)}"

    link = (
        f"Driven {via}: the load's top speed of {say(top)} rpm is {say(top * g)} rpm at the motor, "
        f"against your design speed of {say(n)} rpm."
    )
    vehicle = item["load"].get("vehicle")
    if vehicle:
        link += f" That is {written(top * math.pi / 30 * vehicle['wheel_radius'] * 3.6, 3)} km/h on the road."
    return link


def _usual_motor(key: str, load: dict, profile: dict, v_dc: float | None) -> dict:
    """The motor such products have, wound for the supply in use, and the point it is judged
    at: the top speed of the duty, with the torque the load asks there held steady."""
    c = APPLICATION_MOTORS[key]
    values, _ = class_motor(c)
    example = yaml.safe_load(TEMPLATES[c.kind])
    ordered = {"type": c.kind, **{k: values[k] for k in example if k in values}}
    bus = v_dc or c.v_dc
    worked = Load.model_validate(load)
    top = max((sg.speed_end for sg, _ in Profile.model_validate(profile).stretches()), key=abs)
    _, torque = worked.at_motor(top * math.pi / 30, 0.0, math.pi)  # the turn's mean place
    return {
        "kind": c.kind,
        "v_dc": bus,
        "own_v_dc": c.v_dc,
        "values": rewound(c.kind, ordered, bus, c.v_dc),
        "point": {"rpm": rounded(top * worked.gear_ratio, 4), "torque": rounded(abs(torque), 3)},
    }


def _runs(given: dict, load: dict, profile: dict, v_dc: float) -> dict:
    """Whether the motor in the design can run this duty from this supply: at its heaviest,
    its fastest and its most powerful instants, within the motor's reach and its current
    limit. The words say what stops it."""
    from motionsim.load import sample

    try:
        motor = _motor(given)
    except Refusal:
        return {"ok": True, "why": ""}
    instants = sample(Load.model_validate(load), Profile.model_validate(profile), 6)
    hardest = {
        max(instants, key=lambda x: abs(x.motor_torque)),
        max(instants, key=lambda x: abs(x.motor_rpm)),
        max(instants, key=lambda x: abs(x.motor_rpm * x.motor_torque)),
    }
    limit = guard.current_limit(motor)
    for x in sorted(hardest, key=lambda x: x.time):
        torque = max((abs(t) for t in x.torques or ()), default=abs(x.motor_torque)) * (
            1 if x.motor_torque >= 0 else -1
        )
        at = f"{x.motor_rpm:,.0f} rpm and {written(abs(torque), 3)} N·m"
        try:
            i_peak = motor.stage(x.motor_rpm, torque, v_dc, motor.default_pwm).i_peak
        except (Unreachable, ValueError):
            return {"ok": False, "why": f"this motor cannot reach {at} from {written(v_dc, 3)} V"}
        if limit is not None and i_peak > limit * 1.001:
            return {
                "ok": False,
                "why": f"{at} asks {written(i_peak, 3)} A of this motor, past its limit of {written(limit, 3)} A",
            }
    return {"ok": True, "why": ""}


def load_presets(
    kind: str, rpm: float, torque: float, v_dc: float | None = None, motor: dict | None = None
) -> list[dict]:
    """The applications a motor of this kind is usually in, each with its load and its duty.

    An application whose products have a size of their own comes with its own figures and
    the motor such products have; given the motor in the design, it says whether that one
    can run it. The rest are sized from the design point so that they ask the motor for
    about what the user said the motor can give: the speed is reached, and the torque
    stays within the design torque.
    """
    w = max(abs(rpm), 1.0) * math.pi / 30  # rad/s at the motor
    t = max(abs(torque), 1e-6)
    at = Point(rpm=rpm, w=w, t=t, n=max(abs(rpm), 1.0), rotor=rounded(0.05 * t * 0.1 / w))
    mains = v_dc is not None and v_dc >= 150
    order = (LOADS_MAINS if mains else {}).get(kind) or LOADS_FOR.get(kind, ["conveyor"])
    out = []
    for key in order:
        app = APPLICATIONS[key]
        load, motion = app.build(at)
        profile = {"start_angle_deg": 0, **motion}
        item: dict[str, Any] = {
            "id": key,
            "label": app.label,
            "about": app.about,
            "load": load,
            "fields": list(app.fields),
            "segments": motion.get("segments", []),
            "phases": motion.get("phases"),
            "start_angle_deg": 0,
            "profile": profile,
            "start": app.start,
            "usage": {"per_year": app.usage.per_year, "unit": app.usage.unit, "said": app.usage.said},
            "why": list(app.why),
            "duration": Profile.model_validate(profile).duration,
            "motor": None,
            "runs": None,
        }
        if app.motor is not None:
            item["motor"] = _usual_motor(app.motor, load, profile, v_dc)
            if motor is not None and v_dc is not None:
                item["runs"] = _runs({"type": kind, **motor}, load, profile, v_dc)
        item["link"] = _link({**item, "profile": profile}, at.n)
        out.append(item)
    return out


def loads(data: dict) -> dict:
    """The loads a kind of motor usually drives, sized to a design point."""
    kind = data.get("kind", "pmsm")
    if not isinstance(kind, str) or kind not in MOTOR_NAMES:
        raise Refusal("there is no kind of motor of that name", f"one of {', '.join(MOTOR_NAMES)}", "kind")
    rpm, torque = point(data)
    v_dc = data.get("v_dc")
    supply = None if v_dc in ("", None) else _number(v_dc, "supply voltage", low=1, high=2000, field="v_dc")
    motor = data.get("motor")
    given = {k: v for k, v in motor.items() if k != "type"} if isinstance(motor, dict) else None
    return {"loads": load_presets(kind, rpm, torque, supply, given)}


def typed_form() -> dict:
    """The forms for a part typed in from its datasheet, as the page draws them: a field-effect
    transistor's and an IGBT's. `main` marks the boxes shown with the required ones: those, and
    the optional ones a stated rule fills when they are left empty."""
    from motionsim.fit.taken import DEFAULTED
    from motionsim.fit.typed import FIGURES, OUTLINES, TECHNOLOGIES
    from motionsim.fit.typed_igbt import IGBT_FIGURES, MAIN, TECHNOLOGY, TOPOLOGIES

    def fields(table, main) -> list[dict]:
        return [
            {
                "key": key,
                "label": label,
                "unit": unit,
                "required": required,
                "help": text_,
                "main": required or key in main,
            }
            for key, label, unit, _, required, text_ in table
        ]

    return {
        "technologies": list(TECHNOLOGIES),
        "outlines": list(OUTLINES),
        "fields": fields(FIGURES, DEFAULTED),
        "igbt": {"technology": TECHNOLOGY, "topologies": list(TOPOLOGIES), "fields": fields(IGBT_FIGURES, MAIN)},
    }
