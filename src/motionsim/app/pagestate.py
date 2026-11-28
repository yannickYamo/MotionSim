"""The page's design, as the server reads and writes it for a coding agent.

The page keeps what was entered as one object (`web/src/state.ts`, `State`), and the shared
session holds it as the page wrote it. This module reads it the way the page does: the
request the page sends the engine (`request`, `motion_request`, as in state.ts), the design
file `motionsim design run` takes (`design_of`), the design the control lab simulates
(`lab_body`, as `designOfPage` in control/entry.ts), and a first state where the page has
never been opened (`initial`). And it writes it the way the page's boxes do: a figure set is
the user's own from then on, so that the starting point that follows the part leaves it be
(`settle`, as in follow.ts).

What is here mirrors the page's code, function by function; tests/test_mcp_pagestate.py
holds it to what state.ts answers for the same states.
"""

from __future__ import annotations

import copy
import json
import math
from decimal import Decimal
from typing import Any

from motionsim.errors import Refusal

# The steps of the page (web/src/steps.ts).
DEVICE, MOTOR, SUPPLY, LOAD, RESULTS = range(5)
STEP_NAMES = ("Device", "Motor", "Supply and point", "Load", "Results")

POINT_KEYS = ("v_dc", "rpm", "torque", "f_khz", "pwm")
SUPPLY_WORDS = {"one-way": "Power supply", "battery": "Battery"}

# Every figure an agent may set on the design, by the name it is set by: where it lives in the
# state, its label and unit as the page's box says them, and what it is (a number the state
# holds as a number; a figure the state holds as typed text, empty for "not given"; one word of
# a few; a whole number).
NUM, TEXT, WORD, WHOLE = "number", "text", "word", "whole"
FIELDS: dict[str, dict[str, Any]] = {
    "v_dc": {"path": "conditions.v_dc", "label": "Supply voltage", "unit": "V", "is": NUM, "low": 1, "high": 2000},
    "rpm": {"path": "conditions.rpm", "label": "Speed", "unit": "rpm", "is": NUM, "low": 0, "high": 200000},
    "torque": {"path": "conditions.torque", "label": "Torque", "unit": "N·m", "is": NUM, "low": 0, "high": 100000},
    "f_khz": {
        "path": "conditions.f_khz",
        "label": "Switching frequency",
        "unit": "kHz",
        "is": NUM,
        "low": 0.1,
        "high": 2000,
    },
    "pwm": {"path": "conditions.pwm", "label": "Modulation", "unit": "", "is": TEXT},
    "t_sink": {
        "path": "conditions.t_sink",
        "label": "Heatsink temperature",
        "unit": "°C",
        "is": NUM,
        "low": -60,
        "high": 200,
    },
    "t_ambient": {
        "path": "conditions.t_ambient",
        "label": "Air temperature",
        "unit": "°C",
        "is": NUM,
        "low": -60,
        "high": 150,
    },
    "parallel": {
        "path": "conditions.parallel",
        "label": "Devices in parallel",
        "unit": "",
        "is": WHOLE,
        "low": 1,
        "high": 64,
    },
    "cooling": {
        "path": "conditions.cooling",
        "label": "Cooling",
        "unit": "",
        "is": WORD,
        "choices": ["held", "heatsink", "none", "board"],
    },
    "edge_limit": {
        "path": "conditions.edge_limit",
        "label": "Edge limit",
        "unit": "",
        "is": WORD,
        "choices": ["cable", "close", "none"],
    },
    "interface": {"path": "conditions.interface", "label": "Interface", "unit": "", "is": WORD, "choices": ["", "pad"]},
    "v_drive": {"path": "conditions.v_drive", "label": "Gate drive voltage", "unit": "V", "is": TEXT},
    "rg_on": {"path": "conditions.rg_on", "label": "Gate resistor, on", "unit": "Ω", "is": TEXT},
    "rg_off": {"path": "conditions.rg_off", "label": "Gate resistor, off", "unit": "Ω", "is": TEXT},
    "t_dead_ns": {"path": "conditions.t_dead_ns", "label": "Dead time", "unit": "ns", "is": TEXT},
    "l_loop_nh": {"path": "conditions.l_loop_nh", "label": "Loop inductance", "unit": "nH", "is": TEXT},
    "t_motor": {"path": "conditions.t_motor", "label": "Motor temperature", "unit": "°C", "is": TEXT},
    "t_min_ns": {"path": "conditions.t_min_ns", "label": "Shortest pulse", "unit": "ns", "is": TEXT},
    "rth_sink": {"path": "conditions.rth_sink", "label": "Heatsink to air", "unit": "K/W", "is": TEXT},
    "rth_ja": {"path": "conditions.rth_ja", "label": "Junction to air", "unit": "K/W", "is": TEXT},
    "board_area": {"path": "conditions.board_area", "label": "Board area", "unit": "cm²", "is": TEXT},
    "copper": {"path": "conditions.copper", "label": "Copper", "unit": "oz", "is": TEXT},
    "copper_ref": {
        "path": "conditions.copper_ref",
        "label": "Copper of the datasheet's board",
        "unit": "oz",
        "is": TEXT,
    },
    "rth_case_sink": {"path": "conditions.rth_case_sink", "label": "Case to heatsink", "unit": "K/W", "is": TEXT},
    "supply": {"path": "supply", "label": "Supply", "unit": "", "is": WORD, "choices": ["one-way", "battery", "mains"]},
    "kind": {"path": "kind", "label": "Kind of motor", "unit": "", "is": WORD},
    "sink.rth": {"path": "sink.rth", "label": "Heatsink thermal resistance (motion)", "unit": "K/W", "is": TEXT},
    "sink.capacity": {"path": "sink.capacity", "label": "Heatsink heat capacity", "unit": "J/K", "is": TEXT},
    "sink.t_ambient": {"path": "sink.t_ambient", "label": "Air around the heatsink", "unit": "°C", "is": TEXT},
    "sink.c_link_uf": {"path": "sink.c_link_uf", "label": "Link capacitance", "unit": "µF", "is": TEXT},
    "sink.precharge": {"path": "sink.precharge", "label": "Precharge resistor", "unit": "Ω", "is": TEXT},
    "sink.repeats": {
        "path": "sink.repeats",
        "label": "Repeats of the motion",
        "unit": "",
        "is": WHOLE,
        "low": 1,
        "high": 1000,
    },
    "start.method": {
        "path": "start.method",
        "label": "Starting method",
        "unit": "",
        "is": WORD,
        "choices": ["sensor", "injection", "open_loop"],
    },
    "start.current": {"path": "start.current", "label": "Starting current", "unit": "A rms", "is": TEXT},
    "start.align_time": {"path": "start.align_time", "label": "Alignment time", "unit": "s", "is": TEXT},
    "start.handover_rpm": {"path": "start.handover_rpm", "label": "Handover speed", "unit": "rpm", "is": TEXT},
    "start.flux_time": {"path": "start.flux_time", "label": "Flux build-up time", "unit": "s", "is": TEXT},
}
LOAD_LABELS = {
    "gear_ratio": ("Gear ratio", ""),
    "gear_efficiency": ("Gear efficiency", ""),
    "motor_inertia": ("Motor inertia", "kg·m²"),
    "inertia": ("Load inertia", "kg·m²"),
    "friction_coulomb": ("Coulomb friction", "N·m"),
    "friction_viscous": ("Viscous friction", "N·m·s/rad"),
    "mass": ("Mass on the arm", "kg"),
    "arm": ("Arm length", "m"),
    "start_angle_deg": ("Starting angle", "°"),
    "constant_torque": ("Constant torque", "N·m"),
    "fan_coefficient": ("Fan coefficient", "N·m/(rad/s)²"),
    "v_mass": ("Vehicle mass", "kg"),
    "wheel_radius": ("Wheel radius", "m"),
    "rolling_resistance": ("Rolling resistance", ""),
    "drag_area": ("Drag area", "m²"),
    "slope_percent": ("Slope", "%"),
    "tumble_mass": ("Tumbling mass", "kg"),
    "tumble_radius": ("Tumbling radius", "m"),
    "pulsation_torque": ("Torque pulse", "N·m"),
    "breakaway_torque": ("Break-away torque", "N·m"),
    "breakaway_rpm": ("Break-away speed", "rpm"),
}
for _key, (_label, _unit) in LOAD_LABELS.items():
    FIELDS[f"load.{_key}"] = {"path": f"load.{_key}", "label": _label, "unit": _unit, "is": NUM}


# Figures of the design set on the page itself rather than by a field the agent names.
OTHER_LABELS = {
    "event.l_cs_nh": ("Common-source inductance", "nH"),
    "event.l_g_nh": ("Gate-loop inductance", "nH"),
    "event.v_off": ("Driver's low level", "V"),
    "event.layout": ("Board layout file", ""),
    "event.layout_name": ("Board layout file's name", ""),
    "map.rpm_max": ("Map's highest speed", "rpm"),
    "map.torque_max": ("Map's highest torque", "N·m"),
    "sweep.key": ("Setting swept", ""),
    "sweep.values": ("Values swept", ""),
    "loadKind": ("Kind of load", ""),
    "loadPicked": ("Load picked", ""),
    "loadUsual": ("Application's usual load", ""),
    "loadSet": ("Loads compared", ""),
    "motorSet": ("Motors compared", ""),
    "mission": ("Mission profile", ""),
    "phases": ("Duty in phases", ""),
    "typed": ("Part being typed in", ""),
}
# The page's bookkeeping of whose a figure is and what it followed: each path, and all within it.
KEPT = {
    "pointOf": "Figures typed for each kind of motor",
    "motorOwn": "Motor figures typed",
    "motorEntry": "How the motor's figures are entered",
    "typedOf": "Typed parts' figures",
    "supplyOwn": "Supply chosen",
    "kindPicked": "Kind of motor chosen",
    "inertiaOwn": "Load inertia typed",
    "loadTouched": "Load edited",
    "loadTouchedBefore": "Load edited before the mission",
    "conditions.sized": "Cooling figure sized",
    "conditions.sizedFor": "What the cooling was sized for",
}


def labels_of(state: dict | None, setup: dict) -> dict[str, dict]:
    """Every figure of the design by its path in the session (`design.<path>`), with its label
    and unit: what the activity log says of a change."""
    out = {f"design.{f['path']}": {"label": f["label"], "unit": f["unit"]} for f in FIELDS.values()}
    for kind, spec in setup["motors"].items():
        for field in [*spec.get("fields", []), *(spec.get("optional") or [])]:
            out[f"design.motors.{kind}.{field['key']}"] = {
                "label": f"{field.get('label') or field['key']} ({spec.get('label', kind)})",
                "unit": field.get("unit") or "",
            }
    for kind in setup["motors"]:
        out[f"design.motors.{kind}.type"] = {
            "label": f"Type of motor ({setup['motors'][kind].get('label', kind)})",
            "unit": "",
        }
    out.update({f"design.{path}": {"label": label, "unit": unit} for path, (label, unit) in OTHER_LABELS.items()})
    # The page's own bookkeeping, figure by figure kept for Undo but never said as a change.
    out.update(
        {f"design.{path}": {"label": label, "unit": "", "kept": True, "within": True} for path, label in KEPT.items()}
    )
    out["design.devices"] = {"label": "Parts compared", "unit": ""}
    out["design.lead"] = {"label": "Part the design starts from", "unit": ""}
    out["design.added"] = {"label": "Parts on the page", "unit": ""}
    out["design.step"] = {"label": "Step open", "unit": ""}
    out["design.segments"] = {"label": "Motion", "unit": ""}
    return out


# -- the state as the page makes it ------------------------------------------------------------


# Where the user is on the page, and how they look at it: each tab's own, never in the shared
# session, so that neither the agent nor another tab moves the user's view (web/src/session/sync.ts).
VIEW = ("step", "reached", "visited", "tab", "metric", "mapAt", "pwmPeriods", "compare", "focus", "focusPicked")


def content(state: dict) -> dict:
    """The design without the page's view of it: what the session shares."""
    return {k: v for k, v in state.items() if k not in VIEW}


# Figures of the design that only make sense together: each set moves as one in every merge,
# the page's (web/src/session/units.ts, the same list) and the session's rebase of a stale
# write (session.py). Never the parts on the page from one version and the parts ticked from
# another: that leaves a part on the page that is not ticked, and nothing to go on with.
UNITS: tuple[tuple[str, ...], ...] = (
    ("devices", "added", "lead"),
    ("typed", "typedOf"),
    ("kind", "kindPicked", "motors", "motorOwn"),
    ("supply", "supplyOwn"),
    (
        "load",
        "loadKind",
        "loadPicked",
        "loadUsual",
        "loadTouched",
        "loadTouchedBefore",
        "inertiaOwn",
        "segments",
        "phases",
        "mission",
    ),
    ("conditions.cooling", "conditions.rth_sink", "conditions.board_area", "conditions.sized", "conditions.sizedFor"),
)


def parts_held(state: dict) -> bool:
    """A part on the page is always under test (`partsHeld` in state.ts): with parts on the page
    and none ticked, the one the design started from is ticked, else the first brought. Mends
    the state where it was so; returns whether it did."""
    added = state.get("added") or []
    if state.get("devices") or not added:
        return False
    pick = state["lead"] if state.get("lead") in added else added[0]
    state["devices"], state["lead"] = [pick], pick
    return True


def initial(setup: dict) -> dict:
    """The state of a first visit (`initial` in state.ts)."""
    kind = "pmsm"
    start = setup["motors"][kind]["start"]
    load = setup["load"]
    gravity = load.get("gravity") or {}
    zero_keys = (
        "constant_torque",
        "fan_coefficient",
        "v_mass",
        "wheel_radius",
        "rolling_resistance",
        "drag_area",
        "slope_percent",
        "tumble_mass",
        "tumble_radius",
        "pulsation_torque",
        "breakaway_torque",
        "breakaway_rpm",
    )
    return {
        "step": 0,
        "reached": 0,
        "visited": [0],
        "kind": kind,
        "motors": {k: dict(m["values"]) for k, m in setup["motors"].items()},
        "motorEntry": {},
        "conditions": {
            "v_dc": start["v_dc"],
            "rpm": start["rpm"],
            "torque": start["torque"],
            "f_khz": start["f_sw"] / 1000,
            "t_sink": 60,
            "pwm": "",
            **dict.fromkeys(
                ("v_drive", "rg_on", "rg_off", "t_dead_ns", "l_loop_nh", "t_motor", "t_min_ns"),
                "",
            ),
            "parallel": 1,
            "cooling": "held",
            "t_ambient": 40,
            **dict.fromkeys(("rth_sink", "rth_ja", "board_area", "copper", "copper_ref", "interface"), ""),
            "rth_case_sink": "",
            "sized": "",
            "sizedFor": "",
            "edge_limit": "cable",
        },
        "typed": {},
        "typedOf": {},
        "mission": None,
        "supply": "one-way",
        "load": {
            "gear_ratio": load.get("gear_ratio", 1),
            "gear_efficiency": load.get("gear_efficiency", 1),
            "motor_inertia": load.get("motor_inertia", 0),
            "inertia": load.get("inertia", 0),
            "friction_coulomb": load.get("friction_coulomb", 0),
            "friction_viscous": load.get("friction_viscous", 0),
            "mass": gravity.get("mass", 0),
            "arm": gravity.get("arm", 0),
            "start_angle_deg": setup["profile"].get("start_angle_deg", 0),
            **dict.fromkeys(zero_keys, 0),
        },
        "loadKind": "",
        "compare": "devices",
        "motorSet": [],
        "sweep": {"key": "f_khz", "values": ""},
        "loadSet": [],
        "pwmPeriods": 5,
        "mapAt": "",
        "loadTouched": False,
        "inertiaOwn": False,
        "loadTouchedBefore": False,
        "segments": [dict(s) for s in setup["profile"]["segments"]],
        "phases": None,
        "sink": {"rth": "", "capacity": "", "t_ambient": "", "c_link_uf": "", "precharge": "", "repeats": 1},
        "start": {"method": "sensor", "current": "", "align_time": "", "handover_rpm": "", "flux_time": ""},
        "devices": [],
        "lead": "",
        "added": [],
        "kindPicked": False,
        "supplyOwn": False,
        "motorOwn": {},
        "pointOf": {},
        "loadPicked": "",
        "focus": None,
        "focusPicked": False,
        "tab": "proposal",
        "metric": "loss",
        "map": {"rpm_max": "", "torque_max": ""},
        "event": {"l_cs_nh": "", "l_g_nh": "", "v_off": "", "layout": "", "layout_name": ""},
    }


def number(text: Any, scale: float = 1.0) -> float | None:
    """A box that may be left empty: its figure in the engine's unit, or None."""
    if isinstance(text, bool):
        return None
    if isinstance(text, (int, float)):
        return text * scale if scale != 1 else text
    if isinstance(text, str) and text.strip():
        try:
            value = float(text.strip().replace(",", "."))
        except ValueError:
            return None
        if not math.isfinite(value):
            return None
        return value * scale if scale != 1 else (int(value) if value.is_integer() and "." not in text else value)
    return None


def lead_of(state: dict) -> str:
    """The device the design starts from (`underTest` in store.ts)."""
    devices = state.get("devices") or []
    if state.get("lead") and state["lead"] in devices:
        return state["lead"]
    return devices[0] if devices else ""


def request(state: dict) -> dict:
    """The request the engine expects, in SI units (`request` in state.ts)."""
    c = state["conditions"]
    motor = {k: v for k, v in state["motors"][state["kind"]].items() if v != ""}
    return {
        "motor": {"type": state["kind"], **motor, "t_motor": number(c.get("t_motor"))},
        "conditions": {
            "v_dc": c["v_dc"],
            "rpm": c["rpm"],
            "torque": c["torque"],
            "f_sw": c["f_khz"] * 1000,
            "t_sink": c["t_sink"],
            "pwm": c.get("pwm") or None,
            "v_drive": number(c.get("v_drive")),
            "rg_on": number(c.get("rg_on")),
            "rg_off": number(c.get("rg_off")),
            "t_dead": number(c.get("t_dead_ns"), 1e-9),
            "l_loop": number(c.get("l_loop_nh"), 1e-9),
            "t_min_pulse": number(c.get("t_min_ns"), 1e-9) or 0,
            "parallel": number(c.get("parallel")) or 1,
            "edge_limit": c.get("edge_limit", "cable"),
            "cooling": c.get("cooling", "held"),
            "t_ambient": c.get("t_ambient", 40),
            "rth_sink": number(c.get("rth_sink")),
            "rth_ja": number(c.get("rth_ja")),
            "board_area": number(c.get("board_area")),
            "copper": number(c.get("copper")),
            "copper_ref": number(c.get("copper_ref")),
            "interface": c.get("interface") or None,
            "rth_case_sink": number(c.get("rth_case_sink")),
            "sized": c.get("sized") or None,
            "sized_earlier": None,
        },
        "supply": state.get("supply", "one-way"),
    }


def _turning(l: dict) -> dict:
    out: dict = {}
    if _f(l.get("tumble_mass")) and _f(l.get("tumble_radius")):
        out["tumble"] = {"mass": l["tumble_mass"], "radius": l["tumble_radius"]}
    if _f(l.get("pulsation_torque")):
        out["pulsation"] = {"torque": l["pulsation_torque"], "per_turn": 1}
    if _f(l.get("breakaway_torque")) and _f(l.get("breakaway_rpm")):
        out["breakaway"] = {"torque": l["breakaway_torque"], "rpm": l["breakaway_rpm"]}
    return out


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def motion_request(state: dict) -> dict:
    """The load and its motion (`motionRequest` in state.ts)."""
    l = state["load"]
    load = {
        k: l.get(k, 0)
        for k in (
            "gear_ratio",
            "gear_efficiency",
            "motor_inertia",
            "inertia",
            "friction_coulomb",
            "friction_viscous",
            "constant_torque",
            "fan_coefficient",
        )
    }
    if _f(l.get("mass")) and _f(l.get("arm")):
        load["gravity"] = {"mass": l["mass"], "arm": l["arm"]}
    if _f(l.get("v_mass")) and _f(l.get("wheel_radius")):
        load["vehicle"] = {k: l.get(k, 0) for k in ("rolling_resistance", "drag_area", "slope_percent")} | {
            "mass": l["v_mass"],
            "wheel_radius": l["wheel_radius"],
        }
    load |= _turning(l)
    angle = l.get("start_angle_deg", 0)
    phases = state.get("phases")
    profile = (
        {"start_angle_deg": angle, "phases": phases}
        if phases
        else {"start_angle_deg": angle, "segments": state.get("segments") or []}
    )
    sink = state.get("sink") or {}
    mission = state.get("mission")
    return {
        "load": load,
        "profile": profile,
        "mission": {k: mission[k] for k in ("time", "rpm", "torque")} if mission else None,
        "heatsink": {
            "rth": number(sink.get("rth")),
            "capacity": number(sink.get("capacity")),
            "t_ambient": number(sink.get("t_ambient"))
            if number(sink.get("t_ambient")) is not None
            else state["conditions"]["t_sink"],
        },
        "c_link": number(sink.get("c_link_uf"), 1e-6),
        "precharge": number(sink.get("precharge")),
        "start": dict(state.get("start") or {}),
        "repeats": sink.get("repeats", 1),
    }


def _given(record: dict) -> dict:
    return {k: v for k, v in record.items() if v is not None and v != ""}


def design_of(state: dict) -> dict:
    """The design file for the page as it stands (`designFile` in designfile.ts), as the dict
    `motionsim.design.run` takes: the device the design starts from named first."""
    req, motion = request(state), motion_request(state)
    lead = lead_of(state)
    devices = list(dict.fromkeys([*([lead] if lead else []), *state.get("devices", [])]))
    design: dict[str, Any] = {
        "devices": devices,
        "motor": _given(req["motor"]),
        "conditions": _given(req["conditions"]),
        "supply": req["supply"],
        "load": motion["load"],
        "profile": motion["profile"],
        "start": _given(motion["start"]),
        "repeats": motion["repeats"],
    }
    heatsink = _given(motion["heatsink"])
    if heatsink.get("rth") is not None:
        design["heatsink"] = heatsink
    if motion["c_link"] is not None:
        design["c_link"] = motion["c_link"]
    if state.get("focus") in devices:
        design["follow"] = state["focus"]
    return design


def lab_body(state: dict) -> dict:
    """The design as the lab simulates it (`designOfPage` in control/entry.ts)."""
    devices = state.get("devices") or []
    focus = state.get("focus") if state.get("focus") in devices else None
    body = {
        **request(state),
        "device": focus or lead_of(state),
        "load": motion_request(state)["load"],
    }
    if state.get("loadPicked"):
        body["application"] = state["loadPicked"]
    return body


# -- the page's key, as JSON.stringify writes it --------------------------------------------------


def _js_number(x: float | int) -> str:
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, int):
        return str(x)
    if not math.isfinite(x):
        return "null"
    if x == 0:
        return "0"
    _sign, digits, exponent = Decimal(repr(abs(x))).normalize().as_tuple()
    ds = "".join(map(str, digits))
    k, n = len(ds), len(ds) + int(exponent)
    neg = "-" if x < 0 else ""
    if k <= n <= 21:
        return neg + ds + "0" * (n - k)
    if 0 < n <= 21:
        return neg + ds[:n] + "." + ds[n:]
    if -6 < n <= 0:
        return neg + "0." + "0" * (-n) + ds
    e = n - 1
    mant = ds[0] + ("." + ds[1:] if k > 1 else "")
    return f"{neg}{mant}e{'+' if e >= 0 else '-'}{abs(e)}"


def js_stringify(value: Any) -> str:
    """`JSON.stringify` of plain data: what the page keys a design by."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _js_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return "[" + ",".join("null" if v is None else js_stringify(v) for v in value) + "]"
    if isinstance(value, dict):
        return (
            "{"
            + ",".join(f"{json.dumps(str(k), ensure_ascii=False)}:{js_stringify(v)}" for k, v in value.items())
            + "}"
        )
    return "null"


def lab_key(state: dict) -> str:
    return js_stringify(lab_body(state))


# -- writing a figure as the page's box does -------------------------------------------------------


def _at(state: dict, path: str) -> tuple[dict, str]:
    *head, last = path.split(".")
    node = state
    for key in head:
        node = node.setdefault(key, {})
    return node, last


def get_field(state: dict, path: str) -> Any:
    node: Any = state
    for key in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _checked(name: str, spec: dict, value: Any, setup: dict) -> Any:
    """A value for a figure, as the state holds it, or the refusal of one it cannot be."""
    label = spec["label"]
    unit = f" {spec['unit']}" if spec.get("unit") else ""
    if spec["is"] in (NUM, WHOLE):
        if isinstance(value, str):
            value = number(value)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise Refusal(f"{label} is a number{unit}", f"give {name} as a number", name)
        if spec["is"] == WHOLE and not float(value).is_integer():
            raise Refusal(f"{label} is a whole number", f"give {name} as a whole number", name)
        low, high = spec.get("low"), spec.get("high")
        if (low is not None and value < low) or (high is not None and value > high):
            raise Refusal(
                f"{label} of {value:g}{unit} is outside what the page takes ({low:g} to {high:g}{unit})",
                f"give {name} between {low:g} and {high:g}",
                name,
            )
        return int(value) if spec["is"] == WHOLE else value
    if spec["is"] == WORD:
        choices = spec.get("choices") or (list(setup["motors"]) if name == "kind" else [])
        if value not in choices:
            raise Refusal(
                f"{label} is one of {', '.join(repr(c) for c in choices)}",
                f"give {name} as one of them",
                name,
            )
        return value
    # TEXT: a figure kept as typed, empty for "not given".
    if value is None or value == "":
        return ""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise Refusal(f"{label} is a figure{unit}, or empty", f"give {name} as a number, or an empty string", name)
    if name == "pwm":
        offered = [p.get("id", p) if isinstance(p, dict) else p for p in setup.get("pwm", [])]
        if offered and value not in offered:
            raise Refusal(f"the modulation is one of {', '.join(map(str, offered))}", "give pwm as one of them", name)
        return value
    if isinstance(value, str) and number(value) is None:
        raise Refusal(f"{label} is a figure{unit}: {value!r} is not one", f"give {name} as a number", name)
    return _js_number(value) if isinstance(value, (int, float)) else value.strip()


def set_fields(state: dict, fields: dict, setup: dict) -> list[str]:
    """Set figures of the design as the page's boxes set them, each the user's own from then
    on. Returns the paths set. Raises a Refusal, naming the field, for one that cannot be."""
    if not isinstance(fields, dict) or not fields:
        raise Refusal("no figures were given", 'give fields as {"v_dc": 60, "rpm": 3000, ...}', "fields")
    staged = copy.deepcopy(state)
    set_paths: list[str] = []
    for name, value in fields.items():
        if name == "f_sw":  # in hertz, as the engine and the design file name it
            name, value = "f_khz", (value / 1000 if isinstance(value, (int, float)) else value)
        if name == "segments":
            staged["segments"] = _segments(value)
            staged["phases"] = None
            staged["mission"] = None
            set_paths.append("segments")
            continue
        if name.startswith("motor."):
            set_paths.append(_set_motor(staged, name.removeprefix("motor."), value, setup))
            continue
        spec = FIELDS.get(name)
        if spec is None:
            known = ", ".join(sorted(k for k in FIELDS if "." not in k))
            raise Refusal(
                f"the design has no figure called {name}",
                f"one of {known}; motor.<figure> for the motor (list_parts shows them); load.<figure>; "
                "sink.<figure>; start.<figure>; segments",
                name,
            )
        checked = _checked(name, spec, value, setup)
        node, last = _at(staged, spec["path"])
        node[last] = checked
        set_paths.append(spec["path"])
        _own(staged, name, spec["path"], checked)
    state.clear()
    state.update(staged)
    return set_paths


def _own(state: dict, name: str, path: str, value: Any) -> None:
    """A figure set is the user's own: the starting point that follows the part leaves it be."""
    key = path.split(".")[-1]
    if path.startswith("conditions.") and key in POINT_KEYS:
        state.setdefault("pointOf", {}).setdefault(state["kind"], {})[key] = value
    if name == "supply":
        state["supplyOwn"] = True
    if name == "kind":
        state["kindPicked"] = True
        point = state.get("pointOf", {}).get(value, {})
        state["conditions"].update(point)
    if path.startswith("load."):
        state["loadTouched"] = True
        if key == "inertia":
            state["inertiaOwn"] = True
    c = state["conditions"]
    if path.startswith("conditions.") and c.get("sized") == key:
        c["sized"], c["sizedFor"] = "", ""


def _set_motor(state: dict, key: str, value: Any, setup: dict) -> str:
    kind = state["kind"]
    spec = setup["motors"][kind]
    fields = {f["key"]: f for f in [*spec.get("fields", []), *(spec.get("optional") or [])]}
    if key not in fields:
        raise Refusal(
            f"a {spec.get('label', kind)} motor has no figure called {key}",
            f"one of {', '.join(fields)}",
            f"motor.{key}",
        )
    field = fields[key]
    if field.get("options"):
        if value not in field["options"]:
            raise Refusal(
                f"{field['label']} is one of {', '.join(field['options'])}",
                "give it as one of them",
                f"motor.{key}",
            )
    elif value == "" and not field.get("required"):
        value = ""
    else:
        value = number(value) if isinstance(value, str) else value
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            unit = f" {field['unit']}" if field.get("unit") else ""
            raise Refusal(f"{field['label']} is a number{unit}", f"give motor.{key} as a number", f"motor.{key}")
    state["motors"].setdefault(kind, {})[key] = value
    own = state.setdefault("motorOwn", {}).setdefault(kind, [])
    if key not in own:
        own.append(key)
    return f"motors.{kind}.{key}"


def _segments(value: Any) -> list[dict]:
    if not isinstance(value, list) or not value:
        raise Refusal(
            "the motion is a list of stretches",
            'give segments as [{"duration": s, "speed_start": rpm, "speed_end": rpm}, ...] at the load',
            "segments",
        )
    out = []
    for k, s in enumerate(value):
        if not isinstance(s, dict):
            raise Refusal(
                f"stretch {k + 1} of the motion is not an object", "give each with duration and speeds", "segments"
            )
        seg = {}
        for key in ("duration", "speed_start", "speed_end"):
            v = s.get(key)
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                raise Refusal(
                    f"stretch {k + 1} of the motion needs {key} as a number", "give it", f"segments.{k}.{key}"
                )
            seg[key] = v
        if seg["duration"] <= 0:
            raise Refusal(
                f"stretch {k + 1} of the motion lasts no time",
                "give a duration above nought, in s",
                f"segments.{k}.duration",
            )
        out.append(seg)
    return out


def settle(state: dict, setup: dict, suggest: dict | None) -> list[dict]:
    """Every figure the user has not typed put where the device under test starts it (`settle`
    in follow.ts). Returns what moved."""
    changes: list[dict] = []
    if not state.get("kindPicked") and suggest:
        recommended = next(
            (k for k, m in suggest["motors"].items() if k in setup["motors"] and m["fit"] == "recommended"), None
        )
        if recommended and recommended != state["kind"]:
            changes.append({"path": "kind", "from": state["kind"], "to": recommended})
            state["kind"] = recommended
    supply = ((suggest or {}).get("application") or {}).get("supply")
    if supply and not state.get("supplyOwn") and state.get("supply") != supply:
        changes.append({"path": "supply", "from": state["supply"], "to": supply})
        state["supply"] = supply
    for kind, spec in setup["motors"].items():
        example = {**spec["values"], **(((suggest or {}).get("motors") or {}).get(kind, {}).get("values") or {})}
        own = set((state.get("motorOwn") or {}).get(kind, []))
        now = state["motors"].setdefault(kind, {})
        for key, value in example.items():
            if key == "type" or key in own or now.get(key) == value:
                continue
            if kind == state["kind"]:
                changes.append({"path": f"motors.{kind}.{key}", "from": now.get(key, ""), "to": value})
            now[key] = value
    kind = state["kind"]
    start = (((suggest or {}).get("motors") or {}).get(kind) or {}).get("start") or setup["motors"][kind]["start"]
    point = {
        "v_dc": start["v_dc"],
        "rpm": start["rpm"],
        "torque": start["torque"],
        "f_khz": start["f_sw"] / 1000,
        "pwm": "",
    }
    point |= (state.get("pointOf") or {}).get(kind, {})
    for key in POINT_KEYS:
        if state["conditions"].get(key) != point[key]:
            changes.append({"path": f"conditions.{key}", "from": state["conditions"].get(key), "to": point[key]})
            state["conditions"][key] = point[key]
    return changes


def summary(state: dict | None, setup: dict) -> dict:
    """The design in a few lines, with units: what get_session says of it."""
    if not state:
        return {"state": "empty", "said": "Nothing is set up yet: choose a part (list_parts, then choose_part)."}
    c = state["conditions"]
    kind = state["kind"]
    motor = {k: v for k, v in state["motors"].get(kind, {}).items() if k != "type" and v != ""}
    names = {d["id"]: d["name"] for d in setup.get("devices", [])}
    lead = lead_of(state)
    return {
        "parts": [{"id": d, "name": names.get(d, d), "leads": d == lead} for d in state.get("devices", [])],
        "motor": {"kind": kind, "label": setup["motors"][kind].get("label", kind), **motor},
        "supply": state.get("supply"),
        "point": {
            "v_dc_V": c["v_dc"],
            "rpm": c["rpm"],
            "torque_Nm": c["torque"],
            "f_sw_kHz": c["f_khz"],
            "pwm": c.get("pwm") or "the motor's usual",
        },
        "cooling": {
            "kind": c.get("cooling"),
            "t_sink_C": c.get("t_sink"),
            "t_ambient_C": c.get("t_ambient"),
            **{k: c[k] for k in ("rth_sink", "rth_ja", "board_area") if c.get(k) not in ("", None)},
        },
        "parallel": c.get("parallel", 1),
        "load": state.get("loadPicked") or state.get("loadKind") or "the page's own",
        "motion": f"{len(state.get('segments') or [])} stretches"
        if not state.get("phases")
        else f"{len(state['phases'])} phases",
    }


def apply_preset(state: dict, preset: dict) -> None:
    """Make an application's load the load of step 4 (`applyPreset` in engine/loads.ts, as a
    pick from the list makes it)."""
    l = preset["load"]
    gravity, vehicle = l.get("gravity") or {}, l.get("vehicle") or {}
    tumble, pulse, brk = l.get("tumble") or {}, l.get("pulsation") or {}, l.get("breakaway") or {}
    state["load"] = {
        "gear_ratio": l.get("gear_ratio", 1),
        "gear_efficiency": l.get("gear_efficiency", 1),
        "motor_inertia": l.get("motor_inertia", 0),
        "inertia": l.get("inertia", 0),
        "friction_coulomb": l.get("friction_coulomb", 0),
        "friction_viscous": l.get("friction_viscous", 0),
        "mass": gravity.get("mass", 0),
        "arm": gravity.get("arm", 0),
        "start_angle_deg": preset.get("start_angle_deg", 0),
        "constant_torque": l.get("constant_torque", 0),
        "fan_coefficient": l.get("fan_coefficient", 0),
        "v_mass": vehicle.get("mass", 0),
        "wheel_radius": vehicle.get("wheel_radius", 0),
        "rolling_resistance": vehicle.get("rolling_resistance", 0),
        "drag_area": vehicle.get("drag_area", 0),
        "slope_percent": vehicle.get("slope_percent", 0),
        "tumble_mass": tumble.get("mass", 0),
        "tumble_radius": tumble.get("radius", 0),
        "pulsation_torque": pulse.get("torque", 0),
        "breakaway_torque": brk.get("torque", 0),
        "breakaway_rpm": brk.get("rpm", 0),
    }
    phases = preset.get("phases") or None
    if phases:
        state["phases"] = copy.deepcopy(phases)
        state["segments"] = [dict(s) for p in phases for _ in range(p.get("repeat", 1)) for s in p["segments"]]
    else:
        state["phases"] = None
        state["segments"] = [dict(s) for s in preset.get("segments", [])]
    state["inertiaOwn"] = False
    state["loadKind"] = preset["id"]
    state["loadPicked"] = preset["id"]
    state["loadTouched"] = False
    state["mission"] = None
    if state["kind"] in ("pmsm", "bldc", "synrm") and preset.get("start"):
        state["start"]["method"] = preset["start"]
    state["loadSet"] = [x for x in state.get("loadSet", []) if x.get("id") != preset["id"]]
