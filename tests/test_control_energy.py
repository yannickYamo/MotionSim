"""The power into the motor's terminals, where the rotor turns a large angle in one stretch of
constant voltage: the energy the kernel gathers is the heat, the field and the shaft's work,
on a motor whose two axes differ, at ten switching periods a turn."""

from __future__ import annotations

import math

import pytest
from test_control_bench import BURIED, SALIENT, design, machine_of

from motionsim.control import Inverter, Kernel, Plant, Trial, compile_scheme, context
from motionsim.control.presets import BUILDERS

RATIO = 10.0


def low_ratio(rpm: float = 3000.0, torque: float = 12.0):
    """The made-up salient machine with the carrier at ten periods a turn of the output."""
    f_out = abs(rpm) / 60.0 * SALIENT.pole_pairs
    return design(SALIENT, rpm=rpm, torque=torque, i_design=20.0, f_sw=RATIO * f_out, v_dc=320.0, i_limit=60.0)


def test_one_long_stretch_gathers_the_energy_of_the_same_stretch_taken_in_a_thousand() -> None:
    # A voltage that stands still in the stator's frame while the rotor turns 36° under it:
    # the current's vector turns with the rotor, and the power is not a straight line between
    # the stretch's two ends. Taken in a thousand short stretches a straight line is exact.
    d = low_ratio()
    scheme = BUILDERS["foc_torque"](d)
    ts = 1.0 / d.f_sw
    gathered = []
    for pieces in (1, 1000):
        ctx = context(d, scheme)
        plant = Plant(machine_of(d), 1.0, held=True)
        k = Kernel(compile_scheme(scheme, ctx), ctx, plant, Inverter("averaged"), Trial(duration=1.0))
        plant.start(i_d=-12.0, i_q=25.0, omega_m=d.omega, theta=0.3)
        k.ia, k.ib, k.ic = plant.phase_currents()
        k.gather = True
        for _ in range(pieces):
            k._advance(110.0, -60.0, ts / pieces, -1)
        gathered.append(k.energy)
    assert d.omega * d.pole_pairs * ts == pytest.approx(math.radians(36.0))
    assert abs(gathered[0]) > 0.05  # joules: a stretch that carries real power
    # The plant takes the long stretch in two steps of 18° each: fourth-order steps that size
    # are good to two parts in ten thousand. (A straight line between the two ends gave 0.127 J
    # of these 0.443 J.)
    assert gathered[0] == pytest.approx(gathered[1], rel=5e-4)
    assert gathered[1] == pytest.approx(0.4425, rel=1e-3)


class Watched(Plant):
    """The plant, with the heat and the shaft's work read as it goes by the motor's own
    equations: every stretch the kernel asks is taken in twenty, so that between two readings
    the currents seen from the rotor are a straight line however far the rotor turns in the
    stretch. The kernel still sees one stretch and its two ends."""

    def begin(self, machine) -> None:
        self.rs, self.heat, self.shaft = machine.rs, 0.0, 0.0

    def advance(self, v_alpha: float, v_beta: float, h: float) -> None:
        work, piece = 0.0, h / 20.0
        for _ in range(20):
            d0, q0, t0 = self.i_d, self.i_q, self.torque
            super().advance(v_alpha, v_beta, piece)
            d1, q1 = self.i_d, self.i_q
            self.heat += 1.5 * self.rs * piece * (d0 * d0 + d0 * d1 + d1 * d1 + q0 * q0 + q0 * q1 + q1 * q1) / 3.0
            self.shaft += 0.5 * (t0 + self.torque) * piece * self.w_m
            work += self.work
        self.work = work


def balance(d, scheme_id: str, fidelity: str, turns: int = 40) -> tuple[float, float]:
    """A held speed under torque control: the energy the kernel gathered, and where it went
    by the motor's own equations."""
    scheme = BUILDERS[scheme_id](d)
    ctx = context(d, scheme)
    m = machine_of(d)
    plant = Watched(m, 1.0, held=True)
    plant.begin(m)
    test = Trial(
        duration=turns / d.f_out,
        speed=lambda t: d.omega,
        torque=lambda t: d.torque,
        initial={"omega_m": d.omega},
        trip=20.0 * d.limit,
    )
    trace = Kernel(compile_scheme(scheme, ctx), ctx, plant, Inverter(fidelity), test).run()
    field = 0.75 * (m.ld * plant.i_d**2 + m.lq * plant.i_q**2)
    return float(trace.energy.sum()), plant.heat + plant.shaft + field


@pytest.mark.parametrize("fidelity", ("averaged", "switched"))
def test_at_ten_periods_a_turn_the_energy_in_is_the_heat_the_field_and_the_shaft_s_work(fidelity) -> None:
    put_in, accounted = balance(low_ratio(), "foc_torque", fidelity)
    assert put_in > 500.0  # joules: the motor was driven at 12 N·m and 3000 rpm for a fifth of a second
    assert put_in == pytest.approx(accounted, rel=1e-3)


@pytest.mark.parametrize("fidelity", ("averaged", "switched"))
def test_the_balance_holds_deep_in_field_weakening_and_in_regeneration(fidelity) -> None:
    for d in (
        design(BURIED, rpm=9000, torque=2.0, i_design=20.0, f_sw=6000.0),
        low_ratio(torque=-12.0),
        low_ratio(rpm=-3000.0, torque=12.0),
    ):
        put_in, accounted = balance(d, "foc_torque", fidelity)
        assert put_in == pytest.approx(accounted, rel=1e-3), (d.rpm, d.torque)
