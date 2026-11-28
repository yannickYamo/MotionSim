"""What the stage does once the drive trips: its safe state, in place of the scheme's switching.

Three safe states, as drives use them:

- "off": every gate off (pulse-off). Each leg then conducts through one of its two diodes, by
  the sign of its current: into the motor through the low one (the terminal at −v_drop), out of
  it through the high one (at v_dc + v_drop). A leg with no current floats: both its diodes
  block while its terminal stands between the two rails, which it does wherever the motor's
  own voltage keeps it there. Below the speed at which the magnet's line voltage reaches the
  DC link, the currents die out and the motor makes no torque; above it the legs are a diode
  bridge, the motor a generator into the link, and the current it returns is uncontrolled.
- "short": the three low switches on (active short circuit). The winding is shorted on itself:
  no current reaches the link, and the currents settle where the magnet's voltage drives them
  through the winding's own impedance, about −ψ/Ld on the d axis at speed, with a braking
  torque that is largest at low speed.
- "hybrid": shorted above that speed, off below it, which keeps the link from being charged
  at speed and the braking torque low near standstill.

The switched-off legs are taken through each period in short steps. In each, the voltage of a
floating leg is the one that keeps its current at nought through the step, found from the plant
itself (the currents after a step are affine in the voltage across the motor), so it holds for
saturating iron as for constant inductances. A conducting leg whose current passes through
nought within a step is stopped there, its diode blocking, and the rest of the step is taken
with it floating.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from motionsim.control.kernel import Kernel

SQRT3 = math.sqrt(3.0)
SAFE_STATES = ("off", "short", "hybrid")
# The code each state is put on the bus with (`inverter.safe`); nought while the scheme switches.
CODE = {"off": 1.0, "short": 2.0}
# A hybrid leaves the short circuit only below this share of the speed it enters it at: the
# magnet's voltage near the link's would otherwise take it back and forth. This tool's choice.
BAND = 0.95
# The most electrical angle one step of the switched-off legs turns through, rad.
TURN = 0.02
LEAST_STEPS = 16


def bridge_speed(psi: float, v_dc: float, v_drop: float) -> float:
    """rad/s electrical: the speed at which the peak of the magnet's line-to-line voltage, √3·ωe·ψ,
    reaches the DC link and two diodes' drops. Above it, legs switched off make the motor a
    generator into the link."""
    return (v_dc + 2.0 * v_drop) / (SQRT3 * psi) if psi > 0 else math.inf


def _alpha_beta(v: list[float]) -> tuple[float, float]:
    return (2.0 * v[0] - v[1] - v[2]) / 3.0, (v[1] - v[2]) / SQRT3


class SafeStage:
    """The stage in its safe state, period by period, on the kernel's plant."""

    def __init__(self, kernel: Kernel, mode: str, psi: float) -> None:
        self.k, self.mode = kernel, mode
        drop = kernel.inverter.v_drop
        self.low, self.high = -drop, kernel.v_dc + drop
        self.w_bridge = bridge_speed(psi, kernel.v_dc, drop)
        self.code = 0.0
        self.blocked = [False, False, False]
        self.link = 0.0  # C into the link's positive rail through the period

    def _chosen(self, w_e: float) -> str:
        if self.mode != "hybrid":
            return self.mode
        if self.code == CODE["short"]:
            return "short" if abs(w_e) > BAND * self.w_bridge else "off"
        return "short" if abs(w_e) > self.w_bridge else "off"

    def period(self, ts: float) -> float:
        """The stage through one period in its safe state. Returns the mean current it returned
        to the DC link through the period, A."""
        k = self.k
        w_e = k.plant._p * k.plant.w_m
        chosen = self._chosen(w_e)
        self.code, self.link = CODE[chosen], 0.0
        if chosen == "short":
            self.blocked = [False, False, False]
            k.state = 0
            k._stretch(0, ts)
            return 0.0
        n = max(LEAST_STEPS, math.ceil(abs(w_e) * ts / TURN))
        for _ in range(n):
            self._step(ts / n)
        return self.link / ts

    # The switched-off legs.

    def _currents(self) -> list[float]:
        return [self.k.ia, self.k.ib, self.k.ic]

    def _tried(self, v: list[float], h: float) -> list[float]:
        """The phase currents a step of h seconds with these leg voltages would end at."""
        plant = self.k.plant
        kept = plant.kept()
        plant.advance(*_alpha_beta(v), h)
        out = list(plant.phase_currents())
        plant.restore(kept)
        return out

    def _voltages(self, h: float) -> list[float]:
        """The legs' voltages through the next step: a conducting leg at the rail its diode ties
        it to, a floating one where its current stays at nought, or, where no such voltage lies
        between the rails, at the rail it is taken to (its diode then conducting)."""
        now, low, high = self._currents(), self.low, self.high
        for leg in range(3):
            if not self.blocked[leg] and now[leg] == 0.0:
                self.blocked[leg] = True
        if sum(self.blocked) >= 2:
            # Two legs with no current leave none for the third: all three float.
            self.blocked = [True, True, True]
        v = [0.0 if self.blocked[leg] else (low if now[leg] > 0.0 else high) for leg in range(3)]
        floating = [leg for leg in range(3) if self.blocked[leg]]
        if not floating:
            return v
        if len(floating) == 1:
            return self._floated(v, floating[0], h)
        # All three float: the voltage across the motor that keeps every current at nought, which
        # is its own; the legs follow it where its spread fits between the rails.
        legs = self._unloaded(h)
        if legs is None:
            return [0.5 * (low + high)] * 3
        if max(legs) - min(legs) <= high - low:
            return legs  # their common part moves no current: there is no path for it
        # The motor's voltage passes the link's: the legs at its two ends conduct, the middle one
        # floats. Their currents start from nought, in the diodes the motor's voltage drives them through.
        top, bottom = legs.index(max(legs)), legs.index(min(legs))
        self.blocked = [True, True, True]
        self.blocked[top] = self.blocked[bottom] = False
        v = [0.0, 0.0, 0.0]
        v[top], v[bottom] = high, low
        return self._floated(v, 3 - top - bottom, h)

    def _floated(self, v: list[float], x: int, h: float) -> list[float]:
        """Leg x's voltage where its current ends the step at nought, the others' as given: from the
        two rails' currents (it is affine in the voltage, growing with it, for constant inductances),
        then by secants on the plant's own currents, which saturating iron bends. Where that voltage
        lies past a rail, the leg is at the rail and its diode conducts."""
        low, high = self.low, self.high
        v[x] = low
        a, i_a = low, self._tried(v, h)[x]
        v[x] = high
        b, i_b = high, self._tried(v, h)[x]
        if i_a == i_b:
            v[x] = 0.5 * (low + high)
            return v
        wanted = a - i_a * (b - a) / (i_b - i_a)
        if low <= wanted <= high:
            scale = max(abs(i_a), abs(i_b))
            for _ in range(3):
                v[x] = wanted
                now = self._tried(v, h)[x]
                if abs(now) <= 1e-12 * scale:
                    break
                # The nearer of the two ends is replaced: a secant on the curve as the plant has it.
                if abs(i_a) < abs(i_b):
                    b, i_b = wanted, now
                else:
                    a, i_a = wanted, now
                if i_a == i_b:
                    break
                wanted = min(max(a - i_a * (b - a) / (i_b - i_a), low), high)
            v[x] = wanted
            return v
        v[x] = high if wanted > high else low
        self.blocked[x] = False
        return v

    def _unloaded(self, h: float) -> list[float] | None:
        """Leg voltages (up to a common part, which moves no current) that keep all three currents
        at nought through the step: Newton's rule on the plant's own currents, its slopes taken once."""
        step = 0.01 * (self.high - self.low)
        legs = [0.0, 0.0, 0.0]
        base = self._tried(legs, h)
        da = self._tried([step, 0.0, 0.0], h)
        db = self._tried([0.0, step, 0.0], h)
        m00, m01 = (da[0] - base[0]) / step, (db[0] - base[0]) / step
        m10, m11 = (da[1] - base[1]) / step, (db[1] - base[1]) / step
        det = m00 * m11 - m01 * m10
        if det == 0.0:
            return None
        scale = max(abs(base[0]), abs(base[1]), 1e-300)
        now = base
        for _ in range(4):
            legs[0] -= (now[0] * m11 - now[1] * m01) / det
            legs[1] -= (now[1] * m00 - now[0] * m10) / det
            now = self._tried(legs, h)
            if max(abs(now[0]), abs(now[1])) <= 1e-12 * scale:
                break
        return legs

    def _step(self, h: float) -> None:
        """One short step of the switched-off legs, stopped where a conducting leg's current
        reaches nought and taken on from there with that leg floating."""
        k = self.k
        left = h
        for _ in range(6):
            if left <= 0.0:
                return
            v = self._voltages(left)
            before = self._currents()
            kept = k.plant.kept()
            after = self._tried(v, left)
            crossing = [
                (before[leg] / (before[leg] - after[leg]), leg)
                for leg in range(3)
                if not self.blocked[leg] and before[leg] != 0.0 and before[leg] * after[leg] <= 0.0
            ]
            if not crossing:
                self._taken(v, left, before)
                return
            share, first = min(crossing)
            k.plant.restore(kept)
            for _ in range(3):
                # A floating leg's voltage is the one for the step as it is shortened.
                share = self._reaching(v, left, share, first, before[first])
                v = self._voltages(share * left)
            self._taken(v, share * left, before)
            for f, leg in crossing:
                if f <= share + 1e-9:
                    self.blocked[leg] = True
            left -= share * left
        if left > 0.0:
            self._taken(self._voltages(left), left, self._currents())

    def _reaching(self, v: list[float], h: float, share: float, leg: int, start: float) -> float:
        """The share of a step at which a leg's current reaches nought, from the straight line's
        guess, by secants on the plant's own currents: a few, to a millionth of the current."""
        lo, at_lo = 0.0, start
        for _ in range(4):
            now = self._tried(v, share * h)[leg]
            if abs(now) <= 1e-9 * abs(start):
                break
            nxt = share - now * (share - lo) / (now - at_lo) if now != at_lo else share
            lo, at_lo, share = share, now, min(max(nxt, 0.0), 1.0)
        return share

    def _taken(self, v: list[float], h: float, before: list[float]) -> None:
        """A step taken: the plant moved, and what the kernel gathers of it."""
        k = self.k
        if h <= 0.0:
            return
        k.plant.advance(*_alpha_beta(v), h)
        after = list(k.plant.phase_currents())
        k.ia, k.ib, k.ic = after
        for leg in range(3):
            if not self.blocked[leg] and v[leg] == self.high:
                self.link -= 0.5 * (before[leg] + after[leg]) * h
        if k.gather:
            k.energy += k.plant.work
            third = h / 3.0
            for leg in range(3):
                a0, a1 = before[leg], after[leg]
                if abs(a1) > k.peak[leg]:
                    k.peak[leg] = abs(a1)
                if self.blocked[leg]:
                    continue
                # Through the high diode (index 1 of the leg's four) or the low one (index 2).
                i = 4 * leg + (1 if v[leg] == self.high else 2)
                k.T[i] += h
                k.Q[i] += third * (a0 * a0 + a0 * a1 + a1 * a1)
        if k.detailing:
            p = k.plant
            k.corners.append((p.time, after[0], after[1], after[2], -1, p.torque, p.i_d, p.i_q, p.theta))
