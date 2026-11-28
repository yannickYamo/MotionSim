"""The motor of the control lab on its own, against what its equations give by hand."""

from __future__ import annotations

import math

import pytest

from motionsim.control.plant import Machine, Plant, simple_load

MACHINE = Machine(rs=0.5, ld=2e-3, lq=3e-3, psi=0.08, pole_pairs=4)


def test_a_voltage_step_on_a_still_rotor_rises_with_the_time_constant_l_over_r() -> None:
    plant = Plant(MACHINE, held=True)
    plant.start()
    volts, tau = 6.0, MACHINE.ld / MACHINE.rs
    # With the rotor at angle nought the stator's first axis is the d axis.
    for _ in range(40):
        plant.advance(volts, 0.0, tau / 40)
    assert plant.i_d == pytest.approx(volts / MACHINE.rs * (1 - math.exp(-1.0)), rel=1e-6)
    assert plant.i_q == pytest.approx(0.0, abs=1e-12)
    for _ in range(160):
        plant.advance(volts, 0.0, tau / 40)
    assert plant.i_d == pytest.approx(volts / MACHINE.rs * (1 - math.exp(-5.0)), rel=1e-6)
    # The q axis has its own inductance: the second axis of the stator at angle nought.
    # Taken in one stretch a whole time constant long, the plant divides it for itself.
    plant.start()
    plant.advance(0.0, volts, MACHINE.lq / MACHINE.rs)
    assert plant.i_q == pytest.approx(volts / MACHINE.rs * (1 - math.exp(-1.0)), rel=1e-4)


def test_the_back_emf_is_the_speed_times_the_flux() -> None:
    w_m = 150.0
    w_e = MACHINE.pole_pairs * w_m
    plant = Plant(MACHINE, held=True)
    plant.start(omega_m=w_m)
    # No current and no voltage: the only thing that moves the q-axis current is the back-EMF.
    h = 1e-7
    plant.advance(0.0, 0.0, h)
    assert plant.i_q / h == pytest.approx(-w_e * MACHINE.psi / MACHINE.lq, rel=1e-4)
    # Shorted and left to settle, the currents are those of the back-EMF across the windings.
    for _ in range(4000):
        plant.advance(0.0, 0.0, 2e-5)
    r, ld, lq, psi = MACHINE.rs, MACHINE.ld, MACHINE.lq, MACHINE.psi
    across = r * r + w_e * w_e * ld * lq
    assert plant.i_d == pytest.approx(-w_e * w_e * lq * psi / across, rel=1e-6)
    assert plant.i_q == pytest.approx(-r * w_e * psi / across, rel=1e-6)


def test_the_torque_is_the_magnets_and_the_reluctance_torque() -> None:
    plant = Plant(MACHINE, held=True)
    plant.start(i_d=-5.0, i_q=12.0)
    # 1.5 · 4 · (0.08·12 + (0.002 − 0.003)·(−5)·12) = 6 · (0.96 + 0.06)
    assert plant.torque == pytest.approx(6.12)
    assert MACHINE.torque(-5.0, 12.0) == pytest.approx(6.12)
    a, b, c = plant.phase_currents()
    assert (a, a + b + c) == pytest.approx((-5.0, 0.0), abs=1e-12)
    # A quarter of a turn on, the q axis lies where phase a points backwards.
    plant.start(i_d=0.0, i_q=12.0, theta=math.pi / 2)
    assert plant.phase_currents()[0] == pytest.approx(-12.0)


def test_the_energy_put_in_is_the_heat_the_field_the_motion_and_the_load() -> None:
    inertia = 2e-4
    load = simple_load(constant=0.3, viscous=2e-3, quadratic=1e-5, still=0.5)
    plant = Plant(MACHINE, inertia, load)
    plant.start()
    h, f_turn = 2e-6, 40.0
    electrical = heat = work = 0.0
    for k in range(60_000):
        # A voltage that turns, stepped as a stage would step it, its size rising.
        t = k * h
        size = min(40.0, 400.0 * t + 4.0)
        angle = 2 * math.pi * f_turn * (math.floor(t * 5000) / 5000)
        va, vb = size * math.cos(angle), size * math.sin(angle)
        before = (plant.i_d, plant.i_q, plant.cos, plant.sin, plant.w_m, load(plant.w_m, 0.0, t))
        plant.advance(va, vb, h)
        both = []
        for i_d, i_q, c, s in (before[:4], (plant.i_d, plant.i_q, plant.cos, plant.sin)):
            both.append(
                (1.5 * (va * (i_d * c - i_q * s) + vb * (i_d * s + i_q * c)), 1.5 * MACHINE.rs * (i_d**2 + i_q**2))
            )
        electrical += 0.5 * (both[0][0] + both[1][0]) * h
        heat += 0.5 * (both[0][1] + both[1][1]) * h
        work += 0.5 * (before[5] * before[4] + load(plant.w_m, 0.0, t) * plant.w_m) * h
    field = 0.75 * (MACHINE.ld * plant.i_d**2 + MACHINE.lq * plant.i_q**2)
    motion = 0.5 * inertia * plant.w_m**2
    assert plant.w_m > 20.0 and heat > 0.1 * electrical  # the run did turn the shaft and warm the windings
    assert heat + field + motion + work == pytest.approx(electrical, rel=0.005)


def test_a_load_is_constant_viscous_and_quadratic_and_opposes_the_motion() -> None:
    load = simple_load(constant=1.0, viscous=0.1, quadratic=0.01, still=1e-3)
    assert load(10.0, 0.0, 0.0) == pytest.approx(1.0 + 1.0 + 1.0)
    assert load(-10.0, 0.0, 0.0) == pytest.approx(-3.0)
    assert load(0.0, 0.0, 0.0) == 0.0
