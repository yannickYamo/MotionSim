"""The torque learned over the turn (periodic_compensation, control/regulators.py).

The expected values are the load's own: an ideal shaft is stepped here, J·dω/dt = T − T_L(θ),
with a proportional speed loop, so what the block should learn is the load's harmonic, whose
amplitude and phase the test sets.
"""

from __future__ import annotations

import math

import pytest

from motionsim.control.blocks import BLOCKS, Context

J, TS, W0 = 3e-4, 1e-4, 2.0 * math.pi * 40.0  # kg·m², s, rad/s (40 turns a second)


def _block(**params: float):
    ctx = Context(TS, 1.0 / TS, 48.0, 0.1, 1e-3, 1e-3, 0.01, 3)
    block = BLOCKS["periodic_compensation"](
        "periodic", {"harmonics": 3.0, "gain": 0.2, "inertia": J, "reach": 1e6, "floor": 1.0, **params}, ctx
    )
    block.reset()
    return block


def _run(block, load, turns: float, kp: float = 0.02):
    """The shaft stepped with the block between a proportional speed loop and the motor.
    Returns the speed's swing over the last turn and the block's last outputs."""
    omega, angle, t = W0, 0.0, 0.0
    steps = int(turns / (W0 / (2.0 * math.pi)) / TS)
    last_turn = int(1.0 / (W0 / (2.0 * math.pi)) / TS)
    speeds = []
    for k in range(steps):
        asked = kp * (W0 - omega) + 2.0  # a mean torque of 2 N·m, as the load's
        out, _, _ = block.step(t, asked, omega)
        omega += TS / J * (out - 2.0 - load(angle))
        angle += omega * TS
        t += TS
        if k >= steps - last_turn:
            speeds.append(omega)
    return max(speeds) - min(speeds)


def test_the_load_s_harmonic_is_learned_and_the_shaft_runs_smooth():
    amplitude, phase = 1.5, 0.7
    load = lambda a: amplitude * math.cos(a - phase)
    plain = _run(_block(gain=0.0), load, 40)
    block = _block()
    smooth = _run(block, load, 40)
    # What it learned: the first harmonic of the load, A at φ, read at the middle of each step
    # where this shaft applies the load at its start: half a step's angle later, ½·ω·Ts.
    assert math.hypot(block._a[0], block._b[0]) == pytest.approx(amplitude, rel=1e-3)
    assert math.atan2(block._b[0], block._a[0]) == pytest.approx(phase + 0.5 * W0 * TS, abs=1e-3)
    assert block._mean == pytest.approx(2.0, rel=1e-3)  # the mean, learned apart and not given
    assert abs(block._a[1]) + abs(block._b[1]) < 0.02 * amplitude
    assert smooth < plain / 20.0


def test_a_harmonic_beyond_the_reach_is_neither_learned_nor_given():
    # The load at the second harmonic (80 Hz), the reach at 60 Hz: only the first is within.
    load = lambda a: 1.0 * math.cos(2.0 * a)
    block = _block(reach=60.0)
    _run(block, load, 20)
    assert block._a[1] == 0.0 and block._b[1] == 0.0
    # Within the reach it is learned.
    block = _block(reach=100.0)
    _run(block, load, 20)
    assert math.hypot(block._a[1], block._b[1]) == pytest.approx(1.0, rel=0.05)


def test_below_the_floor_nothing_is_learned():
    block = _block(floor=2.0 * W0)
    _run(block, lambda a: math.cos(a), 10)
    assert all(v == 0.0 for v in (*block._a, *block._b))


def test_with_no_gain_the_block_passes_the_torque_through():
    block = _block(gain=0.0)
    for k in range(50):
        out, learned, _ = block.step(k * TS, 1.25, W0)
        assert (out, learned) == (1.25, 0.0)
