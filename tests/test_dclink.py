"""Energy returned by braking and the DC-link voltage it leads to."""

from __future__ import annotations

import math

import pytest
from conftest import V_REF, line, linear_device

from motionsim import dclink, guard
from motionsim.cycle import run_cycle
from motionsim.engine import OperatingPoint
from motionsim.load import Load, Profile, Segment
from motionsim.motor import BrushedDc

BASE = OperatingPoint(
    v_dc=V_REF, i_rms=0.0, modulation_index=0.0, power_factor=1.0, f_sw=8000.0, t_sink=40.0
)
MOTOR = BrushedDc(type="dc", kt=0.5, r=0.5)
STOP = Profile(segments=[
    Segment(duration=0.5, speed_start=2000, speed_end=2000),
    Segment(duration=0.5, speed_start=2000, speed_end=0),
])


def lossless():
    return linear_device(sw_curves=[line(25.0, 0.0, 0.0)], d_curves=[line(25.0, 0.0, 0.0)])


def test_stopping_a_flywheel_returns_its_kinetic_energy_less_the_winding_loss() -> None:
    inertia = 0.02
    cycle = run_cycle(lossless(), MOTOR, Load(inertia=inertia), STOP, BASE, per_segment=200)
    r = dclink.returned(cycle, V_REF, 600.0)
    w = 2000 * 2 * math.pi / 60
    current = inertia * (w / 0.5) / 0.5
    # Returned power falls in a straight line from its peak to zero at the speed where the
    # back-EMF only just covers the winding drop; below that the supply feeds the braking.
    peak = 0.5 * w * current - 0.5 * current**2
    time_returning = 0.5 * (1 - (0.5 * current / 0.5) / w)
    assert r.energy == pytest.approx(0.5 * peak * time_returning, rel=1e-3)
    assert r.burst_energy == pytest.approx(r.energy)
    assert r.peak_power == pytest.approx(peak, rel=0.01)
    assert r.energy < 0.5 * inertia * w**2  # never more than the flywheel held


def test_link_voltage_follows_the_capacitor_energy_balance() -> None:
    cycle = run_cycle(lossless(), MOTOR, Load(inertia=0.02), STOP, BASE, per_segment=50)
    capacitance = 470e-6
    r = dclink.returned(cycle, V_REF, 600.0, capacitance=capacitance)
    assert 0.5 * capacitance * (r.v_peak**2 - V_REF**2) == pytest.approx(r.burst_energy)
    # The capacitance asked for is the one that lands exactly on the limit.
    at_limit = dclink.returned(cycle, V_REF, 600.0, capacitance=r.capacitance_needed)
    assert at_limit.v_peak == pytest.approx(0.8 * 600.0)


def test_verdicts() -> None:
    cycle = run_cycle(lossless(), MOTOR, Load(inertia=0.02), STOP, BASE, per_segment=50)
    needed = dclink.returned(cycle, V_REF, 600.0).capacitance_needed

    def level(capacitance=None):
        r = dclink.returned(cycle, V_REF, 600.0, capacitance=capacitance)
        return dclink.check(r, V_REF, 600.0, supply="one-way")[0].level

    assert level(0.3 * needed) is guard.Level.fail  # past the rating
    assert level(0.8 * needed) is guard.Level.caution  # past 80% of it
    assert level(2 * needed) is guard.Level.ok
    assert level() is guard.Level.caution  # no capacitance given: says what is needed
    battery = dclink.check(dclink.returned(cycle, V_REF, 600.0), V_REF, 600.0, supply="battery")
    assert battery[0].level is guard.Level.ok and "charging current" in battery[0].message
    coasting = Profile(segments=[Segment(duration=1, speed_start=2000, speed_end=2000)])
    none = run_cycle(lossless(), MOTOR, Load(constant_torque=1.0), coasting, BASE)
    assert dclink.check(dclink.returned(none, V_REF, 600.0), V_REF, 600.0, supply="one-way") == []
