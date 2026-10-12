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
from pathlib import Path

import yaml

from motionsim import __version__, page
from motionsim.engine import ThermalRunaway

STEPS = ("fit", "verdict", "motion", "build", "drive")
SETUP_HEAD = """\
# A design for `motionsim design run`. Edit the figures to yours.
#   devices     made-up names (example-mosfet, example), or paths to device files
#               (.device.yaml) or to figures typed from a datasheet (motionsim template device)
#   motor       its kind and catalogue figures (motionsim template pmsm, bldc, dc, ...)
#   conditions  SI units: V, rpm, N·m, Hz, s, ohm, °C, K/W. cooling is one of
#               held (t_sink), heatsink (rth_sink, t_ambient), none (rth_ja, t_ambient),
#               board (rth_ja, board_area, copper, t_ambient). Gate drive left out is chosen.
#   load, profile   what the motor moves and how: leave out to judge the design point alone
"""


def _refusal(exc: Exception) -> dict:
    if isinstance(exc, page.Refused):
        return {"refused": exc.reason, "fix": exc.fix, "field": exc.field}
    if isinstance(exc, ThermalRunaway):
        return dict(page.RUNAWAY)
    raise exc


def _step(work) -> dict:
    try:
        return work()
    except (page.Refused, ThermalRunaway) as exc:
        return _refusal(exc)


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


def run(setup: dict, workspace: page.Workspace, steps: tuple[str, ...] = STEPS, traces: bool = False) -> dict:
    """Every step of a design, in the page's order. `setup` is what the page sends: a motor,
    conditions, the devices by their names in the workspace, and optionally a load and its
    motion. The first device that passes is the one followed through the motion, the build
    sheet and the capability; the others stand beside it in the verdict."""
    if not isinstance(setup, dict):
        raise page.Refused("the design is not a list of names and values", "see `motionsim design init`", "")
    devices = [str(d) for d in (setup.get("devices") or [])]
    if not devices:
        raise page.Refused("no device is named", "name at least one under `devices`", "devices")
    for key in ("motor", "conditions"):
        if not isinstance(setup.get(key), dict):
            raise page.Refused(f"the design has no {key}", "see `motionsim design init`", key)
    base = {"motor": setup["motor"], "conditions": setup["conditions"], "supply": setup.get("supply", "one-way")}
    c = setup["conditions"]
    out: dict = {
        "motionsim": __version__, "date": datetime.date.today().isoformat(),
        "setup": {**base, "devices": devices, **({"load": setup["load"], "profile": setup["profile"]} if setup.get("load") and setup.get("profile") else {})},
        "devices": {key: workspace.summary(key, workspace.device(key)) for key in devices},
    }
    if "fit" in steps:
        out["fit"] = _step(lambda: page.motor_fit({"motor": setup["motor"], "device": devices[0], "parallel": c.get("parallel"),
                                                    "rpm": c.get("rpm"), "v_dc": c.get("v_dc")}, workspace))
    out["stage"] = _step(lambda: page.stage(base))
    verdict = _step(lambda: page.proposal({**base, "devices": devices}, workspace))
    out["verdict"] = verdict
    if "refused" in verdict or "refused" in out["stage"]:
        out["outcome"] = "refused"
        return out
    ran = [x for x in verdict["candidates"] if x["result"] is not None]
    passing = [x for x in ran if x["level"] != "fail"]
    chosen = (passing or ran or verdict["candidates"])[0]["id"]
    out["followed"] = chosen
    out["outcome"] = "passes" if passing and passing[0]["level"] == "ok" else "passes with cautions" if passing else "does not pass"
    one = {**base, "device": chosen}
    if "motion" in steps and setup.get("load") and setup.get("profile"):
        motion = _step(lambda: page.cycle({**one, "load": setup["load"], "profile": setup["profile"],
                                           "heatsink": setup.get("heatsink"), "c_link": setup.get("c_link"),
                                           "repeats": setup.get("repeats", 1)}, workspace))
        if not traces:
            motion = {k: v for k, v in motion.items() if k in ("summary", "checks", "start", "life", "sink_name", "refused", "fix", "field")}
        out["motion"] = motion
    if "build" in steps:
        out["build"] = _step(lambda: page.recommendations({**one, "t_ambient": setup.get("t_ambient")}, workspace))
    if "drive" in steps:
        out["drive"] = _step(lambda: page.capability(one, workspace))
    return out


# ---------- the report ----------

def _n(value, unit: str = "", digits: int = 3) -> str:
    if value is None:
        return "n/a"
    x = float(f"{float(value):.{digits}g}")
    # Three significant figures, written out: 2000, not 2e+03.
    text = f"{x:g}" if x != 0 and (abs(x) >= 1e6 or abs(x) < 1e-3) else (f"{x:.0f}" if x.is_integer() else f"{x:.10g}")
    return f"{text} {unit}".strip()


def _cooling(c: dict) -> str:
    kind = c.get("cooling") or "held"
    air = f"{_n(c.get('t_ambient', 40))} °C air"
    if kind == "heatsink":
        return f"a {_n(c.get('rth_sink'))} K/W heatsink in {air}"
    if kind == "none":
        return f"no heatsink, each part in {air}" + (f", {_n(c['rth_ja'])} K/W junction to air" if c.get("rth_ja") else "")
    if kind == "board":
        return f"no heatsink, parts on a {_n(c.get('board_area'))} cm² board in {air}"
    return f"a heatsink held at {_n(c.get('t_sink', 60))} °C"


def _said(text: str) -> str:
    text = str(text).strip()
    return text[:1].upper() + text[1:] + ("" if text.endswith((".", ":", "?")) else ".")


def _refused(step: dict) -> list[str]:
    return [f"**This could not be run.** {_said(step['refused'])}" + (f" {_said(step['fix'])}" if step.get("fix") else ""), ""]


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
    add(f"{result['date']} · MotionSim {result['motionsim']}, an exploratory tool. Results are estimates from datasheet "
        "values, stated assumptions and simplified models. Verify by measurement before building anything.")
    add("")
    add(f"**Outcome: {result.get('outcome', 'not run')}.**")
    add("")

    add("## What was tested")
    add("")
    for key in s["devices"]:
        d = result["devices"][key]
        add(f"- Device: {d['name']}, {d['technology']}, {_n(d['v_max'])} V, {_n(d['i_nominal'])} A, {_n(d['tj_max'])} °C junction. "
            f"Switching loss: {d['switching']}.")
    figures = ", ".join(f"{k} {v}" for k, v in m.items() if k not in ("type", "name") and v not in ("", None))
    add(f"- Motor: {m.get('type')} ({figures})")
    add(f"- Supply: {_n(c.get('v_dc'))} V, {'a battery' if s.get('supply') == 'battery' else 'a power supply'}")
    add(f"- Design point: {_n(c.get('rpm'))} rpm, {_n(c.get('torque'))} N·m")
    add(f"- Switching: {_n((c.get('f_sw') or 0) / 1000)} kHz, {c.get('pwm') or 'the usual modulation for this motor'}, "
        f"{int(c.get('parallel') or 1)} device{'s' if int(c.get('parallel') or 1) > 1 else ''} a switch")
    add(f"- Cooling: {_cooling(c)}")
    if s.get("load"):
        segments = s["profile"]["segments"]
        add(f"- Load and motion: gear {_n(s['load'].get('gear_ratio', 1))}:1, {len(segments)} stretches, "
            f"{_n(sum(float(x['duration']) for x in segments))} s")
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
        for sentence in verdict.get("explain", []):
            add(_said(sentence))
        add("")
        add("| Device | Verdict | Loss | Conduction | Switching | Hottest junction | Margin | Held still | Shaft over DC |")
        add("|---|---|---|---|---|---|---|---|---|")
        word = {"ok": "passes", "caution": "passes, with cautions", "fail": "does not pass"}
        for x in verdict["candidates"]:
            r = x["result"]
            if r is None:
                add(f"| {x['name']} | cannot run: {x.get('problem') or ''} | | | | | | | |")
                continue
            add(f"| {x['name']} | {word[x['level']]} | {_n(r['loss'], 'W')} | {_n(r['conduction'], 'W')} | {_n(r['switching'], 'W')} | "
                f"{_n(r['tj_peak'], '°C')} | {_n(x.get('margin'), 'K')} | {_n(x.get('stall_tj'), '°C')} | "
                f"{_n(100 * x['efficiency'], '%') if x.get('efficiency') is not None else 'n/a'} |")
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
                add(f"- **{'Fails' if k['level'] == 'fail' else 'Caution'}, {k['topic']}.** {_said(k['message'])}")
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
            add(f"- Lasts {_n(q['duration'], 's')}; mean loss {_n(q['mean_loss'], 'W')}; energy lost {_n(q['loss_energy'], 'J')}; "
                f"energy to the shaft {_n(q['shaft_energy'], 'J')}")
            add(f"- Hottest junction reached {_n(q['peak'], '°C')} against a {_n(q['tj_max'], '°C')} rating; "
                f"{_n(q['forever'], '°C')} if the hardest instant lasted forever")
            if q.get("returned"):
                add(f"- Braking returns {_n(q['returned'], 'J')}" + (f"; the link needs at least {_n(1e6 * q['c_needed'], 'µF')} to take it" if q.get("c_needed") else ""))
            for line in (motion.get("start") or {}).get("lines", []):
                add(f"- Starting: {_said(line)}")
            for k in motion["checks"]:
                tag = "Passes" if k["level"] == "ok" else "**Fails**" if k["level"] == "fail" else "**Caution**"
                add(f"- {tag}, {k['topic']}. {_said(k['message'])}")
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
            add(f"On this motor, at {_n(c.get('v_dc'))} V, {_n((c.get('f_sw') or 0) / 1000)} kHz and {_cooling(c)}, held without end: "
                f"{_n(d['torque'], 'N·m')} at {_n(d['rpm'])} rpm ({_n(d['power'], 'W')} at the shaft, {_n(d['current'], 'A')} peak). "
                f"What stops it: {d['why']}." + (f" The design torque is {_n(100 * d['share'], '%', 2)} of that." if d.get("share") else ""))
            add("")
            add("| Speed, rpm | Torque it can hold, N·m | What stops it |")
            add("|---|---|---|")
            for rpm, row in zip(drive["rpm"], drive["edge"]):
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
    except (OSError, yaml.YAMLError) as exc:
        raise page.Refused(f"cannot read {path}: {str(exc).splitlines()[0]}", "", "") from None
    if not isinstance(setup, dict):
        raise page.Refused(f"{path} is not a design", "start from `motionsim design init`", "")
    for key in ("motor", "load", "profile"):  # each may be a file of its own
        if isinstance(setup.get(key), str):
            try:
                setup[key] = yaml.safe_load((path.parent / setup[key]).read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as exc:
                raise page.Refused(f"cannot read the {key} file: {str(exc).splitlines()[0]}", "", key) from None
    setup["devices"] = [bring_device(str(entry), path.parent, workspace) for entry in setup.get("devices") or []]
    return setup


def bring_device(entry: str, base: Path, workspace: page.Workspace) -> str:
    """A device named in a design, brought into the workspace: one of the made-up parts by its
    name, a device file as it is, or a file of typed figures built first. Returns its name there."""
    from motionsim.device import load_device, save_device
    from motionsim.fit.typed import Mistyped, from_figures

    if entry in workspace.paths():
        return entry
    file = Path(entry) if Path(entry).is_absolute() else base / entry
    if not file.is_file():
        raise page.Refused(f"no device called {entry}, and no file of that name",
                           "give a path to a device file, or example-mosfet or example", "devices")
    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
        device = from_figures(data) if isinstance(data, dict) and "switch" not in data else load_device(file)
    except Mistyped as exc:
        raise page.Refused(f"{file.name}: {exc}", "check the figure against the datasheet", exc.field or "devices") from None
    except Exception as exc:  # not a device model
        raise page.Refused(f"{file.name} is not a device: {str(exc).splitlines()[0][:160]}", "", "devices") from None
    key = file.name.removesuffix(".yaml").removesuffix(".yml").removesuffix(".device").lower().replace(" ", "-") or "device"
    if key in page.EXAMPLES:
        key = f"{key}-file"
    save_device(device, workspace.folder / f"{key}.device.yaml")
    return key
