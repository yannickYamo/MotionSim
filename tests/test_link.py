"""The DC-link capacitor's ripple current and the motor current's ripple, from the switching sequence."""

from __future__ import annotations

import math

import numpy as np
import pytest

from motionsim.engine.link import capacitor_ripple, legs_of, phase_ripple
from motionsim.engine.modulation import Pwm, Role, phase_leg_roles, waveform


@pytest.mark.parametrize("pwm", [Pwm.sine, Pwm.space_vector])
@pytest.mark.parametrize("m", [0.2, 0.5, 0.8, 1.0])
@pytest.mark.parametrize("pf", [1.0, 0.8, 0.3, -0.9])
def test_capacitor_ripple_matches_the_closed_form(pwm: Pwm, m: float, pf: float) -> None:
    """Level A: Kolar and Round's expression for a three-phase inverter with sinusoidal currents.
    It does not depend on the zero-sequence a scheme adds, so it holds for both."""
    i_rms = 10.0
    roles = phase_leg_roles(waveform(i_rms, m, pf, 2880, pwm), 6, pwm)
    found, mean = capacitor_ripple(roles)
    closed = i_rms * math.sqrt(2 * m * (math.sqrt(3) / (4 * math.pi) + pf**2 * (math.sqrt(3) / math.pi - 9 * m / 16)))
    assert found == pytest.approx(closed, rel=0.02)
    assert mean == pytest.approx(3 / 2 * m / 2 * math.sqrt(2) * i_rms * pf, rel=0.01)  # power balance: V_dc * I_dc = 3 V I cos(phi)


def _h_bridge(duty: float, current: float) -> list[Role]:
    n = np.ones(8)
    zero = 0 * n
    return [
        Role("leg A high side", 1, current * n, duty * n, zero, n, zero, leg="A"),
        Role("leg A low side", 1, current * n, zero, (1 - duty) * n, zero, n, leg="A"),
        Role("leg B high side", 1, zero, zero, zero, zero, zero, leg="B"),
        Role("leg B low side", 1, current * n, n, zero, zero, zero, leg="B"),
    ]


@pytest.mark.parametrize("duty", [0.1, 0.5, 0.75])
def test_an_h_bridge_chopping_one_leg(duty: float) -> None:
    """The link gives the motor current for the duty and nothing otherwise; the winding sees
    the supply for the duty and a short circuit otherwise."""
    current, v_dc, f_sw, winding = 8.0, 48.0, 20000.0, 400e-6
    roles = _h_bridge(duty, current)
    found, mean = capacitor_ripple(roles)
    assert mean == pytest.approx(duty * current)
    assert found == pytest.approx(current * math.sqrt(duty * (1 - duty)))
    pp = phase_ripple(roles, v_dc, f_sw, winding / 2)  # each half of the winding, to its mid point
    assert float(pp.max()) == pytest.approx(v_dc * duty * (1 - duty) / (winding * f_sw))


def test_three_phase_ripple_stays_under_one_legs_bound_and_grows_as_inductance_falls() -> None:
    v_dc, f_sw, l_phase = 48.0, 20000.0, 120e-6
    for pwm in (Pwm.sine, Pwm.space_vector, Pwm.discontinuous):
        for m in (0.1, 0.5, 0.9):
            pp = phase_ripple(phase_leg_roles(waveform(10.0, m, 0.9, 1440, pwm), 6, pwm), v_dc, f_sw, l_phase)
            assert 0 <= float(pp.max()) <= v_dc / (4 * l_phase * f_sw) * 1.001
    roles = phase_leg_roles(waveform(10.0, 0.6, 0.9, 1440, Pwm.space_vector), 6, Pwm.space_vector)
    assert phase_ripple(roles, v_dc, f_sw, 20e-6).max() == pytest.approx(6 * phase_ripple(roles, v_dc, f_sw, 120e-6).max())


def test_a_stage_whose_legs_cannot_be_told_apart_is_left_alone() -> None:
    one = np.ones(4)
    assert legs_of([Role("phase leg", 8, one, one, one, one, one)]) is None
