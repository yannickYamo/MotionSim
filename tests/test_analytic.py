"""Level A verification: the engine against closed-form solutions.

For a device with V = V0 + r*I and E = k*I under sinusoidal PWM with a
sinusoidal current of peak Ipk, modulation index m and power factor cos(phi):

  switch conduction  V0*Ipk*(1/(2pi) + m*cos(phi)/8) + r*Ipk^2*(1/8 + m*cos(phi)/(3pi))
  diode conduction   V0*Ipk*(1/(2pi) - m*cos(phi)/8) + r*Ipk^2*(1/8 - m*cos(phi)/(3pi))
  switching          fsw * k * Ipk / pi * Vdc/Vref
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from conftest import V_REF, line, linear_device

from motionsim.device import FosterNetwork, Source, Topology
from motionsim.engine import OperatingPoint, ThermalRunaway, Validity, solve
from motionsim.engine.thermal import zth

V0_SW, R_SW = 0.9, 0.03
V0_D, R_D = 1.0, 0.025
K_ON, K_OFF, K_RR = 20e-6, 15e-6, 5e-6


def conduction(v0: float, r: float, i_pk: float, m: float, pf: float, sign: float) -> float:
    return v0 * i_pk * (1 / (2 * math.pi) + sign * m * pf / 8) + r * i_pk**2 * (1 / 8 + sign * m * pf / (3 * math.pi))


def temperature_independent_device(**kwargs):
    return linear_device(
        sw_curves=[line(25.0, V0_SW, R_SW)],
        d_curves=[line(25.0, V0_D, R_D)],
        k_on=K_ON,
        k_off=K_OFF,
        k_rr=K_RR,
        **kwargs,
    )


@pytest.mark.parametrize("m", [0.1, 0.6, 1.0])
@pytest.mark.parametrize("pf", [1.0, 0.8, 0.3, 0.0, -0.7])
def test_losses_match_closed_form(m: float, pf: float) -> None:
    i_rms, f_sw = 20.0, 8000.0
    i_pk = math.sqrt(2) * i_rms
    op = OperatingPoint(v_dc=V_REF, i_rms=i_rms, modulation_index=m, power_factor=pf, f_sw=f_sw, t_sink=25.0)
    r = solve(temperature_independent_device(), op)

    assert r.switch.conduction == pytest.approx(conduction(V0_SW, R_SW, i_pk, m, pf, +1), rel=0.01)
    assert r.diode.conduction == pytest.approx(conduction(V0_D, R_D, i_pk, m, pf, -1), rel=0.01)
    assert r.switch.turn_on == pytest.approx(f_sw * K_ON * i_pk / math.pi, rel=0.01)
    assert r.switch.turn_off == pytest.approx(f_sw * K_OFF * i_pk / math.pi, rel=0.01)
    assert r.diode.recovery == pytest.approx(f_sw * K_RR * i_pk / math.pi, rel=0.01)


def test_switching_energy_scales_with_dc_voltage_and_is_labelled() -> None:
    base = OperatingPoint(v_dc=V_REF, i_rms=20.0, modulation_index=0.8, power_factor=0.9, f_sw=8000.0, t_sink=25.0)
    scaled = OperatingPoint(**{**base.__dict__, "v_dc": 1.2 * V_REF})
    device = temperature_independent_device()
    r0, r1 = solve(device, base), solve(device, scaled)

    assert r1.switch.turn_on == pytest.approx(1.2 * r0.switch.turn_on)
    assert r1.switch.conduction == pytest.approx(r0.switch.conduction)
    assert not any("scaled linearly" in n for n in r0.notes)
    assert r1.validity is Validity.extrapolated
    assert any("scaled linearly" in n for n in r1.notes)


def test_single_temperature_data_used_hot_is_labelled() -> None:
    op = OperatingPoint(v_dc=V_REF, i_rms=20.0, modulation_index=0.8, power_factor=0.9, f_sw=8000.0, t_sink=80.0)
    r = solve(temperature_independent_device(), op)
    assert r.validity is Validity.extrapolated
    assert any("only characterised at 25 °C" in n for n in r.notes)


def test_current_above_data_is_labelled() -> None:
    op = OperatingPoint(v_dc=V_REF, i_rms=180.0, modulation_index=0.8, power_factor=0.9, f_sw=100.0, t_sink=25.0)
    r = solve(temperature_independent_device(rth_sw=0.01, rth_d=0.01), op)
    assert r.validity is Validity.extrapolated
    assert any("above the data" in n for n in r.notes)


def test_steady_state_temperatures() -> None:
    rth_sw, rth_d, rth_cs, t_sink = 0.8, 1.5, 0.05, 60.0
    device = temperature_independent_device(rth_sw=rth_sw, rth_d=rth_d, rth_cs=rth_cs, topology=Topology.six_pack)
    op = OperatingPoint(
        v_dc=V_REF,
        i_rms=15.0,
        modulation_index=0.9,
        power_factor=0.85,
        f_sw=10000.0,
        t_sink=t_sink,
    )
    r = solve(device, op)

    assert r.p_inverter == pytest.approx(6 * (r.switch.total + r.diode.total))
    assert r.t_case == pytest.approx(t_sink + rth_cs * r.p_inverter)
    assert r.tj_switch == pytest.approx(r.t_case + rth_sw * r.switch.total)
    assert r.tj_diode == pytest.approx(r.t_case + rth_d * r.diode.total)


def test_self_consistent_temperature_matches_closed_form() -> None:
    """Switch with Vce = a + b*Tj and nothing else: Tj = (Ts + R*c*a) / (1 - R*c*b)."""
    a, b, rth, t_sink = 0.8, 0.004, 2.0, 40.0
    i_rms, m, pf = 20.0, 0.9, 0.8
    c = math.sqrt(2) * i_rms * (1 / (2 * math.pi) + m * pf / 8)
    device = linear_device(
        sw_curves=[line(25.0, a + 25 * b, 0.0), line(150.0, a + 150 * b, 0.0)],
        d_curves=[line(25.0, 0.0, 0.0)],
        rth_sw=rth,
    )
    op = OperatingPoint(v_dc=V_REF, i_rms=i_rms, modulation_index=m, power_factor=pf, f_sw=0.0, t_sink=t_sink)
    r = solve(device, op)

    expected = (t_sink + rth * c * a) / (1 - rth * c * b)
    assert r.converged
    assert r.tj_switch == pytest.approx(expected, rel=0.01)
    assert r.switch.conduction == pytest.approx(c * (a + b * expected), rel=0.01)


def test_thermal_runaway_is_reported() -> None:
    a, b, rth = 0.8, 0.05, 5.0  # rth * c * b > 1: no stable temperature exists
    device = linear_device(
        sw_curves=[line(25.0, a + 25 * b, 0.0), line(150.0, a + 150 * b, 0.0)],
        d_curves=[line(25.0, 0.0, 0.0)],
        rth_sw=rth,
    )
    op = OperatingPoint(v_dc=V_REF, i_rms=20.0, modulation_index=0.9, power_factor=0.8, f_sw=0.0, t_sink=40.0)
    with pytest.raises(ThermalRunaway):
        solve(device, op)


def test_foster_step_response() -> None:
    net = FosterNetwork(r=[0.2, 0.5], tau=[0.001, 0.1], source=Source(kind="synthetic"))
    assert zth(net, 0.0) == pytest.approx(0.0)
    assert zth(net, 1e6) == pytest.approx(net.rth)
    expected = 0.2 * (1 - math.exp(-10)) + 0.5 * (1 - math.exp(-0.1))
    assert zth(net, 0.01) == pytest.approx(expected)
    assert np.all(np.diff(zth(net, np.logspace(-5, 1, 50))) >= 0)


def test_operating_entirely_below_the_data_is_labelled() -> None:
    from motionsim.device import Curve

    device = temperature_independent_device(rth_sw=0.01, rth_d=0.01)
    device.switch.e_on.curves = [Curve(tj=25.0, current=[0.0, 20.0, 100.0], value=[0.0, 4e-4, 2e-3])]
    low = OperatingPoint(v_dc=V_REF, i_rms=5.0, modulation_index=0.8, power_factor=0.9, f_sw=8000.0, t_sink=25.0)
    assert any("below the lowest data point (20 A)" in n for n in solve(device, low).notes)
    high = OperatingPoint(**{**low.__dict__, "i_rms": 30.0})
    assert not any("below the lowest data point" in n for n in solve(device, high).notes)


@pytest.mark.parametrize(
    ("topology", "share"),
    [
        (Topology.half_bridge, 1 / 3),
        (Topology.h_bridge, 2 / 3),
        (Topology.six_pack, 1.0),
    ],
)
def test_the_busiest_package_carries_its_share_of_the_whole_loss(topology: Topology, share: float) -> None:
    """Three legs on two-leg modules: a module cannot hold a leg and a half, so one holds
    two legs and two thirds of the loss."""
    rth_cs = 0.2
    device = temperature_independent_device(rth_cs=rth_cs, topology=topology)
    device.package.rth_mutual = 0.0
    op = OperatingPoint(v_dc=V_REF, i_rms=15.0, modulation_index=0.9, power_factor=0.85, f_sw=10000.0, t_sink=60.0)
    r = solve(device, op)
    assert r.t_case == pytest.approx(60.0 + rth_cs * r.p_inverter * share)


def test_package_share_counts_whole_legs() -> None:
    from motionsim.engine.solver import _package_share

    assert _package_share(6, 2) == pytest.approx(1 / 3)  # three half-bridges
    assert _package_share(6, 4) == pytest.approx(4 / 6)  # two-leg modules: 2 legs + 1 leg
    assert _package_share(8, 6) == pytest.approx(4 / 8)  # stepper on six-packs: 2 + 2 legs
    assert _package_share(4, 6) == 1.0  # an H-bridge inside one six-pack
    assert _package_share(8, 4) == pytest.approx(1 / 2)


@pytest.mark.parametrize("pf", [1.0, 0.6, -0.9])
def test_clamping_to_one_rail_loads_the_two_sides_differently_but_not_the_total(pf: float) -> None:
    """Clamping every leg to the positive rail or to the negative one are mirror images:
    the totals must be equal, and what the high side does in one the low side does in the other."""
    from motionsim.engine import Pwm

    device = temperature_independent_device()

    def run(pwm):
        return solve(
            device,
            OperatingPoint(
                v_dc=V_REF,
                i_rms=15.0,
                modulation_index=0.9,
                power_factor=pf,
                f_sw=16000.0,
                t_sink=25.0,
                pwm=pwm,
            ),
        )

    high, low = run(Pwm.discontinuous_high), run(Pwm.discontinuous_low)
    assert high.p_inverter == pytest.approx(low.p_inverter, rel=1e-3)
    by = lambda r: {x.name: x.switch.total + x.diode.total for x in r.roles}
    assert by(high)["high-side position"] == pytest.approx(by(low)["low-side position"], rel=1e-3)
    assert by(high)["high-side position"] != pytest.approx(by(high)["low-side position"], rel=0.02)
    # Each switch still rests for a third of the period, so the total sits below
    # space-vector PWM, which never rests.
    assert high.p_inverter < run(Pwm.space_vector).p_inverter


def test_output_power_stops_at_what_the_stage_can_deliver() -> None:
    device = temperature_independent_device()
    base = dict(v_dc=V_REF, i_rms=10.0, f_sw=8000.0, t_sink=25.0)
    at_limit = solve(device, OperatingPoint(modulation_index=1.0, power_factor=1.0, **base))
    beyond = solve(device, OperatingPoint(modulation_index=1.5, power_factor=1.0, **base))
    assert beyond.p_out == pytest.approx(at_limit.p_out)


def test_a_stopped_output_is_solved_not_divided_by() -> None:
    device = temperature_independent_device()
    r = solve(
        device,
        OperatingPoint(
            v_dc=V_REF,
            i_rms=10.0,
            modulation_index=0.1,
            power_factor=1.0,
            f_sw=8000.0,
            t_sink=25.0,
            f_out=0.0,
        ),
    )
    assert math.isfinite(r.tj_switch_peak)


def test_a_package_holds_its_own_leg_and_the_hottest_of_the_others() -> None:
    """Legs that do different work lose differently, and a leg's package is heated by what
    that leg loses, not by the mean of the stage."""
    import numpy as np

    from motionsim.engine.modulation import Role
    from motionsim.engine.solver import _package_losses

    one = np.ones(4)
    chop = [
        Role("leg A high", 1, one, one, one, one, one, leg="A"),
        Role("leg A low", 1, one, one, one, one, one, leg="A"),
    ]
    hold = [
        Role("leg B high", 1, one, one, one, one, one, leg="B"),
        Role("leg B low", 1, one, one, one, one, one, leg="B"),
    ]
    each = [10.0, 4.0, 3.0, 1.0]
    # A leg a package: each package carries its own leg.
    assert _package_losses(chop + hold, each, 1) == [14.0, 14.0, 4.0, 4.0]
    # Both legs in one package: all of it.
    assert _package_losses(chop + hold, each, 2) == [18.0, 18.0, 18.0, 18.0]
    # Legs that are not told apart share alike, as in a three-phase inverter.
    alike = [Role("high", 3, one, one, one, one, one), Role("low", 3, one, one, one, one, one)]
    assert _package_losses(alike, [5.0, 3.0], 1) == pytest.approx([8.0, 8.0])
    assert _package_losses(alike, [5.0, 3.0], 2) == pytest.approx([16.0, 16.0])
    assert _package_losses(alike, [5.0, 3.0], 3) == pytest.approx([24.0, 24.0])


def test_a_stalled_discrete_switch_heats_its_case_with_its_worst_position() -> None:
    """Held at one rotor position, a switch in its own package loses the same all the time.
    Its case sits at what the worst position loses, not at the mean of a turn."""
    rth_cs = 0.5
    device = temperature_independent_device(rth_cs=rth_cs, topology=Topology.discrete)
    turning = OperatingPoint(
        v_dc=V_REF,
        i_rms=15.0,
        modulation_index=0.05,
        power_factor=1.0,
        f_sw=10000.0,
        t_sink=60.0,
        f_out=50.0,
    )
    stalled = OperatingPoint(**{**turning.__dict__, "f_out": 0.0})
    moving, held = solve(device, turning), solve(device, stalled)
    role = max(held.roles, key=lambda r: r.t_case)
    worst = float((role.p_switch + role.p_diode).max())
    assert role.t_case == pytest.approx(60.0 + rth_cs * worst)
    assert worst > 1.3 * (role.switch.total + role.diode.total)  # the peak of a turn against its mean
    assert held.t_case > moving.t_case
    # In a module the whole bridge shares the case, and its loss does not depend on the position.
    module = temperature_independent_device(rth_cs=rth_cs, topology=Topology.six_pack)
    module.package.rth_mutual = 0.0
    assert solve(module, stalled).t_case == pytest.approx(solve(module, turning).t_case)


def test_devices_in_parallel_each_carry_their_share() -> None:
    """Two devices in parallel at 30 A are two stages of one device at 15 A: each device's
    loss and temperature are those of the half current, and the stage loses twice that."""
    from dataclasses import replace

    device = temperature_independent_device(rth_cs=0.3, topology=Topology.discrete)
    op = OperatingPoint(v_dc=V_REF, i_rms=30.0, modulation_index=0.9, power_factor=0.85, f_sw=10000.0, t_sink=60.0)
    pair = solve(device, replace(op, parallel=2))
    half = solve(device, replace(op, i_rms=15.0))
    assert pair.p_inverter == pytest.approx(2 * half.p_inverter)
    assert pair.tj_switch_peak == pytest.approx(half.tj_switch_peak)
    assert pair.switch.conduction == pytest.approx(half.switch.conduction)
    assert pair.tj_peak_range == pytest.approx(half.tj_peak_range) if half.tj_peak_range else True
    assert any("in parallel" in n for n in pair.notes)
    # Two share the conduction loss of one unevenly with current: less than one device alone.
    assert pair.p_inverter < solve(device, op).p_inverter


def test_thermal_cycling_life_counts_swings_and_adds_their_damage() -> None:
    import numpy as np

    from motionsim.lifetime import cycles_to_failure, estimate, rainflow

    # One swing of 60 K about 90 °C a motion: the life is the model's own number for it.
    one = np.array([60.0, 120.0, 60.0])
    assert estimate(one).repeats == pytest.approx(cycles_to_failure(60.0, 90.0))
    # The model's known shape: a swing twice as large lasts about 33 times fewer cycles.
    assert cycles_to_failure(30.0, 90.0) / cycles_to_failure(60.0, 90.0) == pytest.approx(2**5.039)
    # A large swing with two small ones riding on it: three swings, the large one found whole.
    trace = np.array([40.0, 100.0, 90.0, 110.0, 95.0, 120.0, 40.0])
    sizes = sorted(round(s) for s, _, c in rainflow(trace) for _ in range(int(2 * c)))
    assert max(sizes) == 80 and estimate(trace).swing == pytest.approx(80.0)
    assert estimate(trace).repeats < cycles_to_failure(80.0, 80.0)  # the small ones add a little
    assert estimate(trace).swing_share > 0.9
    # A flat trace wears nothing out.
    assert estimate(np.full(10, 80.0)).repeats == float("inf")


def test_switching_energy_follows_the_gate_resistor_along_the_datasheets_figure() -> None:
    from dataclasses import replace

    from motionsim.engine.losses import gate_factor

    device = temperature_independent_device()
    op = OperatingPoint(v_dc=V_REF, i_rms=15.0, modulation_index=0.9, power_factor=0.85, f_sw=10000.0, t_sink=60.0)
    base = solve(device, op)
    device.switch.e_on = device.switch.e_on.model_copy(
        update={"rg": 10.0, "rg_values": [5.0, 10.0, 40.0], "rg_factor": [0.8, 1.0, 2.2]}
    )
    assert gate_factor(device.switch.e_on, None) == 1.0 and gate_factor(device.switch.e_on, 10.0) == 1.0
    assert gate_factor(device.switch.e_on, 25.0) == pytest.approx(1.6)
    assert gate_factor(device.switch.e_on, 100.0) == 2.2  # the end of the figure, not beyond it
    # No resistor given: the datasheet's own. A resistor given: turn-on follows, turn-off does not.
    assert solve(device, op).switch.turn_on == pytest.approx(base.switch.turn_on)
    slow = solve(device, replace(op, rg_on=40.0, rg_off=40.0))
    assert slow.switch.turn_on == pytest.approx(2.2 * base.switch.turn_on)
    assert slow.switch.turn_off == pytest.approx(base.switch.turn_off)


def test_devices_in_parallel_share_as_unevenly_as_the_datasheet_allows() -> None:
    """With a maximum 1.5 times the typical drop, the typical part of a pair carries 60% of
    the current: its temperature is that of 60%, and the stage loses what 60% and 40% lose."""
    from dataclasses import replace

    device = temperature_independent_device(rth_cs=0.3, topology=Topology.discrete)
    op = OperatingPoint(v_dc=V_REF, i_rms=30.0, modulation_index=0.9, power_factor=0.85, f_sw=10000.0, t_sink=60.0)
    equal = solve(device, replace(op, parallel=2))
    device.switch.conduction = device.switch.conduction.model_copy(update={"spread": 1.5})
    uneven = solve(device, replace(op, parallel=2))
    hot = solve(device, replace(op, i_rms=0.6 * 30.0))
    cold = solve(device, replace(op, i_rms=0.4 * 30.0))
    assert uneven.tj_switch_peak == pytest.approx(hot.tj_switch_peak)
    assert uneven.p_inverter == pytest.approx(hot.p_inverter + cold.p_inverter)
    assert uneven.tj_switch_peak > equal.tj_switch_peak
    assert any("60% of the current" in n for n in uneven.notes)
