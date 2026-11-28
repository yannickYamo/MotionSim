"""The stage between the mains and the DC link: each topology held to a closed form of the
textbooks, the closed forms to a count of the pulses, and the whole to the balance of power."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import motionsim
from motionsim import front_end as fe
from motionsim.device.io import load_device
from motionsim.engine.point import OperatingPoint
from motionsim.engine.solver import solve as solve_inverter
from motionsim.errors import Refusal
from motionsim.front_end import stage

ROOT = Path(motionsim.__file__).parent
ONE = fe.Mains(230.0, 50.0, 1)
THREE = fe.Mains(400.0, 50.0, 3)
OP = OperatingPoint(
    v_dc=390, i_rms=5, modulation_index=0.8, power_factor=0.9, f_sw=16e3, t_sink=60,
    v_drive=18, rg_on=10, rg_off=10, t_dead=200e-9,
)  # fmt: skip


@pytest.fixture(scope="module")
def sic():
    return load_device(ROOT / "example_sic.yaml")


@pytest.fixture(scope="module")
def igbt():
    return load_device(ROOT / "example_device.yaml")


def test_a_boost_stage_s_currents_are_the_textbook_s(sic) -> None:
    # With an inductor so large it has no ripple, a boost stage in continuous conduction has
    # (any text on power-factor correction): switch rms = I·sqrt(1 − 8√2·V/(3π·Vdc)), the
    # diode's mean = P/Vdc, the capacitor's current at twice the mains = P/(√2·Vdc).
    p, v_dc = 1500.0, 390.0
    shaped = stage._boost(ONE, v_dc, p, 65e3, sic, 1, 1.0)
    role = shaped.roles[0]
    i = p / ONE.v_rms
    switch = float(np.sqrt((role.current**2 * role.d_switch).mean()))
    assert switch == pytest.approx(i * np.sqrt(1 - 8 * np.sqrt(2) * ONE.v_rms / (3 * np.pi * v_dc)), rel=1e-4)
    diode_square = i**2 * 8 * np.sqrt(2) * ONE.v_rms / (3 * np.pi * v_dc)
    assert shaped.cap_rms == pytest.approx(np.sqrt(diode_square - (p / v_dc) ** 2), rel=1e-4)
    assert shaped.cap_slow == pytest.approx(p / (np.sqrt(2) * v_dc))
    assert shaped.i_line == pytest.approx(i)


def _pulses(mains, v_dc, p, f_sw, henry, cells):
    """One period of the mains counted pulse by pulse: each cell's inductor current as the
    triangle its switch draws, a carrier for each cell, 200 instants a switching period.
    Returns what the diodes give the link and one inductor's current, at each instant."""
    periods = round(f_sw / mains.f)
    fine = 200
    k = np.arange(periods * fine)
    t = (k + 0.5) / (periods * fine * mains.f)
    middle = (k // fine + 0.5) / (periods * mains.f)  # the duty is set once a switching period
    v_in = mains.peak * np.abs(np.sin(2 * np.pi * mains.f * middle))
    duty = np.clip(1 - v_in / v_dc, 0, 1)
    mean = np.sqrt(2) * p / mains.v_rms * np.abs(np.sin(2 * np.pi * mains.f * middle)) / cells
    swing = v_in * duty / (henry * f_sw)
    link = np.zeros_like(t)
    first = None
    for cell in range(cells):
        phase = ((k % fine + 0.5) / fine + cell / cells) % 1.0  # where the cell is in its period
        on = phase < duty
        # Rising while the switch is on, falling while the diode carries it, about the mean.
        rising = mean - swing / 2 + swing * phase / np.maximum(duty, 1e-12)
        falling = mean + swing / 2 - swing * (phase - duty) / np.maximum(1 - duty, 1e-12)
        current = np.where(on, rising, falling)
        link += np.where(on, 0.0, current)
        first = current if first is None else first
    return link, first, t


@pytest.mark.parametrize("cells", [1, 2])
def test_the_closed_forms_hold_to_a_count_of_the_pulses(sic, cells) -> None:
    p, v_dc, f_sw = 1500.0, 390.0, 20e3
    shaped = stage._boost(ONE, v_dc, p, f_sw, sic, cells, None)
    link, one, _ = _pulses(ONE, v_dc, p, f_sw, shaped.inductor.henry, cells)
    counted = float(np.sqrt((link**2).mean() - link.mean() ** 2))
    assert shaped.cap_rms == pytest.approx(counted, rel=0.01)
    assert link.mean() == pytest.approx(p / v_dc, rel=0.005)  # the diodes' mean is the link's current
    assert shaped.inductor.i_rms == pytest.approx(float(np.sqrt((one**2).mean())), rel=0.01)
    assert shaped.inductor.i_peak == pytest.approx(float(one.max()), rel=0.01)
    # The inductor is sized for the ripple asked for, at its worst instant.
    assert shaped.inductor.ripple == pytest.approx(stage.RIPPLE * np.sqrt(2) * p / ONE.v_rms / cells, rel=1e-6)


def test_two_cells_spare_the_capacitor(sic) -> None:
    one = stage._boost(ONE, 390.0, 1500.0, 65e3, sic, 1, None)
    two = stage._boost(ONE, 390.0, 1500.0, 65e3, sic, 2, None)
    assert two.cap_rms < 0.85 * one.cap_rms
    assert two.cap_slow == pytest.approx(one.cap_slow)  # what the mains' rhythm asks of it stays


@pytest.mark.parametrize("topology", ["boost", "interleaved", "totem_pole"])
def test_what_is_drawn_is_what_is_given_and_what_is_lost(sic, topology) -> None:
    r = fe.solve(sic, ONE, topology, 1500.0, OP)
    assert r.p_in == pytest.approx(r.p_link + r.p_switches + r.p_diodes, rel=1e-3)
    assert r.i_line == pytest.approx(r.p_in / ONE.v_rms, rel=1e-3)
    assert 0.97 < r.efficiency < 0.998
    assert r.stage is not None and r.stage.tj_switch_peak > OP.t_sink
    assert r.v_dc == 390.0 and r.f_sw == 65e3


def test_a_rectifier_s_real_power_is_the_load_s_and_its_current_is_poor() -> None:
    amps, volts = fe.rectified(ONE, 1500.0, 1.2e-3)
    theta = 2 * np.pi * (np.arange(amps.size) + 0.5) / amps.size
    assert float((ONE.peak * np.sin(theta) * amps).mean()) == pytest.approx(1500.0, rel=0.01)
    # The capacitor's voltage never passes the mains' peak and falls between two crests.
    assert volts.max() <= ONE.peak and volts.min() < 0.95 * ONE.peak
    r = fe.solve(None, ONE, "rectifier", 1500.0, OP)  # no switch in it: no part is needed
    assert r.capacitance_sized and r.v_ripple == pytest.approx(stage.SAG * ONE.peak, rel=0.02)
    assert 0.4 < r.power_factor < 0.7 and r.thd > 1.0
    assert r.within_limit is False
    third = next(h for h in r.harmonics if h.order == 3)
    assert third.limit == 2.30 and third.current > third.limit
    assert r.v_dc == pytest.approx(fe.link_voltage(ONE, "rectifier"), rel=0.02)


def test_a_small_rectifier_is_within_the_limit() -> None:
    assert fe.solve(None, ONE, "rectifier", 60.0, OP).within_limit is True


def test_a_six_pulse_rectifier_draws_blocks() -> None:
    r = fe.solve(None, THREE, "six_pulse", 5000.0, OP)
    assert r.v_dc == pytest.approx(1.3505 * 400.0, rel=1e-3)
    assert r.power_factor == pytest.approx(3 / np.pi)
    assert r.thd == pytest.approx(0.3108, rel=1e-3)
    fifth, seventh = (next(h for h in r.harmonics if h.order == n) for n in (5, 7))
    assert fifth.current / seventh.current == pytest.approx(7 / 5)
    assert [h.order for h in r.harmonics][:4] == [5, 7, 11, 13]
    # Real power: the fundamental, in phase, on three lines.
    first = fifth.current * 5
    assert np.sqrt(3) * 400.0 * first == pytest.approx(r.p_in * 540.2 / (540.2 - 2), rel=0.01)


def test_an_active_front_end_is_the_inverter_run_backwards(sic) -> None:
    r = fe.solve(sic, THREE, "active", 5000.0, OP, f_sw=20e3)
    index = 2 * np.sqrt(2) * THREE.v_phase / r.v_dc
    op = OperatingPoint(
        v_dc=r.v_dc, i_rms=r.i_line, modulation_index=index, power_factor=-1.0, f_sw=20e3, t_sink=60, f_out=50.0,
        v_drive=18, rg_on=10, rg_off=10, t_dead=200e-9, pwm=fe.stage.Pwm.space_vector,
    )  # fmt: skip
    assert r.p_switches == pytest.approx(solve_inverter(sic, op).p_inverter, rel=1e-3)
    assert r.p_diodes == 0.0 and r.cap_slow == 0.0 and r.cap_rms > 0


def test_a_vienna_rectifier_switches_half_the_link(sic) -> None:
    vienna = fe.solve(sic, THREE, "vienna", 5000.0, OP, f_sw=40e3)
    active = fe.solve(sic, THREE, "active", 5000.0, OP, f_sw=40e3)
    assert vienna.p_switches < 0.6 * active.p_switches
    assert vienna.inductor.henry < active.inductor.henry
    assert vienna.cap_rms is None and any("three levels" in n for n in vienna.notes)


def test_recovery_is_what_a_totem_pole_pays_for(sic) -> None:
    # The same part with a large reverse-recovery charge: the boost stage, which commutates
    # against a diode with none, loses what it lost; the totem-pole loses far more.
    charge = sic.switch.charge.model_copy(update={"q_rr": 2e-6})
    slow = sic.model_copy(update={"switch": sic.switch.model_copy(update={"charge": charge})})
    assert fe.solve(slow, ONE, "boost", 1500.0, OP).p_switches == pytest.approx(
        fe.solve(sic, ONE, "boost", 1500.0, OP).p_switches, rel=1e-6
    )
    quick, heavy = (fe.solve(d, ONE, "totem_pole", 1500.0, OP).p_switches for d in (sic, slow))
    assert heavy > 2.5 * quick
    assert fe.solve(sic, ONE, "totem_pole", 1500.0, OP).p_loss < fe.solve(sic, ONE, "boost", 1500.0, OP).p_loss


def test_the_link_stands_over_the_mains_peak() -> None:
    assert fe.link_voltage(ONE, "boost") == 390.0
    assert fe.link_voltage(fe.Mains(120.0, 60.0, 1), "totem_pole") == 200.0
    assert fe.link_voltage(THREE, "active") == 680.0
    # Asked for less than the stage can hold, it holds the least that clears the peak.
    assert fe.link_voltage(ONE, "boost", need=300.0) == 375.0
    assert fe.link_voltage(ONE, "boost", need=420.0) == 420.0


def test_what_cannot_be_is_refused_in_words(sic) -> None:
    with pytest.raises(Refusal, match="three phases"):
        fe.solve(sic, ONE, "vienna", 1000.0, OP)
    with pytest.raises(Refusal, match="one phase"):
        fe.solve(sic, THREE, "boost", 1000.0, OP)
    with pytest.raises(Refusal, match="above the mains' peak"):
        fe.solve(sic, ONE, "boost", 1000.0, OP, v_dc=300.0)
    with pytest.raises(Refusal, match="one of rectifier"):
        fe.solve(sic, ONE, "flyback", 1000.0, OP)
    with pytest.raises(Refusal, match="needs the part"):
        fe.solve(None, ONE, "boost", 1000.0, OP)
    with pytest.raises(Refusal, match="between 20 and 1000 V"):
        fe.Mains(5.0)


def test_an_igbt_has_its_own_usual_frequency(igbt, sic) -> None:
    assert fe.default_frequency(igbt, ONE) == 20e3 and fe.default_frequency(sic, ONE) == 65e3
    assert fe.default_frequency(igbt, THREE) == 16e3 and fe.default_frequency(sic, THREE) == 40e3
    assert fe.solve(igbt, ONE, "totem_pole", 1500.0, OP).p_switches > 0


def test_the_least_link_of_a_boost_stage_clears_a_mains_running_a_tenth_high() -> None:
    # A boost stage shapes the current only while the link stands over the mains' crest.
    for volts in (100.0, 120.0, 230.0, 240.0):
        mains = fe.Mains(volts, 50.0, 1)
        assert fe.link_voltage(mains, "boost", need=1.0) > 1.10 * mains.peak * 1.03
