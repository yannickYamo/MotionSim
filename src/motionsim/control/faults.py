"""A fault while the drive runs, and the drive's own check that sees it.

`open_switch`: from the fault's instant leg a's high switch never closes. Commanded high, the
leg stands where its current puts it: high through the upper diode while the current comes out
of the motor, low through the lower one while it goes in, and open at nought. Phase a then
carries no current into the motor; the other two carry what it cannot.

`encoder`: from the fault's instant the angle sensor reads the same count, so the controller
sees a rotor standing still where it stopped. The controller then drives a current fixed in a
frame that no longer turns with the rotor, and the torque it makes alternates about nought.

The check is the one a drive can make from what it has: the voltage it applied through each
period and the currents it sampled. It integrates the stator's flux from them, ψs = ∫(v − Rs·i),
and takes from it the active flux, ψa = ψs − Lq·i, which lies along the rotor's d axis whatever
the motor's saliency (ψa = (ψ + (Ld − Lq)·id) on d). The check flags the encoder once ψa stands
more than `AGREE` from the angle the encoder gives, `RUNNING` periods in a row. The integral
starts from the flux the encoder and the currents put at the first instant, and leaks with a
corner far below the slowest speed judged, which keeps it from drifting on the stage's own
voltage errors. It judges only while the back-EMF those give, the active flux times its own
speed of turning, is clear of `FLOOR` of the phase voltage the link allows: at standstill and
at low speed a frozen encoder is not seen from the currents, and the check says so.
"""

from __future__ import annotations

import cmath
import math

FAULTS = ("encoder", "open_switch")
AGREE = math.radians(30.0)  # the active flux's angle from the encoder's, past which it is flagged
RUNNING = 3  # periods in a row past it
FLOOR = 0.05  # of the phase voltage the link allows, v_dc/√3: the back-EMF judged only above it
LEAK = 0.05  # of the slowest speed judged: the integral's corner
SPEED_PERIODS = 5.0  # periods: the time constant the active flux's speed is read through

_S3 = math.sqrt(3.0)


def _vector(a: float, b: float, c: float) -> complex:
    return complex((2.0 * a - b - c) / 3.0, (b - c) / _S3)


def _wrapped(x: float) -> float:
    return (x + math.pi) % (2.0 * math.pi) - math.pi


class EncoderWatch:
    """The drive's plausibility check of its encoder from the voltage it applied and the currents
    it sampled. `seen` is the instant it flagged the encoder, None while it has not; `judged`
    counts the instants it judged; `most` is the most the active flux stood from the encoder's
    angle while judged, before it flagged."""

    def __init__(self, rs: float, ld: float, lq: float, psi: float, v_dc: float) -> None:
        self.rs, self.ld, self.lq, self.psi = rs, ld, lq, psi
        self.floor = FLOOR * v_dc / _S3
        self.leak = LEAK * self.floor / max(psi, 1e-12)
        self.flux: complex | None = None  # ψs
        self.last: complex | None = None  # the current sampled at the last instant
        self.applied: complex | None = None
        self.angle: float | None = None  # the active flux's angle at the last instant
        self.speed = 0.0  # rad/s: the active flux's, read through SPEED_PERIODS
        self.dt = 0.0
        self.past = 0
        self.seen: float | None = None
        self.judged = 0
        self.most = 0.0

    def applied_period(self, duties: tuple[float, float, float], v_dc: float) -> None:
        """The voltage the stage applied through the period about to run, from its duty cycles."""
        held = [min(max(d, 0.0), 1.0) for d in duties]
        mean = sum(held) / 3.0
        self.applied = _vector(*((d - mean) * v_dc for d in held))

    def sampled(self, t: float, ia: float, ib: float, ic: float, theta_e: float) -> bool:
        """The currents sampled at `t` and the encoder's angle there. True the instant the check flags
        the encoder."""
        now = _vector(ia, ib, ic)
        last, self.last = self.last, now
        if self.flux is None:
            # Healthy at the start: the flux the encoder's angle and the currents put there.
            i_dq = now * cmath.exp(-1j * theta_e)
            d_axis = cmath.exp(1j * theta_e)
            self.flux = (self.psi + self.ld * i_dq.real) * d_axis + 1j * self.lq * i_dq.imag * d_axis
            return False
        if self.applied is None or last is None or self.dt <= 0:
            return False
        dt = self.dt
        self.flux += dt * (self.applied - self.rs * 0.5 * (now + last) - self.leak * self.flux)
        active = self.flux - self.lq * now
        angle = cmath.phase(active)
        if self.angle is not None:
            turned = _wrapped(angle - self.angle) / dt
            self.speed += (turned - self.speed) * min(1.0, 1.0 / SPEED_PERIODS)
        self.angle = angle
        if self.seen is not None or abs(active) * abs(self.speed) < self.floor:
            self.past = 0
            return False
        self.judged += 1
        off = abs(_wrapped(angle - theta_e))
        self.past = self.past + 1 if off > AGREE else 0
        if self.past >= RUNNING:
            self.seen = t
            return True
        self.most = max(self.most, off)
        return False


LEG_SHARE = 0.2  # a phase current's mean over a turn, of the current's amplitude, past which a leg is flagged
OPEN_PIECES = 64  # pieces a sampling period is taken in while the broken leg stands by its current alone
MOST_WINDOW = 4096  # samples: the longest turn judged
LEAST_CURRENT = 0.05  # of the motor's current limit: under it the phase currents are not judged


class LegWatch:
    """The drive's check of its legs from the currents it samples: each phase current's mean over
    the last electrical turn against the current's amplitude over it. A healthy phase means nought;
    a leg whose high switch has failed open carries no current into the motor, so its phase loses
    the half-wave that would, and means about −1/π of the amplitude. Flagged past `LEG_SHARE`;
    judged only over a whole turn of samples, with a current of at least `LEAST_CURRENT` of the
    limit, and only after a whole turn of the run."""

    def __init__(self, ts: float, i_limit: float) -> None:
        self.ts, self.least = ts, LEAST_CURRENT * i_limit
        self.kept: list[tuple[float, float, float]] = []
        self.seen: float | None = None
        self.leg: int | None = None

    def sampled(self, t: float, ia: float, ib: float, ic: float, omega_e: float) -> bool:
        if self.seen is not None:
            return False
        self.kept.append((ia, ib, ic))
        if len(self.kept) > MOST_WINDOW:
            del self.kept[0]
        if omega_e == 0.0:
            return False
        n = round(2.0 * math.pi / abs(omega_e) / self.ts)
        if n < 8 or n > len(self.kept):
            return False
        window = self.kept[-n:]
        amp = sum(math.sqrt((a * a + b * b + c * c) * 2.0 / 3.0) for a, b, c in window) / n
        if amp < self.least:
            return False
        means = [sum(w[k] for w in window) / n for k in range(3)]
        leg = max(range(3), key=lambda k: abs(means[k]))
        if abs(means[leg]) > LEG_SHARE * amp:
            self.seen, self.leg = t, leg
            return True
        return False
