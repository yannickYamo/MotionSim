"""Partial inductances in closed form: what the board's loop figures are summed from.

Every conductor is cut into straight pieces, and a loop's inductance is the sum of each piece's
own partial inductance and of the mutual partial inductances of every two, with the sign of
the currents (Ruehli, "Inductance calculations in a complex integrated circuit environment",
IBM J. Res. Dev. 16, 1972). Pieces at right angles have no mutual. The formulas:

- two parallel filaments, any offset: Grover, "Inductance Calculations" (1946),
  the Neumann integral worked out, M = µ0/4π · [F(a2-b1) - F(a2-b2) - F(a1-b1) + F(a1-b2)]
  with F(z) = z·asinh(z/d) - sqrt(z² + d²);
- a flat tape's own (Ruehli 1972, the zero-thickness limit of Hoer and Love's bar, "Exact
  inductance equations for rectangular conductors", J. Res. NBS 69C, 1965);
- two parallel flat tapes in parallel planes: the same fourfold integral of 1/r in closed form;
- a round wire's own (Rosa, 1908; Grover).

All lengths in metres, all inductances in henries.
"""

from __future__ import annotations

import math

import numpy as np

MU0 = 4e-7 * math.pi


def mutual_filaments(a1: float, a2: float, b1: float, b2: float, d: float) -> float:
    """Two parallel filaments a distance d apart, one from a1 to a2 along their common
    direction and the other from b1 to b2. Positive where the currents run the same way."""

    def f(z: float) -> float:
        return z * math.asinh(z / d) - math.hypot(z, d)

    return MU0 / (4 * math.pi) * (f(a2 - b1) - f(a2 - b2) - f(a1 - b1) + f(a1 - b2))


def self_round(length: float, radius: float) -> float:
    """A straight round wire with its current even over its section: the mutual of two
    filaments at the section's geometric mean distance from itself, radius·e^(-1/4)."""
    return mutual_filaments(0.0, length, 0.0, length, radius * math.exp(-0.25))


def self_tube(length: float, radius: float) -> float:
    """A thin-walled tube, as a via's plating is: its geometric mean distance is its radius."""
    return mutual_filaments(0.0, length, 0.0, length, radius)


def self_bar(length: float, width: float, thickness: float = 0.0) -> float:
    """A straight bar of rectangular section, its current even over the section. Exact for a
    tape of no thickness (Ruehli 1972); a bar's thickness is added to its width, as
    in Grover's ln(2l/(w+t)) + 1/2, which this tends to for a long bar."""
    u = length / (width + thickness)
    inner = 3 * math.asinh(u) + u * u + 1 / u + 3 * u * math.asinh(1 / u) - (u ** (4 / 3) + u ** (-2 / 3)) ** 1.5
    return MU0 * length / (6 * math.pi) * inner


def _fourfold(x: np.ndarray, y: np.ndarray, z: float) -> np.ndarray:
    """The function whose second difference in x and in y is the integral of 1/r over two
    rectangles in parallel planes a distance z apart."""
    r = np.sqrt(x * x + y * y + z * z)

    def log_sum(u: np.ndarray, rest2: np.ndarray) -> np.ndarray:
        # ln(u + r), written for a negative u so that nothing is lost in the sum; where u + r
        # is nought the term it multiplies is nought too.
        positive = np.where(u >= 0, u + r, rest2 / np.where(r - u > 0, r - u, 1.0))
        return np.log(np.where(positive > 0, positive, 1.0))

    out = 0.5 * x * (y * y - z * z) * log_sum(x, y * y + z * z)
    out += 0.5 * y * (x * x - z * z) * log_sum(y, x * x + z * z)
    out -= (x * x + y * y - 2 * z * z) * r / 6
    if z > 0:
        out -= x * y * z * np.arctan(x * y / (z * r))
    return out


def tape_table(pitch: float, along: int, across: int, z: float) -> np.ndarray:
    """Mutual partial inductance of two equal square tapes (pitch long, pitch wide) in
    parallel planes z apart, for every offset of 0..along pitches along the current and
    0..across pitches across it: table[across, along]. The entry at nought with z = 0 is a
    tape's own."""
    a = np.arange(along + 1)[None, :] * pitch
    t = np.arange(across + 1)[:, None] * pitch
    total = np.zeros((across + 1, along + 1))
    for dx, wx in ((-pitch, 1.0), (0.0, -2.0), (pitch, 1.0)):
        for dy, wy in ((-pitch, 1.0), (0.0, -2.0), (pitch, 1.0)):
            total += wx * wy * _fourfold(a + dx + 0 * t, t + dy + 0 * a, z)
    return MU0 / (4 * math.pi) * total / (pitch * pitch)
