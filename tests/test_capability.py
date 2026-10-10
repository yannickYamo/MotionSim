"""What a device can drive: the torque it holds at a speed, and how that moves."""

from __future__ import annotations

import pytest
from conftest import V_REF, line, linear_device

from motionsim.capability import against, envelope, torque_limit
from motionsim.drivers import at_speed_and_torque
from motionsim.engine import OperatingPoint
from motionsim.engine.limits import hottest
from motionsim.motor import Pmsm

OP = OperatingPoint(v_dc=V_REF, i_rms=0.0, modulation_index=0.0, power_factor=1.0, f_sw=10000.0, t_sink=60.0)
MOTOR = Pmsm(type="pmsm", pole_pairs=4, kv=40, l=0.002, rs=0.2)


def device():
    return linear_device(sw_curves=[line(25.0, 1.0, 0.03)], d_curves=[line(25.0, 1.0, 0.03)], k_on=4e-5, k_off=4e-5, k_rr=1e-5)


def test_at_the_limit_the_hottest_junction_is_at_its_rating() -> None:
    d = device()
    found = torque_limit(d, MOTOR, 1000.0, OP)
    assert found.reason == "junction" and found.torque > 0
    assert found.tj == pytest.approx(d.ratings.tj_max, abs=0.5)
    # A little more and it is over; the point itself solves.
    over = at_speed_and_torque(d, MOTOR, 1000.0, 1.02 * found.torque, OP)
    assert hottest(over.result) > d.ratings.tj_max


def test_the_limit_falls_with_switching_frequency_and_with_a_hotter_heatsink() -> None:
    d = device()
    by_frequency = [x.torque for x in against(d, MOTOR, 1000.0, OP, "f_sw", [4000.0, 8000.0, 16000.0, 32000.0])]
    assert by_frequency == sorted(by_frequency, reverse=True) and by_frequency[0] > 1.2 * by_frequency[-1]
    by_sink = [x.torque for x in against(d, MOTOR, 1000.0, OP, "t_sink", [40.0, 60.0, 80.0, 100.0])]
    assert by_sink == sorted(by_sink, reverse=True)


def test_past_the_motors_reach_the_motor_is_what_stops_it() -> None:
    d = device()
    limits = envelope(d, MOTOR, [500.0, 1000.0, 60000.0], OP)
    assert limits[0].reason == "junction" and limits[-1].reason == "motor"
    assert limits[-1].torque < limits[0].torque
