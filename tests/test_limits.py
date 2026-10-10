from __future__ import annotations

import math

import pytest
from conftest import V_REF, line, linear_device

from motionsim.engine import OperatingPoint
from motionsim.engine.limits import max_current


def test_max_current_matches_closed_form() -> None:
    """Switch with a constant on-state voltage: Tj = Ts + R*V0*c*Irms, linear in current."""
    v0, rth, t_sink, limit, m, pf = 1.2, 2.0, 50.0, 150.0, 0.9, 0.8
    c = math.sqrt(2) * (1 / (2 * math.pi) + m * pf / 8)
    device = linear_device(
        sw_curves=[line(25.0, v0, 0.0)], d_curves=[line(25.0, 0.0, 0.0)], rth_sw=rth
    )
    op = OperatingPoint(
        v_dc=V_REF, i_rms=0.0, modulation_index=m, power_factor=pf, f_sw=0.0, t_sink=t_sink
    )
    i_max, result = max_current(device, op, tj_limit=limit, peak=False)
    assert i_max == pytest.approx((limit - t_sink) / (rth * v0 * c), rel=0.01)
    assert result.tj_switch == pytest.approx(limit, abs=0.5)


def test_no_current_when_sink_is_at_the_limit() -> None:
    device = linear_device(sw_curves=[line(25.0, 1.0, 0.0)], d_curves=[line(25.0, 0.0, 0.0)])
    op = OperatingPoint(
        v_dc=V_REF, i_rms=0.0, modulation_index=0.9, power_factor=0.8, f_sw=0.0, t_sink=150.0
    )
    assert max_current(device, op, tj_limit=150.0) == (0.0, None)


def test_the_current_check_is_per_device_when_devices_share_a_switch() -> None:
    """Two devices in parallel each carry half: 1.6 times one rating at the switch is 0.8 each."""
    from dataclasses import replace

    from motionsim import guard
    from motionsim.device import load_device
    from motionsim.engine import OperatingPoint, solve

    device = load_device("examples/synthetic_igbt_600v_30a.yaml")
    op = OperatingPoint(v_dc=300.0, i_rms=10.0, modulation_index=0.9, power_factor=0.85, f_sw=8000.0, t_sink=60.0)
    at_switch = 1.6 * device.ratings.i_nominal
    level = lambda o: next(c for c in guard.check(device, o, solve(device, o), at_switch) if c.topic == "current")  # noqa: E731
    assert level(op).level is guard.Level.caution
    pair = level(replace(op, parallel=2))
    assert pair.level is guard.Level.ok and "shared by 2" in pair.message


def test_the_pulsed_rating_is_a_hard_limit_and_the_short_circuit_time_is_passed_on() -> None:
    from motionsim import guard
    from motionsim.device import load_device
    from motionsim.engine import OperatingPoint, solve

    device = load_device("examples/synthetic_igbt_600v_30a.yaml")
    op = OperatingPoint(v_dc=300.0, i_rms=10.0, modulation_index=0.9, power_factor=0.85, f_sw=8000.0, t_sink=60.0)
    result = solve(device, op)
    plain = guard.check(device, op, result, 70.0)
    assert not [c for c in plain if c.level is guard.Level.fail and c.topic == "current"]
    assert not [c for c in plain if c.topic == "protection"]
    device.ratings.i_pulsed, device.ratings.t_sc = 60.0, 5e-6
    rated = guard.check(device, op, result, 70.0)
    assert [c for c in rated if c.level is guard.Level.fail and "pulsed rating" in c.message]
    assert [c for c in rated if c.topic == "protection" and "5 µs" in c.message]
    assert not [c for c in guard.check(device, op, result, 50.0) if c.level is guard.Level.fail and c.topic == "current"]
