"""The engine's own figures, each against a closed form, a limit case or the documented behaviour."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest
from conftest import SRC, V_REF, energy, line

from motionsim.device import (
    Basis,
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
from motionsim.engine.point import ThermalRunaway
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
    # docs/THERMAL_MODEL.md, moulded leadframe module of 15 A: 0.36 K/W between chips over the
    # package's own face, and 0.36 K/W for the layer between that face and the heatsink.
    between, interface = 0.364, 0.357
    device = igbt(topology=Topology.half_bridge, construction="leadframe", i_nominal=15)
    r = solve(device, point(t_sink=60.0))
    p_sw, p_d = position_loss(math.sqrt(2) * 20.0, 0.8, 0.9, 8000.0)
    package = 2 * (p_sw + p_d)
    assert r.t_case == pytest.approx(60.0 + interface * package, abs=0.15)
    assert r.tj_switch == pytest.approx(r.t_case + 0.8 * p_sw + between * (package - p_sw), abs=0.3)
    assert r.tj_diode == pytest.approx(r.t_case + 1.5 * p_d + between * (package - p_d), abs=0.3)
    assert any(
        "heating between chips computed for a generic moulded leadframe module: 0.36 K/W" in a for a in r.assumptions
    )
    assert any("on grease: 0.36" in a for a in r.assumptions)


def test_how_a_module_is_mounted_moves_its_case_and_not_what_its_chips_do_to_each_other() -> None:
    """The layer under a package belongs to the build. Whatever is given for it, each junction
    stands as far above the case as before."""
    device = igbt(topology=Topology.half_bridge, construction="leadframe", i_nominal=15)
    p_sw, p_d = position_loss(math.sqrt(2) * 20.0, 0.8, 0.9, 8000.0)
    package = 2 * (p_sw + p_d)
    as_computed = solve(device, point(t_sink=60.0))
    for given in (0.05, 0.4, 1.2):
        r = solve(device, replace(point(t_sink=60.0), rth_case_sink=given))
        assert r.t_case == pytest.approx(60.0 + given * package, abs=0.02)
        assert r.tj_switch - r.t_case == pytest.approx(as_computed.tj_switch - as_computed.t_case, abs=0.02)
        assert r.tj_diode - r.t_case == pytest.approx(as_computed.tj_diode - as_computed.t_case, abs=0.02)
        assert not any("case-to-heatsink" in a for a in r.assumptions)  # given, so nothing was assumed
    on_a_pad = solve(device, replace(point(t_sink=60.0), interface="pad"))
    # 200 µm of a 1.5 W/(m·K) pad against 100 µm of 1 W/(m·K) grease, over the same copper.
    assert (on_a_pad.t_case - 60.0) / (as_computed.t_case - 60.0) == pytest.approx((200 / 1.5) / (100 / 1.0), rel=1e-3)
    assert on_a_pad.tj_switch - on_a_pad.t_case == pytest.approx(as_computed.tj_switch - as_computed.t_case, abs=0.02)


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


# ---------- a result that rests on data beyond the datasheet's last point ----------


def from_one_table_point(i_last: float = 10.0) -> Device:
    """On-state voltages drawn from one table point each, as a part typed in from a table is."""
    device = igbt(
        sw=[Curve(tj=25.0, current=[0.0, i_last], value=[V0_SW, V0_SW + R_SW * i_last])],
        d=[Curve(tj=25.0, current=[0.0, i_last], value=[V0_D, V0_D + R_D * i_last])],
        rth_case_sink=0.0,
    )
    for chip in (device.switch, device.diode):
        chip.conduction.basis = Basis.point
        chip.conduction.assumption = "below the first table point the shape is assumed"
    return device


def test_above_its_last_table_point_a_voltage_is_said_to_be_off_by_what_the_two_ways_it_could_go_allow() -> None:
    """Above the point the voltage lies between staying put and rising in proportion to the
    current. The line drawn runs midway: at twice the point's current that is a third either way."""
    i_last = 10.0
    r = solve(from_one_table_point(i_last), point(i_rms=2 * i_last / math.sqrt(2)))
    flat, in_proportion, drawn = 1.0, 2.0, 1.5  # of the point's voltage, at twice its current
    assert (in_proportion - drawn) / drawn == pytest.approx(1 / 3) == pytest.approx((drawn - flat) / drawn)
    assert any("switch conduction: peak current 20 A is above the last table point (10 A)" in n for n in r.notes)
    assert any("could be 33% off either way" in n for n in r.notes)
    assert r.validity is Validity.extrapolated
    # A junction rises mostly with its own chip's loss, so a chip's doubt is the share of its
    # own loss that is in doubt, and never less than the stage's. Each chip is carried to where
    # it would stand were that share higher, and the doubt is how much higher the hottest
    # junction's rise would then be.
    role = r.roles[0]
    of_switch = role.switch.conduction / role.switch.total / 3
    of_diode = role.diode.conduction / role.diode.total / 3
    of_stage = (role.switch.conduction + role.diode.conduction) / 3 / (role.switch.total + role.diode.total)
    assert of_diode > of_stage > of_switch
    hot = max(role.tj_switch_peak, role.tj_diode_peak)
    would = max(
        role.tj_switch_peak + of_stage * (role.tj_switch_peak - 25.0),
        role.tj_diode_peak + of_diode * (role.tj_diode_peak - 25.0),
    )
    # The recovery energy, measured at 25 °C and used warmer, adds a little of its own.
    expected = (would - hot) / (hot - 25.0)
    assert expected < r.doubt < expected + 0.01
    inside = solve(from_one_table_point(i_last), point(i_rms=0.9 * i_last / math.sqrt(2)))
    assert inside.doubt == 0.0 and inside.validity is not Validity.extrapolated


def test_a_pass_that_would_not_survive_the_doubt_in_its_losses_is_undecided() -> None:
    from motionsim import guard

    device = from_one_table_point()
    op = point(i_rms=20 / math.sqrt(2), t_sink=60.0)
    r = solve(device, op)
    top = max(r.tj_switch_peak, r.tj_diode_peak)
    rise = top - 60.0

    def temperature(rating: float) -> guard.Check:
        device.ratings.tj_max = rating
        return next(c for c in guard.check(device, op, r, 20.0, junction_margin=0.0) if c.topic == "temperature")

    # Were the doubted share of the loss that much higher, the junction would rise that much more.
    edge = top + r.doubt * rise
    assert temperature(edge + 1.0).level is guard.Level.ok
    held = temperature(edge - 1.0)
    assert held.level is guard.Level.undecided
    assert "beyond the datasheet's data" in held.message and f"{r.doubt:.0%}" in held.message
    assert temperature(top - 1.0).level is guard.Level.fail


def test_a_hot_chip_whose_loss_is_in_doubt_holds_the_pass_though_the_stage_as_a_whole_is_inside_its_data() -> None:
    """A diode that conducts a twentieth of the stage's loss is too little to put the stage
    outside its data. Most of that diode's own loss is conduction all the same: where it is
    the hottest chip its doubt holds the pass, and where it is a cool one it does not."""
    from motionsim import guard

    def stage(rth_d: float) -> Device:
        device = igbt(
            sw=[Curve(tj=t, current=[0.0, 40.0], value=[V0_SW, V0_SW + R_SW * 40.0]) for t in (25.0, 150.0)],
            d=[Curve(tj=25.0, current=[0.0, 10.0], value=[V0_D / 2, (V0_D + R_D * 10.0) / 2])],
            rth_d=rth_d,
            rth_case_sink=0.0,
        )
        device.diode.conduction.basis = Basis.point
        return device

    op = point(i_rms=20 / math.sqrt(2), power_factor=1.0, modulation_index=1.0)

    def temperature(device: Device, r, rating: float) -> guard.Check:
        device.ratings.tj_max = rating
        return next(c for c in guard.check(device, op, r, 20.0, junction_margin=0.0) if c.topic == "temperature")

    # The diode on a poor thermal path: the hottest chip, and the one in doubt.
    device = stage(rth_d=12.0)
    r = solve(device, op)
    role = r.roles[0]
    assert role.tj_diode_peak > role.tj_switch_peak
    of_stage = role.diode.conduction / (role.switch.total + role.diode.total)
    assert of_stage < 0.05 and r.outside == [] and r.validity is not Validity.extrapolated
    # At twice the last table point the voltage could be a third off: that share of the
    # diode's conduction, with a little of its recovery measured cold and used warmer.
    of_diode = role.diode.conduction / role.diode.total / 3
    assert of_diode > 0.2
    assert of_diode < r.doubt < of_diode + 0.02
    top = role.tj_diode_peak
    held = temperature(device, r, top + r.doubt * (top - 25.0) - 1.0)
    assert held.level is guard.Level.undecided
    assert "above the last table point" in held.message  # what is beyond the data is said
    # The same diode on a good path stands far below the switch, which has nothing in doubt:
    # carried up by its own share it is still the cooler chip, and the pass stands.
    device = stage(rth_d=1.5)
    r = solve(device, op)
    role = r.roles[0]
    assert role.tj_switch_peak > role.tj_diode_peak + 5.0
    assert role.tj_diode_peak + (role.tj_diode_peak - 25.0) < role.tj_switch_peak
    assert r.doubt == 0.0
    assert temperature(device, r, role.tj_switch_peak + 2.0).level is guard.Level.ok


def test_a_temperature_range_names_the_assumption_that_widens_it_most() -> None:
    from motionsim import guard
    from motionsim.engine import assumed

    def held(device: Device, op: OperatingPoint) -> tuple[str | None, str]:
        r = solve(device, op)
        device.ratings.tj_max = (max(r.tj_switch_peak, r.tj_diode_peak) + r.tj_peak_range[1]) / 2
        check = next(c for c in guard.check(device, op, r, 20.0, junction_margin=0.0) if c.topic == "temperature")
        assert check.level is guard.Level.undecided
        return r.range_lead, check.message

    # A discrete part with its transient curve given: only the layer under it is assumed.
    lead, said = held(igbt(outline="TO-247"), point())
    assert lead == "mounting" and "case-to-heatsink resistance" in said
    assert "the largest part of it from the layer under the package" in said
    # The same part with the layer given leaves nothing assumed, and no range.
    assert solve(igbt(outline="TO-247"), point(rth_case_sink=0.2)).tj_peak_range is None
    # A module of two positions: each chip is heated by the three others through the coupling,
    # and the whole package's loss crosses the layer. Whichever lifts the top more is named.
    module = igbt(topology=Topology.half_bridge, construction="leadframe", i_nominal=15)
    r = solve(module, point(i_rms=8.0))
    role = r.roles[0]
    package = 2 * (role.switch.total + role.diode.total)
    hot = role.switch.total if role.tj_switch_peak >= role.tj_diode_peak else role.diode.total
    by_layer = (
        assumed.module_interface("leadframe", 15, "high") - assumed.module_interface("leadframe", 15, "typical")
    ) * package
    by_chips = (
        assumed.module_coupling("leadframe", 15, "high") - assumed.module_coupling("leadframe", 15, "typical")
    ) * (package - hot)
    assert abs(by_layer - by_chips) > 0.5  # not a tie this test would call either way
    lead, said = held(module, point(i_rms=8.0))
    assert lead == ("mounting" if by_layer > by_chips else "between chips")
    assert ("case-to-heatsink resistance" in said) == (by_layer > by_chips)
    # Its mounting given, the chips are what is left.
    lead, said = held(module, point(i_rms=8.0, rth_case_sink=0.3))
    assert lead == "between chips" and "heat each other" in said
    # No transient curve and nothing else assumed: the swing within the period is the range.
    bare = igbt(outline="TO-247", tau=False)
    lead, said = held(bare, point(rth_case_sink=0.2, f_out=2.0))
    assert lead == "transient" and "transient thermal curve" in said


def test_the_largest_current_says_how_much_of_it_the_data_covers() -> None:
    from motionsim.engine.limits import supported_current

    i_last = 10.0
    device = from_one_table_point(i_last)
    op = point(t_sink=25.0)
    i_max, _ = max_current(device, op)
    assert i_max > i_last / math.sqrt(2)
    covered = supported_current(device, op, i_max)
    # The peak of the current reaches the last table point at that point's current over root two.
    assert covered == pytest.approx(i_last / math.sqrt(2), rel=0.02)
    assert supported_current(igbt(rth_case_sink=0.0), op, 20.0) is None  # curves that reach as far as asked


def test_what_the_data_covers_is_judged_by_the_current_alone() -> None:
    from motionsim.engine.limits import supported_current

    # A supply above the test voltage is outside the data at every current: that is not a
    # current the data stops at, and curves that reach as far as asked cover all of it.
    assert supported_current(igbt(rth_case_sink=0.0), point(v_dc=1.3 * V_REF), 20.0) is None
    # A table point at 10 A is reached by the crest of 10 / √2 A rms, on a warm heatsink as on a cold one.
    warm = supported_current(from_one_table_point(10.0), point(t_sink=60.0), 20.0)
    assert warm == pytest.approx(10.0 / math.sqrt(2), rel=0.01)


def test_the_doubt_is_reckoned_on_the_range_and_from_the_air_where_the_heatsink_stands_in_it() -> None:
    from motionsim import guard

    device = from_one_table_point()
    op = replace(point(i_rms=20 / math.sqrt(2), t_sink=40.0), rth_sink=0.5)  # 40 °C is the air
    r = solve(device, op)
    assert r.t_sink > 45.0  # the heatsink stands well above the air
    top = max(r.tj_switch_peak, r.tj_diode_peak)
    r = replace(r, tj_peak_range=(top - 5.0, top + 10.0), assumptions=["something assumed"])
    edge = (top + 10.0) + r.doubt * (top + 10.0 - 40.0)  # from the top of the range, down to the air
    device.ratings.tj_max = edge + 1.0
    assert (
        guard.verdict([c for c in guard.check(device, op, r, 20.0, junction_margin=0.0) if c.topic == "temperature"])
        is guard.Level.ok
    )
    device.ratings.tj_max = edge - 1.0
    found = next(c for c in guard.check(device, op, r, 20.0, junction_margin=0.0) if c.topic == "temperature")
    assert found.level is guard.Level.undecided and "beyond the datasheet's data" in found.message


def test_a_layer_named_for_the_build_is_computed_and_a_figure_given_for_it_is_not_called_missing() -> None:
    # A TO-247 whose datasheet gives 0.24 K/W on grease: kept on grease, computed on a pad.
    device = igbt(rth_case_sink=0.24, outline="TO-247")
    p_sw, p_d = position_loss(math.sqrt(2) * 20.0, 0.8, 0.9, 8000.0)
    as_given = solve(device, point(t_sink=60.0))
    assert as_given.t_case == pytest.approx(60.0 + 0.24 * (p_sw + p_d), abs=0.02)
    assert not any("case-to-heatsink" in a for a in as_given.assumptions)
    on_a_pad = solve(device, replace(point(t_sink=60.0), interface="pad"))
    # 200 µm of a 1.5 W/(m·K) pad under a tab of 15.9 mm by 17.0 mm.
    computed = 200e-6 / (1.5 * 15.9e-3 * 17.0e-3)
    assert on_a_pad.t_case == pytest.approx(60.0 + computed * (p_sw + p_d), abs=0.05)
    assert any("on a pad" in a for a in on_a_pad.assumptions)
    # With no outline there is nothing to compute a pad for: the figure stays, and that is said.
    bare = solve(igbt(rth_case_sink=0.24), replace(point(t_sink=60.0), interface="pad"))
    assert bare.t_case == pytest.approx(as_given.t_case, abs=0.02)
    assert any("left as it was" in n for n in bare.notes)
    # A part with neither, given a figure for the build: the case is not taken as the heatsink.
    unknown = igbt()
    assert any("sink temperature is used as the case temperature" in x for x in solve(unknown, point()).limits)
    given = solve(unknown, replace(point(t_sink=60.0), rth_case_sink=0.5))
    assert given.t_case == pytest.approx(60.0 + 0.5 * (p_sw + p_d), abs=0.02)
    assert not any("sink temperature is used as the case temperature" in x for x in given.limits)


def test_a_temperature_that_is_not_a_number_does_not_pass() -> None:
    from dataclasses import replace

    from motionsim import guard

    device = igbt()
    op = point()
    r = solve(device, op)
    broken = replace(r, tj_switch_peak=float("nan"), tj_diode_peak=float("nan"), tj_peak_range=None)
    check = next(c for c in guard.check(device, op, broken, 20.0) if c.topic == "temperature")
    assert check.level is guard.Level.fail and "could not be worked out" in check.message
    # One peak that is not a number is enough: the larger of a number and none is the number.
    half = replace(r, tj_diode_peak=float("nan"), tj_peak_range=None)
    check = next(c for c in guard.check(device, op, half, 20.0) if c.topic == "temperature")
    assert check.level is guard.Level.fail


def test_a_range_whose_top_runs_away_is_closed_at_a_figure_and_says_so() -> None:
    """Where the high end of the thermal assumptions does not settle there is no temperature
    to give: the range ends where the search stopped, far over any rating, with the reason."""
    from motionsim import guard

    # On-state voltage rising steeply with temperature, on a module whose chips heat each other.
    hot = [line(25.0, V0_SW, R_SW), line(150.0, V0_SW, 6 * R_SW)]
    device = igbt(sw=hot, topology=Topology.half_bridge, construction="leadframe", i_nominal=15)
    found = None
    for amps in (8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 24.0, 28.0):
        try:
            r = solve(device, point(i_rms=amps, t_sink=80.0))
        except ThermalRunaway:
            break
        if any("does not settle" in a for a in r.assumptions):
            found = r
            break
    assert found is not None, "no current where only the high end runs away"
    high = found.tj_peak_range[1]
    assert math.isfinite(high) and high == pytest.approx(device.ratings.tj_max + 500.0)
    check = next(
        c for c in guard.check(device, point(i_rms=amps, t_sink=80.0), found, 30.0) if c.topic == "temperature"
    )
    assert "inf" not in check.message and check.level in (guard.Level.undecided, guard.Level.fail)
    assert found.range_lead in ("mounting", "between chips")


def test_a_peak_current_with_no_room_for_the_current_loop_to_overshoot_is_a_caution() -> None:
    """The currents worked out are the ones the control settles to. A loop passes its
    reference for a moment on a step in torque, and a pulsed rating has no moment to give."""
    from motionsim import guard

    device = igbt()
    op = point()
    r = solve(device, op)

    def current(i_peak: float, **more) -> list[guard.Check]:
        return [c for c in guard.check(device, op, r, i_peak, **more) if c.topic == "current"]

    device.ratings.i_pulsed = 100.0
    # 15% over 86 A is 98.9 A, under the rating; 15% over 88 A is 101.2 A, past it.
    assert len(current(86.0)) == 1  # the one line on the continuous rating, and nothing on the pulsed
    held = current(88.0)[-1]
    assert held.level is guard.Level.caution and "overshoots" in held.message and "no current limit" in held.message
    assert "under 87 A" in held.message  # 100 A / 1.15
    # Settled above the rating it fails, as before, and says nothing of overshoot.
    over = current(101.0)[-1]
    assert over.level is guard.Level.fail and "overshoot" not in over.message
    # A drive known to overshoot less is held to less.
    assert len(current(88.0, overshoot=0.10)) == 1
    # With the drive's own limit known, that is what is checked, and the allowance is not used:
    # a limit under the rating says nothing, one over it says what to set.
    assert len(current(88.0, i_limit=95.0)) == 1
    over_limit = current(40.0, i_limit=120.0)[-1]
    assert over_limit.level is guard.Level.caution and "current limit lets 120 A" in over_limit.message
    assert "no more than 100 A peak reaches a device" in over_limit.message
    # A motor's limit is rms, a block-commutated one's the current itself; ripple rides on top.
    from motionsim.motor.machines import Pmsm

    motor = Pmsm(type="pmsm", pole_pairs=4, flux_linkage=0.1, ld=1e-3, lq=1e-3, rs=0.1, i_max=50.0)
    assert guard.current_limit(motor) == pytest.approx(50.0 * math.sqrt(2))
    assert guard.current_limit(motor, ripple_pp=4.0) == pytest.approx(50.0 * math.sqrt(2) + 2.0)
    assert guard.current_limit(motor.model_copy(update={"i_max": None})) is None
    # A brushed or block-commutated motor's limit is the current through the switch itself.
    from types import SimpleNamespace

    for kind in ("dc", "dc_series", "bldc"):
        assert guard.current_limit(SimpleNamespace(type=kind, i_max=20.0)) == 20.0
    assert guard.current_limit(SimpleNamespace(type="stepper")) is None


def test_a_narrow_range_that_crosses_the_rating_does_not_point_at_something_it_never_named() -> None:
    """Under 5 K a range is not said to come from anywhere, so the advice on narrowing it
    cannot open with "its" or "that curve"."""
    from dataclasses import replace

    from motionsim import guard

    device = igbt(outline="TO-247")
    op = point()
    r = solve(device, op)
    top = max(r.tj_switch_peak, r.tj_diode_peak)
    narrow = replace(r, tj_peak_range=(top - 1.0, top + 3.0), range_lead="mounting")
    device.ratings.tj_max = top + 1.0
    said = next(c for c in guard.check(device, op, narrow, 20.0, junction_margin=0.0) if c.topic == "temperature")
    assert said.level is guard.Level.undecided
    assert "largest part" not in said.message and "Its case-to-heatsink" not in said.message
    assert "A transient thermal curve, or how the chips" in said.message


def test_an_assumed_thermal_shape_stops_at_the_package_face_where_the_template_has_one() -> None:
    """What lies under a module belongs to the mounting: the shape assumed for a chip's own
    path does not move with it. A discrete part's template has no face of its own."""
    from motionsim.package.templates import response_shape

    assert response_shape("leadframe-module", 15.0, "typical", "grease") == response_shape(
        "leadframe-module", 15.0, "typical", "pad"
    )
    assert response_shape("TO-247", 15.0, "typical", "grease") != response_shape("TO-247", 15.0, "typical", "pad")
