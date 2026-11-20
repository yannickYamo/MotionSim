"""Parts of the engine held to hand values: the sums a result is made of, the modulation's
zero sequence and phase, curves read outside their data, assumed package values, and
searches that end."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from conftest import V_REF, line, linear_device

from motionsim.device import Curve, FosterNetwork, Source
from motionsim.engine import OperatingPoint, assumed, limits, lookup, solve
from motionsim.engine.compare import Row
from motionsim.engine.modulation import Pwm, waveform
from motionsim.engine.point import DiodeLoss, SwitchLoss
from motionsim.engine.thermal import periodic_rise, repeating_rise
from motionsim.motor import Bldc
from motionsim.motor.stage import Unreachable
from motionsim.package import templates

SRC = Source(kind="synthetic")


def igbt():
    return linear_device(
        sw_curves=[line(25.0, 0.9, 0.03)], d_curves=[line(25.0, 1.0, 0.025)], k_on=20e-6, k_off=15e-6, k_rr=5e-6
    )


def point(**changes) -> OperatingPoint:
    base = dict(v_dc=V_REF, i_rms=10.0, modulation_index=0.8, power_factor=0.85, f_sw=8000.0, t_sink=60.0)
    return OperatingPoint(**{**base, **changes})


# ---------- what a result adds up ----------


def test_a_chip_is_heated_by_every_term_of_its_loss() -> None:
    assert SwitchLoss(1.0, 2.0, 4.0, dead_time=8.0, recovery=16.0).total == 31.0
    assert DiodeLoss(3.0, 5.0).total == 8.0


def test_efficiency_is_output_over_output_and_loss() -> None:
    result = replace(solve(igbt(), point()), p_out=900.0, p_inverter=100.0)
    assert result.efficiency == pytest.approx(0.9)
    assert replace(result, p_out=0.0).efficiency is None


# ---------- modulation ----------


def test_space_vector_centres_the_three_references() -> None:
    """At the peak of phase A the three stand at m, -m/2, -m/2: the shift that centres them
    is -m/4, and the reference is 3m/4. Where A and B are equal and opposite and C is at
    zero, nothing is shifted."""
    m = 1.15
    at_peak = waveform(1.0, m, 1.0, 2, Pwm.space_vector)  # samples at 90 and 270 degrees
    assert at_peak.duty == pytest.approx([0.5 * (1 + 0.75 * m), 0.5 * (1 - 0.75 * m)])
    at_sixty = waveform(1.0, m, 1.0, 3, Pwm.space_vector)  # 60, 180, 300 degrees
    assert at_sixty.duty == pytest.approx([0.5 * (1 + m * np.sin(np.pi / 3)), 0.5, 0.5 * (1 - m * np.sin(np.pi / 3))])


def test_space_vector_stays_inside_the_period_up_to_its_limit() -> None:
    """Up to 2/sqrt(3) the centred reference never asks for more than the whole period, and
    its highest duty is that of the line-to-line peak: half of 1 + m·cos(30°)."""
    m = 1.15
    w = waveform(1.0, m, 1.0, 720, Pwm.space_vector)
    unclipped = 0.5 * (1 + m * np.cos(np.pi / 6))
    assert w.duty.min() > 0.0 and w.duty.max() < 1.0
    assert w.duty.max() == pytest.approx(unclipped, abs=1e-4)
    assert w.duty.min() == pytest.approx(1 - unclipped, abs=1e-4)


def test_a_lagging_power_factor_puts_the_current_behind_the_voltage() -> None:
    """Power factor 0.5 is 60 degrees. At 30 degrees of the voltage the current is still
    negative, at half its peak; it crosses zero at 60 and peaks at 150."""
    w = waveform(10.0, 0.8, 0.5, 6)  # samples at 30, 90, 150, ... degrees
    peak = np.sqrt(2) * 10.0
    assert w.current[0] == pytest.approx(-0.5 * peak)
    assert w.current[1] == pytest.approx(0.5 * peak)
    assert w.current[2] == pytest.approx(peak)
    assert w.duty[1] == pytest.approx(0.9)  # the voltage peaks at 90 degrees, ahead of the current


# ---------- a block-commutated motor ----------


def test_a_block_commutated_motor_turns_through_its_pole_pairs_electrically() -> None:
    motor = Bldc(type="bldc", pole_pairs=4, kt=0.1, r=0.1)
    stage = motor.stage(600.0, 1.0, 48.0, Pwm.sine)
    assert stage.period == pytest.approx(1 / 40.0)  # 600 rpm is 10 turns a second, 40 electrical
    assert not stage.stalled


def test_a_voltage_out_of_reach_is_set_against_the_link_when_the_stage_takes_none_of_it() -> None:
    motor = Bldc(type="bldc", pole_pairs=4, kt=0.1, r=0.1)
    with pytest.raises(Unreachable, match=r"more than the DC link$"):
        motor.stage(6000.0, 1.0, 48.0, Pwm.sine)


# ---------- curves read below, inside and above their data ----------

FIVE = Curve(tj=25.0, current=[10.0, 20.0, 40.0, 60.0, 100.0], value=[1.0, 1.4, 2.0, 2.4, 3.0])


def test_a_curve_is_read_between_its_points_and_drawn_on_from_its_end_segments() -> None:
    at = np.array([5.0, 10.0, 30.0, 50.0, 100.0, 120.0])
    # Below: the first segment's 0.04 V/A carried down. Above: the last one's 0.015 V/A carried up.
    expected = [1.0 - 0.04 * 5.0, 1.0, 1.7, 2.2, 3.0, 3.0 + 0.015 * 20.0]
    assert lookup.evaluate([FIVE], at, 25.0) == pytest.approx(expected)


def test_between_two_temperatures_and_beyond_them_the_value_follows_a_straight_line() -> None:
    hot = Curve(tj=125.0, current=FIVE.current, value=[2 * v for v in FIVE.value])
    at = np.array([30.0])
    assert lookup.evaluate([FIVE, hot], at, 75.0) == pytest.approx([1.5 * 1.7])
    assert lookup.evaluate([FIVE, hot], at, 175.0) == pytest.approx([2.5 * 1.7])
    assert lookup.evaluate([FIVE, hot], at, -25.0) == pytest.approx([0.5 * 1.7])


def test_the_data_of_a_family_reaches_as_far_as_its_shortest_curve() -> None:
    short = Curve(tj=125.0, current=[0.0, 20.0, 50.0], value=[0.0, 1.5, 2.5])  # the origin is an anchor
    assert lookup.current_range([FIVE, short]) == (20.0, 50.0)
    assert lookup.current_range([FIVE]) == (10.0, 100.0)
    assert lookup.temperature_range([FIVE, short]) == (25.0, 125.0)


# ---------- values assumed for a package ----------


def test_a_named_construction_gets_its_own_template() -> None:
    """A ceramic substrate takes the heat down before it reaches the neighbours: its chips
    heat each other far less than those on a leadframe, and a module said to be one is not
    given the other's figure."""
    substrate = assumed.module_coupling("substrate", 15.0, "typical")
    leadframe = assumed.module_coupling("leadframe", 15.0, "typical")
    assert substrate == templates.summary("substrate-module", 15.0, "typical", "grease").coupling
    assert leadframe == templates.summary("leadframe-module", 15.0, "typical", "grease").coupling
    assert substrate < 0.1 * leadframe
    assert assumed.module_interface("substrate", 15.0, "typical") < assumed.module_interface(
        "leadframe", 15.0, "typical"
    )


def test_a_half_bridge_is_a_module_and_a_single_switch_is_its_outline() -> None:
    assert assumed.template_for("substrate", None, 2) == ("substrate-module", False)
    assert assumed.template_for("unknown", None, 2) == ("leadframe-module", True)
    assert assumed.template_for("unknown", "TO-220", 1) == ("TO-220", False)
    assert assumed.template_for("unknown", None, 1) == ("TO-247", True)


# ---------- thermal networks ----------


def test_a_network_with_no_time_constants_has_no_swing_to_give() -> None:
    assert periodic_rise(FosterNetwork(r=[1.0], source=SRC), np.ones(8), 0.02) is None


def test_a_stage_with_no_time_constant_follows_the_power_at_once() -> None:
    power = np.array([0.0, 10.0, 4.0, 0.0])
    assert repeating_rise([0.5], [0.0], power, 0.01) == pytest.approx(0.5 * power)


# ---------- comparisons ----------


def test_a_device_with_no_stable_temperature_has_no_margin() -> None:
    assert Row(igbt(), None).margin is None


# ---------- searches for a current ----------


def test_the_largest_current_is_found_in_a_few_dozen_solves(monkeypatch) -> None:
    """Doubling up from the rated current, then halving the bracket to a thousandth: the
    search ends, and the junction then stands at its limit."""
    calls = []
    real = limits.solve

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(limits, "solve", counted)
    current, result = limits.max_current(igbt(), point())
    assert len(calls) < 40
    assert limits.hottest(result) == pytest.approx(150.0, abs=0.5)
    assert limits.hottest(solve(igbt(), point(i_rms=1.01 * current))) > 150.0


def test_the_current_the_data_covers_is_where_the_peak_meets_the_last_point() -> None:
    """Curves that end at 200 A cover a sine of 200/sqrt(2) A rms and no more."""
    part = linear_device(
        sw_curves=[line(25.0, 0.9, 0.003)], d_curves=[line(25.0, 1.0, 0.0025)], rth_sw=0.05, rth_d=0.05
    )
    covered = limits.supported_current(part, point(), 180.0)
    assert covered == pytest.approx(200.0 / np.sqrt(2), abs=0.2)
    assert limits.supported_current(part, point(), 100.0) is None


def test_a_search_that_cannot_close_stops_and_says_so(monkeypatch) -> None:
    """A junction that reads above the limit at one call and below it at the next gives the
    halving nothing to close on. It is given up, not followed for ever."""
    monkeypatch.setattr(limits, "_hottest", lambda device, op, i_rms, peak, bound=False: 1e9 if i_rms > 0 else 0.0)
    with pytest.raises(RuntimeError, match="did not close"):
        limits.max_current(igbt(), point(), tolerance=0.0)
