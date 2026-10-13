"""What has to hold at any operating point, tried at points nobody chose.

The other tests check figures at points picked by hand. These state what must be true
everywhere inside a device's ratings, and let the points be drawn at random: a loss is
never negative, more current or a faster switch never loses less, a hotter heatsink never
makes a cooler junction, and a comparison does not depend on the order its parts are named in.
"""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from test_propose import BASE, MOTOR, igbt

from motionsim.device import load_device
from motionsim.engine import OperatingPoint
from motionsim.engine.limits import hottest
from motionsim.engine.solver import solve
from motionsim.motor.stage import Unreachable
from motionsim.propose import propose

ROOT = Path(__file__).parent.parent
IGBT = load_device(ROOT / "examples/synthetic_igbt_600v_30a.yaml")
MOSFET = load_device(ROOT / "examples/synthetic_mosfet_100v_100a.yaml")
QUICK = settings(max_examples=30, deadline=None)

# Points inside each made-up part's ratings: (device, the conditions it needs beyond the point).
igbt_points = st.builds(
    lambda i, m, pf, f, t: OperatingPoint(v_dc=300, i_rms=i, modulation_index=m, power_factor=pf, f_sw=f, t_sink=t),
    st.floats(0.5, 14),
    st.floats(0.05, 1.0),
    st.floats(-1, 1),
    st.floats(2e3, 2e4),
    st.floats(20, 80),
)
fet_points = st.builds(
    lambda i, m, pf, f, t: OperatingPoint(
        v_dc=48,
        i_rms=i,
        modulation_index=m,
        power_factor=pf,
        f_sw=f,
        t_sink=t,
        v_drive=10,
        rg_on=5,
        rg_off=5,
        t_dead=1.5e-7,
    ),
    st.floats(1, 40),
    st.floats(0.05, 1.0),
    st.floats(-1, 1),
    st.floats(5e3, 6e4),
    st.floats(20, 80),
)
cases = st.one_of(st.tuples(st.just(IGBT), igbt_points), st.tuples(st.just(MOSFET), fet_points))


@QUICK
@given(cases)
def test_a_loss_is_never_negative_and_a_junction_never_cooler_than_its_heatsink(case) -> None:
    device, op = case
    r = solve(device, op)
    parts = [
        r.switch.conduction,
        r.switch.turn_on,
        r.switch.turn_off,
        r.switch.dead_time,
        r.switch.recovery,
        r.diode.conduction,
        r.diode.recovery,
    ]
    assert all(math.isfinite(x) and x >= 0 for x in parts) and math.isfinite(r.p_inverter) and r.p_inverter > 0
    assert op.t_sink <= r.tj_switch <= r.tj_switch_peak + 1e-9 and hottest(r) < device.ratings.tj_max + 200


@QUICK
@given(cases, st.floats(1.05, 1.6))
def test_more_current_never_loses_less(case, more) -> None:
    device, op = case
    assert solve(device, replace(op, i_rms=op.i_rms * more)).p_inverter > solve(device, op).p_inverter


@QUICK
@given(cases, st.floats(1.1, 2.0))
def test_switching_faster_never_loses_less(case, faster) -> None:
    device, op = case
    assert solve(device, replace(op, f_sw=op.f_sw * faster)).p_inverter > solve(device, op).p_inverter


@QUICK
@given(cases, st.floats(2, 25))
def test_a_hotter_heatsink_never_makes_a_cooler_junction(case, warmer) -> None:
    device, op = case
    # The loss itself may fall as a part warms (an IGBT at low current drops less voltage
    # hot than cold), but never by enough to leave the junction cooler than it was.
    cool, warm = solve(device, op), solve(device, replace(op, t_sink=op.t_sink + warmer))
    assert hottest(warm) > hottest(cool)


@QUICK
@given(cases)
def test_two_in_parallel_carrying_twice_the_current_are_one_twice_over(case) -> None:
    """On a heatsink held at a temperature, with nothing between the parts to make them
    share unevenly, two devices each carrying what one carried lose twice what one lost."""
    device, op = case
    one = solve(device, op)
    two = solve(device, replace(op, i_rms=2 * op.i_rms, parallel=2))
    assert two.p_inverter == pytest.approx(2 * one.p_inverter, rel=1e-6)
    assert hottest(two) == pytest.approx(hottest(one), abs=1e-3)


@settings(max_examples=12, deadline=None)
@given(st.floats(0.6, 1.4), st.floats(0.6, 1.4), st.floats(500, 2500), st.floats(1, 12))
def test_a_comparison_does_not_depend_on_the_order_its_parts_are_named_in(a, b, rpm, torque) -> None:
    first, second = igbt("first", a), igbt("second", b)
    try:
        one, other = (
            propose([first, second], MOTOR, rpm, torque, BASE),
            propose([second, first], MOTOR, rpm, torque, BASE),
        )
    except Unreachable:
        assume(False)  # a point this motor cannot reach from this supply: not a comparison at all
    assert [c.device.part_number for c in one] == [c.device.part_number for c in other] or one[0].loss == pytest.approx(
        one[1].loss
    )
    by_name = lambda found: {c.device.part_number: (c.loss, c.level, c.margin) for c in found}
    assert by_name(one) == by_name(other)
