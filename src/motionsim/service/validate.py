"""What is asked, checked before anything is worked out.

Every figure that reaches the engine comes through here, whoever sends it: the page, a
design file or the command line. Each has a name the asker knows it by and bounds no real
drive is outside of, and one that cannot be is refused with that name, what is wrong with
it and what to change. Nothing here works anything out.
"""

from __future__ import annotations

import math
from dataclasses import replace

from motionsim.engine import OperatingPoint, Pwm
from motionsim.engine.point import EDGE_LIMITS
from motionsim.errors import Refusal
from motionsim.motor.machines import ADAPTER
from motionsim.service.catalogue import FIELDS
from motionsim.text import whole, written

Refused = Refusal  # the name this was first written under


# The unit each figure is checked in, said with every limit: the page turns a limit into the
# unit of its own box (kilohertz, nanoseconds), and can only do that knowing the unit it is in.
UNITS = {
    "v_dc": "V",
    "f_sw": "Hz",
    "sweep_f_sw": "Hz",
    "f_out": "Hz",
    "t_dead": "s",
    "t_min_pulse": "s",
    "t_sink": "°C",
    "t_ambient": "°C",
    "t_motor": "°C",
    "tj_limit": "°C",
    "t_sink_max": "°C",
    "rth_sink": "K/W",
    "rth_case_sink": "K/W",
    "rth_ja": "K/W",
    "rg_on": "Ω",
    "rg_off": "Ω",
    "v_drive": "V",
    "v_drive_off": "V",
    "l_loop": "H",
    "i_rms": "A",
    "rpm": "rpm",
    "torque": "N·m",
    "rpm_max": "rpm",
    "torque_max": "N·m",
    "c_link": "F",
    "precharge": "Ω",
    "capacity": "J/K",
    "rth": "K/W",
}


def _number(
    value,
    name: str,
    *,
    low: float | None = None,
    high: float | None = None,
    field: str | None = None,
    unit: str | None = None,
) -> float:
    """field: the page's own name for the input, where it differs from the words used.
    unit: what the limits are said in; left out, the field's own (UNITS)."""
    field = field or name
    unit = UNITS.get(field, "") if unit is None else unit
    said = f" {unit}" if unit else ""
    try:
        # True is not 1: a figure answered with yes or no is a slip, not a volt.
        x = float("nan") if isinstance(value, bool) else float(value)
    except (TypeError, ValueError, OverflowError):
        raise Refused(f"{name} is not a number", f"enter a value for {name}", field) from None
    if not math.isfinite(x):
        raise Refused(f"{name} is not a number", f"enter a value for {name}", field)
    if low is not None and x < low:
        raise Refused(f"{name} cannot be below {written(low, 6)}{said}", f"raise {name}", field)
    if high is not None and x > high:
        most = f"{whole(high)}" if high >= 1e6 and high == int(high) else written(high, 6)
        raise Refused(f"{name} cannot be above {most}{said}", f"lower {name}", field)
    return x


def _count(value, name: str, *, low: int, high: int, field: str) -> int:
    """A whole number of things: 2.5 devices is a slip, not 2."""
    x = _number(1 if value in ("", None) else value, name, low=low, high=high, field=field)
    if x != int(x):
        raise Refused(f"{name} has to be a whole number, and {x:g} was given", f"give a whole number for {name}", field)
    return int(x)


NEEDS = {
    "/api/stage": ("motor", "conditions"),
    "/api/proposal": ("motor", "conditions", "devices"),
    "/api/event": ("motor", "conditions", "device"),
    "/api/cycle": ("motor", "conditions", "device"),
    "/api/map": ("motor", "conditions", "device"),
    "/api/capability": ("motor", "conditions", "device"),
    "/api/largest": ("motor", "conditions", "device"),
    "/api/load-proposal": ("motor", "conditions", "device"),
    "/api/recommend": ("motor", "conditions", "device"),
    "/api/fit": ("motor", "device"),
    "/api/suggest": ("device",),
    "/api/simulate": ("conditions", "device"),
    "/api/max-current": ("conditions", "device"),
    "/api/compare": ("conditions", "devices"),
    "/api/point": ("motor", "conditions", "device"),
    "/api/trajectory": ("conditions", "device"),
    "/api/cooling": ("motor", "conditions", "device"),
    "/api/control/presets": ("motor", "conditions"),
    "/api/control/loops": ("motor", "conditions"),
    "/api/control/run": ("motor", "conditions", "device"),
    "/api/control/explorations": ("motor", "conditions"),
    "/api/control/sweep": ("motor", "conditions", "device"),
    "/api/control/export_c": ("motor", "conditions", "device"),
}


MOST_DEVICES = 5  # compared at once, on the page, in a design and on the command line


def asked(route: str, data) -> None:
    """A request that does not hold what its route needs is refused in words, here, before
    anything is worked out: a missing motor is the asker's slip, not a fault of the engine."""
    if not isinstance(data, dict):
        raise Refused(
            "the request is not a set of names and values", "send an object with the names this address takes"
        )
    for name in NEEDS.get(route, ()):
        value = data.get(name)
        if name in ("motor", "conditions") and not isinstance(value, dict):
            raise Refused(
                f"the request has no {name}, or it is not a set of names and values", f"give the {name}", name
            )
        if name == "device" and not (isinstance(value, str) and value):
            raise Refused("no device is named", "name the device", "device")
        if name == "devices" and not (
            isinstance(value, list) and value and all(isinstance(x, str) and x for x in value)
        ):
            raise Refused("no device chosen", "pick at least one device in the Devices step", "devices")
        if name == "devices" and isinstance(value, list) and len(value) > MOST_DEVICES:
            raise Refused(
                f"{len(value)} devices are named, and {MOST_DEVICES} is the most compared at once",
                f"name up to {MOST_DEVICES}",
                "devices",
            )
    for name in ("start", "heatsink", "load", "profile"):
        if data.get(name) is not None and not isinstance(data[name], dict):
            raise Refused(f"the {name} is not a set of names and values", f"give the {name}'s figures by name", name)


# The least a winding's inductance and resistance can be and still be a winding's. Under
# these the current ripple and the short-circuit current run to figures no stage is built
# for, and the search for an operating point runs for minutes before finding nothing.
LEAST_INDUCTANCE = 1e-9  # H
LEAST_RESISTANCE = 1e-9  # ohm; nought itself is taken, for a winding idealised on purpose
INDUCTANCES = ("l", "ld", "lq", "lm", "lls", "llr")
RESISTANCES = ("rs", "rr", "r")


def _winding_bounds(cleaned: dict) -> None:
    for key in INDUCTANCES:
        value = cleaned.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value < LEAST_INDUCTANCE:
            raise Refusal(
                f"the motor's {key} cannot be below {LEAST_INDUCTANCE * 1e9:g} nH, and {value:g} H was given",
                "give the winding's inductance in henries",
                key,
            )
    for key in RESISTANCES:
        value = cleaned.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value < LEAST_RESISTANCE:
            raise Refusal(
                f"the motor's {key} cannot be below {LEAST_RESISTANCE * 1e9:g} nΩ, and {value:g} Ω was given",
                "give the winding's resistance in ohms, or 0 to leave it out",
                key,
            )


# No figure of a motor, in SI units, is this small without being nought or this large: a
# saturation current of 1e-320 A is a slip, and the arithmetic downstream has no answer for it.
LEAST_FIGURE, MOST_FIGURE = 1e-12, 1e12


def _figure_bounds(cleaned: dict) -> None:
    for key, value in cleaned.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value == 0:
            continue
        if not LEAST_FIGURE <= abs(value) <= MOST_FIGURE:  # also refuses what is not a number
            raise Refusal(
                f"the motor's {key} is not a figure a motor has: {value:g} was given",
                "check the figure and its unit: henries, ohms, amperes, webers",
                str(key),
            )


def _motor_refusal(exc, cleaned: dict) -> Refusal:
    """What a motor's figures were refused for, in a sentence that names each figure as the
    form does, and the figure's name in the form for the page to mark."""
    from motionsim.text import plain_error

    known = FIELDS.get(str(cleaned.get("type")), [])
    labels = {key: f"the {label[:1].lower()}{label[1:]}" for key, label, *_ in known}
    said, field = plain_error(exc.errors()[0], labels)
    field = {"ld": "l", "lq": "l", "flux_linkage": "kv", "ke": "kv"}.get(field, field)  # as the form names them
    if field == str(cleaned.get("type")):
        field = ""
    return Refusal(said, "correct the motor's values", field)


def motor(data: dict):
    """The motor a set of figures describes, at its working temperature where one is given."""
    from pydantic import ValidationError

    cleaned = {k: v for k, v in data.items() if v not in ("", None)}
    # A working temperature comes with the motor's figures and is not one of them.
    hot = cleaned.pop("t_motor", None)
    cleaned.setdefault("type", "pmsm")  # as a motor file read from the terminal is taken
    _winding_bounds(cleaned)
    _figure_bounds(cleaned)
    try:
        machine = ADAPTER.validate_python(cleaned)
    except ValidationError as exc:
        raise _motor_refusal(exc, cleaned) from None
    if hot is None:
        return machine
    from motionsim.motor.machines import at_temperature

    return at_temperature(machine, _number(hot, "motor temperature", low=-40, high=250, field="t_motor"))


_motor = motor


def _pwm(name) -> Pwm:
    try:
        return Pwm(name)
    except ValueError:
        raise Refusal(
            f"there is no modulation called {name}", f"one of {', '.join(x.value for x in Pwm)}", "pwm"
        ) from None


COOLING = ("held", "heatsink", "none", "board")
# The bounds on what a gate drive and its loop can be: a gate resistance is never nothing,
# and a loop of a millihenry is not a commutation loop.
FLOOR = {"rg_on": 0.01, "rg_off": 0.01, "v_drive": 0.1}
MOST = {"rg_on": 1e4, "rg_off": 1e4, "v_drive": 100, "l_loop": 1e-3, "rth_case_sink": 50}
WORDS = {
    "rg_on": "turn-on gate resistance",
    "rg_off": "turn-off gate resistance",
    "v_drive": "gate drive voltage",
    "l_loop": "loop inductance",
    "rth_case_sink": "case-to-heatsink thermal resistance",
}


def _low_level(data: dict) -> float | None:
    """The gate driver's low level where it is given: nought, or below it."""
    if data.get("v_drive_off") in ("", None):
        return None
    return _number(data["v_drive_off"], "gate driver's low level", low=-25, high=0, field="v_drive_off")


def _optional(data: dict, key: str) -> float | None:
    if data.get(key) in ("", None):
        return None
    return _number(data[key], WORDS.get(key, key), low=FLOOR.get(key, 0), high=MOST.get(key), field=key)


def _cooling(data: dict) -> dict:
    """The cooling asked for, as the engine takes it: a heatsink held at a temperature, a
    heatsink in air, or no heatsink at all. In air, t_sink is the air's temperature and the
    engine works out the rest."""
    cooling = data.get("cooling") or "held"
    if cooling not in COOLING:
        raise Refusal(f"cooling is one of {', '.join(COOLING)}", "", "cooling")
    rth_sink = None
    if cooling == "held":
        t_sink = _number(data.get("t_sink", 60), "heatsink temperature", low=-40, high=200, field="t_sink")
    else:
        air = data.get("t_ambient")
        t_sink = _number(40 if air in ("", None) else air, "air temperature", low=-40, high=120, field="t_ambient")
    if cooling == "board" and data.get("board_area") in ("", None):
        raise Refusal(
            "the board's area is needed", "give the area of the board the power stage is on, in cm²", "board_area"
        )
    if cooling == "heatsink":
        if data.get("rth_sink") in ("", None):
            raise Refusal(
                "the heatsink's thermal resistance is needed",
                "give it in K/W, from the heatsink's data: a smaller figure is a bigger heatsink",
                "rth_sink",
            )
        rth_sink = _number(data["rth_sink"], "heatsink thermal resistance", low=0.001, high=500, field="rth_sink")
    # What lies between a package and its heatsink belongs to the build. With no heatsink
    # there is no such layer, and what was typed for another cooling is left alone.
    on_heatsink = cooling in ("held", "heatsink")
    layer = (data.get("interface") or None) if on_heatsink else None
    if layer not in (None, "grease", "pad"):
        raise Refusal(
            f"the layer under the package (interface) is grease or pad, and {layer!r} was given", "", "interface"
        )
    return {
        "t_sink": t_sink,
        "rth_sink": rth_sink,
        "rth_case_sink": _optional(data, "rth_case_sink") if on_heatsink else None,
        "interface": layer,
        "sized": (sized := _sized(data, cooling, rth_sink)),
        "sized_earlier": _earlier(data) and sized is not None,
    }


SIZABLE = {"heatsink": "rth_sink", "board": "board_area"}


def _sized(data: dict, cooling: str, rth_sink: float | None) -> tuple[str, float] | None:
    """The cooling figure the tool sized, where the request says it did: its name and value.
    Said of a figure of another cooling, it is left alone, as what was typed for one is."""
    named = data.get("sized") or None
    if named not in (None, *SIZABLE.values()):
        raise Refusal(f"sized names the cooling figure the tool sized: {' or '.join(SIZABLE.values())}", "", "sized")
    if named is None or SIZABLE.get(cooling) != named:
        return None
    if named == "rth_sink":
        assert rth_sink is not None  # a heatsink in air is refused above without its figure
        return named, rth_sink
    return named, _number(data["board_area"], "board area", low=0.01, high=100000, field="board_area")


def _earlier(data: dict) -> bool:
    """Whether the cooling figure the tool sized was sized for an earlier design point than the
    one asked: the page says so once the inputs it was sized from have moved."""
    said = data.get("sized_earlier")
    if said in (None, "", False, "false"):
        return False
    if said in (True, "true"):
        return True
    raise Refusal(
        "sized_earlier says whether the cooling was sized for an earlier design point: true or false",
        "",
        "sized_earlier",
    )


def conditions(data: dict, default_pwm: Pwm = Pwm.sine) -> OperatingPoint:
    """The supply, the switching, the gate drive and the cooling a stage is run with, each
    within the bounds a real drive lies in. The one check of these, whoever asks: the page,
    a design file and every command take their conditions through here.

    What the load asks (the current, or the speed and torque) is not among them: the
    operating point comes back with no current, for the caller to fill.
    """
    cooling = _cooling(data)
    v_dc = _number(data.get("v_dc"), "supply voltage", low=1, high=2000, field="v_dc")
    # Up to 10 MHz: a GaN stage switches in megahertz, and nothing here stops at a technology.
    f_sw = _number(data.get("f_sw"), "switching frequency", low=100, high=1e7, field="f_sw")
    # Left out it is open, for the tool to work out; given, nought included, it is used.
    dead = data.get("t_dead")
    t_dead_given = dead not in (None, "")
    t_dead = _number(dead, "dead time", low=0, high=1e-4, field="t_dead") if t_dead_given else 0.0
    t_min_pulse = _number(data.get("t_min_pulse", 0) or 0, "shortest pulse", low=0, high=1e-4, field="t_min_pulse")
    if 2 * (t_dead + t_min_pulse) * f_sw >= 1:
        raise Refusal(
            f"the dead time and the shortest pulse take the whole switching period at {f_sw / 1e3:g} kHz",
            "lower the switching frequency or shorten them",
            "t_dead",
        )
    return OperatingPoint(
        v_dc=v_dc,
        i_rms=0.0,
        modulation_index=0.0,
        power_factor=1.0,
        f_sw=f_sw,
        **cooling,
        pwm=_pwm(data.get("pwm") or default_pwm.value),
        t_dead=t_dead,
        t_dead_given=t_dead_given,
        t_min_pulse=t_min_pulse,
        v_drive=_optional(data, "v_drive"),
        v_drive_off=_low_level(data),
        rg_on=_optional(data, "rg_on"),
        rg_off=_optional(data, "rg_off"),
        l_loop=_optional(data, "l_loop"),
        parallel=_count(data.get("parallel", 1), "devices in parallel", low=1, high=12, field="parallel"),
        edge_limit=edge_limit(data),
    )


def edge_limit(data: dict) -> str:
    """How fast an edge the tool may choose the gate resistors for: cable (the default), close or none."""
    named = data.get("edge_limit") or "cable"
    if named not in EDGE_LIMITS:
        raise Refusal(
            f"there is no edge limit called {named}",
            "cable (5 V/ns, a motor on a cable), close (20 V/ns, a motor close to the drive) or none",
            "edge_limit",
        )
    return named


def _conditions(data: dict, motor) -> OperatingPoint:
    """The conditions for a motor: its usual modulation where none is asked for."""
    return conditions(data, motor.default_pwm)


def switches_enough(f_out: float, f_sw: float, where: str = "", lower: str = "the output frequency") -> None:
    """An output that turns faster than the stage switches is refused: there is no pulse to
    make it from. Asked wherever an output frequency is known, of a point told outright or of
    a motor's speed, so that every way of asking is answered alike. lower: what the user has
    to lower, where it is not the output frequency itself."""
    if not f_out > f_sw:
        return
    raise Refusal(
        f"{where}the output frequency of {f_out:g} Hz is above the switching frequency of {f_sw:g} Hz",
        f"a stage switches many times in each turn of its output: lower {lower} or raise the switching frequency",
        "f_out" if lower == "the output frequency" else "f_sw",
    )


def turns_slower_than_switched(stage, f_sw: float, where: str = "") -> None:
    """The same of a motor's stage: its output frequency is its speed's, so the speed is what
    to lower. A motor standing still, or one whose stage has no output period, is not asked."""
    if stage.stalled or not stage.period > 0 or not math.isfinite(stage.period):
        return
    switches_enough(1.0 / stage.period, f_sw, where, "the speed")


def electrical(data: dict, op: OperatingPoint) -> OperatingPoint:
    """An operating point told outright, with no motor to work it out from: the current,
    the modulation index, the power factor and the output frequency, each within bounds."""
    f_out = _number(data.get("f_out", 50.0), "output frequency", low=0, field="f_out")
    switches_enough(f_out, op.f_sw)
    m = _number(data.get("m", 0.0), "modulation index", low=0, field="m")
    if op.pwm.within_reach(m) is None:
        raise Refusal(
            f"the modulation index is at most {op.pwm.max_written:g} with {op.pwm.value} PWM, and {m:g} was given",
            "lower the modulation index"
            + ("" if op.pwm is not Pwm.sine else ", or take space-vector PWM, which reaches 1.155"),
            "m",
        )
    return replace(
        op,
        i_rms=_number(data.get("i_rms"), "current", low=0, high=MOST_CURRENT, field="i_rms"),
        modulation_index=m,
        power_factor=_number(data.get("pf", 1.0), "power factor", low=-1, high=1, field="pf"),
        f_out=f_out,
    )


def point(data: dict) -> tuple[float, float]:
    """The speed and torque of a design point, rpm and N·m."""
    return (
        _number(data.get("rpm"), "speed", low=-MOST_SPEED, high=MOST_SPEED, field="rpm"),
        _number(data.get("torque"), "torque", low=-MOST_TORQUE, high=MOST_TORQUE, field="torque"),
    )


MOST_CURRENT = 1e5  # A rms: past any winding, and any stage this tool is for
MOST_SPEED = 1e6  # rpm: past any rotor that holds together
MOST_TORQUE = 1e6  # N·m


def supply(data: dict) -> str:
    """Whether the supply takes braking energy back: one-way (it cannot) or battery."""
    kind = data.get("supply") or "one-way"
    if kind == "mains":
        # A front end that can give energy back to the mains takes braking as a battery does.
        from motionsim.front_end import TOPOLOGIES

        stage = TOPOLOGIES.get((data.get("front_end") or {}).get("topology") or "")
        return "battery" if stage is not None and stage.returns else "one-way"
    if kind not in ("one-way", "battery"):
        raise Refusal(f"there is no supply called {kind}", "one-way (a power supply), battery or mains", "supply")
    return kind


# Stretches of a motion that say yes or no: run up at the current limit, held until steady.
YES_OR_NO = frozenset({"at_limit", "until_steady"})


def strict_numbers(value, where: str, field: str = "") -> None:
    """A file written by hand is held to its figures: a yes or no where a number belongs, or
    a number in quotes, is a slip and is refused with the place it sits in. The page's own
    forms send what was typed as text, and are not held to this."""
    if isinstance(value, dict):
        for key, inner in value.items():
            # A motor may be called 12; a stretch's yes or no is one.
            if key != "name" and not (key in YES_OR_NO and isinstance(inner, bool)):
                strict_numbers(inner, f"{where}.{key}" if where else str(key), field or str(key))
    elif isinstance(value, list):
        for k, inner in enumerate(value):
            strict_numbers(inner, f"{where}[{k}]", field)
    elif isinstance(value, bool):
        raise Refusal(
            f"{where} has to be a number, and {'true' if value else 'false'} was given",
            f"give a figure for {where}",
            field,
        )
    elif isinstance(value, str) and _reads_as_number(value):
        raise Refusal(
            f"{where} has to be a number, and the text {value!r} was given",
            f"write {where} without quotes",
            field,
        )


def _reads_as_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True
