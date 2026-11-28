"""The design as a report in Markdown, section by section."""

from __future__ import annotations

import re

from motionsim.design.table import WORD
from motionsim.service.catalogue import FIELDS, MOTOR_NAMES
from motionsim.text import capital, written

TAG = {"ok": "Passes", "caution": "**Caution**", "undecided": "**Undecided**", "fail": "**Fails**"}


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
    # A figure the tool sized from its own loss is said to be one wherever it is named.
    earlier = " for an earlier design point" if c.get("sized_earlier") in (True, "true") else ""
    sized = lambda figure: f" (sized by the tool{earlier})" if c.get("sized") == figure else ""  # noqa: E731
    if kind == "heatsink":
        return f"a {_n(c.get('rth_sink'))} K/W heatsink{sized('rth_sink')} in {air}{under}"
    if kind == "none":
        return f"no heatsink, each part in {air}" + (
            f", {_n(c['rth_ja'])} K/W junction to air" if c.get("rth_ja") else ""
        )
    if kind == "board":
        return f"no heatsink, parts on a {_n(c.get('board_area'))} cm² board{sized('board_area')} in {air}"
    return f"a heatsink held at {_n(c.get('t_sink', 60))} °C{under}"


def _said(text: str) -> str:
    text = str(text).strip()
    return capital(text) + ("" if text.endswith((".", ":", "?")) else ".")


def _refused(step: dict) -> list[str]:
    lead = "**The part fails here.**" if step.get("level") == "fail" else "**This could not be run.**"
    return [
        f"{lead} {_said(step['refused'])}" + (f" {_said(step['fix'])}" if step.get("fix") else ""),
        "",
    ]


_MARKS = re.compile(r"([\\`*_{}\[\]<>|#~])")


def _md(text) -> str:
    """A name from a file, as it can stand in a Markdown report: on one line, and with
    nothing in it read as a heading, a table's edge, a link or a tag. A part's name is its
    maker's to choose and is never trusted to be plain."""
    flat = " ".join(str(text).split())
    return _MARKS.sub(r"\\\1", flat).replace("&", "&amp;")


def _head(result: dict) -> list[str]:
    s = result["setup"]
    names = [_md(result["devices"][k]["name"]) for k in s["devices"]]
    lines = [
        f"# {' and '.join(names[:2])}{' and others' if len(names) > 2 else ''}: power-stage estimate",
        "",
        f"{result['date']} · MotionSim {result['motionsim']}, an exploratory tool. Results are estimates from datasheet "
        "values, stated assumptions and simplified models. Verify by measurement before building anything.",
        "",
        f"**Outcome: {result.get('outcome', 'not run')}.**",
        "",
    ]
    if result.get("refusals"):
        # Which steps were not run, so that the outcome is never read as the verdict alone.
        lines += [f"Not run: {', '.join(result['refusals'])}. {_said(result['refused'])}", ""]
    marks = result.get("marks")
    if marks:
        lines += [
            f"Design {marks['design']}; device files "
            + ", ".join(f"{_md(result['devices'][k]['name'])} {v}" for k, v in marks["devices"].items())
            + ". The same marks mean the same inputs.",
            "",
        ]
    return lines


def _motor_line(m: dict) -> str:
    # The motor's figures by the names the page gives them, not by the names in the file.
    named = {key: (label, unit) for key, label, unit, *_ in FIELDS.get(str(m.get("type")), [])}
    figures = ", ".join(
        f"{named[k][0].lower()} {_md(v)} {named[k][1]}".strip() if k in named else f"{_md(k)} {_md(v)}"
        for k, v in m.items()
        if k not in ("type", "name") and v not in ("", None)
    )
    kind = MOTOR_NAMES.get(str(m.get("type")), (None, _md(m.get("type")), None))[1]
    return f"- Motor: {kind} ({figures})"


def _tested(result: dict) -> list[str]:
    s = result["setup"]
    c = s["conditions"]
    lines = ["## What was tested", ""]
    for key in s["devices"]:
        d = result["devices"][key]
        lines.append(
            f"- Device: {_md(d['name'])}, {_md(d['technology'])}, {_n(d['v_max'])} V, {_n(d['i_nominal'])} A, {_n(d['tj_max'])} °C junction. "
            f"Switching loss: {d['switching']}."
        )
    several = _f(c.get("parallel"), 1) > 1
    lines += [
        _motor_line(s["motor"]),
        f"- Supply: {_n(c.get('v_dc'))} V, {'a battery' if s.get('supply') == 'battery' else 'a power supply'}",
        f"- Design point: {_n(c.get('rpm'))} rpm, {_n(c.get('torque'))} N·m",
        f"- Switching: {_n(_f(c.get('f_sw')) / 1000)} kHz, {_md(c.get('pwm') or 'the usual modulation for this motor')}, "
        f"{_n(c.get('parallel') or 1)} device{'s' if several else ''} a switch",
        f"- Edge speed limit: {EDGE_WORDS.get(c.get('edge_limit') or 'cable', _md(str(c.get('edge_limit'))))}",
        f"- Cooling: {_cooling(c)}",
    ]
    if s.get("load"):
        segments = [x for x in (s.get("profile") or {}).get("segments") or [] if isinstance(x, dict)]
        lines.append(
            f"- Load and motion: gear {_n(s['load'].get('gear_ratio', 1))}:1, {len(segments)} stretches, "
            f"{_n(sum(_f(x.get('duration')) for x in segments))} s"
        )
    return [*lines, ""]


# The edge limit as the page says it.
EDGE_WORDS = {
    "cable": "motor on a cable, 5 V/ns",
    "close": "motor close to the drive, 20 V/ns",
    "none": "none, as fast as the part allows",
}


def _fit_section(result: dict) -> list[str]:
    fit = result.get("fit")
    if not fit:
        return []
    lines = ["## Does the motor fit the part", ""]
    if "refused" in fit:
        return lines + _refused(fit)
    lines += [f"- {'**Caution.** ' if x['level'] != 'ok' else ''}{_said(x['text'])}" for x in fit["lines"]]
    return [*lines, ""]


ALONE = {
    "ok": "{name} passes every check at this design point.",
    "caution": "{name} can do this, with cautions to read below.",
    "undecided": "{name} is not decided by this data: what the datasheet leaves out "
    "could change the answer. The check below says what would settle it.",
    "fail": "{name} does not pass at this point: see the checks below.",
}


def _verdict_table(candidates: list[dict]) -> list[str]:
    lines = [
        "| Device | Verdict | Loss | Conduction | Switching | Hottest junction | Margin | Standstill, same torque | DC-to-shaft efficiency |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for x in candidates:
        r = x["result"]
        if r is None:
            lines.append(f"| {_md(x['name'])} | cannot run: {x.get('problem') or ''} | | | | | | | |")
            continue
        lines.append(
            f"| {_md(x['name'])} | {WORD[x['level']]} | {_n(r['loss'], 'W')} | {_n(r['conduction'], 'W')} | {_n(r['switching'], 'W')} | "
            f"{_n(r['tj_peak'], '°C')} | {_n(x.get('margin'), 'K')} | {_n(x.get('stall_tj'), '°C')} | "
            f"{_n(100 * x['efficiency'], '%') if x.get('efficiency') is not None else 'n/a'} |"
        )
    return [*lines, ""]


def _listed(title: str, items) -> list[str]:
    return ["", title, "", *(f"- {_said(x)}" for x in items)] if items else []


def _candidate_section(x: dict) -> list[str]:
    """One device of the verdict: its checks, those raised first, its gate drive, what it
    needs around it and what its switching loss rests on."""
    lines = [f"### {_md(x['name'])}", ""]
    if x.get("problem"):
        lines += [_said(x["problem"]) + (f" {_said(x['fix'])}" if x.get("fix") else ""), ""]
    for k in x["checks"]:
        if k["level"] != "ok":
            lines.append(f"- {TAG[k['level']].rstrip('*')}, {k['topic']}.** {_said(k['message'])}")
    lines += [f"- Passes, {k['topic']}. {_said(k['message'])}" for k in x["checks"] if k["level"] == "ok"]
    lines += _listed("Gate drive:", (x.get("gate") or {}).get("lines"))
    lines += _listed("What it needs around it:", x.get("needs"))
    if x.get("switching"):
        lines += ["", f"Switching data: {_said(x['switching']['text'])}"]
    return [*lines, ""]


def _verdict_section(result: dict) -> list[str]:
    lines = ["## Verdict at the design point", ""]
    verdict, stage = result["verdict"], result.get("stage", {})
    if "refused" in stage:
        return lines + _refused(stage)
    if "refused" in verdict:
        return lines + _refused(verdict)
    candidates = verdict["candidates"]
    alone = candidates[0] if len(candidates) == 1 else None
    if alone is not None and alone["result"] is not None:
        lines.append(ALONE[alone["level"]].format(name=_md(alone["name"])))
    else:
        lines += [_said(sentence) for sentence in verdict.get("explain", [])]
    lines.append("")
    lines += _verdict_table(candidates)
    for x in candidates:
        lines += _candidate_section(x)
    return lines


def _motion_section(result: dict, name: str) -> list[str]:
    motion = result.get("motion")
    if not motion:
        return []
    lines = [f"## Through the motion, {name}", ""]
    if "refused" in motion:
        return lines + _refused(motion)
    q = motion["summary"]
    lines += [
        f"- Lasts {_n(q['duration'], 's')}; mean loss {_n(q['mean_loss'], 'W')}; energy lost {_n(q['loss_energy'], 'J')}; "
        f"energy to the shaft {_n(q['shaft_energy'], 'J')}",
        f"- Hottest junction reached {_n(q['peak'], '°C')} against a {_n(q['tj_max'], '°C')} rating; "
        f"{_n(q['forever'], '°C')} if the hardest instant lasted forever",
    ]
    if q.get("returned"):
        needs = f"; the link needs at least {_n(1e6 * q['c_needed'], 'µF')} to take it" if q.get("c_needed") else ""
        lines.append(f"- Braking returns {_n(q['returned'], 'J')}" + needs)
    lines += [f"- Starting: {_said(line)}" for line in (motion.get("start") or {}).get("lines", [])]
    lines += [f"- {TAG[k['level']]}, {k['topic']}. {_said(k['message'])}" for k in motion["checks"]]
    return [*lines, ""]


def _motions_section(result: dict) -> list[str]:
    motions = result.get("motions")
    if not motions:
        return []
    lines = [
        "## Through the motion, each device",
        "",
        "| Device | Mean loss | Hottest junction | Energy lost | Not ok |",
        "|---|---|---|---|---|",
    ]
    for key, found in motions.items():
        label = _md(result["devices"][key]["name"])
        if "refused" in found:
            lines.append(f"| {label} | cannot run: {found['refused']} | | | |")
            continue
        q = found["summary"]
        raised = "; ".join(k["topic"] for k in found["checks"] if k["level"] != "ok") or "nothing"
        lines.append(
            f"| {label} | {_n(q['mean_loss'], 'W')} | {_n(q['peak'], '°C')} | {_n(q['loss_energy'], 'J')} | {raised} |"
        )
    return [*lines, ""]


def _motors_section(result: dict, name: str) -> list[str]:
    compared = result.get("motors")
    if not compared:
        return []
    lines = [
        f"## Motors compared, on {name}",
        "",
        "| Motor | Verdict | Peak current | Loss | Hottest junction | Margin | Capacitor ripple | DC-to-shaft efficiency |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for mo in compared:
        if "refused" in mo:
            lines.append(f"| {_md(mo['name'])} | cannot run: {mo['refused']} | | | | | | |")
            continue
        lines.append(
            f"| {_md(mo['name'])} | {WORD.get(mo['level'], 'cannot run')} | {_n(mo['i_peak'], 'A')} | {_n(mo['loss'], 'W')} | {_n(mo['tj_peak'], '°C')} | "
            f"{_n(mo['margin'], 'K')} | {_n(mo['capacitor_rms'], 'A rms')} | "
            f"{_n(100 * mo['efficiency'], '%') if mo.get('efficiency') is not None else 'n/a'} |"
        )
    return [*lines, ""]


def _front_end_section(result: dict) -> list[str]:
    front = result.get("front_end")
    if not front:
        return []
    lines = ["## Front end", ""]
    if "refused" in front:
        return lines + _refused(front)
    r, mains = front["result"], front["mains"]
    phases = "three phases" if mains["phases"] == 3 else "one phase"
    own = front["chosen"] != front["recommended"]
    lines += [
        f"- {r['name']} on {_n(mains['v'], 'V')}, {_n(mains['f'], 'Hz')}, {phases}"
        + (", chosen in the design" if own else f": {_said(front['why'])}"),
        f"- It holds the DC link at {_n(r['v_dc'], 'V')}"
        + (" (given in the design)" if front.get("v_dc_given") else "")
        + f" and loses {_n(r['loss'], 'W')} on top of the inverter's ({_n(100 * r['efficiency'], '%')} efficient).",
        f"- Mains current {_n(r['i_line'], 'A rms')}, power factor {_n(r['power_factor'], '')}".rstrip()
        + ("." if r.get("within_limit") is not False else ", over the harmonic limits of IEC 61000-3-2 class A."),
    ]
    lines += [
        f"- {WORD.get(c['level'], c['level']).capitalize()}: {_said(c['message'])}"
        for c in r["checks"]
        if c["level"] != "ok"
    ]
    return [*lines, ""]


def _build_section(result: dict, name: str) -> list[str]:
    build = result.get("build")
    if not build:
        return []
    lines = [f"## What to build, with {name}", ""]
    if "refused" in build:
        return lines + _refused(build)
    for item in build["items"]:
        lines += [f"### {item['topic'].capitalize()}", "", *(f"- {_said(line)}" for line in item["lines"]), ""]
    return lines


def _drive_section(result: dict, name: str) -> list[str]:
    drive = result.get("drive")
    if not drive:
        return []
    c = result["setup"]["conditions"]
    lines = [f"## What {name} can drive", ""]
    if "refused" in drive:
        return lines + _refused(drive)
    d = drive["design"]
    lines += [
        f"On this motor, at {_n(c.get('v_dc'))} V, {_n(_f(c.get('f_sw')) / 1000)} kHz and {_cooling(c)}, held without end: "
        f"{_n(d['torque'], 'N·m')} at {_n(d['rpm'])} rpm ({_n(d['power'], 'W')} at the shaft, {_n(d['current'], 'A')} peak). "
        f"What stops it: {d['why']}."
        + (f" The design torque is {_n(100 * d['share'], '%', 2)} of that." if d.get("share") else ""),
        "",
        "| Speed, rpm | Torque it can hold, N·m | What stops it |",
        "|---|---|---|",
    ]
    lines += [
        f"| {_n(rpm)} | {_n(row['torque'])} | {row['why']} |"
        for rpm, row in zip(drive["rpm"], drive["edge"], strict=True)
    ]
    return [*lines, ""]


def _rests_section(result: dict) -> list[str]:
    rests: list[str] = []
    for x in result["verdict"].get("candidates", []) if "refused" not in result["verdict"] else []:
        r = x["result"]
        if r is None:
            continue
        for group, title in (("notes", "noted"), ("assumptions", "assumed"), ("limits", "left out of the model")):
            rests += [f"- {_md(x['name'])}, {title}: {_said(line)}" for line in r.get(group, [])]
    return ["## What this rests on", "", *dict.fromkeys(rests), ""] if rests else []


def markdown(result: dict) -> str:
    """The design as a report in Markdown: what was tested, the verdict and why, the motion,
    what to build, what the part can drive, and what the result rests on. Written to be read
    by a person or handed to an agent as it is."""
    name = _md(result["devices"].get(result.get("followed", ""), {}).get("name", "the device"))
    lines = [
        *_head(result),
        *_tested(result),
        *_fit_section(result),
        *_verdict_section(result),
        *_motion_section(result, name),
        *_motions_section(result),
        *_motors_section(result, name),
        *_front_end_section(result),
        *_build_section(result, name),
        *_drive_section(result, name),
        *_rests_section(result),
    ]
    return "\n".join(lines).rstrip() + "\n"
