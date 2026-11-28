"""A window of the board cut into square cells: which net's copper each cell is, which pad it
lies under, and from that the network of short bars a loop's current runs through.

Every bar lies along x or along y between two neighbouring cells of one net on one layer, or
stands upright in a via. A part's body between two of its pads is drawn as flat bars just
outside the copper, so that the loop is closed where its current is. What this leaves out is
said in docs by the figures that rest on it: copper of other nets, and copper outside the window.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from motionsim.board.model import Board, Layer, Pad, Zone

SIGMA = 1 / 1.724e-8  # S/m: annealed copper at 20 °C
PLATING = 0.025  # mm: the copper plated in a via's hole, assumed
BODY = 0.1  # mm: how far outside the copper a part's body carries its current, assumed
MOST_VIAS = 2000  # upright bars in one window, after those in one cell are taken together


class Unsolved(Exception):
    """A figure that cannot be worked out from this board as it was read, and why."""


@dataclass(frozen=True)
class Link:
    """A part's body from its pad a to its pad b. emf: this is where the loop is driven
    (the capacitor in the power loop, the driver in the gate loop)."""

    ref: str
    a: Pad
    b: Pad
    emf: bool = False


@dataclass
class Grid:
    x0: float
    y0: float
    pitch: float  # mm
    nx: int
    ny: int
    layers: list[Layer]
    nets: list[str]
    owner: np.ndarray  # [layer, row, column]: 0, or 1 + the net's place in nets
    pad: np.ndarray  # [layer, row, column]: -1, or the pad's number
    pads: dict[tuple[str, str], int] = field(default_factory=dict)
    zl1: np.ndarray = field(default_factory=lambda: np.zeros(0, int))  # upright bars: upper layer,
    zl2: np.ndarray = field(default_factory=lambda: np.zeros(0, int))  # lower layer,
    zj: np.ndarray = field(default_factory=lambda: np.zeros(0, int))  # row, column,
    zi: np.ndarray = field(default_factory=lambda: np.zeros(0, int))
    zr: np.ndarray = field(default_factory=lambda: np.zeros(0))  # hole radius in mm
    zn: np.ndarray = field(default_factory=lambda: np.zeros(0))  # and how many vias it stands for
    said: list[str] = field(default_factory=list)
    thin: np.ndarray | None = None  # [layer, row, column]: the cells of tracks narrower than a cell
    narrowest: float = math.inf  # mm: the narrowest of those tracks

    def through_thin(self, fields) -> bool:
        """Whether a fifth or more of a loop's steady current runs through one bar of a track drawn
        wider than it is. The steady current is asked, since a fast edge also drives small eddies
        in copper that hangs off the loop, which are no part of its way round."""
        if self.thin is None or not self.thin.any():
            return False
        copper = len(self.layers)
        return bool(
            max(np.abs(fields[0][:copper][self.thin]).max(), np.abs(fields[1][:copper][self.thin]).max()) >= 0.2
        )

    def heights(self) -> list[float]:
        """The height of every layer bars lie on, mm: the copper layers, then the bodies of
        the parts on top and of those underneath."""
        zs = [layer.z for layer in self.layers]
        return [*zs, zs[0] - BODY, zs[-1] + BODY]

    def column(self, x: float) -> int:
        return min(max(int((x - self.x0) / self.pitch), 0), self.nx - 1)

    def row(self, y: float) -> int:
        return min(max(int((y - self.y0) / self.pitch), 0), self.ny - 1)

    def span(self, low: float, high: float, origin: float, n: int) -> tuple[int, int]:
        """The cells whose middles lie from low to high: first and one past the last."""
        first = math.ceil((low - origin) / self.pitch - 0.5)
        last = math.floor((high - origin) / self.pitch - 0.5)
        return max(first, 0), min(last + 1, n)


def _pads(grid: Grid, board: Board) -> None:
    names = [layer.name for layer in grid.layers]
    for part in board.components:
        for pad in part.pads:
            if pad.net not in grid.nets:
                continue
            number = len(grid.pads)
            i0, i1 = grid.span(pad.x - pad.w / 2, pad.x + pad.w / 2, grid.x0, grid.nx)
            j0, j1 = grid.span(pad.y - pad.h / 2, pad.y + pad.h / 2, grid.y0, grid.ny)
            if i1 <= i0:
                i0, i1 = grid.column(pad.x), grid.column(pad.x) + 1
            if j1 <= j0:
                j0, j1 = grid.row(pad.y), grid.row(pad.y) + 1
            inside = grid.x0 <= pad.x <= grid.x0 + grid.nx * grid.pitch
            inside = inside and grid.y0 <= pad.y <= grid.y0 + grid.ny * grid.pitch
            if not inside:
                continue
            net = grid.nets.index(pad.net) + 1
            taken = False
            for name in pad.layers:
                if name not in names:
                    continue
                k = names.index(name)
                free = grid.pad[k, j0:j1, i0:i1] < 0
                grid.pad[k, j0:j1, i0:i1][free] = number
                grid.owner[k, j0:j1, i0:i1][free] = net
                taken = taken or bool(free.any())
            if taken:
                grid.pads[(pad.ref, pad.name)] = number


def _tracks(grid: Grid, board: Board) -> None:
    names = [layer.name for layer in grid.layers]
    p = grid.pitch
    for track in board.tracks:
        if track.net not in grid.nets or track.layer not in names:
            continue
        half = max(track.width / 2, 0.71 * p)  # a track thinner than a cell is still one unbroken run of cells
        i0, i1 = grid.span(min(track.x1, track.x2) - half, max(track.x1, track.x2) + half, grid.x0, grid.nx)
        j0, j1 = grid.span(min(track.y1, track.y2) - half, max(track.y1, track.y2) + half, grid.y0, grid.ny)
        if i1 <= i0 or j1 <= j0:
            continue
        x = grid.x0 + (np.arange(i0, i1) + 0.5) * p
        y = grid.y0 + (np.arange(j0, j1) + 0.5) * p
        dx, dy = track.x2 - track.x1, track.y2 - track.y1
        along = ((x[None, :] - track.x1) * dx + (y[:, None] - track.y1) * dy) / max(dx * dx + dy * dy, 1e-18)
        along = np.clip(along, 0.0, 1.0)
        away = np.hypot(x[None, :] - track.x1 - along * dx, y[:, None] - track.y1 - along * dy)
        cells = grid.owner[names.index(track.layer), j0:j1, i0:i1]
        drawn = (away <= half) & (cells == 0)
        cells[drawn] = grid.nets.index(track.net) + 1
        if track.width < p and grid.thin is not None:
            grid.thin[names.index(track.layer), j0:j1, i0:i1] |= drawn
            grid.narrowest = min(grid.narrowest, track.width)


MOST_CROSSINGS = 2_000_000  # of a pour's edges with the rows of cells, worked out at a time


def inside(grid: Grid, zone: Zone) -> np.ndarray:
    """The cells whose middles lie in a pour: in its outline and in none of its holes, by the
    even-odd rule, which also reads an outline its holes are slit into. Every edge of a ring
    is taken with every row of cells it crosses, all of a ring's edges at once: a fill of a
    hundred thousand corners costs what its crossings cost, not a step for each corner."""
    p = grid.pitch
    y = grid.y0 + (np.arange(grid.ny) + 0.5) * p
    toggles = np.zeros((grid.ny, grid.nx + 1), dtype=np.int32)
    for ring in [zone.outline, *zone.holes]:
        if len(ring) < 3:
            continue
        pts = np.asarray(ring, dtype=float)
        x1, y1 = pts[:, 0], pts[:, 1]
        x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
        # The rows whose middle is at or above an edge's lower end and under its upper end.
        first = np.searchsorted(y, np.minimum(y1, y2), side="left")
        last = np.searchsorted(y, np.maximum(y1, y2), side="left")
        crossed = np.where(y1 == y2, 0, last - first)
        ends = np.cumsum(crossed)
        start = 0
        while start < crossed.size:
            # As many edges as cross MOST_CROSSINGS rows together, and one edge at the least.
            base = int(ends[start - 1]) if start else 0
            stop = max(int(np.searchsorted(ends, base + MOST_CROSSINGS, side="right")), start + 1)
            count = crossed[start:stop]
            edge = np.repeat(np.arange(start, stop), count)
            if edge.size:
                within = np.arange(edge.size) - np.repeat(ends[start:stop] - count - base, count)
                rows = first[edge] + within
                cross = x1[edge] + (y[rows] - y1[edge]) * (x2[edge] - x1[edge]) / (y2[edge] - y1[edge])
                columns = np.clip(np.ceil((cross - grid.x0) / p - 0.5), 0, grid.nx).astype(int)
                np.add.at(toggles, (rows, columns), 1)
            start = stop
    return (np.cumsum(toggles, axis=1)[:, : grid.nx] % 2).astype(bool)


def _zones(grid: Grid, board: Board) -> None:
    names = [layer.name for layer in grid.layers]
    for zone in board.zones:
        if zone.net not in grid.nets or zone.layer not in names:
            continue
        cells = grid.owner[names.index(zone.layer)]
        cells[inside(grid, zone) & (cells == 0)] = grid.nets.index(zone.net) + 1


def _vias(grid: Grid, board: Board) -> None:
    names = [layer.name for layer in grid.layers]
    found: dict[tuple[int, int, int, int], list[float]] = {}
    for via in board.vias:
        if via.net not in grid.nets or via.layers[0] not in names or via.layers[1] not in names:
            continue
        if not (
            grid.x0 <= via.x < grid.x0 + grid.nx * grid.pitch and grid.y0 <= via.y < grid.y0 + grid.ny * grid.pitch
        ):
            continue
        j, i = grid.row(via.y), grid.column(via.x)
        top, bottom = sorted((names.index(via.layers[0]), names.index(via.layers[1])))
        net = grid.nets.index(via.net) + 1
        on = [k for k in range(top, bottom + 1) if grid.owner[k, j, i] == net]
        for upper, lower in zip(on, on[1:], strict=False):
            entry = found.setdefault((upper, lower, j, i), [0.0, 0.0])
            entry[0] += 1
            entry[1] = max(entry[1], via.drill / 2 or via.size / 4)
    if len(found) > MOST_VIAS:
        raise Unsolved(f"more than {MOST_VIAS} vias in the loop's window")
    keys = np.array(list(found), dtype=int).reshape(-1, 4)
    grid.zl1, grid.zl2, grid.zj, grid.zi = keys[:, 0], keys[:, 1], keys[:, 2], keys[:, 3]
    grid.zn = np.array([v[0] for v in found.values()])
    grid.zr = np.array([v[1] for v in found.values()])


def rasterise(board: Board, nets: list[str], window: tuple[float, float, float, float], pitch: float) -> Grid:
    """The copper of these nets inside the window, as cells: pads first, then tracks, then
    pours where nothing else is."""
    x0, y0, x1, y1 = window
    nx, ny = max(math.ceil((x1 - x0) / pitch), 2), max(math.ceil((y1 - y0) / pitch), 2)
    layers = board.stackup.layers
    owner = np.zeros((len(layers), ny, nx), dtype=np.int16)
    grid = Grid(x0, y0, pitch, nx, ny, layers, nets, owner, np.full(owner.shape, -1, dtype=np.int32))
    grid.thin = np.zeros(owner.shape, dtype=bool)
    _pads(grid, board)
    _tracks(grid, board)
    _zones(grid, board)
    _vias(grid, board)
    return grid


@dataclass
class Network:
    """The bars one loop's current may run through. kind: 0 along x, 1 along y, 2 upright.
    where: the bar's place in the field it belongs to. emf: +1 or -1 where the loop is driven
    along or against the bar, else 0. copper: false for the bars of a part's body."""

    nodes: int
    kind: np.ndarray
    where: np.ndarray
    n1: np.ndarray
    n2: np.ndarray
    g: np.ndarray
    emf: np.ndarray
    copper: np.ndarray


class _Bars:
    def __init__(self) -> None:
        self.rows: list[tuple[np.ndarray, ...]] = []

    def add(self, kind: int, where, n1, n2, g, emf=0.0, copper: bool = True) -> None:
        where, n1, n2 = (np.atleast_1d(np.asarray(v, dtype=np.int64)) for v in (where, n1, n2))
        n = where.size

        def full(v, dtype):
            return np.broadcast_to(np.asarray(v, dtype=dtype), (n,)).copy()

        self.rows.append((full(kind, np.int8), where, n1, n2, full(g, float), full(emf, float), full(copper, bool)))

    def columns(self) -> list[np.ndarray]:
        return [np.concatenate([row[k] for row in self.rows]) for k in range(7)]


def _sheet(grid: Grid, active: np.ndarray, node: np.ndarray, bars: _Bars) -> None:
    """The flat bars of the copper: between two neighbouring cells of one net on one layer."""
    size = grid.ny * grid.nx
    for k, layer in enumerate(grid.layers):
        own, ids = grid.owner[k], node[k]
        g = SIGMA * layer.thickness * 1e-3  # a square of the sheet, whatever its size
        for kind, a, b in ((0, np.s_[:, :-1], np.s_[:, 1:]), (1, np.s_[:-1, :], np.s_[1:, :])):
            joined = (own[a] == own[b]) & active[own[a]] & (ids[a] != ids[b])
            j, i = np.nonzero(joined)
            bars.add(kind, k * size + j * grid.nx + i, ids[a][j, i], ids[b][j, i], g)


def _upright(grid: Grid, active: np.ndarray, node: np.ndarray, bars: _Bars) -> None:
    for n in range(grid.zj.size):
        l1, l2, j, i = grid.zl1[n], grid.zl2[n], grid.zj[n], grid.zi[n]
        if not active[grid.owner[l1, j, i]]:
            continue
        height = (grid.layers[l2].z - grid.layers[l1].z) * 1e-3
        wall = math.pi * max(2 * grid.zr[n] - PLATING, PLATING) * PLATING * 1e-6
        bars.add(2, n, node[l1, j, i], node[l2, j, i], SIGMA * wall / height * grid.zn[n])


def _body(grid: Grid, link: Link, nodes: list[int], pad_node, bars: _Bars, merged: list[tuple[int, int]]) -> None:
    """A part's body as rows of flat bars from pad a to pad b, on the layer just outside the
    copper the part sits on: as many rows as the two pads face each other over."""
    a, b = link.a, link.b
    start, end = pad_node(a), pad_node(b)
    top = grid.layers[0].name in a.layers
    layer = len(grid.layers) + (0 if top else 1)
    along_x = abs(b.x - a.x) >= abs(b.y - a.y)
    if along_x:
        first, last = grid.column(a.x), grid.column(b.x)
        low, high = max(a.y - a.h / 2, b.y - b.h / 2), min(a.y + a.h / 2, b.y + b.h / 2)
        rows = range(*grid.span(low, high, grid.y0, grid.ny))
        rows = rows or range(grid.row((a.y + b.y) / 2), grid.row((a.y + b.y) / 2) + 1)
    else:
        first, last = grid.row(a.y), grid.row(b.y)
        low, high = max(a.x - a.w / 2, b.x - b.w / 2), min(a.x + a.w / 2, b.x + b.w / 2)
        rows = range(*grid.span(low, high, grid.x0, grid.nx))
        rows = rows or range(grid.column((a.x + b.x) / 2), grid.column((a.x + b.x) / 2) + 1)
    if first == last:
        if link.emf:
            raise Unsolved(f"the pads of {link.ref} fall in one cell of the mesh")
        merged.append((start, end))
        return
    step = 1 if last > first else -1
    count = abs(last - first)
    g = SIGMA * grid.layers[0].thickness * 1e-3
    size = grid.ny * grid.nx
    for row in rows:
        inner = list(range(nodes[0], nodes[0] + count - 1))
        nodes[0] += count - 1
        chain = [start, *inner, end]
        for n in range(count):
            cell = first + n * step - (0 if step > 0 else 1)  # the bar from this cell to the next
            where = layer * size + (row * grid.nx + cell if along_x else cell * grid.nx + row)
            lower, upper = (chain[n], chain[n + 1]) if step > 0 else (chain[n + 1], chain[n])
            bars.add(0 if along_x else 1, where, lower, upper, g, step if link.emf and n == 0 else 0.0, False)


def network(grid: Grid, nets: list[str], links: list[Link]) -> Network:
    """The bars of these nets' copper and of these parts' bodies, with every cell under one
    pad taken as one point: the pad, its solder and the part's lead hold it at one voltage."""
    active = np.zeros(len(grid.nets) + 1, dtype=bool)
    for net in nets:
        active[grid.nets.index(net) + 1] = True
    node = np.arange(grid.owner.size, dtype=np.int64).reshape(grid.owner.shape)
    under = grid.pad >= 0
    node[under] = grid.owner.size + grid.pad[under]
    nodes = [grid.owner.size + len(grid.pads) + 1]

    def pad_node(pad: Pad) -> int:
        number = grid.pads.get((pad.ref, pad.name))
        if number is None:
            raise Unsolved(f"pad {pad.name} of {pad.ref} has no copper in the mesh")
        return grid.owner.size + number

    bars = _Bars()
    _sheet(grid, active, node, bars)
    _upright(grid, active, node, bars)
    merged: list[tuple[int, int]] = []
    for link in links:
        _body(grid, link, nodes, pad_node, bars, merged)
    kind, where, n1, n2, g, emf, copper = bars.columns()
    for keep, gone in merged:
        n1[n1 == gone], n2[n2 == gone] = keep, keep
    same = n1 == n2
    kind, where, n1, n2, g, emf, copper = (v[~same] for v in (kind, where, n1, n2, g, emf, copper))
    used, flat = np.unique(np.concatenate([n1, n2]), return_inverse=True)
    return Network(used.size, kind, where, flat[: n1.size], flat[n1.size :], g, emf, copper)
