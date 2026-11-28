"""The blocks between the controller and the world: what it measures (currents, the rotor's
angle), the changes of frame, and the modulator that turns a voltage into duty cycles."""

from __future__ import annotations

import math
import random
from collections import deque

import numpy as np

from motionsim.control.blocks import Block, Param, Port, register
from motionsim.engine.modulation import Pwm, _zero_sequence

SQRT3 = math.sqrt(3.0)
TWO_PI = 2.0 * math.pi
PWM_NAMES = tuple(p.value for p in Pwm)


@register
class CurrentSampling(Block):
    kind = "current_sampling"
    role = "sensing"
    title = "Current sampling"
    summary = (
        "Reads two phase currents at the carrier's peak and makes the third; a sensor's noise and offset are "
        "added where given."
    )
    definition = (
        "Reads two phase currents at the sampling instant (the carrier's peak, where the ripple passes through "
        "its mean) and makes the third from them; a sensor's noise, offset, gain error and the converter's steps "
        "are added where given."
    )
    math = (
        r"\hat i_a = \mathrm{Q}\!\left[(1+g)\,i_a + o + n\right]",
        r"\hat i_b = \mathrm{Q}\!\left[i_b + n\right]",
        r"\hat i_c = -\hat i_a - \hat i_b",
    )
    inputs = (
        Port("i_a", "A", "phase a current"),
        Port("i_b", "A", "phase b current"),
        Port("i_c", "A", "phase c current"),
    )
    outputs = (
        Port("i_a", "A", "sampled phase a current"),
        Port("i_b", "A", "sampled phase b current"),
        Port("i_c", "A", "phase c current made from the other two"),
    )
    params = (
        Param("noise", "A", 0.0, "gaussian noise on each sample, rms", 0.0, 1e4),
        Param("offset", "A", 0.0, "offset of the phase a sensor", -1e4, 1e4),
        Param("gain_error", "", 0.0, "gain error of the phase a sensor, as a share", -0.5, 0.5),
        Param("bits", "bit", 0.0, "resolution of the converter; 0 for none", 0.0, 24.0),
        Param("full_scale", "A", 100.0, "current at the converter's full scale, either way", 1e-3, 1e6),
    )

    def setup(self) -> None:
        bits = int(self.p["bits"])
        self._step = 2.0 * self.p["full_scale"] / (2**bits) if bits else 0.0
        self._plain = not (self.p["noise"] or self.p["offset"] or self.p["gain_error"] or bits)

    def reset(self) -> None:
        # Seeded: the same run gives the same noise.
        self._random = random.Random(self.ctx.seed)

    def _read(self, value: float) -> float:
        if self.p["noise"]:
            value += self._random.gauss(0.0, self.p["noise"])
        if self._step:
            top = self.p["full_scale"]
            value = min(max(round(value / self._step) * self._step, -top), top)
        return value

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        i_a, i_b, i_c = inputs
        if self._plain:
            return i_a, i_b, i_c
        a = self._read((1.0 + self.p["gain_error"]) * i_a + self.p["offset"])
        b = self._read(i_b)
        return a, b, -a - b


SHUNTS = ("three", "two", "single")
FIXES = ("shift", "none")
# A window the timer made exactly long enough is long enough: what it falls short by in the
# rounding, in single precision as much as in double, is no shortfall.
SLACK = 1e-5


def shifted(duty: list[float], shunts: str, window: float, half: float, rising: bool) -> list[float]:
    """The duty cycles of half a carrier period with the edges shifted so the shunts can read.

    Under low-side shunts, the legs together: every duty lowered by as much as the legs that must
    be read are short of the window, which leaves the line voltages as they were, as far as the
    lowest leg has room. Under one shunt in the DC link, the vectors apart: in the rising half the
    highest leg rises the window ahead of the middle one and the lowest the window after (the
    middle one moved instead where a rail stops the other), and the falling half gives that back,
    so the period's mean is the one asked where the rails allow."""
    if window <= 0.0:
        return duty
    least = window / (2.0 * half)  # of the duty cycle: the window, about the peak, both halves
    if shunts != "single":
        legs = sorted(range(3), key=lambda x: duty[x])[:2] if shunts == "three" else [0, 1]
        short = max(duty[x] - (1.0 - least) for x in legs)
        down = min(max(short, 0.0), min(duty))
        return [d - down for d in duty]
    hi, mid, lo = sorted(range(3), key=lambda x: -duty[x])
    gap = window / half
    up = list(duty)  # the rising half's; the falling half's give back what they moved

    def move(leg: int, to: float) -> None:
        # No further than the falling half can give back within the rails: the mean holds.
        room = min(duty[leg], 1.0 - duty[leg])
        up[leg] = duty[leg] + min(max(to - duty[leg], -room), room)

    if up[hi] - up[mid] < gap:
        # The highest leg ahead of the middle one; where the rail stops it, the middle one back.
        move(hi, up[mid] + gap)
        if up[hi] - up[mid] < gap:
            move(mid, up[hi] - gap)
    if up[mid] - up[lo] < gap:
        # The lowest leg after the middle one; where the rail stops it, the middle one on.
        move(lo, up[mid] - gap)
        if up[mid] - up[lo] < gap:
            move(mid, min(up[lo] + gap, up[hi] - gap))
    return up if rising else [2.0 * d - u for d, u in zip(duty, up, strict=True)]


@register
class ShuntSampling(Block):
    kind = "shunt_sampling"
    role = "sensing"
    title = "Shunt sampling"
    summary = (
        "Reads the phase currents through shunts in the stage, as a low-cost drive does: each reading needs "
        "its switch on long enough, and a phase that cannot be read is made from the others or held."
    )
    definition = (
        "Reads the phase currents through resistors in the stage, where a cheap drive has no current sensor. "
        "Three or two shunts sit under the low switches: a phase is read at the carrier's peak while its low "
        "switch is on, which it is for (1 − d)·Ts, and needs that to be at least the window the amplifier "
        "and the converter take to settle and sample. Of three, the two with the longest windows are read "
        "and the third made from them; of two (phases a and b), each is read where it can be. One shunt in "
        "the DC link reads, in each of the period's two active vectors, the current of the leg alone in its "
        "state: two phases a period, the third made from them, each read where its vector stands for the "
        "window, in the period before the instant. A phase that cannot be read keeps its last reading, made "
        "to sum to nought with what was read; `held` says when. At a high modulation a low-side shunt's "
        "window closes; at a low one, and wherever two references meet, a DC-link shunt's does."
    )
    math = (
        r"\text{low side: } (1 - d_x)\,T_s \ge t_w:\quad \hat i_x = \mathrm{Q}[i_x + n]",
        r"\text{DC link: } i_{dc} = \sum_{x\ \text{high}} i_x,\quad \text{read where the vector stands} \ge t_w",
        r"\hat i_a + \hat i_b + \hat i_c = 0",
    )
    inputs = (
        Port("i_a", "A", "phase a current, at the sampling instant"),
        Port("i_b", "A", "phase b current, at the sampling instant"),
        Port("i_c", "A", "phase c current, at the sampling instant"),
        Port("window_a", "s", "leg a's low switch on about the instant"),
        Port("window_b", "s", "leg b's low switch on about the instant"),
        Port("window_c", "s", "leg c's low switch on about the instant"),
        Port("i_dc_1", "A", "the DC link's current in the first active vector"),
        Port("vector_1", "", "the legs high in it"),
        Port("span_1", "s", "how long it stood"),
        Port("i_dc_2", "A", "the DC link's current in the second active vector"),
        Port("vector_2", "", "the legs high in it"),
        Port("span_2", "s", "how long it stood"),
        Port(
            "skip",
            "",
            "1 where no reading is due at this instant: the last is kept, and no miss counted",
            optional=True,
        ),
    )
    outputs = (
        Port("i_a", "A", "phase a current as read"),
        Port("i_b", "A", "phase b current as read"),
        Port("i_c", "A", "phase c current as read"),
        Port("held", "", "1 where a reading was due and a phase could not be read: its last reading was kept"),
    )
    params = (
        Param("shunts", "", "three", "three or two under the low switches, or one in the DC link", choices=SHUNTS),
        Param("window", "s", 2e-6, "the least time a shunt must carry its phase to be read", 0.0, 1e-3),
        Param(
            "fix",
            "",
            "shift",
            "what the timer does where a window would be too short: shift the edges so it is not "
            "(the legs together under low-side shunts, the vectors apart under one in the DC link), or nothing",
            choices=FIXES,
        ),
        Param("noise", "A", 0.0, "gaussian noise on each reading, rms", 0.0, 1e4),
        Param("bits", "bit", 0.0, "resolution of the converter; 0 for none", 0.0, 24.0),
        Param("full_scale", "A", 100.0, "current at the converter's full scale, either way", 1e-3, 1e6),
    )

    def setup(self) -> None:
        bits = int(self.p["bits"])
        self._step = 2.0 * self.p["full_scale"] / (2**bits) if bits else 0.0

    def reset(self) -> None:
        self._random = random.Random(self.ctx.seed)
        self._last: list[float] | None = None

    def _read(self, value: float) -> float:
        if self.p["noise"]:
            value += self._random.gauss(0.0, self.p["noise"])
        if self._step:
            top = self.p["full_scale"]
            value = min(max(round(value / self._step) * self._step, -top), top)
        return value

    def _low_side(self, currents: tuple[float, ...], windows: tuple[float, ...]) -> dict[int, float]:
        """The phases a low-side shunt reads: of three, the two with the longest windows; of two,
        a and b; each only where its window is long enough."""
        legs = sorted(range(3), key=lambda x: -windows[x])[:2] if self.p["shunts"] == "three" else [0, 1]
        return {x: self._read(currents[x]) for x in legs if windows[x] >= self.p["window"] * (1.0 - SLACK)}

    def _dc_link(self, readings: tuple[tuple[float, ...], ...]) -> dict[int, float]:
        """The phases one DC-link shunt reads: one leg high, its own current; two high, the
        third's reversed. A vector too short to read, or none, reads nothing."""
        got: dict[int, float] = {}
        for i_dc, vector, span in readings:
            state = round(vector)
            if state in (0, 7) or span <= 0.0 or span < self.p["window"] * (1.0 - SLACK):
                continue
            high = [x for x in range(3) if (state >> x) & 1]
            if len(high) == 1:
                got[high[0]] = self._read(i_dc)
            else:
                low = next(x for x in range(3) if not (state >> x) & 1)
                got[low] = -self._read(i_dc)
        return got

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        currents, windows = inputs[0:3], inputs[3:6]
        if len(inputs) > 12 and inputs[12] > 0.5 and self._last is not None:
            # No reading is due: the drive works on with the last, as its converter was not started.
            return self._last[0], self._last[1], self._last[2], 0.0
        if self.p["shunts"] == "single":
            got = self._dc_link((inputs[6:9], inputs[9:12]))
        else:
            got = self._low_side(currents, windows)
        if len(got) >= 2:
            # Two phases read make the third.
            known = list(got)[:2]
            out = [0.0, 0.0, 0.0]
            for x in known:
                out[x] = got[x]
            third = next(x for x in range(3) if x not in known)
            out[third] = -out[known[0]] - out[known[1]]
            held = 0.0
        else:
            # What could not be read keeps its last reading; the phases sum to nought. At the first
            # instant there is no period before and nothing to keep: the drive reads as it starts.
            if self._last is None:
                got = {x: got.get(x, self._read(currents[x])) for x in range(2)}
                self._last = [got[0], got[1], -got[0] - got[1]]
                return self._last[0], self._last[1], self._last[2], 0.0
            last = self._last
            out = [got.get(x, last[x]) for x in range(3)]
            free = [x for x in range(3) if x not in got]
            excess = sum(out) / len(free)
            for x in free:
                out[x] -= excess
            held = 1.0
        self._last = out
        return out[0], out[1], out[2], held


@register
class PositionSensing(Block):
    kind = "position_sensing"
    role = "sensing"
    title = "Position sensing"
    summary = (
        "The rotor's angle and speed as the controller sees them: ideal, or through an encoder's counts and delay."
    )
    definition = (
        "Gives the controller the rotor's angle and speed: as they are (ideal), or as an encoder of so many "
        "counts a turn reads them, so many seconds late, with the speed taken from the counts over a window."
    )
    math = (
        r"\hat\theta_m[k] = \frac{2\pi}{N}\left\lfloor \frac{N\,\theta_m(t_k - T_\ell)}{2\pi} \right\rfloor",
        r"\hat\omega_m[k] = \frac{\hat\theta_m[k] - \hat\theta_m[k-W]}{W\,T_s}",
        r"\hat\theta_e = p\,\hat\theta_m",
    )
    inputs = (
        Port("theta", "rad", "the rotor's electrical angle"),
        Port("omega_m", "rad/s", "the shaft's speed"),
    )
    outputs = (
        Port("theta", "rad", "electrical angle as sensed"),
        Port("omega_m", "rad/s", "shaft speed as sensed"),
        Port("omega_e", "rad/s", "electrical speed as sensed"),
    )
    params = (
        Param("sensor", "", "ideal", "ideal, or an encoder with counts and latency", choices=("ideal", "encoder")),
        Param("counts", "1/turn", 4096.0, "encoder counts in one turn of the shaft", 4.0, 1e8),
        Param("latency", "s", 0.0, "how late the angle is read", 0.0, 0.01),
        Param("speed_window", "samples", 8.0, "samples the speed is taken over", 1.0, 4096.0),
    )

    def setup(self) -> None:
        self._late = round(self.p["latency"] / self.ctx.ts)
        self._window = int(self.p["speed_window"])
        self._count = TWO_PI / self.p["counts"]
        # The shaft's angle an electrical turn is: what the angle given may jump by at a wrap.
        self._turn = TWO_PI / self.ctx.pole_pairs

    def reset(self) -> None:
        self._line: deque[float] = deque(maxlen=self._late + 1)
        self._seen: deque[float] = deque(maxlen=self._window + 1)
        self._last: float | None = None
        self._turned = 0.0

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        theta, omega_m = inputs
        pairs = self.ctx.pole_pairs
        if self.p["sensor"] == "ideal":
            return theta, omega_m, pairs * omega_m
        self._line.append(theta / pairs)
        read = math.floor(self._line[0] / self._count) * self._count
        # The angle may come wrapped to one electrical turn: a jump of whole turns between two
        # samples is taken back out, so the speed is that of the shaft and not of the wrap.
        if self._last is not None:
            self._turned -= math.floor((read - self._last) / self._turn + 0.5) * self._turn
        self._last = read
        self._seen.append(read + self._turned)
        span = len(self._seen) - 1
        speed = (self._seen[-1] - self._seen[0]) / (span * self.ctx.ts) if span else omega_m
        return pairs * read, speed, pairs * speed


@register
class Clarke(Block):
    kind = "clarke"
    role = "transform_feedback"
    title = "Clarke transform"
    definition = "Three phase currents as two in the stator's own axes (amplitude kept)."
    math = (
        r"i_\alpha = \tfrac{2}{3}\left(i_a - \tfrac12 i_b - \tfrac12 i_c\right)",
        r"i_\beta = \tfrac{1}{\sqrt3}\left(i_b - i_c\right)",
    )
    inputs = (Port("a", "A", "phase a"), Port("b", "A", "phase b"), Port("c", "A", "phase c"))
    outputs = (Port("alpha", "A", "along phase a"), Port("beta", "A", "a quarter turn ahead"))

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        a, b, c = inputs
        return (2.0 * a - b - c) / 3.0, (b - c) / SQRT3


@register
class Park(Block):
    kind = "park"
    role = "transform_feedback"
    title = "Park transform"
    definition = "Stator-frame quantities seen from the rotor: d along the magnet, q a quarter turn ahead."
    math = (
        r"x_d = x_\alpha\cos\theta + x_\beta\sin\theta",
        r"x_q = -x_\alpha\sin\theta + x_\beta\cos\theta",
    )
    inputs = (
        Port("alpha", "", "stator-frame component along phase a"),
        Port("beta", "", "stator-frame component a quarter turn ahead"),
        Port("theta", "rad", "electrical angle"),
    )
    outputs = (Port("d", "", "along the magnet"), Port("q", "", "a quarter turn ahead of it"))

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        alpha, beta, theta = inputs
        c, s = math.cos(theta), math.sin(theta)
        return alpha * c + beta * s, beta * c - alpha * s


@register
class InversePark(Block):
    kind = "inverse_park"
    role = "transform_forward"
    title = "Inverse Park transform"
    summary = "Rotor-frame voltages back to the stator's frame, at the angle the rotor will have when they are applied."
    definition = (
        "Rotor-frame voltages turned back to the stator's frame, at the angle the rotor will have reached "
        "when the voltage is applied: `advance` sampling periods ahead (1.5 with a one-sample delay: the "
        "delay, and half the period the voltage is held for; 0.5 without)."
    )
    math = (
        r"\theta' = \theta + a\,\omega_e T_s",
        r"v_\alpha = v_d\cos\theta' - v_q\sin\theta'",
        r"v_\beta = v_d\sin\theta' + v_q\cos\theta'",
    )
    inputs = (
        Port("d", "V", "d-axis voltage"),
        Port("q", "V", "q-axis voltage"),
        Port("theta", "rad", "electrical angle"),
        Port("omega_e", "rad/s", "electrical speed"),
    )
    outputs = (Port("alpha", "V", "along phase a"), Port("beta", "V", "a quarter turn ahead"))
    params = (Param("advance", "samples", 1.5, "sampling periods the angle is advanced by", 0.0, 4.0),)

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        d, q, theta, omega_e = inputs
        angle = theta + self.p["advance"] * omega_e * self.ctx.ts
        c, s = math.cos(angle), math.sin(angle)
        return d * c - q * s, d * s + q * c


MIN_LOSS = "discontinuous-min-loss"
RAIL = 1e-12  # of a period: a duty cycle nearer a rail than this is on it


def on_rail(duty: float) -> float:
    """A duty cycle, taken to the rail where it is within a rounding step of one: a pulse of
    a millionth of a millionth of a period is no pulse."""
    return 0.0 if duty <= RAIL else 1.0 if duty >= 1.0 - RAIL else duty


@register
class Modulator(Block):
    kind = "modulator"
    role = "actuation"
    title = "Modulator"
    summary = (
        "Turns the voltage asked for into the three legs' duty cycles. In its least-loss mode it clamps the "
        "leg carrying the most current to a rail, so that leg does not switch; at low modulation it centres "
        "the references as space-vector does."
    )
    definition = (
        "Turns the voltage asked for into the three legs' duty cycles: each phase's share of half the DC "
        "voltage, shifted together by the scheme's zero-sequence signal (the same shifts the loss engine "
        "uses), and held between 0 and 1. One more shift is chosen online, for least switching loss "
        "(discontinuous-min-loss): of the two legs that can be held to a rail without leaving the linear "
        "range, the one whose reference is highest and the one whose reference is lowest, the one "
        "carrying the larger current is held and so does not switch. That follows the current's peak as "
        "far as 30° either side of the voltage's; past that the clamp stops at the edge. It needs the phase "
        "currents wired in; without them it clamps at the voltage peaks. The currents it chooses by are a "
        "sample old when the duty cycles take effect, and the rotor has turned since: with the electrical "
        "speed wired in they are turned forward by `advance` sampling periods first (1.5 with a one-sample "
        "delay), or the clamp changes legs that much late, which at 30 periods a turn costs a twentieth "
        "of what it saves. Below `threshold` in modulation "
        "index it centres the references as space-vector does, where a clamp costs more ripple than it "
        "saves. A supervisor's signal (`clamp`, above nought) asks for that shift whatever `pwm` says."
    )
    math = (
        r"u_x = \frac{v_x}{V_{dc}/2},\quad x \in \{a,b,c\}",
        r"d_x = \mathrm{clip}\!\left(\tfrac12\,(1 + u_x + u_0),\,0,\,1\right)",
        r"u_0 = -\tfrac12\left(\max u_x + \min u_x\right)\ \text{(space-vector)}",
        r"u_0 = \begin{cases} 1 - u_{max} & |i_{max}| \ge |i_{min}| \\ -1 - u_{min} & \text{otherwise}"
        r"\end{cases}\ \text{(discontinuous-min-loss)}",
        r"i_{\alpha\beta}' = e^{\,j a\,\omega_e T_s}\,i_{\alpha\beta}\ \text{(the currents the clamp is chosen by)}",
    )
    inputs = (
        Port("alpha", "V", "voltage along phase a"),
        Port("beta", "V", "voltage a quarter turn ahead"),
        Port("v_dc", "V", "DC voltage"),
        Port("i_a", "A", "phase a current, for the least-loss clamp", optional=True),
        Port("i_b", "A", "phase b current, for the least-loss clamp", optional=True),
        Port("i_c", "A", "phase c current, for the least-loss clamp", optional=True),
        Port("clamp", "", "above nought: clamp for least loss whatever `pwm` says", optional=True),
        Port("omega_e", "rad/s", "electrical speed, to turn the currents to when the clamp applies", optional=True),
    )
    outputs = (
        Port("d_a", "", "duty cycle of leg a's high side"),
        Port("d_b", "", "duty cycle of leg b's high side"),
        Port("d_c", "", "duty cycle of leg c's high side"),
        Port("m", "", "modulation index asked for"),
        Port("clamped", "", "leg held to a rail: 1 to 3 high, -1 to -3 low, 0 none"),
        Port("limited", "", "1 while a duty cycle asked for lies past a rail and is cut there"),
    )
    params = (
        Param(
            "pwm",
            "",
            Pwm.space_vector.value,
            "how the three references are shifted",
            choices=(*PWM_NAMES, MIN_LOSS),
        ),
        Param("threshold", "", 0.0, "modulation index below which the least-loss clamp is not used", 0.0, 1.2),
        Param("advance", "samples", 0.0, "sampling periods the currents are turned forward by for the clamp", 0.0, 4.0),
    )

    def setup(self) -> None:
        self._min_loss = self.p["pwm"] == MIN_LOSS
        self._pwm = Pwm.space_vector if self._min_loss else Pwm(self.p["pwm"])
        self._phases = np.zeros((3, 1))
        self._theta = np.zeros(1)

    def _least_loss(self, u: tuple[float, float, float], i: tuple[float, float, float]) -> tuple[float, float]:
        """The shift that holds, of the highest and the lowest reference, the leg carrying
        the larger current; and which leg that is."""
        high = max(range(3), key=u.__getitem__)
        low = min(range(3), key=u.__getitem__)
        size_high, size_low = abs(i[high]), abs(i[low])
        if size_high == size_low:  # no current to go by: the larger reference, as the fixed scheme does
            size_high, size_low = abs(u[high]), abs(u[low])
        if size_high >= size_low:
            return 1.0 - u[high], float(high + 1)
        return -1.0 - u[low], float(-low - 1)

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        alpha, beta, v_dc = inputs[:3]
        # The currents and the supervisor's signal are optional: nought where a caller leaves them out.
        i_a, i_b, i_c, clamp, omega_e = (*inputs[3:], 0.0, 0.0, 0.0, 0.0, 0.0)[:5]
        half = 0.5 * v_dc
        a = alpha / half
        b = (-0.5 * alpha + 0.5 * SQRT3 * beta) / half
        c = (-0.5 * alpha - 0.5 * SQRT3 * beta) / half
        m = math.hypot(alpha, beta) / half
        pwm = self._pwm
        clamped = 0.0
        if clamp > 0.0 or (self._min_loss and m >= self.p["threshold"]):
            turn = self.p["advance"] * omega_e * self.ctx.ts
            if turn:
                # The currents as they will stand when these duty cycles are applied.
                i_alpha, i_beta = (2.0 * i_a - i_b - i_c) / 3.0, (i_b - i_c) / SQRT3
                cs, sn = math.cos(turn), math.sin(turn)
                i_alpha, i_beta = i_alpha * cs - i_beta * sn, i_alpha * sn + i_beta * cs
                i_a = i_alpha
                i_b, i_c = -0.5 * i_alpha + 0.5 * SQRT3 * i_beta, -0.5 * i_alpha - 0.5 * SQRT3 * i_beta
            shift, clamped = self._least_loss((a, b, c), (i_a, i_b, i_c))
        elif pwm is Pwm.sine:
            shift = 0.0
        elif pwm is Pwm.space_vector:
            shift = -0.5 * (max(a, b, c) + min(a, b, c))
        else:
            # The engine's own shifts, asked for the one instant: phase a is m·sin(theta).
            phases, theta = self._phases, self._theta
            phases[0, 0], phases[1, 0], phases[2, 0] = a, b, c
            theta[0] = math.atan2(alpha, -beta)
            shift = float(_zero_sequence(pwm, m, theta, phases)[0])
            # Which leg that shift holds, and to which rail: the highest reference to the
            # high one, or the lowest to the low one.
            if shift == 1.0 - max(a, b, c):
                clamped = float(max(range(3), key=(a, b, c).__getitem__) + 1)
            elif shift == -1.0 - min(a, b, c):
                clamped = float(-min(range(3), key=(a, b, c).__getitem__) - 1)
        asked = [0.5 * (1.0 + a + shift), 0.5 * (1.0 + b + shift), 0.5 * (1.0 + c + shift)]
        cut = any(d < -1e-9 or d > 1.0 + 1e-9 for d in asked)
        if clamped:
            # The held leg's duty cycle is the rail itself, written and not worked out:
            # 0.5·(1 + u + (1 − u)) comes out a rounding step under 1 for some u, and a leg
            # that is a rounding step from a rail would be charged two commutations a period.
            asked[int(abs(clamped)) - 1] = 1.0 if clamped > 0 else 0.0
        d_a, d_b, d_c = (on_rail(min(max(d, 0.0), 1.0)) for d in asked)
        return d_a, d_b, d_c, m, clamped, float(cut)
