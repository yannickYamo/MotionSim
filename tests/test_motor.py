from __future__ import annotations

import json
import math

import numpy as np
import pytest
from conftest import V_REF, line, linear_device
from test_mosfet import fet
from test_mosfet import op as fet_op

from motionsim.drivers import at_speed_and_torque, speed_torque_map
from motionsim.engine import OperatingPoint, solve
from motionsim.measured import DoublePulse, apply_double_pulse
from motionsim.motor import Motor, Pmsm, Unreachable, operating_state

SPM = Motor(pole_pairs=4, flux_linkage=0.1, ld=0.008, lq=0.008, rs=1.0)
IPM = Motor(pole_pairs=4, flux_linkage=0.1, ld=0.006, lq=0.015, rs=0.5)
SPM_MACHINE = Pmsm(pole_pairs=4, flux_linkage=0.1, ld=0.008, lq=0.008, rs=1.0)


def torque_of(m: Motor, i_d: float, i_q: float) -> float:
    return 1.5 * m.pole_pairs * (m.flux_linkage * i_q + (m.ld - m.lq) * i_d * i_q)


def test_surface_magnet_motor_uses_only_torque_current() -> None:
    s = operating_state(SPM, rpm=3000, torque=2.0, v_max=150.0)
    assert s.i_d == 0.0
    assert s.i_q == pytest.approx(2.0 / (1.5 * 4 * 0.1))
    w = 4 * 2 * math.pi * 3000 / 60
    assert s.v_q == pytest.approx(1.0 * s.i_q + w * 0.1)
    assert s.v_d == pytest.approx(-w * 0.008 * s.i_q)
    assert s.f_out == pytest.approx(200.0)
    assert not s.field_weakening


@pytest.mark.parametrize("motor", [SPM, IPM])
def test_electrical_power_equals_shaft_power_plus_copper_loss(motor: Motor) -> None:
    s = operating_state(motor, rpm=2000, torque=3.0, v_max=400.0)
    electrical = 3 * (s.v_peak / math.sqrt(2)) * s.i_rms * s.power_factor
    assert electrical == pytest.approx(s.p_shaft + s.p_copper, rel=1e-9)
    assert s.p_shaft == pytest.approx(3.0 * 2 * math.pi * 2000 / 60)


def test_salient_motor_takes_the_least_current_for_the_torque() -> None:
    s = operating_state(IPM, rpm=500, torque=4.0, v_max=400.0)
    assert s.i_d < 0  # reluctance torque is used
    assert torque_of(IPM, s.i_d, s.i_q) == pytest.approx(4.0, rel=1e-6)
    amplitude = math.hypot(s.i_d, s.i_q)
    for delta in (-0.3, 0.3):
        i_d = s.i_d + delta
        i_q = 4.0 / (1.5 * 4 * (0.1 + (0.006 - 0.015) * i_d))
        assert math.hypot(i_d, i_q) > amplitude


def test_field_weakening_holds_voltage_at_the_limit_and_keeps_the_torque() -> None:
    free = operating_state(SPM, rpm=6000, torque=1.0, v_max=1000.0)
    limited = operating_state(SPM, rpm=6000, torque=1.0, v_max=150.0)
    assert free.v_peak > 150.0 and limited.field_weakening
    assert limited.v_peak == pytest.approx(150.0, rel=1e-6)
    assert limited.i_d < 0
    assert torque_of(SPM, limited.i_d, limited.i_q) == pytest.approx(1.0, rel=1e-6)
    assert limited.i_rms > free.i_rms


def test_unreachable_points_are_refused() -> None:
    with pytest.raises(Unreachable, match="more voltage"):
        operating_state(SPM, rpm=30000, torque=1.0, v_max=150.0)
    capped = SPM.model_copy(update={"i_max": 2.0})
    with pytest.raises(Unreachable, match="above the motor's"):
        operating_state(capped, rpm=1000, torque=5.0, v_max=150.0)


def igbt():
    return linear_device(
        sw_curves=[line(25.0, 0.9, 0.03)], d_curves=[line(25.0, 1.0, 0.025)],
        k_on=20e-6, k_off=15e-6, k_rr=5e-6,
    )


BASE = OperatingPoint(
    v_dc=V_REF, i_rms=0.0, modulation_index=0.0, power_factor=1.0, f_sw=8000.0, t_sink=60.0
)


def test_motor_point_equals_the_engine_at_the_same_electrical_point() -> None:
    point = at_speed_and_torque(igbt(), SPM_MACHINE, 3000, 2.0, BASE)
    state = operating_state(SPM, 3000, 2.0, 150.0)
    direct = solve(igbt(), OperatingPoint(
        v_dc=V_REF, i_rms=state.i_rms, modulation_index=state.modulation_index(V_REF),
        power_factor=state.power_factor, f_sw=8000.0, t_sink=60.0, f_out=state.f_out, n_steps=1440,
    ))
    assert point.result.p_inverter == pytest.approx(direct.p_inverter, rel=1e-9)
    assert point.result.tj_switch_peak == pytest.approx(direct.tj_switch_peak, rel=1e-9)
    assert point.stage.p_electrical == pytest.approx(state.p_shaft + state.p_copper, rel=1e-9)
    assert 0 < point.system_efficiency < 1


def test_map_marks_what_the_motor_cannot_reach() -> None:
    m = speed_torque_map(
        igbt(), SPM_MACHINE, np.array([1000.0, 3000.0, 40000.0]), np.array([1.0, 3.0]), BASE
    )
    assert m.p_inverter.shape == (2, 3)
    assert np.isnan(m.p_inverter[:, 2]).all() and m.reason[0][2] == "motor"
    assert m.p_inverter[1, 0] > m.p_inverter[0, 0]  # more torque, more loss
    assert m.tj_peak[1, 1] > 60.0


def test_double_pulse_data_replaces_the_charge_estimate() -> None:
    data = DoublePulse.model_validate(json.loads(
        '{"v_dc": 300, "energy_unit": "uJ", "rg_on": 2.0, "points": ['
        '{"tj": 25, "current": 10, "e_on": 200, "e_off": 100},'
        '{"tj": 25, "current": 30, "e_on": 600, "e_off": 300}]}'
    ))
    device = apply_double_pulse(fet(), data, "dpt.json")
    assert device.switch.e_on.source.kind.value == "measured"
    assert device.switch.e_on.curves[0].current == [0.0, 10.0, 30.0]
    r = solve(device, fet_op(v_drive=None, rg_on=None, rg_off=None))
    i_pk = math.sqrt(2) * 20.0
    assert r.switch.turn_on == pytest.approx(50_000 * 20e-6 * i_pk / math.pi, rel=0.01)
    assert not any("gate and output charge" in n for n in r.notes)


def test_recovery_energy_goes_to_the_diode_and_is_refused_for_a_mosfet() -> None:
    data = DoublePulse.model_validate(
        {"v_dc": 300, "points": [{"tj": 25, "current": 10, "e_on": 2e-4, "e_off": 1e-4, "e_rr": 5e-5}]}
    )
    assert apply_double_pulse(igbt(), data).diode.e_rr.curves[0].value == [0.0, 5e-5]
    with pytest.raises(ValueError, match="part of its measured turn-on energy"):
        apply_double_pulse(fet(), data)
