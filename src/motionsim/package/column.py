"""Heat flowing straight down from a die to the package's case, through time.

Under a die soldered to thick copper, on a discrete package's tab or a ceramic
substrate, heat goes down: through the die, the die attach, and the copper, widening
as it goes at a spreading angle. The case face under it is taken to be at one
temperature, which is what a junction-to-case figure means. That is transient
conduction in one dimension,

    c(z) · A(z) · dT/dt = d/dz ( k(z) · A(z) · dT/dz ) ,   heat in at the top, T = 0 at the case,

with A the area the heat has spread to at depth z. It is cut into thin slices, each a heat
capacity between two resistances, and that ladder is solved exactly: its modes are the
stages of the response, each a resistance with a time constant. The time constants follow
from thicknesses and diffusivities; nothing is fitted.

At times too short for the heat to have left the die the response is that of a body
without end, 2·sqrt(t/π) / (e·A) with e = sqrt(k·c) of the die, and at long times it is the
sum of the layers' resistances. Both are held by tests.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


# SciPy takes a good part of a second to load, and most runs never reach this: it is
# loaded at the first call.
def eigh_tridiagonal(*args, **kwargs):
    from scipy.linalg import eigh_tridiagonal as loaded

    return loaded(*args, **kwargs)


@dataclass(frozen=True)
class Layer:
    """One layer under the die. k in W/(m·K), c in J/(m3·K), thickness in m."""

    k: float
    c: float
    thickness: float
    spreads: bool = False  # the heat widens in it, at the column's angle
    slices: int = 8


@dataclass(frozen=True)
class Column:
    """A square die and the layers under it, top to bottom, down to the case face."""

    side: float  # m, of the die
    layers: tuple[Layer, ...]
    angle: float = 45.0  # degrees from the vertical at which heat widens in a layer that spreads
    widest: float = float("inf")  # m: the copper is no wider than this

    def _slices(self) -> tuple[np.ndarray, np.ndarray]:
        """Resistance of every slice, K/W, and its heat capacity, J/K, from the junction down.

        A layer's slices grow from its top: the first of the die is thin enough to follow
        the first microseconds, and the last are no finer than the slow end needs.
        """
        grow = 2 * np.tan(np.radians(self.angle))
        side = self.side
        r, c = [], []
        for layer in self.layers:
            cuts = np.geomspace(1.0, 1.35**layer.slices, layer.slices + 1) - 1.0
            cuts = layer.thickness * cuts / cuts[-1]
            for top, bottom in zip(cuts[:-1], cuts[1:], strict=True):
                dz = bottom - top
                if layer.spreads:
                    a, b = min(side + grow * top, self.widest), min(side + grow * bottom, self.widest)
                else:
                    a = b = side
                # Between two squares of sides a and b the resistance is dz / (k·a·b) exactly,
                # for a side that grows in a straight line.
                r.append(dz / (layer.k * a * b))
                c.append(layer.c * dz * (a * a + a * b + b * b) / 3)
            if layer.spreads:
                side = min(side + grow * layer.thickness, self.widest)
        return np.array(r), np.array(c)

    @property
    def resistance(self) -> float:
        """Junction to case, K/W: the layers in series."""
        return float(self._slices()[0].sum())

    def stages(self) -> tuple[np.ndarray, np.ndarray]:
        """The step response as stages: resistances in K/W and time constants in s.

        The temperatures sit where the slices meet, the junction being the first; each holds
        half the heat capacity of the slice on either side, and the last, on the case, is
        held at zero. With C the capacities and K the conductances between them,
        C·dT/dt = −K·T + P at the junction. Made symmetric by the square root of C, its
        eigenvalues are one over the time constants, and the junction's share of each mode
        is that stage's resistance.
        """
        r, c = self._slices()
        g = 1.0 / r
        node_c = np.empty(r.size)
        node_c[0] = c[0] / 2
        node_c[1:] = (c[:-1] + c[1:]) / 2
        diagonal = np.empty(r.size)
        diagonal[0] = g[0]
        diagonal[1:] = g[:-1] + g[1:]
        root = np.sqrt(node_c)
        values, vectors = eigh_tridiagonal(diagonal / node_c, -g[:-1] / (root[:-1] * root[1:]))
        stage_r = vectors[0] ** 2 / (node_c[0] * values)
        return stage_r, 1.0 / values


def sized(resistance: float, layers: tuple[Layer, ...], angle: float, widest: float) -> Column:
    """The column whose die is the size that gives this junction-to-case resistance.

    A datasheet's resistance is the one figure that says how large the die is: a larger
    die has a lower one. Where no die that fits the copper is large enough, the die is as
    wide as the copper; where none is small enough to be a power chip, it is 0.3 mm.
    """
    low, high = 0.3e-3, min(widest, 0.1)
    if Column(high, layers, angle, widest).resistance >= resistance:
        return Column(high, layers, angle, widest)
    if Column(low, layers, angle, widest).resistance <= resistance:
        return Column(low, layers, angle, widest)
    for _ in range(60):
        middle = 0.5 * (low + high)
        if Column(middle, layers, angle, widest).resistance > resistance:
            low = middle
        else:
            high = middle
    return Column(0.5 * (low + high), layers, angle, widest)


def trimmed(r: np.ndarray, tau: np.ndarray, least: float = 2e-4) -> tuple[tuple[float, float], ...]:
    """Stages as (share of the whole resistance, time constant), slowest first, with those
    that carry next to nothing folded into the fastest one kept: the whole stays the whole."""
    total = float(r.sum())
    order = np.argsort(-tau)
    kept = [(float(r[k]) / total, float(tau[k])) for k in order if r[k] >= least * total]
    lost = 1.0 - sum(share for share, _ in kept)
    share, fastest = kept[-1]
    kept[-1] = (share + lost, fastest)
    return tuple(kept)
