from __future__ import annotations

import math

import numpy as np
import pytest
from conftest import V_REF, line, linear_device

from motionsim.device import Topology
from motionsim.engine import OperatingPoint, Pwm, solve
from motionsim.engine.compare import compare, crossover, sweep_switching_frequency
from motionsim.engine.modulation import waveform


def device(v0=1.0, r=0.02, k=20e-6, **kw):
    return linear_device(
        sw_curves=[line(25.0, v0, r)],
        d_curves=[line(25.0, 1.0, 0.02)],
        k_on=k,
        k_off=k,
        k_rr=k / 4,
        **kw,
    )


def op(**kw) -> OperatingPoint:
    base = dict(v_dc=V_REF, i_rms=20.0, modulation_index=0.9, power_factor=1.0, f_sw=8000.0, t_sink=25.0)
    return OperatingPoint(**{**base, **kw})


@pytest.mark.parametrize("pwm", list(Pwm))
def test_every_scheme_delivers_the_same_fundamental_voltage(pwm: Pwm) -> None:
    w = waveform(10.0, 0.9, 0.8, 4096, pwm)
    fundamental = 2 * np.mean((2 * w.duty - 1) * np.sin(w.theta))
    assert fundamental == pytest.approx(0.9, abs=1e-3)


@pytest.mark.parametrize("pwm", [Pwm.third_harmonic, Pwm.space_vector])
def test_continuous_schemes_switch_as_often_as_sine(pwm: Pwm) -> None:
    assert solve(device(), op(pwm=pwm)).switch.turn_on == pytest.approx(solve(device(), op()).switch.turn_on, rel=1e-6)


def test_discontinuous_pwm_halves_switching_loss_at_unity_power_factor() -> None:
    """Each leg is held for 60 degrees around its current peak: the loss integral halves."""
    sine = solve(device(), op())
    held = solve(device(), op(pwm=Pwm.discontinuous))
    assert held.switch.turn_on == pytest.approx(0.5 * sine.switch.turn_on, rel=0.01)


def test_space_vector_reaches_beyond_sine_without_a_warning() -> None:
    r = solve(device(), op(pwm=Pwm.space_vector, modulation_index=1.1))
    assert not any("linear range" in n for n in r.notes)
    r = solve(device(), op(modulation_index=1.1))
    assert any("linear range" in n for n in r.notes)


def test_neighbour_heating_adds_to_every_junction() -> None:
    alone = device(topology=Topology.six_pack)
    coupled = device(topology=Topology.six_pack)
    coupled.package.rth_mutual = 0.3
    a, b = solve(alone, op()), solve(coupled, op())
    position = a.switch.total + a.diode.total
    expected = 0.3 * (6 * position - a.switch.total)
    assert b.tj_switch - a.tj_switch == pytest.approx(expected, rel=1e-6)
    assert a.assumptions == [] and b.assumptions == []  # the user gave the coupling both times


def test_compare_ranks_by_loss_and_finds_the_crossover() -> None:
    low_conduction = device(v0=0.8, r=0.01, k=60e-6)  # wins at low switching frequency
    low_switching = device(v0=1.4, r=0.03, k=10e-6)  # wins at high switching frequency
    low_conduction.part_number, low_switching.part_number = "A", "B"
    devices = [low_conduction, low_switching]

    assert compare(devices, op(f_sw=1000.0))[0].device.part_number == "A"
    assert compare(devices, op(f_sw=40000.0))[0].device.part_number == "B"

    frequencies = np.linspace(1000, 40000, 14)
    table = sweep_switching_frequency(devices, op(), frequencies)
    f_cross = crossover(frequencies, table[0], table[1])
    at_cross = [solve(d, op(f_sw=f_cross)).p_inverter for d in devices]
    assert at_cross[0] == pytest.approx(at_cross[1], rel=0.01)
    assert crossover(frequencies, table[0], table[0] + 1.0) is None
    assert math.isfinite(f_cross)
