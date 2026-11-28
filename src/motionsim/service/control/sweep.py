"""A sweep of the control lab: one thing varied, the same run made for each value, and the
figures set side by side. An exploration of the library (library.py) is a sweep that is
ready to run; a request can also name what it varies itself.

What is varied is named by a path:

    "scheme"                             the scheme itself, by the id of a preset
    "conditions.<name>"                  a condition (f_sw, v_dc, ...): every scheme is tuned again
    "scenario.<name>"                    a figure of the test
    "mismatch.r" | ".ld" | ".lq" | ".flux"   a factor on the simulated motor only
    "inverter.dead_time" | ".device_drop"    what the simulated stage carries
    "fidelity" | "seed"
    "scheme.blocks.<block>.<parameter>"  one parameter of one block of the scheme
    "scheme.timing.<name>"               update, delay, f_control
    "scheme.rate"                        updates a carrier period (0.25, 0.5, 1, 2, 4, 8), the gains
                                         tuned again by the presets' rules at each
    "scheme.gains.current"               a factor on the current regulator's gains

A variant that is refused does not fail the sweep: it carries the refusal and the others
go on.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Generator
from dataclasses import dataclass, replace
from typing import Any

from motionsim.control import report
from motionsim.control.presets import BUILDERS, Design
from motionsim.control.scheme import Scheme
from motionsim.errors import Refusal
from motionsim.service.control import linking
from motionsim.service.control.design import _designed, _scheme, _schemes_named
from motionsim.service.control.library import BY_ID, EXPLORATIONS, FRONT_END, described
from motionsim.service.control.reading import SWEEP_BUDGET, name_of, names_of, over, set_of, shape
from motionsim.service.control.running import Ran, Ready, _sensing, execute, motor_loss, prepared
from motionsim.service.validate import _number
from motionsim.service.workspace import Workspace
from motionsim.text import said as said_number
from motionsim.text import written

MOST_VARIANTS = 12
TOP = ("conditions", "scenario", "mismatch", "inverter", "plant", "front_end")
# A share of the design's link capacitance (given or sized), on the link's simulation only.
LINK_SHARE = "link.capacitance"
GAINS = {"current": ("current", ("kp_d", "ki_d", "kp_q", "ki_q", "gain")), "speed": ("speed", ("kp", "ki"))}


@dataclass(frozen=True)
class Read:
    """A figure a sweep reads: what it is called, the unit it is said in and the factor to
    that unit, and how a change of it is said.

    kind: `relative`, as a percentage of the baseline (a loss, a current, a time);
    `difference`, in the figure's own unit (a temperature in °C changes by kelvins, an angle
    by degrees: a percentage of a temperature means nothing, its zero being arbitrary);
    `points`, for a figure that is itself a percentage.
    floor: under it, in the unit said, a figure is about zero: a baseline that small is no
    base for a percentage, and the change is given as it is.
    least: a change under it is no change to speak of: a share of the baseline for
    `relative`, and in the unit of the change for the other two.
    """

    label: str
    unit: str
    factor: float = 1.0
    kind: str = "relative"
    floor: float = 1e-3
    least: float = 1e-3

    @property
    def change_unit(self) -> str:
        if self.kind == "points":
            return "points"
        return "K" if self.unit == "°C" else self.unit


KINDS = ("relative", "difference", "points")
MOST_PERCENT = 1000.0  # past it a change is said as so many times the baseline


def _heat(label: str, unit: str = "°C") -> Read:
    return Read(label, unit, kind="difference", least=0.05)


def _percent(label: str) -> Read:
    return Read(label, "%", 100.0, "points", least=0.05)


def _angle(label: str, unit: str) -> Read:
    return Read(label, unit, kind="difference", least=0.01)


READS: dict[str, Read] = {
    "losses.loss": Read("inverter loss", "W"),
    "losses.conduction": Read("conduction loss", "W"),
    "losses.switching": Read("switching loss", "W"),
    "losses.tj_peak": _heat("peak junction temperature, settled"),
    "losses.tj_swing": _heat("junction temperature swing", "K"),
    "losses.tj_peak_from_start": _heat("peak junction temperature from a cold start"),
    "losses.system": Read("loss of motor and inverter together", "W"),
    "losses.motor_copper": Read("copper loss", "W"),
    "losses.motor_iron": Read("iron loss", "W"),
    "channels.i_switch_rms": Read("switch current", "A rms"),
    "channels.i_switch_peak": Read("peak switch current", "A"),
    "channels.f_switch_mean": Read("mean switching frequency", "kHz", 1e-3),
    "channels.i_at_commutation": Read("mean current at commutation", "A"),
    "channels.thd": _percent("current distortion"),
    "channels.ripple_pp": Read("current ripple", "A peak to peak"),
    "channels.ripple_rms": Read("current ripple", "A rms"),
    "channels.torque_ripple_pp": Read("torque ripple", "N·m peak to peak", floor=1e-6),
    "channels.speed_ripple_pp": Read("speed ripple", "rad/s peak to peak", floor=1e-6),
    "channels.shaft_swing_pp": Read("shaft still swinging", "rad/s peak to peak", floor=1e-6),
    "channels.unread_share": _percent("periods a phase could not be read"),
    "channels.read_error_rms": Read("current as read, off the true one", "A rms", floor=1e-6),
    "step.rise_time": Read("rise time", "ms", 1e3),
    "step.overshoot": _percent("overshoot"),
    "step.settling_time": Read("settling time", "ms", 1e3),
    "step.steady_state_error": Read("steady error", "", floor=1e-6),
    "step.load.overshoot": _percent("the load's overshoot"),
    "step.load.settling_time": Read("the load's settling time", "ms", 1e3),
    "step.deviation": Read("largest deviation", "", floor=1e-6),
    "step.recovery_time": Read("recovery time", "ms", 1e3),
    "sensing.angle_error_mean": _angle("mean angle error", "°"),
    "sensing.angle_error_rms": _angle("angle error", "° rms"),
    "sensing.angle_error_peak": _angle("largest angle error", "°"),
    "link.v_min": Read("lowest DC-link voltage", "V"),
    "link.v_max": Read("highest DC-link voltage", "V"),
    "link.ripple": Read("DC-link ripple", "V peak to peak", floor=1e-3),
    "link.sag": Read("DC link below its set point", "V", floor=1e-3),
    "link.thd": _percent("mains current off a sine"),
    "torque_mean": Read("mean torque", "N·m", floor=1e-6),
    "loops.current_hz": Read("current loop's crossover", "Hz"),
    "loops.current_pm": Read("current loop's phase margin", "°"),
}
DEFAULT_READS = ("losses.loss", "losses.switching", "channels.ripple_rms", "losses.tj_peak")


def explorations(data: dict, workspace: Workspace) -> dict:
    """The exploration library for this design."""
    notes = shape("explorations", data)
    design, rest = _designed(data, workspace)
    rest["taken"] += notes
    return {
        "explorations": [
            described(e, design) for e in EXPLORATIONS + (FRONT_END if data.get("supply") == "mains" else ())
        ],
        "groups": ["losses", "dynamics", "sensing", "robustness", "thermal"],
        # `scale` takes a run's own figure (SI: Hz, s, a share) to `unit`: 1e-3 for a
        # switching frequency read in kHz.
        "reads": {
            key: {"label": r.label, "unit": r.unit, "kind": r.kind, "scale": r.factor} for key, r in READS.items()
        },
        "taken": rest["taken"],
    }


def _refused(reason: str, fix: str, field: str = "vary") -> Refusal:
    return Refusal(reason, fix, field)


def _planned(data: dict, design: Design) -> dict:
    """What the sweep is to do: the exploration named, with whatever the request sets itself
    laid over it; or the request's own vary."""
    named = data.get("exploration")
    plan: dict[str, Any] = {"fixed": {}, "reads": list(DEFAULT_READS), "exploration": None}
    if named not in (None, ""):
        named = name_of(named, "exploration", what="the exploration")
        if named not in BY_ID:
            raise _refused(f"there is no exploration called {named}", f"one of {', '.join(BY_ID)}", "exploration")
        found = described(BY_ID[named], design)
        plan |= {k: found[k] for k in ("scheme", "scenario", "fidelity", "vary", "fixed", "reads")}
        plan["exploration"] = named
    for key in ("scheme", "scenario", "fidelity", "vary", "reads"):
        if data.get(key) not in (None, ""):
            plan[key] = data[key]
    if data.get("fixed") not in (None, ""):
        plan["fixed"] = {**plan["fixed"], **set_of(data["fixed"], "fixed", "what the sweep holds fixed")}
    plan["reads"] = names_of(plan["reads"], "reads", "what the sweep reads")
    vary = plan.get("vary")
    if not isinstance(vary, dict) or not isinstance(vary.get("path"), str):
        raise _refused(
            "the sweep does not say what it varies", "name an exploration, or give vary with a path and its values"
        )
    if vary.get("also") not in (None, ""):
        names_of(vary["also"], "vary.also", "what else the sweep sets with each value")
    for key in ("label", "unit"):
        if vary.get(key) not in (None, ""):
            name_of(vary[key], f"vary.{key}")
    values = vary.get("schemes") if vary["path"] == "scheme" else vary.get("values")
    if not isinstance(values, list) or not values:
        raise _refused("the sweep has no values to go through", "give vary.values, or vary.schemes for the scheme")
    if vary["path"] == "scheme":
        names_of(values, "vary.schemes", "the schemes a sweep goes through")
    if len(values) > MOST_VARIANTS:
        raise _refused(
            f"the sweep has {len(values)} variants, and {MOST_VARIANTS} is the most", "give fewer values", "vary.values"
        )
    plan["values"] = values
    return plan


def _set_scheme(scheme: Scheme, path: str, value: Any, design: Design) -> Scheme:
    """The scheme with what one path names set."""
    parts = path.split(".")
    if path == "scheme.rate":
        from motionsim.control.presets import retimed

        rate = _number(value, "updates a carrier period", low=0.0, high=8.0, field="vary.values")
        return retimed(scheme, design, rate)
    if path == "scheme.sensing":
        from motionsim.control.applications import SENSINGS, shunted

        if value not in SENSINGS:
            raise _refused(f"the currents are sensed by one of {', '.join(SENSINGS)}", "vary one of those", "vary.path")
        if not any(b.kind == "current_sampling" for b in scheme.blocks):
            raise _refused(
                f"the scheme {scheme.named} has no current sensor for shunts to take the place of",
                "vary a scheme that samples its currents",
                "vary.path",
            )
        return shunted(scheme, value)
    if parts[1] == "timing" and len(parts) == 3:
        return replace(scheme, timing={**scheme.timing, parts[2]: value})
    if parts[1] == "gains" and len(parts) == 3 and parts[2] in GAINS:
        name, gains = GAINS[parts[2]]
        factor = _number(value, "the factor on the gains", low=0.0, high=1e6, field=path)
        blocks = [
            replace(
                b,
                params={k: (v * factor if k in gains else v) for k, v in b.params.items()},
                sources={
                    **b.sources,
                    **{k: f"the rule's value times {factor:g}, by the sweep" for k in gains if k in b.params},
                },
            )
            if b.name == name
            else b
            for b in scheme.blocks
        ]
        if not any(b.name == name for b in scheme.blocks):
            raise _refused(
                f"the scheme {scheme.named} has no block called {name}", "vary a scheme that has one", "vary.path"
            )
        return replace(scheme, blocks=blocks)
    if parts[1] == "blocks" and len(parts) == 4:
        name, param = parts[2], parts[3]
        if not any(b.name == name for b in scheme.blocks):
            raise _refused(
                f"the scheme {scheme.named} has no block called {name}",
                f"one of {', '.join(b.name for b in scheme.blocks)}",
                "vary.path",
            )
        return replace(
            scheme,
            blocks=[
                replace(b, params={**b.params, param: value}, sources={**b.sources, param: "set by the sweep"})
                if b.name == name
                else b
                for b in scheme.blocks
            ],
        )
    raise _refused(
        f"nothing is called {path}",
        "a scheme path is scheme.blocks.<block>.<parameter>, scheme.timing.<name> or scheme.gains.current",
        "vary.path",
    )


def _request(data: dict, plan: dict, settings: dict[str, Any], workspace: Workspace) -> dict:
    """The request of one run of the sweep: the sweep's own, with every setting applied. The
    settings of the request go in first, so that a scheme is built for the design they make."""
    request = {k: copy.deepcopy(v) for k, v in data.items() if k not in ("exploration", "vary", "fixed", "reads")}
    for key in ("scheme", "scenario", "fidelity"):
        if plan.get(key) not in (None, ""):
            request[key] = copy.deepcopy(plan[key])
    inner: list[tuple[str, Any]] = []
    for path, value in settings.items():
        parts = path.split(".")
        if path == "scheme":
            if value not in BUILDERS:
                names = _schemes_named(_designed(request, workspace)[0])
                raise _refused(f"there is no scheme called {value}", f"one of {names}", "vary.schemes")
            request["scheme"] = value
        elif path in ("fidelity", "seed"):
            request[path] = value
        elif path == LINK_SHARE:
            request["link_share"] = value
        elif parts[0] in TOP and len(parts) == 2:
            held = request.get(parts[0])
            request[parts[0]] = {**(held if isinstance(held, dict) else {}), parts[1]: value}
        elif path in ("scheme.sensing", "scheme.rate") or (parts[0] == "scheme" and len(parts) >= 3):
            inner.append((path, value))
        else:
            raise _refused(f"nothing is called {path}", "see the paths a sweep can vary", "vary.path")
    if inner:
        design, _ = _designed(request, workspace)
        scheme = _scheme(request, design)
        for path, value in inner:
            scheme = _set_scheme(scheme, path, value, design)
        request["scheme"] = scheme.data()
    return request


def _summary(ran: Ran) -> dict:
    """What a sweep keeps of one run."""
    from motionsim.service.shapes import _result, level_of

    found, trace = ran.found, ran.trace
    shaped = _result(found.result, ran.rest["device"].ratings.tj_max, ran.rest["op"].parallel)
    channels = report.channels(trace, found, ran.quality, steady=ran.kind == "hold")
    motor = motor_loss(ran)
    kept = trace.time >= trace.gather_from - 1e-12
    return {
        "channels": channels,
        "losses": {
            "loss": shaped["loss"],
            "conduction": shaped["conduction"],
            "switching": shaped["switching"],
            "tj_peak": channels["tj_peak"],
            "tj_swing": channels["tj_swing"],
            "tj_peak_from_start": float(found.tj_from_start.max()),
            "motor_copper": motor["copper"],
            "motor_iron": motor["iron"],
            "system": motor["system"],
        },
        "step": report.tracked(
            trace, ran.planned.tracked, report.ripple_window(trace, ran.design.f_sw, ran.inverter.fidelity)
        ),
        "sensing": _sensing(trace, ran.scheme),
        "loops": _current_loop(ran.linear),
        "torque_mean": float(trace.wire("plant.torque")[kept].mean()),
        "stability": ran.stability,
        "checks": ran.checks,
        "level": level_of(ran.checks),
        "refused": None,
    }


def _current_loop(found: dict | None) -> dict:
    """The q-axis current loop's crossover and phase margin, by the linear analysis of the run's scheme."""
    margins = ((found or {}).get("current_q") or {}).get("margins") or {}
    return {"current_hz": margins.get("crossover_hz"), "current_pm": margins.get("phase_deg")}


def _link(read: dict) -> dict:
    """What a sweep keeps of the link."""
    return {
        "v_min": read["v_min"],
        "v_max": read["v_max"],
        "ripple": read["ripple"],
        "sag": max(read["v_ref"] - read["v_min"], 0.0),
        "thd": read["thd"],
    }


def _one(request: dict, workspace: Workspace, ready: Ready) -> dict:
    steps = execute(request, workspace, ready)
    while True:
        try:
            next(steps)
        except StopIteration as done:
            ran = done.value
            link = linking.linked(ran, request, workspace)
            return _summary(ran) | {"link": _link(link.read) if link else None}


def _read(variant: dict, key: str) -> float | None:
    found: Any = variant
    for part in key.split("."):
        if not isinstance(found, dict) or found.get(part) is None:
            return None
        found = found[part]
    return float(found) if isinstance(found, (int, float)) and not isinstance(found, bool) else None


def _with_unit(value: float, unit: str) -> str:
    # An angle's degree sign stands against its figure, "11.4° rms"; every other unit after a space.
    gap = "" if unit.startswith("°") and not unit.startswith("°C") else " "
    return f"{said_number(value, 3)}{f'{gap}{unit}' if unit else ''}"


def _changed(read: Read, start: float, value: float) -> str:
    """How a figure moved from the baseline's to another's, both in the unit they are said in:
    what goes in the parentheses after the two figures."""
    moved = value - start
    way = "higher" if moved > 0 else "lower"
    apart = _with_unit(abs(moved), read.change_unit)
    if read.kind != "relative":
        return "no change to speak of" if abs(moved) < read.least else f"{apart} {way}"
    small = abs(start) < read.floor
    if small and abs(value) < read.floor:
        return "no change to speak of"
    if small:
        return f"{apart} {way}"  # no base for a percentage
    if abs(moved) < read.least * abs(start):
        return "no change to speak of"
    if start * value < 0:
        return f"it changes sign: {apart} apart"
    # A figure with a sign (a torque, an error) is compared by its size.
    signed = start < 0
    grew = abs(value) > abs(start)
    way = ("larger in size" if grew else "smaller in size") if signed else way
    share = 100.0 * abs(moved) / abs(start)
    if share > MOST_PERCENT:
        return f"{written(abs(value) / abs(start), 3)} times as {'large in size' if signed else 'high'}"
    return f"{written(share, 3)} % {way}"


def _shown(read: Read, value: float) -> str:
    return "about zero" if read.kind == "relative" and abs(value) < read.floor else _with_unit(value, read.unit)


def _sentences(variants: list[dict], baseline: int, reads: list[str], vary: dict) -> list[str]:
    """What the sweep found, in sentences worked out from its figures: each figure read at
    the baseline, and at the variant that moved it furthest, with the change said the way
    that kind of figure changes (`Read`)."""
    said = []
    base = variants[baseline]
    for v in variants:
        if v["refused"] is not None:
            said.append(f"{v['label']} could not be run: {v['refused']['refused']}")
            continue
        # What a run says of whether it did what was asked comes first: a figure read from
        # a step that is not over, or from another torque than the one asked, is not the
        # figure the sweep is about.
        said += [f"{v['label']}: {c['message']}" for c in v["checks"] if c["topic"] == "tracking"]
        if not v["stability"]["linear_stable"]:
            said.append(f"{v['label']}: {v['stability']['said']}")
    if base["refused"] is not None:
        return said
    if vary.get("path") == "scheme":
        # Two schemes' losses or ripples compare only at the torque each really made.
        made = [(v, _read(v, "torque_mean")) for v in variants if v["refused"] is None]
        shown = ", ".join(f"{said_number(x, 3)} N·m at {v['label']}" for v, x in made if x is not None)
        if shown:
            said.append(f"torque delivered: {shown}")
    for key in reads:
        read = READS.get(key) or Read(key, "")
        start = _read(base, key)
        found = [(v, _read(v, key)) for n, v in enumerate(variants) if n != baseline and v["refused"] is None]
        others: list[tuple[dict, float]] = [(v, x * read.factor) for v, x in found if x is not None]
        if not others:
            continue
        if start is None:
            # The baseline has no such figure (an encoder has no angle error): the others' are said.
            shown = ", ".join(f"{said_number(x, 3)} at {v['label']}" for v, x in others)
            missing = (
                "does not settle within the run" if key.endswith(("settling_time", "recovery_time")) else "has none"
            )
            said.append(f"{read.label}{f' ({read.unit})' if read.unit else ''}: {shown}; {base['label']} {missing}")
            continue
        start *= read.factor
        far, value = max(others, key=lambda pair: abs(pair[1] - start))
        said.append(
            f"{read.label}: {_shown(read, start)} at {base['label']}, {_shown(read, value)} at {far['label']} "
            f"({_changed(read, start, value)})"
        )
    return said


def tags_of(said: list[str], variants: list[dict]) -> list[str]:
    """A tag for each of the sweep's sentences, as a page marks them: "short" for one that says a
    run did not do what was asked (a step not over, another torque than the one asked, a loop
    unstable, a variant that could not be run), "note" for a figure read. A sweep's sentences
    never pass or fail the design: no sentence is tagged good."""
    flagged = set()
    for v in variants:
        if v["refused"] is not None:
            flagged.add(f"{v['label']} could not be run: {v['refused']['refused']}")
            continue
        flagged.update(f"{v['label']}: {c['message']}" for c in v["checks"] if c["topic"] == "tracking")
        if not v["stability"]["linear_stable"]:
            flagged.add(f"{v['label']}: {v['stability']['said']}")
    return ["short" if line in flagged else "note" for line in said]


def _label(vary: dict, value: Any, design: Any = None) -> str:
    if vary["path"] == "scheme":
        # A scheme by its short name, as the page names it: what comes before its label's colon.
        from motionsim.control.presets import BUILDERS

        built = BUILDERS.get(str(value))
        return built(design).label.split(":")[0].strip() if built is not None and design is not None else str(value)
    shown = written(value, 4) if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)
    unit = f" {vary['unit']}" if vary.get("unit") else ""
    return f"{vary.get('label') or vary['path']} {shown}{unit}"


def sweep_steps(data: dict, workspace: Workspace) -> Generator[dict, None, dict]:
    """The sweep, each variant said as it finishes, and the whole answer returned."""
    notes = shape("sweep", data)
    design, rest = _designed(data, workspace)
    plan = _planned(data, design)
    vary, values = plan["vary"], plan["values"]
    paths = [vary["path"], *(vary.get("also") or [])]
    # Every variant is made ready before the first is run: what the whole sweep would take
    # is known from its sampling instants, and a sweep too long is refused before it starts.
    readied: list[tuple[dict, Ready] | Refusal] = []
    for value in values:
        try:
            request = _request(data, plan, {**plan["fixed"], **dict.fromkeys(paths, value)}, workspace)
            readied.append((request, prepared(request, workspace)))
        except Refusal as refusal:
            readied.append(refusal)
    runs = [made[1] for made in readied if not isinstance(made, Refusal)]
    needed = sum(r.seconds for r in runs)
    if needed > SWEEP_BUDGET:
        raise over(needed, SWEEP_BUDGET, sum(r.instants for r in runs), f"its {len(runs)} runs go through")
    variants: list[dict] = []
    for n, (value, made) in enumerate(zip(values, readied, strict=True)):
        began = time.perf_counter()
        try:
            if isinstance(made, Refusal):
                raise made
            found = _one(made[0], workspace, made[1])
        except Refusal as refusal:
            found = {
                "channels": None,
                "losses": None,
                "step": None,
                "sensing": None,
                "torque_mean": None,
                "stability": None,
                "checks": [],
                "level": "fail",
                "refused": {"refused": refusal.reason, "fix": refusal.fix, "field": refusal.field},
            }
        key = "scheme" if vary["path"] == "scheme" else "value"
        variant = {key: value, "label": _label(vary, value, design), **found, "seconds": time.perf_counter() - began}
        variants.append(variant)
        yield {"variant": n, "of": len(values), "progress": (n + 1) / len(values), "result": variant}
    wanted = vary.get("baseline")
    baseline = values.index(wanted) if wanted in values else 0
    reads = plan["reads"]
    return {
        "exploration": plan["exploration"],
        "scheme": plan.get("scheme") if isinstance(plan.get("scheme"), str) else None,
        "scenario": plan.get("scenario"),
        "fidelity": plan.get("fidelity") or "switched",
        "vary": vary,
        "fixed": plan["fixed"],
        "reads": reads,
        "variants": variants,
        "baseline": baseline,
        "said": (said := _sentences(variants, baseline, reads, vary)),
        "tags": tags_of(said, variants),
        "taken": rest["taken"] + notes,
    }


def sweep(data: dict, workspace: Workspace) -> dict:
    """The answer of a sweep, its progress left unsaid."""
    steps = sweep_steps(data, workspace)
    while True:
        try:
            next(steps)
        except StopIteration as done:
            return done.value
