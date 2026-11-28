"""A current regulator designed in discrete time, for a motor that turns through a large
angle in one sampling period.

The usual regulator is designed as if time were continuous: a PI on each axis, the coupling
between the axes fed forward from the measured currents, and the angle advanced by a period
and a half for the delay. That holds while the rotor turns a few degrees a period. At a
carrier ratio of ten the rotor turns 36° a period: the coupling fed forward is a period
late, the pole the PI was meant to cancel has moved off the real axis, and the loop that had
a phase margin of 60° at standstill oscillates.

Seen from the rotor, with the voltage held through each period in the stator's frame and
asked one period before it is applied, the winding is, as one complex equation,

    i[k+1] = p · i[k] + b · v[k−1] − (back-EMF),   p = a · e^(−jω·Ts),  a = e^(−R·Ts/L),  b = (1 − a)/R

where v is the voltage asked in the rotor's frame and turned to the stator's at the angle the
rotor will have at the END of the period it is applied through (an advance of two periods
with the delay, one without). The regulator cancels the complex pole p exactly and leaves an
integrator:

    C(z) = (K/b) · (z − p)/(z − 1)   so that   L(z) = K / (z·(z − 1))

whose closed loop, z² − z + K, does not depend on the speed at all. That is exact for a
motor with one inductance on both axes. For one with saliency each axis takes its own
inductance in a and b, and the cancellation is close and not exact.
"""

from __future__ import annotations

import cmath
import math

from motionsim.control.blocks import Block, Param, Port, register
from motionsim.control.plant import held_voltage


@register
class CurrentDiscrete(Block):
    kind = "current_discrete_dq"
    role = "inner_regulator"
    title = "Current regulator (discrete-time, complex vector)"
    summary = (
        "A current regulator designed at the sampling rate on the winding's exact model, delay included. It "
        "cancels the winding's pole at any speed, so the loop holds up even at low carrier ratios. It trusts "
        "L and R."
    )
    definition = (
        "A current regulator designed directly at the sampling rate on the exact model of the winding seen "
        "from the turning rotor, with the period of delay in it: it cancels the winding's complex pole "
        "a·e^(−jωTs), whatever the speed, and leaves an integrator, so the closed loop z² − z + K is the "
        "same at a carrier ratio of 6 as at standstill. A drop-in for the PI regulator; the inverse Park "
        "transform after it advances the angle by 2 periods with the delay (1 without) in place of 1.5. K "
        "= 0.25 puts both poles at z = 0.5 (no overshoot); up to 0.5 is faster with a little overshoot, and "
        "at 1 the loop is on the edge. Exact for one inductance on both axes; with saliency each axis takes "
        "its own and the cancellation is approximate. It trusts L and R: wrong figures bring the coupling "
        "back."
    )
    math = (
        r"i_{dq}[k+1] = a\,e^{-j\omega T_s}\,i_{dq}[k] + b\,v_{dq}[k-1] - e,\quad a = e^{-R T_s/L},\ b = \frac{1-a}{R}",
        r"C(z) = \frac{K}{b}\,\frac{z - a\,e^{-j\omega T_s}}{z - 1}",
        r"u[k] = u[k-1] + \frac{K}{b}\left(\epsilon[k] - a\,e^{-j\omega T_s}\,\epsilon[k-1]\right),\quad \epsilon = i^* - i",
        r"v_{dq} = u + j\omega\psi\,\frac{1 - a\,e^{-j\omega T_s}}{b\,(R + j\omega L)}",
        r"L(z) = \frac{K}{z\,(z-1)},\qquad z^2 - z + K = 0",
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
        Port("int_d", "V", "d axis, the regulator's own part: what its integrator holds"),
        Port("int_q", "V", "q axis, the regulator's own part"),
        Port("ff_d", "V", "d axis, the back-EMF fed forward"),
        Port("ff_q", "V", "q axis, the back-EMF fed forward"),
    )
    params = (
        Param("gain", "", 0.25, "K: the loop gain; the closed loop is z² − z + K", 0.001, 1.0),
        Param("bemf_feedforward", "", True, "feed the back-EMF forward, through the same exact model"),
        Param("voltage_share", "", 1.0, "share of the modulation's linear range the voltage is held to", 0.1, 1.5),
    )
    linear = True
    loop = "current"

    def setup(self) -> None:
        self._reach = float(self.p["voltage_share"] * self.ctx.pwm.max_modulation_index * 0.5)

    def _winding(self, inductance: float) -> tuple[float, float]:
        c = self.ctx
        if c.rs <= 0:
            return 1.0, c.ts / inductance
        keep = math.exp(-c.rs * c.ts / inductance)
        return keep, (1.0 - keep) / c.rs

    def reset(self) -> None:
        self._u = self._before = 0j
        self._start: complex | None = None

    def warm(self, settled: dict[str, float]) -> None:
        if "v_d" in settled and "v_q" in settled:
            self._start = complex(settled["v_d"], settled["v_q"])

    def _emf(self, w: float) -> complex:
        """The voltage that holds the back-EMF off, through the same model: what the
        regulator's own output would settle to with no current flowing."""
        c = self.ctx
        if not self.p["bemf_feedforward"] or w == 0.0:
            return 0j
        keep, gain = self._winding(c.lq)
        pole = keep * cmath.exp(-1j * w * c.ts)
        return 1j * w * c.psi * (1.0 - pole) / (gain * complex(c.rs, w * c.lq))

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        id_ref, iq_ref, i_d, i_q, w, v_dc = inputs
        c, k = self.ctx, self.p["gain"]
        error = complex(id_ref - i_d, iq_ref - i_q)
        turn = cmath.exp(-1j * w * c.ts)
        (a_d, b_d), (a_q, b_q) = self._winding(c.ld), self._winding(c.lq)
        # Each axis with its own inductance: the error of the instant before, turned and
        # decayed as the winding would have left it.
        gone = turn * complex(a_d * self._before.real, a_q * self._before.imag)
        forward = self._emf(w)
        held = self._u
        if self._start is not None:
            # A drive already running: the integrator holds what the settled voltage needs,
            # as a stage that holds its voltage through the period has to give it.
            start = held_voltage(c.rs, c.lq, c.ts, w, self._start.real, self._start.imag)
            self._u, self._start = start - forward, None
            held = self._u
        else:
            self._u += k * complex((error.real - gone.real) / b_d, (error.imag - gone.imag) / b_q)
        self._before = error
        v = self._u + forward
        most, size = self._reach * v_dc, abs(v)
        if size <= most:
            return v.real, v.imag, error.real, error.imag, 0.0, self._u.real, self._u.imag, forward.real, forward.imag
        # Held to the circle, and the regulator's memory with it: the integrator takes the
        # voltage really asked, and the error remembered is the one that would have asked
        # exactly that, so that the pole it cancels stays cancelled once the limit lets go.
        v *= most / size
        self._u = v - forward
        made = self._u - held
        self._before = complex(made.real * b_d / k + gone.real, made.imag * b_q / k + gone.imag)
        return v.real, v.imag, error.real, error.imag, 1.0, self._u.real, self._u.imag, forward.real, forward.imag

    def transfer(self, axis: str = "q") -> tuple[list[float], list[float]] | None:
        keep, gain = self._winding(self.ctx.ld if axis == "d" else self.ctx.lq)
        k = self.p["gain"]
        return [k / gain, -k * keep / gain], [1.0, -1.0]
