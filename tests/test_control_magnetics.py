"""The saturating iron (control/magnetics.py) and the plant that carries it (control/plant.py).

The expected values are worked here from the definitions, not read from the code under test:
the linear limit is the constant-inductance machine; the calibration's three shares are
measured back from the map by solving it at the rated current; reciprocity and the energy
balance are checked by finite differences and by integration.
"""

from __future__ import annotations

import math

import pytest

from motionsim.control.magnetics import calibrated, kind_of, usual
from motionsim.control.plant import Machine, Plant

LD, LQ, PSI, I_R, P = 0.4e-3, 0.9e-3, 0.012, 20.0, 4


def test_with_no_saturation_the_map_is_the_linear_machine():
    m = calibrated(LD, LQ, PSI, I_R, 1.0, 1.0, 0.0)
    for i_d, i_q in ((0.0, 0.0), (-12.0, 30.0), (8.0, -5.0)):
        psi_d, psi_q = m.fluxes(i_d, i_q)
        assert psi_d == pytest.approx(PSI + LD * i_d, rel=1e-12)
        assert psi_q == pytest.approx(LQ * i_q, rel=1e-12, abs=1e-15)
        assert m.inductances(i_d, i_q) == pytest.approx((LD, 0.0, LQ), rel=1e-10, abs=1e-15)


def test_the_calibration_gives_back_its_three_shares_and_the_small_signal_inductances():
    d, q, x = 0.8, 0.65, 0.07
    m = calibrated(LD, LQ, PSI, I_R, d, q, x)
    psi_d, _ = m.fluxes(I_R, 0.0)
    assert (psi_d - PSI) / I_R == pytest.approx(d * LD, rel=1e-9)
    psi_d, psi_q = m.fluxes(0.0, I_R)
    assert psi_q / I_R == pytest.approx(q * LQ, rel=1e-9)
    assert psi_d == pytest.approx(PSI * (1.0 - x), rel=1e-9)
    l_dd, l_dq, l_qq = m.inductances(0.0, 0.0)
    assert (l_dd, l_qq) == pytest.approx((LD, LQ), rel=1e-9)
    assert l_dq == pytest.approx(0.0, abs=1e-15)


def test_the_map_is_reciprocal_so_its_torque_is_an_energy_s():
    m = calibrated(LD, LQ, PSI, I_R, 0.8, 0.65, 0.07)
    psi_d, psi_q, e = 0.011, 0.012, 1e-7
    did_dq = (m.currents(psi_d, psi_q + e)[0] - m.currents(psi_d, psi_q - e)[0]) / (2 * e)
    diq_dd = (m.currents(psi_d + e, psi_q)[1] - m.currents(psi_d - e, psi_q)[1]) / (2 * e)
    assert did_dq == pytest.approx(diq_dd, rel=1e-6)


def test_a_current_that_adds_to_the_magnet_meets_less_inductance_than_one_that_takes_from_it():
    m = usual("interior", LD, LQ, PSI, I_R)
    assert m.inductances(+0.5 * I_R, 0.0)[0] < m.inductances(-0.5 * I_R, 0.0)[0]


def test_under_load_the_q_inductance_and_the_magnet_flux_fall():
    m = usual("interior", LD, LQ, PSI, I_R)
    assert m.inductances(0.0, I_R)[2] < 0.8 * LQ
    assert m.fluxes(0.0, I_R)[0] < PSI


def test_shares_that_make_no_proper_energy_are_refused_in_words():
    with pytest.raises(ValueError, match="share"):
        calibrated(LD, LQ, PSI, I_R, 1.2, 0.7, 0.05)
    with pytest.raises(ValueError, match="share"):
        calibrated(LD, LQ, PSI, I_R, 0.9, 0.7, 0.6)
    with pytest.raises(ValueError, match="above nought"):
        calibrated(LD, LQ, -PSI, I_R, 0.9, 0.7, 0.05)


def test_the_kind_of_motor_is_read_from_its_saliency():
    assert kind_of(1e-3, 1.05e-3) == "surface" and kind_of(1e-3, 2e-3) == "interior"


def _driven(machine: Machine, v: tuple[float, float], steps: int, h: float) -> Plant:
    plant = Plant(machine, inertia=1e-4, held=True)
    plant.start(omega_m=200.0)
    for _ in range(steps):
        plant.advance(v[0], v[1], h)
    return plant


def test_a_plant_with_linear_iron_runs_as_the_constant_inductance_plant():
    linear = Machine(0.05, LD, LQ, PSI, P)
    mapped = Machine(0.05, LD, LQ, PSI, P, calibrated(LD, LQ, PSI, I_R, 1.0, 1.0, 0.0))
    a = _driven(linear, (6.0, 2.0), 400, 50e-6)
    b = _driven(mapped, (6.0, 2.0), 400, 50e-6)
    assert (b.i_d, b.i_q, b.torque) == pytest.approx((a.i_d, a.i_q, a.torque), rel=1e-9, abs=1e-9)


def test_the_energy_into_the_terminals_is_the_copper_loss_the_work_and_the_field_s():
    """Over a stretch with the speed held: ∫1.5·v·i dt = ∫1.5·Rs·|i|² dt + ∫Te·ωm dt + ΔW_field,
    where the field's energy is the line integral of 1.5·i·dψ, taken here along the path."""
    m = usual("interior", LD, LQ, PSI, I_R)
    plant = Plant(Machine(0.05, LD, LQ, PSI, P, m), inertia=1e-4, held=True)
    plant.start(omega_m=150.0)
    h, n = 2e-6, 3000
    into = copper = mech = field = 0.0
    for k in range(n):
        v_a, v_b = 18.0 * math.cos(2 * math.pi * 300 * k * h), 18.0 * math.sin(2 * math.pi * 300 * k * h)
        before = (plant.psi_d, plant.psi_q, plant.i_d, plant.i_q, plant.torque)
        plant.advance(v_a, v_b, h)
        into += plant.work
        i_d, i_q = 0.5 * (before[2] + plant.i_d), 0.5 * (before[3] + plant.i_q)
        copper += 1.5 * 0.05 * (i_d * i_d + i_q * i_q) * h
        mech += 0.5 * (before[4] + plant.torque) * 150.0 * h
        field += 1.5 * (i_d * (plant.psi_d - before[0]) + i_q * (plant.psi_q - before[1]))
    assert into == pytest.approx(copper + mech + field, rel=2e-3)


def test_the_saturating_plant_reaches_the_currents_its_map_gives_for_a_held_voltage():
    """At standstill a held voltage settles to i = v/R on each axis, whatever the iron."""
    m = usual("interior", LD, LQ, PSI, I_R)
    plant = Plant(Machine(0.05, LD, LQ, PSI, P, m), inertia=1e-4, held=True)
    plant.start()
    for _ in range(4000):
        plant.advance(0.5, 0.0, 50e-6)  # 0.5 V on the d axis (the rotor at angle nought)
    assert plant.i_d == pytest.approx(10.0, rel=1e-6)
    assert plant.i_q == pytest.approx(0.0, abs=1e-6)


def test_on_a_free_shaft_the_linear_plant_and_an_unsaturating_map_agree():
    """Two ways to step the same machine, under hard acceleration of a light shaft: the
    constant-inductance plant, and the flux-state plant with a map that does not saturate. The
    angle the shaft turns beyond the step's own must move the stator's flux, not merely turn the
    currents (the magnet's flux turns with the rotor); then the two agree."""
    ld, lq, psi, rs = 2e-4, 3e-4, 0.02, 0.05
    ends = []
    for machine in (
        Machine(rs, ld, lq, psi, P),
        Machine(rs, ld, lq, psi, P, calibrated(ld, lq, psi, 20.0, 1.0, 1.0, 0.0)),
    ):
        plant = Plant(machine, inertia=1e-5)
        plant.start(0.0, 10.0, 200.0, 0.3)
        for _ in range(2000):
            th = plant.theta
            plant.advance(-4.0 * math.sin(th), 4.0 * math.cos(th), 1e-4)
        ends.append((plant.i_d, plant.i_q, plant.w_m))
    assert ends[0] == pytest.approx(ends[1], rel=1e-7, abs=1e-8)
