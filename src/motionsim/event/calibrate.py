"""One free factor of each edge, found so that the energy the edge loses is the energy the
loss model counts at the same voltage, current, junction temperature and gate resistor.

What is seen of an edge (the loop's inductance, the capacitances, the recovery charge, the
gate resistor and the driver) is left as it was given or assumed. The free factor is what a
datasheet does not give: how much of the gate-drain charge the edge really moves at this
current, which sets how fast the voltage swings, and for an IGBT the share of its current
that is the tail. So the zoom never contradicts the loss chart: its area is the spike's.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from motionsim.event.circuit import Circuit
from motionsim.event.measure import Readout, turn_off, turn_on
from motionsim.event.run import Wave, edge_wave

TOLERANCE = 0.05  # the share the event's energy may differ from the loss model's
LOW, HIGH = 0.1, 10.0  # the range the factor on the gate-drain charge is looked for in
WIDE = (0.5, 2.0)  # inside these factors the edge keeps the shape its datasheet figures give it
TRIES = 9


@dataclass(frozen=True)
class Edge:
    """One edge, worked out and read, with the factor it was found at."""

    wave: Wave
    read: Readout
    factor: float  # on the gate-drain charge
    tail: float  # s, how long an IGBT's tail lasts; nought for a field-effect transistor
    target: float  # J, the loss model's energy
    met: bool  # the energy came within the tolerance
    recovery: float = 1.0  # on the reverse path's stored charge, at turn-on

    @property
    def corrected(self) -> bool:
        """The energy was met only by moving a figure more than a factor of two: the edge's
        energy is the datasheet's, its shape only indicative."""
        return not all(WIDE[0] <= x <= WIDE[1] for x in (self.factor, self.recovery))


def _run(
    c: Circuit, edge: str, rg: float, factor: float, tail: tuple[float, float], recovery: float = 1.0
) -> tuple[Wave, Readout]:
    g, s, rv = c.gate, c.switch, c.reverse
    k = replace(
        c,
        gate=replace(g, c_gd=g.c_gd.scaled(factor)),
        switch=replace(s, tail=tail[0], tau_tail=tail[1]),
        reverse=replace(rv, q_rr=rv.q_rr * recovery, q_soft=rv.q_soft * recovery),
    )
    w = edge_wave(k, edge, rg)
    read = (turn_on if edge == "on" else turn_off)(w, c.loop.v_dc, c.loop.i_load)
    return w, read


class _Tries:
    """Every edge worked out in a search, so that the one kept is never worked out twice."""

    def __init__(self, run) -> None:
        self.run = run
        self.seen: list[tuple[float, Wave, Readout]] = []

    def energy(self, x: float) -> float:
        w, read = self.run(x)
        self.seen.append((x, w, read))
        return read.energy

    def nearest(self, target: float) -> tuple[float, Wave, Readout]:
        return min(self.seen, key=lambda s: abs(math.log(max(s[2].energy, 1e-30) / target)))


def _search(tries: _Tries, target: float, low: float, high: float) -> bool:
    """Look for the factor at which the energy meets target: secant steps on the logarithms
    of both, held inside the bracket the tries so far have found, halving it (on the
    logarithm) where a step would leave it. True where it was met."""
    if target <= 0:
        return False
    miss = lambda e: math.log(max(e, 1e-30) / target)  # noqa: E731
    a, b = 1.0, 1.6
    ea, eb = tries.energy(a), tries.energy(b)
    for _ in range(TRIES):
        if abs(eb - target) <= TOLERANCE * target:
            return True
        below = [x for x, _, r in tries.seen if r.energy < target] or [low]
        above = [x for x, _, r in tries.seen if r.energy > target] or [high]
        # The energy rises with the factor: the answer lies between the largest factor below
        # and the smallest above, where the tries so far put it.
        lo, hi = max(below), min(above)
        if lo >= hi or (lo == low and b == low) or (hi == high and b == high):
            return False
        da, db = miss(ea), miss(eb)
        step = -db * (math.log(b) - math.log(a)) / (db - da) if db != da else 0.0
        x = b * math.exp(max(min(step, 6.0), -6.0))
        if not lo < x < hi:
            x = math.sqrt(lo * hi)
        a, ea, b, eb = b, eb, x, tries.energy(x)
    return abs(eb - target) <= TOLERANCE * target


def calibrated(c: Circuit, edge: str, rg: float, target: float) -> Edge:
    """The edge at the factor that makes its energy the loss model's.

    For an IGBT's turn-off it is how long the tail lasts, with the gate-drain charge as
    tabulated or assumed; only where no tail can meet the energy is the charge moved too."""
    s = c.switch
    tail = (s.tail, s.tau_tail)
    if s.tail and edge == "off":
        low, high = s.tail_range
        tries = _Tries(lambda x: _run(c, edge, rg, 1.0, (s.tail, x * s.tau_tail)))
        met = _search(tries, target, low / s.tau_tail, high / s.tau_tail)
        x, w, read = tries.nearest(target)
        if met:
            return Edge(w, read, 1.0, x * s.tau_tail, target, True)
        tail = (s.tail, min(max(x * s.tau_tail, low), high))
    recovery = 1.0
    if edge == "on" and c.reverse.q_rr > 0:
        # The recovery charge, most often itself worked out from a recovery energy, is the
        # least known figure of a turn-on: it is moved first, within a factor of two.
        tries = _Tries(lambda x: _run(c, edge, rg, 1.0, tail, x))
        met = _search(tries, target, *WIDE)
        x, w, read = tries.nearest(target)
        if met:
            return Edge(w, read, 1.0, tail[1] if s.tail else 0.0, target, True, recovery=x)
        recovery = min(max(x, WIDE[0]), WIDE[1])
    tries = _Tries(lambda x: _run(c, edge, rg, x, tail, recovery))
    met = _search(tries, target, LOW, HIGH)
    x, w, read = tries.nearest(target)
    return Edge(w, read, x, tail[1] if s.tail else 0.0, target, met, recovery=recovery)
