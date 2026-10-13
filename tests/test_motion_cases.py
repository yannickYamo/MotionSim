"""A motion through time: what each figure along it must be, from closed forms and plain arithmetic."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest
from conftest import V_REF, line, linear_device

from motionsim import dclink, guard, lifetime
from motionsim.capability import torque_limit
from motionsim.cycle import Cycle, Step, run_cycle
from motionsim.device import FosterNetwork, Source, Topology
from motionsim.drivers import at_speed_and_torque
from motionsim.engine import OperatingPoint
from motionsim.engine.limits import hottest
from motionsim.load import G, Load, Profile, Sample, Segment, Vehicle, sample
from motionsim.motor import BrushedDc, Pmsm
from motionsim.motor.stage import Unreachable
from motionsim.starting import Start, with_start
from motionsim.trajectory import BadTrajectory, Trajectory, load_trajectory, run
from motionsim.transient import follow

SRC = Source(kind="synthetic")
NETWORK = FosterNetwork(r=[0.3, 0.7], tau=[0.002, 0.05], source=SRC)
BASE = OperatingPoint(v_dc=V_REF, i_rms=0.0, modulation_index=0.0, power_factor=1.0, f_sw=8000.0, t_sink=60.0)
PMSM = Pmsm(pole_pairs=4, flux_linkage=0.1, l=0.008, rs=1.0)
DC = BrushedDc(type="dc", kt=0.5, r=1.0)
RTH, TAU = 1.0, 0.01  # the one-stage junction-to-case path of a device built without its own network


def device(**more):
    """Losses that do not depend on temperature, on a two-stage thermal path."""
    d = linear_device(
        sw_curves=[line(25.0, 0.9, 0.03)],
        d_curves=[line(25.0, 1.0, 0.025)],
        k_on=20e-6,
        k_off=15e-6,
        k_rr=5e-6,
        **more,
    )
    d.switch.thermal = NETWORK
    d.diode.thermal = NETWORK
    return d


def conducting(**more):
    """Conduction loss only: 0.9 V + 30 mΩ in the switch, 1.0 V + 25 mΩ in the diode."""
    return linear_device(sw_curves=[line(25.0, 0.9, 0.03)], d_curves=[line(25.0, 1.0, 0.025)], **more)


def steady(speed: float, duration: float) -> Profile:
    return Profile(segments=[Segment(duration=duration, speed_start=speed, speed_end=speed)])


def instant(rpm: float, torque: float, duration: float = 1.0) -> Sample:
    return Sample(0.0, duration, rpm * 2 * math.pi / 60, 0.0, 0.0, rpm, torque)


def write(tmp_path, text: str):
    path = tmp_path / "trajectory.csv"
    path.write_text(text, encoding="utf-8")
    return path


# ---------- temperature through time ----------


def test_a_long_braking_run_settles_at_the_diode_peak_of_the_steady_solution() -> None:
    point = at_speed_and_torque(device(), PMSM, 1500, -4.0, BASE)
    assert point.result.tj_diode_peak > point.result.tj_switch_peak + 0.3  # braking loads the diode
    _, trace = follow(device(), PMSM, Load(constant_torque=-4.0), steady(1500, 2.0), BASE)
    assert trace.tj[-1] == pytest.approx(point.result.tj_diode_peak, abs=0.02)


def test_chips_cool_along_their_network_through_an_instant_that_cannot_be_driven() -> None:
    heating, idle = 0.02, 0.03
    profile = Profile(
        segments=[
            Segment(duration=heating, speed_start=600, speed_end=600),
            Segment(duration=idle, speed_start=60000, speed_end=60000),  # back-EMF far above the link
        ]
    )
    cycle, trace = follow(device(), DC, Load(constant_torque=5.0), profile, BASE, per_segment=1)
    assert cycle.steps[0].point is not None and cycle.steps[1].point is None
    amps = 5.0 / DC.kt
    loss = (0.9 + 0.03 * amps) * amps  # the switch that stays on carries the armature current all the time
    r, tau = np.array(NETWORK.r), np.array(NETWORK.tau)
    stages = loss * r * (1 - np.exp(-heating / tau))
    assert trace.tj[0] - BASE.t_sink == pytest.approx(float(stages.sum()), rel=1e-6)
    assert trace.tj[1] - BASE.t_sink == pytest.approx(float((stages * np.exp(-idle / tau)).sum()), rel=1e-6)
    assert math.isnan(trace.steady[1])


def test_the_settled_figure_of_an_instant_is_taken_at_the_heatsink_temperature_given() -> None:
    """Losses here do not move with temperature, so every junction sits 0.2 K higher on a sink 0.2 K warmer."""
    warm = replace(BASE, t_sink=60.2)
    _, trace = follow(device(), PMSM, Load(constant_torque=4.0), steady(1500, 0.1), warm, per_segment=2)
    on_a_round_figure = hottest(at_speed_and_torque(device(), PMSM, 1500, 4.0, BASE).result)
    assert np.allclose(trace.steady, on_a_round_figure + 0.2, atol=1e-6)


def test_two_modules_in_parallel_in_still_air_each_warm_with_half_the_loss() -> None:
    case_to_sink, to_air, ambient = 0.1, 2.1, 40.0
    module = device(topology=Topology.six_pack, rth_cs=case_to_sink)
    base = replace(BASE, parallel=2, rth_free=to_air, t_sink=ambient)
    cycle, trace = follow(module, PMSM, Load(constant_torque=4.0), steady(1500, 0.1), base, per_segment=2)
    # What the module sits on is its path to the air less the layer the solution already counts.
    expected = ambient + (to_air - case_to_sink) * cycle.mean_loss / 2
    assert trace.t_sink[-1] == pytest.approx(expected, abs=0.3)
    assert trace.t_sink[-1] - ambient > 10  # far from where half as much, or twice as much, would put it


# ---------- an imported trajectory ----------


def test_a_trajectory_lasts_as_long_as_its_samples_together() -> None:
    step = 0.002
    trajectory = Trajectory(time=np.arange(4) * step, current={"a": np.zeros(4)}, duty={"a": np.full(4, 0.5)})
    assert trajectory.duration == pytest.approx(4 * step)


def test_from_cold_a_constant_diode_loss_heats_its_junction_by_power_times_transient_impedance() -> None:
    """Current into the leg with the high side on 90% of the time: the high-side reverse path carries it."""
    step, amps, on = 0.002, 10.0, 0.9
    trajectory = Trajectory(time=np.arange(4) * step, current={"a": np.full(4, -amps)}, duty={"a": np.full(4, on)})
    outcome = run(conducting(), trajectory, BASE)
    loss = (1.0 + 0.025 * amps) * amps * on
    ends = step * np.arange(1, 5)  # each figure is reached at the end of its sample
    assert outcome.time == pytest.approx(ends)
    assert outcome.tj_from_start - BASE.t_sink == pytest.approx(loss * RTH * (1 - np.exp(-ends / TAU)), rel=1e-9)


def test_from_cold_the_case_to_heatsink_layer_adds_its_rise_at_once() -> None:
    step, amps, layer = 0.002, 10.0, 0.5
    trajectory = Trajectory(time=np.arange(4) * step, current={"a": np.full(4, amps)}, duty={"a": np.ones(4)})
    outcome = run(conducting(rth_cs=layer), trajectory, BASE)
    loss = (0.9 + 0.03 * amps) * amps
    ends = step * np.arange(1, 5)
    expected = loss * (layer + RTH * (1 - np.exp(-ends / TAU)))
    assert outcome.tj_from_start - BASE.t_sink == pytest.approx(expected, rel=1e-9)


def test_a_repeating_trajectory_swings_at_the_frequency_of_its_whole_length() -> None:
    """A loss P0 + P1 cos(wt) through R and tau settles at P0 R + P1 |Z(w)| cos(wt - atan(w tau))."""
    n, length, amps, drop = 8, 0.02, 10.0, 1.0
    k = np.arange(n)
    flat = linear_device(sw_curves=[line(25.0, drop, 0.0)], d_curves=[line(25.0, drop, 0.0)])
    duty = 0.5 + 0.4 * np.cos(2 * np.pi * k / n)
    trajectory = Trajectory(time=k * length / n, current={"a": np.full(n, amps)}, duty={"a": duty})
    high_side = run(flat, trajectory, BASE).result.roles[0]
    w = 2 * math.pi / length
    swing = drop * amps * 0.4 * RTH / math.sqrt(1 + (w * TAU) ** 2)
    rise = drop * amps * 0.5 * RTH + swing * np.cos(2 * np.pi * k / n - math.atan(w * TAU))
    assert high_side.tj_switch_peak - BASE.t_sink == pytest.approx(float(rise.max()), rel=1e-6)


def test_a_time_stamp_given_twice_is_refused(tmp_path) -> None:
    with pytest.raises(BadTrajectory, match="time must increase"):
        load_trajectory(write(tmp_path, "time_s,i_a,d_a\n0,1,0.5\n0.001,2,0.5\n0.001,3,0.5\n0.002,4,0.5\n"))


def test_a_loaded_trajectory_ends_at_the_last_row_of_the_file(tmp_path) -> None:
    rows = "".join(f"{k / 1000},{k},0.5\n" for k in range(300))
    trajectory = load_trajectory(write(tmp_path, "time_s,i_a,d_a\n" + rows))
    assert trajectory.time[-1] == pytest.approx(0.299, rel=1e-9)
    assert trajectory.current["a"][-1] == pytest.approx(299.0, rel=1e-9)


def test_duty_cycles_a_rounding_error_outside_the_range_are_brought_into_it(tmp_path) -> None:
    text = "time_s,i_a,d_a,i_b,d_b\n0,1,1.0000005,1,-0.0000005\n0.001,1,1.0000005,1,-0.0000005\n0.002,1,1,1,0\n"
    trajectory = load_trajectory(write(tmp_path, text))
    assert trajectory.duty["a"].max() == 1.0
    assert trajectory.duty["b"].min() == 0.0


def test_a_log_of_three_rows_gives_the_loss_of_the_ramp_between_them(tmp_path) -> None:
    """A switch that is a pure resistance, always on, carrying a current that ramps from 0 to I:
    the mean loss is R I^2 / 3."""
    ohms, top = 0.03, 20.0
    resistive = linear_device(sw_curves=[line(25.0, 0.0, ohms)], d_curves=[line(25.0, 1.0, 0.0)])
    trajectory = load_trajectory(write(tmp_path, f"time_s,i_a,d_a\n0,0,1\n0.5,{top / 2},1\n1,{top},1\n"))
    outcome = run(resistive, trajectory, BASE)
    assert outcome.result.p_inverter == pytest.approx(ohms * top**2 / 3, rel=0.01)


# ---------- a whole motion ----------


def test_the_worst_instant_of_a_motion_is_the_hottest_and_not_the_one_that_loses_most() -> None:
    held = at_speed_and_torque(device(), PMSM, 0.0, 4.0, BASE)  # all the loss in the chips of one position
    turning = at_speed_and_torque(device(), PMSM, 1500.0, 5.0, BASE)
    assert turning.result.p_inverter > 1.2 * held.result.p_inverter
    assert held.result.tj_switch_peak > turning.result.tj_switch_peak + 1
    cycle = Cycle([Step(instant(1500.0, 5.0), turning, None), Step(instant(0.0, 4.0), held, None)])
    assert cycle.worst.sample.motor_rpm == 0.0


def test_means_over_a_motion_leave_out_the_instants_that_could_not_be_solved() -> None:
    profile = Profile(
        segments=[
            Segment(duration=0.02, speed_start=600, speed_end=600),
            Segment(duration=0.03, speed_start=60000, speed_end=60000),
        ]
    )
    cycle = run_cycle(conducting(), DC, Load(constant_torque=5.0), profile, BASE, per_segment=1)
    assert [s.point is None for s in cycle.steps] == [False, True]
    assert cycle.rms_torque == pytest.approx(5.0)
    assert cycle.mean_loss == pytest.approx(at_speed_and_torque(conducting(), DC, 600, 5.0, BASE).result.p_inverter)


# ---------- the load ----------


def test_air_drag_on_a_vehicle_is_half_rho_cd_a_v_squared_with_air_at_1_2_kg_per_m3() -> None:
    radius, drag_area, wheel_speed = 0.1, 0.5, 50.0
    load = Load(vehicle=Vehicle(mass=20.0, wheel_radius=radius, rolling_resistance=0.0, drag_area=drag_area))
    force = 0.5 * 1.2 * drag_area * (wheel_speed * radius) ** 2
    assert load.load_torque(wheel_speed, 0.0) == pytest.approx(force * radius, rel=1e-12)


def test_rolling_resistance_opposes_a_vehicle_driven_backwards() -> None:
    mass, radius, rolling = 20.0, 0.1, 0.02
    load = Load(vehicle=Vehicle(mass=mass, wheel_radius=radius, rolling_resistance=rolling))
    assert load.load_torque(-10.0, 0.0) == pytest.approx(-mass * G * rolling * radius, rel=1e-12)
    assert load.load_torque(10.0, 0.0) == pytest.approx(mass * G * rolling * radius, rel=1e-12)


@pytest.mark.parametrize("acceleration", [2.0, -2.0])
def test_friction_at_standstill_opposes_the_way_the_load_is_being_pushed(acceleration) -> None:
    inertia, friction = 0.1, 0.3
    load = Load(inertia=inertia, friction_coulomb=friction)
    expected = inertia * acceleration + math.copysign(friction, acceleration)
    assert load.load_torque(0.0, acceleration) == pytest.approx(expected, rel=1e-12)


def test_the_instants_of_a_motion_are_timed_from_its_start_across_segments() -> None:
    profile = Profile(
        segments=[
            Segment(duration=1.0, speed_start=0, speed_end=100),
            Segment(duration=2.0, speed_start=100, speed_end=100),
        ]
    )
    assert [s.time for s in sample(Load(), profile, per_segment=2)] == pytest.approx([0.25, 0.75, 1.5, 2.5])


# ---------- what a device can drive ----------


def test_a_limit_set_by_the_motor_current_is_said_to_be_the_motor_s() -> None:
    """Little loss and a motor that stops at 40 A: the search reaches the motor's limit exactly
    on its way up, and nothing below it fails."""
    motor = BrushedDc(type="dc", kt=0.5, r=0.2, i_max=40.0)
    cool = linear_device(sw_curves=[line(25.0, 0.5, 0.005)], d_curves=[line(25.0, 0.5, 0.005)])
    most = motor.kt * motor.i_max
    found = torque_limit(cool, motor, 500.0, replace(BASE, t_sink=40.0), start=most * 1.0001 / 8)
    assert found.torque == pytest.approx(most, rel=1e-3)
    assert found.reason == "motor"
    assert found.tj < cool.ratings.tj_max - 50


def test_a_junction_that_gives_out_below_the_motor_s_limit_is_what_the_limit_is_put_down_to() -> None:
    """The switch that stays on carries the armature current: 1.5 K/W * (1 V + 30 mΩ * I) * I = 90 K."""
    motor = BrushedDc(type="dc", kt=0.5, r=0.2, i_max=40.0)
    hot = linear_device(sw_curves=[line(25.0, 1.0, 0.03)], d_curves=[line(25.0, 1.0, 0.03)], rth_sw=1.5, rth_d=1.5)
    start = 11.0
    with pytest.raises(Unreachable):  # the search's first step up is past what the motor can carry
        at_speed_and_torque(hot, motor, 500.0, 2 * start, BASE)
    found = torque_limit(hot, motor, 500.0, BASE, start=start)
    amps = (-1.0 + math.sqrt(1.0 + 4 * 0.03 * (hot.ratings.tj_max - BASE.t_sink) / 1.5)) / (2 * 0.03)
    assert found.torque == pytest.approx(motor.kt * amps, rel=2e-3)
    assert found.reason == "junction"


# ---------- braking and the DC link ----------


def test_the_stretch_of_braking_lasts_as_long_as_the_flywheel_returns_energy() -> None:
    inertia, ohms, kt, stop = 0.02, 0.5, 0.5, 0.5
    motor = BrushedDc(type="dc", kt=kt, r=ohms)
    profile = Profile(
        segments=[
            Segment(duration=0.5, speed_start=2000, speed_end=2000),
            Segment(duration=stop, speed_start=2000, speed_end=0),
        ]
    )
    lossless = linear_device(sw_curves=[line(25.0, 0.0, 0.0)], d_curves=[line(25.0, 0.0, 0.0)])
    per_segment = 50
    cycle = run_cycle(lossless, motor, Load(inertia=inertia), profile, replace(BASE, t_sink=40.0), per_segment)
    w = 2000 * 2 * math.pi / 60
    amps = inertia * (w / stop) / kt
    # Energy comes back while the back-EMF is above the winding drop; the speed falls in a straight line.
    returning = stop * (1 - (ohms * amps / kt) / w)
    assert dclink.returned(cycle, V_REF, 600.0).burst_time == pytest.approx(returning, abs=stop / per_segment)


def given_back(**figures) -> dclink.Returned:
    figures = {"capacitance_needed": None, "v_peak": None, **figures}
    return dclink.Returned(energy=50.0, burst_energy=50.0, burst_time=0.4, peak_power=1200.0, v_limit=480.0, **figures)


def test_a_battery_is_told_the_charging_current_at_the_link_voltage() -> None:
    (said,) = dclink.check(given_back(), 300.0, 600.0, supply="battery")
    assert said.level is guard.Level.ok
    assert "as up to 4 A of charging current" in said.message  # 1200 W into 300 V


def test_the_capacitance_asked_for_is_written_in_microfarads() -> None:
    (said,) = dclink.check(given_back(capacitance_needed=470e-6), 300.0, 600.0, supply="one-way")
    assert said.level is guard.Level.caution
    assert "needs at least 470 µF on the link to stay under 480 V" in said.message


def test_a_link_lifted_past_the_margin_is_given_as_a_share_of_the_device_rating() -> None:
    (said,) = dclink.check(given_back(v_peak=540.0, capacitance_needed=1e-3), 300.0, 600.0, supply="one-way")
    assert said.level is guard.Level.caution
    assert "to 540 V, 90% of the 600 V device rating" in said.message


# ---------- lifetime ----------


def test_a_once_a_turn_swing_that_does_the_damage_is_said_to_come_within_a_turn() -> None:
    trace = np.array([50.0, 55.0, 50.0, 55.0])  # one slow swing of 5 K
    life = lifetime.estimate(trace, fast=[(40.0, 80.0, 100.0)])
    assert (life.swing, life.swing_mean) == (40.0, 80.0)
    assert life.within_turn
    assert not lifetime.estimate(trace, fast=[(1.5, 52.0, 1.0)]).within_turn  # here the slow swing does it


# ---------- starting ----------


def test_an_open_loop_drive_holds_its_start_current_below_the_handover_speed_in_either_direction() -> None:
    start = Start(method="open_loop", current=8.0, handover_rpm=500.0)
    assert start.floor(-499.0) == 8.0
    assert start.floor(499.0) == 8.0
    assert start.floor(-2000.0) is None
    assert start.floor(2000.0) is None


def test_at_the_handover_speed_itself_normal_control_has_taken_over() -> None:
    start = Start(method="open_loop", current=8.0, handover_rpm=500.0)
    assert start.floor(500.0) is None
    assert start.floor(-500.0) is None


def test_flux_build_up_and_alignment_each_last_their_own_time() -> None:
    motion = [instant(0.0, 1.0, 0.05), instant(100.0, 1.0, 0.05)]
    start = Start(method="open_loop", current=8.0, align_time=0.2, handover_rpm=500.0, flux_time=0.3)
    out = with_start(motion, start)
    assert [s.duration for s in out] == [0.3, 0.2, 0.05, 0.05]
    assert [s.motor_rpm for s in out[:2]] == [0.0, 0.0] and [s.motor_torque for s in out[:2]] == [0.0, 0.0]


@pytest.mark.parametrize("method", ["sensor", "injection"])
def test_a_drive_that_knows_where_the_rotor_is_does_not_align_it(method) -> None:
    motion = [instant(0.0, 1.0, 0.05), instant(100.0, 1.0, 0.05)]
    assert with_start(motion, Start(method=method, current=8.0, align_time=0.2, handover_rpm=500.0)) == motion


# ---------- cooled to air ----------


def test_a_three_phase_stage_in_four_switch_modules_in_still_air_shares_its_loss_between_two_of_them() -> None:
    """Six switches take two packages of four: each warms the air around it with half of what the stage loses."""
    case_to_sink, to_air, ambient = 0.1, 2.1, 40.0
    module = device(topology=Topology.h_bridge, rth_cs=case_to_sink)
    base = replace(BASE, rth_free=to_air, t_sink=ambient)
    cycle, trace = follow(module, PMSM, Load(constant_torque=4.0), steady(1500, 0.1), base, per_segment=2)
    expected = ambient + (to_air - case_to_sink) * cycle.mean_loss / 2
    assert trace.t_sink[-1] == pytest.approx(expected, abs=0.3)
    assert trace.t_sink[-1] - ambient > 10  # far from where all of it, or a third of it, would put it


def test_a_stage_on_a_heatsink_in_air_still_aligns_the_rotor_and_holds_the_start_current() -> None:
    start = Start(method="open_loop", current=12.0, align_time=0.2, handover_rpm=500.0)
    ramp = Profile(segments=[Segment(duration=0.1, speed_start=0, speed_end=1000)])
    in_air = replace(BASE, rth_sink=0.5, t_sink=40.0)
    cycle, _ = follow(device(), PMSM, Load(constant_torque=1.0), ramp, in_air, per_segment=4, start=start)
    assert [s.sample.duration for s in cycle.steps] == pytest.approx([0.2, 0.025, 0.025, 0.025, 0.025])
    assert [s.sample.motor_rpm for s in cycle.steps] == pytest.approx([0.0, 125.0, 375.0, 625.0, 875.0])
    # Above 500 rpm the drive sees the rotor and applies what 1 N·m takes: 1 / (1.5 * 4 * 0.1 Wb) A.
    needed = 1.0 / (1.5 * 4 * 0.1)
    held = [s.point.stage.i_peak for s in cycle.steps]
    assert held == pytest.approx([12.0, 12.0, 12.0, needed, needed], rel=1e-4)


# ---------- what a device can drive: the reason given ----------


def test_loss_that_outruns_the_cooling_stops_the_torque_as_a_junction_limit() -> None:
    """The switch drops 1 V up to 100 °C and far more beyond it. Through 2 K/W over a 60 °C sink it
    reaches 100 °C at 20 A; one amp more and each kelvin adds more loss than the path sheds."""
    motor = BrushedDc(type="dc", kt=0.5, r=0.2)
    drop = [line(25.0, 1.0, 0.0), line(100.0, 1.0, 0.0), line(125.0, 1.0, 2.0)]
    kinked = linear_device(sw_curves=drop, d_curves=[line(25.0, 1.0, 0.03)], rth_sw=2.0, rth_d=2.0)
    amps = (100.0 - BASE.t_sink) / (2.0 * 1.0)
    found = torque_limit(kinked, motor, 500.0, BASE, start=1.0)
    assert found.torque == pytest.approx(motor.kt * amps, rel=2e-3)
    assert found.tj < kinked.ratings.tj_max - 20  # the last point that holds is well inside the rating
    assert found.reason == "junction"


def test_a_speed_the_motor_cannot_reach_at_any_torque_is_put_down_to_the_motor() -> None:
    """At 60 000 rpm a 0.5 V·s motor generates 3100 V, ten times the link: no torque can be held there."""
    motor = BrushedDc(type="dc", kt=0.5, r=0.2)
    assert motor.kt * 60000 * 2 * math.pi / 60 > 10 * V_REF
    found = torque_limit(conducting(), motor, 60000.0, BASE)
    assert (found.torque, found.tj, found.current) == (0.0, None, None)
    assert found.reason == "motor"


# ---------- braking after motoring ----------


def test_energy_drawn_while_speeding_up_is_not_owed_by_the_braking_that_follows() -> None:
    """A flywheel run up and stopped again, by a motor and a stage that lose nothing: the stop
    returns the whole of its 1/2 J w^2, and a link that cannot pass it on is lifted by all of it."""
    inertia, top, each, farads = 0.02, 2000.0, 0.5, 1e-3
    motor = BrushedDc(type="dc", kt=0.5, r=0.0)
    profile = Profile(
        segments=[
            Segment(duration=each, speed_start=0, speed_end=top),
            Segment(duration=each, speed_start=top, speed_end=0),
        ]
    )
    lossless = linear_device(sw_curves=[line(25.0, 0.0, 0.0)], d_curves=[line(25.0, 0.0, 0.0)])
    cycle = run_cycle(lossless, motor, Load(inertia=inertia), profile, replace(BASE, t_sink=40.0), 10)
    spinning = 0.5 * inertia * (top * 2 * math.pi / 60) ** 2
    back = dclink.returned(cycle, V_REF, 600.0, capacitance=farads)
    assert back.energy == pytest.approx(spinning, rel=1e-9)
    assert back.burst_energy == pytest.approx(spinning, rel=1e-9)
    assert back.burst_time == pytest.approx(each)
    assert back.v_peak == pytest.approx(math.sqrt(V_REF**2 + 2 * spinning / farads), rel=1e-9)


# ---------- starting: caught, and injection ----------


def test_a_motor_already_turning_above_the_handover_speed_is_caught_and_not_aligned() -> None:
    start = Start(method="open_loop", current=8.0, align_time=0.2, handover_rpm=500.0)
    turning = [instant(1000.0, 1.0, 0.05), instant(1200.0, 1.0, 0.05)]
    assert with_start(turning, start) == turning
    creeping = [instant(100.0, 1.0, 0.05), instant(1200.0, 1.0, 0.05)]
    assert [s.duration for s in with_start(creeping, start)] == [0.2, 0.05, 0.05]


@pytest.mark.parametrize("method", ["sensor", "injection"])
def test_a_drive_that_knows_where_the_rotor_is_applies_only_what_the_torque_needs(method) -> None:
    start = Start(method=method, current=8.0, handover_rpm=500.0)
    assert start.floor(0.0) is None
    assert start.floor(499.0) is None
