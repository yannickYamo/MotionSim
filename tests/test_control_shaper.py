"""The input shaper on the move asked (input_shaper, control/regulators.py).

The expected values do not come from the shaper's own formulas: a lightly damped mode,
y'' + 2ζω y' + ω² y = ω² u, is integrated here (scipy's lsim) from what the shaper gives for a
step, and the swing left once the shaped step is over is set against the swing a bare step
leaves. Zero vibration (ZV) leaves none at the mode it is set for; ZV and derivative (ZVD) also
leaves little where the mode is off its figure, more robustly than ZV; both reach the target
unchanged, ZV half a period of the mode later, ZVD a whole period later.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from scipy.signal import lsim

from motionsim.control.blocks import BLOCKS, Context

TS = 1.0 / 16000.0
F = 40.0  # Hz, the mode
ZETA = 0.02


def _shaper(shape: str, frequency: float = F, damping: float = ZETA):
    ctx = Context(TS, 1.0 / TS, 48.0, 0.1, 1e-3, 1e-3, 0.01, 3)
    block = BLOCKS["input_shaper"]("shaper", {"shape": shape, "frequency": frequency, "damping": damping}, ctx)
    block.reset()
    return block


def _shaped(block, n: int) -> np.ndarray:
    return np.array([block.step(k * TS, 1.0)[0] for k in range(n)])


def _left_swinging(u: np.ndarray, f: float = F, zeta: float = ZETA, after: float = 0.06) -> float:
    """Peak to peak of the mode about its end, over two periods from `after` s on."""
    w = 2.0 * math.pi * f
    t = np.arange(u.size) * TS
    _, y, _ = lsim(([w * w], [1.0, 2.0 * zeta * w, w * w]), u, t)
    tail = y[(t >= after) & (t < after + 2.0 / f)]
    return float(tail.max() - tail.min())


N = int(0.2 / TS)
BARE = np.ones(N)


def test_zero_vibration_leaves_the_mode_it_is_set_for_still():
    bare = _left_swinging(BARE)
    assert bare > 0.5
    assert _left_swinging(_shaped(_shaper("zv"), N)) < 0.02 * bare


def test_zvd_leaves_little_where_the_mode_is_off_its_figure_and_less_than_zv():
    off = 1.15 * F
    bare = _left_swinging(BARE, f=off)
    zv = _left_swinging(_shaped(_shaper("zv"), N), f=off)
    zvd = _left_swinging(_shaped(_shaper("zvd"), N), f=off)
    assert zvd < 0.1 * bare
    assert zvd < 0.5 * zv


def test_the_target_is_reached_unchanged_half_a_period_or_a_period_later():
    period = 1.0 / (F * math.sqrt(1.0 - ZETA**2))
    for shape, late in (("zv", 0.5 * period), ("zvd", period)):
        out = _shaped(_shaper(shape), N)
        assert out[-1] == pytest.approx(1.0, rel=1e-12)
        done = int(np.argmax(np.abs(out - 1.0) < 1e-12)) * TS
        assert done == pytest.approx(late, abs=1.5 * TS)
        assert out[0] < 1.0


def test_a_steady_move_passes_unchanged_from_a_warm_start():
    block = _shaper("zvd")
    block.warm({"ref": 120.0})
    assert all(block.step(k * TS, 120.0)[0] == pytest.approx(120.0, rel=1e-12) for k in range(400))


def test_with_no_mode_set_the_move_passes():
    block = _shaper("zv", frequency=0.0)
    assert [block.step(k * TS, x)[0] for k, x in enumerate((1.0, -2.0, 3.5))] == [1.0, -2.0, 3.5]
