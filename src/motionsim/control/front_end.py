"""The control of a drive's front end, and the DC link it holds, through time.

A stage that shapes the mains current has two loops: a slow one that holds the link's voltage
by asking for more or less power, and a fast one that makes the inductor's current follow the
mains' shape at that power. The motor's control and this one share the link, and are tied here
the way a drive ties them: the motor's control says what power it is about to draw (the feed
forward), so the link's loop does not have to see the voltage fall before it answers.

The controller is written out plainly, a sample at a time, in the order its C is written in
(codegen/front_end.py): the two are run side by side on the same samples.

The stage itself is averaged over a switching period: the inductor's current and the link's
voltage move with the duty cycle's mean. On three phases the mains is balanced and its angle is
followed by a phase-locked loop. A rectifier has no control: its capacitor follows the crests.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from motionsim.front_end import Mains

SQRT3 = math.sqrt(3.0)
TWO_PI = 2.0 * math.pi
# The link's loop crosses over at this share of the mains frequency: slower, and a step of the
# load is felt for longer; faster, and the loop bends the current it is meant to keep a sine.
LINK_LOOP = 0.2
# The current's loop crosses over at this share of the sampling frequency.
CURRENT_LOOP = 1.0 / 15.0
# The slow loop runs this many times a period of the mains.
SLOW_PER_PERIOD = 40
# The most duty cycle a boost switch is given, so its diode always has its turn.
MOST_DUTY = 0.97
# The stage's current limit over the peak of what it is sized for.
HEADROOM = 1.5
# Periods of the mains run before the test, for the link and the loops to be in their rhythm.
SETTLING = 6


@dataclass(frozen=True)
class Gains:
    """A front end's controller, tuned for a stage: every figure its C carries."""

    phases: int
    ts: float  # s, the fast loop's period
    slow: int  # the slow loop runs every `slow` samples
    v_ref: float
    kp_v: float  # W per V
    ki_v: float  # W per V per slow sample
    b0: float  # the notch at twice the mains, on the slow loop (one phase only)
    b1: float
    b2: float
    a1: float
    a2: float
    a_ms: float  # the mean square of the mains voltage, low-passed: its share a sample
    kp_i: float  # V per A
    ki_i: float  # V per A per sample
    p_max: float
    p_min: float  # nought for a stage that gives nothing back
    i_max: float
    inductance: float  # H, each phase's
    w0: float  # rad/s, the mains
    kp_pll: float
    ki_pll: float
    feed_forward: bool

    def figures(self) -> dict[str, float]:
        """The gains by name, as the C's table holds them."""
        out = {k: float(v) for k, v in vars(self).items() if k not in ("phases", "slow", "feed_forward")}
        return out | {"slow": float(self.slow), "feed_forward": 1.0 if self.feed_forward else 0.0}


def tuned(
    mains: Mains,
    v_ref: float,
    p_rated: float,
    inductance: float,
    capacitance: float,
    f_s: float,
    *,
    returns: bool,
    feed_forward: bool = True,
) -> Gains:
    """The gains for a stage by rule: the link's loop at a fifth of the mains frequency with
    its zero a quarter of that, the current's loop at a fifteenth of the sampling frequency
    with its zero a tenth of that, a notch at twice the mains on one phase."""
    ts = 1.0 / f_s
    slow = max(1, round(f_s / (SLOW_PER_PERIOD * mains.f)))
    t_slow = slow * ts
    w_v = TWO_PI * LINK_LOOP * mains.f
    kp_v = w_v * capacitance * v_ref
    w_i = TWO_PI * CURRENT_LOOP * f_s
    kp_i = w_i * inductance
    if mains.phases == 1:
        # A notch at twice the mains, two poles at radius r: what the link does at the mains'
        # rhythm does not reach the power asked for, and the current stays a sine.
        w = TWO_PI * 2.0 * mains.f * t_slow
        r = 0.9
        gain = (1.0 - 2.0 * r * math.cos(w) + r * r) / (2.0 - 2.0 * math.cos(w))
        notch = (gain, -2.0 * gain * math.cos(w), gain, -2.0 * r * math.cos(w), r * r)
    else:
        notch = (1.0, 0.0, 0.0, 0.0, 0.0)
    i_rated = math.sqrt(2.0) * p_rated / (mains.v_rms if mains.phases == 1 else SQRT3 * mains.v_rms)
    return Gains(
        phases=mains.phases,
        ts=ts,
        slow=slow,
        v_ref=v_ref,
        kp_v=kp_v,
        ki_v=kp_v * (w_v / 4.0) * t_slow,
        b0=notch[0],
        b1=notch[1],
        b2=notch[2],
        a1=notch[3],
        a2=notch[4],
        # Slow enough that the voltage's own rhythm at twice the mains leaves a percent on its mean
        # square: left in, it comes out as a third harmonic of the current.
        a_ms=ts * mains.f / 8.0,
        kp_i=kp_i,
        ki_i=kp_i * (w_i / 10.0) * ts,
        p_max=HEADROOM * p_rated,
        p_min=-HEADROOM * p_rated if returns else 0.0,
        i_max=HEADROOM * i_rated,
        inductance=inductance,
        w0=TWO_PI * mains.f,
        kp_pll=2.0 * 0.707 * TWO_PI * 20.0,
        ki_pll=(TWO_PI * 20.0) ** 2 * ts,
        feed_forward=feed_forward,
    )


class Controller:
    """The front end's controller as its C runs it: `slow` once every `gains.slow` samples,
    then `fast` (one phase) or `fast3` (three) every sample."""

    def __init__(self, gains: Gains, v_peak: float) -> None:
        self.g = gains
        self.x1 = self.x2 = 0.0  # the notch's state
        self.xv = 0.0  # the link loop's integrator, W
        self.p = 0.0  # the power asked of the mains, W
        self.ms = 0.5 * v_peak * v_peak  # the mains voltage's mean square
        self.xi = 0.0
        self.theta = 0.0
        self.w = gains.w0
        self.xw = 0.0
        self.xd = self.xq = 0.0
        self.ed = v_peak

    def settle(self, v_dc: float, p: float) -> None:
        """Start as a stage that has been holding this link at this power."""
        g = self.g
        if g.phases == 1:
            # The notch at rest on a steady input: its two states hold what makes it give v_dc.
            self.x1 = v_dc * (1.0 - g.b0)
            self.x2 = v_dc * (g.b2 - g.a2)
        self.xv = 0.0 if g.feed_forward else p
        self.p = p

    def slow(self, v_dc: float, p_ff: float) -> float:
        """The link's loop: the power to draw from the mains, W."""
        g = self.g
        y = g.b0 * v_dc + self.x1
        self.x1 = g.b1 * v_dc - g.a1 * y + self.x2
        self.x2 = g.b2 * v_dc - g.a2 * y
        e = g.v_ref - y
        p = g.kp_v * e + self.xv
        if g.feed_forward:
            p = p + p_ff
        p_sat = min(max(p, g.p_min), g.p_max)
        # The integrator stops where the power asked for is at its limit and it would push further.
        if p == p_sat or (p > p_sat) != (e > 0.0):
            self.xv = self.xv + g.ki_v * e
        self.p = p_sat
        return p_sat

    def fast(self, v_in: float, i_l: float, v_dc: float) -> float:
        """One phase: the boost switch's duty cycle from the rectified mains voltage, the
        inductor's current and the link's voltage."""
        g = self.g
        self.ms = self.ms + g.a_ms * (v_in * v_in - self.ms)
        i_ref = self.p / self.ms * v_in
        i_ref = min(max(i_ref, -g.i_max if g.p_min < 0.0 else 0.0), g.i_max)
        e = i_ref - i_l
        u = g.kp_i * e + self.xi
        d = 1.0 - (v_in - u) / v_dc
        # A stage with a diode keeps it its turn; one with a switch in its place needs none.
        d_sat = min(max(d, 0.0), 1.0 if g.p_min < 0.0 else MOST_DUTY)
        if d == d_sat:
            self.xi = self.xi + g.ki_i * e
        return d_sat

    def fast3(self, e_abc: tuple[float, float, float], i_abc: tuple[float, float, float], v_dc: float):
        """Three phases: each leg's duty cycle from the mains voltages (to neutral), the line
        currents (into the stage) and the link's voltage."""
        g = self.g
        ea, eb, ec = e_abc
        ia, ib, ic = i_abc
        e_al = (2.0 * ea - eb - ec) / 3.0
        e_be = (eb - ec) / SQRT3
        i_al = (2.0 * ia - ib - ic) / 3.0
        i_be = (ib - ic) / SQRT3
        c, s = math.cos(self.theta), math.sin(self.theta)
        e_d = c * e_al + s * e_be
        e_q = -s * e_al + c * e_be
        i_d = c * i_al + s * i_be
        i_q = -s * i_al + c * i_be
        # The loop that follows the mains' angle: the voltage has no part across it once locked.
        self.ed = self.ed + 0.01 * (e_d - self.ed)
        lock = e_q / max(self.ed, 1.0)
        self.w = g.w0 + g.kp_pll * lock + self.xw
        self.xw = self.xw + g.ki_pll * lock
        id_ref = self.p / (1.5 * max(self.ed, 1.0))
        id_ref = min(max(id_ref, -g.i_max if g.p_min < 0.0 else 0.0), g.i_max)
        err_d = id_ref - i_d
        err_q = -i_q
        wl = self.w * g.inductance
        v_d = e_d - (g.kp_i * err_d + self.xd) + wl * i_q
        v_q = e_q - (g.kp_i * err_q + self.xq) - wl * i_d
        v_al = c * v_d - s * v_q
        v_be = s * v_d + c * v_q
        va = v_al
        vb = -0.5 * v_al + 0.5 * SQRT3 * v_be
        vc = -0.5 * v_al - 0.5 * SQRT3 * v_be
        # Centred between the rails: the room of space-vector modulation.
        mid = -0.5 * (max(va, vb, vc) + min(va, vb, vc))
        da = 0.5 + (va + mid) / v_dc
        db = 0.5 + (vb + mid) / v_dc
        dc = 0.5 + (vc + mid) / v_dc
        sa = min(max(da, 0.0), 1.0)
        sb = min(max(db, 0.0), 1.0)
        sc = min(max(dc, 0.0), 1.0)
        if sa == da and sb == db and sc == dc:
            self.xd = self.xd + g.ki_i * err_d
            self.xq = self.xq + g.ki_i * err_q
        self.theta = self.theta + self.w * g.ts
        if self.theta > TWO_PI:
            self.theta = self.theta - TWO_PI
        return sa, sb, sc


@dataclass
class Linked:
    """The link and the mains side through a run."""

    time: np.ndarray  # s, each of the motor run's instants
    v_dc: np.ndarray  # V
    p_in: np.ndarray  # W drawn from the mains
    i_line: np.ndarray  # A, one line's current
    v_ref: float
    v_min: float
    v_max: float
    ripple: float  # V peak to peak over the last period of the mains
    thd: float | None  # of the line current over the last period of the mains; None for a rectifier
    i_peak: float
    # The controller's first samples, from the state it is settled in, for the C's replay.
    recorded: dict[str, list] = field(default_factory=dict)
    # The link fell to where the stage no longer holds it: the run of it stops there.
    collapsed: bool = False


def _power_at(time: np.ndarray, power: np.ndarray, t: float) -> float:
    return float(np.interp(t, time, power))


def _distortion(current: np.ndarray) -> float:
    parts = np.abs(np.fft.rfft(current))
    first = float(parts[1])
    rest = float(np.sqrt(np.sum(parts[2:40] ** 2)))
    return rest / first if first > 0 else 0.0


def link_through(
    mains: Mains,
    shapes: bool,
    gains: Gains | None,
    capacitance: float,
    time: np.ndarray,
    power: np.ndarray,
    *,
    v_start: float,
    record: int = 0,
) -> Linked:
    """The link through a run of the motor's control. time, power: what the inverter draws from
    the link at each of the run's instants, W (negative where the motor brakes). A stage that
    shapes the current is run with its controller (gains); a rectifier follows the crests.
    record: how many of the controller's samples to keep for the C's replay."""
    if shapes and gains is not None:
        return _controlled(mains, gains, capacitance, time, power, record)
    return _uncontrolled(mains, capacitance, time, power, v_start)


def _summed(mains: Mains, t, v, p, i, time, v_ref, thd, recorded, collapsed=False):
    last = t >= t[-1] - 1.0 / mains.f
    run = t >= 0.0
    return Linked(
        time=time,
        v_dc=np.interp(time, t, v),
        p_in=np.interp(time, t, p),
        i_line=np.interp(time, t, i),
        v_ref=v_ref,
        v_min=float(v[run].min()),
        v_max=float(v[run].max()),
        ripple=float(v[last].max() - v[last].min()),
        thd=thd,
        i_peak=float(np.abs(i[run]).max()),
        recorded=recorded,
        collapsed=collapsed,
    )


class _OnePhase:
    """A boost cell averaged over a switching period, in the rectified frame."""

    def __init__(self, g: Gains, peak: float) -> None:
        self.g, self.peak = g, peak
        self.il = 0.0
        self.duty = 0.0

    def step(self, ctl: Controller, angle: float, v_dc: float, keep: dict | None) -> tuple[float, float, float]:
        """One sample: what the stage gives the link (A), draws from the mains (W), and its line current."""
        g = self.g
        line = self.peak * math.sin(angle)
        v_in = abs(line)
        il = self.il
        # What was worked out last period is what the stage does in this one.
        applied = self.duty
        self.duty = ctl.fast(v_in, il, v_dc)
        if keep is not None:
            keep["in"].append((v_in, il))
            keep["out"].append((self.duty,))
        after = il + g.ts * (v_in - (1.0 - applied) * v_dc) / g.inductance
        if g.p_min >= 0.0 and after < 0.0:
            after = 0.0  # a diode: the current does not turn round
        self.il = after
        return (1.0 - applied) * after, v_in * after, after if line >= 0.0 else -after


class _ThreePhase:
    """Three legs on a balanced mains, averaged over a switching period."""

    def __init__(self, g: Gains, peak: float) -> None:
        self.g, self.peak = g, peak
        self.i = (0.0, 0.0, 0.0)
        self.duties = (0.5, 0.5, 0.5)

    def step(self, ctl: Controller, angle: float, v_dc: float, keep: dict | None) -> tuple[float, float, float]:
        g, peak = self.g, self.peak
        e = (peak * math.sin(angle), peak * math.sin(angle - TWO_PI / 3.0), peak * math.sin(angle + TWO_PI / 3.0))
        applied = self.duties
        self.duties = ctl.fast3(e, self.i, v_dc)
        if keep is not None:
            keep["in"].append((*e, *self.i))
            keep["out"].append(self.duties)
        mean = (applied[0] + applied[1] + applied[2]) / 3.0
        ia, ib, ic = (
            i + g.ts * (volts - (d - mean) * v_dc) / g.inductance
            for i, volts, d in zip(self.i, e, applied, strict=True)
        )
        self.i = (ia, ib, ic)
        into = applied[0] * ia + applied[1] * ib + applied[2] * ic
        if g.p_min >= 0.0 and into < 0.0:
            into = 0.0
        return into, e[0] * ia + e[1] * ib + e[2] * ic, ia


def _controlled(mains: Mains, g: Gains, capacitance: float, time: np.ndarray, power: np.ndarray, record: int) -> Linked:
    ts = g.ts
    before = SETTLING / mains.f
    n = math.ceil((before + float(time[-1])) / ts) + 1
    t = np.arange(n) * ts - before
    load = np.interp(t, time, power, left=float(power[0]))
    peak = math.sqrt(2.0) * mains.v_phase
    ctl = Controller(g, peak)
    ctl.settle(g.v_ref, float(power[0]))
    stage: _OnePhase | _ThreePhase = _OnePhase(g, peak) if g.phases == 1 else _ThreePhase(g, peak)
    v, p_in, i_line = np.empty(n), np.empty(n), np.empty(n)
    v_dc = g.v_ref
    keep: dict[str, list] = {"v_dc": [], "p_ff": [], "slow": [], "in": [], "out": [], "p": []}
    floor, ceiling, collapsed = 0.5 * peak, 4.0 * g.v_ref, False
    for k in range(n):
        if k % g.slow == 0:
            ctl.slow(v_dc, load[k])
        kept = keep if k < record else None
        if kept is not None:
            kept["slow"].append(1 if k % g.slow == 0 else 0)
            kept["v_dc"].append(v_dc)
            kept["p_ff"].append(float(load[k]))
            kept["p"].append(ctl.p)
        into, p_in[k], i_line[k] = stage.step(ctl, g.w0 * t[k], v_dc, kept)
        v_dc = v_dc + ts * (into - load[k] / v_dc) / capacitance
        if not (floor < v_dc < ceiling):
            # Under half the mains' crest a stage that boosts holds nothing, and a link at several
            # times its set point has long since failed: the rest of the run says nothing.
            collapsed = True
            v[k:], p_in[k:], i_line[k:] = min(max(v_dc, floor), ceiling), 0.0, 0.0
            break
        v[k] = v_dc
    per = round(1.0 / (mains.f * ts))
    thd = _distortion(i_line[-per:]) if n > per and not collapsed else None
    return _summed(mains, t, v, p_in, i_line, time, g.v_ref, thd, keep if record else {}, collapsed)


def _uncontrolled(mains: Mains, capacitance: float, time: np.ndarray, power: np.ndarray, v_start: float) -> Linked:
    """A bridge on the capacitor: the link follows the mains' crests and falls between them by
    what the inverter draws; what the motor gives back charges it, as nothing takes it."""
    ts = 1.0 / (mains.f * 2000.0)
    before = SETTLING / mains.f
    n = math.ceil((before + float(time[-1])) / ts) + 1
    t = np.arange(n) * ts - before
    load = np.interp(t, time, power, left=float(power[0]))
    w = TWO_PI * mains.f
    if mains.phases == 1:
        wave = mains.peak * np.abs(np.sin(w * t))
        sign = np.sign(np.sin(w * t))
    else:
        phases = [np.sin(w * t + shift) for shift in (0.0, -TWO_PI / 3.0, TWO_PI / 3.0)]
        wave = mains.peak / SQRT3 * (np.max(phases, axis=0) - np.min(phases, axis=0))
        # Line a carries the bridge's current while it is the highest or the lowest of the three.
        sign = np.where(
            phases[0] >= np.max(phases, axis=0), 1.0, np.where(phases[0] <= np.min(phases, axis=0), -1.0, 0.0)
        )
    v = np.empty(n)
    p_in = np.zeros(n)
    i_line = np.zeros(n)
    v_dc = v_start
    for k in range(n):
        alone = max(v_dc - ts * load[k] / (v_dc * capacitance), 1.0)
        if wave[k] > alone:
            # The diodes conduct: the mains gives what the load draws and what charges the capacitor.
            amps = max(capacitance * (wave[k] - v_dc) / ts + load[k] / wave[k], 0.0)
            p_in[k] = wave[k] * amps
            i_line[k] = amps * sign[k]
            v_dc = float(wave[k])
        else:
            v_dc = alone
        v[k] = v_dc
    return _summed(mains, t, v, p_in, i_line, time, float(np.mean(v[t >= t[-1] - 1.0 / mains.f])), None, {})
