"""A motion followed through time: the junction traced through it, the checks over the whole
of it, a heatsink sized to it where asked, and the answer as the page and a report read it."""

from __future__ import annotations

import math
from dataclasses import replace
from types import SimpleNamespace
from typing import TYPE_CHECKING

import numpy as np

from motionsim import guard
from motionsim.engine import OperatingPoint, ThermalRunaway
from motionsim.engine.limits import hottest
from motionsim.engine.point import NO_STABLE
from motionsim.errors import Refusal
from motionsim.service.answers import GATE_FIX
from motionsim.service.shapes import _checks
from motionsim.service.validate import _number
from motionsim.service.validate import supply as _supply
from motionsim.service.workspace import Workspace

if TYPE_CHECKING:
    pass
from motionsim.service.motion import told
from motionsim.service.motion.inputs import Motion, motion_inputs


def _inrush(data: dict, op: OperatingPoint) -> dict | None:
    from motionsim.starting import inrush

    c_link = data.get("c_link")
    if not c_link:
        return None
    r = data.get("precharge")
    found = inrush(
        op.v_dc,
        _number(c_link, "DC-link capacitance", low=1e-9, field="c_link"),
        _number(r, "precharge resistance", low=1e-3, field="precharge") if r else None,
    )
    return {"energy": found.energy, "peak": found.peak, "time": found.time}


def _life(trace, tj, duration: float) -> dict:
    """Thermal-cycling life of the chip that wears out first, from its own temperature
    trace, by a generic model."""
    from motionsim.lifetime import estimate, worst_of

    life = worst_of(trace.chips, trace.swings) or estimate(np.asarray([v for v in tj if math.isfinite(v)]))
    endless = not math.isfinite(life.repeats)
    return {
        "repeats": None if endless else life.repeats,
        "hours": None if endless else life.repeats * duration / 3600,
        "swing": life.swing,
        "swing_mean": life.swing_mean,
        "swing_share": life.swing_share,
        "swings": life.swings,
        "chip": life.chip,
        "within_turn": life.within_turn,
    }


def follow_cycle(m: Motion, op: OperatingPoint | None = None, *, started: bool = True):
    """The motion solved instant by instant with temperatures followed through time: the
    last run of it, and the trace of all of them."""
    from motionsim.engine.mosfet import MissingGateDrive
    from motionsim.transient import follow

    try:
        return follow(
            m.device,
            m.motor,
            m.load,
            m.profile,
            m.op if op is None else op,
            heatsink=m.sink if op is None else None,
            repeats=m.repeats,
            start=m.start if started else None,
            samples=m.mission if m.mission is not None else m.samples,
            per_segment=m.per_segment,
        )
    except MissingGateDrive as exc:
        raise Refusal(str(exc), GATE_FIX, "v_drive") from None


def worst_instant(run, trace):
    """The hottest instant of a motion, and its result with the temperature it reached in
    time. The spread across the thermal assumptions is carried over from the steady
    solution there."""
    worst = run.steps[trace.peak_index % len(run.steps)]
    if worst.point is None:
        worst = run.worst
    result = worst.point.result
    shift = trace.peak - hottest(result)
    span = result.tj_peak_range
    reached = replace(
        result,
        tj_switch_peak=result.tj_switch_peak + shift,
        tj_diode_peak=result.tj_diode_peak + shift,
        tj_peak_range=None if span is None else (span[0] + shift, span[1] + shift),
    )
    return worst, reached


def motion_checks(m: Motion, run, reached, link, supply: str) -> list[guard.Check]:
    """The checks over a whole motion: the hottest instant as it was reached, the most
    current, the energy braking returns, the instant with the most ripple, what the link
    capacitor carries at its worst, a trip at the top speed, and whether the motor could
    follow all of it."""
    from motionsim import dclink

    device, op = m.device, m.op
    checks = guard.check(
        device,
        op,
        reached,
        max(s.heaviest.stage.i_peak for s in run.solved),
        i_limit=guard.current_limit(m.motor, max((s.point.ripple_pp or 0.0) for s in run.solved)),
    )
    checks += dclink.check(link, op.v_dc, device.ratings.v_max, supply=supply)
    hardest, most = _hardest(run), _most_ripple_current(run)
    # The ripple is weighed against the most current of the motion, not the current at the
    # instant it is largest: that is often a pause, carrying almost none.
    peak = max(s.heaviest.stage.i_peak for s in run.solved)
    weighed = SimpleNamespace(stage=SimpleNamespace(i_peak=peak), ripple_pp=hardest.ripple_pp, capacitor_rms=None)
    checks += [c for c in guard.ripple_checks(weighed, op) if c.topic == "ripple"]
    checks += [c for c in guard.ripple_checks(most, op) if c.topic == "link capacitor"]
    tripped = guard.trip_check(m.motor, max(abs(s.sample.motor_rpm) for s in run.steps), op.v_dc, device.ratings.v_max)
    if tripped is not None:
        checks.append(tripped)
    few = told.pulses(m, run)
    if few is not None:
        checks.append(few)
    failed = [s for s in run.steps if s.point is None]
    if failed:
        checks.append(
            guard.Check(guard.Level.fail, "motion", f"the motor cannot follow part of this motion: {failed[0].problem}")
        )
    return checks


def _hardest(run):
    """The instant with the most ripple on the motor current."""
    return max(run.solved, key=lambda s: s.point.ripple_pp or 0.0).point


def _most_ripple_current(run):
    """The instant at which the link capacitor carries most."""
    return max(run.solved, key=lambda s: s.point.capacitor_rms or 0.0).point


def cycle_summary(m: Motion, run, trace, link, peak_top: float) -> dict:
    """The motion in a dozen figures: how long, how hot, the energies, what braking sends
    back, and what the link capacitor carries."""
    most = _most_ripple_current(run)
    lasting = sum(s.sample.duration for s in run.solved)
    # What heats the capacitor is what it carries on average over the motion.
    capacitor_mean = (
        math.sqrt(sum((s.point.capacitor_rms or 0.0) ** 2 * s.sample.duration for s in run.solved) / lasting)
        if lasting
        else 0.0
    )
    return {
        "duration": run.duration,
        "peak": trace.peak,
        # The top of the spread across the thermal assumptions at that instant: what a margin
        # or a heatsink is counted from.
        "peak_top": peak_top,
        "forever": float(np.nanmax(trace.steady)),
        "tj_max": m.device.ratings.tj_max,
        "mean_loss": run.mean_loss,
        "shaft_energy": run.shaft_energy,
        "loss_energy": run.loss_energy,
        "rms_torque": run.rms_torque,
        "returned": link.energy,
        "returned_peak": link.peak_power,
        "v_link_peak": link.v_peak,
        "c_needed": link.capacitance_needed,
        "sink_peak": float(trace.t_sink.max()),
        "capacitor_rms": capacitor_mean if most.capacitor_rms is not None else None,
        "capacitor_rms_worst": most.capacitor_rms,
        "ripple_pp_worst": _hardest(run).ripple_pp,
    }


def _sizing(data: dict, m: Motion, reached) -> dict | None:
    """The heatsink this motion needs when it repeats without pause, where one is asked
    for: sized on the hottest junction through the motion, with the spread across the
    thermal assumptions that its hottest instant carries added on."""
    from motionsim import recommend

    asked = data.get("size_heatsink")
    if not isinstance(asked, dict) or m.sink is not None:
        return None
    ambient = _number(asked.get("t_ambient"), "air temperature", low=-40, high=120, field="t_ambient")
    most = asked.get("t_sink_max")
    limit = (
        None
        if most in ("", None)
        else _number(most, "highest heatsink temperature", low=-40, high=250, field="t_sink_max")
    )
    span = reached.tj_peak_range
    spread = 0.0 if span is None else span[1] - hottest(reached)

    def evaluate(t_sink: float) -> tuple[float, float]:
        held = replace(m.op, t_sink=t_sink, rth_sink=None, rth_free=None, rth_board=None)
        moved, temperatures = follow_cycle(m, held, started=False)
        return temperatures.peak + spread, moved.mean_loss

    needed = recommend.heatsink(m.device, ambient, evaluate, sink_limit=limit)
    return {"value": needed.value, "lines": needed.lines}


def cycle(data: dict, workspace: Workspace) -> dict:
    """A motor, its load and a motion, followed through time: the junction's trace, the
    energies, how the drive starts, the life the swings leave, and the checks over the
    whole of it. The one answer to this, for the page, a design and the command line."""
    from motionsim import dclink

    m = motion_inputs(data, workspace)
    run, trace = follow_cycle(m)
    if not run.solved:
        problem = next(s.problem for s in run.steps if s.problem)
        if any(s.problem == NO_STABLE for s in run.steps):
            # The motor could be asked it; the part does not survive it. That fails, as a
            # point with no stable temperature does everywhere, and is not a slip to put right.
            raise ThermalRunaway(f"no instant of this motion can be run: {NO_STABLE}")
        raise Refusal(
            f"no instant of this motion can be reached: {problem}",
            "slow the motion, lighten the load or raise the supply voltage",
            "motion",
        )
    worst, reached = worst_instant(run, trace)
    c_link = data.get("c_link")
    link = dclink.returned(
        run,
        m.op.v_dc,
        m.device.ratings.v_max,
        capacitance=_number(c_link, "DC-link capacitance", low=1e-9, field="c_link") if c_link else None,
    )
    checks = motion_checks(m, run, reached, link, _supply(data))
    first, offset = told.first_of(trace, run)
    traces = _traces(m, run, trace, first)
    phases = told.phases_of(run.steps, traces["time"])
    duty = {
        "phases": phases,
        "startup": told.startup(m, run.steps, traces, phases),
        "steady_at": told.steady_of(run.steps, trace, first, offset),
        "worst_swing": told.worst_swing(run.steps, trace, first, offset),
        "method": {**m.method, "said": told.method_said(m.method)},
    }
    return {
        **told.thinned(traces),
        **duty,
        "start": m.starting,
        "life": _life(trace, trace.tj[first:], run.duration),
        "inrush": _inrush(data, m.op),
        "summary": cycle_summary(m, run, trace, link, max(hottest(reached), *(reached.tj_peak_range or ()))),
        "checks": _checks(checks),
        **_for_a_reader(m, run, trace, worst, first, offset),
        "device": workspace.summary(data["device"], m.device),
        "sizing": _sizing(data, m, reached),
        "taken": m.taken,
    }


def _traces(m: Motion, run, trace, first: int) -> dict:
    """What the page draws against time: one figure an instant of the last time through."""
    clean = lambda a: [None if not math.isfinite(v) else float(v) for v in a]  # noqa: E731
    return {
        "time": clean(trace.time[first:] - (trace.time[first] - run.steps[0].sample.duration)),
        "tj": clean(trace.tj[first:]),
        "steady": clean(trace.steady[first:]),
        "t_sink": clean(trace.t_sink[first:]),
        "sink_name": "each package's case, on average" if m.op.rth_free is not None else "heatsink",
        "rpm": [s.sample.motor_rpm for s in run.steps],
        "torque": [s.sample.motor_torque for s in run.steps],
        "p_stage": [None if s.point is None else s.point.result.p_inverter for s in run.steps],
        "i_peak": [None if s.point is None else s.heaviest.stage.i_peak for s in run.steps],
        "p_dc": [
            None if s.point is None else s.point.stage.p_electrical + s.point.result.p_inverter for s in run.steps
        ],
        # The junction's swing within one period of the output, or one turn of the load, K.
        "swing": clean(trace.ripple[first:]) if trace.ripple.size else [None] * len(run.steps),
    }


def _for_a_reader(m: Motion, run, trace, worst, first: int, offset: float) -> dict:
    """For a reader in a terminal: where the hottest instant fell, each instant that could
    not be reached and why, and the heatsink that was followed."""
    return {
        "worst": {
            "time": float(trace.time[trace.peak_index]),
            "rpm": worst.sample.motor_rpm,
            "torque": worst.sample.motor_torque,
        },
        "problems": [s.problem for s in run.steps],
        # A duty's stretch held until steady is followed only until it is, so its instants
        # are where they fell in time; any other motion's are where they were asked for.
        "instants": [s.sample.time for s in run.steps]
        if m.samples is None
        else [float(t - offset) - s.sample.duration / 2 for s, t in zip(run.steps, trace.time[first:], strict=True)],
        "began": float(trace.time[first]) - run.steps[0].sample.duration,
        "repeats": m.repeats,
        "names": {
            "motor": m.motor.name,
            "type": m.motor.type,
            "load": None if m.load is None else m.load.name,
            "profile": None if m.profile is None else m.profile.name,
        },
        "heatsink": None
        if m.sink is None
        else {
            "rth": m.sink.rth,
            "capacity": m.sink.capacity,
            "t_ambient": m.sink.t_ambient,
            "t_start": m.op.t_sink,
            "settles": m.sink.t_ambient + run.mean_loss * m.sink.rth,
        },
    }
