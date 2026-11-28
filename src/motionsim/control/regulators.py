"""The blocks that decide: the speed reference and its ramp, the speed regulator, the shaping
of the torque it asks, the currents that make a torque, and the current regulator."""

from __future__ import annotations

import math

from motionsim.control.blocks import Block, Param, Port, register
from motionsim.control.references import least_loss
from motionsim.motor import pmsm
from motionsim.motor.stage import Unreachable

SHAPES = ("step", "slew", "s-curve")
MOST = 1e12  # stands for no limit, in a parameter that is a number


class Shaped:
    """A value taken toward a target: at once, at a limited rate, or with a limited rate
    whose own rate of change is limited (an S-curve), so that it arrives without a corner."""

    def __init__(self, shape: str, rate: float, jerk: float, ts: float) -> None:
        self.shape, self.rate, self.jerk, self.ts = shape, rate, jerk, ts
        self.value = self.slope = 0.0

    def start(self, value: float = 0.0) -> None:
        self.value, self.slope = value, 0.0

    def toward(self, target: float) -> float:
        gap = target - self.value
        if self.shape == "step" or gap == 0.0:
            self.value, self.slope = target, 0.0
            return target
        if self.shape == "slew":
            self.slope = math.copysign(self.rate, gap)
        else:
            # The fastest rate from which it can still be brought to rest at the target.
            want = math.copysign(min(self.rate, math.sqrt(2.0 * self.jerk * abs(gap))), gap)
            change = self.jerk * self.ts
            self.slope += min(max(want - self.slope, -change), change)
        move = self.slope * self.ts
        if abs(move) >= abs(gap) and move * gap > 0:
            self.value, self.slope = target, 0.0
        else:
            self.value += move
        return self.value


@register
class SpeedReference(Block):
    kind = "speed_reference"
    role = "reference"
    title = "Speed reference"
    summary = "The speed asked for, given at once, at a limited acceleration, or along an S-curve."
    definition = (
        "Takes the speed asked for to the speed regulator: at once (step), at a limited acceleration (slew), "
        "or with the acceleration itself limited in how fast it changes (S-curve)."
    )
    math = (
        r"\left|\frac{d\omega^*}{dt}\right| \le a_{max}",
        r"\left|\frac{d^2\omega^*}{dt^2}\right| \le j_{max}\ \text{(S-curve)}",
    )
    inputs = (Port("target", "rad/s", "speed asked for"),)
    outputs = (Port("ref", "rad/s", "speed reference"), Port("accel", "rad/s2", "its rate of change"))
    params = (
        Param("shape", "", "slew", "step, slew or s-curve", choices=SHAPES),
        Param("slew", "rad/s2", 1000.0, "most acceleration of the reference", 1e-6, MOST),
        Param("jerk", "rad/s3", 1e5, "most rate of change of that acceleration (S-curve)", 1e-6, MOST),
    )

    def setup(self) -> None:
        self._shaped = Shaped(self.p["shape"], self.p["slew"], self.p["jerk"], self.ctx.ts)

    def reset(self) -> None:
        self._shaped.start()

    def warm(self, settled: dict[str, float]) -> None:
        self._shaped.start(settled.get("omega_m", 0.0))

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        return self._shaped.toward(inputs[0]), self._shaped.slope


@register
class SpeedPi(Block):
    kind = "speed_pi"
    role = "outer_regulator"
    title = "Speed regulator (PI)"
    summary = (
        "A PI asks the torque that closes the speed error, held to a limit with anti-windup; tuned a decade "
        "below the current loop."
    )
    definition = (
        "Asks the torque that closes the speed error: proportional and integral, held to a torque limit, the "
        "integral stopped while the limit holds (anti-windup). Tuned by symmetric optimum, a decade below "
        "the current loop. Where the loop is not closed through it (an open-loop start, which wires its "
        "`open` output here), the integral is held where it stands: a regulator whose torque nothing "
        "follows would otherwise integrate the whole run-up and overshoot when the loop is closed."
    )
    math = (
        r"e = \omega^* - \omega",
        r"T^* = \mathrm{sat}\!\left(K_p\,e + K_i\!\int e\,dt\right)",
        r"C(z) = K_p + K_i T_s \frac{z}{z-1}",
        r"\int e\,dt\ \text{held while the loop is open}",
    )
    inputs = (
        Port("ref", "rad/s", "speed reference"),
        Port("speed", "rad/s", "speed as sensed"),
        Port("open", "", "above nought while the loop is not closed through this regulator", optional=True),
    )
    outputs = (
        Port("torque", "N·m", "torque asked for"),
        Port("error", "rad/s", "speed error"),
        Port("prop", "N·m", "the proportional part: Kp·e"),
        Port("int", "N·m", "the integral part: Ki·∫e"),
        Port("limited", "", "1 while the torque limit holds"),
    )
    params = (
        Param("kp", "N·m·s/rad", 0.1, "proportional gain", 0.0, MOST),
        Param("ki", "N·m/rad", 1.0, "integral gain", 0.0, MOST),
        Param("limit", "N·m", MOST, "most torque asked for, either way", 0.0, MOST),
        Param("anti_windup", "", True, "stop the integral while the limit holds"),
    )
    linear = True
    loop = "speed"

    def reset(self) -> None:
        self._sum = 0.0

    def warm(self, settled: dict[str, float]) -> None:
        self._sum = settled.get("torque", 0.0)

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        ref, speed, not_closed = inputs
        error = ref - speed
        gained = 0.0 if not_closed > 0.0 else self.p["ki"] * self.ctx.ts * error
        asked = self.p["kp"] * error + self._sum + gained
        limit = self.p["limit"]
        held = min(max(asked, -limit), limit)
        # While the limit holds, the integral only moves if that brings the output back.
        if not (self.p["anti_windup"] and held != asked and gained * asked > 0):
            self._sum += gained
        return held, error, self.p["kp"] * error, self._sum, float(held != asked)

    def transfer(self, axis: str = "q") -> tuple[list[float], list[float]] | None:
        return [self.p["kp"] + self.p["ki"] * self.ctx.ts, -self.p["kp"]], [1.0, -1.0]


def eso_gains(bandwidth_hz: float, observer: float, inertia: float, ts: float) -> tuple[float, float, float, float]:
    """The gains of a linear active-disturbance-rejection speed loop, by bandwidth: the control
    law's kp = ωc, the extended state observer's two gains placing both of its poles at
    z = e^(−ωo·Ts), ωo = observer·ωc, exactly for the sampled model (no Euler error), and b0 = 1/J.

    The model is J·dω/dt = T − T_load: one integrator, with all that is not the torque asked
    (the load, friction, an inertia that is not J, a torque the current loop does not make)
    lumped as one disturbance the observer tracks as a second state."""
    wc = 2.0 * math.pi * bandwidth_hz
    beta = math.exp(-observer * wc * ts)
    return wc, 2.0 - 2.0 * beta, (1.0 - beta) ** 2 / ts, 1.0 / inertia


@register
class SpeedAdrc(Block):
    kind = "speed_adrc"
    role = "outer_regulator"
    title = "Speed regulator (active disturbance rejection)"
    summary = (
        "An observer estimates the speed and everything that is not the torque asked (load, friction, an "
        "inertia that is not the one assumed) and the torque cancels it; one knob, the bandwidth."
    )
    definition = (
        "Linear active disturbance rejection (LADRC). The shaft is taken as one integrator, J·dω/dt = T − "
        "T_load, and an extended state observer tracks the speed and, as a second state, the lumped "
        "disturbance: whatever makes the shaft move other than the torque asked. The torque asked cancels "
        "the estimate and closes a proportional loop at the bandwidth ωc. The observer's two poles sit at "
        "z = e^(−ωo·Ts), ωo a few times ωc, placed exactly for the sampled model. The observer is fed the "
        "torque as limited, so nothing winds up while the limit holds. A load step is rejected at the "
        "observer's rate, not the integral's, which is what it is chosen for; the price is noise through "
        "the observer's higher gain and a reliance on the inertia figure b0 = 1/J within a factor of about "
        "two."
    )
    math = (
        r"\hat\omega_{k+1} = \hat\omega_k + T_s(\hat f_k + b_0 u_k) + l_1(\omega_k - \hat\omega_k)",
        r"\hat f_{k+1} = \hat f_k + l_2(\omega_k - \hat\omega_k)",
        r"u_k = \mathrm{sat}\!\left(\frac{\omega_c(\omega^*_k - \hat\omega_k) - \hat f_k}{b_0}\right),\ b_0 = 1/J",
        r"l_1 = 2 - 2\beta,\ l_2 = (1-\beta)^2/T_s,\ \beta = e^{-\omega_o T_s}",
    )
    inputs = (
        Port("ref", "rad/s", "speed reference"),
        Port("speed", "rad/s", "speed as sensed"),
        Port("open", "", "above nought while the loop is not closed through this regulator", optional=True),
    )
    outputs = (
        Port("torque", "N·m", "torque asked for"),
        Port("error", "rad/s", "speed error"),
        Port("disturbance", "N·m", "the torque the observer finds acting against the one asked: −f̂/b0"),
        Port("estimate", "rad/s", "the observer's speed"),
        Port("limited", "", "1 while the torque limit holds"),
    )
    params = (
        Param("bandwidth", "Hz", 10.0, "the speed loop's bandwidth, ωc/2π", 0.01, 1e5),
        Param("observer", "", 5.0, "the observer's bandwidth as a multiple of the loop's", 1.0, 50.0),
        Param("inertia", "kg·m²", 1e-3, "the inertia the loop assumes, J (b0 = 1/J)", 1e-12, MOST),
        Param("limit", "N·m", MOST, "most torque asked for, either way", 0.0, MOST),
    )
    linear = True
    loop = "speed"

    def _gains(self) -> tuple[float, float, float, float]:
        return eso_gains(self.p["bandwidth"], self.p["observer"], self.p["inertia"], self.ctx.ts)

    def reset(self) -> None:
        # Kept as a single-precision controller keeps them: the disturbance as a torque,
        # d = −f̂/b0 (N·m, not the large b0·T), and the observer's speed as its offset from the
        # last speed read, δ = ω̂ − ω[k−1] (small), so that the one large subtraction is of two
        # close readings, which a float takes exactly. The same law as the equations say.
        self._lead = self._d = self._last = 0.0
        self._started = False

    def warm(self, settled: dict[str, float]) -> None:
        self._last, self._lead = settled.get("omega_m", 0.0), 0.0
        self._d = settled.get("torque", 0.0)
        self._started = True

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        ref, speed, not_closed = inputs
        wc, l1, l2, _ = self._gains()
        j = self.p["inertia"]
        if not self._started:
            self._last, self._lead, self._started = speed, 0.0, True
        seen = (speed - self._last) - self._lead  # ω − ω̂
        d = self._d
        asked = j * wc * ((ref - speed) + seen) + d
        limit = self.p["limit"]
        held = min(max(asked, -limit), limit)
        if not_closed > 0.0:
            # Nothing follows this torque: the observer is held to the speed and the disturbance kept.
            self._lead = 0.0
        else:
            self._lead = self.ctx.ts * (held - d) / j - (1.0 - l1) * seen
            self._d = d - j * l2 * seen
        self._last = speed
        return held, ref - speed, d, speed - seen, float(held != asked)

    def transfer(self, axis: str = "q") -> tuple[list[float], list[float]] | None:
        """The feedback from the speed to the torque, with the reference at nought, as an
        error-driven C(z): what the loop's margins and poles are read from."""
        wc, l1, l2, b0 = self._gains()
        ts = self.ctx.ts
        k0, k1 = wc / b0, 1.0 / b0
        # x̂ ← (A − B·K − L·C)·x̂ + L·y,  u = −K·x̂,  A = [[1, Ts], [0, 1]], B = [b0·Ts, 0].
        m11, m12 = 1.0 - ts * b0 * k0 - l1, ts - ts * b0 * k1
        m21, m22 = -l2, 1.0
        num = [k0 * l1 + k1 * l2, -m22 * k0 * l1 + m12 * k0 * l2 + m21 * k1 * l1 - m11 * k1 * l2]
        return num, [1.0, -(m11 + m22), m11 * m22 - m12 * m21]

    def reference_transfer(self) -> tuple[list[float], list[float]]:
        """The path from the speed reference to the torque, with the speed at nought: the
        reference enters as J·ωc·r and through the observer, which is fed the torque asked, so
        it does not pass through C(z). u = k0·r − K·x̂ and x̂ ← M·x̂ + B·k0·r give
        Cr(z) = k0·(1 − K·(zI − M)⁻¹·B), over the same denominator as C(z)."""
        wc, l1, l2, b0 = self._gains()
        ts = self.ctx.ts
        k0, k1 = wc / b0, 1.0 / b0
        m11, m12 = 1.0 - ts * b0 * k0 - l1, ts - ts * b0 * k1
        m21, m22 = -l2, 1.0
        det = [1.0, -(m11 + m22), m11 * m22 - m12 * m21]
        # K·adj(zI − M)·B = b0·Ts·(k0·(z − m22) + k1·m21)
        num = [k0 * det[0], k0 * (det[1] - b0 * ts * k0), k0 * (det[2] + b0 * ts * (k0 * m22 - k1 * m21))]
        return num, det


def notch_coefficients(f0: float, width: float, depth: float, ts: float) -> tuple[list[float], list[float]]:
    """The notch's difference equation, b and a with a0 = 1: the continuous notch
    (s² + 2·depth·width·ω0·s + ω0²)/(s² + 2·width·ω0·s + ω0²) by the bilinear transform with its
    centre prewarped, so that the discrete notch is deepest at f0 exactly. Unity (b = a = [1]) at
    f0 = 0, or at or above the half-sampling frequency, where there is nothing it can take out."""
    if f0 <= 0.0 or f0 * ts >= 0.5:
        return [1.0, 0.0, 0.0], [1.0, 0.0, 0.0]
    w0 = 2.0 * math.pi * f0
    k = w0 / math.tan(0.5 * w0 * ts)
    zeta_z, zeta_p = depth * width, width
    a0 = k * k + 2.0 * zeta_p * w0 * k + w0 * w0
    b = [
        (k * k + 2.0 * zeta_z * w0 * k + w0 * w0) / a0,
        2.0 * (w0 * w0 - k * k) / a0,
        (k * k - 2.0 * zeta_z * w0 * k + w0 * w0) / a0,
    ]
    a = [1.0, 2.0 * (w0 * w0 - k * k) / a0, (k * k - 2.0 * zeta_p * w0 * k + w0 * w0) / a0]
    return b, a


@register
class TorqueNotch(Block):
    kind = "torque_notch"
    role = "reference"
    title = "Notch on the torque asked (a flexible shaft's resonance)"
    summary = "Takes out of the torque asked the frequency the shaft between motor and load swings at, so the loop no longer rings it."
    definition = (
        "Where the shaft between the motor and its load twists (a robot joint's gear, a long coupling, a belt), "
        "motor and load swing against each other at the shaft's resonance, and a speed loop fast enough to be "
        "useful feeds that swing through the torque it asks. This block is a notch on that torque: it passes "
        "every frequency but a band about the resonance, which it takes down to a share (the depth). It is "
        "the bilinear transform of the continuous notch with its centre prewarped, so the discrete notch is "
        "deepest at the frequency set, and it passes a steady torque unchanged. Its centre is the resonance as "
        "the engineer measured it (a frequency sweep, the gear's datasheet): where the request gives the "
        "shaft's resonance and the notch has none set, it is taken from there and said. A notch costs phase "
        "below its centre, which the speed loop's margin pays."
    )
    math = (
        r"N(s) = \frac{s^2 + 2 d\,\zeta\,\omega_0 s + \omega_0^2}{s^2 + 2\zeta\,\omega_0 s + \omega_0^2},\quad "
        r"s \leftarrow \frac{\omega_0}{\tan(\omega_0 T_s/2)}\,\frac{z-1}{z+1}",
        r"y_k = b_0 x_k + b_1 x_{k-1} + b_2 x_{k-2} - a_1 y_{k-1} - a_2 y_{k-2}",
    )
    inputs = (Port("torque", "N·m", "torque asked"),)
    outputs = (Port("torque", "N·m", "torque passed on, the resonance taken out"),)
    params = (
        Param(
            "frequency",
            "Hz",
            0.0,
            "the notch's centre, the shaft's resonance (0: the resonance set for the motor and load is taken; with none set, the torque passes)",
            0.0,
            MOST,
        ),
        Param("width", "", 0.5, "the notch's width, as the damping ratio of its poles", 0.01, 5.0),
        Param("depth", "", 0.05, "what is left at the centre, as a share", 0.0, 1.0),
    )
    linear = True

    def setup(self) -> None:
        self._b, self._a = notch_coefficients(self.p["frequency"], self.p["width"], self.p["depth"], self.ctx.ts)

    def reset(self) -> None:
        self._x1 = self._x2 = self._y1 = self._y2 = 0.0

    def warm(self, settled: dict[str, float]) -> None:
        # A steady torque passes unchanged: the notch starts as if it had always been asked it.
        torque = settled.get("torque", 0.0)
        self._x1 = self._x2 = self._y1 = self._y2 = torque

    def transfer(self, axis: str = "q") -> tuple[list[float], list[float]] | None:
        return list(self._b), list(self._a)

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        (x,) = inputs
        b, a = self._b, self._a
        y = b[0] * x + b[1] * self._x1 + b[2] * self._x2 - a[1] * self._y1 - a[2] * self._y2
        self._x2, self._x1, self._y2, self._y1 = self._x1, x, self._y1, y
        return (y,)


SHAPERS = ("zv", "zvd")


def shaper_impulses(shape: str, frequency: float, damping: float) -> list[tuple[float, float]]:
    """The impulses of a zero-vibration shaper, (amplitude, s after the first), for a mode of
    `frequency` Hz damped `damping`: ZV two, half a damped period apart; ZVD three, the third a
    whole period on, which leaves little swing where the mode is off its figure as well."""
    if frequency <= 0.0 or damping >= 1.0:
        return [(1.0, 0.0)]
    root = math.sqrt(1.0 - damping * damping)
    k = math.exp(-damping * math.pi / root)
    half = 0.5 / (frequency * root)
    if shape == "zv":
        return [(1.0 / (1.0 + k), 0.0), (k / (1.0 + k), half)]
    total = (1.0 + k) ** 2
    return [(1.0 / total, 0.0), (2.0 * k / total, half), (k * k / total, 2.0 * half)]


@register
class InputShaper(Block):
    kind = "input_shaper"
    role = "reference"
    title = "Input shaper on the move asked (a flexible load)"
    summary = "Gives the move asked in two or three parts, timed so that the swing the first starts in the load the last stops."
    definition = (
        "Where the load swings on what holds it (a robot arm on its gear, a long belt, a crane's rope), a move "
        "that ends sets it swinging, and the swing lasts long after the motor has stopped. The shaper takes "
        "the move asked and gives it as the sum of copies of itself, each scaled and delayed: two half a period "
        "of the swing apart (zero vibration, ZV), or three (ZV and derivative, ZVD), timed and weighted so that "
        "the swing each copy starts is cancelled by the next. The move arrives unchanged, half a period later "
        "(ZV) or a whole period later (ZVD); ZVD also cancels most of a swing whose frequency is off its figure "
        "by a sixth. Nothing in the loop changes: its margins are the loop's own. The mode it is set for is the "
        "one the loop rings the load at, which is neither the shaft's free resonance nor fixed: with the "
        "frequency left at nought it is taken from the speed loop's own least damped closed-loop poles, with "
        "the shaft that twists, and said."
    )
    math = (
        r"y(t) = \sum_i A_i\,x(t - t_i),\quad K = e^{-\zeta\pi/\sqrt{1-\zeta^2}},\quad "
        r"T_d = \frac{1}{f\sqrt{1-\zeta^2}}",
        r"\text{ZV: } A = \tfrac{1}{1+K}\,[1,\ K],\ t = [0,\ T_d/2];\quad "
        r"\text{ZVD: } A = \tfrac{1}{(1+K)^2}\,[1,\ 2K,\ K^2],\ t = [0,\ T_d/2,\ T_d]",
    )
    inputs = (Port("ref", "rad/s", "speed asked"),)
    outputs = (Port("ref", "rad/s", "speed asked, shaped"),)
    params = (
        Param(
            "shape",
            "",
            "zvd",
            "zv: two impulses, least delay; zvd: three, robust to a mode off its figure",
            choices=SHAPERS,
        ),
        Param(
            "frequency",
            "Hz",
            0.0,
            "the mode to leave still (0: the least damped mode of the speed loop with its shaft is taken; with no shaft that twists, the move passes)",
            0.0,
            MOST,
        ),
        Param("damping", "", 0.0, "the mode's damping ratio", 0.0, 0.99),
    )

    def setup(self) -> None:
        nyquist = 0.5 / self.ctx.ts
        f = self.p["frequency"] if self.p["frequency"] < nyquist else 0.0
        self._taps = [(a, round(t / self.ctx.ts)) for a, t in shaper_impulses(self.p["shape"], f, self.p["damping"])]
        self._size = self._taps[-1][1] + 1

    def reset(self) -> None:
        self._start(0.0)

    def warm(self, settled: dict[str, float]) -> None:
        # A steady move passes unchanged: the shaper starts as if it had always been asked it.
        self._start(settled.get("ref", settled.get("omega_m", 0.0)))

    def _start(self, value: float) -> None:
        self._past = [value] * self._size
        self._at = 0

    def transfer(self, axis: str = "q") -> tuple[list[float], list[float]] | None:
        b = [0.0] * self._size
        for a, k in self._taps:
            b[k] += a
        return b, [1.0]

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        (x,) = inputs
        self._at = (self._at + 1) % self._size
        self._past[self._at] = x
        size, at, past = self._size, self._at, self._past
        return (sum(a * past[(at - k) % size] for a, k in self._taps),)


TURN = 2**32  # counts of a whole turn in a 32-bit angle


@register
class PeriodicCompensation(Block):
    kind = "periodic_compensation"
    role = "reference"
    title = "Torque learned over the turn (periodic compensation)"
    summary = (
        "Learns, turn by turn, the torque a load asks again at the same angle every turn (a compressor's "
        "gas torque) and gives it ahead, so the speed loop no longer chases it and the shaft runs smooth."
    )
    definition = (
        "A rotary compressor asks a torque that rises and falls with the angle of its shaft, the same every "
        "turn: a speed loop that only answers the error it sees lets the shaft slow and speed up through each "
        "turn, which shakes the compressor and its pipes. This block reads the load's torque from the shaft "
        "itself, the torque given less the inertia times the acceleration, and learns its first few harmonics "
        "in the angle of the turn, not in time, so that what it learns holds as the speed changes: at each "
        "instant each harmonic's coefficient moves a little toward the one the last turn showed (the load's "
        "mean is learned beside them, and not given, so that it cannot leak into them). What it "
        "has learned is added to the torque the speed regulator asks, ahead of any error. Read from the "
        "shaft and not from the regulator, what is learned is in step with the angle whatever the speed "
        "loop's own lag at the turn's frequency (learning from the regulator's torque, lagging by more than "
        "a quarter of a turn, feeds the swing it should cancel). The same holds of the speed sensed: a "
        "harmonic above what the sensing follows (an observer's phase-locked loop) is read late, and "
        "learning it would feed it; so at each instant only the harmonics within the reach are learned and "
        "given, which holds at any speed, not only at the design one. It leans on the inertia figure: one "
        "that is off leaves part of the acceleration counted as load."
    )
    math = (
        r"\hat T_L = T^*_{k-1} - J\,\frac{\omega_k - \omega_{k-1}}{T_s}",
        r"e = \hat T_L - \tilde T - m,\quad m \mathrel{+}= \gamma\,\frac{|\omega| T_s}{2\pi}\,e",
        r"a_n \mathrel{+}= \gamma\,\frac{|\omega| T_s}{\pi}\,e\cos n\theta,\quad "
        r"b_n \mathrel{+}= \gamma\,\frac{|\omega| T_s}{\pi}\,e\sin n\theta",
        r"\tilde T = \sum_{n=1}^{N} a_n\cos n\theta + b_n \sin n\theta,\quad T^* = T^*_{reg} + \tilde T",
    )
    inputs = (
        Port("torque", "N·m", "torque the speed regulator asks"),
        Port("speed", "rad/s", "speed as sensed"),
    )
    outputs = (
        Port("torque_out", "N·m", "torque asked, with what was learned added"),
        Port("learned", "N·m", "what was learned, at this angle"),
        Port("angle", "rad", "the shaft's angle in its turn"),
    )
    params = (
        Param("harmonics", "", 2.0, "how many harmonics of the turn are learned", 1.0, 12.0),
        Param("gain", "", 0.2, "the share of a turn's harmonic learned in one turn", 0.0, 1.0),
        Param("inertia", "kg·m²", 1e-3, "the inertia the load's torque is read with", 1e-12, MOST),
        Param(
            "reach",
            "Hz",
            100.0,
            "the highest harmonic frequency learned: within what the speed sensing follows",
            0.1,
            MOST,
        ),
        Param("floor", "rad/s", 10.0, "below this speed nothing is learned", 0.0, MOST),
    )

    def reset(self) -> None:
        n = int(self.p["harmonics"])
        self._a, self._b = [0.0] * n, [0.0] * n
        self._mean = 0.0  # the load's mean, learned with the harmonics so that it does not leak into them
        # The angle as a fraction of a turn in 32 bits, as a drive's processor keeps one: it wraps
        # by itself and never drifts, in single precision as in double.
        self._turn = 0
        self._last: tuple[float, float] | None = None  # the torque asked and the speed, an instant ago

    def _at(self, angle: float, within: int) -> float:
        return sum(
            self._a[k] * math.cos((k + 1) * angle) + self._b[k] * math.sin((k + 1) * angle) for k in range(within)
        )

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        torque, speed = inputs
        ts = self.ctx.ts
        signed = self._turn - TURN if self._turn >= TURN // 2 else self._turn
        angle = signed * (2.0 * math.pi / TURN)
        # The harmonics whose frequency at this speed the sensing still follows.
        turn = abs(speed) / (2.0 * math.pi)
        within = min(len(self._a), int(self.p["reach"] // turn) if turn > 0 else len(self._a))
        if self._last is not None and abs(speed) >= self.p["floor"]:
            asked, before = self._last
            # The load's torque over the last instant, read at its middle, against what is learned there.
            middle = math.remainder(angle - 0.5 * speed * ts, 2.0 * math.pi)
            seen = asked - self.p["inertia"] * (speed - before) / ts - self._at(middle, within) - self._mean
            rate = self.p["gain"] * abs(speed) * ts / math.pi
            self._mean += 0.5 * rate * seen
            for k in range(within):
                self._a[k] += rate * seen * math.cos((k + 1) * middle)
                self._b[k] += rate * seen * math.sin((k + 1) * middle)
        learned = self._at(angle, within)
        out = torque + learned
        self._last = (out, speed)
        self._turn = (self._turn + round(speed * ts * (TURN / (2.0 * math.pi)))) % TURN
        return out, learned, angle


@register
class TorqueShaper(Block):
    kind = "torque_shaper"
    role = "reference"
    title = "Torque limit and shaping"
    summary = (
        "Holds the torque asked for to the current limit, reached at once, at a limited rate, or along an S-curve."
    )
    definition = (
        "Holds the torque asked for to the limit the drive's current allows, and shapes how it gets there: at "
        "once (a hard limit), at a limited rate, or along an S-curve."
    )
    math = (
        r"|T^*| \le T_{max}",
        r"\left|\frac{dT^*}{dt}\right| \le r_{max}\ \text{(slew, S-curve)}",
    )
    inputs = (Port("torque", "N·m", "torque asked for"),)
    outputs = (Port("torque", "N·m", "torque passed on"), Port("limited", "", "1 while the torque limit holds"))
    params = (
        Param("shape", "", "step", "step (hard limit), slew or s-curve", choices=SHAPES),
        Param("limit", "N·m", MOST, "most torque passed on, either way", 0.0, MOST),
        Param("rate", "N·m/s", 1000.0, "most rate of change of the torque", 1e-9, MOST),
        Param("jerk", "N·m/s2", 1e6, "most rate of change of that rate (S-curve)", 1e-9, MOST),
    )

    def setup(self) -> None:
        self._shaped = Shaped(self.p["shape"], self.p["rate"], self.p["jerk"], self.ctx.ts)

    def reset(self) -> None:
        self._shaped.start()

    def warm(self, settled: dict[str, float]) -> None:
        self._shaped.start(settled.get("torque", 0.0))

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        limit = self.p["limit"]
        return self._shaped.toward(min(max(inputs[0], -limit), limit)), float(abs(inputs[0]) > limit)


@register
class CurrentReference(Block):
    kind = "current_reference"
    role = "reference_generator"
    title = "Torque to current reference"
    summary = (
        "Turns the torque asked for into d- and q-axis currents: least current (with field weakening), d held"
        " at nought, or least total loss. Held to the drive's current limit."
    )
    definition = (
        "The d- and q-axis currents that make the torque: the pair of least current, and field weakening "
        "where the voltage runs out, both worked out by the same solver the loss engine settles its "
        "currents with; or the d-axis current held at nought; or the pair of least total loss, the "
        "motor's copper and iron and the inverter together, which leaves the least-current pair toward "
        "more negative d-axis current as the speed rises and the torque falls (it needs the motor's iron "
        "loss; without one it is the least-current pair). Held to the drive's current limit, which a "
        "supervisor's factor (`derate`) can fold back."
    )
    math = (
        r"T = \tfrac32\,p\,\left(\psi\,i_q + (L_d - L_q)\,i_d\,i_q\right)",
        r"\min\ i_d^2 + i_q^2 \quad \text{(least current)}",
        r"v_d^2 + v_q^2 \le \left(k\,m_{max}\,\tfrac{V_{dc}}{2}\right)^2 \quad \text{(field weakening)}",
        r"\min\ \tfrac32 R\,(i_d^2 + i_q^2) + P_{fe}(n)\,\frac{(\psi + L_d i_d)^2 + (L_q i_q)^2}{\psi^2} + "
        r"P_{inv}\!\left(\sqrt{i_d^2 + i_q^2}\right) \quad \text{(least loss)}",
    )
    inputs = (
        Port("torque", "N·m", "torque asked for"),
        Port("omega_m", "rad/s", "shaft speed as sensed"),
        Port("v_dc", "V", "DC voltage"),
        Port("derate", "", "factor on the current limit from a supervisor; open or nought: 1", optional=True),
    )
    outputs = (
        Port("i_d", "A", "d-axis current reference"),
        Port("i_q", "A", "q-axis current reference"),
        Port("limited", "", "1 while the current limit holds the reference short of the torque asked for"),
    )
    params = (
        Param(
            "strategy",
            "",
            "mtpa_fw",
            "least current with field weakening, id = 0, or least total loss",
            choices=("mtpa_fw", "id_zero", "least_loss"),
        ),
        Param("i_limit", "A", MOST, "most current asked for, peak", 0.0, MOST),
        Param("voltage_share", "", 1.0, "share of the modulation's linear range field weakening keeps to", 0.1, 1.0),
        Param(
            "torque_grid",
            "N·m",
            0.0,
            "grid of torque the solver is read between while moving; 0: asked at every value",
            0.0,
            MOST,
        ),
        Param(
            "speed_grid",
            "rad/s",
            0.0,
            "grid of speed the solver is read between while moving; 0: asked at every value",
            0.0,
            MOST,
        ),
    )

    def setup(self) -> None:
        c = self.ctx
        self._motor = pmsm.Motor(pole_pairs=c.pole_pairs, flux_linkage=c.psi, ld=c.ld, lq=c.lq, rs=c.rs)
        self._plain = self.p["strategy"] == "id_zero"
        self._least = self.p["strategy"] == "least_loss" and c.iron is not None
        # Volts of phase voltage, peak, for each volt of DC voltage, that field weakening keeps to.
        self._reach = float(self.p["voltage_share"] * c.pwm.max_modulation_index * 0.5)

    def reset(self) -> None:
        self._nodes: dict[tuple[int, int, float], tuple[float, float]] = {}
        self._last: tuple[tuple[float, float, float], tuple[float, float]] | None = None
        self._seen: tuple[float, float, float] | None = None

    def _solved(self, torque: float, omega_m: float, v_max: float) -> tuple[float, float]:
        """The engine's settled currents for a torque and speed within a voltage. Where the
        voltage cannot give the torque at all, the most torque it can give is found."""
        rpm = omega_m * 30.0 / math.pi
        too_much = None
        for _ in range(12):
            try:
                found = pmsm.operating_state(self._motor, rpm, torque, v_max)
            except Unreachable:
                too_much, torque = torque, torque * 0.5
                continue
            if too_much is not None:
                # Halved past the edge: the most the voltage gives lies between the two,
                # found to a few parts in a thousand, not left at as little as half of it.
                low, high = torque, too_much
                for _ in range(8):
                    middle = 0.5 * (low + high)
                    try:
                        found, low = pmsm.operating_state(self._motor, rpm, middle, v_max), middle
                    except Unreachable:
                        high = middle
                torque = low
            pair = float(found.i_d), float(found.i_q)
            if self._least:
                return least_loss(self.ctx, torque, omega_m, v_max, self.p["i_limit"], pair)
            return pair
        # Not even nought fits: the magnet is opposed as far as it can be.
        return -0.999 * self._motor.flux_linkage / self._motor.ld, 0.0

    def _node(self, k: int, n: int, v_max: float) -> tuple[float, float]:
        key = (k, n, v_max)
        found = self._nodes.get(key)
        if found is None:
            if len(self._nodes) > 8192:
                self._nodes.clear()
            found = self._nodes[key] = self._solved(k * self.p["torque_grid"], n * self.p["speed_grid"], v_max)
        return found

    def _between(self, torque: float, omega_m: float, v_max: float) -> tuple[float, float]:
        """Read between the solver's answers at the four corners of the grid around the point."""
        x, y = torque / self.p["torque_grid"], omega_m / self.p["speed_grid"]
        k, n = math.floor(x), math.floor(y)
        fx, fy = x - k, y - n
        out = [0.0, 0.0]
        for dk, dn, share in (
            (0, 0, (1 - fx) * (1 - fy)),
            (1, 0, fx * (1 - fy)),
            (0, 1, (1 - fx) * fy),
            (1, 1, fx * fy),
        ):
            if share:
                i_d, i_q = self._node(k + dk, n + dn, v_max)
                out[0] += share * i_d
                out[1] += share * i_q
        return out[0], out[1]

    def _asked(self, torque: float, omega_m: float, v_max: float) -> tuple[float, float]:
        """The solver's currents: its own answer for a point that stands, read from the grid
        for one that is moving, so that a transient does not ask the solver at every instant."""
        point = (torque, omega_m, v_max)
        if self._last is not None and self._last[0] == point:
            return self._last[1]
        if not (self.p["torque_grid"] and self.p["speed_grid"]) or self._seen == point:
            self._last = (point, self._solved(torque, omega_m, v_max))
            return self._last[1]
        self._seen = point
        return self._between(torque, omega_m, v_max)

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        torque, omega_m, v_dc = inputs[:3]
        derate = inputs[3] if len(inputs) > 3 else 0.0
        c = self.ctx
        limit = self.p["i_limit"]
        if 0.0 < derate < 1.0:
            limit *= derate
        if self._plain:
            return 0.0, min(max(torque / c.kt, -limit), limit), float(abs(torque / c.kt) > limit)
        v_max = self._reach * v_dc
        if c.ld == c.lq and not self._least:
            # With the magnets on the surface the least current is all on the q axis, and the
            # solver is only asked where the voltage would not fit.
            i_q = min(max(torque / c.kt, -limit), limit)
            w = c.pole_pairs * omega_m
            if math.hypot(w * c.lq * i_q, c.rs * i_q + w * c.psi) <= v_max:
                return 0.0, i_q, float(abs(torque / c.kt) > limit)
        i_d, i_q = self._asked(torque, omega_m, v_max)
        size = math.hypot(i_d, i_q)
        if size > limit:
            # Shortened to the limit along its own direction.
            return i_d * limit / size, i_q * limit / size, 1.0
        return i_d, i_q, 0.0


@register
class VoltageFeedbackFw(Block):
    kind = "voltage_feedback_fw"
    role = "reference_generator"
    title = "Field weakening by voltage feedback"
    summary = (
        "Watches the voltage the current regulator asks and, as it reaches the limit, takes the d-axis current "
        "further negative until it fits: field weakening that holds whatever the motor's figures really are."
    )
    definition = (
        "The current reference worked out from the motor's figures weakens the field by the model: where the "
        "magnet's flux is higher than the controller holds, the iron saturates or the inductance is not the "
        "one assumed, the voltage still runs out, the current regulator is held at its limit and the torque "
        "is lost. This block closes a loop on the voltage itself: from the size of the voltage the regulator "
        "asked at the instant before, against a share of the most the modulation gives (`headroom`, so that "
        "the regulator keeps some voltage to move the current with), an integral moves a d-axis current added "
        "to the reference, never positive, and never past the characteristic current −ψ/Ld, past which more "
        "negative d current costs torque faster than it saves voltage (the limit of maximum torque per volt "
        "for a motor without saliency, and a safe bound for one with it). The loop's gain is scaled by the "
        "speed, as the voltage a d-axis ampere saves is ωe·Ld, so that it answers at its bandwidth at every "
        "speed. The q-axis current is then held so that the whole stays within the current limit."
    )
    math = (
        r"e = \frac{\sqrt{v_d^2 + v_q^2}}{V_{max}} - h,\quad V_{max} = m_{max}\,\tfrac{V_{dc}}{2}",
        r"\Delta i_{d,k+1} = \mathrm{clip}\!\left(\Delta i_{d,k} - \omega_{fw}\,T_s\,\frac{V_{max}}{|\omega_e|\,L_d}\,e,"
        r"\ -\tfrac{\psi}{L_d} - i_d^*,\ 0\right)",
        r"i_d = i_d^* + \Delta i_d,\quad |i_q| \le \sqrt{I_{max}^2 - i_d^2}",
    )
    inputs = (
        Port("i_d", "A", "d-axis current reference, from the model"),
        Port("i_q", "A", "q-axis current reference, from the model"),
        Port("v_d", "V", "d-axis voltage the current regulator asked, at the instant before"),
        Port("v_q", "V", "q-axis voltage the current regulator asked, at the instant before"),
        Port("v_dc", "V", "DC voltage"),
        Port("omega_e", "rad/s", "electrical speed"),
    )
    outputs = (
        Port("i_d_out", "A", "d-axis current reference, weakened as the voltage asks"),
        Port("i_q_out", "A", "q-axis current reference, within the current limit"),
        Port("delta", "A", "the d-axis current added by the loop"),
        Port("limited", "", "1 while the current limit or the characteristic current holds"),
    )
    params = (
        Param("headroom", "", 0.95, "share of the most voltage the loop keeps the regulator to", 0.5, 1.0),
        Param("bandwidth", "Hz", 50.0, "how fast the loop answers, ωfw/2π", 0.1, 1e5),
        Param("i_limit", "A", MOST, "most current, peak", 0.0, MOST),
    )

    def setup(self) -> None:
        c = self.ctx
        self._reach = float(c.pwm.max_modulation_index * 0.5)
        self._floor = -c.psi / c.ld

    def reset(self) -> None:
        self._delta = 0.0

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        i_d, i_q, v_d, v_q, v_dc, omega_e = inputs
        c = self.ctx
        v_max = self._reach * v_dc
        excess = math.sqrt(v_d * v_d + v_q * v_q) / v_max - self.p["headroom"] if v_max > 0 else 0.0
        # The voltage one d-axis ampere moves at this speed; held off nought at standstill.
        per_amp = max(abs(omega_e), 2.0 * math.pi) * c.ld
        gain = 2.0 * math.pi * self.p["bandwidth"] * c.ts * v_max / per_amp
        lowest = min(self._floor - i_d, 0.0)
        moved = self._delta - gain * excess
        self._delta = min(max(moved, lowest), 0.0)
        out_d = i_d + self._delta
        limit = self.p["i_limit"]
        out_d = max(out_d, -limit)
        room = math.sqrt(max(limit * limit - out_d * out_d, 0.0))
        out_q = min(max(i_q, -room), room)
        held = moved < lowest or out_q != i_q
        return out_d, out_q, self._delta, float(held)


@register
class CurrentPi(Block):
    kind = "current_pi_dq"
    role = "inner_regulator"
    title = "Current regulator (PI, rotor frame)"
    summary = "A PI per axis asks the voltages that close the d and q current errors, coupling fed forward."
    definition = (
        "Asks the d- and q-axis voltages that close the current errors: a PI on each axis, with the "
        "cross-coupling between the axes and the back-EMF fed forward (each can be switched off), held inside "
        "the circle of voltage the modulation reaches. While it holds, each integral stops integrating the "
        "error and follows the resistive drop of its current instead (what it holds on the linear answer, "
        "where the regulator's zero cancels the winding's pole), so that the current comes out of the limit "
        "on the loop's own answer and not on the winding's slow L/R. Tuned by cancelling the winding's pole: "
        "Kp = ωc·L and Ki = ωc·R, with ωc the bandwidth asked for."
    )
    math = (
        r"v_d^* = K_{pd}\,e_d + K_{id}\!\int e_d\,dt - \omega_e L_q i_q",
        r"v_q^* = K_{pq}\,e_q + K_{iq}\!\int e_q\,dt + \omega_e L_d i_d + \omega_e \psi",
        r"\sqrt{v_d^2 + v_q^2} \le k\,m_{max}\,\tfrac{V_{dc}}{2}",
        r"C(z) = K_p + K_i T_s \frac{z}{z-1}",
    )
    inputs = (
        Port("id_ref", "A", "d-axis current reference"),
        Port("iq_ref", "A", "q-axis current reference"),
        Port("i_d", "A", "d-axis current as measured"),
        Port("i_q", "A", "q-axis current as measured"),
        Port("omega_e", "rad/s", "electrical speed"),
        Port("v_dc", "V", "DC voltage"),
    )
    outputs = (
        Port("v_d", "V", "d-axis voltage asked for"),
        Port("v_q", "V", "q-axis voltage asked for"),
        Port("err_d", "A", "d-axis current error"),
        Port("err_q", "A", "q-axis current error"),
        Port("limited", "", "1 while the voltage limit holds"),
        Port("prop_d", "V", "d axis, the proportional part: Kp·e"),
        Port("prop_q", "V", "q axis, the proportional part"),
        Port("int_d", "V", "d axis, the integral part: Ki·∫e"),
        Port("int_q", "V", "q axis, the integral part"),
        Port("ff_d", "V", "d axis, what is fed forward: the cross-coupling"),
        Port("ff_q", "V", "q axis, what is fed forward: the cross-coupling and the back-EMF"),
    )
    params = (
        Param("kp_d", "V/A", 1.0, "proportional gain, d axis", 0.0, MOST),
        Param("ki_d", "V/(A·s)", 100.0, "integral gain, d axis", 0.0, MOST),
        Param("kp_q", "V/A", 1.0, "proportional gain, q axis", 0.0, MOST),
        Param("ki_q", "V/(A·s)", 100.0, "integral gain, q axis", 0.0, MOST),
        Param("decoupling", "", True, "feed the cross-coupling between the axes forward"),
        Param("bemf_feedforward", "", True, "feed the back-EMF forward"),
        Param(
            "anti_windup",
            "",
            True,
            "while the voltage limit holds, the integrals stop integrating and follow the resistive drop",
        ),
        Param("voltage_share", "", 1.0, "share of the modulation's linear range the voltage is held to", 0.1, 1.5),
    )
    linear = True
    loop = "current"

    def setup(self) -> None:
        self._reach = float(self.p["voltage_share"] * self.ctx.pwm.max_modulation_index * 0.5)

    def reset(self) -> None:
        self._sum_d = self._sum_q = 0.0
        self._start: tuple[float, float] | None = None
        self._last: tuple[float, float] | None = None

    def warm(self, settled: dict[str, float]) -> None:
        if "v_d" in settled and "v_q" in settled:
            self._start = settled["v_d"], settled["v_q"]

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        id_ref, iq_ref, i_d, i_q, w, v_dc = inputs
        p, c = self.p, self.ctx
        e_d, e_q = id_ref - i_d, iq_ref - i_q
        ff_d = -w * c.lq * i_q if p["decoupling"] else 0.0
        ff_q = (w * c.ld * i_d if p["decoupling"] else 0.0) + (w * c.psi if p["bemf_feedforward"] else 0.0)
        gain_d = gain_q = 0.0
        if self._start is not None:
            # A drive already running: the integrals hold what the settled voltages need.
            self._sum_d = self._start[0] - ff_d - p["kp_d"] * e_d
            self._sum_q = self._start[1] - ff_q - p["kp_q"] * e_q
            self._start = None
        else:
            gain_d, gain_q = p["ki_d"] * c.ts * e_d, p["ki_q"] * c.ts * e_q
            self._sum_d += gain_d
            self._sum_q += gain_q
        v_d = p["kp_d"] * e_d + self._sum_d + ff_d
        v_q = p["kp_q"] * e_q + self._sum_q + ff_q
        most = self._reach * v_dc
        size = math.hypot(v_d, v_q)
        parts = (p["kp_d"] * e_d, p["kp_q"] * e_q, self._sum_d, self._sum_q, ff_d, ff_q)
        last, self._last = self._last, (i_d, i_q)
        if size <= most:
            return v_d, v_q, e_d, e_q, 0.0, *parts
        held_d, held_q = v_d * most / size, v_q * most / size
        if p["anti_windup"]:
            # What the integrals gained at this instant is taken back: they stop integrating
            # the error. On the linear answer an integral holds R·i, the resistive drop of its
            # current (with the zero on the winding's pole, Ki·∫e grows as R·di/dt does), and
            # whatever else it has found besides; while the limit holds it follows the drop of
            # the current as it moves, so that coming out of the limit the current is on the
            # loop's answer of bandwidth ωc and not left to close the rest at the winding's L/R.
            self._sum_d -= gain_d
            self._sum_q -= gain_q
            if last is not None:
                self._sum_d += c.rs * (i_d - last[0])
                self._sum_q += c.rs * (i_q - last[1])
        return held_d, held_q, e_d, e_q, 1.0, *parts

    def transfer(self, axis: str = "q") -> tuple[list[float], list[float]] | None:
        kp, ki = self.p[f"kp_{axis}"], self.p[f"ki_{axis}"]
        return [kp + ki * self.ctx.ts, -kp], [1.0, -1.0]
