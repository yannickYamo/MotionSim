"""The speed loop by active disturbance rejection (regulators.SpeedAdrc).

Expected values are worked here, not read from the block: on a shaft that is one integrator,
ω[k+1] = ω[k] + Ts·b0·u[k], the separation of the observer and the control law puts the
closed loop's poles at 1 − ωc·Ts and at the observer's double pole e^(−ωo·Ts); a constant
load leaves no error once the observer has it; and the block's own step matches the
transfer it gives the linear view.
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest
from test_control_bench import design

from motionsim.control import context
from motionsim.control.blocks import kind_of
from motionsim.control.presets import BUILDERS

TS, J = 1.0 / 10000.0, 2e-4


def _block(bandwidth=20.0, observer=5.0, inertia=J, limit=1e12):
    d = design()
    scheme = BUILDERS["foc_servo"](d)
    ctx = replace(context(d, scheme), ts=TS)
    block = kind_of("speed_adrc")(
        "speed", {"bandwidth": bandwidth, "observer": observer, "inertia": inertia, "limit": limit}, ctx
    )
    block.reset()
    return block, block.ctx.ts


def test_the_closed_loop_poles_are_the_control_laws_and_the_observers():
    block, ts = _block()
    num, den = block.transfer()
    b0 = 1.0 / J
    # 1 + C·P = 0 with P = Ts·b0/(z − 1): den·(z − 1) + num·Ts·b0 = 0.
    char = np.polyadd(np.polymul(den, [1.0, -1.0]), np.polymul(num, [ts * b0]))
    poles = list(np.roots(char))
    wc, beta = 2 * math.pi * 20.0, math.exp(-5.0 * 2 * math.pi * 20.0 * ts)
    # Each expected pole claims its nearest root; a double pole split into a pair is caught by
    # its imaginary parts, a moved one by its distance (the split of a double root under
    # rounding is of the order of the square root of the machine's precision).
    for expected in (1.0 - wc * ts, beta, beta):
        nearest = min(poles, key=lambda z: abs(z - expected))
        assert abs(nearest - expected) < 1e-6
        poles.remove(nearest)


def _shaft(block, ts, steps, load=0.0, at=0, inertia=J, ref=100.0):
    w, out = 0.0, []
    for k in range(steps):
        torque = block.step(k * ts, ref, w, 0.0)[0]
        w += ts * (torque - (load if k >= at else 0.0)) / inertia
        out.append(w)
    return out


def test_a_load_step_leaves_no_error_once_the_observer_has_it():
    block, ts = _block()
    run = _shaft(block, ts, 20000, load=0.05, at=10000)
    assert run[9999] == pytest.approx(100.0, rel=1e-6)
    assert run[-1] == pytest.approx(100.0, rel=1e-6)
    assert min(run[10000:]) < 100.0  # the step was felt


def test_an_inertia_twice_the_one_assumed_still_settles_where_it_is_asked():
    block, ts = _block()
    run = _shaft(block, ts, 30000, inertia=2 * J)
    assert run[-1] == pytest.approx(100.0, rel=1e-6)


def test_the_blocks_step_is_the_transfer_it_gives():
    """With the reference at nought, u = −C(z)·y: drive y with a sine, compare."""
    block, ts = _block(bandwidth=15.0, observer=4.0)
    num, den = block.transfer()
    y = [math.sin(2 * math.pi * 37.0 * k * ts) for k in range(3000)]
    u = [block.step(k * ts, 0.0, y[k], 0.0)[0] for k in range(3000)]
    # The difference equation of C(z) = num/den, in z⁻¹ (num has one fewer coefficient than den).
    b, a = [0.0, *num], den
    expect = []
    for k in range(3000):
        acc = sum(b[i] * y[k - i] for i in range(3) if k - i >= 0)
        acc -= sum(a[i] * expect[k - i] for i in range(1, 3) if k - i >= 0)
        expect.append(acc)
    assert u[100:] == pytest.approx([-e for e in expect[100:]], rel=1e-9, abs=1e-9)


def test_the_limit_holds_and_nothing_winds_up():
    block, ts = _block(limit=0.2)
    run = _shaft(block, ts, 40000)
    assert max(run) < 100.0 * 1.02  # a PI with no anti-windup would sail past
    assert run[-1] == pytest.approx(100.0, rel=1e-6)


def test_the_linear_view_s_closed_loop_is_the_block_s_own_step():
    """The reference does not pass through the feedback C(z): T = P·Cr/(1 + P·C). Its step on
    an ideal shaft is the block's own, sample for sample (the block's speed read after it moves),
    with no overshoot, where L/(1 + L) would show one."""
    import numpy as np
    from scipy.signal import dlti, dstep

    blk, ts = _block(bandwidth=20.0)
    cn, cd = blk.transfer()
    rn, rd = blk.reference_transfer()
    pn, pd = [ts / J], [1.0, -1.0]
    t_num = np.polymul(np.polymul(rn, pn), cd)
    t_den = np.polymul(rd, np.polyadd(np.polymul(cd, pd), np.polymul(cn, pn)))
    _, (y,) = dstep(dlti(t_num, t_den, dt=ts), n=3000)
    w, ys = 0.0, []
    for k in range(3000):
        u = blk.step(k * ts, 1.0, w, 0.0)[0]
        w += ts / J * u
        ys.append(w)
    assert np.abs(y.ravel()[1:] - np.array(ys[:-1])).max() < 1e-5
    assert y.max() < 1.0 + 1e-6
