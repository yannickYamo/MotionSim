"""The rotor's angle read at standstill: a high-frequency voltage injected along the estimated d
axis, the current it makes read back by differencing samples, and the magnet's polarity told
by pulses of opposite sign. What a drive with no encoder holds a load at zero speed with, and
hands over to an observer of the back-EMF once there is one to read.

A square wave of ±V on the estimated d axis, its sign changed at every sampling instant, makes
the current step by Ts·L⁻¹·v in each period. Seen from the estimated frame, an angle off the
rotor's by e = θ − θ̂ turns part of that step onto the q axis:

    Δi_q̂ = ½·V·Ts·(1/Ld − 1/Lq)·sin 2e

so a motor whose two axes differ in inductance shows its angle in the current, at any speed,
standstill included. The fundamental current hardly moves in one period: the difference of two
successive steps, divided by the difference of the voltages that made them, is the injected
signal's alone. A phase-locked loop on ½·sin 2e takes the angle and the speed.

sin 2e is the same half a turn on: the injection cannot tell the magnet's north from its south.
Where the iron saturates, a current that adds to the magnet's flux meets less inductance than
one that takes from it: one-sided pulses on the d axis, +I and back, then −I and back, step
faster on the side of the magnet. With linear iron the two are the same and the block says the
polarity could not be told.

The currents the regulators read are the mean of two successive samples, which the square wave
alternates about: the injected ripple is left out, at the cost of half a sampling period more
delay in the current loop. Above the speed where the back-EMF observer has its signal, the
angle is blended over to it and the injection stops.
"""

from __future__ import annotations

import cmath
import math
from collections import deque

from motionsim.control.blocks import Block, Param, Port, register
from motionsim.control.observers import TWO_PI, wrapped
from motionsim.errors import Refusal

SALIENCY_LEAST = 0.05  # |Lq − Ld| over the larger, the least an injected signal can read an angle from
POLARITIES = ("pulses", "none")
PATTERN = (1.0, -1.0, -1.0, 1.0)  # the pulses: 0 → +I → 0 → −I → 0
UNTOLD = 2e-3  # a difference between the two sides under this share is none
# The most the angle read may stand off the rotor's while injecting, after the block's own
# compensation of the iron's coupling: cos 20° = 0.94, the torque per ampere within 6%. Past it
# the turn grows with the current that makes it: less torque per ampere asks more current, which
# turns the angle further, and the injection loses the rotor. This tool's choice.
TURN_MOST = math.radians(20.0)
# The most the loop may lag the rotor as the current held accelerates the shaft: a loop of two
# integrators lags α/ρ², and 5° is what the observers' loops are held to. This tool's choice.
LAG_MOST = math.radians(5.0)
# The observer is handed over to only where its angle agrees with the injection's: one that has
# not yet settled from standstill would hand the regulators a wrong angle. This tool's choice.
AGREE = math.radians(15.0)


@register
class HfInjection(Block):
    kind = "hf_injection"
    role = "estimation"
    title = "High-frequency injection"
    summary = (
        "Reads the rotor's angle at standstill from the current a small injected voltage makes, where the "
        "motor's two axes differ in inductance; tells the magnet's polarity by pulses, and hands over to the "
        "back-EMF observer once the motor turns fast enough for it."
    )
    definition = (
        "A square wave of ±V on the estimated d axis, its sign changed at every sampling instant. An angle off "
        "the rotor's turns part of the current it makes onto the estimated q axis, in proportion to sin 2e and "
        "to the difference of the two axes' inductances: read by differencing successive samples, it drives a "
        "phase-locked loop. The angle it finds may be the magnet's or the opposite: after the loop locks, "
        "one-sided pulses on the d axis tell which, where the iron saturates (the side of the magnet steps "
        "faster), and the angle is turned half a turn if needed. Torque is held off until then, and kept off "
        "where the side cannot be told. While injecting, the current is held to what the loop follows within "
        "5° on the bare shaft, and to what keeps the angle read within 20° of the rotor's by the controller's "
        "usual map of the iron, its coupling compensation counted. The observer is handed over to only once "
        "its angle agrees with the injection's within 15°, the blend no faster than the loop settles. The "
        "regulators "
        "read the mean of two successive samples, without the injected ripple. Above the hand-over speed the "
        "angle is blended over to the back-EMF observer and the injection stops; it starts again below. Where "
        "the iron saturates the two axes also couple, which turns the angle read with the q current: a "
        "compensation in radians per ampere takes that back."
    )
    math = (
        r"v_{\hat d} = \pm V,\quad \Delta i_{\hat q} = \tfrac12 V T_s\left(\tfrac1{L_d} - \tfrac1{L_q}\right)\sin 2e",
        r"\varepsilon = \frac{(\Delta i_k - \Delta i_{k-1})_{\hat q}}{(u_k - u_{k-1})\,T_s\,(1/L_d - 1/L_q)},\quad "
        r"\dot{\hat\omega} = \rho^2\varepsilon,\quad \dot{\hat\theta} = \hat\omega + 2\rho\,\varepsilon",
        r"\text{polarity: } \sum_{+}|\Delta i_{\hat d}| \lessgtr \sum_{-}|\Delta i_{\hat d}|",
        r"\theta = \hat\theta - k_c\,i_{\hat q} + s\,(\theta_{emf} - \hat\theta),\quad s: 0 \to 1\ "
        r"\text{from } \omega_h \text{ to } 2\omega_h",
    )
    inputs = (
        Port("i_alpha", "A", "measured current along phase a"),
        Port("i_beta", "A", "measured current a quarter turn ahead"),
        Port("theta_emf", "rad", "the back-EMF observer's angle, handed over to at speed", optional=True),
        Port("omega_emf", "rad/s", "the back-EMF observer's electrical speed", optional=True),
        Port("theta_true", "rad", "the rotor's true angle: read for the error wire only", optional=True),
    )
    outputs = (
        Port("theta", "rad", "electrical angle the scheme is to use"),
        Port("omega_m", "rad/s", "shaft speed the scheme is to use"),
        Port("omega_e", "rad/s", "electrical speed the scheme is to use"),
        Port("current", "A", "nought: no current is imposed, the regulators take the outer loops' (for if_current)"),
        Port("mode", "", "0 while the angle is found and its polarity told, then 1"),
        Port("open", "", "1 while the angle is found and its polarity told: the speed regulator waits"),
        Port("error", "rad", "angle put out less the true one"),
        Port("i_alpha", "A", "current along phase a without the injected ripple: the regulators read it"),
        Port("i_beta", "A", "the same a quarter turn ahead"),
        Port("h_alpha", "V", "the voltage injected now, along phase a"),
        Port("h_beta", "V", "the same a quarter turn ahead"),
        Port("polarity", "", "1 the angle found was the magnet's, −1 it was turned half a turn, 0 not told"),
        Port("share", "", "the share of the angle taken from the back-EMF observer: 0 injecting, 1 handed over"),
        Port("derate", "", "the share of the current limit held to while injecting; 1 handed over"),
    )
    params = (
        Param("amplitude", "V", 1.0, "the injected square wave's voltage, peak", 0.0, 1e5),
        Param("pll_bandwidth", "Hz", 100.0, "the phase-locked loop's bandwidth ρ/2π: Kp = 2ρ, Ki = ρ²", 0.1, 1e5),
        Param("lock", "s", 0.01, "time the loop is given to lock before the polarity is told", 0.0, 10.0),
        Param("polarity", "", "pulses", "pulses to tell the magnet's polarity, or none", choices=POLARITIES),
        Param("pulse", "A", 1.0, "the current the polarity pulses reach, either way", 0.0, 1e6),
        Param("cycles", "", 20.0, "rounds of the four pulses, + and back, − and back", 1.0, 1000.0),
        Param("handover", "rad/s", 100.0, "electrical speed the blend to the back-EMF observer starts at", 0.0, 1e7),
        Param(
            "cross",
            "rad/A",
            0.0,
            "the angle the axes' coupling turns the reading by, per ampere of q current",
            -1.0,
            1.0,
        ),
    )

    def setup(self) -> None:
        c = self.ctx
        if abs(c.lq - c.ld) < SALIENCY_LEAST * max(c.ld, c.lq):
            raise Refusal(
                f"injection reads the angle from the difference between Ld and Lq, and the controller holds them "
                f"equal ({c.ld:.4g} and {c.lq:.4g} H): it would read nothing",
                "give the motor its two axis inductances, Ld and Lq, as measured at standstill",
                f"scheme.blocks.{self.name}",
            )
        rho = TWO_PI * self.p["pll_bandwidth"]
        self._kp, self._ki = 2.0 * rho, rho * rho
        self._blend = rho / 8.0  # per second: eight of the loop's time constants, as to lock
        self._gain = c.ts0 * (1.0 / c.ld - 1.0 / c.lq)  # Δi_q̂ per volt, for ½·sin 2e
        self._pulse_v = self.p["pulse"] * min(c.ld, c.lq) / c.ts0
        self._held = self._held_share()

    def _held_share(self) -> float:
        """The share of the drive's current limit held to while injecting: the least of what keeps
        the loop within LAG_MOST of a shaft that current accelerates with no load, and what
        keeps the angle read within TURN_MOST of the rotor's by the map of the iron the
        controller takes as usual for this motor, its coupling compensation counted."""
        c = self.ctx
        if not math.isfinite(c.i_limit) or c.i_limit <= 0.0:
            return 1.0
        turn = self._turn_share()
        if c.inertia <= 0.0 or c.kt <= 0.0:
            return turn
        # α = p·kt·i/J electrical, held to ρ²·LAG_MOST.
        accel = self._ki * LAG_MOST * c.inertia / (c.pole_pairs * c.kt * c.i_limit)
        return min(turn, accel)

    def _turn_share(self) -> float:
        from motionsim.control.magnetics import kind_of, usual

        c = self.ctx
        iron = usual(kind_of(c.ld, c.lq), c.ld, c.lq, c.psi, c.i_limit)
        steps = 200
        for n in range(1, steps + 1):
            i_q = c.i_limit * n / steps
            ldd, ldq, lqq = iron.inductances(0.0, i_q)
            # The axis of least inductance turns by ½·atan2(2·Ldq, Lqq − Ldd); the compensation
            # turns the angle read back by cross·i_q.
            if abs(0.5 * math.atan2(2.0 * ldq, lqq - ldd) + self.p["cross"] * i_q) > TURN_MOST:
                return (n - 1) / steps
        return 1.0

    def reset(self) -> None:
        self._theta = self._omega = 0.0
        self._i_last: complex | None = None
        self._di_last: complex | None = None
        # What was injected, the newest last: the voltage, the angle it was put along, and its
        # place among the pulses (−1: the square wave). With the delay what is worked out at
        # one instant is applied through the period after the next.
        self._sent: deque[tuple[float, float, int]] = deque([(0.0, 0.0, -1)] * 3, maxlen=3)
        self._sign = 1.0
        self._told = 0.0
        self._done = False
        self._sides = [0.0, 0.0]
        self._issued = self._measured = 0
        self._pulses = 4 * int(self.p["cycles"]) if self.p["polarity"] == "pulses" else 0
        self._over = False
        self._share = 0.0

    def warm(self, settled: dict[str, float]) -> None:
        """A drive already running: its angle found and its polarity told."""
        if "i_d" not in settled:
            return
        self._theta = settled.get("theta", 0.0)
        self._omega = self.ctx.pole_pairs * settled.get("omega_m", 0.0)
        self._done, self._told = True, 1.0
        self._over = abs(self._omega) >= 2.0 * self.p["handover"] > 0.0
        self._share = 1.0 if self._over else 0.0

    def _applied(self) -> tuple[tuple[float, float, int], tuple[float, float, int]]:
        """What was applied through the period just ended, and through the one before."""
        s = self._sent
        return (s[0], s[1]) if self.ctx.delay else (s[1], s[2])

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        c = self.ctx
        i = complex(inputs[0], inputs[1])
        theta_emf, omega_emf, theta_true = inputs[2], inputs[3], inputs[4]
        di = None if self._i_last is None else i - self._i_last
        self._read(t, di)
        if not self._done and t >= self.p["lock"] - 1e-12 and self._pulses == 0:
            self._done = True
        filtered = i if self._i_last is None else 0.5 * (i + self._i_last)
        self._di_last, self._i_last = di, i
        theta, omega, share, u = self._out(t, filtered, theta_emf, omega_emf)
        h = u * cmath.exp(1j * self._theta)
        # Torque only once the side is told, or where no pulses were asked for.
        ready = 1.0 if self._done and (self._told != 0.0 or self._pulses == 0) else 0.0
        derate = self._held + share * (1.0 - self._held)
        return (
            theta,
            omega / c.pole_pairs,
            omega,
            0.0,
            ready,
            1.0 - ready,
            wrapped(theta - theta_true),
            filtered.real,
            filtered.imag,
            h.real,
            h.imag,
            self._told,
            share,
            1.0 if derate >= 1.0 else max(derate, 1e-6),
        )

    def _read(self, t: float, di: complex | None) -> None:
        """What the period just ended tells: a pulse's step on its side, or the square wave's
        step turned into the angle's error and run through the loop."""
        ts = self.ctx.ts
        (u_before, _, _), (u_now, at_now, place) = self._applied()
        if place >= 0:
            # A pulse: how fast the current stepped along the estimated d axis, on its side.
            if di is not None:
                self._sides[0 if place in (0, 1) else 1] += abs((di * cmath.exp(-1j * at_now)).real)
            self._measured += 1
            if self._measured == self._pulses:
                self._tell()
        elif di is not None and self._di_last is not None and u_now != u_before and not self._pulsing(t):
            # The injected signal's own step: the fundamental's cancels between two periods.
            seen = (di - self._di_last) * cmath.exp(-1j * at_now) / (u_now - u_before)
            # ½·sin 2e is never more than a half: what reads more is the regulators' own change.
            error = min(max(seen.imag / self._gain, -0.5), 0.5)
            self._omega += self._ki * ts * error
            self._theta = wrapped(self._theta + ts * (self._omega + self._kp * error))
        else:
            self._theta = wrapped(self._theta + ts * self._omega)

    def _out(
        self, t: float, filtered: complex, theta_emf: float, omega_emf: float
    ) -> tuple[float, float, float, float]:
        """The angle and speed put out, the observer's share of them, and the voltage to inject next."""
        # The angle put out: the injection's, its coupling taken back, blended toward the observer's.
        i_q = (filtered * cmath.exp(-1j * self._theta)).imag
        own = wrapped(self._theta - self.p["cross"] * i_q)
        w_h = self.p["handover"]
        # Handed over by the injection's own speed: the observer has no signal at standstill. Once
        # handed over the injection's speed is the observer's (below), and the observer's own
        # speed brings it back under the hand-over.
        share = 0.0 if w_h <= 0.0 or not self._done else min(max((abs(self._omega) - w_h) / w_h, 0.0), 1.0)
        if not self._over:
            if share > 0.0 and abs(wrapped(theta_emf - own)) > AGREE:
                share = 0.0  # the observer has not settled on the rotor: the injection keeps the angle
            # Blended over no faster than the loop settles: a jump in the angle the regulators use
            # moves their voltage, which the reading would take for the injected signal.
            share = min(share, self._share + self.ctx.ts * self._blend)
            self._over = share >= 1.0
        elif share <= 0.0:
            self._over = False  # back under the hand-over: the injection takes the angle again
        self._share = share
        theta = wrapped(own + share * wrapped(theta_emf - own))
        omega = self._omega + share * (omega_emf - self._omega)
        if share >= 1.0:
            # Handed over: follow the observer, ready to take the angle back below.
            self._theta, self._omega = wrapped(theta + self.p["cross"] * i_q), omega_emf
        # What to inject next: the next of the pulses, nothing while they are read, or the square wave.
        place = -1
        if self._pulsing(t):
            self._omega = 0.0
            if self._issued < self._pulses:
                place = self._issued % 4
                u = PATTERN[place] * self._pulse_v
                self._issued += 1
            else:
                u = 0.0
        elif share >= 1.0:
            u = 0.0
        else:
            self._sign = -self._sign
            # The whole amplitude until handed over: the reading divides by the step of the voltage
            # injected, which a wave tapered toward nought would leave to the regulators' own.
            u = self._sign * self.p["amplitude"]
        self._sent.append((u, self._theta, place))
        return theta, omega, share, u

    def _pulsing(self, t: float) -> bool:
        """Past the lock, with pulses still to send or to read."""
        return not self._done and self._pulses > 0 and t >= self.p["lock"] - 1e-12

    def _tell(self) -> None:
        """The pulses read: the side that stepped faster is the magnet's."""
        plus, minus = self._sides
        if abs(plus - minus) <= UNTOLD * (plus + minus):
            self._told = 0.0
        elif plus > minus:
            self._told = 1.0
        else:
            self._told = -1.0
            self._theta = wrapped(self._theta + math.pi)
        self._done = True


@register
class InjectionSum(Block):
    kind = "injection_sum"
    role = "actuation"
    title = "Injection added"
    summary = "Adds the injected voltage to the voltage the regulators ask for, before the modulator."
    definition = "The voltage the current regulators ask for, with the injection's added: v + h, along each axis."
    math = (r"v_{\alpha\beta} = v^*_{\alpha\beta} + h_{\alpha\beta}",)
    inputs = (
        Port("alpha", "V", "voltage asked for along phase a"),
        Port("beta", "V", "voltage asked for a quarter turn ahead"),
        Port("h_alpha", "V", "voltage injected along phase a"),
        Port("h_beta", "V", "voltage injected a quarter turn ahead"),
    )
    outputs = (
        Port("alpha", "V", "voltage to the modulator, along phase a"),
        Port("beta", "V", "voltage to the modulator, a quarter turn ahead"),
    )
    params = ()

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        return inputs[0] + inputs[2], inputs[1] + inputs[3]
