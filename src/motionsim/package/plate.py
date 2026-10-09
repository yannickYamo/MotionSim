"""Heat spreading from chips mounted on a metal plate over an insulating layer.

This is the common structure of power packages: chips soldered to copper (a
leadframe pad, the copper of a ceramic substrate, or the tab of a discrete
package), with an insulating layer between that copper and a surface held at
one temperature.

The plate is thin compared with its width, so temperature is taken as uniform
through its thickness and heat flows sideways in the plate and straight down
through the insulation. Temperature rise theta over the reference surface then
obeys

    k_plate * t_plate * laplacian(theta) - (k_ins / t_ins) * theta + q = 0

with q the heat entering per unit area under each chip and no heat leaving
through the plate's edges. The length sqrt(k_plate * t_plate * t_ins / k_ins)
sets how far heat spreads: chips closer together than that heat each other,
chips much further apart do not.

Everything here follows from this equation and handbook material properties.
No measured device data is involved.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import splu


@dataclass(frozen=True)
class Stack:
    """Materials under the chips. Conductivities in W/(m·K), thicknesses in m."""

    k_plate: float
    t_plate: float
    k_insulation: float
    t_insulation: float
    k_die: float = 100.0  # silicon near 100 °C
    t_die: float = 150e-6
    k_attach: float = 50.0  # solder
    t_attach: float = 50e-6
    c_plate: float = 3.45e6  # volumetric heat capacity of copper, J/(m3·K)
    c_die: float = 1.66e6  # silicon

    @property
    def spreading_length(self) -> float:
        return float(np.sqrt(self.k_plate * self.t_plate * self.t_insulation / self.k_insulation))


@dataclass(frozen=True)
class ChipSite:
    name: str
    x: float  # centre, m, from the plate's lower-left corner
    y: float
    width: float
    height: float

    @property
    def area(self) -> float:
        return self.width * self.height


@dataclass(frozen=True)
class Plate:
    """One electrically continuous piece of copper and the chips on it."""

    width: float
    height: float
    chips: tuple[ChipSite, ...]


def _assemble(plate: Plate, stack: Stack, cell: float):
    """Conductance matrix of the plate on a grid, with its cell counts and sizes."""
    nx = max(4, int(round(plate.width / cell)))
    ny = max(4, int(round(plate.height / cell)))
    dx, dy = plate.width / nx, plate.height / ny
    sideways = stack.k_plate * stack.t_plate
    down = stack.k_insulation / stack.t_insulation * dx * dy
    gx, gy = sideways * dy / dx, sideways * dx / dy
    matrix = lil_matrix((nx * ny, nx * ny))
    for j in range(ny):
        for i in range(nx):
            n = j * nx + i
            diagonal = down
            for di, dj, g in ((1, 0, gx), (-1, 0, gx), (0, 1, gy), (0, -1, gy)):
                ii, jj = i + di, j + dj
                if 0 <= ii < nx and 0 <= jj < ny:
                    matrix[n, jj * nx + ii] = -g
                    diagonal += g
            matrix[n, n] = diagonal
    return matrix.tocsc(), nx, ny, dx, dy


def _solver(plate: Plate, stack: Stack, cell: float):
    matrix, nx, ny, dx, dy = _assemble(plate, stack, cell)
    return splu(matrix), nx, ny, dx, dy


def _footprint(chip: ChipSite, nx: int, ny: int, dx: float, dy: float) -> np.ndarray:
    """Share of each grid cell covered by a chip, flattened."""
    x = (np.arange(nx) + 0.5) * dx
    y = (np.arange(ny) + 0.5) * dy
    cover_x = np.clip(
        (np.minimum(x + dx / 2, chip.x + chip.width / 2) - np.maximum(x - dx / 2, chip.x - chip.width / 2)) / dx,
        0, 1,
    )
    cover_y = np.clip(
        (np.minimum(y + dy / 2, chip.y + chip.height / 2) - np.maximum(y - dy / 2, chip.y - chip.height / 2)) / dy,
        0, 1,
    )
    return np.outer(cover_y, cover_x).ravel()


def thermal_matrix(plate: Plate, stack: Stack, cell: float = 0.25e-3) -> np.ndarray:
    """Thermal resistance matrix of the chips on one plate, in K/W.

    Entry [i, j] is the average temperature rise under chip i per watt
    dissipated in chip j, over the reference surface beneath the insulation.
    The diagonal includes the chip's own die and attach layers.
    """
    solve, nx, ny, dx, dy = _solver(plate, stack, cell)
    covers = [_footprint(c, nx, ny, dx, dy) for c in plate.chips]
    n = len(plate.chips)
    out = np.zeros((n, n))
    for j, source in enumerate(covers):
        theta = solve.solve(source / source.sum())  # one watt spread over chip j
        for i, target in enumerate(covers):
            out[i, j] = float(theta @ target / target.sum())
    for i, chip in enumerate(plate.chips):
        out[i, i] += (stack.t_die / stack.k_die + stack.t_attach / stack.k_attach) / chip.area
    return out


def step_response(
    plate: Plate, stack: Stack, chip: int, times: np.ndarray, cell: float = 0.5e-3
) -> np.ndarray:
    """Rise under one chip at the given times after it starts dissipating one watt, K/W.

    The copper's heat capacity is added to the plate equation and the result
    stepped forward in time. The die is one more stage in series: its own
    resistance charging its own heat capacity.
    """
    from scipy.sparse import identity

    matrix, nx, ny, dx, dy = _assemble(plate, stack, cell)
    capacity = stack.c_plate * stack.t_plate * dx * dy
    cover = _footprint(plate.chips[chip], nx, ny, dx, dy)
    source = cover / cover.sum()
    weights = cover / cover.sum()
    theta = np.zeros(nx * ny)
    times = np.asarray(times, dtype=float)
    out = np.empty(times.size)
    eye = identity(nx * ny, format="csc")
    previous = 0.0
    for k, t in enumerate(times):
        # Several implicit steps per output time keep the stepping error small.
        steps = 4
        dt = (t - previous) / steps
        solve = splu(matrix + eye * (capacity / dt))
        for _ in range(steps):
            theta = solve.solve(source + theta * (capacity / dt))
        out[k] = float(theta @ weights)
        previous = t
    area = plate.chips[chip].area
    r_die = (stack.t_die / stack.k_die + stack.t_attach / stack.k_attach) / area
    if r_die > 0:
        tau_die = r_die * stack.c_die * stack.t_die * area / 2
        out = out + r_die * (1 - np.exp(-times / tau_die))
    return out
