"""Active thermal control: a supervisor that follows an estimate of the junction temperature
of each of the six switches and gives up some ripple, some efficiency and at last some
current to keep the hottest of them under a limit.

The estimate is the controller's own, as a drive's firmware would hold it: the loss of each
switch from the current it measures, the duty cycle it asked for and two lines of the
device (control/stage.py), put through the junction's thermal network as first-order terms
to a sink at a known temperature. It is not the loss engine's model, which works the run's
real losses out afterwards: the difference between the two is the estimate's error, and
`loss_error` makes it larger on purpose.

At standstill and at a low output frequency one switch carries the peak current for longer
than its junction takes to follow, which is where an inverter sized by its root-mean-square
current is caught out, and where this block matters.
"""

from __future__ import annotations

import math

from motionsim.control.blocks import Block, Param, Port, register

ACTUATORS = ("all", "none", "clamp", "clamp+frequency", "derate")


class JunctionEstimate:
    """Six junctions followed through time from the loss put into each."""

    def __init__(self, r_th: tuple[float, ...], tau: tuple[float, ...], t_sink: float) -> None:
        self.r_th, self.tau, self.t_sink = r_th, tau, t_sink
        self.rise = [[0.0] * len(r_th) for _ in range(6)]
        self._dt = -1.0
        self._share: list[float] = []

    def clear(self) -> None:
        for chip in self.rise:
            chip[:] = [0.0] * len(self.r_th)

    def settle(self, power: list[float]) -> None:
        """As after this loss for ever: where a run starts from a drive already running."""
        for chip, p in zip(self.rise, power, strict=True):
            chip[:] = [p * r for r in self.r_th]

    def follow(self, power: list[float], dt: float) -> float:
        """dt seconds of this loss in each switch, W. Returns the hottest junction, °C."""
        if dt != self._dt:
            self._dt = dt
            self._share = [1.0 - math.exp(-dt / tau) if tau > 0 else 1.0 for tau in self.tau]
        hottest = 0.0
        r_th, share = self.r_th, self._share
        for chip, p in zip(self.rise, power, strict=True):
            total = 0.0
            for n, r in enumerate(r_th):
                chip[n] += share[n] * (p * r - chip[n])
                total += chip[n]
            if total > hottest:
                hottest = total
        return self.t_sink + hottest


@register
class ThermalSupervisor(Block):
    kind = "thermal_supervisor"
    role = "supervisor"
    title = "Active thermal control (supervisor)"
    summary = (
        "Estimates each switch's junction temperature and, as the hottest heats up, acts in three steps of "
        "rising cost: clamp the leg carrying the most current, lower the switching frequency, then fold the "
        "current limit back. Each is given back once it cools."
    )
    definition = (
        "Estimates the junction temperature of each of the six switches from the measured current, the duty "
        "cycles and the device's own conduction and switching lines, through the junction's thermal "
        "network, and acts on the hottest in three steps of rising cost: above `t_clamp` it asks the "
        "modulator to clamp the leg carrying the most current (fewer commutations, at the largest current), "
        "but only while that lowers the loss of the switch it clamps on: a clamped leg puts the whole "
        "current through one position, and where conduction outweighs switching, as at standstill in a "
        "device of low switching loss, the clamp would heat that switch more (the leg and the rail are the "
        "ones the modulator would take: of the highest and the lowest duty cycle the leg carrying more "
        "current, which regenerating is held on the rail its current flows backwards through); "
        "above `t_frequency` it lowers the switching frequency a step at a time, down to `f_floor`; above "
        "`t_derate` it folds the current limit back in proportion, reaching `i_floor` at `limit`. Each "
        "measure is given back once the estimate has fallen `hysteresis` below its threshold. Without a "
        "device the block has nothing to estimate from and leaves everything as it is."
    )
    math = (
        r"P_x = d_x\,|i_x|\left(v_0 + r\,|i_x|\right) + f_{sw}\left(e_0 + e_1 |i_x|\right)\ \text{(the switch that commutates)}",
        r"\text{clamp only if}\quad f_{sw}\left(e_0 + e_1 |i|\right) > \Delta d\,|i|\left(v_0 + r\,|i|\right),\qquad "
        r"\Delta d = 1 - d\ \text{(held high)},\ d\ \text{(held low)}",
        r"\hat T_j = T_{sink} + \sum_n \vartheta_n,\qquad \tau_n \dot\vartheta_n = P R_n - \vartheta_n",
        r"k_i = \mathrm{clip}\!\left(1 - \left(1 - k_{floor}\right)\frac{\hat T_j - T_{derate}}{T_{limit} - T_{derate}},\ k_{floor},\ 1\right)",
    )
    inputs = (
        Port("i_a", "A", "phase a current"),
        Port("i_b", "A", "phase b current"),
        Port("i_c", "A", "phase c current"),
        Port("d_a", "", "duty cycle of leg a"),
        Port("d_b", "", "duty cycle of leg b"),
        Port("d_c", "", "duty cycle of leg c"),
        Port("f_sw", "Hz", "switching frequency in use; open or nought: the design's", optional=True),
    )
    outputs = (
        Port("tj", "°C", "estimated temperature of the hottest junction"),
        Port("clamp", "", "1 while the modulator is asked to clamp for least loss"),
        Port("f_scale", "", "factor on the switching frequency"),
        Port("i_scale", "", "factor on the current limit"),
        Port("p_hot", "W", "estimated loss of the hottest switch"),
    )
    params = (
        Param("actuators", "", "all", "which measures it may take", choices=ACTUATORS),
        Param("limit", "°C", 150.0, "junction temperature held under", -50.0, 400.0),
        Param("t_clamp", "°C", 105.0, "estimate above which the modulator clamps", -50.0, 400.0),
        Param("t_frequency", "°C", 120.0, "estimate above which the frequency is lowered", -50.0, 400.0),
        Param("t_derate", "°C", 135.0, "estimate above which the current limit folds back", -50.0, 400.0),
        Param("hysteresis", "K", 15.0, "fall below a threshold before its measure is given back", 0.0, 200.0),
        Param("f_step", "", 0.25, "share of the design's frequency taken off at each step", 0.01, 0.75),
        Param("f_floor", "", 0.5, "lowest factor on the frequency", 0.25, 1.0),
        Param("i_floor", "", 0.3, "lowest factor on the current limit", 0.0, 1.0),
        Param("dwell", "s", 0.01, "time between two steps of the frequency", 0.0, 10.0),
        Param("loss_error", "", 1.0, "factor on the estimated loss: the estimate's own error, for study", 0.1, 10.0),
    )

    def setup(self) -> None:
        stage = self.ctx.stage
        self._stage = stage
        self._estimate = None if stage is None else JunctionEstimate(stage.r_th, stage.tau, stage.t_sink)
        allowed = self.p["actuators"]
        self._may_clamp = allowed in ("all", "clamp", "clamp+frequency")
        self._may_slow = allowed in ("all", "clamp+frequency")
        self._may_derate = allowed in ("all", "derate")

    def reset(self) -> None:
        self._clamp, self._f_scale, self._since, self._worth = 0.0, 1.0, 0.0, True
        if self._estimate is not None:
            self._estimate.clear()

    def _losses(self, currents: tuple[float, ...], duties: tuple[float, ...], f_sw: float) -> list[float]:
        """W in each of the six switches now: a high, a low, b high, ... by the stage's lines."""
        stage, wrong = self._stage, self.p["loss_error"]
        out = []
        for i, d in zip(currents, duties, strict=True):
            size = abs(i)
            carried = size * stage.drop(size)
            switched = f_sw * stage.pair(size) if 0.0 < d < 1.0 else 0.0
            forwards_high = i > 0
            for high in (True, False):
                share = d if high else 1.0 - d
                forwards = forwards_high == high
                p = share * carried if forwards or stage.reverse_in_switch else 0.0
                # The switch the current flows forwards through is the one that commutates it.
                out.append(wrong * (p + (switched if forwards else 0.0)))
        return out

    def _clamp_pays(self, currents: tuple[float, ...], duties: tuple[float, ...], f_sw: float) -> bool:
        """Whether the clamp the modulator would make lowers the loss of the switch it loads:
        the commutations the held leg no longer makes against the conduction its other
        position no longer shares. Judged while the clamp is off, on the duty cycles the
        legs have without it.

        The modulator holds, of the leg with the highest duty cycle (to the high rail) and
        the one with the lowest (to the low rail), the one carrying the larger current. The
        position on that rail then carries the leg's current for the whole period: 1 − d of
        it more on the high rail, d more on the low one. Motoring, that is the switch the
        current flows forwards through; regenerating it is the one it flows backwards
        through, which is loaded only where the switch itself conducts backwards (a diode
        chip beside it takes the current otherwise, and no switch is loaded more)."""
        stage = self._stage
        high = max(range(3), key=duties.__getitem__)
        low = min(range(3), key=duties.__getitem__)
        to_high = abs(currents[high]) >= abs(currents[low])
        leg = high if to_high else low
        size = abs(currents[leg])
        more = 1.0 - duties[leg] if to_high else duties[leg]
        forwards = (currents[leg] > 0) == to_high
        added = more * size * stage.drop(size) if forwards or stage.reverse_in_switch else 0.0
        saved = f_sw * stage.pair(size) if 0.0 < duties[leg] < 1.0 else 0.0
        return saved > added

    def _act(self, tj: float) -> float:
        """The three measures against the estimate. Returns the factor on the current limit."""
        p = self.p
        back = p["hysteresis"]
        if self._may_clamp:
            if tj > p["t_clamp"] and self._worth:
                self._clamp = 1.0
            elif tj < p["t_clamp"] - back or not self._worth:
                self._clamp = 0.0
        self._since += self.ctx.ts
        if self._may_slow and self._since >= p["dwell"]:
            if tj > p["t_frequency"] and self._f_scale > p["f_floor"] + 1e-9:
                self._f_scale, self._since = max(self._f_scale - p["f_step"], p["f_floor"]), 0.0
            elif tj < p["t_frequency"] - back and self._f_scale < 1.0:
                self._f_scale, self._since = min(self._f_scale + p["f_step"], 1.0), 0.0
        if not self._may_derate or tj <= p["t_derate"]:
            return 1.0
        span = max(p["limit"] - p["t_derate"], 1e-9)
        return max(1.0 - (1.0 - p["i_floor"]) * (tj - p["t_derate"]) / span, p["i_floor"])

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        if self._estimate is None:
            return 0.0, 0.0, 1.0, 1.0, 0.0
        c = self.ctx
        f_sw = inputs[6] if inputs[6] > 0.0 else c.f_carrier * c.ts0 / c.ts
        power = self._losses(inputs[0:3], inputs[3:6], f_sw)
        if self._clamp == 0.0:
            self._worth = self._clamp_pays(inputs[0:3], inputs[3:6], f_sw)
        tj = self._estimate.follow(power, c.ts)
        i_scale = self._act(tj)
        return tj, self._clamp, self._f_scale, i_scale, max(power)
