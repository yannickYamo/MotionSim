"""What a run says of itself beside the engine's own checks: whether the drive did what the
test asked of it. A hold that makes another torque than the one asked, or whose shaft is not
at the speed asked when the run ends, is not a run of the design point, and its losses and
temperatures are not the design point's: it says so, in words, as a caution.

The limits are of this tool's choosing: 2% of the torque asked and 0.5% of the speed asked,
each with a floor so that a point of no torque or no speed is not judged against nought.
"""

from __future__ import annotations

import math

import numpy as np

from motionsim.control import scenario
from motionsim.control.kernel import SoFar, Trace
from motionsim.control.observers import Observer
from motionsim.control.presets import Design
from motionsim.control.scheme import Compiled
from motionsim.text import written

TORQUE_OFF = 0.02  # of the torque asked
SPEED_OFF = 0.005  # of the speed asked
TORQUE_FLOOR = 0.05  # of the torque limit: what a torque asked is never taken below, for the share
SPEED_FLOOR = 2.0 * math.pi  # rad/s: likewise for the speed (60 rpm)
RPM = 30.0 / math.pi


def _check(message: str, field: str = "scheme") -> dict:
    return {"level": "caution", "topic": "tracking", "message": message, "field": field}


def _share(off: float, against: float) -> str:
    return f"{written(100.0 * abs(off) / against, 2)} %"


def held_point(design: Design, planned: scenario.Plan, trace: Trace, rippled: dict | None) -> list[dict]:
    """A hold against what it was asked to hold: the mean torque over the analysed stretch
    against the torque the trial asks (the design torque, or the load's own over its turn), and, where
    the shaft is free, the speed at the end of the run (over its last turn, where the load pulses within it)
    against the design speed and whether it was still moving."""
    kept = trace.time >= trace.gather_from - 1e-12
    if not kept.any():
        return []
    out = []
    asked = planned.test.torque(float(trace.time[-1]))
    made = rippled["torque_mean"] if rippled is not None else float(trace.wire("plant.torque")[kept].mean())
    against = max(abs(asked), TORQUE_FLOOR * design.torque_limit)
    if abs(made - asked) > TORQUE_OFF * against:
        way = "the other way" if made * asked < 0 else "more" if abs(made) > abs(asked) else "less"
        out.append(
            _check(
                f"the drive made {written(made, 3)} N·m on average where {written(asked, 3)} N·m was asked, "
                f"{_share(made - asked, against)} {way}: the losses and temperatures of this run are those of the "
                "torque it made, not of the design point"
            )
        )
    if planned.held:
        return out  # the bench sets the speed
    speed, at = trace.wire("plant.omega_m")[kept], trace.time[kept]
    span = float(at[-1] - at[0])
    if 0 < planned.turned <= 0.505 * span:  # two turns, less what rounding to whole steps takes
        # A load that pulses within the turn: the speed's mean over the last turn and the first.
        end = float(speed[at >= at[-1] - planned.turned].mean())
        moved = end - float(speed[at <= at[0] + planned.turned].mean())
        span -= planned.turned
    else:
        end = float(speed[-1])
        moved = end - float(speed[0])
    wanted = design.omega
    floor = max(abs(wanted), SPEED_FLOOR)
    off, moving = abs(end - wanted) > SPEED_OFF * floor, abs(moved) > SPEED_OFF * floor and span > 0
    if off or moving:
        message = (
            f"the shaft turns at {written(end * RPM, 3)} rpm when the run ends where {written(wanted * RPM, 3)} rpm "
            f"was asked ({_share(end - wanted, floor)} off)"
        )
        if moving:
            way = "speeding up" if moved * end > 0 or (end == 0 and moved > 0) else "slowing"
            message += f", and it is still {way}, by {written(abs(moved) / span * RPM, 2)} rpm a second"
        out.append(_check(message + ": the run did not hold the design point"))
    return out


LOST = 15.0  # ° electrical: an estimated angle further off than this no longer makes the torque asked
STEP_BAND = 0.02  # of the step: the band the settling time is read against


def _said(value: float, wire: str) -> str:
    return f"{written(value * RPM, 3)} rpm" if wire == "plant.omega_m" else f"{written(value, 3)} N·m"


def stepped(planned: scenario.Plan, trace: Trace) -> list[dict]:
    """A step against where it was to arrive: one that never rose through 90% of the way, or
    that ends outside the band about its target, did not get there within the run."""
    asked = planned.tracked
    if asked is None or trace.time.size < 3:
        return []
    wire, y = asked["wire"], trace.wire(asked["wire"])
    what = "speed" if wire == "plant.omega_m" else "torque"
    span = float(trace.time[-1] - trace.time[0])
    tail = max(trace.time.size // 20, 2)
    rate = float(y[-1] - y[-tail]) / max(float(trace.time[-1] - trace.time[-tail]), 1e-12)
    if asked["kind"] == "disturbance":
        held = asked["held"]
        floor = max(abs(held), SPEED_FLOOR)
        if abs(float(y[-1]) - held) <= SPEED_OFF * floor:
            return []
        return [
            _check(
                f"the speed did not come back within the run: it ends at {_said(float(y[-1]), wire)} where "
                f"{_said(held, wire)} is held ({_share(float(y[-1]) - held, floor)} off). Lengthen the test, or "
                "look at whether the drive has the torque the load now asks",
                "scenario.duration",
            )
        ]
    start, target = asked["from"], asked["to"]
    size = target - start
    if size == 0:
        return []
    done = (y[trace.time >= asked["t_step"]] - start) / size
    reached = bool((done >= 0.9).any())
    end = float(done[-1]) if done.size else 0.0
    if reached and abs(end - 1.0) <= STEP_BAND:
        return []
    still = ""
    if abs(rate) * span > STEP_BAND * abs(size):
        unit = "rpm" if wire == "plant.omega_m" else "N·m"
        scale = RPM if wire == "plant.omega_m" else 1.0
        way = "rising" if rate * size > 0 else "falling back"
        still = f", still {way} by {written(abs(rate) * scale, 2)} {unit} a second"
    return [
        _check(
            f"the {what} did not reach {_said(target, wire)} within the run: it ends at "
            f"{_said(float(y[-1]), wire)}, {written(100.0 * end, 3)} % of the way from {_said(start, wire)}{still}. "
            "The step's figures are those of a step that is not over: lengthen the test, or look at whether "
            "the drive has the torque to get there",
            "scenario.duration",
        )
    ]


def lost(compiled: Compiled, trace: Trace | SoFar, floor: dict | None = None) -> list[dict]:
    """An observer below the speed it can read at: where the run took the shaft under the
    speed at which the observer's own signal is too small, while the scheme was on the
    observer, it says so, with how long and how far off the estimated angle went. `floor` is
    the observer's floor for this run (control/floor.py), where it is known: where the error
    it reads through sets it above the observer's own, that is the speed said."""
    block = next((b for b in compiled.blocks if isinstance(b, Observer)), None)
    if block is None or trace.time.size < 2:
        return []
    floor_e, why = block.lowest()
    if floor is not None and floor["held_by"] == "error":
        floor_e = floor["omega_e"]
        why = (
            f"there its back-EMF is {floor['margin']:g} times the {written(_error_v(floor), 3)} V it reads it "
            "through wrong"
        )
    pairs = block.ctx.pole_pairs
    on = np.ones(trace.time.size, dtype=bool)
    start = next((b for b in compiled.blocks if b.kind == "if_startup"), None)
    if start is not None:
        on = trace.wire(f"{start.name}.mode") >= 1.0  # until then the angle is the imposed one
    injected = next((b for b in compiled.blocks if b.kind == "hf_injection"), None)
    if injected is not None:
        on = trace.wire(f"{injected.name}.share") > 0.0  # below the hand-over the angle is the injection's
    under = on & (np.abs(trace.wire("plant.omega_m")) * pairs < floor_e)
    if not under.any():
        return []
    step = float(np.median(np.diff(trace.time)))
    worst = float(np.degrees(np.abs(trace.wire(f"{block.name}.error")[under]).max()))
    if worst < LOST:
        return []  # it passed under its floor and held all the same, as a model with the right figures can
    return [
        _check(
            f"the observer loses the rotor below {written(floor_e / pairs * RPM, 3)} rpm ({why}): the shaft was "
            f"under that speed for {written(under.sum() * step * 1e3, 3)} ms of this run with the scheme on the "
            f"observer, and the estimated angle was up to {written(worst, 3)}° off the rotor's. A drive with no "
            "encoder passes through standstill open loop (the start's hand-back), or with a method that reads "
            "the rotor's saliency",
            f"scheme.blocks.{start.name}.handback" if start is not None else "scheme",
        )
    ]


def _error_v(floor: dict) -> float:
    return floor["stage_v"] + floor["noise_v"] + floor["resistance_v"]


def tracking(
    kind: str,
    design: Design,
    planned: scenario.Plan,
    trace: Trace,
    rippled: dict | None,
    compiled: Compiled,
    floor: dict | None = None,
) -> list[dict]:
    """What the run says of whether it did what its test asked."""
    found = held_point(design, planned, trace, rippled) if kind == "hold" else stepped(planned, trace)
    return found + lost(compiled, trace, floor)


TAIL_SHARE = 0.1  # of the stretch after a step: what the current is taken to have settled to


def current_overshoot(planned: scenario.Plan, trace: Trace, window: float | None) -> dict | None:
    """How far the current's size passed what it settled to, after a torque step: the peak of
    |i| = √(id² + iq²), read on its mean over a switching period (`window`) so the ripple is
    not taken for it, over its mean through the last tenth of the run. This is the figure the
    pulsed rating is held to in place of the fixed allowance. None for any other test (the
    current of a speed or load step, or a start, goes to the drive's limit, not past a
    reference), for a step that ends at no current, and for a step that does not raise the
    torque's size: there the first samples after it still carry the current from before, which
    is no overshoot, and the rating is held with the allowance."""
    asked = planned.tracked
    if asked is None or asked.get("kind") != "step" or asked.get("wire") != "plant.torque":
        return None
    if abs(float(asked.get("to", 0.0))) <= abs(float(asked.get("from", 0.0))):
        return None
    from motionsim.control.metrics import moving_mean

    t = trace.time
    after = t >= asked["t_step"]
    if int(after.sum()) < 10:
        return None
    size = np.hypot(trace.wire("plant.i_d"), trace.wire("plant.i_q"))[after]
    ts = t[after] - asked["t_step"]
    mean = moving_mean(ts, size, window) if window else size
    tail = ts >= ts[-1] * (1.0 - TAIL_SHARE)
    final = float(np.mean(mean[tail]))
    if final <= 1e-9:
        return None
    peak = float(np.max(mean))
    return {"share": max(peak / final - 1.0, 0.0), "settled": final, "peak": peak}
