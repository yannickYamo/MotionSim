"""A whole design in one call: the steps of the page, run from a description of the design.

The page walks a person through a part, a motor, a supply and design point, a load, and
then shows what the power stage does. This module does the same from one description, for
a terminal or a coding agent: it runs each step through the very functions the page calls,
gathers what they answer into one document, and writes that document as a report in
Markdown. Nothing is worked out here that the page does not work out; there is no second
model to disagree with the first.

A step that cannot be run is not a fault: it comes back in its place in the document as a
refusal, with the reason, what to change, and the name of the figure at issue.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import logging
import time
from pathlib import Path

import yaml

from motionsim import __version__, page
from motionsim.engine import ThermalRunaway
from motionsim.text import written

log = logging.getLogger("motionsim")

MOST = 5  # devices compared at once, as on the page
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
}
CONDITIONS = {
    "v_dc", "rpm", "torque", "f_sw", "parallel", "pwm", "cooling", "t_sink", "t_ambient", "rth_sink", "rth_ja", "board_area",
    "copper", "copper_ref", "rth_case_sink", "interface", "t_sink_max", "v_drive", "rg_on", "rg_off", "t_dead", "l_loop", "t_min_pulse", "t_motor",
}  # fmt: skip

STEPS = ("fit", "verdict", "motion", "build", "drive")
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
#   load, profile   what the motor moves and how: leave out to judge the design point alone
"""


def _refusal(exc: Exception) -> dict:
    if isinstance(exc, page.Refused):
        return {"refused": exc.reason, "fix": exc.fix, "field": exc.field}
    if isinstance(exc, ThermalRunaway):
        return dict(page.RUNAWAY)
    raise exc


def _step(work, name: str = "") -> dict:
    began = time.perf_counter()
    try:
        return work()
    except (page.Refused, ThermalRunaway) as exc:
        return _refusal(exc)
    except (*page.UNWORKABLE, TypeError) as exc:  # a design file may hold anything
        log.info("%s refused: %r", name or "a step", exc)
        return page.unworkable(exc)
    finally:
        log.info("%s took %.2f s", name or "a step", time.perf_counter() - began)


def starting_setup(device: str, workspace: page.Workspace, kind: str | None = None) -> dict:
    """A design to start from for a device: the supply it suits, the kind of motor usual with
    it wound for that supply, a design point, and the usual load for that motor sized to it."""
    suggested = page.suggest({"device": device}, workspace)
    motors = suggested["motors"]
    kind = kind or next((k for k, m in motors.items() if m["fit"] == "recommended"), next(iter(motors)))
    if kind not in motors:
        raise page.Refused(f"no kind of motor called {kind}", f"one of {', '.join(motors)}", "motor")
    start = motors[kind]["start"]
    load = page.load_presets(kind, start["rpm"], start["torque"], start["v_dc"])[0]
    return {
        "devices": [device],
        "motor": {"type": kind, **motors[kind]["values"]},
        "conditions": {**start, "parallel": 1, "cooling": "held", "t_sink": 60},
        "supply": "one-way",
        "load_kind": load["id"],
        "load": load["load"],
        "profile": {"start_angle_deg": load.get("start_angle_deg", 0), "segments": load["segments"]},
    }


def run(
    setup: dict, workspace: page.Workspace, steps: tuple[str, ...] = STEPS, traces: bool = False, strict: bool = True
) -> dict:
    """Every step of a design, in the page's order. `setup` is what the page sends: a motor,
    conditions, the devices by their names in the workspace, and optionally a load and its
    motion. The first device that passes is the one followed through the motion, the build
    sheet and the capability; the others stand beside it in the verdict."""
    if not isinstance(setup, dict):
        raise page.Refused("the design is not a list of names and values", "see `motionsim design init`", "")
    named = setup.get("devices")
    if not isinstance(named, list) or not named:
        raise page.Refused("no device is named", "name at least one under `devices`, as a list", "devices")
    devices = [str(d) for d in named]
    if len(devices) > MOST:
        raise page.Refused(
            f"{len(devices)} devices are named, and {MOST} is the most compared at once",
            f"name up to {MOST}",
            "devices",
        )
    if setup.get("motors") is not None and setup.get("motor") is not None:
        raise page.Refused(
            "the design gives both `motor` and `motors`",
            "give one: `motors` to compare several, the first being the design's own",
            "motors",
        )
    if setup.get("supply", "one-way") not in ("one-way", "battery"):
        raise page.Refused(
            f"there is no supply called {setup.get('supply')}", "one-way (a power supply) or battery", "supply"
        )
    unknown = (
        sorted(str(k) for k in setup if k not in KNOWN)
        if all(isinstance(k, str) for k in setup)
        else ["a name that is not a word"]
    )
    if unknown and strict:  # a file written by hand is held to the names; the page sends more than these, by design
        raise page.Refused(
            f"the design has names this tool does not know: {', '.join(unknown)}",
            f"a design holds {', '.join(sorted(KNOWN))}",
            unknown[0],
        )
    # Several motors on one inverter: `motors` is a list, and the first of them is the one
    # the rest of the design is about.
    motors = setup.get("motors")
    if motors is not None:
        if not isinstance(motors, list) or not motors or not all(isinstance(m, dict) for m in motors):
            raise page.Refused(
                "`motors` is a list of motors, each with its kind and figures", "see `motionsim agent`", "motors"
            )
        setup = {**setup, "motor": motors[0]}
    for key in ("motor", "conditions"):
        if not isinstance(setup.get(key), dict):
            raise page.Refused(f"the design has no {key}", "see `motionsim design init`", key)
    for key in ("load", "profile", "heatsink"):
        if setup.get(key) is not None and not isinstance(setup[key], dict):
            raise page.Refused(f"the {key} is not a set of names and values", f"give the {key}'s figures by name", key)
    segments = (setup.get("profile") or {}).get("segments")
    if setup.get("profile") is not None and (
        not isinstance(segments, list) or not segments or not all(isinstance(s, dict) for s in segments)
    ):
        raise page.Refused(
            "the profile's segments are not a list of stretches",
            "give each stretch its duration, speed_start and speed_end",
            "profile",
        )
    # A motor with no kind named is a permanent-magnet one, as a motor file is taken elsewhere.
    setup = {**setup, "motor": {"type": "pmsm", **setup["motor"]}}
    unknown = sorted(str(k) for k in setup.get("heatsink") or {} if k not in ("rth", "capacity", "t_ambient"))
    if unknown and strict:
        raise page.Refused(
            f"the heatsink has names this tool does not know: {', '.join(unknown)}",
            "a heatsink holds rth (K/W), capacity (J/K) and t_ambient (°C)",
            "heatsink",
        )
    c = dict(setup["conditions"])
    stray = sorted(str(k) for k in c if k not in CONDITIONS)
    if stray and strict:
        raise page.Refused(
            f"the conditions have names this tool does not know: {', '.join(stray)}",
            f"conditions hold {', '.join(sorted(CONDITIONS))}",
            stray[0],
        )
    motor = dict(setup["motor"])
    # The winding's temperature is a condition to the user and a property of the motor to
    # the engine: taken from either place.
    if c.get("t_motor") not in ("", None) and motor.get("t_motor") in ("", None):
        motor["t_motor"] = c["t_motor"]
    c.pop("t_motor", None)
    setup = {**setup, "motor": motor, "conditions": c}
    base = {"motor": motor, "conditions": c, "supply": setup.get("supply", "one-way")}
    out: dict = {
        "motionsim": __version__,
        "date": datetime.date.today().isoformat(),
        "setup": {
            **base,
            "devices": devices,
            **(
                {"load": setup["load"], "profile": setup["profile"]}
                if setup.get("load") and setup.get("profile")
                else {}
            ),
        },
        "devices": {key: workspace.summary(key, workspace.device(key)) for key in devices},
    }
    # So that two people with a report each can tell whether they ran the same thing: a mark
    # of the design as given, and one of each device file as it was read.
    out["marks"] = {
        "design": _mark(json.dumps(_canon({k: v for k, v in setup.items() if k != "devices"})).encode()),
        "devices": {key: _mark(workspace.paths()[key].read_bytes()) for key in devices},
    }
    if "fit" in steps:
        out["fit"] = _step(
            lambda: page.motor_fit(
                {
                    "motor": setup["motor"],
                    "device": devices[0],
                    "parallel": c.get("parallel"),
                    "rpm": c.get("rpm"),
                    "v_dc": c.get("v_dc"),
                },
                workspace,
            ),
            "fit",
        )
    out["stage"] = _step(lambda: page.stage(base), "stage")
    verdict = _step(lambda: page.proposal({**base, "devices": devices}, workspace), "verdict")
    out["verdict"] = verdict
    if "refused" in verdict or "refused" in out["stage"]:
        out["outcome"] = "refused"
        return _refusals(out)
    ran = [x for x in verdict["candidates"] if x["result"] is not None]
    passing = [x for x in ran if x["level"] in ("ok", "caution")]
    open_ = [x for x in ran if x["level"] == "undecided"]  # the data cannot say whether these pass
    chosen = (passing or open_ or ran or verdict["candidates"])[0]["id"]
    # The page asks for the device on its drawing, passing or not; a design follows the first that passes.
    if setup.get("follow") in [x["id"] for x in ran]:
        chosen = setup["follow"]
    out["followed"] = chosen
    out["outcome"] = (
        "passes"
        if passing and passing[0]["level"] == "ok"
        else "passes with cautions"
        if passing
        else "undecided"
        if open_
        else "does not pass"
    )
    one = {**base, "device": chosen}
    brief = ("summary", "checks", "start", "life", "sink_name", "refused", "fix", "field")

    def through(device: str, keep_traces: bool) -> dict:
        found = _step(
            lambda: page.cycle(
                {
                    **base,
                    "device": device,
                    "load": setup["load"],
                    "profile": setup["profile"],
                    "heatsink": setup.get("heatsink"),
                    "c_link": setup.get("c_link"),
                    "repeats": setup.get("repeats", 1),
                },
                workspace,
            ),
            f"motion of {device}",
        )
        return found if keep_traces else {k: v for k, v in found.items() if k in brief}

    if "motion" in steps and setup.get("load") and setup.get("profile"):
        out["motion"] = through(chosen, traces)
        # A part that passes at the design point and cannot do the motion does not pass.
        levels = {c.get("level") for c in out["motion"].get("checks", [])}
        if "fail" in levels:
            out["outcome"] = "does not pass"
        elif "undecided" in levels and out["outcome"] != "does not pass":
            out["outcome"] = "undecided"
        elif "caution" in levels and out["outcome"] == "passes":
            out["outcome"] = "passes with cautions"
        # Every device that ran is taken through the same motion, so that they can be set
        # side by side over the duty and not only at the design point.
        if len(ran) > 1:
            out["motions"] = {x["id"]: out["motion"] if x["id"] == chosen else through(x["id"], False) for x in ran}
    if motors is not None:
        out["motors"] = [_one_motor(m, k, chosen, setup, workspace) for k, m in enumerate(motors)]
    if "build" in steps:
        air = setup.get("t_ambient", c.get("t_ambient"))
        out["build"] = _step(lambda: page.recommendations({**one, "t_ambient": air}, workspace), "build")
    if "drive" in steps:
        out["drive"] = _step(lambda: page.capability(one, workspace), "drive")
    return _refusals(out)


def _refusals(out: dict) -> dict:
    """Every step that could not be run, by name, at the top of the answer where it cannot
    be missed, with the first of them in the three words a refusal always comes in."""
    found = {
        name: out[name]
        for name in ("fit", "stage", "verdict", "motion", "build", "drive")
        if isinstance(out.get(name), dict) and "refused" in out[name]
    }
    if found:
        first = next(iter(found.values()))
        out["refusals"] = sorted(found)
        out.update({"refused": first["refused"], "fix": first.get("fix", ""), "field": first.get("field", "")})
    return out


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
    return str(value)


def _mark(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def _one_motor(motor: dict, index: int, device: str, setup: dict, workspace: page.Workspace) -> dict:
    """One motor of several on the same inverter: what it asks at the design point and what
    the device then loses, by the same steps as the design itself."""
    request = {"motor": motor, "conditions": setup["conditions"], "supply": setup.get("supply", "one-way")}
    name = str(motor.get("name") or f"motor {index + 1} ({motor.get('type', '?')})")
    stage = _step(lambda: page.stage(request), f"stage of {name}")
    if "refused" in stage:
        return {"name": name, **stage}
    found = _step(lambda: page.proposal({**request, "devices": [device]}, workspace), f"verdict of {name}")
    if "refused" in found:
        return {"name": name, **found}
    x = found["candidates"][0]
    r = x["result"] or {}
    return {
        "name": name,
        "level": x["level"],
        "problem": x.get("problem"),
        "i_peak": stage["stage"]["i_peak"],
        "loss": r.get("loss"),
        "tj_peak": r.get("tj_peak"),
        "margin": x.get("margin"),
        "stall_tj": x.get("stall_tj"),
        "efficiency": x.get("efficiency"),
        "capacitor_rms": (x.get("link") or {}).get("capacitor_rms"),
        "checks": [k for k in x["checks"] if k["level"] != "ok"],
    }


WORD = {
    "ok": "passes",
    "caution": "passes, with cautions",
    "undecided": "undecided on this data",
    "fail": "does not pass",
}
TAG = {"ok": "Passes", "caution": "**Caution**", "undecided": "**Undecided**", "fail": "**Fails**"}


def rows(result: dict) -> list[dict]:
    """The comparison as a table: one row a device, and one a motor where several are
    compared, with every figure the report gives for it. For a spreadsheet."""
    out: list[dict] = []
    verdict = result.get("verdict", {})
    for x in verdict.get("candidates", []):
        r = x["result"] or {}
        gate = x.get("gate") or {}
        motion = (
            (result.get("motions") or {}).get(x["id"])
            or (result.get("motion") if x["id"] == result.get("followed") else None)
            or {}
        )
        q = motion.get("summary") or {}
        out.append(
            {
                "kind": "device",
                "name": x["name"],
                "verdict": WORD[x["level"]] if x["result"] else "cannot run",
                "loss_w": r.get("loss"),
                "conduction_w": r.get("conduction"),
                "switching_w": r.get("switching"),
                "tj_peak_c": r.get("tj_peak"),
                "margin_k": x.get("margin"),
                "stall_tj_c": x.get("stall_tj"),
                "stall_margin_k": x.get("stall_margin"),
                "shaft_over_dc": x.get("efficiency"),
                "data": r.get("validity"),
                "switching_data": (x.get("switching") or {}).get("text"),
                "v_drive_v": gate.get("v_drive"),
                "rg_on_ohm": gate.get("rg_on"),
                "rg_off_ohm": gate.get("rg_off"),
                "t_dead_s": gate.get("t_dead"),
                "motion_mean_loss_w": q.get("mean_loss"),
                "motion_tj_peak_c": q.get("peak"),
                "motion_energy_lost_j": q.get("loss_energy"),
                "not_ok": "; ".join(f"{k['topic']}: {k['message']}" for k in x["checks"] if k["level"] != "ok"),
            }
        )
    for m in result.get("motors", []):
        out.append(
            {
                "kind": "motor",
                "name": m["name"],
                "verdict": WORD.get(m.get("level"), "cannot run"),
                "loss_w": m.get("loss"),
                "tj_peak_c": m.get("tj_peak"),
                "margin_k": m.get("margin"),
                "stall_tj_c": m.get("stall_tj"),
                "shaft_over_dc": m.get("efficiency"),
                "i_peak_a": m.get("i_peak"),
                "capacitor_rms_a": m.get("capacitor_rms"),
                "not_ok": m.get("refused") or "; ".join(f"{k['topic']}: {k['message']}" for k in m.get("checks", [])),
            }
        )
    return out


COLUMNS = [
    "kind", "name", "verdict", "loss_w", "conduction_w", "switching_w", "tj_peak_c", "margin_k", "stall_tj_c", "stall_margin_k",
    "shaft_over_dc", "data", "switching_data", "v_drive_v", "rg_on_ohm", "rg_off_ohm", "t_dead_s", "motion_mean_loss_w",
    "motion_tj_peak_c", "motion_energy_lost_j", "i_peak_a", "capacitor_rms_a", "not_ok",
]  # fmt: skip


def csv_text(result: dict) -> str:
    import csv
    import io

    table = rows(result)
    columns = COLUMNS
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(table)
    return out.getvalue()


# ---------- the report ----------


def _n(value, unit: str = "", digits: int = 3) -> str:
    """A figure for the report. One that is not a number (a design refused for it is still
    reported) is shown as it was given."""
    if value is None:
        return "n/a"
    try:
        return f"{written(float(value), digits)} {unit}".strip()
    except (TypeError, ValueError):
        return f"{value} {unit}".strip()


def _f(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _cooling(c: dict) -> str:
    kind = c.get("cooling") or "held"
    air = f"{_n(c.get('t_ambient', 40))} °C air"
    under = ""
    if c.get("rth_case_sink") not in ("", None):
        under = f", {_n(c['rth_case_sink'])} K/W from each case to it"
    elif c.get("interface") == "pad":
        under = ", each package on a thermal pad"
    if kind == "heatsink":
        return f"a {_n(c.get('rth_sink'))} K/W heatsink in {air}{under}"
    if kind == "none":
        return f"no heatsink, each part in {air}" + (
            f", {_n(c['rth_ja'])} K/W junction to air" if c.get("rth_ja") else ""
        )
    if kind == "board":
        return f"no heatsink, parts on a {_n(c.get('board_area'))} cm² board in {air}"
    return f"a heatsink held at {_n(c.get('t_sink', 60))} °C{under}"


def _said(text: str) -> str:
    text = str(text).strip()
    return text[:1].upper() + text[1:] + ("" if text.endswith((".", ":", "?")) else ".")


def _refused(step: dict) -> list[str]:
    return [
        f"**This could not be run.** {_said(step['refused'])}" + (f" {_said(step['fix'])}" if step.get("fix") else ""),
        "",
    ]


def markdown(result: dict) -> str:
    """The design as a report in Markdown: what was tested, the verdict and why, the motion,
    what to build, what the part can drive, and what the result rests on. Written to be read
    by a person or handed to an agent as it is."""
    s = result["setup"]
    c = s["conditions"]
    m = s["motor"]
    lines: list[str] = []
    add = lines.append
    names = [result["devices"][k]["name"] for k in s["devices"]]
    add(f"# {' and '.join(names[:2])}{' and others' if len(names) > 2 else ''}: power-stage estimate")
    add("")
    add(
        f"{result['date']} · MotionSim {result['motionsim']}, an exploratory tool. Results are estimates from datasheet "
        "values, stated assumptions and simplified models. Verify by measurement before building anything."
    )
    add("")
    add(f"**Outcome: {result.get('outcome', 'not run')}.**")
    add("")
    marks = result.get("marks")
    if marks:
        add(
            f"Design {marks['design']}; device files "
            + ", ".join(f"{result['devices'][k]['name']} {v}" for k, v in marks["devices"].items())
            + ". The same marks mean the same inputs."
        )
        add("")

    add("## What was tested")
    add("")
    for key in s["devices"]:
        d = result["devices"][key]
        add(
            f"- Device: {d['name']}, {d['technology']}, {_n(d['v_max'])} V, {_n(d['i_nominal'])} A, {_n(d['tj_max'])} °C junction. "
            f"Switching loss: {d['switching']}."
        )
    # The motor's figures by the names the page gives them, not by the names in the file.
    named = {key: (label, unit) for key, label, unit, *_ in page.FIELDS.get(str(m.get("type")), [])}
    figures = ", ".join(
        f"{named[k][0].lower()} {v} {named[k][1]}".strip() if k in named else f"{k} {v}"
        for k, v in m.items()
        if k not in ("type", "name") and v not in ("", None)
    )
    kind = page.MOTOR_NAMES.get(str(m.get("type")), (None, str(m.get("type")), None))[1]
    add(f"- Motor: {kind} ({figures})")
    add(f"- Supply: {_n(c.get('v_dc'))} V, {'a battery' if s.get('supply') == 'battery' else 'a power supply'}")
    add(f"- Design point: {_n(c.get('rpm'))} rpm, {_n(c.get('torque'))} N·m")
    several = _f(c.get("parallel"), 1) > 1
    add(
        f"- Switching: {_n(_f(c.get('f_sw')) / 1000)} kHz, {c.get('pwm') or 'the usual modulation for this motor'}, "
        f"{_n(c.get('parallel') or 1)} device{'s' if several else ''} a switch"
    )
    add(f"- Cooling: {_cooling(c)}")
    if s.get("load"):
        segments = [x for x in (s.get("profile") or {}).get("segments") or [] if isinstance(x, dict)]
        add(
            f"- Load and motion: gear {_n(s['load'].get('gear_ratio', 1))}:1, {len(segments)} stretches, "
            f"{_n(sum(_f(x.get('duration')) for x in segments))} s"
        )
    add("")

    fit = result.get("fit")
    if fit:
        add("## Does the motor fit the part")
        add("")
        if "refused" in fit:
            lines.extend(_refused(fit))
        else:
            for x in fit["lines"]:
                add(f"- {'**Caution.** ' if x['level'] != 'ok' else ''}{_said(x['text'])}")
            add("")

    add("## Verdict at the design point")
    add("")
    verdict = result["verdict"]
    stage = result.get("stage", {})
    if "refused" in stage:
        lines.extend(_refused(stage))
    elif "refused" in verdict:
        lines.extend(_refused(verdict))
    else:
        alone = verdict["candidates"][0] if len(verdict["candidates"]) == 1 else None
        if alone is not None and alone["result"] is not None:
            add(
                {
                    "ok": f"{alone['name']} suits this motor and these conditions.",
                    "caution": f"{alone['name']} can do this, with cautions to read below.",
                    "undecided": f"{alone['name']} is not decided by this data: what the datasheet leaves out "
                    "could change the answer. The check below says what would settle it.",
                    "fail": f"{alone['name']} does not pass at this point: see the checks below.",
                }[alone["level"]]
            )
        else:
            for sentence in verdict.get("explain", []):
                add(_said(sentence))
        add("")
        add(
            "| Device | Verdict | Loss | Conduction | Switching | Hottest junction | Margin | Held still | Shaft over DC |"
        )
        add("|---|---|---|---|---|---|---|---|---|")
        word = WORD
        for x in verdict["candidates"]:
            r = x["result"]
            if r is None:
                add(f"| {x['name']} | cannot run: {x.get('problem') or ''} | | | | | | | |")
                continue
            add(
                f"| {x['name']} | {word[x['level']]} | {_n(r['loss'], 'W')} | {_n(r['conduction'], 'W')} | {_n(r['switching'], 'W')} | "
                f"{_n(r['tj_peak'], '°C')} | {_n(x.get('margin'), 'K')} | {_n(x.get('stall_tj'), '°C')} | "
                f"{_n(100 * x['efficiency'], '%') if x.get('efficiency') is not None else 'n/a'} |"
            )
        add("")
        for x in verdict["candidates"]:
            add(f"### {x['name']}")
            add("")
            if x.get("problem"):
                add(_said(x["problem"]) + (f" {_said(x['fix'])}" if x.get("fix") else ""))
                add("")
            raised = [k for k in x["checks"] if k["level"] != "ok"]
            passed = [k for k in x["checks"] if k["level"] == "ok"]
            for k in raised:
                add(f"- {TAG[k['level']].rstrip('*')}, {k['topic']}.** {_said(k['message'])}")
            for k in passed:
                add(f"- Passes, {k['topic']}. {_said(k['message'])}")
            gate = x.get("gate") or {}
            if gate.get("lines"):
                add("")
                add("Gate drive:")
                add("")
                for g in gate["lines"]:
                    add(f"- {_said(g)}")
            if x.get("needs"):
                add("")
                add("What it needs around it:")
                add("")
                for n in x["needs"]:
                    add(f"- {_said(n)}")
            if x.get("switching"):
                add("")
                add(f"Switching data: {_said(x['switching']['text'])}")
            add("")

    name = result["devices"].get(result.get("followed", ""), {}).get("name", "the device")
    motion = result.get("motion")
    if motion:
        add(f"## Through the motion, {name}")
        add("")
        if "refused" in motion:
            lines.extend(_refused(motion))
        else:
            q = motion["summary"]
            add(
                f"- Lasts {_n(q['duration'], 's')}; mean loss {_n(q['mean_loss'], 'W')}; energy lost {_n(q['loss_energy'], 'J')}; "
                f"energy to the shaft {_n(q['shaft_energy'], 'J')}"
            )
            add(
                f"- Hottest junction reached {_n(q['peak'], '°C')} against a {_n(q['tj_max'], '°C')} rating; "
                f"{_n(q['forever'], '°C')} if the hardest instant lasted forever"
            )
            if q.get("returned"):
                add(
                    f"- Braking returns {_n(q['returned'], 'J')}"
                    + (
                        f"; the link needs at least {_n(1e6 * q['c_needed'], 'µF')} to take it"
                        if q.get("c_needed")
                        else ""
                    )
                )
            for line in (motion.get("start") or {}).get("lines", []):
                add(f"- Starting: {_said(line)}")
            for k in motion["checks"]:
                tag = TAG[k["level"]]
                add(f"- {tag}, {k['topic']}. {_said(k['message'])}")
            add("")

    motions = result.get("motions")
    if motions:
        add("## Through the motion, each device")
        add("")
        add("| Device | Mean loss | Hottest junction | Energy lost | Not ok |")
        add("|---|---|---|---|---|")
        for key, found in motions.items():
            label = result["devices"][key]["name"]
            if "refused" in found:
                add(f"| {label} | cannot run: {found['refused']} | | | |")
                continue
            q = found["summary"]
            raised = "; ".join(k["topic"] for k in found["checks"] if k["level"] != "ok") or "nothing"
            add(
                f"| {label} | {_n(q['mean_loss'], 'W')} | {_n(q['peak'], '°C')} | {_n(q['loss_energy'], 'J')} | {raised} |"
            )
        add("")

    compared = result.get("motors")
    if compared:
        add(f"## Motors compared, on {name}")
        add("")
        add("| Motor | Verdict | Peak current | Loss | Hottest junction | Margin | Capacitor ripple | Shaft over DC |")
        add("|---|---|---|---|---|---|---|---|")
        for mo in compared:
            if "refused" in mo:
                add(f"| {mo['name']} | cannot run: {mo['refused']} | | | | | | |")
                continue
            add(
                f"| {mo['name']} | {WORD.get(mo['level'], 'cannot run')} | {_n(mo['i_peak'], 'A')} | {_n(mo['loss'], 'W')} | {_n(mo['tj_peak'], '°C')} | "
                f"{_n(mo['margin'], 'K')} | {_n(mo['capacitor_rms'], 'A rms')} | "
                f"{_n(100 * mo['efficiency'], '%') if mo.get('efficiency') is not None else 'n/a'} |"
            )
        add("")

    build = result.get("build")
    if build:
        add(f"## What to build, with {name}")
        add("")
        if "refused" in build:
            lines.extend(_refused(build))
        else:
            for item in build["items"]:
                add(f"### {item['topic'].capitalize()}")
                add("")
                for line in item["lines"]:
                    add(f"- {_said(line)}")
                add("")

    drive = result.get("drive")
    if drive:
        add(f"## What {name} can drive")
        add("")
        if "refused" in drive:
            lines.extend(_refused(drive))
        else:
            d = drive["design"]
            add(
                f"On this motor, at {_n(c.get('v_dc'))} V, {_n(_f(c.get('f_sw')) / 1000)} kHz and {_cooling(c)}, held without end: "
                f"{_n(d['torque'], 'N·m')} at {_n(d['rpm'])} rpm ({_n(d['power'], 'W')} at the shaft, {_n(d['current'], 'A')} peak). "
                f"What stops it: {d['why']}."
                + (f" The design torque is {_n(100 * d['share'], '%', 2)} of that." if d.get("share") else "")
            )
            add("")
            add("| Speed, rpm | Torque it can hold, N·m | What stops it |")
            add("|---|---|---|")
            for rpm, row in zip(drive["rpm"], drive["edge"], strict=True):
                add(f"| {_n(rpm)} | {_n(row['torque'])} | {row['why']} |")
            add("")

    rests: list[str] = []
    for x in result["verdict"].get("candidates", []) if "refused" not in result["verdict"] else []:
        r = x["result"]
        if r is None:
            continue
        for group, title in (("notes", "noted"), ("assumptions", "assumed"), ("limits", "left out of the model")):
            for line in r.get(group, []):
                rests.append(f"- {x['name']}, {title}: {_said(line)}")
    if rests:
        add("## What this rests on")
        add("")
        lines.extend(dict.fromkeys(rests))
        add("")
    return "\n".join(lines).rstrip() + "\n"


# ---------- files ----------


def load_setup(path: str | Path, workspace: page.Workspace) -> dict:
    """A design read from a file. Devices named by a path are brought into the workspace:
    a device file as it is, a file of typed figures built first."""
    path = Path(path)
    try:
        setup = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        raise page.Refused(f"cannot read {path}: {str(exc).splitlines()[0]}", "", "") from None
    if not isinstance(setup, dict):
        raise page.Refused(f"{path} is not a design", "start from `motionsim design init`", "")
    if isinstance(setup.get("motors"), list):  # each motor may be a file of its own too
        try:
            setup["motors"] = [
                yaml.safe_load((path.parent / m).read_text(encoding="utf-8")) if isinstance(m, str) else m
                for m in setup["motors"]
            ]
        except (OSError, ValueError, yaml.YAMLError) as exc:
            raise page.Refused(f"cannot read a motor file: {str(exc).splitlines()[0]}", "", "motors") from None
    for key in ("motor", "load", "profile"):  # each may be a file of its own
        if isinstance(setup.get(key), str):
            try:
                setup[key] = yaml.safe_load((path.parent / setup[key]).read_text(encoding="utf-8"))
            except (OSError, ValueError, yaml.YAMLError) as exc:
                raise page.Refused(f"cannot read the {key} file: {str(exc).splitlines()[0]}", "", key) from None
    if not isinstance(setup.get("devices"), list):
        raise page.Refused("no device is named", "name at least one under `devices`, as a list", "devices")
    setup["devices"] = [bring_device(str(entry), path.parent, workspace) for entry in setup.get("devices") or []]
    return setup


def bring_device(entry: str, base: Path, workspace: page.Workspace) -> str:
    """A device named in a design, brought into the workspace: one of the made-up parts by its
    name, a device file as it is, or a file of typed figures built first. Returns its name there."""
    from motionsim.device import load_device
    from motionsim.fit.typed import Mistyped, from_figures

    if entry in workspace.paths():
        return entry
    file = Path(entry) if Path(entry).is_absolute() else base / entry
    try:
        there = file.is_file()
    except OSError:  # a name no file could have
        there = False
    if not there:
        raise page.Refused(
            f"no device called {entry}, and no file of that name",
            "give a path to a device file, or example-mosfet or example",
            "devices",
        )
    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
        device = from_figures(data) if isinstance(data, dict) and "switch" not in data else load_device(file)
    except Mistyped as exc:
        raise page.Refused(
            f"{file.name}: {exc}", "check the figure against the datasheet", exc.field or "devices"
        ) from None
    except (OSError, yaml.YAMLError, ValueError, TypeError) as exc:  # a file that is not a device model
        raise page.Refused(f"{file.name} is not a device: {page.reason_of(exc)[:160]}", "", "devices") from None
    key = (
        file.name.removesuffix(".yaml").removesuffix(".yml").removesuffix(".device").lower().replace(" ", "-")
        or "device"
    )
    if key in page.EXAMPLES:
        key = f"{key}-file"
    # Two files of one name from two folders are two devices: the second is not written over the first.
    text = yaml.safe_dump(device.model_dump(mode="json", exclude_none=True), sort_keys=False)
    base, n = key, 1
    while (workspace.folder / f"{key}.device.yaml").exists() and (
        workspace.folder / f"{key}.device.yaml"
    ).read_text() != text:
        n += 1
        key = f"{base}-{n}"
    (workspace.folder / f"{key}.device.yaml").write_text(text, encoding="utf-8")
    return key
