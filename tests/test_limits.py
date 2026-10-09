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
