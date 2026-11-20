"""What a duty is said to have done: its phases in time, how it started, where it got steady,
its worst swing of the junction, and the traces thinned for the page with every peak kept."""

from __future__ import annotations

import math

import numpy as np

from motionsim import guard

# Points the page draws a motion with, at most. A bucket of the trace keeps the instants of
# its lowest and highest figure of each quantity drawn, so no peak is lost.
BUCKETS = 200
THIN_ABOVE = 1200
KEPT = ("tj", "steady", "t_sink", "rpm", "torque", "p_stage", "i_peak", "p_dc", "swing")


def thinned(traces: dict) -> dict:
    """The traces with at most a few points a bucket of time: the first and the last, and
    the first and last instants of each quantity's least and greatest in it."""
    n = len(traces["time"])
    if n <= THIN_ABOVE:
        return traces
    keep = {0, n - 1}
    edges = np.linspace(0, n, BUCKETS + 1).astype(int)
    for key in KEPT:
        values = np.array([np.nan if v is None else v for v in traces[key]], dtype=float)
        for a, b in zip(edges, edges[1:], strict=False):
            part = values[a:b]
            if b <= a or np.all(np.isnan(part)):
                continue
            # The first and the last instant of each, so that a stretch held flat keeps its
            # end as well as its start, and is never drawn as a slope to what comes next.
            for pick in (np.nanargmax, np.nanargmin):
                keep.add(int(a + pick(part)))
                keep.add(int(b - 1 - pick(part[::-1])))
    order = sorted(keep)
    out = dict(traces)
    for key in ("time", *KEPT):
        out[key] = [traces[key][k] for k in order]
    out["thinned"] = {"from": n, "to": len(order)}
    return out


def phases_of(steps, ends: list[float]) -> list[dict]:
    """The named parts of a duty in the order they came, each from when it began to when it
    ended, s. Instants of no named part (a start's alignment) are left out."""
    out: list[dict] = []
    for step, end in zip(steps, ends, strict=True):
        name = step.sample.phase
        begin = end - step.sample.duration
        if name is None:
            continue
        if out and out[-1]["name"] == name and abs(out[-1]["end"] - begin) < 1e-9:
            out[-1]["end"] = end
        else:
            out.append({"name": name, "start": begin, "end": end})
    return out


def _window(steps, ends: list[float], phases: list[dict]) -> float:
    """When the start-up ends, s: the end of a phase named so, or else of the first stretch
    that leaves standstill."""
    named = next((p for p in phases if p["name"] == "start-up"), None)
    if named is not None:
        return named["end"]
    for step, end in zip(steps, ends, strict=True):
        if step.sample.load_acceleration == 0 and step.sample.motor_rpm != 0:
            return end - step.sample.duration
    return ends[-1] if ends else 0.0


def startup(m, steps, traces: dict, phases: list[dict]) -> dict | None:
    """How the drive got the load going: the most current in the start-up, how long the
    current stood near it, and the junction's own peak there."""
    ends = traces["time"]
    if not ends:
        return None
    until = _window(steps, ends, phases)
    inside = [k for k, t in enumerate(ends) if t - steps[k].sample.duration < until - 1e-9]
    amps = [(k, traces["i_peak"][k]) for k in inside if traces["i_peak"][k] is not None]
    if not amps:
        return None
    k_top, top = max(amps, key=lambda x: x[1])
    near = [k for k, i in amps if i >= 0.9 * top]
    held = sum(steps[k].sample.duration for k in near)
    tj = [(traces["tj"][k], ends[k]) for k in inside if traces["tj"][k] is not None]
    peak, at = max(tj) if tj else (None, None)
    limit = guard.current_limit(m.motor)
    run_up = next((r for r in m.runups if r.reached), None)
    return {
        "current": top,
        "time": held,
        "at": ends[k_top],
        "until": until,
        "tj_peak": peak,
        "tj_at": at,
        "limit": limit,
        "at_limit": limit is not None and top >= 0.97 * limit,
        "run_up": None if run_up is None else run_up.time,
        "run_up_reached": None if not m.runups else all(r.reached for r in m.runups),
    }


def steady_of(steps, trace, first: int, offset: float) -> list[dict]:
    """Each stretch held until steady: when it began, how long it took, the junction then,
    and those the cap stopped first."""
    began: dict[int, tuple[float, str | None]] = {}
    ends = trace.time[first:] - offset
    for step, end in zip(steps, ends, strict=True):
        place = step.sample.steady
        if place is not None and place not in began:
            began[place] = (float(end - step.sample.duration), step.sample.phase)
    reached = {place: (float(at - offset), tj) for place, at, tj in trace.steady_at}
    out = []
    for place, (start, name) in began.items():
        if place in reached:
            at, tj = reached[place]
            out.append({"phase": name, "start": start, "time": at, "after": at - start, "tj": tj, "reached": True})
        else:
            stop = max(float(e) for s, e in zip(steps, ends, strict=True) if s.sample.steady == place)
            out.append(
                {"phase": name, "start": start, "time": stop, "after": stop - start, "tj": None, "reached": False}
            )
    return out


def worst_swing(steps, trace, first: int, offset: float) -> dict | None:
    """The largest swing a junction goes through within one period of the output or one turn
    of the load, where in the duty it is, and the output's frequency there."""
    ripple = trace.ripple[first:] if trace.ripple.size else np.zeros(0)
    if not ripple.size or not np.nanmax(ripple) > 0:
        return None
    k = int(np.nanargmax(ripple))
    step = steps[k]
    point = step.point
    stage = None if point is None else point.stage
    period = None if stage is None or stage.stalled else stage.period
    return {
        "swing": float(ripple[k]),
        "time": float(trace.time[first + k] - offset),
        "phase": step.sample.phase,
        "rpm": step.sample.motor_rpm,
        "torque": step.sample.motor_torque,
        "f_e": None if not period else 1.0 / period,
        "loss": None if point is None else point.result.p_inverter,
    }


def method_said(method: dict) -> str:
    """The rule that picked how the heatsink is followed, in words."""
    how = method.get("method")
    tau = method.get("tau")
    if how == "periodic" and tau:
        return (
            f"the motion lasts {method['length']:.3g} s, under a tenth of the heatsink's time constant "
            f"({tau / 60:.2g} min): the heatsink is taken where the motion's mean loss holds it, run after run"
        )
    if how == "from cold" and tau:
        assumed = ", an assumed one" if method.get("assumed") else ""
        return (
            f"the motion is long beside the heatsink's time constant ({tau / 60:.2g} min{assumed}): the "
            "heatsink is followed from the air's temperature as it warms"
        )
    if how == "from cold":
        return "the heatsink given is followed from cold as it warms"
    if how == "own air":
        return "each package is taken where its own mean loss through the motion holds it in the air"
    return "the heatsink is held at the temperature given"


def pulses(m, run) -> guard.Check | None:
    """The fewest switching periods in one period of the output over the motion, as a
    caution where they are too few."""
    turning = [s.point.stage for s in run.solved if not s.point.stage.stalled and s.sample.motor_rpm != 0]
    if not turning:
        return None
    fastest = min(turning, key=lambda st: st.period)
    return guard.pulses_check(m.op.f_sw, fastest.period, False, "at the top of the motion ")


def first_of(trace, run) -> tuple[int, float]:
    """Where the last run begins in the trace, and the time it began at."""
    first = len(trace.time) - len(run.steps)
    return first, float(trace.time[first]) - run.steps[0].sample.duration if len(trace.time) else 0.0


def finite(values) -> list:
    return [None if v is None or not math.isfinite(v) else float(v) for v in values]
