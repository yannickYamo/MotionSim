"""Observers that take the encoder's place: the rotor's angle and speed estimated from the
voltage the controller asks for and the current it measures. Three of them, each a drop-in
for `position_sensing` (the same three outputs first), each with the estimate's error on a
wire of its own:

- `observer_emf_pll`: the back-EMF as a disturbance of the winding's equation, filtered, and
  a phase-locked loop on its direction (the extended-EMF form, which holds for a motor
  with saliency);
- `observer_smo`: a sliding-mode current observer whose switching term is the back-EMF,
  its low-pass filter and the compensation of that filter's phase;
- `observer_flux`: a Luenberger flux observer, the voltage model corrected toward the
  current model, and a phase-locked loop on the active flux.

All three read the back-EMF or the flux it integrates to, which vanish at standstill: none
can start a motor from rest. `if_startup` (startup.py) runs the motor up open loop and hands
over to the observer once there is something to read.

Discretisation. An observer works on quantities that turn with the rotor in the stator's
frame; at a low carrier ratio they turn through a large angle in one sampling period, and
how the observer is stepped decides whether it holds. Each offers two forms:

- `exact`: the voltage really applied through the last period (the command delayed as the
  stage delays it), brought to the start of the period, and the observer's own equation
  solved through the period for an input that turns at the estimated speed. What is left
  of the filter's phase is then the continuous filter's own, which is compensated, to within
  a term of second order in the period (about g·ω·Ts²/12 rad for a filter of bandwidth g:
  0.1° at a carrier ratio of 85 with g·Ts = 0.3).
- `euler`: as firmware often has it. The newest voltage command is taken for the voltage
  across the motor, the equation is stepped by one forward-Euler step from the newest
  samples, and the continuous filter's phase is taken for the compensation. Each of the
  three shortcuts is an angle error that grows with the angle turned in a period: small at
  a carrier ratio of 50, tens of degrees at a ratio of 6, where the drive loses its
  orientation.
"""

from __future__ import annotations

import cmath
import math

from motionsim.control.blocks import Block, Param, Port, register
from motionsim.control.plant import held_voltage

TWO_PI = 2.0 * math.pi
FORMS = ("exact", "euler")
EMF_FLOOR = 5.0  # Hz electrical: below the back-EMF of this frequency there is nothing to lock onto
COMMON_IN = (
    Port("v_alpha", "V", "voltage asked for along phase a (the wire the modulator reads)"),
    Port("v_beta", "V", "voltage asked for a quarter turn ahead"),
    Port("i_alpha", "A", "measured current along phase a"),
    Port("i_beta", "A", "measured current a quarter turn ahead"),
    Port("theta_true", "rad", "the rotor's true angle: read for the error wire only", optional=True),
)
COMMON_OUT = (
    Port("theta", "rad", "estimated electrical angle"),
    Port("omega_m", "rad/s", "estimated shaft speed"),
    Port("omega_e", "rad/s", "estimated electrical speed"),
    Port("error", "rad", "estimated angle less the true one"),
    Port("size", "", "size of what the angle is read from: back-EMF in V, or flux in Wb"),
)
PLL = Param("pll_bandwidth", "Hz", 100.0, "the phase-locked loop's bandwidth ρ/2π: Kp = 2ρ, Ki = ρ²", 0.1, 1e5)
FORM = Param("discretisation", "", "exact", "exact, or the naive forward-Euler form", choices=FORMS)


def wrapped(angle: float) -> float:
    """An angle brought to within half a turn of nought."""
    return (angle + math.pi) % TWO_PI - math.pi


class Observer(Block):
    """What the three share: the delay line of the voltage, the phase-locked loop, the outputs."""

    inputs = COMMON_IN
    outputs = COMMON_OUT

    def setup(self) -> None:
        rho = TWO_PI * self.p["pll_bandwidth"]
        # A double real pole at ρ: the usual rule for a loop that tracks an angle and its speed.
        self._kp, self._ki = 2.0 * rho, rho * rho
        self._exact = self.p["discretisation"] == "exact"

    def reset(self) -> None:
        self._theta = self._omega = 0.0
        self._v_before = 0j  # the command the wire held one instant ago
        self._instants = 0
        self._v_first: complex | None = None  # what a running drive's first period is held at
        self._i_last = 0j
        self._clear()

    def _clear(self) -> None:
        raise NotImplementedError

    def warm(self, settled: dict[str, float]) -> None:
        """From a drive already running: the state the observer would have settled to."""
        c = self.ctx
        if "i_d" not in settled or "v_d" not in settled:
            return
        theta, w = settled.get("theta", 0.0), c.pole_pairs * settled.get("omega_m", 0.0)
        turn = cmath.exp(1j * theta)
        back = cmath.exp(-1j * w * c.ts)
        i_dq, v_dq = complex(settled["i_d"], settled["i_q"]), complex(settled["v_d"], settled["v_q"])
        self._omega = w
        self._i_last = i_dq * turn * back
        # The stage holds each voltage through a period: what it held through the period
        # just over, and what the kernel holds through the first of a running drive.
        held = held_voltage(c.rs, c.lq, c.ts, w, v_dq.real, v_dq.imag) * turn
        self._v_before = held
        self._v_first = held * cmath.exp(1j * w * c.ts)
        # Each observer's state is where the last instant left it: one period back.
        self._settle(theta, w, i_dq, turn * back)

    def _settle(self, theta: float, w: float, i_dq: complex, turn: complex) -> None:
        raise NotImplementedError

    def _applied(self, v_wire: complex) -> tuple[complex, complex]:
        """The voltage this step works with, and the one applied through the period that
        has just ended. With the one-sample delay the command on the wire (the last
        instant's) is only now reaching the stage: what was applied is the one before it."""
        # The first period of a run has no command from before it: the kernel holds a
        # running drive at its settled voltage through it, and gives a drive that starts
        # cold its very first command at once.
        self._instants += 1
        applied = self._v_before if self.ctx.delay else v_wire
        if self._instants == 2 and self.ctx.delay:
            applied = v_wire if self._v_first is None else self._v_first
        self._v_before = v_wire
        return (applied if self._exact else v_wire), applied

    def _through(self, pole: float) -> complex:
        """A first-order filter of unit gain and bandwidth `pole` rad/s through one period,
        for an input that turns at the estimated speed: what the sample at the start of the
        period is multiplied by. The state itself decays by exp(−pole·Ts)."""
        ts, w = self.ctx.ts, self._omega
        return pole * (cmath.exp(1j * w * ts) - math.exp(-pole * ts)) / complex(pole, w)

    def _through_ramp(self, pole: float) -> complex:
        """The same filter for an input that turns at the estimated speed and, seen from the
        rotor, rises in a straight line from nought to one through the period."""
        ts = self.ctx.ts
        rate = complex(pole, self._omega)
        grown = cmath.exp(rate * ts)
        return pole * math.exp(-pole * ts) * (grown * (rate * ts - 1.0) + 1.0) / (rate * rate * ts)

    def _lock(self, along: complex, lag: float, theta_true: float, size: float) -> tuple[float, ...]:
        """One step of the phase-locked loop toward the direction of `along` (a vector meant
        to lie along the rotor's d axis), and the block's outputs. `lag` is added back to
        the angle put out: the phase the filters are known to have taken."""
        ts = self.ctx.ts
        length = abs(along)
        if length > 0.0:
            error = (along.imag * math.cos(self._theta) - along.real * math.sin(self._theta)) / length
        else:
            error = 0.0
        # The angle put out is the loop's own for this instant; the loop then moves on to the next.
        theta = wrapped(self._theta + lag)
        self._omega += self._ki * ts * error
        self._theta = wrapped(self._theta + ts * (self._omega + self._kp * error))
        speed = self._omega
        return theta, speed / self.ctx.pole_pairs, speed, wrapped(theta - theta_true), size

    def _along_d(self, emf: complex) -> complex:
        """A back-EMF turned to point along the d axis: it lies a quarter turn ahead of d at
        a positive speed and behind it at a negative one. Below the EMF of 5 Hz there is
        nothing to lock onto, and the loop is let go in proportion."""
        along = -1j * emf if self._omega >= 0.0 else 1j * emf
        floor = self.ctx.psi * TWO_PI * EMF_FLOOR
        return along if abs(emf) >= floor else along * (abs(emf) / floor)

    def lowest(self) -> tuple[float, str]:
        """The electrical speed in rad/s below which this observer has too little to read,
        by its own signal's size, and why in words."""
        return TWO_PI * EMF_FLOOR, (
            f"its back-EMF is then under that of {EMF_FLOOR:g} Hz, {self.ctx.psi * TWO_PI * EMF_FLOOR:.3g} V, "
            "the least the phase-locked loop locks onto"
        )

    def _saliency(self, i: complex) -> complex:
        """The voltage the difference between the two axes' inductances puts across the
        winding in the extended-EMF form: ω·(Ld − Lq)·(i_β − j·i_α)."""
        c = self.ctx
        return self._omega * (c.ld - c.lq) * complex(i.imag, -i.real)


@register
class EmfObserver(Observer):
    kind = "observer_emf_pll"
    role = "estimation"
    title = "Back-EMF observer with phase-locked loop"
    summary = (
        "Estimates the back-EMF from what the winding's equation leaves unexplained; a phase-locked loop "
        "reads the rotor's angle and speed from it. No encoder needed, but blind at standstill."
    )
    definition = (
        "Estimates the back-EMF as what the winding's equation leaves unexplained, through a first-order "
        "filter of bandwidth g, and locks a phase-locked loop onto its direction: the rotor's angle and "
        "speed with no encoder. Written for the extended EMF, so it holds for a motor whose two axes differ "
        "in inductance. The filter delays the EMF by atan(ω/g), which is added back. It reads a voltage that "
        "is proportional to the speed: at standstill there is nothing to read, and a start-up method has to "
        "bring the motor up first. Tuned with the filter three times above the design's electrical "
        "frequency and the loop's two poles at ρ."
    )
    math = (
        r"\hat e = \frac{g}{s+g}\left(v - R\,i - L_d\,\dot\imath - \omega(L_d - L_q)\,J' i\right),\quad "
        r"e = \omega\left[\psi + (L_d - L_q)\,i_d\right]\begin{pmatrix}-\sin\theta\\ \cos\theta\end{pmatrix}",
        r"\dot\xi = -g\,\xi + g\left(v - R\,i - \omega(L_d-L_q)J' i + g L_d\,i\right),\quad \hat e = \xi - g L_d\,i",
        r"\varepsilon = \mathrm{sgn}(\hat\omega)\,\frac{-\hat e_\alpha\cos\hat\theta - \hat e_\beta\sin\hat\theta}{|\hat e|},\quad "
        r"\dot{\hat\omega} = \rho^2\varepsilon,\quad \dot{\hat\theta} = \hat\omega + 2\rho\,\varepsilon",
        r"\hat\theta_{out} = \hat\theta + \arctan(\hat\omega / g)",
    )
    params = (
        Param("bandwidth", "Hz", 500.0, "the EMF filter's bandwidth g/2π", 0.1, 1e6),
        PLL,
        Param("phase_compensation", "", True, "add the filter's phase back to the angle"),
        FORM,
    )

    def setup(self) -> None:
        super().setup()
        self._g = TWO_PI * self.p["bandwidth"]

    def _clear(self) -> None:
        self._xi = 0j

    def _felt(self, i: complex) -> complex:
        """What a current puts into the filter beside the voltage."""
        c = self.ctx
        return self._g * c.ld * i - c.rs * i - self._saliency(i)

    def _settle(self, theta: float, w: float, i_dq: complex, turn: complex) -> None:
        c, g = self.ctx, self._g
        emf = 1j * turn * w * (c.psi + (c.ld - c.lq) * i_dq.real)
        self._xi = emf * g / complex(g, w) + g * c.ld * i_dq * turn
        self._theta = wrapped(theta - math.atan2(w, g))  # the loop's own angle, for this instant

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        v_wire, i = complex(inputs[0], inputs[1]), complex(inputs[2], inputs[3])
        c, g = self.ctx, self._g
        used, applied = self._applied(v_wire)
        if self._exact:
            before = self._i_last
            # The voltage is held through the period, the current turns with the rotor.
            # The voltage is held; the current turns with the rotor and, seen from it, goes
            # in a straight line from its sample at one end of the period to the other's.
            keep = math.exp(-g * c.ts)
            grown = i * cmath.exp(-1j * self._omega * c.ts) - before
            steady, rising = self._through(g), self._through_ramp(g)
            self._xi = keep * self._xi + (1.0 - keep) * applied
            self._xi += steady * self._felt(before) + rising * self._felt(grown)
        else:
            drive = used - c.rs * i - self._saliency(i) + g * c.ld * i
            self._xi += c.ts * g * (drive - self._xi)
        self._i_last = i
        emf = self._xi - g * c.ld * i
        lag = math.atan2(self._omega, g) if self.p["phase_compensation"] else 0.0
        return self._lock(self._along_d(emf), lag, inputs[4], abs(emf))


@register
class SlidingModeObserver(Observer):
    kind = "observer_smo"
    role = "estimation"
    title = "Sliding-mode observer"
    summary = (
        "A winding model forced onto the measured current by a saturating switching term: once it slides, "
        "that term is the back-EMF, filtered, and a phase-locked loop reads the angle. Blind at standstill."
    )
    definition = (
        "A model of the winding is driven by the same voltage as the motor and forced onto the measured "
        "current by a switching term that saturates at `gain` volts: once it slides, that term is the "
        "back-EMF. Inside the `boundary` either side of nought it is proportional, which keeps it from "
        "chattering; a low-pass filter of bandwidth ωc smooths it, and the filter's phase atan(ω/ωc) is "
        "added back to the angle, with the half period the sampled observer adds. A phase-locked loop reads "
        "the angle. Like every observer of the back-EMF it has nothing to read at standstill. Tuned with "
        "the gain at twice the design's back-EMF, the boundary where the model reaches the measured current "
        "in one period, and the filter three times above the design's electrical frequency."
    )
    math = (
        r"L_d\,\dot{\hat\imath} = v - R\,\hat\imath - \omega(L_d - L_q)J' i - z,\qquad "
        r"z = k\,\mathrm{sat}\!\left(\frac{\hat\imath - i}{\delta}\right)",
        r"\hat e = \frac{\omega_c}{s + \omega_c}\,z",
        r"\hat\theta_{out} = \hat\theta + \arctan(\hat\omega/\omega_c) + \tfrac12\hat\omega T_s",
        r"\delta = k\,\frac{1 - e^{-R T_s/L_d}}{R}\ \text{(reached in one period)}",
    )
    params = (
        Param("gain", "V", 10.0, "k: what the switching term saturates at; above the back-EMF", 1e-6, 1e5),
        Param("boundary", "A", 1.0, "δ: current error over which the switching term is proportional", 1e-9, 1e5),
        Param("cutoff", "Hz", 500.0, "the low-pass filter's bandwidth ωc/2π", 0.1, 1e6),
        PLL,
        Param("phase_compensation", "", True, "add the filter's phase back to the angle"),
        FORM,
    )

    def setup(self) -> None:
        super().setup()
        self._wc = TWO_PI * self.p["cutoff"]

    def _clear(self) -> None:
        self._model = self._z = self._xi = 0j

    def _settle(self, theta: float, w: float, i_dq: complex, turn: complex) -> None:
        c, wc = self.ctx, self._wc
        emf = 1j * turn * w * (c.psi + (c.ld - c.lq) * i_dq.real)
        # Sliding, the model stands off the measured current by what makes the switching
        # term the back-EMF: d[k+1] = keep·d[k] + b·(ē[k] − d[k]/b), ē the EMF's mean through
        # the period, for a d that turns with the rotor.
        keep = math.exp(-c.rs * c.ts / c.ld) if c.rs > 0 else 1.0
        reach = (1.0 - keep) / c.rs if c.rs > 0 else c.ts / c.ld
        x = 0.5 * w * c.ts
        mean = emf * cmath.exp(1j * x) * (math.sin(x) / x if abs(x) > 1e-6 else 1.0)
        self._z = self._switching(reach * mean / (cmath.exp(2j * x) + 1.0 - keep)) if self._exact else emf
        self._model = i_dq * turn + self._z * self.p["boundary"] / self.p["gain"]
        self._xi = self._z * wc / complex(wc, w)
        self._theta = wrapped(theta - math.atan2(w, wc) - 0.5 * w * c.ts)

    def _switching(self, error: complex) -> complex:
        k, d = self.p["gain"], self.p["boundary"]
        return complex(k * min(max(error.real / d, -1.0), 1.0), k * min(max(error.imag / d, -1.0), 1.0))

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        v_wire, i = complex(inputs[0], inputs[1]), complex(inputs[2], inputs[3])
        c, wc = self.ctx, self._wc
        used, applied = self._applied(v_wire)
        if self._exact:
            # The winding through the period under the voltage it really had, held as the
            # stage holds it: exact for the resistance and the inductance.
            keep = math.exp(-c.rs * c.ts / c.ld) if c.rs > 0 else 1.0
            gain = (1.0 - keep) / c.rs if c.rs > 0 else c.ts / c.ld
            self._xi = math.exp(-wc * c.ts) * self._xi + self._through(wc) * self._z
            self._model = keep * self._model + gain * (applied - self._saliency(self._i_last) - self._z)
            self._z = self._switching(self._model - i)
        else:
            slope = used - c.rs * self._model - self._saliency(i) - self._z
            self._model += c.ts * slope / c.ld
            self._z = self._switching(self._model - i)
            self._xi += c.ts * wc * (self._z - self._xi)
        self._i_last = i
        emf = self._xi
        lag = 0.0
        if self.p["phase_compensation"]:
            lag = math.atan2(self._omega, wc) + (0.5 * self._omega * c.ts if self._exact else 0.0)
        return self._lock(self._along_d(emf), lag, inputs[4], abs(emf))


@register
class FluxObserver(Observer):
    kind = "observer_flux"
    role = "estimation"
    title = "Flux observer (Luenberger)"
    summary = (
        "Blends two estimates of the stator flux, the integrated voltage at speed and the current model at "
        "low speed; a phase-locked loop reads the angle from it. It cannot find a rotor at rest."
    )
    definition = (
        "Integrates the voltage less the resistive drop to the stator flux (the voltage model), and pulls "
        "that integral toward the flux the measured current and the estimated angle give (the current model) "
        "with a gain g: below g/2π the current model decides, which keeps the integral from drifting; above "
        "it the voltage model does, which needs no inductance on the d axis and no angle. The active flux, "
        "the stator flux less Lq·i, lies along the rotor's d axis whatever the saliency, and a phase-locked "
        "loop reads the angle from it. With the motor's figures right it has no phase error to compensate; a "
        "wrong Lq turns the angle by atan(ΔLq·iq / ψa). At standstill the voltage model integrates nothing "
        "and the current model only repeats the angle it is given: the observer cannot find the rotor at "
        "rest. Tuned with g a tenth of the design's electrical frequency."
    )
    math = (
        r"\dot{\hat\psi}_s = v - R\,i + g\left(\hat\psi_{cm} - \hat\psi_s\right)",
        r"\hat\psi_{cm} = e^{j\hat\theta}\left(L_d\,\hat\imath_d + \psi + j L_q\,\hat\imath_q\right)",
        r"\hat\psi_a = \hat\psi_s - L_q\,i = \left[\psi + (L_d - L_q)\,i_d\right]e^{j\theta}",
        r"\varepsilon = \frac{\hat\psi_{a\beta}\cos\hat\theta - \hat\psi_{a\alpha}\sin\hat\theta}{|\hat\psi_a|}",
    )
    params = (
        Param("crossover", "Hz", 10.0, "g/2π: the current model below, the voltage model above", 0.01, 1e5),
        PLL,
        FORM,
    )

    def setup(self) -> None:
        super().setup()
        self._g = TWO_PI * self.p["crossover"]

    def _clear(self) -> None:
        self._flux = complex(self.ctx.psi, 0.0)

    def _settle(self, theta: float, w: float, i_dq: complex, turn: complex) -> None:
        c = self.ctx
        self._flux = turn * complex(c.ld * i_dq.real + c.psi, c.lq * i_dq.imag)
        self._theta = wrapped(theta)

    def lowest(self) -> tuple[float, str]:
        return self._g, (
            f"under its crossover of {self.p['crossover']:.3g} Hz the voltage model gives way to the current "
            "model, which only repeats the angle it is given"
        )

    def _current_model(self, i: complex, theta: float) -> complex:
        c = self.ctx
        turn = cmath.exp(1j * theta)
        seen = i / turn
        return turn * complex(c.ld * seen.real + c.psi, c.lq * seen.imag)

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        v_wire, i = complex(inputs[0], inputs[1]), complex(inputs[2], inputs[3])
        c, g = self.ctx, self._g
        used, applied = self._applied(v_wire)
        ahead = self._theta  # where the loop expects the rotor now
        if self._exact:
            # The voltage really applied, integrated as it was held; the current at the
            # period's two ends.
            flux = self._flux + c.ts * (applied - 0.5 * c.rs * (self._i_last + i))
            self._flux = flux + (1.0 - math.exp(-g * c.ts)) * (self._current_model(i, ahead) - flux)
        else:
            self._flux += c.ts * (used - c.rs * i + g * (self._current_model(i, ahead) - self._flux))
        self._i_last = i
        active = self._flux - c.lq * i
        return self._lock(active, 0.0, inputs[4], abs(active))
