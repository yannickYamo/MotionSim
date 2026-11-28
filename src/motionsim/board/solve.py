"""A loop's inductance and resistance from its network of bars.

The loop is driven where its capacitor (or its driver) is, and two currents are worked out.
The first is the one a steady voltage drives, shared out by the copper's resistance; from it
come the loop's resistance and an inductance, sum of I_i·I_j·M_ij over every two bars. The
second is the one a fast edge drives, shared out so that the magnetic energy is least, found
by conjugate gradients among the currents that keep Kirchhoff's current law. Whatever current
keeps that law gives an inductance at or above the least (Thomson's principle), so stopping
the search early only leaves the figure on the high side, never under.

How long the search may go on is counted in work, never in time: a step costs what its
transforms cost, by the size of the mesh and the layers that carry current, and a search is
given so many of those. The same network is then searched the same number of steps on any
machine, however busy, and gives the same figure.

The mutual of every two flat bars depends only on how many cells apart they are, so the sum
over all pairs is a convolution, taken with the fast Fourier transform.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy import fft, sparse
from scipy.sparse import csgraph
from scipy.sparse.linalg import splu

from motionsim.board.induct import MU0, tape_table
from motionsim.board.mesh import Grid, Network, Unsolved

MOST_STEPS = 400  # of the search for the least-energy current
CLOSE_ENOUGH = 3e-4  # the search stops where its residual has fallen this far


class Kernel:
    """Every bar's partial inductance with every other, as something to multiply a current by."""

    def __init__(self, grid: Grid) -> None:
        self.grid = grid
        self.p = grid.pitch * 1e-3
        self.z = [z * 1e-3 for z in grid.heights()]
        self.shape = (fft.next_fast_len(2 * grid.ny - 1, real=True), fft.next_fast_len(2 * grid.nx - 1, real=True))
        self._tables: dict[tuple[int, int], np.ndarray] = {}
        self.upright = self._upright()

    def _table(self, dz: float, kind: int) -> np.ndarray:
        """The transform of the table of mutuals at one height apart, for bars along x or y."""
        key = (round(dz * 1e9), kind)
        if key not in self._tables:
            ny, nx = self.grid.ny, self.grid.nx
            # [across, along]: a bar along x has its columns along it, a bar along y its rows.
            table = tape_table(self.p, nx, ny, dz) if kind == 0 else tape_table(self.p, ny, nx, dz).T
            table = table[:ny, :nx]
            wrapped = np.zeros(self.shape)
            wrapped[:ny, :nx] = table
            wrapped[-(ny - 1) :, :nx] = table[:0:-1, :]
            wrapped[:ny, -(nx - 1) :] = table[:, :0:-1]
            wrapped[-(ny - 1) :, -(nx - 1) :] = table[:0:-1, :0:-1]
            self._tables[key] = fft.rfft2(wrapped)
        return self._tables[key]

    def _upright(self) -> np.ndarray:
        """The upright bars' partial inductances, each with each: parallel filaments, a
        via's own being a thin tube's."""
        g = self.grid
        if not g.zj.size:
            return np.zeros((0, 0))
        top = np.array([g.layers[k].z for k in g.zl1]) * 1e-3
        bottom = np.array([g.layers[k].z for k in g.zl2]) * 1e-3
        d = np.hypot((g.zi[:, None] - g.zi[None, :]) * self.p, (g.zj[:, None] - g.zj[None, :]) * self.p)
        d = np.where(d > 0, d, g.zr[:, None] * 1e-3)

        def f(s):
            return s * np.arcsinh(s / d) - np.hypot(s, d)

        a1, a2, b1, b2 = top[:, None], bottom[:, None], top[None, :], bottom[None, :]
        return MU0 / (4 * np.pi) * (f(a2 - b1) - f(a2 - b2) - f(a1 - b1) + f(a1 - b2))

    def apply(self, flat: tuple[np.ndarray, np.ndarray, np.ndarray]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """The flux each bar is linked by, for these currents in the bars along x, along y and upright."""
        out = []
        ny, nx = self.grid.ny, self.grid.nx
        for kind in (0, 1):
            field = flat[kind]
            live = [k for k in range(field.shape[0]) if field[k].any()]
            spectra = {k: fft.rfft2(field[k], s=self.shape) for k in live}
            flux = np.zeros_like(field)
            for a in live:
                total = sum(self._table(abs(self.z[a] - self.z[b]), kind) * spectra[b] for b in live)
                flux[a] = fft.irfft2(total, s=self.shape)[:ny, :nx]
            out.append(flux)
        return out[0], out[1], self.upright @ flat[2]


@dataclass
class Loop:
    """One loop solved: its inductance by the least-energy current (l) and by the steady
    current (l_dc), H; its copper's resistance, ohm; and the least-energy current itself for
    one ampere round the loop, in the fields the kernel takes, with the steady current beside it."""

    l: float
    l_dc: float
    r: float
    fields: tuple[np.ndarray, np.ndarray, np.ndarray]
    steady: tuple[np.ndarray, np.ndarray, np.ndarray]
    bars: int
    steps: int
    settled: bool
    work: float = 0.0  # what the search cost, in the units a search is given its budget in


class _Circuit:
    """A network's bars as vectors, with what turns them into the kernel's fields and back."""

    def __init__(self, net: Network, kernel: Kernel) -> None:
        self.net, self.kernel = net, kernel
        g = kernel.grid
        self.sizes = ((len(g.layers) + 2, g.ny, g.nx), (len(g.layers) + 2, g.ny, g.nx), (g.zj.size,))
        self.masks = [net.kind == kind for kind in (0, 1, 2)]
        n = net.kind.size
        self.incidence = sparse.csr_matrix(
            (np.r_[np.ones(n), -np.ones(n)], (np.r_[np.arange(n), np.arange(n)], np.r_[net.n1, net.n2])),
            shape=(n, net.nodes),
        )

    def cost(self) -> float:
        """What one step of the search costs, in cells transformed: for the bars along x and
        those along y, every layer that carries any with every other, over the transform's
        cells; and the upright bars each with each."""
        cells = self.kernel.shape[0] * self.kernel.shape[1]
        per_layer = self.sizes[0][1] * self.sizes[0][2]
        pairs = 0
        for mask in self.masks[:2]:
            live = np.unique(self.net.where[mask] // per_layer).size
            pairs += live * live
        return float(cells * max(pairs, 1) + self.masks[2].sum() ** 2)

    def fields(self, current: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        out = []
        for mask, size in zip(self.masks, self.sizes, strict=True):
            field = np.zeros(int(np.prod(size)))
            np.add.at(field, self.net.where[mask], current[mask])
            out.append(field.reshape(size))
        return out[0], out[1], out[2]

    def flux(self, current: np.ndarray) -> np.ndarray:
        """L·I: the flux linking each bar."""
        linked = self.kernel.apply(self.fields(current))
        out = np.zeros(current.size)
        for mask, field in zip(self.masks, linked, strict=True):
            out[mask] = field.ravel()[self.net.where[mask]]
        return out


def _driven(net: Network) -> Network:
    """The part of the network joined to where it is driven: copper that hangs off elsewhere
    carries none of the loop's current."""
    graph = sparse.coo_matrix((np.ones(net.n1.size), (net.n1, net.n2)), shape=(net.nodes, net.nodes))
    _, label = csgraph.connected_components(graph, directed=False)
    wanted = np.isin(label[net.n1], np.unique(label[net.n1[net.emf != 0]]))
    if not wanted.any():
        raise Unsolved("nothing drives the loop")
    cols = [v[wanted] for v in (net.kind, net.where, net.n1, net.n2, net.g, net.emf, net.copper)]
    used, flat = np.unique(np.concatenate([cols[2], cols[3]]), return_inverse=True)
    n = cols[2].size
    return Network(used.size, cols[0], cols[1], flat[:n], flat[n:], cols[4], cols[5], cols[6])


def _grounded(circuit: _Circuit, weight: np.ndarray):
    """A solver for the nodes' voltages with these conductances, one node of each island held at nought."""
    a = circuit.incidence
    laplace = (a.T @ sparse.diags(weight) @ a).tocsc()
    _, label = csgraph.connected_components(laplace, directed=False)
    _, held = np.unique(label, return_index=True)
    keep = np.setdiff1d(np.arange(laplace.shape[0]), held)
    lu = splu(laplace[keep][:, keep].tocsc())

    def solve(rhs: np.ndarray) -> np.ndarray:
        out = np.zeros(laplace.shape[0])
        out[keep] = lu.solve(rhs[keep])
        return out

    return solve


def _least_energy(circuit: _Circuit, steps: int, alive: Callable[[], None]) -> tuple[np.ndarray, int, bool]:
    """The current of least magnetic energy for a unit drive, among those that keep the
    current law: conjugate gradients, every step projected back onto that law. At most
    `steps` steps are taken; alive is asked before each, and raises to stop the lot."""
    a = circuit.incidence
    volts = _grounded(circuit, np.ones(a.shape[0]))

    def kept(v):
        return v - a @ volts(a.T @ v)

    x = np.zeros(a.shape[0])
    r = kept(circuit.net.emf)
    p, rr = r.copy(), float(r @ r)
    first = rr
    for step in range(1, steps + 1):
        alive()
        lp = kept(circuit.flux(p))
        curve = float(p @ lp)
        if curve <= 0:
            return x, step, False
        alpha = rr / curve
        x += alpha * p
        r -= alpha * lp
        new = float(r @ r)
        if new <= CLOSE_ENOUGH**2 * first:
            return x, step, True
        p, rr = r + (new / rr) * p, new
    return x, steps, False


def _always() -> None:
    return None


def solve(net: Network, kernel: Kernel, work: float = math.inf, alive: Callable[[], None] = _always) -> Loop:
    """The loop this network closes, or Unsolved where its copper does not close one.
    work: what the search for the fast edge's current may cost (see _Circuit.cost): it is
    stopped at the step that would pass it, and at MOST_STEPS. alive: asked before every
    step; it raises where the whole reading is to be given up."""
    if not net.emf.any():
        raise Unsolved("nothing drives the loop")
    net = _driven(net)
    circuit = _Circuit(net, kernel)
    a = circuit.incidence
    volts = _grounded(circuit, net.g)(-(a.T @ (net.g * net.emf)))
    steady = net.g * (a @ volts + net.emf)
    round_loop = float(steady @ net.emf)
    if not abs(round_loop) > 1e-9 * float(net.g[net.emf != 0].sum()):
        raise Unsolved("the copper found does not close the loop")
    steady /= round_loop
    r = float((steady[net.copper] ** 2 / net.g[net.copper]).sum())
    flux_steady = circuit.flux(steady)
    w11 = float(steady @ flux_steady)
    cost = circuit.cost()
    fast, steps, settled = _least_energy(circuit, int(min(max(work / cost, 1.0), MOST_STEPS)), alive)
    share = float(fast @ net.emf)
    best, l = steady, w11
    if share > 0:
        fast = fast / share
        w12, w22 = float(fast @ flux_steady), float(fast @ circuit.flux(fast))
        # The least over every mix of the two currents: never above either.
        bend = w11 - 2 * w12 + w22
        s = min(max((w11 - w12) / bend, 0.0), 1.5) if bend > 0 else 0.0
        best = steady + s * (fast - steady)
        l = w11 + 2 * s * (w12 - w11) + s * s * bend
    return Loop(
        l, w11, r, circuit.fields(best), circuit.fields(steady), int(net.kind.size), steps, settled, steps * cost
    )


def coupling(one: Loop, other: Loop, kernel: Kernel) -> float:
    """The mutual inductance of two loops through the board's own copper, H: the flux one
    loop's ampere puts through the other. The parts' bodies are left out of it."""
    copper = len(kernel.grid.layers)

    def cut(loop: Loop):
        flat = [np.concatenate([field[:copper], np.zeros_like(field[copper:])]) for field in loop.fields[:2]]
        return flat[0], flat[1], loop.fields[2]

    a, b = cut(one), cut(other)
    linked = kernel.apply(a)
    return float(sum((u * v).sum() for u, v in zip(linked, b, strict=True)))
