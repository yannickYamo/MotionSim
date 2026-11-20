"""A duty: the motion of a real application, minutes or an hour of it in named phases.

A short motion is followed in twelve instants a stretch. A duty is followed by time and by
the load's turn, so that what it costs grows with what changes, not with how long it lasts:

- a stretch whose speed changes is followed in instants of at most RAMP_STEP s, and at
  least MIN_RAMP of them;
- a held stretch in instants that grow from FIRST s by GROWTH each, to at most LONGEST s:
  the junction settles in the first seconds and the heatsink over minutes, and an instant
  whose loss is constant is stepped exactly however long it lasts;
- where the load's torque changes as it turns (a weight on an arm, a tumble, a pulse), no
  instant is longer than a PLACES-th of a turn while a turn takes RESOLVE s or more. At a
  faster turn the instant carries the torque at PLACES places of one turn and how long the
  turn takes, and the follower works out from them the swing each turn puts on a junction.

A stretch at the drive's current limit (at_limit) is worked out here too, before any of
that: the speed rises as fast as the limit lets it against what the load asks.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from motionsim.load import Load, Profile, Sample, Segment

PLACES = 8  # places over one turn where the torque is read
SNAP = 16  # places a turn followed through is read at
RESOLVE = 0.5  # s: a turn this long or longer is followed through
FIRST = 0.25  # s, the first instant of a held stretch
GROWTH = 1.4
LONGEST = 15.0  # s
RAMP_STEP = 5.0  # s
MIN_RAMP = 6
RUN_UP_PIECES = 16  # straight ramps a run-up at the limit is made of


def _with_slope(load: Load, seg: Segment) -> Load:
    """The load on this stretch's own road, where it gives one."""
    if seg.slope_percent is None or load.vehicle is None:
        return load
    return load.model_copy(update={"vehicle": load.vehicle.model_copy(update={"slope_percent": seg.slope_percent})})


def _step(seg: Segment, k: int, coarse: bool) -> float:
    """How long the k-th instant of a stretch is, before the load's turn is counted."""
    scale = 2.0 if coarse else 1.0
    if seg.speed_start != seg.speed_end:
        return min(RAMP_STEP * scale, seg.duration / (MIN_RAMP / scale))
    return min(FIRST * scale * GROWTH**k, LONGEST * scale)


def duty_samples(load: Load, profile: Profile, coarse: bool = False) -> list[Sample]:
    """Motor speed and torque at the instants a duty is followed in."""
    out: list[Sample] = []
    t0 = 0.0
    angle = math.radians(profile.start_angle_deg)
    turning = load.turns_with_angle
    for place, (seg, phase) in enumerate(profile.stretches()):
        here = _with_slope(load, seg)
        w0, w1 = seg.speed_start * math.pi / 30, seg.speed_end * math.pi / 30
        a = (w1 - w0) / seg.duration
        tau, k = 0.0, 0
        while tau < seg.duration * (1 - 1e-12):
            dt = _step(seg, k, coarse)
            fastest = max(abs(w0 + a * tau), abs(w0 + a * min(tau + dt, seg.duration)))
            if turning and fastest > 0 and 2 * math.pi / fastest >= RESOLVE:
                dt = min(dt, 2 * math.pi / fastest / PLACES)
            left = seg.duration - tau
            dt = left if dt >= left or left - dt < 0.3 * dt else dt
            mid = tau + dt / 2
            speed = w0 + a * mid
            here_angle = angle + w0 * mid + 0.5 * a * mid**2
            # A turn followed through is read at the nearest of SNAP places on it, so that the
            # turns of a held stretch ask the same torques again and are solved once.
            read = round(here_angle * SNAP / (2 * math.pi)) * 2 * math.pi / SNAP if turning else here_angle
            rpm, torque = here.at_motor(speed, a, read)
            torques: tuple[float, ...] | None = None
            turn = 0.0
            if turning and speed != 0 and 2 * math.pi / abs(speed) < RESOLVE:
                turn = 2 * math.pi / abs(speed)
                # At places fixed on the turn, not on where this instant began: many turns
                # pass in it, and the same torques at the same speed are solved once.
                torques = tuple(here.at_motor(speed, a, 2 * math.pi * j / PLACES)[1] for j in range(PLACES))
                torque = float(np.mean(torques))
            out.append(
                Sample(
                    t0 + mid,
                    dt,
                    speed,
                    a,
                    here_angle,
                    rpm,
                    torque,
                    phase=phase,
                    torques=torques,
                    turn=turn,
                    steady=place if seg.until_steady else None,
                )
            )
            tau += dt
            k += 1
        angle += w0 * seg.duration + 0.5 * a * seg.duration**2
        t0 += seg.duration
    return out


@dataclass(frozen=True)
class RunUp:
    """A run-up at the drive's current limit, as worked out: how long it took, the torque
    the limit gave at its start, and whether it reached the speed it was asked for."""

    time: float  # s
    torque_limit: float  # N·m at the motor, at the start of the run-up
    reached: bool
    phase: str | None


def _limit_torque(motor, rpm: float, v_dc: float, pwm, limit: float) -> float:
    """The most torque the motor gives at this speed without passing the current limit, N·m:
    found by halving, the current rising with the torque. Nought where it cannot turn at
    this speed at all."""
    from motionsim.motor import Unreachable

    sign = 1.0 if rpm >= 0 else -1.0

    def current(t: float) -> float | None:
        try:
            return motor.stage(rpm, sign * t, v_dc, pwm).i_peak
        except (Unreachable, ValueError):
            return None

    low, high = 0.0, 1.0
    for _ in range(60):  # a torque the limit is passed at
        i = current(high)
        if i is None or i > limit:
            break
        low, high = high, 2 * high
    for _ in range(40):
        middle = (low + high) / 2
        i = current(middle)
        if i is not None and i <= limit:
            low = middle
        else:
            high = middle
    return low


def _asked(load: Load, speed: float, direction: float) -> tuple[float, float]:
    """What the load asks of the motor at a load speed, rad/s: the torque with no
    acceleration at the worst place of a turn, and the torque each rad/s² adds."""
    one = [load.at_motor(speed, direction, 2 * math.pi * j / PLACES)[1] for j in range(PLACES)]
    two = load.at_motor(speed, 2 * direction, 0.0)[1]
    per = (two - one[0]) * direction  # torque per rad/s² of load acceleration, motor side
    worst = max(t * direction for t in one) - per
    return worst, per


def run_up(seg: Segment, load: Load, motor, v_dc: float, pwm, limit: float) -> tuple[list[Segment], float, float]:
    """A stretch at the limit as straight ramps: in each, the speed rises as fast as the
    least the limit leaves over the load across it allows. Returns the ramps, how long they
    take and the torque the limit gives at standstill; no ramps where the limit cannot bring
    the load to speed."""
    direction = 1.0 if seg.speed_end >= seg.speed_start else -1.0
    gear = load.gear_ratio
    speeds = np.linspace(seg.speed_start, seg.speed_end, RUN_UP_PIECES + 1) * math.pi / 30

    def spare(w: float) -> tuple[float, float]:
        worst, per = _asked(load, w, direction)
        rpm = w * gear * 30 / math.pi
        return _limit_torque(motor, rpm, v_dc, pwm, limit) - worst, per

    pieces, total = [], 0.0
    first = _limit_torque(motor, seg.speed_start * gear, v_dc, pwm, limit)
    for wa, wb in zip(speeds, speeds[1:], strict=False):
        found = [spare(w) for w in (wa, (wa + wb) / 2, wb)]
        least = min(f[0] for f in found)
        per = max(f[1] for f in found)
        if least <= 0 or per <= 0:
            return [], math.inf, first
        dt = abs(wb - wa) / (least / per)
        total += dt
        pieces.append(Segment(duration=dt, speed_start=float(wa * 30 / math.pi), speed_end=float(wb * 30 / math.pi)))
    return pieces, total, first


def limited(profile: Profile, load: Load, motor, v_dc: float, pwm, limit: float | None) -> tuple[Profile, list[RunUp]]:
    """The duty with each stretch at the current limit worked out as the ramps it is, and
    what is left of its time held at the speed it reached. A stretch the limit cannot bring
    to speed in any time, or a motor with no limit, keeps the ramp as written."""
    found: list[RunUp] = []

    def worked(seg: Segment, phase: str | None) -> list[Segment]:
        if not seg.at_limit or limit is None:
            return [seg]
        pieces, took, first = run_up(seg, load, motor, v_dc, pwm, limit)
        if not pieces:
            found.append(RunUp(seg.duration, first, False, phase))
            return [seg.model_copy(update={"at_limit": False})]
        found.append(RunUp(took, first, True, phase))
        held = seg.duration - took
        hold = [Segment(duration=held, speed_start=seg.speed_end, speed_end=seg.speed_end)] if held > 1e-3 else []
        return pieces + hold

    if profile.phases is None:
        segments = [s for seg in profile.segments for s in worked(seg, None)]
        return profile.model_copy(update={"segments": segments}), found
    phases = []
    for p in profile.phases:
        segments = [s for seg in p.segments for s in worked(seg, p.name)]
        phases.append(p.model_copy(update={"segments": segments}))
    return profile.model_copy(update={"phases": phases}), found
