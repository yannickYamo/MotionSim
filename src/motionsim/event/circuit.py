"""The circuit one switching event is worked out in, and the equations it obeys.

A clamped inductive load: the load current is held, and it moves between the switch under
test and the reverse path of the other switch of its leg. The commutation loop holds the
supply (or its decoupling capacitor), the loop's inductance and resistance, the switch with
its output capacitance and the reverse path with its own capacitance and stored charge. The
gate is charged and discharged through its resistance from the driver, its capacitances
those of the datasheet's charges. Nothing in it is a formula for the result: the ringing,
the overshoot and the recovery spike are what the equations do.

States, in this order:
  v_gs   gate-source voltage at the die, V
  i_l    current in the loop's inductance, A: the switch's terminal current less what the
         damping across the inductance carries
  v_ds   voltage across the switch, V
  v_r    voltage across the reverse path, cathode to anode, V
  q      charge still stored in the reverse path, C
  i_g    gate current, A (a state only where the gate loop has inductance)
  i_t    an IGBT's tail current: the stored charge swept out after the channel closes, A
  v_c    voltage of the decoupling capacitor, V (held at the supply where none is given)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

EPS_CURRENT = 1e-6  # A: below this no channel is said to conduct
SMOOTH = 0.05  # V: how softly a channel opens at its threshold
AVALANCHE = 0.05  # ohm: the slope of a transistor in avalanche
JOIN = 0.02
TURN = 0.5  # V: over which a gate-drain capacitance rises to the oxide's once the voltage turns  # V: over which a junction goes from blocking to conducting


@dataclass(frozen=True)
class Capacitance:
    """A capacitance that falls with the voltage across it as an abrupt junction's does:
    C(v) = c0 / sqrt(1 + v / v0), or a constant where v0 is None. The charge it holds from
    nought to v is in closed form, so a datasheet charge fixes c0. c_neg, where given, is
    what it rises to once the voltage has turned round: a gate above its drain sees the
    oxide whole, which is the charge a gate holds above its plateau."""

    c0: float
    v0: float | None = None
    c_neg: float | None = None

    def at(self, v: float) -> float:
        if v < 0 and self.c_neg is not None:
            return self.c0 + (self.c_neg - self.c0) * (1.0 - math.exp(v / TURN))
        if self.v0 is None:
            return self.c0
        return self.c0 / math.sqrt(1.0 + max(v, 0.0) / self.v0)

    def charge(self, v: float) -> float:
        if self.v0 is None:
            return self.c0 * v
        return 2.0 * self.c0 * self.v0 * (math.sqrt(1.0 + max(v, 0.0) / self.v0) - 1.0)

    @classmethod
    def holding(cls, q: float, v: float, v0: float | None) -> Capacitance:
        """The capacitance of this shape that holds the charge q at the voltage v."""
        unit = cls(1.0, v0)
        return cls(q / max(unit.charge(v), 1e-30), v0)

    def scaled(self, k: float) -> Capacitance:
        return replace(self, c0=self.c0 * k)


@dataclass(frozen=True)
class Table:
    """An output capacitance read from a tabulated output charge: C = dQ/dV between the
    points, carried past the last as an abrupt junction's."""

    v: tuple[float, ...]
    q: tuple[float, ...]

    def at(self, v: float) -> float:
        vs, qs = np.asarray(self.v), np.asarray(self.q)
        c = np.gradient(qs, vs)
        if v <= vs[-1]:
            return float(np.interp(max(v, vs[0]), vs, c))
        return float(c[-1] * math.sqrt(vs[-1] / v))

    def charge(self, v: float) -> float:
        if v <= self.v[-1]:
            return float(np.interp(max(v, 0.0), (0.0, *self.v), (0.0, *self.q)))
        return float(self.q[-1] * math.sqrt(v / self.v[-1]))

    def scaled(self, k: float) -> Table:
        return Table(self.v, tuple(x * k for x in self.q))


@dataclass(frozen=True)
class Gate:
    v_on: float  # V, the driver's high level
    v_off: float  # V, its low level (nought or below)
    rg: float  # ohm, in total: driver, external resistor and the chip's own
    l_g: float  # H, of the gate loop; nought leaves it out
    c_gs: float  # F
    c_gd: Capacitance  # against the drain-gate voltage
    v_th: float  # V
    k: float  # A/V^n, of the channel's saturation current above threshold
    n: float = 2.0  # the power the channel's current rises with above threshold


@dataclass(frozen=True)
class Switch:
    c_oss: Capacitance | Table  # drain to source in all, the gate-drain part with it
    r_on: float  # ohm, at the event's current and junction temperature
    v_knee: float = 0.0  # V, an IGBT's knee
    tail: float = 0.0  # an IGBT's tail current as a share of the channel's
    tau_tail: float = 0.0  # s, how fast the tail dies
    dynamic: float = 0.0  # an IGBT's drop just after turning on, over the settled one, less one
    v_br: float | None = None  # V, where a field-effect transistor avalanches; None: not modelled
    tail_range: tuple[float, float] = (0.0, 0.0)  # s, the least and the most the tail may take, for its class


@dataclass(frozen=True)
class Reverse:
    c_r: Capacitance | Table  # across the reverse path
    v_f: float  # V, its knee in forward conduction
    r_f: float  # ohm, its slope
    q_rr: float  # C, stored at the start of a turn-on
    q_soft: float  # C, the charge under which it stops conducting: the smaller, the snappier


@dataclass(frozen=True)
class Loop:
    v_dc: float
    i_load: float
    l: float  # H, all of the commutation loop: the common-source part among it
    r: float  # ohm, in series: the copper's and the parts' own at the event's frequencies
    r_damp: float = float("inf")  # ohm, across the inductance: what damps the ringing (see parts)
    l_cs: float = 0.0  # H, shared by the power loop and the gate loop
    c_dc: float | None = None  # F, the decoupling capacitor; None: the supply holds still


@dataclass(frozen=True)
class Circuit:
    loop: Loop
    gate: Gate
    switch: Switch
    reverse: Reverse


def softplus(x: float, width: float = SMOOTH) -> float:
    if x > 30 * width:
        return x
    return width * math.log1p(math.exp(x / width))


def channel(c: Circuit, v_gs: float, v_ds: float, slower: float = 1.0) -> float:
    """The current the channel carries: saturated at what the gate allows, resistive below
    it. slower multiplies its resistance, as an IGBT's just after it turns on."""
    g, s = c.gate, c.switch
    sat = g.k * softplus(v_gs - g.v_th) ** g.n
    if sat < EPS_CURRENT:
        return 0.0
    across = softplus(v_ds - s.v_knee, 0.05 * max(s.v_knee, 0.1)) if s.v_knee else v_ds
    r = s.r_on * (1.0 + s.tail) * slower
    return sat * math.tanh(across / (r * sat))


def igbt_channel(c: Circuit, v_gs: float, v_ds: float, i_t: float) -> float:
    """An IGBT's channel just after it turns on drops more than settled: its drift region
    fills with charge as the tail current, which stands for that charge, builds up."""
    s = c.switch
    i_ch = channel(c, v_gs, v_ds)
    if not s.dynamic or i_ch <= EPS_CURRENT:
        return i_ch
    filled = min(max(i_t / (s.tail * i_ch), 0.0), 1.0)
    return channel(c, v_gs, v_ds, 1.0 + s.dynamic * (1.0 - filled))


def reverse_current(c: Circuit, v_r: float, q: float) -> float:
    """Forward current through the reverse path. Forward biased it conducts; reverse biased
    it goes on conducting while charge is stored in it, less and less as the charge goes.
    The two are joined smoothly over a few tens of millivolts, as a junction joins them."""
    rv = c.reverse
    x = -v_r - rv.v_f
    on = 0.5 * (1.0 + math.tanh(x / (2 * JOIN)))
    stored = q / (q + rv.q_soft) if q > 0 else 0.0
    return x / rv.r_f * (on + (1.0 - on) * stored)


def terminal(c: Circuit, i_l: float, v_ds: float, v_r: float, v_c: float) -> float:
    """The current through the switch's terminals: the inductance's and the damping's across it."""
    lp = c.loop
    if math.isinf(lp.r_damp):
        return i_l
    return (i_l + (v_c - v_r - v_ds) / lp.r_damp) / (1.0 + lp.r / lp.r_damp)


def conducted(c: Circuit, v_gs: float, v_ds: float, i_t: float) -> float:
    """What the chip itself conducts: its channel, an IGBT's tail, and a transistor in
    avalanche. Its voltage times this is the power the chip turns into heat; the rest of its
    terminal current charges or empties its own capacitance, which stores the energy and
    gives it up at the next turn-on, inside the chip, where the terminals do not see it."""
    s = c.switch
    i_ch = igbt_channel(c, v_gs, v_ds, i_t) if s.tail else channel(c, v_gs, v_ds)
    if s.v_br is not None:
        i_ch += softplus(v_ds - s.v_br, 0.5) / AVALANCHE
    return i_ch + (i_t if s.tail else 0.0)


def rates(t: float, y: np.ndarray, c: Circuit, v_drive: float) -> list[float]:
    """The time derivative of every state."""
    v_gs, i_l, v_ds, v_r, q, i_g, i_t, v_c = y
    lp, g, s, rv = c.loop, c.gate, c.switch, c.reverse
    i = terminal(c, i_l, v_ds, v_r, v_c)
    di = (v_c - lp.r * i - v_r - v_ds) / lp.l
    if g.l_g > 0:
        di_g = (v_drive - g.rg * i_g - v_gs - lp.l_cs * di) / g.l_g
    else:
        i_g, di_g = (v_drive - v_gs - lp.l_cs * di) / g.rg, 0.0
    i_ch = igbt_channel(c, v_gs, v_ds, i_t) if s.tail else channel(c, v_gs, v_ds)
    if s.v_br is not None:
        # Past its breakdown a field-effect transistor conducts in avalanche and holds the voltage there.
        i_ch += softplus(v_ds - s.v_br, 0.5) / AVALANCHE
    di_t = (s.tail * i_ch - i_t) / s.tau_tail if s.tail else 0.0
    cgd = g.c_gd.at(v_ds - v_gs)
    cds = max(s.c_oss.at(v_ds) - cgd, 0.05 * s.c_oss.at(v_ds))
    # The gate node and the drain node share the gate-drain capacitance: two equations, solved together.
    a11, a12, a22 = g.c_gs + cgd, -cgd, cds + cgd
    det = a11 * a22 - a12 * a12
    b1, b2 = i_g, i - (i_ch + i_t)
    dv_gs = (b1 * a22 - a12 * b2) / det
    dv_ds = (a11 * b2 - a12 * b1) / det
    i_rev = reverse_current(c, v_r, q)
    # The reverse path carries what the switch does not of the load's current, from the
    # switch node up: through its junction, and the rest into its capacitance.
    dv_r = (i_rev - (lp.i_load - i)) / rv.c_r.at(v_r)
    dq = min(i_rev, 0.0) if q > 0 else 0.0
    dv_c = -i / lp.c_dc if lp.c_dc else 0.0
    return [dv_gs, di, dv_ds, dv_r, dq, di_g, di_t, dv_c]
