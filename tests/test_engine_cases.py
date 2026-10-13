"""The engine's own figures, each against a closed form, a limit case or the documented behaviour."""

from __future__ import annotations

import math

import numpy as np
import pytest
from conftest import SRC, V_REF, energy, line

from motionsim.device import (
    ChargeModel,
    Chip,
    ConductionModel,
    Curve,
    Device,
    FosterNetwork,
    Package,
    Ratings,
    SwitchingEnergy,
    Topology,
)
from motionsim.engine import OperatingPoint, Pwm, Role, Validity, solve, solve_roles
from motionsim.engine.limits import hottest, max_current
from motionsim.engine.modulation import phase_leg_roles, waveform
from motionsim.engine.mosfet import charge_energies
from motionsim.engine.solver import switching_period

V0_SW, R_SW = 0.9, 0.03
V0_D, R_D = 1.0, 0.025
K_ON, K_OFF, K_RR = 20e-6, 15e-6, 5e-6


def igbt(
    *,
    sw=None,
    d=None,
    e_on=None,
    e_off=None,
    e_rr=None,
    rth_sw: float = 0.8,
    rth_d: float = 1.5,
    tau: bool = True,
    topology: Topology = Topology.discrete,
    spread: float | None = None,
    i_nominal: float = 30,
    **package,
) -> Device:
    """A switch and a diode whose drops are straight lines, measured at 25 °C unless curves are given."""
    return Device(
        vendor="synthetic",
        part_number="LINEAR",
        technology="Si IGBT",
        ratings=Ratings(v_max=600, i_nominal=i_nominal, tj_max=150),
        package=Package(topology=topology, **package),
        switch=Chip(
            kind="igbt",
            conduction=ConductionModel(curves=sw or [line(25.0, V0_SW, R_SW)], source=SRC, spread=spread),
            e_on=e_on or energy(K_ON),
            e_off=e_off or energy(K_OFF),
            thermal=FosterNetwork(r=[rth_sw], tau=[0.01] if tau else None, source=SRC),
        ),
        diode=Chip(
            kind="diode",
            conduction=ConductionModel(curves=d or [line(25.0, V0_D, R_D)], source=SRC),
            e_rr=e_rr or energy(K_RR),
            thermal=FosterNetwork(r=[rth_d], tau=[0.01] if tau else None, source=SRC),
        ),
    )


def fet(*, charge: ChargeModel | None = None, reverse: ConductionModel | None = None) -> Device:
    """A transistor of 20 mohm whose switching loss comes from its charges."""
    chip = Chip(
        kind="mosfet",
        conduction=ConductionModel(curves=[line(25.0, 0.0, 0.02)], source=SRC),
        reverse=reverse,
        charge=charge
        or ChargeModel(q_gs=9e-9, q_gd=2.5e-9, q_g_th=6e-9, v_plateau=2.5, q_oss=80e-9, v_ref=V_REF, source=SRC),
        thermal=FosterNetwork(r=[0.5], tau=[0.01], source=SRC),
    )
    return Device(
        vendor="synthetic",
        part_number="FET",
        technology="Si MOSFET",
        ratings=Ratings(v_max=650, i_nominal=30, tj_max=150),
        package=Package(topology=Topology.discrete, rth_case_sink=0.0),
        switch=chip,
    )


def point(**kw) -> OperatingPoint:
    base = dict(v_dc=V_REF, i_rms=20.0, modulation_index=0.8, power_factor=0.9, f_sw=8000.0, t_sink=25.0)
    return OperatingPoint(**{**base, **kw})


def conduction(v0: float, r: float, i_pk: float, m: float, pf: float, sign: float) -> float:
    return v0 * i_pk * (1 / (2 * math.pi) + sign * m * pf / 8) + r * i_pk**2 * (1 / 8 + sign * m * pf / (3 * math.pi))


def position_loss(i_pk: float, m: float, pf: float, f_sw: float) -> tuple[float, float]:
    """Closed-form loss of one switch and one diode of the straight-line device at its test voltage."""
    p_sw = conduction(V0_SW, R_SW, i_pk, m, pf, +1) + f_sw * (K_ON + K_OFF) * i_pk / math.pi
    p_d = conduction(V0_D, R_D, i_pk, m, pf, -1) + f_sw * K_RR * i_pk / math.pi
    return p_sw, p_d


def test_the_switching_period_shown_is_that_of_one_device_of_those_in_parallel() -> None:
    op = point(power_factor=1.0, parallel=2)
    role = phase_leg_roles(waveform(op.i_rms, op.modulation_index, op.power_factor, op.n_steps), 6, Pwm.sine)[0]
    shown = switching_period(igbt(), role, op, 25.0, 25.0)
    # At unity power factor the switch works hardest at the crest of the current, and carries half of it.
    i = math.sqrt(2) * 20.0 / 2
    assert shown["current"] == pytest.approx(i, rel=1e-4)
    assert shown["duty"] == pytest.approx(0.5 * (1 + 0.8), rel=1e-4)
    assert shown["p_on"] == pytest.approx(i * (V0_SW + R_SW * i), rel=1e-4)
    assert shown["e_on"] == pytest.approx(K_ON * i, rel=1e-4)
    assert shown["e_off"] == pytest.approx(K_OFF * i, rel=1e-4)


def test_each_edge_of_an_igbt_is_scaled_by_its_own_gate_resistor() -> None:
    def against_rg(slope: float, factor: float) -> SwitchingEnergy:
        return SwitchingEnergy(
            curves=[line(25.0, 0.0, slope)], v_ref=V_REF, rg=10, rg_values=[10, 20], rg_factor=[1, factor], source=SRC
        )

    device = igbt(e_on=against_rg(K_ON, 2.0), e_off=against_rg(K_OFF, 3.0), rth_sw=0.001, rth_d=0.001)
    r = solve(device, point(rg_on=20, rg_off=10))
    i_pk = math.sqrt(2) * 20.0
    assert r.switch.turn_on == pytest.approx(2.0 * 8000.0 * K_ON * i_pk / math.pi, rel=1e-3)
    assert r.switch.turn_off == pytest.approx(1.0 * 8000.0 * K_OFF * i_pk / math.pi, rel=1e-3)


def test_a_switch_and_diode_in_a_package_of_their_own_are_not_heated_by_other_chips() -> None:
    op = point(t_sink=60.0)
    r = solve(igbt(rth_case_sink=0.0), op)
    p_sw, p_d = position_loss(math.sqrt(2) * 20.0, 0.8, 0.9, 8000.0)
    assert r.t_case == pytest.approx(60.0)
    assert r.tj_switch == pytest.approx(60.0 + 0.8 * p_sw, abs=0.05)
    assert r.tj_diode == pytest.approx(60.0 + 1.5 * p_d, abs=0.05)
    assert not any("heating between chips" in a for a in r.assumptions)


def test_a_moulded_module_is_heated_as_the_thermal_model_tabulates() -> None:
    # docs/THERMAL_MODEL.md, moulded leadframe module of 15 A: 0.48 K/W between chips measured
    # from the heatsink, of which the interface layer alone is 0.11 K/W.
    between, interface = 0.48, 0.11
    device = igbt(topology=Topology.half_bridge, construction="leadframe", i_nominal=15)
    r = solve(device, point(t_sink=60.0))
    p_sw, p_d = position_loss(math.sqrt(2) * 20.0, 0.8, 0.9, 8000.0)
    package = 2 * (p_sw + p_d)
    assert r.t_case == pytest.approx(60.0 + interface * package, abs=0.15)
    assert r.tj_switch == pytest.approx(60.0 + (0.8 + interface) * p_sw + between * (package - p_sw), abs=0.3)
    assert r.tj_diode == pytest.approx(60.0 + (1.5 + interface) * p_d + between * (package - p_d), abs=0.3)
    assert any(
        "heating between chips computed for a generic moulded leadframe module: 0.37 K/W" in a for a in r.assumptions
    )
    assert any("on grease: 0.11" in a for a in r.assumptions)


def test_above_the_test_voltage_the_note_says_how_much_more_a_power_of_1_4_would_add() -> None:
    r = solve(igbt(rth_sw=0.001, rth_d=0.001), point(v_dc=1.2 * V_REF))
    more = 1.2**1.4 / 1.2 - 1  # what linear scaling leaves out of a rise as the power 1.4
    assert f"{more:.0%}" == "8%"
    said = (
        "turn-on energy: scaled linearly from 300 V test voltage to 360 V; above the test voltage "
        "real devices rise faster, by up to 8% more here"
    )
    assert said in r.notes
    assert said in r.outside


def test_reverse_conduction_data_is_only_held_against_the_point_when_there_is_dead_time() -> None:
    short = ConductionModel(curves=[Curve(tj=25.0, current=[0.0, 10.0], value=[2.0, 2.0])], source=SRC)
    drive = dict(v_drive=10.0, rg_on=5.0, rg_off=3.0)
    without = solve(fet(reverse=short), point(**drive))
    assert without.switch.dead_time == 0.0
    assert not any(n.startswith("reverse conduction") for n in without.notes)
    with_dead_time = solve(fet(reverse=short), point(t_dead=200e-9, **drive))
    assert "reverse conduction: peak current 28.3 A is above the data (10 A)" in with_dead_time.notes


def test_a_junction_colder_than_the_coldest_curve_is_said_to_be_outside_the_data() -> None:
    device = igbt(
        sw=[line(25.0, V0_SW, R_SW), line(125.0, V0_SW, R_SW)],
        d=[line(25.0, V0_D, R_D), line(125.0, V0_D, R_D)],
        rth_sw=0.001,
        rth_d=0.001,
        rth_case_sink=0.0,
    )
    r = solve(device, point(t_sink=-20.0))
    assert "switch conduction: -20 °C is outside the data (25 to 125 °C)" in r.outside
    assert "diode conduction: -20 °C is outside the data (25 to 125 °C)" in r.outside
    assert r.validity is Validity.extrapolated


def test_three_in_parallel_lose_what_the_hardest_worked_one_and_both_others_lose() -> None:
    n, rho, r_on = 3, 1.5, 0.02
    resistive = [line(25.0, 0.0, r_on)]
    device = igbt(sw=resistive, d=resistive, e_on=energy(0.0), e_off=energy(0.0), e_rr=energy(0.0), spread=rho)
    r = solve(device, point(i_rms=30.0, parallel=n))
    # The hardest-worked part is typical among parts at the maximum drop: currents as 1 to 1/rho.
    most = 1 / (1 + (n - 1) / rho)
    rest = (1 - most) / (n - 1)
    # A switch and its diode of the same resistance lose r * Ipk^2 / 4 between them, whatever the duty.
    i_pk = math.sqrt(2) * 30.0
    one_carrying_all = 6 * r_on * i_pk**2 / 4
    assert r.p_inverter == pytest.approx(one_carrying_all * (most**2 + (n - 1) * rest**2), rel=1e-4)
    assert any("carries most, 43% of the current" in note for note in r.notes)


def test_a_diodes_recovery_counts_towards_the_share_that_is_outside_its_data() -> None:
    recovery = SwitchingEnergy(curves=[line(25.0, 0.0, 100e-6)], v_ref=V_REF / 2, source=SRC)
    device = igbt(e_on=energy(0.0), e_off=energy(0.0), e_rr=recovery, rth_sw=0.001, rth_d=0.001, rth_case_sink=0.0)
    r = solve(device, point(f_sw=20000.0))
    # Twice the test voltage: 2^1.4 against 2, so up to 32% more than linear scaling gives.
    assert f"{2**0.4 - 1:.0%}" == "32%"
    assert r.diode.recovery == pytest.approx(2 * 20000.0 * 100e-6 * math.sqrt(2) * 20.0 / math.pi, rel=1e-3)
    assert r.diode.recovery > 0.5 * r.p_inverter / 6
    assert r.outside == [
        "recovery energy: scaled linearly from 150 V test voltage to 300 V; above the test voltage "
        "real devices rise faster, by up to 32% more here"
    ]
    assert r.validity is Validity.extrapolated


def test_overshoot_that_uses_most_of_the_rating_is_warned_of_though_the_dc_voltage_does_not() -> None:
    i_pk = math.sqrt(2) * 20.0
    t_fall = (9e-9 - 6e-9) * 3.0 / 2.5  # gate charge from plateau to threshold through the turn-off resistor
    l_loop = 100.0 * t_fall / i_pk  # 100 V of overshoot
    r = solve(fet(), point(v_dc=450.0, v_drive=10.0, rg_on=5.0, rg_off=3.0, l_loop=l_loop))
    assert 450.0 < 0.8 * 650 < 550.0 < 650
    assert f"{550 / 650:.0%}" == "85%"
    assert r.rating_warnings == ["turn-off overshoot of about 100 V takes the device to 550 V, 85% of its rating"]


def test_output_charge_beyond_its_curve_goes_on_as_the_square_root_of_voltage() -> None:
    table = ChargeModel(
        q_gs=9e-9,
        q_gd=2.5e-9,
        q_g_th=6e-9,
        v_plateau=2.5,
        q_oss=50e-9,
        v_ref=100.0,
        q_oss_scaling="table",
        oss_voltage=[0.0, 100.0],
        oss_charge=[0.0, 50e-9],
        source=SRC,
    )
    op = point(v_dc=400.0, v_drive=10.0, rg_on=5.0, rg_off=3.0)
    e_on, e_off = charge_energies(fet(charge=table).switch, np.zeros(1), op)
    # Four times the last voltage of the curve: twice its charge, lost through the whole DC voltage.
    assert e_on[0] == pytest.approx(2 * 50e-9 * 400.0)
    assert e_off[0] == 0.0
    inside, _ = charge_energies(
        fet(charge=table).switch, np.zeros(1), point(v_dc=50.0, v_drive=10.0, rg_on=5, rg_off=3)
    )
    assert inside[0] == pytest.approx(25e-9 * 50.0)


def test_the_largest_current_is_found_for_the_limit_that_was_asked_for() -> None:
    device = igbt(rth_case_sink=0.0)
    op = point(t_sink=60.0)
    i_max, r = max_current(device, op, tj_limit=100.0, peak=False)
    # The diode's share is small at this power factor: the switch's mean temperature is the one at the limit.
    p_sw, _ = position_loss(math.sqrt(2) * i_max, 0.8, 0.9, 8000.0)
    assert 60.0 + 0.8 * p_sw == pytest.approx(100.0, abs=0.2)
    assert hottest(r, peak=False) == pytest.approx(100.0, abs=0.2)


def test_the_largest_current_keeps_the_junction_at_or_below_the_limit() -> None:
    device = igbt(rth_case_sink=0.0)
    op = point(t_sink=60.0)
    for peak in (True, False):
        i_max, r = max_current(device, op, peak=peak)
        assert 149.5 < hottest(r, peak=peak) <= 150.0
        assert hottest(solve(device, point(t_sink=60.0, i_rms=i_max)), peak=peak) <= 150.0
        assert r.p_out == pytest.approx(3 * 0.8 * V_REF / (2 * math.sqrt(2)) * i_max * 0.9)


def test_the_hottest_mean_temperature_is_the_diodes_when_the_stage_regenerates() -> None:
    r = solve(igbt(rth_case_sink=0.0), point(t_sink=60.0, modulation_index=1.0, power_factor=-1.0))
    _, p_d = position_loss(math.sqrt(2) * 20.0, 1.0, -1.0, 8000.0)
    assert hottest(r, peak=False) == pytest.approx(60.0 + 1.5 * p_d, abs=0.1)
    assert hottest(r, peak=False) > r.tj_switch + 10.0
    assert hottest(r) == r.tj_diode_peak


def test_data_notes_that_are_each_minor_decide_the_verdict_when_together_they_are_not() -> None:
    # docs/LIMITS.md: a table measured at one temperature drifts by up to 0.5% a kelvin, and a
    # caution is raised when what is in doubt could move the stage's loss by 5% or more.
    same = [line(25.0, 1.0, 0.02)]
    device = igbt(
        sw=same, d=same, e_on=energy(0.0), e_off=energy(0.0), e_rr=energy(0.0), rth_sw=1e-4, rth_d=1e-4, rth_case_sink=0
    )
    # At zero power factor the switch and the diode each carry half the loss.
    each_at_15_k = 0.5 * 0.005 * 15
    assert each_at_15_k < 0.05 <= 2 * each_at_15_k
    r = solve(device, point(power_factor=0.0, t_sink=40.0))
    assert r.switch.conduction == pytest.approx(r.diode.conduction, rel=1e-6)
    assert sorted(r.outside) == [
        "diode conduction: only characterised at 25 °C, used at 40 °C",
        "switch conduction: only characterised at 25 °C, used at 40 °C",
    ]
    assert r.validity is Validity.extrapolated
    # 8 K away, 4% of the loss is in doubt: noted, and the verdict stands.
    near = solve(device, point(power_factor=0.0, t_sink=33.0))
    assert near.outside == []
    assert "switch conduction: only characterised at 25 °C, used at 33 °C" in near.notes
    assert near.validity is Validity.interpolated


def test_on_a_shared_board_a_steady_loss_leaves_no_range_across_the_assumed_thermal_response() -> None:
    # Positions that lose a constant power have no temperature swing, so the response assumed for
    # the package cannot move the hottest junction: the range across the assumptions closes on it.
    current, air, rth_free, rth_board = 5.0, 25.0, 20.0, 5.0
    flat = np.ones(8)

    def held_on(name: str, share: float) -> Role:
        return Role(name, 2, current * flat, share * flat, 0 * flat, 0 * flat, 0 * flat)

    device = igbt(tau=False, e_on=energy(0.0), e_off=energy(0.0), e_rr=energy(0.0))
    op = point(t_sink=air, rth_free=rth_free, rth_board=rth_board)
    r = solve_roles(device, [held_on("busy", 0.9), held_on("idle", 0.2)], op, period=0.02, p_out=0.0)
    busy, idle = (share * current * (V0_SW + R_SW * current) for share in (0.9, 0.2))
    everything = 2 * busy + 2 * idle
    case = air + max(rth_free * busy + rth_board * (everything - busy), rth_board * everything)
    assert r.p_inverter == pytest.approx(everything)
    assert r.t_case == pytest.approx(case, abs=0.01)
    assert r.tj_switch_peak == pytest.approx(case + 0.8 * busy, abs=0.01)
    assert r.assumptions
    assert r.tj_peak_range == pytest.approx((r.tj_switch_peak, r.tj_switch_peak), abs=0.02)


@pytest.mark.parametrize("still", [dict(power_factor=0.0), dict(modulation_index=0.0), dict(i_rms=0.0)])
def test_a_stage_that_delivers_no_power_has_no_efficiency_to_report(still) -> None:
    r = solve(igbt(), point(**still))
    assert r.p_out == 0.0
    assert r.efficiency is None


def steady(name: str, current: float, on: float, back: float = 0.0, leg: str | None = None) -> Role:
    """Two positions that carry a constant current, forwards for one share of the time and backwards for another."""
    flat = np.ones(8)
    return Role(name, 2, current * flat, on * flat, back * flat, 0 * flat, 0 * flat, leg=leg)


def test_a_package_of_two_legs_is_heated_by_its_own_leg_and_the_hottest_of_the_others() -> None:
    # Three legs on two-leg modules: one module carries two legs, and the worst arrangement
    # puts the two that lose most together.
    rth_cs, current = 0.5, 10.0
    device = igbt(topology=Topology.h_bridge, rth_case_sink=rth_cs, rth_mutual=0.0, e_on=energy(0.0), e_off=energy(0.0))
    roles = [steady(leg, current, share, leg=leg) for leg, share in (("a", 0.9), ("b", 0.5), ("c", 0.1))]
    r = solve_roles(device, roles, point(t_sink=40.0), period=0.02, p_out=0.0)
    a, b, c = (2 * share * current * (V0_SW + R_SW * current) for share in (0.9, 0.5, 0.1))
    cases = {role.name: role.t_case for role in r.roles}
    assert cases["a"] == pytest.approx(40.0 + rth_cs * (a + b), abs=0.01)
    assert cases["b"] == pytest.approx(40.0 + rth_cs * (b + a), abs=0.01)
    assert cases["c"] == pytest.approx(40.0 + rth_cs * (c + a), abs=0.01)
    assert r.tj_switch == pytest.approx(40.0 + rth_cs * (a + b) + 0.8 * a / 2, abs=0.01)


def test_an_output_turning_at_half_a_hertz_heats_its_case_with_the_mean_loss_not_the_worst_position() -> None:
    rth_cs = 0.5
    r = solve(igbt(rth_case_sink=rth_cs), point(t_sink=40.0, f_out=0.5))
    p_sw, p_d = position_loss(math.sqrt(2) * 20.0, 0.8, 0.9, 8000.0)
    assert r.t_case == pytest.approx(40.0 + rth_cs * (p_sw + p_d), abs=0.05)
    assert r.tj_switch == pytest.approx(40.0 + rth_cs * (p_sw + p_d) + 0.8 * p_sw, abs=0.05)


def test_third_harmonic_injection_is_one_sixth_of_the_fundamental() -> None:
    # One sixth is what flattens the reference to sqrt(3)/2 of its peak, so the linear range
    # ends at 2/sqrt(3) with the duty just reaching the rails.
    m = 2 / math.sqrt(3)
    full = waveform(10.0, m, 1.0, 3600, Pwm.third_harmonic)
    assert full.duty.max() == pytest.approx(1.0, abs=1e-6)
    assert full.duty.min() == pytest.approx(0.0, abs=1e-6)
    assert np.all((full.duty > 0) & (full.duty < 1))
    quarter = np.argmin(np.abs(full.theta - math.pi / 2))
    assert full.duty[quarter] == pytest.approx(0.5 * (1 + m * (1 - 1 / 6)), abs=1e-5)


def test_third_harmonic_injection_moves_conduction_loss_from_switch_to_diode_by_its_closed_form() -> None:
    # Over the half period the switch conducts, sin(3x) weighs nothing against sin(x) and
    # -4/15 against sin(x)^2: the injection of m/6 takes r * Ipk^2 * m / (90 pi) from the switch.
    m, i_pk = 0.8, math.sqrt(2) * 20.0
    r = solve(igbt(rth_sw=0.001, rth_d=0.001), point(power_factor=1.0, pwm=Pwm.third_harmonic))
    moved = i_pk**2 * (m / 6) * (4 / 15) / (4 * math.pi)
    assert moved == pytest.approx(i_pk**2 * m / (90 * math.pi))
    assert r.switch.conduction == pytest.approx(conduction(V0_SW, R_SW, i_pk, m, 1.0, +1) - R_SW * moved, rel=2e-5)
    assert r.diode.conduction == pytest.approx(conduction(V0_D, R_D, i_pk, m, 1.0, -1) + R_D * moved, rel=2e-5)


def test_each_edge_of_a_transistor_with_measured_energy_is_scaled_by_its_own_gate_resistor() -> None:
    def against_rg(slope: float, factor: float) -> SwitchingEnergy:
        return SwitchingEnergy(
            curves=[line(25.0, 0.0, slope)], v_ref=V_REF, rg=10, rg_values=[10, 20], rg_factor=[1, factor], source=SRC
        )

    chip = Chip(
        kind="mosfet",
        conduction=ConductionModel(curves=[line(25.0, 0.0, 0.02)], source=SRC),
        e_on=against_rg(K_ON, 2.0),
        e_off=against_rg(K_OFF, 3.0),
        thermal=FosterNetwork(r=[0.001], tau=[0.01], source=SRC),
    )
    device = fet().model_copy(update={"switch": chip})
    i_pk = math.sqrt(2) * 20.0
    r = solve(device, point(rg_on=20, rg_off=10))
    assert r.switch.turn_on == pytest.approx(2.0 * 8000.0 * K_ON * i_pk / math.pi, rel=1e-3)
    assert r.switch.turn_off == pytest.approx(1.0 * 8000.0 * K_OFF * i_pk / math.pi, rel=1e-3)
    r = solve(device, point(rg_on=10, rg_off=20))
    assert r.switch.turn_on == pytest.approx(1.0 * 8000.0 * K_ON * i_pk / math.pi, rel=1e-3)
    assert r.switch.turn_off == pytest.approx(3.0 * 8000.0 * K_OFF * i_pk / math.pi, rel=1e-3)


def test_the_stage_is_described_by_the_role_with_the_hottest_junction_be_it_a_diode() -> None:
    current = 10.0
    device = igbt(rth_case_sink=0.0, e_on=energy(0.0), e_off=energy(0.0), e_rr=energy(0.0))
    roles = [steady("drives", current, 0.6), steady("freewheels", current, 0.0, back=0.9)]
    r = solve_roles(device, roles, point(t_sink=40.0), period=0.02, p_out=0.0)
    switch_hot = 40.0 + 0.8 * 0.6 * current * (V0_SW + R_SW * current)
    diode_hot = 40.0 + 1.5 * 0.9 * current * (V0_D + R_D * current)
    assert diode_hot > switch_hot
    assert r.tj_diode_peak == pytest.approx(diode_hot, abs=0.01)
    assert r.tj_switch_peak == pytest.approx(40.0, abs=0.01)
    assert r.diode.conduction == pytest.approx(0.9 * current * (V0_D + R_D * current))


def test_a_current_at_which_the_junction_runs_away_is_above_the_largest_current() -> None:
    # A resistance that rises by 2% a kelvin: Tj = Ts + g * (1 + a * (Tj - 25)) with g = rth * k * R0 * I^2,
    # which settles at dT = g / (1 - g * a) from a 25 °C sink and has no answer once g * a reaches 1.
    r0, a, rth, m, pf = 0.02, 0.02, 1.0, 0.8, 0.9
    rising = [line(25.0, 0.0, r0), line(125.0, 0.0, r0 * (1 + 100 * a))]
    nothing = [line(25.0, 0.0, 0.0)]
    device = igbt(
        sw=rising, d=nothing, e_on=energy(0.0), e_off=energy(0.0), e_rr=energy(0.0), rth_sw=rth, rth_case_sink=0.0
    ).model_copy(update={"ratings": Ratings(v_max=600, i_nominal=100, tj_max=150)})
    k = 2 * (1 / 8 + m * pf / (3 * math.pi))  # mean of duty times current squared, over the rms current squared
    assert rth * k * r0 * 100.0**2 * a > 1  # the rated current itself runs away
    g = 125.0 / (1 + a * 125.0)
    i_max, r = max_current(device, point(t_sink=25.0), peak=False)
    assert i_max == pytest.approx(math.sqrt(g / (rth * k * r0)), rel=3e-3)
    assert r.tj_switch == pytest.approx(150.0, abs=0.5)
