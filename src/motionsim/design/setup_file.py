"""The design as it is given: a file to start from, sized to a device; the checks that
refuse a design that cannot be one before any step is run; the one form the steps take it
in; and the marks and the date a report carries."""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import os
from pathlib import Path

from motionsim.errors import Refusal
from motionsim.files import read_record, read_yaml
from motionsim.service.presets import load_presets, suggest
from motionsim.service.validate import MOST_DEVICES, strict_numbers, supply
from motionsim.service.workspace import Workspace, bring_device

MOST = MOST_DEVICES  # devices compared at once, as on the page
KNOWN = {
    "devices",
    "motor",
    "motors",
    "conditions",
    "supply",
    "load",
    "load_kind",
    "profile",
    "heatsink",
    "c_link",
    "repeats",
    "t_ambient",
    "follow",
    "start",
}
CONDITIONS = {
    "v_dc", "rpm", "torque", "f_sw", "parallel", "pwm", "cooling", "t_sink", "t_ambient", "rth_sink", "rth_ja", "board_area",
    "copper", "copper_ref", "rth_case_sink", "interface", "t_sink_max", "v_drive", "rg_on", "rg_off", "t_dead", "l_loop", "t_min_pulse", "t_motor",
    "sized", "sized_earlier", "edge_limit",
}  # fmt: skip


SETUP_HEAD = """\
# A design for `motionsim design run`. Edit the figures to yours.
#   devices     made-up names (example-mosfet, example), or paths to device files
#               (.device.yaml) or to figures typed from a datasheet (motionsim template device)
#   motor       its kind and catalogue figures (motionsim template pmsm, bldc, dc, ...)
#   conditions  SI units: V, rpm, N·m, Hz, s, ohm, °C, K/W. cooling is one of
#               held (t_sink), heatsink (rth_sink, t_ambient), none (rth_ja, t_ambient),
#               board (rth_ja, board_area, copper, t_ambient). Gate drive left out is chosen.
#               On a heatsink, interface (grease or pad) is the layer under each package and
#               rth_case_sink its resistance where you know it; left out, they are worked out.
#               edge_limit is how fast an edge the chosen gate resistors allow: cable (5 V/ns,
#               a motor on a cable), close (20 V/ns, a motor close to the drive) or none.
#   load, profile   what the motor moves and how: leave out to judge the design point alone
#   start       how the drive starts the motor: method is sensor (the default), injection or
#               open_loop, with current (A rms), handover_rpm and align_time (s) where known
"""


def starting_setup(device: str, workspace: Workspace, kind: str | None = None) -> dict:
    """A design to start from for a device: the supply it suits, the kind of motor usual with
    it wound for that supply, a design point, and the usual load for that motor sized to it."""
    suggested = suggest({"device": device}, workspace)
    motors = suggested["motors"]
    kind = kind or next((k for k, m in motors.items() if m["fit"] == "recommended"), next(iter(motors)))
    if kind not in motors:
        raise Refusal(f"no kind of motor called {kind}", f"one of {', '.join(motors)}", "motor")
    start = motors[kind]["start"]
    offered = load_presets(kind, start["rpm"], start["torque"], start["v_dc"], motors[kind]["values"])
    # The most usual application this motor can run: one sized to it, or one of a size of its
    # own that it can.
    load = next((p for p in offered if p["runs"] is None or p["runs"]["ok"]), offered[0])
    return {
        "devices": [device],
        "motor": {"type": kind, **motors[kind]["values"]},
        "conditions": {**start, "parallel": 1, "cooling": "held", "t_sink": 60},
        "supply": "one-way",
        "load_kind": load["id"],
        "load": load["load"],
        "profile": {"start_angle_deg": load.get("start_angle_deg", 0)}
        | ({"phases": load["phases"]} if load.get("phases") else {"segments": load["segments"]}),
    }


def _stray(given, known, strict: bool, what: str, holds: str, field: str | None = None) -> None:
    """A file written by hand is held to the names; the page sends more than these, by design."""
    if not strict:
        return
    if not all(isinstance(k, str) for k in given):
        unknown = ["a name that is not a word"]
    else:
        unknown = sorted(k for k in given if k not in known)
    if unknown:
        raise Refusal(
            f"the {what} names this tool does not know: {', '.join(unknown)}",
            holds,
            unknown[0] if field is None else field,
        )


def _validate_devices(setup) -> None:
    if not isinstance(setup, dict):
        raise Refusal("the design is not a list of names and values", "see `motionsim design init`", "")
    named = setup.get("devices")
    if not isinstance(named, list) or not named:
        raise Refusal("no device is named", "name at least one under `devices`, as a list", "devices")
    if len(named) > MOST:
        raise Refusal(
            f"{len(named)} devices are named, and {MOST} is the most compared at once", f"name up to {MOST}", "devices"
        )


def _validate_parts(setup: dict) -> None:
    """The motor or motors, the conditions, the load and its motion: each of the kind it has to be."""
    motors = setup.get("motors")
    if motors is not None and (
        not isinstance(motors, list) or not motors or not all(isinstance(m, dict) for m in motors)
    ):
        raise Refusal("`motors` is a list of motors, each with its kind and figures", "see `motionsim agent`", "motors")
    for key in ("motor", "conditions"):
        if not isinstance(setup.get(key), dict) and not (key == "motor" and motors):
            raise Refusal(f"the design has no {key}", "see `motionsim design init`", key)
    for key in ("load", "profile", "heatsink"):
        if setup.get(key) is not None and not isinstance(setup[key], dict):
            raise Refusal(f"the {key} is not a set of names and values", f"give the {key}'s figures by name", key)
    given = setup.get("profile") or {}
    phases = given.get("phases")
    segments = given.get("segments")
    if phases is not None:
        if not isinstance(phases, list) or not phases or not all(isinstance(p, dict) for p in phases):
            raise Refusal(
                "the profile's phases are not a list of phases",
                "give each phase its name, how many times it repeats and its segments",
                "profile",
            )
        segments = [s for p in phases for s in (p.get("segments") or [None])]
    if setup.get("profile") is not None and (
        not isinstance(segments, list) or not segments or not all(isinstance(s, dict) for s in segments)
    ):
        raise Refusal(
            "the profile's segments are not a list of stretches",
            "give each stretch its duration, speed_start and speed_end",
            "profile",
        )


FIGURES = ("motor", "motors", "conditions", "load", "profile", "heatsink", "c_link", "repeats", "t_ambient")


def validate_setup(setup, strict: bool = True) -> None:
    """A design that cannot be one is refused here, before any step is run: what it names,
    and what kind of thing each part of it is. Nothing is changed."""
    _validate_devices(setup)
    if setup.get("motors") is not None and setup.get("motor") is not None:
        raise Refusal(
            "the design gives both `motor` and `motors`",
            "give one: `motors` to compare several, the first being the design's own",
            "motors",
        )
    supply(setup)
    _stray(setup, KNOWN, strict, "design has", f"a design holds {', '.join(sorted(KNOWN))}")
    _validate_parts(setup)
    _stray(
        setup.get("heatsink") or {},
        ("rth", "capacity", "t_ambient"),
        strict,
        "heatsink has",
        "a heatsink holds rth (K/W), capacity (J/K) and t_ambient (°C)",
        "heatsink",
    )
    _stray(
        setup["conditions"], CONDITIONS, strict, "conditions have", f"conditions hold {', '.join(sorted(CONDITIONS))}"
    )
    if strict:
        for key in FIGURES:
            # A figure inside a part is named by its own name there; one at the top by its own.
            strict_numbers(setup.get(key), key, "" if isinstance(setup.get(key), (dict, list)) else key)


def normalise_setup(setup: dict) -> dict:
    """The design in the one form the steps take: the first of several motors as the
    design's own, a motor with no kind named a permanent-magnet one, and the winding's
    temperature with the motor wherever it was written."""
    motors = setup.get("motors")
    # Several motors on one inverter: the first of them is the one the rest of the design is about.
    motor = {"type": "pmsm", **(motors[0] if motors is not None else setup["motor"])}
    c = dict(setup["conditions"])
    # The winding's temperature is a condition to the user and a property of the motor to
    # the engine: taken from either place.
    if c.get("t_motor") not in ("", None) and motor.get("t_motor") in ("", None):
        motor["t_motor"] = c["t_motor"]
    c.pop("t_motor", None)
    return {**setup, "devices": [str(d) for d in setup["devices"]], "motor": motor, "conditions": c}


def setup_marks(setup: dict, workspace: Workspace) -> dict:
    """So that two people with a report each can tell whether they ran the same thing: a mark
    of the design as given, and one of each device file as it was read."""
    return {
        "design": _mark(json.dumps(_canon({k: v for k, v in setup.items() if k != "devices"})).encode()),
        "devices": {key: _mark(workspace.paths()[key].read_bytes()) for key in setup["devices"]},
    }


def report_date(given: str | None = None) -> str:
    """The date a report carries: the one given, else the one the build's clock is pinned to
    (SOURCE_DATE_EPOCH, as other tools read it), else today. So that the same design run
    twice can give the same bytes."""
    if given:
        try:
            return datetime.date.fromisoformat(str(given)).isoformat()
        except ValueError:
            raise Refusal(f"{given} is not a date", "give it as year-month-day, like 2025-01-31", "date") from None
    pinned = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if pinned:
        try:
            return datetime.datetime.fromtimestamp(int(pinned), datetime.UTC).date().isoformat()
        except (ValueError, OverflowError, OSError):
            raise Refusal(
                "SOURCE_DATE_EPOCH is not a time", "set it to whole seconds since 1970, or unset it", "date"
            ) from None
    return datetime.date.today().isoformat()


def _canon(value):
    """A design in one form whatever way it was written: names in order, every number as
    the same number however it was typed."""
    if isinstance(value, dict):
        return [[str(k), _canon(v)] for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))]
    if isinstance(value, (list, tuple)):
        return [_canon(v) for v in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return repr(float(value))
    # The page sends what was typed as text: "100" is the 100 a file holds as a number.
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        return text
    return repr(number) if math.isfinite(number) else text


def _mark(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def _part(base: Path, entry, what: str, field: str):
    """A part of a design that may be a file of its own: read where it is one."""
    return read_record(base / entry, f"{what} file", field) if isinstance(entry, str) else entry


def load_setup(path: str | Path, workspace: Workspace) -> dict:
    """A design read from a file. Devices named by a path are brought into the workspace:
    a device file as it is, a file of typed figures built first."""
    path = Path(path)
    setup = read_yaml(path, "design")
    if not isinstance(setup, dict):
        raise Refusal(f"{path.name} is not a design", "start from `motionsim design init`", "")
    if isinstance(setup.get("motors"), list):  # each motor may be a file of its own too
        setup["motors"] = [_part(path.parent, m, "motor", "motors") for m in setup["motors"]]
    for key in ("motor", "load", "profile"):  # each may be a file of its own
        setup[key] = _part(path.parent, setup.get(key), key, key)
        if setup[key] is None:
            del setup[key]
    if not isinstance(setup.get("devices"), list):
        raise Refusal("no device is named", "name at least one under `devices`, as a list", "devices")
    setup["devices"] = [bring_device(str(entry), path.parent, workspace) for entry in setup["devices"]]
    return setup
