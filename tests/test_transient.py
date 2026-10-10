"""Temperature through time, against closed-form heating and the steady solution."""

from __future__ import annotations

import math

import numpy as np
import pytest
from conftest import V_REF, line, linear_device

from motionsim.device import FosterNetwork, Source
from motionsim.drivers import at_speed_and_torque
from motionsim.engine import OperatingPoint
from motionsim.engine.limits import hottest
from motionsim.engine.thermal import zth
from motionsim.load import G, Gravity, Load, Profile, Segment
from motionsim.motor import BrushedDc, Pmsm
from motionsim.transient import Heatsink, follow

SRC = Source(kind="synthetic")
NETWORK = FosterNetwork(r=[0.3, 0.7], tau=[0.002, 0.05], source=SRC)
BASE = OperatingPoint(
    v_dc=V_REF, i_rms=0.0, modulation_index=0.0, power_factor=1.0, f_sw=8000.0, t_sink=60.0
)
PMSM = Pmsm(pole_pairs=4, flux_linkage=0.1, l=0.008, rs=1.0)
DC = BrushedDc(type="dc", kt=0.5, r=1.0)


def device():
    """Losses that do not depend on temperature, so heating has a closed form."""
    d = linear_device(
        sw_curves=[line(25.0, 0.9, 0.03)], d_curves=[line(25.0, 1.0, 0.025)],
        k_on=20e-6, k_off=15e-6, k_rr=5e-6,
    )
    d.switch.thermal = NETWORK
    d.diode.thermal = NETWORK
    return d


def steady(speed: float, duration: float) -> Profile:
    return Profile(segments=[Segment(duration=duration, speed_start=speed, speed_end=speed)])


def test_a_long_steady_motion_settles_at_the_steady_solution() -> None:
    load = Load(constant_torque=4.0)
    _, trace = follow(device(), PMSM, load, steady(1500, 2.0), BASE)
    point = at_speed_and_torque(device(), PMSM, 1500, 4.0, BASE)
    assert trace.tj[-1] == pytest.approx(hottest(point.result), abs=0.2)
    assert trace.tj[0] < trace.tj[-1]
    assert np.allclose(trace.steady, hottest(point.result))


def test_a_short_pulse_heats_the_chip_by_power_times_transient_impedance() -> None:
    """A DC motor's chopping switch carries a constant loss: rise = P * Zth(t)."""
    load = Load(constant_torque=5.0)
    pulse = 0.004
    cycle, trace = follow(device(), DC, load, steady(600, pulse), BASE, per_segment=1)
    role = max(cycle.steps[0].point.result.roles, key=lambda r: r.hottest)
    loss = max(role.switch.total, role.diode.total)
    assert trace.tj[0] - BASE.t_sink == pytest.approx(loss * float(zth(NETWORK, pulse)), rel=1e-6)
    assert trace.tj[0] < trace.steady[0] - 5


def test_cooling_between_pulses_follows_the_network() -> None:
    load = Load(inertia=0.01)
    profile = Profile(segments=[
        Segment(duration=0.02, speed_start=0, speed_end=600),  # accelerate: torque
        Segment(duration=0.03, speed_start=600, speed_end=600),  # coast: none
    ])
    cycle, trace = follow(device(), DC, load, profile, BASE, per_segment=1)
    role = max(cycle.steps[0].point.result.roles, key=lambda r: r.hottest)
    loss = role.switch.total
    stages = np.array(NETWORK.r) * (1 - np.exp(-0.02 / np.array(NETWORK.tau)))
    after = float((stages * np.exp(-0.03 / np.array(NETWORK.tau))).sum())
    # The coast reports its highest point, its start; one more instant shows the decayed value.
    profile.segments.append(Segment(duration=1e-6, speed_start=600, speed_end=600))
    _, trace = follow(device(), DC, load, profile, BASE, per_segment=1)
    assert trace.tj[-1] - BASE.t_sink == pytest.approx(loss * after, rel=1e-3)


def test_a_heatsink_warms_exponentially_towards_ambient_plus_loss_times_resistance() -> None:
    load = Load(constant_torque=4.0)
    sink = Heatsink(rth=0.5, capacity=40.0, t_ambient=30.0)
    base = OperatingPoint(**{**BASE.__dict__, "t_sink": 30.0})
    duration = 30.0
    cycle, trace = follow(device(), PMSM, load, steady(1500, duration), base, heatsink=sink)
    loss = cycle.steps[0].point.result.p_inverter
    expected = 30.0 + loss * sink.rth * (1 - math.exp(-duration / (sink.rth * sink.capacity)))
    assert trace.t_sink[-1] == pytest.approx(expected, rel=1e-3)
    point = at_speed_and_torque(device(), PMSM, 1500, 4.0, base)
    rise = hottest(point.result) - base.t_sink
    assert trace.tj[-1] - trace.t_sink[-2] == pytest.approx(rise, abs=0.3)


def test_a_slowly_turning_motor_reaches_the_peak_of_the_periodic_solution() -> None:
    """At 1.5 rpm the output period is ten seconds; followed through several periods, the
    hottest junction must match the periodic steady solution found in the frequency domain."""
    load = Load(constant_torque=4.0)
    _, trace = follow(device(), PMSM, load, steady(1.5, 30.0), BASE, per_segment=120)
    point = at_speed_and_torque(device(), PMSM, 1.5, 4.0, BASE)
    assert trace.tj[60:].max() == pytest.approx(hottest(point.result), abs=0.5)


def test_standstill_starts_at_the_worst_rotor_position() -> None:
    load = Load(gravity=Gravity(mass=2.0, arm=0.2))  # held horizontal: m * g * arm
    hold = Profile(start_angle_deg=90, segments=steady(0, 2.0).segments)
    cycle, trace = follow(device(), PMSM, load, hold, BASE)
    torque = cycle.steps[0].sample.motor_torque
    assert torque == pytest.approx(2.0 * G * 0.2)
    point = at_speed_and_torque(device(), PMSM, 0, torque, BASE)
    assert trace.tj[-1] == pytest.approx(hottest(point.result), abs=1.0)


def test_repeating_a_motion_carries_the_heat_over() -> None:
    load = Load(inertia=0.01)
    profile = Profile(segments=[
        Segment(duration=0.02, speed_start=0, speed_end=600),
        Segment(duration=0.01, speed_start=600, speed_end=600),
        Segment(duration=0.02, speed_start=600, speed_end=0),
    ])
    _, once = follow(device(), DC, load, profile, BASE)
    _, thrice = follow(device(), DC, load, profile, BASE, repeats=3)
    assert thrice.time[-1] == pytest.approx(3 * once.time[-1])
    assert thrice.peak > once.peak


def test_life_counts_the_swing_of_every_turn_of_the_motor() -> None:
    """A chip heats and cools once a turn. Turning slowly those swings are large and are what
    wears it out; turning fast with the same current they are small. The life has to show it."""
    from motionsim.lifetime import worst_of
    device = linear_device(
        sw_curves=[line(25.0, 1.0, 0.03)], d_curves=[line(25.0, 1.0, 0.03)], k_on=4e-5, k_off=4e-5, k_rr=1e-5,
    )
    motor = Pmsm(type="pmsm", pole_pairs=4, kv=60, l=0.0005, rs=0.05)
    op = OperatingPoint(v_dc=V_REF, i_rms=0.0, modulation_index=0.0, power_factor=1.0, f_sw=10000.0, t_sink=60.0)

    def life(rpm: float):
        load = Load(constant_torque=4.0)
        profile = Profile(segments=[Segment(duration=60.0, speed_start=rpm, speed_end=rpm)])
        _, trace = follow(device, motor, load, profile, op)
        return worst_of(trace.chips, trace.swings), trace

    slow, slow_trace = life(30.0)  # 2 Hz electrical
    fast, _ = life(3000.0)
    assert slow.repeats < fast.repeats / 10
    assert slow.chip and slow.swing > fast.swing
    # About two swings a second for a minute, each about the swing within one turn.
    label = slow.chip
    counted = sum(c for _, _, c in slow_trace.swings.get(label, []))
    from motionsim.lifetime import rainflow
    in_trace = sum(c for s, _, c in rainflow(slow_trace.chips[label]) if s > 0.5 * slow.swing)
    assert 100 <= counted + in_trace <= 140
