"""The design's own motion, as the lab reads it: the load and how it moves (step 4), or a
mission profile, sampled at the motor's shaft the way the motion is followed elsewhere
(load.sample, the mission's own instants). From it the lab takes a window to run closed loop
(the stretch of its peak torque, or of its fastest change of torque) and the speeds it passes
through, which an observer's floor is set beside."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from motionsim.control import scenario
from motionsim.errors import Refusal
from motionsim.text import written

PER_STRETCH = 24  # instants a stretch of the motion is sampled at


@dataclass
class Motion:
    """A motion at the motor's shaft: instants (s from its start), speed (rpm), torque (N·m)."""

    t: np.ndarray
    rpm: np.ndarray
    torque: np.ndarray
    duration: float
    # A mission's instant stands until the next (service/motion/inputs._mission), as the five
    # steps step through it; the load's motion is sampled densely and read between its samples.
    held: bool = False


def motion_of(data: dict, needed: bool = False) -> Motion | None:
    """The request's motion, sampled; None where it has none. A motion that does not read is
    refused only where the test needs it (`needed`): another test runs without it."""
    from motionsim.service.motion.inputs import _load_and_profile, _mission

    if not data.get("mission") and not (data.get("load") and data.get("profile")):
        return None
    try:
        mission = _mission(data.get("mission"))
        if mission is not None:
            samples, length = mission, mission[-1].time + mission[-1].duration
        else:
            from motionsim.load import sample

            load, profile = _load_and_profile(data, None)
            if load is None or profile is None or not profile.stretches():
                return None
            samples, length = sample(load, profile, PER_STRETCH), profile.duration
    except (Refusal, ValueError, TypeError, KeyError, AttributeError):
        if needed:
            raise
        return None
    if len(samples) < 2:
        return None
    t = np.array([s.time for s in samples], dtype=float)
    keep = np.concatenate(([True], np.diff(t) > 0))
    return Motion(
        t[keep],
        np.array([s.motor_rpm for s in samples], dtype=float)[keep],
        np.array([s.motor_torque for s in samples], dtype=float)[keep],
        float(length),
        held=mission is not None,
    )


def window_of(motion: Motion, span: float, pick: str) -> tuple[scenario.Window, list[str]]:
    """The window of the motion a run follows: `span` long (the whole motion where it is
    shorter), centred on the instant of its most torque, or on the middle of its fastest
    change of torque, and held inside the motion."""
    said = []
    t, torque = motion.t, motion.torque
    end = float(t[-1])
    if span >= end - float(t[0]):
        span = end - float(t[0])
        said.append(f"the motion is {written(span, 3)} s long between its first and last instants: all of it is run")
    rates = np.abs(np.diff(torque)) / np.diff(t)
    if pick == "change" and rates.size:
        k = int(np.argmax(rates))
        at = 0.5 * float(t[k] + t[k + 1])
    else:
        at = float(t[int(np.argmax(np.abs(torque)))])
    start = min(max(at - 0.5 * span, float(t[0])), end - span)
    inside = (t >= start) & (t <= start + span)
    if motion.held:
        # The instant before the window stands into it.
        inside[max(int(np.searchsorted(t, start, side="right")) - 1, 0)] = True
    inner = np.abs(torque[inside]) if inside.any() else np.abs(torque)
    within = rates[inside[:-1] & inside[1:]] if rates.size else rates
    found = scenario.Window(
        t=t,
        rpm=motion.rpm,
        torque=torque,
        start=start,
        end=start + span,
        pick=pick,
        at=at,
        peak=float(np.max(inner)),
        rate=float(np.max(within)) if within.size else 0.0,
        held=motion.held,
    )
    return found, said


def against_floor(motion: Motion | None, floor_rpm: float) -> dict | None:
    """Where the motion sits against an observer's floor: the slowest and fastest it turns,
    whether it reverses (passing through standstill), and the share of its time spent under
    the floor while it is driven."""
    if motion is None or motion.t.size < 2:
        return None
    speed = np.abs(motion.rpm)
    # Each instant stands for the stretch to the next (the last for as long as the one before).
    spans = np.diff(motion.t)
    spans = np.append(spans, spans[-1])
    # At rest with nothing asked of the motor the drive is off: that is not time spent turning
    # under the floor. Standing still while holding a torque is.
    torque = np.abs(np.asarray(getattr(motion, "torque", np.ones_like(speed)), dtype=float))
    resting = (speed < 1e-9) & (torque < 1e-9)
    under = (speed < floor_rpm) & ~resting
    total = float(np.sum(spans))
    signs = np.sign(motion.rpm[np.abs(motion.rpm) > 1e-9])
    return {
        "lowest_rpm": float(speed.min()),
        "highest_rpm": float(speed.max()),
        "under_share": float(np.sum(spans[under])) / total if total > 0 else 0.0,
        "reverses": bool(signs.size > 1 and (np.diff(signs) != 0).any()),
        "duration": motion.duration,
    }
