"""Smaller points of the physics, each held to a figure worked out by hand."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from conftest import SRC, linear_device
from test_mosfet import Q_OSS, V_REF, fet, op

from motionsim.cooling import no_heatsink, on_copper
from motionsim.device import Curve, FosterNetwork, SwitchingEnergy
from motionsim.drivers import _usable, at_speed_and_torque
from motionsim.engine import OperatingPoint
from motionsim.engine.losses import conducted
from motionsim.engine.modulation import Role
from motionsim.engine.mosfet import charge_energies, mosfet_losses, recovery_charge, recovery_note
from motionsim.fit.sparse import turn_on_at_no_current
from motionsim.measured import DoublePulse, apply_double_pulse
from motionsim.motor.stage import Unreachable

# ---------- recovery charge away from where it was tabulated ----------


def _with_recovery(q_rr: float, at: float | None):
    device = fet()
    charge = device.switch.charge.model_copy(update={"q_rr": q_rr, "q_rr_current": at})
    return device.switch.model_copy(update={"charge": charge})


def test_recovery_charge_follows_the_square_root_of_the_current_from_its_test_current() -> None:
    """100 nC at 20 A: 50 nC at 5 A, a quarter of the current and half the charge, 100 at 20,
    and at 80 A twice that. At 45 A: √2.25 = 1.5."""
    c = _with_recovery(100e-9, 20.0).charge
    got = recovery_charge(c, np.array([0.0, 5.0, 20.0, 45.0, 80.0]))
    assert got.tolist() == pytest.approx([0.0, 50e-9, 100e-9, 150e-9, 200e-9])


def test_a_silicon_junction_recovers_more_charge_hot_and_the_others_do_not() -> None:
    """0.7% a kelvin from 25 °C: at 125 °C 1.7 times, at 25 °C as tabulated."""
    c = _with_recovery(100e-9, 20.0).charge
    at = np.array([20.0])
    assert recovery_charge(c, at, 125.0, "Si MOSFET")[0] == pytest.approx(170e-9)
    assert recovery_charge(c, at, 25.0, "Si MOSFET")[0] == pytest.approx(100e-9)
    for flat in ("SiC MOSFET", "GaN HEMT", ""):
        assert recovery_charge(c, at, 125.0, flat)[0] == pytest.approx(100e-9)
    # A temperature for each instant of the period is taken instant by instant.
    hot = recovery_charge(c, np.array([20.0, 20.0]), np.array([25.0, 75.0]), "Si MOSFET")
    assert hot.tolist() == pytest.approx([100e-9, 135e-9])


def test_turn_on_energy_carries_the_recovery_charge_at_the_junctions_temperature() -> None:
    """What recovery adds to turn-on is its charge times the voltage: at 80 A and 125 °C,
    100 nC × 2 × 1.7 = 340 nC through 300 V is 102 µJ."""
    chip, bare = _with_recovery(100e-9, 20.0), _with_recovery(0.0, None)
    drive, at = op(), np.array([80.0])
    with_it = charge_energies(chip, at, drive, 125.0, "Si MOSFET")[0][0]
    without = charge_energies(bare, at, drive, 125.0, "Si MOSFET")[0][0]
    assert with_it - without == pytest.approx(340e-9 * 300.0)
    # And the loss of a position takes its junction temperature there.
    n = 4
    role = Role("one", 1, np.full(n, 80.0), np.ones(n), np.zeros(n), np.ones(n), np.zeros(n))
    cold = mosfet_losses(chip, role, drive, 25.0, "Si MOSFET")[0].turn_on
    hot = mosfet_losses(chip, role, drive, 125.0, "Si MOSFET")[0].turn_on
    assert hot - cold == pytest.approx(0.7 * 200e-9 * 300.0 * drive.f_sw)
    assert mosfet_losses(chip, role, drive, 125.0)[0].turn_on == pytest.approx(cold)


def test_a_recovery_charge_used_away_from_its_conditions_is_said() -> None:
    chip = _with_recovery(100e-9, 20.0)
    assert recovery_note(chip, "Si MOSFET", 20.0, 25.0) is None
    below = recovery_note(chip, "SiC MOSFET", 15.0, 25.0)
    assert below is not None and "20 A" in below and "square root" in below
    above = recovery_note(chip, "SiC MOSFET", 40.0, 125.0)
    assert above is not None and "20 A" in above and "square root" in above and "°C" not in above
    hot = recovery_note(chip, "Si MOSFET", 15.0, 125.0)
    assert hot is not None and "1.70 times" in hot and "125 °C" in hot
    assert recovery_note(_with_recovery(0.0, None), "Si MOSFET", 40.0, 125.0) is None
    assert recovery_note(fet(measured=True).switch, "Si MOSFET", 40.0, 125.0) is None


# ---------- turn-on energy at no current ----------


def _measured_table(first: float = 200e-6) -> SwitchingEnergy:
    return SwitchingEnergy(
        curves=[Curve(tj=25.0, current=[0.0, 10.0, 30.0], value=[0.0, first, 3 * first])],
        v_ref=V_REF,
        source=SRC.model_copy(update={"note": "curves; taken to zero at zero current"}),
    )


def test_turn_on_at_no_current_loses_the_output_charge_through_the_voltage() -> None:
    """80 nC through 300 V is 24 µJ, lost with no current at all."""
    charge = fet().switch.charge
    table = turn_on_at_no_current(_measured_table(), charge)
    assert table.curves[0].current == [0.0, 10.0, 30.0]
    assert table.curves[0].value == pytest.approx([Q_OSS * V_REF, 200e-6, 600e-6])
    assert table.curves[0].value[0] == pytest.approx(24e-6)
    assert "output charge" in table.source.note and "taken to zero" not in table.source.note
    # Halfway to the first measured current: midway between 24 and 200 µJ, not 100.
    from motionsim.engine.losses import energy

    assert energy(table, np.array([5.0]), 25.0, V_REF)[0] == pytest.approx(112e-6)


def test_the_point_at_no_current_is_never_above_the_lowest_measured_energy() -> None:
    charge = fet().switch.charge
    low = turn_on_at_no_current(_measured_table(first=10e-6), charge)
    assert low.curves[0].value == pytest.approx([10e-6, 10e-6, 30e-6])


def test_a_table_is_left_alone_where_there_is_no_output_charge_to_go_by() -> None:
    table = _measured_table()
    assert turn_on_at_no_current(table, None) is table
    none = fet().switch.charge.model_copy(update={"q_oss": 0.0})
    assert turn_on_at_no_current(table, none) is table
    # A point the datasheet itself gives at no current stands.
    given = table.model_copy(
        update={"curves": [Curve(tj=25.0, current=[0.0, 10.0], value=[5e-6, 200e-6])]},
    )
    assert turn_on_at_no_current(given, fet().switch.charge).curves[0].value == [5e-6, 200e-6]


def test_a_double_pulse_file_for_a_transistor_keeps_the_output_charge_at_no_current() -> None:
    data = DoublePulse.model_validate(
        {"v_dc": 300, "energy_unit": "uJ", "points": [{"tj": 25, "current": 10, "e_on": 200, "e_off": 100}]}
    )
    device = apply_double_pulse(fet(), data, "dpt.json")
    assert device.switch.e_on.curves[0].value == pytest.approx([24e-6, 200e-6])
    assert device.switch.e_off.curves[0].value == pytest.approx([0.0, 100e-6])
    # An IGBT has no output charge in its model: its table goes to nothing, as before.
    from test_motor import igbt

    assert apply_double_pulse(igbt(), data).switch.e_on.curves[0].value == pytest.approx([0.0, 200e-6])


# ---------- conduction loss with ripple: a knee loses with the mean current ----------


def _rippled(mean: float, pp: float, n: int = 4) -> Role:
    one, none = np.ones(n), np.zeros(n)
    return Role(
        "one",
        1,
        np.full(n, np.sqrt(mean**2 + pp**2 / 12)),
        one,
        none,
        one,
        none,
        current_on=np.full(n, max(mean - pp / 2, 0.0)),
        current_off=np.full(n, mean + pp / 2),
    )


def test_a_knee_voltage_loses_with_the_mean_current_and_a_resistance_with_the_mean_square() -> None:
    """10 A with 6 A of ripple, through 1 V and 0.05 Ω: the knee loses 1 × 10 = 10 W, the
    resistance 0.05 × (100 + 36/12) = 5.15 W. Taking the knee at the root of the mean
    square, 10.149 A, gave 15.299 W."""
    role = _rippled(10.0, 6.0)
    got = conducted(lambda i: 1.0 + 0.05 * i, role)
    assert got.tolist() == pytest.approx([15.15] * 4)
    # With no ripple there is nothing to average.
    plain = Role("one", 1, np.full(4, 10.0), np.ones(4), np.zeros(4), np.ones(4), np.zeros(4))
    assert conducted(lambda i: 1.0 + 0.05 * i, plain).tolist() == pytest.approx([15.0] * 4)


def test_ripple_wider_than_twice_the_current_still_gives_the_mean_square() -> None:
    """2 A with 10 A of ripple: the bottom is clamped at zero in the role, and the middle is
    found from the top and the root mean square all the same. The resistance loses
    0.05 × (4 + 100/12) W whichever way the current runs."""
    role = _rippled(2.0, 10.0)
    assert conducted(lambda i: 0.05 * i, role).tolist() == pytest.approx([0.05 * (4 + 100 / 12)] * 4)


def test_the_engine_takes_an_igbts_knee_at_the_mean_current() -> None:
    """One position on all the time with 10 A and 6 A of ripple, 1 V plus 0.05 Ω, no
    switching energy: 15.15 W, by the arithmetic above."""
    from conftest import line

    from motionsim.engine.solver import solve_roles

    device = linear_device(sw_curves=[line(25.0, 1.0, 0.05)], d_curves=[line(25.0, 1.0, 0.05)])
    base = OperatingPoint(v_dc=300, i_rms=10, modulation_index=0.5, power_factor=1.0, f_sw=8000, t_sink=25)
    role = replace(_rippled(10.0, 6.0, 16), switch_events=np.zeros(16))
    r = solve_roles(device, [role], base, period=0.02, p_out=0.0)
    assert r.switch.conduction == pytest.approx(15.15)


# ---------- the voltage a stage can give ----------


def test_a_stage_left_with_less_than_half_its_voltage_is_refused_not_floored() -> None:
    """The made-up IGBT drops 1 V plus 0.03 V an amp. On 8 V with 20 A and 12.5 µs of dead
    time at 8 kHz: 1 − 0.2 − 1.6/4 = 0.4 of the voltage is left."""
    from test_edges import igbt

    device = igbt("made-up", 1.0)
    base = OperatingPoint(v_dc=8, i_rms=0, modulation_index=0, power_factor=1, f_sw=8000, t_sink=25, t_dead=12.5e-6)
    with pytest.raises(Unreachable, match="40% of the voltage is left"):
        _usable(device, base, 20.0)
    assert issubclass(Unreachable, ValueError)
    # Just inside: 10 A drops 1.3 V, 1 − 0.2 − 1.3/4 = 0.475 is refused, and with 5 µs of
    # dead time 1 − 0.08 − 0.325 = 0.595 is given as it is.
    with pytest.raises(Unreachable):
        _usable(device, base, 10.0)
    assert _usable(device, replace(base, t_dead=5e-6), 10.0) == pytest.approx(0.595)
    # Nothing lost is all of it, and no more.
    assert _usable(device, replace(base, v_dc=300, t_dead=0.0), 0.0) == 1.0


def test_a_motor_point_on_a_stage_that_loses_half_its_voltage_is_unreachable() -> None:
    from test_edges import igbt

    from motionsim.motor.machines import BrushedDc as Dc

    device = igbt("made-up", 1.0)
    motor = Dc(type="dc", kt=0.05, r=0.01, l=1e-3)
    base = OperatingPoint(v_dc=4, i_rms=0, modulation_index=0, power_factor=1, f_sw=8000, t_sink=25)
    with pytest.raises(Unreachable, match="devices drop"):
        at_speed_and_torque(device, motor, 10.0, 1.0, base)


# ---------- cooling with no heatsink ----------


def _copack(rth_switch: float, rth_diode: float):
    from conftest import line

    device = linear_device(sw_curves=[line(25.0, 1.0, 0.05)], d_curves=[line(25.0, 1.0, 0.05)])
    thermal = lambda r: FosterNetwork(r=[r], tau=[0.01], source=SRC)
    return device.model_copy(
        update={
            "switch": device.switch.model_copy(update={"thermal": thermal(rth_switch)}),
            "diode": device.diode.model_copy(update={"thermal": thermal(rth_diode)}),
        }
    )


def test_case_to_air_is_junction_to_air_less_the_smaller_junction_to_case() -> None:
    """40 K/W to the air, 0.5 K/W in the switch and 1.5 in the diode: 39.5 K/W lies between
    the case and the air, and with the two the other way round as well."""
    assert no_heatsink(_copack(0.5, 1.5), 40.0).rth_free == pytest.approx(39.5)
    assert no_heatsink(_copack(1.5, 0.5), 40.0).rth_free == pytest.approx(39.5)
    # A figure to the air that is not above the one to the case is not a figure to the air.
    with pytest.raises(ValueError, match="not above"):
        no_heatsink(_copack(0.5, 1.5), 0.5)
    assert no_heatsink(_copack(0.5, 1.5), 1.0).rth_free == pytest.approx(0.5)


@pytest.mark.parametrize(
    "wrong",
    [
        {"board_area": 0.0},
        {"board_area": -50.0},
        {"board_area": 100.0, "copper": 0.0},
        {"board_area": 100.0, "copper": -2.0},
        {"board_area": 100.0, "copper_ref": 0.0},
        {"board_area": 100.0, "copper_ref": -6.45},
        {"copper_ref": -1.0},
    ],
)
def test_an_area_of_nothing_or_less_is_refused(wrong: dict) -> None:
    with pytest.raises(ValueError, match="above zero"):
        no_heatsink(_copack(0.5, 1.5), 40.0, **wrong)


def test_a_junction_to_air_figure_of_nothing_or_less_is_refused() -> None:
    for rth in (0.0, -40.0):
        with pytest.raises(ValueError, match="above zero"):
            no_heatsink(_copack(0.5, 1.5), rth)


def test_pads_that_exactly_fill_the_board_fit_and_one_more_does_not() -> None:
    """Six pads of 5 cm² are 30 cm²: they fit on 30 and not on 29.9."""
    device = _copack(0.5, 1.5)
    assert no_heatsink(device, 40.0, board_area=30.0, copper=5.0, packages=6).rth_board == pytest.approx(1 / 0.06)
    with pytest.raises(ValueError, match="does not fit"):
        no_heatsink(device, 40.0, board_area=29.9, copper=5.0, packages=6)


def test_the_line_about_the_pad_is_written_only_when_the_pad_is_not_the_datasheets() -> None:
    device = _copack(0.5, 1.5)
    same = no_heatsink(device, 40.0, board_area=100.0, copper=2.0, copper_ref=2.0)
    assert same.rth_ja == pytest.approx(40.0) and not any("each package has" in line for line in same.lines)
    other = no_heatsink(device, 40.0, board_area=100.0, copper=2.0)
    assert other.rth_ja == pytest.approx(on_copper(40.0, 2.0))
    assert any("each package has" in line for line in other.lines)


# ---------- what a motor point says of itself ----------


def test_a_point_that_gives_the_shaft_nothing_has_no_efficiency_and_one_that_does_has() -> None:
    """Driving: shaft power over shaft power plus both losses, 1 N·m at 100 rad/s."""
    from test_edges import igbt

    from motionsim.motor.machines import BrushedDc

    device = igbt("made-up", 1.0)
    motor = BrushedDc(type="dc", kt=0.5, r=0.5, l=1e-3)
    base = OperatingPoint(v_dc=300, i_rms=0, modulation_index=0, power_factor=1, f_sw=8000, t_sink=25)
    rpm = 100 * 30 / np.pi
    driving = at_speed_and_torque(device, motor, rpm, 1.0, base)
    shaft, copper = 100.0, 0.5 * 2.0**2
    assert driving.stage.p_shaft == pytest.approx(shaft) and driving.stage.p_motor_loss == pytest.approx(copper)
    assert driving.system_efficiency == pytest.approx(shaft / (shaft + copper + driving.result.p_inverter))
    assert at_speed_and_torque(device, motor, rpm, -1.0, base).system_efficiency is None
    assert at_speed_and_torque(device, motor, 0.0, 1.0, base).system_efficiency is None


def test_a_stage_that_loses_none_of_its_voltage_says_nothing_about_it() -> None:
    """No dead time, no shortest pulse and no current: all of the voltage is there, and the
    note on what the stage gives is for a stage that gives less."""
    from test_edges import igbt

    from motionsim.motor.machines import BrushedDc

    device = igbt("made-up", 1.0)
    motor = BrushedDc(type="dc", kt=0.5, r=0.5, l=1e-3)
    base = OperatingPoint(v_dc=300, i_rms=0, modulation_index=0, power_factor=1, f_sw=8000, t_sink=25)
    idle = at_speed_and_torque(device, motor, 500.0, 0.0, base)
    assert not any("of the ideal output voltage" in note for note in idle.stage.notes)
    loaded = at_speed_and_torque(device, motor, 500.0, 1.0, base)
    # 2 A through 1 V plus 0.03 V an amp: 1.06 V of 150 V.
    assert any(f"{1 - 1.06 / 150:.1%} of the ideal output voltage" in note for note in loaded.stage.notes)
