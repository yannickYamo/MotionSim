"""Each motor type against what its power stage must dissipate, in closed form."""

from __future__ import annotations

import math

import numpy as np
import pytest
from conftest import V_REF, line, linear_device
from test_mosfet import R_ON, fet
from test_mosfet import op as fet_op

from motionsim.drivers import at_speed_and_torque
from motionsim.engine import OperatingPoint, Pwm, solve
from motionsim.motor import Bldc, BrushedDc, Induction, Stepper, Unreachable, load_machine

V0, R, VF0, RF = 0.9, 0.03, 1.0, 0.025
K_ON, K_OFF, K_RR = 20e-6, 15e-6, 5e-6
F_SW = 8000.0


def igbt():
    return linear_device(
        sw_curves=[line(25.0, V0, R)], d_curves=[line(25.0, VF0, RF)],
        k_on=K_ON, k_off=K_OFF, k_rr=K_RR, rth_sw=0.01, rth_d=0.01,
    )


BASE = OperatingPoint(
    v_dc=V_REF, i_rms=0.0, modulation_index=0.0, power_factor=1.0, f_sw=F_SW, t_sink=25.0
)


def by_name(result):
    return {r.name: r for r in result.roles}


def test_brushed_dc_h_bridge_with_igbts() -> None:
    motor = BrushedDc(type="dc", kt=0.5, r=2.0)
    rpm, torque = 2000.0, 5.0
    current = torque / 0.5
    duty = (0.5 * 2 * math.pi * rpm / 60 + 2.0 * current) / V_REF
    point = at_speed_and_torque(igbt(), motor, rpm, torque, BASE)
    roles = by_name(point.result)

    chop = roles["leg A high side"]
    assert chop.switch.conduction == pytest.approx(duty * current * (V0 + R * current))
    assert chop.switch.turn_on == pytest.approx(F_SW * K_ON * current)
    assert chop.diode.total == 0.0
    free = roles["leg A low side"]
    assert free.diode.conduction == pytest.approx((1 - duty) * current * (VF0 + RF * current))
    assert free.diode.recovery == pytest.approx(F_SW * K_RR * current)
    assert free.switch.total == 0.0
    steer = roles["leg B low side"]
    assert steer.switch.conduction == pytest.approx(current * (V0 + R * current))
    assert steer.switch.turn_on == 0.0
    assert roles["leg B high side"].switch.total == 0.0

    assert point.result.p_inverter == pytest.approx(sum(r.switch.total + r.diode.total for r in point.result.roles))
    assert point.stage.p_electrical == pytest.approx(point.stage.p_shaft + point.stage.p_motor_loss)
    assert point.result.tj_switch_peak == max(r.hottest for r in point.result.roles)


def test_brushed_dc_h_bridge_with_mosfets_loses_two_i_squared_r() -> None:
    """Chopping plus synchronous freewheeling is one R; the steering switch is the other."""
    motor = BrushedDc(type="dc", kt=0.5, r=1.0)
    current = 3.0 / 0.5
    point = at_speed_and_torque(fet(), motor, 1500.0, 3.0, fet_op(f_sw=1e-9))
    conduction = sum(r.switch.conduction for r in point.result.roles)
    assert conduction == pytest.approx(2 * R_ON * current**2, rel=1e-6)


def test_brushless_dc_block_commutation() -> None:
    motor = Bldc(type="bldc", pole_pairs=4, kt=0.4, r=1.5)
    rpm, torque = 3000.0, 4.0
    current = torque / 0.4
    duty = (0.4 * 2 * math.pi * rpm / 60 + 1.5 * current) / V_REF
    point = at_speed_and_torque(igbt(), motor, rpm, torque, BASE)
    roles = by_name(point.result)

    high = roles["high-side position"]
    assert high.switch.conduction == pytest.approx(duty * current * (V0 + R * current) / 3)
    assert high.switch.turn_on == pytest.approx(F_SW * K_ON * current / 3)
    low = roles["low-side position"]
    assert low.switch.conduction == pytest.approx(current * (V0 + R * current) / 3)
    assert low.switch.turn_on == 0.0
    assert low.diode.conduction == pytest.approx((1 - duty) * current * (VF0 + RF * current) / 3)
    assert low.diode.recovery == pytest.approx(F_SW * K_RR * current / 3)
    assert point.result.p_inverter == pytest.approx(
        3 * (high.switch.total + low.switch.total + low.diode.total)
    )
    assert point.stage.p_electrical == pytest.approx(point.stage.p_shaft + point.stage.p_motor_loss)


def test_voltage_limits_are_refused() -> None:
    with pytest.raises(Unreachable, match="more than the DC link"):
        at_speed_and_torque(igbt(), BrushedDc(type="dc", kt=0.5, r=2.0), 9000.0, 5.0, BASE)
    with pytest.raises(Unreachable, match="more than the DC link"):
        at_speed_and_torque(igbt(), Bldc(type="bldc", pole_pairs=4, kt=0.4, r=1.5), 9000.0, 4.0, BASE)


IM = Induction(
    type="induction", pole_pairs=2, rs=1.2, rr=0.9, lm=0.12, lls=0.006, llr=0.006, i_magnetising=3.0
)


def test_induction_motor_power_balance_and_slip() -> None:
    stage = IM.stage(1400.0, 5.0, 560.0, Pwm.space_vector)
    assert stage.p_electrical == pytest.approx(stage.p_shaft + stage.p_motor_loss, rel=1e-9)
    lr = 0.126
    i_q = 5.0 / (1.5 * 2 * 0.12**2 / lr * 3.0)
    slip_hz = dict((label, value) for label, value, _ in stage.summary)["slip frequency"]
    assert slip_hz == pytest.approx(0.9 / lr * i_q / 3.0 / (2 * math.pi))
    assert stage.roles[0].count == 6


def test_induction_motor_weakens_flux_at_the_voltage_limit() -> None:
    free = IM.stage(3000.0, 2.0, 2000.0, Pwm.space_vector)
    limited = IM.stage(3000.0, 2.0, 300.0, Pwm.space_vector)
    v = {label: value for label, value, _ in limited.summary}
    assert v["field weakening"] == 1.0
    assert v["phase voltage"] * math.sqrt(2) == pytest.approx(2 / math.sqrt(3) * 150.0, rel=1e-6)
    assert limited.p_electrical == pytest.approx(limited.p_shaft + limited.p_motor_loss, rel=1e-9)
    assert limited.i_peak > free.i_peak * 0.5  # less flux, more torque current


STEP = Stepper(type="stepper", i_phase=2.0, r=1.5, l=0.003, holding_torque=0.5)


def test_stepper_is_two_h_bridges_of_sinusoidal_legs() -> None:
    rpm = 300.0
    w = 50 * 2 * math.pi * rpm / 60
    back_emf = 0.5 / (50 * 2.0) * w
    working = 0.2 / 0.5  # the share of the back-EMF in phase with the current
    resistive = 1.5 * 2.0 + back_emf * working
    v_peak = math.hypot(resistive, w * 0.003 * 2.0 + back_emf * math.sqrt(1 - working**2))
    point = at_speed_and_torque(igbt(), STEP, rpm, 0.2, BASE)
    assert point.stage.roles[0].count == 8
    same_leg = solve(igbt(), OperatingPoint(
        v_dc=V_REF, i_rms=2.0 / math.sqrt(2), modulation_index=v_peak / V_REF,
        power_factor=resistive / v_peak, f_sw=F_SW, t_sink=25.0, n_steps=1440,
    ))
    assert point.result.p_inverter == pytest.approx(same_leg.p_inverter * 8 / 6, rel=1e-9)
    assert point.stage.p_electrical == pytest.approx(
        2 * (v_peak / math.sqrt(2)) * (2.0 / math.sqrt(2)) * resistive / v_peak
    )


def test_stepper_limits() -> None:
    with pytest.raises(Unreachable, match="holding torque"):
        STEP.stage(100.0, 0.6, V_REF, Pwm.sine)
    with pytest.raises(Unreachable, match="the current, and the torque, fall"):
        STEP.stage(60000.0, 0.1, 24.0, Pwm.sine)
    held = at_speed_and_torque(igbt(), STEP, 0.0, 0.4, BASE)
    assert np.isfinite(held.result.tj_switch_peak)


def test_motor_file_selects_the_type(tmp_path) -> None:
    path = tmp_path / "m.yaml"
    path.write_text("type: dc\nkt: 0.1\nr: 0.5\n")
    assert isinstance(load_machine(path), BrushedDc)
    path.write_text("pole_pairs: 4\nflux_linkage: 0.1\nld: 0.008\nlq: 0.008\nrs: 1.0\n")
    assert load_machine(path).type == "pmsm"


def test_brushed_dc_braking_returns_energy_through_the_other_leg() -> None:
    """Forward rotation, braking torque: the current reverses, so it runs from leg B to
    leg A. Leg B's low side carries it in reverse; leg A chops and its high-side diode
    returns the energy."""
    motor = BrushedDc(type="dc", kt=0.5, r=2.0)
    rpm, torque = 2000.0, -5.0
    current = 5.0 / 0.5
    back_emf = 0.5 * 2 * math.pi * rpm / 60
    duty = (back_emf - 2.0 * current) / V_REF
    point = at_speed_and_torque(igbt(), motor, rpm, torque, BASE)
    roles = by_name(point.result)

    assert roles["leg B low side"].diode.conduction == pytest.approx(current * (VF0 + RF * current))
    assert roles["leg B low side"].diode.recovery == 0.0
    back = roles["leg A high side"]
    assert back.diode.conduction == pytest.approx(duty * current * (VF0 + RF * current))
    assert back.diode.recovery == pytest.approx(F_SW * K_RR * current)
    chop = roles["leg A low side"]
    assert chop.switch.conduction == pytest.approx((1 - duty) * current * (V0 + R * current))
    assert chop.switch.turn_on == pytest.approx(F_SW * K_ON * current)
    assert roles["leg B high side"].switch.total + roles["leg B high side"].diode.total == 0.0

    stage = point.stage
    assert stage.p_shaft < 0 and stage.p_electrical < 0
    assert stage.p_electrical == pytest.approx(stage.p_shaft + stage.p_motor_loss)
    assert any("returns energy" in n for n in point.result.notes)


def test_brushed_dc_runs_backwards_as_the_mirror_image() -> None:
    motor = BrushedDc(type="dc", kt=0.5, r=2.0)
    forward = by_name(at_speed_and_torque(igbt(), motor, 2000.0, 5.0, BASE).result)
    backward = by_name(at_speed_and_torque(igbt(), motor, -2000.0, -5.0, BASE).result)
    for side in ("high side", "low side"):
        assert backward[f"leg B {side}"].switch == forward[f"leg A {side}"].switch
        assert backward[f"leg A {side}"].diode == forward[f"leg B {side}"].diode


def test_brushed_dc_braking_near_standstill_takes_power_from_the_supply() -> None:
    motor = BrushedDc(type="dc", kt=0.5, r=2.0)
    point = at_speed_and_torque(igbt(), motor, 100.0, -5.0, BASE)
    assert point.stage.p_shaft < 0 < point.stage.p_electrical
    assert any("takes power from the supply" in n for n in point.result.notes)


def test_brushless_dc_braking() -> None:
    motor = Bldc(type="bldc", pole_pairs=4, kt=0.4, r=1.5)
    rpm, torque = 3000.0, -4.0
    current = 4.0 / 0.4
    duty = (0.4 * 2 * math.pi * rpm / 60 - 1.5 * current) / V_REF
    point = at_speed_and_torque(igbt(), motor, rpm, torque, BASE)
    roles = by_name(point.result)
    high, low = roles["high-side position"], roles["low-side position"]
    assert high.switch.total == 0.0
    assert high.diode.conduction == pytest.approx(duty * current * (VF0 + RF * current) / 3)
    assert high.diode.recovery == pytest.approx(F_SW * K_RR * current / 3)
    assert low.switch.conduction == pytest.approx((1 - duty) * current * (V0 + R * current) / 3)
    assert low.switch.turn_on == pytest.approx(F_SW * K_ON * current / 3)
    assert low.diode.conduction == pytest.approx(current * (VF0 + RF * current) / 3)
    assert low.diode.recovery == 0.0
    stage = point.stage
    assert stage.p_electrical < 0
    assert stage.p_electrical == pytest.approx(stage.p_shaft + stage.p_motor_loss)


def test_each_motor_type_has_its_usual_modulation() -> None:
    from motionsim.engine.modulation import Pwm
    from motionsim.motor import Induction, Pmsm, Stepper

    pmsm = Pmsm(pole_pairs=4, flux_linkage=0.1, l=0.008, rs=1.0)
    assert pmsm.default_pwm is Pwm.space_vector and pmsm.scheme(Pwm.space_vector) == "space-vector PWM"
    induction = Induction(type="induction", pole_pairs=2, rs=4, rr=3.5, lm=0.32, lls=0.015,
                          llr=0.015, i_magnetising=2.4)
    assert induction.default_pwm is Pwm.space_vector
    assert "trapezoidal" in Bldc(type="bldc", pole_pairs=4, kt=0.4, r=1.5).scheme(Pwm.sine)
    assert "H-bridge" in BrushedDc(type="dc", kt=0.5, r=2.0).scheme(Pwm.sine)
    stepper = Stepper(type="stepper", i_phase=2, r=1, l=0.002, holding_torque=1)
    assert "microstepping" in stepper.scheme(Pwm.sine)


def test_bipolar_h_bridge_switches_all_four_positions() -> None:
    """Diagonal pair on for (1 + v/Vdc)/2 of each period, the other pair's diodes for the rest."""
    motor = BrushedDc(type="dc", kt=0.5, r=2.0, drive="bipolar")
    rpm, torque = 2000.0, 5.0
    current = torque / 0.5
    voltage = 0.5 * 2 * math.pi * rpm / 60 + 2.0 * current
    share = (1 + voltage / V_REF) / 2
    point = at_speed_and_torque(igbt(), motor, rpm, torque, BASE)
    roles = by_name(point.result)
    for name in ("leg A high side", "leg B low side"):
        assert roles[name].switch.conduction == pytest.approx(share * current * (V0 + R * current))
        assert roles[name].switch.turn_on == pytest.approx(F_SW * K_ON * current)
    for name in ("leg A low side", "leg B high side"):
        assert roles[name].diode.conduction == pytest.approx((1 - share) * current * (VF0 + RF * current))
        assert roles[name].diode.recovery == pytest.approx(F_SW * K_RR * current)
    unipolar = at_speed_and_torque(igbt(), BrushedDc(type="dc", kt=0.5, r=2.0), rpm, torque, BASE)

    def switching(result) -> float:
        return sum(x.switch.turn_on + x.switch.turn_off + x.diode.recovery for x in result.roles)

    assert switching(point.result) == pytest.approx(2 * switching(unipolar.result))
    assert point.stage.p_electrical == pytest.approx(point.stage.p_shaft + point.stage.p_motor_loss)


def test_modulation_recommendation_names_the_saving() -> None:
    from motionsim.recommend import modulation

    r = modulation({"space-vector": 30.0, "sine": 30.0, "discontinuous": 24.0}, "space-vector")
    assert r.value["saving"] == pytest.approx(6.0)
    assert any("20%" in text for text in r.lines) and any("noise" in text for text in r.lines)
    assert modulation({"space-vector": 30.0, "sine": 29.8}, "space-vector").value["saving"] == 0.0
    assert modulation({}, "sine").value == {}


@pytest.mark.parametrize("values", [
    dict(pole_pairs="abc", kv=100), dict(pole_pairs=None, kv=100), dict(pole_pairs=7, kv=0),
    dict(pole_pairs=7, kv="fast"), dict(pole_pairs=0, ke=10),
])
def test_bad_catalogue_values_are_refused_cleanly(values) -> None:
    from pydantic import ValidationError

    from motionsim.motor import Pmsm

    with pytest.raises(ValidationError):
        Pmsm(l=0.0001, rs=0.05, **values)


def test_stepper_power_balance_in_every_quadrant() -> None:
    """Electrical power is winding loss plus shaft power, whichever way it turns."""
    from motionsim.engine.modulation import Pwm
    from motionsim.motor import Stepper

    motor = Stepper(type="stepper", i_phase=2.8, r=0.9, l=0.0025, holding_torque=1.2)
    for rpm, torque in ((300, 0.8), (-300, -0.8), (300, -0.8), (-300, 0.8), (300, 0.0), (0, 0.8)):
        stage = motor.stage(rpm, torque, 48.0, Pwm.sine)
        shaft = torque * 2 * math.pi * rpm / 60
        assert stage.p_shaft == pytest.approx(shaft)
        assert stage.p_electrical == pytest.approx(0.9 * 2.8**2 + shaft, rel=1e-6)
    with pytest.raises(Unreachable, match="holding torque"):
        motor.stage(300, -5.0, 48.0, Pwm.sine)


def test_running_backwards_is_not_standing_still() -> None:
    """The output period follows the size of the speed, not its sign."""
    from motionsim.engine.modulation import Pwm
    from motionsim.motor import Induction, Pmsm

    pmsm = Pmsm(pole_pairs=4, flux_linkage=0.1, l=0.008, rs=1.0)
    assert pmsm.stage(-2000, -2.0, V_REF, Pwm.sine).period == pytest.approx(
        pmsm.stage(2000, 2.0, V_REF, Pwm.sine).period
    )
    induction = Induction(type="induction", pole_pairs=2, rs=4, rr=3.5, lm=0.32, lls=0.015,
                          llr=0.015, i_magnetising=2.4)
    assert induction.stage(-1400, -6.0, 540, Pwm.sine).period == pytest.approx(
        induction.stage(1400, 6.0, 540, Pwm.sine).period
    )


def test_an_idle_induction_motor_with_no_stator_resistance_stays_finite() -> None:
    from motionsim.engine.modulation import Pwm
    from motionsim.motor import Induction

    motor = Induction(type="induction", pole_pairs=2, rs=0, rr=3.5, lm=0.32, lls=0.015,
                      llr=0.015, i_magnetising=2.4)
    point = at_speed_and_torque(igbt(), motor, 0.0, 0.0, BASE)
    assert math.isfinite(point.result.p_inverter) and math.isfinite(point.stage.p_electrical)


def test_reluctance_motor_uses_least_current_then_trades_it_for_voltage() -> None:
    """T = 1.5 p (Ld - Lq) id iq. Least current has id = iq; short of voltage, id falls."""
    from motionsim.engine.modulation import Pwm
    from motionsim.motor import SynRm

    motor = SynRm(type="synrm", pole_pairs=2, ld=0.22, lq=0.045, rs=2.2)
    torque = 5.0
    i_axis = math.sqrt(torque / (1.5 * 2 * (0.22 - 0.045)))
    easy = motor.stage(1500, torque, 540, Pwm.space_vector)
    assert easy.i_peak == pytest.approx(math.sqrt(2) * i_axis, rel=1e-4)
    weak = motor.stage(3000, 3.0, 540, Pwm.space_vector)
    assert dict((a, b) for a, b, _ in weak.summary)["field weakening"] == 1.0
    assert weak.i_peak > math.sqrt(2) * math.sqrt(3.0 / (1.5 * 2 * (0.22 - 0.045)))
    for stage in (easy, weak, motor.stage(1500, -torque, 540, Pwm.space_vector), motor.stage(0, torque, 540, Pwm.space_vector)):
        assert stage.p_electrical == pytest.approx(stage.p_shaft + stage.p_motor_loss, abs=1e-6)
    with pytest.raises(Unreachable, match="any current angle"):
        motor.stage(9000, 5.0, 540, Pwm.space_vector)
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="larger than lq"):
        SynRm(type="synrm", pole_pairs=2, ld=0.04, lq=0.2, rs=1)


def test_series_wound_dc_torque_goes_with_current_squared() -> None:
    from motionsim.engine.modulation import Pwm
    from motionsim.motor import SeriesDc

    motor = SeriesDc(type="dc_series", k=0.004, r=0.25)
    one = motor.stage(3000, 1.0, 24.0, Pwm.sine)
    four = motor.stage(1000, 4.0, 24.0, Pwm.sine)
    assert four.i_peak == pytest.approx(2 * one.i_peak, rel=1e-4)
    current = math.sqrt(1.0 / 0.004)
    volts = 0.004 * current * 2 * math.pi * 3000 / 60 + 0.25 * current
    assert one.p_electrical == pytest.approx(volts * current)
    assert one.p_electrical == pytest.approx(one.p_shaft + one.p_motor_loss)
    with pytest.raises(Unreachable, match="cannot brake"):
        motor.stage(3000, -1.0, 24.0, Pwm.sine)


def test_inset_magnets_allow_a_little_saliency_and_surface_magnets_none() -> None:
    from pydantic import ValidationError

    from motionsim.motor import Pmsm

    assert Pmsm(pole_pairs=4, flux_linkage=0.1, ld=0.008, lq=0.009, rs=1, magnets="inset").lq > 0.008
    with pytest.raises(ValidationError, match="inset or interior"):
        Pmsm(pole_pairs=4, flux_linkage=0.1, ld=0.008, lq=0.009, rs=1, magnets="surface")
