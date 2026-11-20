"""Peaks, worst cases and balances: what a result reports as the highest, the shortest-lived
or the sum has to be that, whatever the figures behind it are."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from conftest import V_REF, line, linear_device

from motionsim import dclink, lifetime
from motionsim.cycle import Cycle, Step
from motionsim.device import FosterNetwork, Source
from motionsim.drivers import at_speed_and_torque
from motionsim.engine import OperatingPoint
from motionsim.engine.limits import hottest
from motionsim.load import Load, Profile, Sample, Segment
from motionsim.motor import BrushedDc, Pmsm
from motionsim.starting import Start, with_start
from motionsim.transient import Trace, follow

SRC = Source(kind="synthetic")
BASE = OperatingPoint(v_dc=V_REF, i_rms=0.0, modulation_index=0.0, power_factor=1.0, f_sw=8000.0, t_sink=60.0)
PMSM = Pmsm(pole_pairs=4, flux_linkage=0.1, l=0.008, rs=1.0)
DC = BrushedDc(type="dc", kt=0.5, r=1.0)


def device(rth_d: float = 1.0):
    """Losses that do not move with temperature. rth_d sets how much hotter the diode runs."""
    d = linear_device(
        sw_curves=[line(25.0, 0.9, 0.03)],
        d_curves=[line(25.0, 1.0, 0.025)],
        k_on=20e-6,
        k_off=15e-6,
        k_rr=5e-6,
        rth_d=rth_d,
    )
    d.switch.thermal = FosterNetwork(r=[0.3, 0.7], tau=[0.002, 0.05], source=SRC)
    d.diode.thermal = FosterNetwork(r=[0.3 * rth_d, 0.7 * rth_d], tau=[0.002, 0.05], source=SRC)
    return d


def instant(time: float, duration: float, rpm: float, torque: float) -> Sample:
    return Sample(time, duration, 0.0, 0.0, 0.0, rpm, torque)


# ---------- the peak of a trace ----------


def test_the_peak_of_a_trace_is_its_largest_sample_and_where_it_is() -> None:
    tj = np.array([60.0, 95.0, 70.0, 62.0])
    trace = Trace(np.arange(4.0), tj, np.full(4, 60.0), tj)
    assert trace.peak == 95.0
    assert trace.peak_index == 1


def test_a_pulsed_motion_reports_the_top_of_the_pulse_not_its_average() -> None:
    """Torque while it accelerates, none while it coasts: the junction is hottest at the end
    of the push, and that is the peak, well above the mean over the motion."""
    profile = Profile(
        segments=[
            Segment(duration=0.02, speed_start=0, speed_end=600),
            Segment(duration=0.2, speed_start=600, speed_end=600),
        ]
    )
    _, trace = follow(device(), DC, Load(inertia=0.01), profile, BASE)
    assert trace.peak == max(trace.tj)
    assert trace.peak > trace.tj.mean() + 1.0
    assert trace.time[trace.peak_index] <= 0.02 + 1e-9  # reached while it pushes
    assert trace.tj[-1] < trace.peak - 1.0  # and cooled from since


@pytest.mark.parametrize("rth_d", [1.0, 3.0])
@pytest.mark.parametrize("torque", [4.0, -4.0])
def test_held_still_after_an_instant_it_could_not_solve_the_rotor_stands_where_it_heats_most(
    rth_d: float, torque: float
) -> None:
    """Nothing says where a stopped rotor stands, so the place that leaves a junction hottest
    is the one followed: held long enough, the trace ends at the steady standstill figure.
    The first instant asks for a speed the voltage cannot give, and stays at the heatsink's
    temperature wherever the rotor is taken to stand."""
    part = device(rth_d)
    samples = [instant(0.0, 0.01, 1e6, torque)] + [instant(0.01 + 0.05 * k, 0.05, 0.0, torque) for k in range(20)]
    cycle, trace = follow(part, PMSM, None, None, BASE, samples=samples)
    assert cycle.steps[0].point is None
    assert trace.tj[0] == BASE.t_sink
    held = hottest(at_speed_and_torque(part, PMSM, 0.0, torque, BASE).result)
    assert trace.peak == pytest.approx(held, abs=0.05)


def test_held_still_after_a_rest_the_rotor_stands_where_it_heats_most() -> None:
    part = device()
    samples = [instant(0.0, 0.01, 0.0, 0.0)] + [instant(0.01 + 0.05 * k, 0.05, 0.0, 4.0) for k in range(20)]
    _, trace = follow(part, PMSM, None, None, BASE, samples=samples)
    held = hottest(at_speed_and_torque(part, PMSM, 0.0, 4.0, BASE).result)
    assert trace.peak == pytest.approx(held, abs=0.05)


# ---------- the shortest life ----------


def survives(swing: float, mean_c: float) -> float:
    """The fit to the power-cycling tests on bond-wire modules, written out."""
    return 302500.0 * swing**-5.039 * np.exp(9.89e-20 / (1.380649e-23 * (mean_c + 273.15)))


def test_the_life_of_a_stage_is_that_of_the_chip_that_wears_out_first() -> None:
    chips = {"switch": np.array([100.0, 140.0]), "diode": np.array([100.0, 160.0])}
    life = lifetime.worst_of(chips, {})
    assert life.chip == "diode"
    assert life.repeats == pytest.approx(survives(60.0, 130.0), rel=1e-9)
    assert life.repeats < survives(40.0, 120.0)
    assert life.swing == 60.0 and life.swing_mean == 130.0


def test_a_trace_with_nothing_in_it_has_no_swings() -> None:
    assert lifetime.rainflow(np.array([])) == []
    assert lifetime.rainflow(np.array([80.0])) == []


def test_a_fast_swing_that_never_happens_does_no_damage() -> None:
    life = lifetime.estimate(np.full(8, 90.0), fast=[(30.0, 90.0, 0.0)])
    assert life.repeats == float("inf")
    assert life.swings == 0
    assert life.swing_share == 0.0  # no swing has a share of no damage


# ---------- energy and power through a motion ----------


def made_up_step(duration: float, p_inverter: float, p_electrical: float, p_shaft: float, p_motor_loss: float) -> Step:
    point = SimpleNamespace(
        result=SimpleNamespace(p_inverter=p_inverter),
        stage=SimpleNamespace(p_electrical=p_electrical, p_shaft=p_shaft, p_motor_loss=p_motor_loss),
    )
    return Step(SimpleNamespace(duration=duration), point, None)


def test_the_energy_lost_counts_the_motor_and_the_link_feeds_the_stage_loss_too() -> None:
    cycle = Cycle([made_up_step(2.0, 10.0, 110.0, 100.0, 10.0), made_up_step(1.0, 4.0, -46.0, -50.0, 4.0)])
    assert cycle.loss_energy == pytest.approx(2.0 * (10.0 + 10.0) + 1.0 * (4.0 + 4.0))
    assert cycle.shaft_energy == pytest.approx(2.0 * 100.0 - 1.0 * 50.0)
    # Motoring, the link gives what the motor takes and what the stage loses. Braking, the
    # stage's loss comes off what the motor returns.
    assert cycle.dc_power == pytest.approx([120.0, -42.0])


def test_what_the_link_gives_is_the_shaft_work_and_every_loss() -> None:
    """A brushed motor at steady speed: V·I = torque·speed + R·I², and the stage's loss on top."""
    torque, rpm = 5.0, 600.0
    profile = Profile(segments=[Segment(duration=0.5, speed_start=rpm, speed_end=rpm)])
    cycle = follow(device(), DC, Load(constant_torque=torque), profile, BASE, per_segment=2)[0]
    shaft = torque * rpm * 2 * np.pi / 60
    copper = DC.r * (torque / DC.kt) ** 2
    stage = cycle.mean_loss
    assert stage > 0
    assert cycle.shaft_energy == pytest.approx(0.5 * shaft, rel=1e-9)
    assert cycle.loss_energy == pytest.approx(0.5 * (copper + stage), rel=1e-9)
    assert cycle.dc_power == pytest.approx([shaft + copper + stage] * 2, rel=1e-9)
    drawn = sum(p * s.sample.duration for p, s in zip(cycle.dc_power, cycle.solved, strict=True))
    assert drawn == pytest.approx(cycle.shaft_energy + cycle.loss_energy, rel=1e-9)


# ---------- braking into the link ----------


def test_the_longest_stretch_of_braking_ends_when_the_energy_stops_coming() -> None:
    """A second of braking at 100 W, then a second with nothing either way: 100 J came back
    in one second. The idle second holds the energy and adds none."""
    cycle = Cycle([made_up_step(1.0, 0.0, -100.0, -100.0, 0.0), made_up_step(1.0, 0.0, 0.0, 0.0, 0.0)])
    back = dclink.returned(cycle, 48.0, 100.0, capacitance=1e-3)
    assert back.energy == pytest.approx(100.0)
    assert back.burst_energy == pytest.approx(100.0)
    assert back.burst_time == pytest.approx(1.0)
    assert back.v_peak == pytest.approx(np.sqrt(48.0**2 + 2 * 100.0 / 1e-3))


def test_half_a_joule_returned_is_still_said() -> None:
    cycle = Cycle([made_up_step(0.5, 0.0, -1.0, -1.0, 0.0)])
    back = dclink.returned(cycle, 48.0, 100.0)
    assert back.energy == pytest.approx(0.5)
    assert dclink.check(back, 48.0, 100.0, supply="battery")


# ---------- starting ----------


def test_an_open_loop_start_with_no_current_given_holds_none() -> None:
    assert Start(method="open_loop", handover_rpm=100.0).floor(50.0) is None
    assert Start(method="open_loop", handover_rpm=100.0, current=8.0).floor(50.0) == 8.0


def test_a_motor_turning_at_the_handover_speed_is_caught_not_aligned() -> None:
    start = Start(method="open_loop", current=8.0, align_time=0.2, handover_rpm=300.0)
    turning = [instant(0.0, 0.1, 300.0, 1.0)]
    assert with_start(turning, start) == turning
    slower = [instant(0.0, 0.1, 299.0, 1.0)]
    aligned = with_start(slower, start)
    assert len(aligned) == 2 and aligned[0].duration == 0.2 and aligned[0].motor_rpm == 0.0
