"""Recommendations against the hand calculations they stand for."""

from __future__ import annotations

from math import log

import pytest
from conftest import line, linear_device
from test_mosfet import fet
from test_mosfet import op as fet_op

from motionsim import recommend
from motionsim.device import Source
from motionsim.device.schema import SwitchingTimes
from motionsim.engine import OperatingPoint, solve


def igbt():
    return linear_device(
        sw_curves=[line(25.0, 0.9, 0.03)], d_curves=[line(25.0, 1.0, 0.025)],
        k_on=20e-6, k_off=15e-6, k_rr=5e-6,
    )


def test_dead_time_from_gate_charge_is_the_three_intervals_of_turn_off() -> None:
    device, op = fet(), fet_op(i_rms=0.0)
    c = device.switch.charge
    c_iss = c.q_gs / c.v_plateau
    v_th = c.v_plateau * c.q_g_th / c.q_gs
    expected = (
        op.rg_off * c_iss * log(op.v_drive / c.v_plateau)
        + c.q_gd * op.rg_off / c.v_plateau
        + op.rg_off * c_iss * log(c.v_plateau / v_th)
    )
    r = recommend.dead_time(device, op, driver_mismatch=20e-9)
    assert r.value["t_dead"] == pytest.approx(1.5 * expected + 20e-9)


def test_dead_time_for_an_igbt_uses_tabulated_times_with_a_larger_margin() -> None:
    device = igbt()
    op = OperatingPoint(v_dc=300, i_rms=0, modulation_index=0, power_factor=1, f_sw=8000, t_sink=60)
    assert recommend.dead_time(device, op).value == {}  # nothing to work from
    device.timing = SwitchingTimes(t_d_off=150e-9, t_f=50e-9, source=Source(kind="synthetic"))
    r = recommend.dead_time(device, op)
    assert r.value["t_dead"] == pytest.approx(2.0 * 200e-9)
    assert any("tail" in text for text in r.lines)


def test_a_dead_time_shorter_than_needed_is_called_out() -> None:
    device = fet()
    short = fet_op(i_rms=0.0, t_dead=1e-9)
    assert any("shorter than this" in text for text in recommend.dead_time(device, short).lines)


def test_packages_with_their_own_drivers_are_left_to_their_datasheet() -> None:
    device = fet()
    device.package.integrated_driver = True
    assert recommend.dead_time(device, fet_op(i_rms=0.0)).value == {}
    assert recommend.gate_resistors(device, fet_op(i_rms=0.0), 10.0).value == {}


def test_gate_resistors_meet_each_limit_exactly() -> None:
    device = fet()
    c = device.switch.charge
    op = fet_op(i_rms=0.0, l_loop=10e-9)
    i_peak, dvdt = 20.0, 5e9
    r = recommend.gate_resistors(device, op, i_peak, dvdt_max=dvdt)
    # Turn-on: voltage swings v_dc while the gate current moves the gate-drain charge.
    slew_on = op.v_dc * (op.v_drive - c.v_plateau) / (c.q_gd * dvdt)
    slew_off = op.v_dc * c.v_plateau / (c.q_gd * dvdt)
    room = 0.8 * device.ratings.v_max - op.v_dc
    overshoot = op.l_loop * i_peak * c.v_plateau / ((c.q_gs - c.q_g_th) * room)
    assert r.value["rg_on"] == pytest.approx(slew_on, rel=0.1) and r.value["rg_on"] >= slew_on
    assert r.value["rg_off"] >= max(slew_off, overshoot)
    assert r.value["rg_off"] == pytest.approx(max(slew_off, overshoot), rel=0.1)
    # A weak driver takes over as the limit.
    weak = recommend.gate_resistors(device, op, i_peak, dvdt_max=dvdt, driver_peak=0.05)
    assert weak.value["rg_on"] == pytest.approx(op.v_drive / 0.05, rel=0.1)
    assert any("gate driver's 0.05 A peak" in text for text in weak.lines)


def test_gate_resistors_say_what_is_missing() -> None:
    assert "gate-charge data" in recommend.gate_resistors(igbt(), fet_op(i_rms=0.0), 10.0).lines[0]
    no_loop = recommend.gate_resistors(fet(), fet_op(i_rms=0.0), 10.0)
    assert any("--lloop" in text for text in no_loop.lines)


def test_heatsink_is_the_temperature_room_over_the_loss() -> None:
    """Losses that do not depend on temperature: junction = sink + a fixed rise."""
    device = igbt()
    conditions = dict(v_dc=300.0, i_rms=12.0, modulation_index=0.9, power_factor=0.85, f_sw=8000.0)

    def evaluate(t_sink: float) -> tuple[float, float]:
        r = solve(device, OperatingPoint(**conditions, t_sink=t_sink))
        return max(r.tj_switch_peak, r.tj_diode_peak), r.p_inverter

    rise, loss = evaluate(0.0)
    r = recommend.heatsink(device, 40.0, evaluate, margin=25.0)
    limit = device.ratings.tj_max - 25.0
    assert r.value["t_sink"] == pytest.approx(limit - rise, abs=0.2)
    assert r.value["rth_sink"] == pytest.approx((limit - rise - 40.0) / loss, rel=0.01)


def test_no_heatsink_is_enough_when_the_junction_is_too_hot_at_ambient() -> None:
    device = igbt()
    r = recommend.heatsink(device, 40.0, lambda t: (t + 200.0, 50.0))
    assert r.value == {} and "no heatsink is enough" in r.lines[0]


def test_an_open_gate_drive_is_filled_with_the_smallest_resistors_the_limits_allow() -> None:
    from dataclasses import replace

    from motionsim.recommend import USUAL_LOOP, choose_gate_drive, gate_resistors

    device = fet()
    op = replace(fet_op(), v_drive=None, rg_on=None, rg_off=None, l_loop=None)
    chosen = choose_gate_drive(device, op, 20.0)
    assert chosen.kind == "chosen" and chosen.v_drive > device.switch.charge.v_plateau
    assert chosen.v_drive == recommend.USUAL_DRIVE[device.technology]
    limits = gate_resistors(device, replace(op, v_drive=chosen.v_drive, l_loop=USUAL_LOOP), 20.0)
    assert (chosen.rg_on, chosen.rg_off) == (limits.value["rg_on"], limits.value["rg_off"])
    assert chosen.op.rg_on == chosen.rg_on and chosen.op.l_loop is None  # the assumed loop stays out of the conditions
    # What the user gave is kept.
    mine = choose_gate_drive(device, replace(op, v_drive=12.0, rg_on=47.0, rg_off=33.0), 20.0)
    assert mine.kind == "given" and (mine.op.rg_on, mine.op.rg_off) == (47.0, 33.0)
    half = choose_gate_drive(device, replace(op, rg_on=47.0), 20.0)
    assert half.op.rg_on == 47.0 and half.op.rg_off == limits.value["rg_off"]


def test_a_device_with_measured_energy_points_to_the_datasheets_resistor() -> None:
    from motionsim.recommend import choose_gate_drive

    device = linear_device(sw_curves=[line(25.0, 1.0, 0.02)], d_curves=[line(25.0, 1.0, 0.02)], k_on=1e-5, k_off=1e-5, k_rr=1e-6)
    op = OperatingPoint(v_dc=300.0, i_rms=10.0, modulation_index=0.8, power_factor=0.9, f_sw=8000.0, t_sink=60.0)
    kept = choose_gate_drive(device, op, 15.0)
    assert kept.kind == "datasheet" and kept.op is op and "measured switching energy" in kept.lines[0]
