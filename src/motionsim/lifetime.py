"""How many times a motion can be repeated before thermal cycling wears the device out.

Every swing of junction temperature strains the joints inside a power device:
the bond wires and the solder, which expand at a different rate from the
silicon. The swings of a temperature trace are counted, each is given the
number of such swings a device survives, and the damage is added up.

The survival model is the one fitted to the LESIT power-cycling tests on
standard modules with aluminium bond wires (Held et al., 1997):

    N_f = A * dT^alpha * exp(E_a / (k_B * T_m))

with dT the swing and T_m its mean temperature in kelvin. It is a generic
model. A real device may last several times longer or shorter: newer joining
methods last longer, and the model was fitted to swings between about 30 and
80 K, so small swings are an extrapolation. It gives the order of magnitude
and shows which swing does the damage. A manufacturer's own power-cycling
curve replaces it where there is one.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

A = 302500.0  # K^-alpha
ALPHA = -5.039
E_A = 9.89e-20  # J
K_B = 1.380649e-23  # J/K
SMALLEST = 1.0  # K; swings below this do no damage worth counting


def cycles_to_failure(swing: float, mean_c: float) -> float:
    """Swings of this size, about this mean temperature in °C, that a device survives."""
    return float(A * swing**ALPHA * np.exp(E_A / (K_B * (mean_c + 273.15))))


def rainflow(trace: np.ndarray) -> list[tuple[float, float, float]]:
    """Swings in a temperature trace that repeats without end, as (size, mean, count).

    The usual rainflow count. The trace is started at its highest point, which a
    repeating trace allows and which closes every swing, so each counts once.
    """
    values = np.asarray(trace, dtype=float)
    if values.size < 2 or np.ptp(values) < SMALLEST:
        return []
    values = np.roll(values, -int(values.argmax()))
    values = np.append(values, values[0])
    # Keep the turning points only.
    turns = [values[0]]
    for v in values[1:]:
        if v == turns[-1]:
            continue
        if len(turns) >= 2 and (turns[-1] - turns[-2]) * (v - turns[-1]) > 0:
            turns[-1] = v
        else:
            turns.append(v)
    out = []
    stack: list[float] = []
    for point in turns:
        stack.append(point)
        while len(stack) >= 3:
            inner, outer = abs(stack[-2] - stack[-3]), abs(stack[-1] - stack[-2])
            if outer < inner:
                break
            if len(stack) == 3:
                break  # the first swing waits for the trace to close
            out.append((inner, (stack[-2] + stack[-3]) / 2, 1.0))
            del stack[-3:-1]
    for a, b in zip(stack, stack[1:], strict=False):  # what is left pairs off as half swings
        out.append((abs(b - a), (a + b) / 2, 0.5))
    # Two halves of the same swing are one swing.
    merged: dict[tuple[float, float], float] = {}
    for size, mean, count in out:
        key = (round(size, 3), round(mean, 3))
        merged[key] = merged.get(key, 0.0) + count
    return [(s, m, c) for (s, m), c in merged.items() if s >= SMALLEST]


@dataclass(frozen=True)
class Life:
    repeats: float  # times the motion can be repeated; inf when no swing counts
    swing: float  # K, the swing that does most of the damage
    swing_mean: float  # °C
    swing_share: float  # of the damage, 0 to 1
    swings: int  # counted in one motion
    within_turn: bool = False  # the swing that does the damage comes once a turn of the motor
    chip: str = ""  # which chip this is the life of


def estimate(tj: np.ndarray, fast: list[tuple[float, float, float]] | None = None, chip: str = "") -> Life:
    """Life of one chip whose junction follows this trace, over and over.

    fast holds the swings the trace is too slow to show: those that come once a turn of
    the motor, as (size, mean, how many). They are added to the count as they are.
    """
    slow = rainflow(tj)
    quick = [(s, m, c) for s, m, c in (fast or []) if s >= SMALLEST and c > 0]
    found = slow + quick
    if not found:
        return Life(float("inf"), 0.0, float(np.mean(tj)), 0.0, 0, chip=chip)
    damage = [count / cycles_to_failure(size, mean) for size, mean, count in found]
    total = sum(damage)
    worst = int(np.argmax(damage))
    return Life(
        1.0 / total,
        found[worst][0],
        found[worst][1],
        damage[worst] / total,
        len(found),
        within_turn=worst >= len(slow),
        chip=chip,
    )


def worst_of(chips: dict, swings: dict) -> Life | None:
    """The shortest life among the chips of a stage, each from its own trace."""
    lives = [estimate(np.asarray(trace), swings.get(label), label) for label, trace in chips.items() if len(trace)]
    return min(lives, key=lambda life: life.repeats) if lives else None
