"""Finite-control-set model predictive current control: the controller that has no
modulator. At each sampling instant it tries each of the eight states the three legs can
take, predicts the current each would give one step on, and takes the one that costs least.
The switches change only when it chooses another state, so the switching frequency is not
set: it falls out of the current, the voltage and the weight put on a commutation."""

from __future__ import annotations

import math

from motionsim.control.blocks import Block, Param, Port, register
from motionsim.control.plant import ALPHA, BETA

SQRT3 = math.sqrt(3.0)
# How many legs change between two states of the three legs.
CHANGES = tuple(tuple(bin(a ^ b).count("1") for b in range(8)) for a in range(8))


@register
class FcsMpc(Block):
    kind = "fcs_mpc"
    role = "inner_regulator"
    title = "Predictive current control (finite control set)"
    summary = (
        "Picks one of the eight leg states each sample: the one whose predicted current lands nearest the "
        "reference, each commutation charged a cost. No modulator, no integrator."
    )
    definition = (
        "Chooses the state of the three legs directly, with no modulator: of the eight, the one whose "
        "predicted current one step on lies nearest the reference, a commutation costing λ amperes. With "
        "the one-sample delay, the current is first predicted to the instant the choice takes effect. The "
        "cost can be taken in its squared form, |i* − i|² + λu·n; a commutation can be charged by the "
        "switching energy of the leg at the current it would switch, so that the leg carrying little "
        "current is the cheap one to move; and two steps can be looked ahead in place of one. There is no "
        "integrator: a wrong inductance, resistance or flux leaves a steady current error."
    )
    math = (
        r"i_{dq}[k+1] = i_{dq}[k] + T_s\,L^{-1}\!\left(v_{dq}(s) - R\,i_{dq}[k] - \omega_e J L\,i_{dq}[k] - \omega_e \psi\,e_q\right)",
        r"g(s) = \left|i_d^* - i_d[k+2]\right| + \left|i_q^* - i_q[k+2]\right| + \lambda\,n_{sw}(s, s_{k+1})",
        r"s_{k+1}^{\,next} = \arg\min_{s \in \{0..7\}} g(s)",
        r"g_2(s) = \left|i^* - i[k+2]\right|^2 + \lambda_u\,n_{sw}\ \text{(squared)},\qquad "
        r"n_{sw} \to \sum_{x\ \text{switching}} \frac{E_{sw}(|i_x|)}{\overline{E_{sw}}},\quad "
        r"\overline{E_{sw}} = e_0 + e_1 \tfrac{2}{\pi} |i^*|\ \text{(loss)}",
    )
    inputs = (
        Port("id_ref", "A", "d-axis current reference"),
        Port("iq_ref", "A", "q-axis current reference"),
        Port("i_d", "A", "d-axis current as measured"),
        Port("i_q", "A", "q-axis current as measured"),
        Port("theta", "rad", "electrical angle"),
        Port("omega_e", "rad/s", "electrical speed"),
        Port("v_dc", "V", "DC voltage"),
    )
    outputs = (
        Port("s_a", "", "leg a: 1 with the high side on"),
        Port("s_b", "", "leg b: 1 with the high side on"),
        Port("s_c", "", "leg c: 1 with the high side on"),
        Port("cost", "A", "cost of the state chosen (A² with the squared cost)"),
        Port("chosen", "", "the state chosen, 0 to 7: leg a is bit 0, b bit 1, c bit 2"),
        *(Port(f"cost_{s}", "A", f"cost of state {s} (a{s & 1} b{(s >> 1) & 1} c{(s >> 2) & 1})") for s in range(8)),
    )
    params = (
        Param("weight", "A", 0.0, "λ: what one leg's commutation costs, in the unit of the current term", 0.0, 1e6),
        Param("delay_compensation", "", True, "predict to the instant the choice takes effect first"),
        Param(
            "cost",
            "",
            "abs",
            "the current term: the sum of the two axes' errors (abs, A), or the error's square (squared, A²)",
            choices=("abs", "squared"),
        ),
        Param(
            "weighting",
            "",
            "count",
            "what a commutation costs: λ each (count), or λ times that leg's switching energy at its "
            "current over the mean energy of a commutation through a turn at the current asked for (loss): "
            "the same λ then charges a turn's commutations about alike either way",
            choices=("count", "loss"),
        ),
        Param("horizon", "steps", 1.0, "steps looked ahead: 1, or 2 (every pair of states is tried)", 1.0, 2.0),
    )
    loop = "current"

    def setup(self) -> None:
        p = self.p
        self._plain = p["cost"] == "abs" and p["weighting"] == "count" and int(p["horizon"]) == 1
        self._squared = p["cost"] == "squared"
        self._by_loss = p["weighting"] == "loss"
        self._two = int(p["horizon"]) >= 2
        stage, limit = self.ctx.stage, self.ctx.i_limit
        self._limit = limit if math.isfinite(limit) else 0.0
        # A leg's commutation at a current: by the device's own switching-energy line where a
        # device is known, else in proportion to the current.
        if stage is not None and stage.e0 + stage.e1 > 0:
            self._e0, self._e1 = stage.e0, stage.e1
        else:
            self._e0, self._e1 = 0.0, 1.0

    def reset(self) -> None:
        self._state = 0  # the state standing on the legs through the period now beginning

    def _ahead(self, i_d: float, i_q: float, v_d: float, v_q: float, w: float) -> tuple[float, float]:
        """One sampling period on, by one forward step of the motor's equations."""
        c = self.ctx
        return (
            i_d + c.ts * (v_d - c.rs * i_d + w * c.lq * i_q) / c.ld,
            i_q + c.ts * (v_q - c.rs * i_q - w * (c.ld * i_d + c.psi)) / c.lq,
        )

    def step(self, t: float, *inputs: float) -> tuple[float, ...]:
        id_ref, iq_ref, i_d, i_q, theta, w, v_dc = inputs
        ts = self.ctx.ts
        standing = self._state
        if self.ctx.delay and self.p["delay_compensation"]:
            # What is chosen now stands from the next instant: the current is taken there
            # first, under the state that stands until then, at the angle of mid-period.
            angle = theta + 0.5 * w * ts
            cs, sn = math.cos(angle), math.sin(angle)
            va, vb = v_dc * ALPHA[standing], v_dc * BETA[standing]
            i_d, i_q = self._ahead(i_d, i_q, va * cs + vb * sn, vb * cs - va * sn, w)
            theta += w * ts
        if not self._plain:
            best, least, costs = self._weighed(id_ref, iq_ref, i_d, i_q, theta, w, v_dc)
            self._state = best
            return float(best & 1), float((best >> 1) & 1), float((best >> 2) & 1), least, float(best), *costs
        angle = theta + 0.5 * w * ts
        cs, sn = math.cos(angle), math.sin(angle)
        weight = self.p["weight"]
        changes = CHANGES[standing]
        best, least = standing, math.inf
        costs = [0.0] * 8
        for state in range(8):
            va, vb = v_dc * ALPHA[state], v_dc * BETA[state]
            p_d, p_q = self._ahead(i_d, i_q, va * cs + vb * sn, vb * cs - va * sn, w)
            cost = costs[state] = abs(id_ref - p_d) + abs(iq_ref - p_q) + weight * changes[state]
            if cost < least - 1e-12 or (cost <= least + 1e-12 and changes[state] < changes[best]):
                best, least = state, cost
        self._state = best
        return float(best & 1), float((best >> 1) & 1), float((best >> 2) & 1), least, float(best), *costs

    def _legs(self, i_d: float, i_q: float, theta: float, asked: float) -> tuple[float, float, float]:
        """What a commutation of each leg costs at the currents it would switch, in λ: its
        switching energy over the mean of one through a turn at the current asked for."""
        if not self._by_loss:
            return 1.0, 1.0, 1.0
        cs, sn = math.cos(theta), math.sin(theta)
        alpha, beta = i_d * cs - i_q * sn, i_d * sn + i_q * cs
        e0, e1 = self._e0, self._e1
        # No current asked for: the mean is taken at a twentieth of the limit, not at nought.
        mean = e0 + e1 * (2.0 / math.pi) * max(asked, 0.05 * self._limit, 1e-9)
        return (
            (e0 + e1 * abs(alpha)) / mean,
            (e0 + e1 * abs(-0.5 * alpha + 0.5 * SQRT3 * beta)) / mean,
            (e0 + e1 * abs(-0.5 * alpha - 0.5 * SQRT3 * beta)) / mean,
        )

    def _error(self, id_ref: float, iq_ref: float, p_d: float, p_q: float) -> float:
        e_d, e_q = id_ref - p_d, iq_ref - p_q
        cost = e_d * e_d + e_q * e_q if self._squared else abs(e_d) + abs(e_q)
        if self._limit and p_d * p_d + p_q * p_q > self._limit * self._limit:
            cost += 1e9  # a state that takes the current past the drive's limit is never chosen
        return cost

    def _weighed(
        self, id_ref: float, iq_ref: float, i_d: float, i_q: float, theta: float, w: float, v_dc: float
    ) -> tuple[int, float, list[float]]:
        """The state of least cost with the cost in its general form: the current term squared
        or not, a commutation weighed by count or by its switching energy, one step ahead or
        two. Looking two steps ahead, each first state is charged with the best that can
        follow it, and the first state of the best pair is taken."""
        ts, weight = self.ctx.ts, self.p["weight"]
        standing = self._state
        legs = self._legs(i_d, i_q, theta, math.hypot(id_ref, iq_ref))
        first = _turned(v_dc, theta + 0.5 * w * ts)
        second = _turned(v_dc, theta + 1.5 * w * ts) if self._two else first
        best, least, fewest = standing, math.inf, 9
        costs = [0.0] * 8
        for state in range(8):
            p_d, p_q = self._ahead(i_d, i_q, first[state][0], first[state][1], w)
            cost = self._error(id_ref, iq_ref, p_d, p_q) + weight * _switched(standing ^ state, legs)
            if self._two:
                then = math.inf
                for after in range(8):
                    q_d, q_q = self._ahead(p_d, p_q, second[after][0], second[after][1], w)
                    tried = self._error(id_ref, iq_ref, q_d, q_q) + weight * _switched(state ^ after, legs)
                    if tried < then:
                        then = tried
                cost += then
            costs[state] = cost
            changed = CHANGES[standing][state]
            if cost < least - 1e-12 or (cost <= least + 1e-12 and changed < fewest):
                best, least, fewest = state, cost, changed
        return best, least, costs


def _turned(v_dc: float, angle: float) -> list[tuple[float, float]]:
    """The eight states' voltages seen from the rotor at an angle: d and q of each."""
    cs, sn = math.cos(angle), math.sin(angle)
    return [(v_dc * (ALPHA[s] * cs + BETA[s] * sn), v_dc * (BETA[s] * cs - ALPHA[s] * sn)) for s in range(8)]


def _switched(changed: int, legs: tuple[float, float, float]) -> float:
    """The cost of the legs that change, each at its own."""
    return (legs[0] if changed & 1 else 0.0) + (legs[1] if changed & 2 else 0.0) + (legs[2] if changed & 4 else 0.0)
