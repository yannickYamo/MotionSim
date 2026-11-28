"""The motor's iron, saturating: the currents of a permanent-magnet synchronous machine as a
function of its flux linkages, with each axis saturating by its own flux and the two axes
saturating each other.

The flux linkages are the state (they are what the voltage moves), and the currents follow
from them by an algebraic map drawn from one magnetic energy, so that the map is reciprocal
(∂id/∂ψq = ∂iq/∂ψd) and the torque 1.5·p·(ψd·iq − ψq·id) is the one the energy gives:

    id = (ψd − ψf)/Ld0 + g(ψd) − g(ψf) + ½·c·ψd·ψq²
    iq = ψq/Lq0 · (1 + kq·|ψq/ψqr|^T) + ½·c·ψd²·ψq
    g(ψ) = kd·ψ·|ψ/ψf|^S / Ld0

The d axis saturates on its whole flux, magnet and current together, so that a current that
adds to the magnet's flux sees less inductance than one that takes from it: the asymmetry a
drive reads the magnet's polarity by. The cross term lowers the d-axis flux as the q-axis
current rises (the magnet's flux falls under load) and the q-axis inductance as the d-axis
flux rises. With kd = kq = c = 0 the map is the linear machine, exactly.

It is calibrated from figures an engineer knows, or that are taken as usual for the kind of
motor and said to be taken: the small-signal Ld and Lq at no load (the datasheet's), the
magnet's flux, a rated current, and three shares at that current:

- d share: the apparent d-axis inductance, (ψd − ψf)/id, with id = +I and no q current, as a
  share of the small-signal Ld;
- q share: the apparent q-axis inductance, ψq/iq, with iq = I and id = 0, as a share of the
  small-signal Lq;
- cross share: how far the d-axis flux falls below the magnet's at that same point.

The form follows the algebraic models of saturated synchronous machines in the literature
(power functions of the flux linkages, drawn from one energy); its coefficients here are
solved in closed form from the three shares, except kd, which is found by bisection.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

S_D = 4.0  # the power the d axis saturates with
T_Q = 2.0  # the power the q axis saturates with
REACH = 3.0  # the map is held to be a proper (convex) energy up to this many times the rated current

# Shares usual for a kind of motor at its rated current, where nothing better is known: a
# surface-magnet motor saturates little (its magnets are a wide air gap), an interior one
# much on its q axis, whose path is all iron.
USUAL = {
    "surface": (0.92, 0.92, 0.02),
    "interior": (0.85, 0.70, 0.06),
}


@dataclass(frozen=True)
class Magnetics:
    """The calibrated map. Built by `calibrated`, never by hand."""

    psi_f: float  # Wb, the magnet's flux linkage
    ld0: float  # H, the d axis's unsaturated inductance
    lq0: float  # H, the q axis's
    kd: float
    kq: float
    cross: float  # A/Wb³
    psi_qr: float  # Wb, the q-axis flux at the rated current
    l_least: float  # H, the least incremental inductance within the reach: what a step is kept short against
    shares: tuple[float, float, float]  # the d, q and cross shares it was calibrated from

    def _g(self, psi_d: float) -> float:
        return self.kd * psi_d * abs(psi_d / self.psi_f) ** S_D / self.ld0

    def currents(self, psi_d: float, psi_q: float) -> tuple[float, float]:
        """The currents, A peak, the flux linkages, Wb peak, stand for."""
        c = self.cross
        i_d = (psi_d - self.psi_f) / self.ld0 + self._g(psi_d) - self._g(self.psi_f) + 0.5 * c * psi_d * psi_q * psi_q
        i_q = psi_q / self.lq0 * (1.0 + self.kq * abs(psi_q / self.psi_qr) ** T_Q) + 0.5 * c * psi_d * psi_d * psi_q
        return i_d, i_q

    def stiffness(self, psi_d: float, psi_q: float) -> tuple[float, float, float]:
        """∂id/∂ψd, ∂id/∂ψq (= ∂iq/∂ψd) and ∂iq/∂ψq: the inverse of the incremental inductances."""
        c = self.cross
        a = (1.0 + self.kd * (S_D + 1.0) * abs(psi_d / self.psi_f) ** S_D) / self.ld0 + 0.5 * c * psi_q * psi_q
        b = c * psi_d * psi_q
        d = (1.0 + self.kq * (T_Q + 1.0) * abs(psi_q / self.psi_qr) ** T_Q) / self.lq0 + 0.5 * c * psi_d * psi_d
        return a, b, d

    def fluxes(self, i_d: float, i_q: float) -> tuple[float, float]:
        """The flux linkages that carry these currents, by Newton's method from the linear guess."""
        a0, _, d0 = self.stiffness(self.psi_f, 0.0)
        psi_d, psi_q = self.psi_f + i_d / a0, i_q / d0
        for _ in range(60):
            e_d, e_q = self.currents(psi_d, psi_q)
            e_d, e_q = e_d - i_d, e_q - i_q
            a, b, d = self.stiffness(psi_d, psi_q)
            det = a * d - b * b
            step_d, step_q = (d * e_d - b * e_q) / det, (a * e_q - b * e_d) / det
            psi_d, psi_q = psi_d - step_d, psi_q - step_q
            if abs(step_d) + abs(step_q) <= 1e-14 * (abs(psi_d) + abs(psi_q) + self.psi_f):
                break
        return psi_d, psi_q

    def inductances(self, i_d: float, i_q: float) -> tuple[float, float, float]:
        """The incremental inductances Ldd, Ldq and Lqq, H, at these currents: what a small
        change of voltage meets, and what an injected signal reads."""
        a, b, d = self.stiffness(*self.fluxes(i_d, i_q))
        det = a * d - b * b
        return d / det, -b / det, a / det

    def torque(self, pole_pairs: int, i_d: float, i_q: float) -> float:
        psi_d, psi_q = self.fluxes(i_d, i_q)
        return 1.5 * pole_pairs * (psi_d * i_q - psi_q * i_d)


def calibrated(
    ld: float,
    lq: float,
    psi_f: float,
    i_rated: float,
    d_share: float,
    q_share: float,
    cross_share: float,
) -> Magnetics:
    """The map whose small-signal inductances at no load are ld and lq, and whose three shares
    at the rated current are those given. ValueError, in words, where no proper map has them."""
    if min(ld, lq, psi_f, i_rated) <= 0:
        raise ValueError("the inductances, the magnet's flux and the rated current must be above nought")
    if not (0.2 <= d_share <= 1.0 and 0.2 <= q_share <= 1.0 and 0.0 <= cross_share <= 0.5):
        raise ValueError("the d and q shares lie between 0.2 and 1, the cross share between 0 and 0.5")
    # d axis alone: small-signal Ld at the magnet's flux fixes Ld0 for a kd; the share fixes kd.
    target_d = psi_f + d_share * ld * i_rated

    def d_current(kd: float) -> float:
        ld0 = ld * (1.0 + kd * (S_D + 1.0))
        g = lambda p: kd * p * abs(p / psi_f) ** S_D / ld0  # noqa: E731
        return (target_d - psi_f) / ld0 + g(target_d) - g(psi_f)

    low, high = 0.0, 1.0
    while d_current(high) < i_rated:
        high *= 2.0
        if high > 1e9:
            raise ValueError("no d-axis saturation reaches that d share")
    if d_share >= 1.0:
        kd = 0.0
    else:
        for _ in range(200):
            mid = 0.5 * (low + high)
            low, high = (mid, high) if d_current(mid) < i_rated else (low, mid)
        kd = 0.5 * (low + high)
    ld0 = ld * (1.0 + kd * (S_D + 1.0))
    g = lambda p: kd * p * abs(p / psi_f) ** S_D / ld0  # noqa: E731
    # q axis with the cross term, at id = 0, iq = I: both in closed form.
    psi_q = q_share * lq * i_rated
    psi_d = psi_f * (1.0 - cross_share)
    cross = -2.0 * ((psi_d - psi_f) / ld0 + g(psi_d) - g(psi_f)) / (psi_d * psi_q * psi_q) if cross_share else 0.0
    if 1.0 / lq <= 0.5 * cross * psi_f * psi_f:
        raise ValueError("that cross share asks more of the q axis than its inductance allows")
    lq0 = 1.0 / (1.0 / lq - 0.5 * cross * psi_f * psi_f)
    psi_qr = lq * i_rated
    kq = ((i_rated - 0.5 * cross * psi_d * psi_d * psi_q) * lq0 / psi_q - 1.0) / abs(psi_q / psi_qr) ** T_Q
    if kq < -1e-12:
        raise ValueError("that q share and cross share together would need a q axis that grows with its current")
    kq = max(kq, 0.0)
    made = Magnetics(psi_f, ld0, lq0, kd, kq, cross, psi_qr, min(ld, lq), (d_share, q_share, cross_share))
    least = _least_inductance(made, i_rated)
    return Magnetics(psi_f, ld0, lq0, kd, kq, cross, psi_qr, least, (d_share, q_share, cross_share))


def _least_inductance(m: Magnetics, i_rated: float) -> float:
    """The least incremental inductance over the currents within REACH of the rated one, and a
    check that the energy is proper there (its stiffness positive definite)."""
    least = math.inf
    span = REACH * i_rated
    for k in range(-6, 7):
        for j in range(0, 7):
            psi_d, psi_q = m.fluxes(span * k / 6.0, span * j / 6.0)
            a, b, d = m.stiffness(psi_d, psi_q)
            det = a * d - b * b
            if a <= 0 or d <= 0 or det <= 0:
                raise ValueError("those shares give no proper magnetic energy within three times the rated current")
            # The least eigenvalue of the inductance matrix: one over the greatest of the stiffness's.
            top = 0.5 * (a + d) + math.sqrt(0.25 * (a - d) ** 2 + b * b)
            least = min(least, 1.0 / top)
    return least


def usual(kind: str, ld: float, lq: float, psi_f: float, i_rated: float) -> Magnetics:
    """The map taken as usual for a motor of this kind ("surface" where Lq is within 10 % of Ld,
    else "interior"), where nothing better is known: said to be taken wherever it is used."""
    return calibrated(ld, lq, psi_f, i_rated, *USUAL[kind])


def kind_of(ld: float, lq: float) -> str:
    return "interior" if lq > 1.1 * ld else "surface"
