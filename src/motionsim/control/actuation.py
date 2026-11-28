"""The blocks between the voltage asked for and the stage, beside the modulator: the switching
frequency as a controlled variable, and the compensation of the voltage the stage loses to
its dead time and its devices' drop."""

from __future__ import annotations

import math

from motionsim.control.blocks import Block, Param, Port, register

SQRT3 = math.sqrt(3.0)
MODES = ("fixed", "peak", "rms", "point")


def ripple_shape(d_a: float, d_b: float, d_c: float) -> tuple[float, float]:
    """The current ripple of a carrier period under three duty cycles, as two numbers without
    a unit: its peak in any phase, and the root mean square over the three phases, each to
    be multiplied by Vdc·T/L for amperes.

    A period of a triangular carrier runs from its peak to its valley and back; leg x rises
    (1 − d_x)/2 of a period after the peak. Between two edges the phase voltage is constant,
    so the ripple is a straight line whose slope is what the phase gets less its mean,
    Vdc·((s_x − s̄) − (d_x − d̄))/L: it starts at nought at the peak, where the current is
    sampled, and is back at nought at the valley.
    """
    duties = (min(max(d_a, 0.0), 1.0), min(max(d_b, 0.0), 1.0), min(max(d_c, 0.0), 1.0))
    mean = (duties[0] + duties[1] + duties[2]) / 3.0
    order = sorted(range(3), key=lambda x: -duties[x])  # the leg of the largest duty rises first
    edges = [0.5 * (1.0 - duties[x]) for x in order]
    ripple = [0.0, 0.0, 0.0]
    state = [0.0, 0.0, 0.0]
    peak = square = at = 0.0
    for k in range(4):
        until = edges[k] if k < 3 else 0.5
        span = until - at
        if span > 0.0:
            high = (state[0] + state[1] + state[2]) / 3.0
            for x in range(3):
                start = ripple[x]
                end = start + span * ((state[x] - high) - (duties[x] - mean))
                square += span * (start * start + start * end + end * end) / 3.0
                ripple[x] = end
                if abs(end) > peak:
                    peak = abs(end)
        at = until
        if k < 3:
            state[order[k]] = 1.0
    return peak, math.sqrt(square / (0.5 * 3.0))


@register
class VariableFrequency(Block):
    kind = "variable_frequency"
    role = "actuation"
    title = "Switching frequency (controlled)"
    summary = (
        "Sets the switching period sample by sample: fixed, or stretched until the predicted current ripple "
        "reaches a limit (peak, rms, or over a turn). Fewer commutations where the ripple allows."
    )
    definition = (
        "Sets the carrier period instant by instant, through the scheme's `actuation.period`: held (fixed), "
        "or stretched until the ripple the coming duty cycles will make reaches a limit, on its peak within "
        "the period (peak), on its root mean square within the period (rms), or on its root mean square "
        "over a turn of the output, which is one frequency for the operating point (point). The ripple is "
        "predicted from the duty cycles, the DC voltage and the inductance the ripple sees; it grows in "
        "proportion to the period. The regulators read the period in use, so their integrals and the "
        "angle's advance follow it. A factor from a supervisor (`scale`) lowers the frequency further. "
        "The voltage was turned to the middle of a period as long as the last one: where the period "
        "changes, the duty cycles are put out again turned by half the angle the rotor covers in the "
        "difference (wire `omega_e`, and drive the stage from this block's duty cycles), or the change of "
        "period is a step of voltage angle at each instant, which a motor of low inductance answers with "
        "amperes."
    )
    math = (
        r"\Delta i_x(t) = \frac{V_{dc}}{L}\int_0^t \left[(s_x - \bar s) - (d_x - \bar d)\right]d\tau",
        r"\hat\imath_{rip}(T) = \frac{V_{dc}\,T}{L}\,\rho(d_a, d_b, d_c)",
        r"T = \mathrm{clip}\!\left(\frac{i_{lim}\,L}{V_{dc}\,\rho},\ \frac{1}{f_{max}},\ \frac{1}{f_{min}}\right)",
        r"\delta = \tfrac12\,\omega\left(T_s' - T_s\right),\qquad "
        r"d_a' = \bar d + (d_a - \bar d)\cos\delta + \frac{d_c - d_b}{\sqrt3}\sin\delta",
    )
    inputs = (
        Port("d_a", "", "duty cycle of leg a"),
        Port("d_b", "", "duty cycle of leg b"),
        Port("d_c", "", "duty cycle of leg c"),
        Port("v_dc", "V", "DC voltage"),
        Port("scale", "", "factor on the frequency from a supervisor; open or nought: 1", optional=True),
        Port("omega_e", "rad/s", "electrical speed, to turn the duty cycles to the new period", optional=True),
    )
    outputs = (
        Port("period", "s", "sampling period asked for"),
        Port("f_sw", "Hz", "switching frequency asked for"),
        Port("ripple", "A", "peak ripple predicted at that frequency"),
        Port("d_a", "", "duty cycle of leg a, turned to the middle of the period asked for"),
        Port("d_b", "", "duty cycle of leg b, turned likewise"),
        Port("d_c", "", "duty cycle of leg c, turned likewise"),
        Port("limited", "", "1 while the frequency the ripple asks for lies past f_min or f_max and is held there"),
    )
    params = (
        Param("mode", "", "fixed", "fixed, or a limit on the ripple: peak, rms or point", choices=MODES),
        Param("ripple_limit", "A", 1.0, "the ripple held: its peak (peak) or its root mean square", 1e-9, 1e6),
        Param("f_min", "Hz", 1000.0, "lowest switching frequency", 1.0, 2e6),
        Param("f_max", "Hz", 100000.0, "highest switching frequency", 1.0, 2e6),
        Param("inductance", "H", 0.0, "inductance the ripple sees; 0: the smaller of Ld and Lq", 0.0, 10.0),
        Param("filter", "s", 0.01, "time the ripple is averaged over (point)", 1e-6, 10.0),
    )

    def setup(self) -> None:
        c = self.ctx
        self._l = self.p["inductance"] or min(c.ld, c.lq)
        self._share = c.ts0 * c.f_carrier  # sampling periods in a carrier period: 1, or a half
        self._nominal = 1.0 / c.f_carrier

    def reset(self) -> None:
        self._square: float | None = None

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        d_a, d_b, d_c, v_dc, scale, omega_e = inputs
        p, mode = self.p, self.p["mode"]
        peak, rms = ripple_shape(d_a, d_b, d_c)
        per_second = v_dc / self._l  # A of ripple per second of period and unit of shape
        period, held = self._nominal, 0.0
        if mode != "fixed":
            shape = peak if mode == "peak" else rms
            if mode == "point":
                # One frequency for the operating point: the mean square over a turn of the output.
                share = min(self.ctx.ts / p["filter"], 1.0)
                held = shape * shape if self._square is None else self._square
                self._square = held + share * (shape * shape - held)
                shape = math.sqrt(self._square)
            period = p["ripple_limit"] / (per_second * shape) if shape > 1e-12 else math.inf
            wanted = period
            period = min(max(period, 1.0 / p["f_max"]), 1.0 / p["f_min"])
            held = float(period != wanted)
        if scale > 0.0:
            period /= scale
        ts = period * self._share
        turn = 0.5 * omega_e * (ts - self.ctx.ts)
        if turn != 0.0:
            mean, cs, sn = (d_a + d_b + d_c) / 3.0, math.cos(turn), math.sin(turn) / SQRT3
            d_a, d_b, d_c = (
                min(max(mean + (d_a - mean) * cs + (d_c - d_b) * sn, 0.0), 1.0),
                min(max(mean + (d_b - mean) * cs + (d_a - d_c) * sn, 0.0), 1.0),
                min(max(mean + (d_c - mean) * cs + (d_b - d_a) * sn, 0.0), 1.0),
            )
        return ts, 1.0 / period, per_second * peak * period, d_a, d_b, d_c, held


@register
class DeadTimeCompensation(Block):
    kind = "dead_time_compensation"
    role = "actuation"
    title = "Dead time and device drop compensation"
    summary = (
        "Adds back the voltage the dead time and the devices' drop will cost, by the sign of each phase's current."
    )
    definition = (
        "Adds to the voltage asked for what the stage will lose: through the dead time a leg's voltage is the "
        "one the current's direction gives, so each carrier period loses t_d·Vdc volt-seconds against the "
        "current, and a conducting device drops its own voltage against it too. The sign follows each "
        "phase's current, and passes through nought over a band about the crossing, where the current's "
        "direction within the period is not known. A leg the modulator clamps loses no dead time: that is "
        "not taken into account here."
    )
    math = (
        r"\Delta v_x = k\left(t_d\,f_{sw}\,V_{dc} + v_{drop}\right)\mathrm{sat}\!\left(\frac{i_x}{i_{band}}\right)",
        r"v_\alpha' = v_\alpha + \tfrac{2}{3}\left(\Delta v_a - \tfrac12\Delta v_b - \tfrac12\Delta v_c\right)",
        r"v_\beta' = v_\beta + \tfrac{1}{\sqrt3}\left(\Delta v_b - \Delta v_c\right)",
    )
    inputs = (
        Port("alpha", "V", "voltage asked for along phase a"),
        Port("beta", "V", "voltage asked for a quarter turn ahead"),
        Port("i_a", "A", "phase a current"),
        Port("i_b", "A", "phase b current"),
        Port("i_c", "A", "phase c current"),
        Port("v_dc", "V", "DC voltage"),
    )
    outputs = (
        Port("alpha", "V", "voltage with the compensation, along phase a"),
        Port("beta", "V", "voltage with the compensation, a quarter turn ahead"),
        Port("added", "V", "what is added to a phase carrying its full current"),
    )
    params = (
        Param("dead_time", "s", 0.0, "dead time compensated for", 0.0, 1e-3),
        Param("drop", "V", 0.0, "drop of a conducting device compensated for", 0.0, 100.0),
        Param(
            "band", "A", 0.0, "current either side of nought over which the sign is brought in; 0: at once", 0.0, 1e6
        ),
        Param("share", "", 1.0, "share of the computed loss that is compensated", 0.0, 2.0),
    )

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        alpha, beta, i_a, i_b, i_c, v_dc = inputs
        p, c = self.p, self.ctx
        carrier = c.f_carrier * c.ts0 / c.ts  # of the period in use
        size = p["share"] * (p["dead_time"] * carrier * v_dc + p["drop"])
        band = p["band"]
        if band > 0.0:
            a = size * min(max(i_a / band, -1.0), 1.0)
            b = size * min(max(i_b / band, -1.0), 1.0)
            cc = size * min(max(i_c / band, -1.0), 1.0)
        else:
            a = math.copysign(size, i_a) if i_a else 0.0
            b = math.copysign(size, i_b) if i_b else 0.0
            cc = math.copysign(size, i_c) if i_c else 0.0
        return alpha + (2.0 * a - b - cc) / 3.0, beta + (b - cc) / SQRT3, size
