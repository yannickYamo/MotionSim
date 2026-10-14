"""Level A checks for field-effect transistors."""

from __future__ import annotations

import math

import pytest
from conftest import SRC, V_REF, energy, line

from motionsim.device import (
    ChargeModel,
    Chip,
    ConductionModel,
    Device,
    FosterNetwork,
    Package,
    Ratings,
    Topology,
)
from motionsim.engine import OperatingPoint, Validity, solve
from motionsim.engine.mosfet import MissingGateDrive

R_ON, V_SD = 0.02, 2.0
Q_GS, Q_GD, Q_TH, V_PL, Q_OSS, Q_RR = 9e-9, 2.5e-9, 6e-9, 2.5, 80e-9, 10e-9


def fet(*, measured: bool = False, reverse: bool = True) -> Device:
    chip = Chip(
        kind="mosfet",
        conduction=ConductionModel(curves=[line(25.0, 0.0, R_ON)], source=SRC),
        reverse=ConductionModel(curves=[line(25.0, V_SD, 0.0)], source=SRC) if reverse else None,
        e_on=energy(20e-6) if measured else None,
        e_off=energy(10e-6) if measured else None,
        charge=None
        if measured
        else ChargeModel(
            q_gs=Q_GS,
            q_gd=Q_GD,
            q_g_th=Q_TH,
            v_plateau=V_PL,
            q_oss=Q_OSS,
            v_ref=V_REF,
            q_rr=Q_RR,
            source=SRC,
        ),
        thermal=FosterNetwork(r=[0.5], tau=[0.01], source=SRC),
    )
    return Device(
        vendor="synthetic",
        part_number="FET",
        technology="GaN HEMT",
        ratings=Ratings(v_max=650, i_nominal=30, tj_max=150),
        package=Package(topology=Topology.discrete),
        switch=chip,
    )


def op(**kw) -> OperatingPoint:
    base = dict(
        v_dc=V_REF,
        i_rms=20.0,
        modulation_index=0.9,
        power_factor=0.8,
        f_sw=50_000.0,
        t_sink=25.0,
        v_drive=5.0,
        rg_on=2.0,
        rg_off=1.0,
    )
    return OperatingPoint(**{**base, **kw})


@pytest.mark.parametrize(("m", "pf"), [(0.3, 1.0), (0.9, 0.8), (1.0, 0.0), (0.7, -0.6)])
def test_resistive_channel_conducts_both_ways(m: float, pf: float) -> None:
    """With the channel carrying current in both directions the loss is R*Irms^2/2 per switch,
    whatever the modulation index and power factor."""
    r = solve(fet(), op(modulation_index=m, power_factor=pf))
    assert r.switch.conduction == pytest.approx(R_ON * 20.0**2 / 2, rel=0.01)
    assert r.diode.total == 0.0
    assert r.tj_diode == r.tj_switch


def test_charge_based_switching_matches_closed_form() -> None:
    f_sw, i_pk = 50_000.0, math.sqrt(2) * 20.0
    moved = Q_GS - Q_TH + Q_GD
    t_on, t_off = moved * 2.0 / (5.0 - V_PL), moved * 1.0 / V_PL
    r = solve(fet(), op())
    assert r.switch.turn_on == pytest.approx(
        f_sw * (0.5 * V_REF * t_on * i_pk / math.pi + 0.5 * (Q_OSS + Q_RR) * V_REF), rel=0.01
    )
    assert r.switch.turn_off == pytest.approx(f_sw * 0.5 * V_REF * t_off * i_pk / math.pi, rel=0.01)
    assert r.validity is Validity.assumed
    assert any("estimated from gate and output charge" in n for n in r.notes)


def test_dead_time_loss_matches_closed_form() -> None:
    f_sw, t_dead, i_pk = 50_000.0, 50e-9, math.sqrt(2) * 20.0
    without = solve(fet(), op())
    with_dead = solve(fet(), op(t_dead=t_dead))
    assert without.switch.dead_time == 0.0
    assert with_dead.switch.dead_time == pytest.approx(2 * t_dead * f_sw * V_SD * i_pk / math.pi, rel=0.01)
    # the channel conducts for that much less of the reverse half-cycle
    saved = 2 * t_dead * f_sw * R_ON * i_pk**2 / 4
    assert without.switch.conduction - with_dead.switch.conduction == pytest.approx(saved, rel=0.02)


def test_charge_model_refuses_without_gate_drive() -> None:
    with pytest.raises(MissingGateDrive, match="gate drive voltage"):
        solve(fet(), op(v_drive=None))
    with pytest.raises(MissingGateDrive, match="does not exceed the plateau"):
        solve(fet(), op(v_drive=2.0))


def test_measured_energy_needs_no_gate_drive() -> None:
    r = solve(fet(measured=True), op(v_drive=None, rg_on=None, rg_off=None))
    assert r.switch.turn_on > 0
    assert not any("gate and output charge" in n for n in r.notes)


def test_missing_reverse_data_is_reported() -> None:
    r = solve(fet(reverse=False), op(t_dead=50e-9))
    assert r.switch.dead_time == 0.0
    assert any("dead-time loss is left out" in x for x in r.limits)


def test_mosfet_with_a_diode_chip_is_rejected() -> None:
    from pydantic import ValidationError

    good = fet()
    diode = Chip(
        kind="diode",
        conduction=ConductionModel(curves=[line(25.0, 1.0, 0.01)], source=SRC),
        thermal=FosterNetwork(r=[1.0], source=SRC),
    )
    with pytest.raises(ValidationError, match="no separate diode"):
        Device(**{**good.model_dump(), "diode": diode.model_dump()})


def test_overshoot_check_and_avalanche_wording() -> None:
    quiet = solve(fet(), op(v_dc=100.0))
    assert quiet.rating_warnings == []

    unchecked = solve(fet(), op(v_dc=560.0))
    assert any("overshoot is not checked" in w for w in unchecked.rating_warnings)

    # t_fall = (9 - 6) nC * 1 ohm / 2.5 V = 1.2 ns; 28.3 A peak; 20 nH -> about 471 V
    hard = solve(fet(), op(v_dc=400.0, l_loop=20e-9))
    assert any("not rated for avalanche" in w for w in hard.rating_warnings)

    silicon = fet()
    silicon.technology = "Si MOSFET"
    assert any("repetitive avalanche rating" in w for w in solve(silicon, op(v_dc=400.0, l_loop=20e-9)).rating_warnings)

    small = solve(fet(), op(v_dc=400.0, l_loop=1e-9))  # about 24 V of overshoot
    assert small.rating_warnings == []

    assert any("above the 650 V rating" in w for w in solve(fet(), op(v_dc=700.0)).rating_warnings)


def test_recovery_charge_is_nothing_at_no_current_and_follows_the_current_below_its_test_point() -> None:
    import numpy as np

    from motionsim.engine.mosfet import charge_energies

    device = fet()
    charge = device.switch.charge.model_copy(update={"q_rr": 1e-6, "q_rr_current": None})
    chip = device.switch.model_copy(update={"charge": charge})
    drive = op(i_rms=0.0)
    e_on, _ = charge_energies(chip, np.array([0.0, 5.0, 40.0]), drive)
    without, _ = charge_energies(
        device.switch.model_copy(update={"charge": charge.model_copy(update={"q_rr": 0.0})}),
        np.array([0.0, 5.0, 40.0]),
        drive,
    )
    assert (e_on - without).tolist() == pytest.approx([0.0, 1e-6 * drive.v_dc, 1e-6 * drive.v_dc])
    scaled = chip.model_copy(update={"charge": charge.model_copy(update={"q_rr_current": 20.0})})
    e_scaled, _ = charge_energies(scaled, np.array([0.0, 5.0, 40.0]), drive)
    assert (e_scaled - without).tolist() == pytest.approx([0.0, 0.25e-6 * drive.v_dc, 1e-6 * drive.v_dc])


def test_the_lowest_sensorless_speed_follows_from_the_voltage_the_stage_gets_wrong() -> None:
    """Dead time takes t·f·V from a phase and the channel drops R·I. A back-EMF four times
    their sum is taken as readable: the electrical speed is that over the flux linkage."""
    import math

    from motionsim import recommend

    device = fet()
    flux, pairs, amps = 0.01, 7, 30.0
    at = op(t_dead=500e-9, f_sw=20_000.0, v_dc=48.0)
    found = recommend.sensorless_floor(device, at, amps, flux, pairs)
    wrong = 500e-9 * 20_000.0 * 48.0 + R_ON * amps
    assert found.value["voltage_error"] == pytest.approx(wrong, rel=1e-9)
    assert found.value["rpm"] == pytest.approx(4.0 * wrong / flux / pairs * 60 / (2 * math.pi), rel=1e-9)
    # A shorter dead time, or two devices sharing the current, lets the drive read the rotor sooner.
    shorter = recommend.sensorless_floor(device, op(t_dead=100e-9, f_sw=20_000.0, v_dc=48.0), amps, flux, pairs)
    shared = recommend.sensorless_floor(
        device, op(t_dead=500e-9, f_sw=20_000.0, v_dc=48.0, parallel=2), amps, flux, pairs
    )
    assert shorter.value["rpm"] < found.value["rpm"] and shared.value["rpm"] < found.value["rpm"]
    assert shared.value["voltage_error"] == pytest.approx(500e-9 * 20_000.0 * 48.0 + R_ON * amps / 2, rel=1e-9)


def test_the_drop_counted_against_a_sensorless_drive_is_the_mean_of_switch_and_diode() -> None:
    from conftest import linear_device

    from motionsim import recommend

    device = linear_device(sw_curves=[line(25.0, 0.9, 0.03)], d_curves=[line(25.0, 1.0, 0.025)])
    at = OperatingPoint(v_dc=300.0, i_rms=0.0, modulation_index=0.0, power_factor=1.0, f_sw=8000.0, t_sink=25.0)
    found = recommend.sensorless_floor(device, at, 10.0, 0.1, 4, margin=3.0)
    # No dead time given: the drop is all there is. Switch 0.9 + 0.3 V, diode 1.0 + 0.25 V.
    assert found.value["voltage_error"] == pytest.approx((1.2 + 1.25) / 2)
    assert found.value["rpm"] == pytest.approx(3.0 * 1.225 / 0.1 / 4 * 60 / (2 * math.pi))
    assert "an estimate" in found.lines[-1] and "3 times" in found.lines[-1]
