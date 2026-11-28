"""The verdict on a run: the figures its findings are judged from (`quality`), taken from the
run as it ended and from the linear analysis of its scheme and of the same scheme as tuned,
and the address that judges such figures again, against a run before (control/verdict.py
does the judging)."""

from __future__ import annotations

import math
import re
from typing import Any

import numpy as np

from motionsim.control import linear, report, scenario, verdict
from motionsim.control.blocks import BLOCKS
from motionsim.control.presets import BUILDERS, context, limited
from motionsim.control.scheme import Scheme, compile_scheme
from motionsim.errors import Refusal
from motionsim.service.control.reading import deep


def _loop(found: dict | None) -> dict | None:
    if not found:
        return None
    m = found["margins"]
    return {
        "phase_deg": m["phase_deg"],
        "gain_db": m["gain_db"],
        "crossover_hz": m["crossover_hz"],
        "bandwidth_hz": found["bandwidth_hz"],
        "stable": found["stable"],
    }


def loops_of(found: dict) -> dict:
    """The figures of the linear analysis a verdict reads: the q-axis current loop and the speed loop."""
    return {"current": _loop(found.get("current_q")), "speed": _loop(found.get("speed"))}


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-15)
    return a == b


def _plainly(kind: str | None) -> str:
    """A kind of block by its title, without what its brackets add: "speed regulator"."""
    block = BLOCKS.get(kind or "")
    return re.sub(r"\s*\(.*?\)", "", block.title).strip().lower() if block is not None else str(kind)


def _symbol(param: str) -> str:
    """A parameter as the page writes it: kp_q is Kp,q; any other, its name in words."""
    gain = re.fullmatch(r"k([a-z])(?:_([a-z]))?", param)
    if gain:
        return f"K{gain[1]}" + (f",{gain[2]}" if gain[2] else "")
    return param.replace("_", " ")


def _titled(kind: str | None) -> str | None:
    block = BLOCKS.get(kind or "")
    return None if kind is None else (block.title if block is not None else kind)


def edits(tuned: Scheme, scheme: Scheme) -> list[dict]:
    """Every figure of the scheme that is not as the scheme was tuned: a block's parameter, a
    block of another kind, a block added or taken away, the timing."""
    out: list[dict] = []
    was = {b.name: b for b in tuned.blocks}
    for b in scheme.blocks:
        old = was.get(b.name)
        if old is None:
            out.append(_swapped(b.name, None, b.kind))
            continue
        if old.kind != b.kind:
            out.append(_swapped(b.name, old.kind, b.kind))
            continue
        for name, value in b.params.items():
            if name in old.params and not _same(old.params[name], value):
                words = f"{_symbol(name)} of the {_plainly(b.kind)}"
                out.append({"block": b.name, "param": name, "tuned": old.params[name], "now": value, "words": words})
    names = {b.name for b in scheme.blocks}
    out += [_swapped(n, was[n].kind, None) for n in was if n not in names]
    for name, value in scheme.timing.items():
        if not _same(tuned.timing.get(name), value):
            was_at = tuned.timing.get(name)
            out.append(
                {
                    "block": "timing",
                    "param": name,
                    "tuned": was_at,
                    "now": value,
                    "words": f"the timing's {_symbol(name)}",
                }
            )
    return out


def _swapped(name: str, was: str | None, now: str | None) -> dict:
    """A block of another kind, added or taken away: said by the kinds' titles."""
    said = f"{_titled(was) or 'no block'}→{_titled(now) or 'no block'}"
    return {"block": name, "param": "kind", "tuned": was, "now": now, "words": "the block", "said": said}


def _tuned(ran) -> dict | None:
    """The scheme of the same name as tuned for this design, with what the run's scheme
    changed of it, and its linear analysis where it was changed."""
    build = BUILDERS.get(ran.scheme.id)
    if build is None:
        return None
    tuned = build(ran.design)
    if ran.kind == "start":
        tuned = limited(
            tuned, ran.design, ran.asked["current_limit"] * math.sqrt(2.0), scenario.LIMIT_SHAPES[ran.asked["shape"]]
        )
    changed = edits(tuned, ran.scheme)
    loops = None
    if changed:
        try:
            ctx = context(ran.design, tuned)
            shaft = ran.coupling if ctx.inertia > 0 else None  # the same shaft the run had
            loops = loops_of(linear.loops(compile_scheme(tuned, ctx), ctx, shaft))
        except Refusal:
            loops = None
    return {"id": tuned.id, "edits": changed, "loops": loops}


def _limited(ran) -> list[dict]:
    """The share of the analysed stretch each block that can saturate spent at its limit."""
    trace = ran.trace
    kept = trace.time >= trace.gather_from - 1e-12
    if ran.kind == "trip":
        # Tripped, the controller has nothing to drive: its limits are read while it drove.
        kept = ~kept
    if not kept.any():
        return []
    out = []
    kinds = {b.name: b.kind for b in ran.scheme.blocks}
    for wire in report.wires(ran.scheme):
        name = wire["name"]
        if not name.endswith(".limited"):
            continue
        held = trace.wire(name)[kept] > 0.5
        share = float(np.mean(held))
        if share > 0.0:
            block = name.rsplit(".", 1)[0]
            item = {"block": block, "kind": kinds.get(block, ""), "share": share}
            if kinds.get(block) == "variable_frequency":
                # Which end the frequency is held at: its lowest, where the ripple would allow a
                # slower one, or its highest, where the ripple asks a faster one than it may take.
                params = next(b.params for b in ran.scheme.blocks if b.name == block)
                asked = float(np.mean(trace.wire(f"{block}.f_sw")[kept][held]))
                low, high = float(params.get("f_min", 0.0)), float(params.get("f_max", math.inf))
                item["at"] = "f_min" if abs(asked - low) <= abs(asked - high) else "f_max"
            out.append(item)
    return out


def _blocks(scheme: Scheme) -> list[dict]:
    out = []
    for b in scheme.blocks:
        cls = BLOCKS.get(b.kind)
        out.append(
            {
                "name": b.name,
                "kind": b.kind,
                "title": cls.title if cls else b.kind,
                "loop": cls.loop if cls else "",
                "params": {k: v for k, v in b.params.items() if isinstance(v, (int, float, str, bool))},
            }
        )
    return out


def _fastest(ran) -> float:
    """Hz, the highest output frequency the run took the motor to: where its carrier ratio is
    lowest. Nought for a shaft held at standstill."""
    speed = ran.trace.wire("plant.omega_m")
    top = float(np.max(np.abs(speed))) if speed.size else 0.0
    return top * ran.design.pole_pairs / (2.0 * math.pi)


def quality(ran, answer: dict) -> dict:
    """What a verdict is judged from, out of a run that is over and the answer made of it."""
    design, losses, channels = ran.design, answer["losses"], answer["channels"]
    f_out = _fastest(ran)
    rippled = ran.rippled if ran.kind == "hold" else None
    modulator = next((b for b in ran.scheme.blocks if b.kind == "modulator"), None)
    windup = {b.name: bool(b.params.get("anti_windup", True)) for b in ran.scheme.blocks if b.kind == "speed_pi"}
    return {
        "scheme": {
            "id": ran.scheme.id,
            "label": ran.scheme.label,
            "update": ran.scheme.timing.get("update"),
            "actuation": ran.scheme.actuation.get("kind"),
            "pwm": modulator.params.get("pwm") if modulator else None,
        },
        "test": ran.kind,
        "fidelity": ran.inverter.fidelity,
        "f_control": 1.0 / ran.ctx.ts0,
        "f_sw": design.f_sw,
        # At the highest speed this test reached, not the design point's: a stall at
        # standstill has no ratio to speak of.
        "f_out": f_out,
        "carrier_ratio": design.f_sw / f_out if f_out > 1e-9 else None,
        "loops": loops_of(ran.linear) if ran.linear else {"current": None, "speed": None},
        "tuned": _tuned(ran),
        "loss": {"total": losses["loss"], "conduction": losses["conduction"], "switching": losses["switching"]},
        "f_switch_mean": channels["f_switch_mean"],
        "tj": {
            "peak": channels["tj_peak"],
            # The top of the thermal assumptions' range, as the run's own check counts its margin from.
            "high": max(ran.found.result.tj_peak_range[1], channels["tj_peak"])
            if ran.found.result.tj_peak_range
            else None,
            "max": losses.get("tj_max"),
            "swing": channels["tj_swing"],
        },
        "ripple": None
        if rippled is None
        else {
            "thd": rippled["thd"],
            "pp": rippled["pp"],
            "fundamental": rippled["i_fundamental"],
            "torque_pp": rippled["torque_pp"],
            "torque_mean": rippled["torque_mean"],
        },
        "step": answer["step"],
        "limited": _limited(ran),
        "anti_windup": windup,
        "sensing": answer["sensing"],
        "checks": [c for c in answer["checks"] if c.get("level") != "ok"],
        "stability": {k: ran.stability.get(k) for k in ("linear_stable", "loop", "said")},
        "blocks": _blocks(ran.scheme),
        "pulsed": answer.get("pulsed"),
        "floor": answer.get("floor"),
        "window": answer.get("window"),
        "shunt": None
        if channels.get("unread_share") is None
        else {"unread": channels["unread_share"], "misread": channels["read_error_rms"]},
        "injection": _injection(ran, answer),
        "trip": answer.get("trip"),
    }


def _injection(ran, answer: dict) -> dict | None:
    """What an injection told: the magnet's side, and the compensation the motor's own
    saturation map gives for the iron's coupling of the axes."""
    from motionsim.control.sensorless import coupling_rate

    sensing = answer.get("sensing") or {}
    if "polarity" not in sensing:
        return None
    return {"polarity": sensing["polarity"], "rate": coupling_rate(ran.design)}


# What a quality sent back may hold: no figure past this size, and no text longer than this.
LARGEST = 1e15
LONGEST_TEXT = 400
TOPICS = frozenset(
    (
        "current",
        "data",
        "dead time",
        "edges",
        "ripple",
        "solver",
        "temperature",
        "trip",
        "voltage",
        "stability",
        "tracking",
    )
)


def _finite(value: Any, path: str) -> None:
    """Refuses a figure that is not a finite number of a size a run gives, by its path."""
    stack: list[tuple[Any, str]] = [(value, path)]
    while stack:
        item, at = stack.pop()
        if isinstance(item, float) and not (math.isfinite(item) and abs(item) <= LARGEST):
            raise Refusal(
                f"the figure at {at[:80]} is not a finite number a run gives",
                "send the `quality` of a run's answer, as it came",
                path,
            )
        if isinstance(item, dict):
            stack += [(v, f"{at}.{k}") for k, v in item.items()]
        elif isinstance(item, list):
            stack += [(v, f"{at}[{k}]") for k, v in enumerate(item)]


def _plain(text: Any) -> str:
    """Words sent back, as plain text of a sentence's length: no control characters, no markup
    that could pass for an instruction set apart, nothing past LONGEST_TEXT."""
    said = "".join(c for c in str(text) if c.isprintable())
    return " ".join(said.replace("`", "'").replace("<", "(").replace(">", ")").split())[:LONGEST_TEXT]


def _trusted(q: dict) -> dict:
    """A quality sent back by a page, with every word it carries made the engine's own again or
    cut to plain text: block titles and loops from the registry by kind, checks of a known
    topic only, the stability's words plain. What the findings say, and so what a model is
    given to phrase, is then never text the sender wrote."""
    q = dict(q)
    blocks = []
    for b in q.get("blocks") or []:
        if not isinstance(b, dict):
            continue
        cls = BLOCKS.get(str(b.get("kind")))
        blocks.append(
            {
                **b,
                "name": _plain(b.get("name"))[:64],
                "title": cls.title if cls else "a block of no known kind",
                "loop": cls.loop if cls else "",
            }
        )
    q["blocks"] = blocks
    checks = []
    for c in q.get("checks") or []:
        if isinstance(c, dict) and c.get("topic") in TOPICS:
            checks.append({**c, "message": _plain(c.get("message")), "field": _plain(c.get("field"))[:80]})
    q["checks"] = checks
    if isinstance(q.get("stability"), dict):
        q["stability"] = {**q["stability"], "said": _plain(q["stability"].get("said"))}
    return q


def verdict_of(data: dict) -> dict:
    """The verdict on the figures a run gave (its `quality`), against a run before where one
    is sent (`before`, that run's `quality`). The figures are held to be finite, and the words
    are the engine's own or plain text (`_trusted`)."""
    deep(data)
    q, before = data.get("quality"), data.get("before")
    if not isinstance(q, dict):
        raise Refusal(
            "the request has no quality, or it is not a set of names and values",
            "send the `quality` of a run's answer, as it came",
            "quality",
        )
    if before is not None and not isinstance(before, dict):
        raise Refusal(
            "the run before is not a set of names and values",
            "send the `quality` of the run before, as it came, or leave it out",
            "before",
        )
    _finite(q, "quality")
    if before is not None:
        _finite(before, "before")
    try:
        q = _trusted(q)
        before = _trusted(before) if before is not None else None
        return verdict.judge(q, before)
    except (TypeError, ValueError, KeyError, AttributeError, IndexError, ZeroDivisionError, OverflowError):
        raise Refusal(
            "the quality is not as a run gives it", "send the `quality` of a run's answer, as it came", "quality"
        ) from None


def judged(data: dict, workspace) -> dict:
    """POST /api/control/verdict."""
    return verdict_of(data)
