"""Motor models, first advice and ranking: figures and wording held to what the physics and the documents say."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import V_REF, line, linear_device
from pydantic import ValidationError

from motionsim import guard
from motionsim.advise import advise, motors_for
from motionsim.device import Topology, load_device
from motionsim.drivers import at_speed_and_torque
from motionsim.engine import OperatingPoint, Pwm
from motionsim.motor import Bldc, BrushedDc, Motor, SeriesDc, Stepper, Unreachable, operating_state
from motionsim.motor.machines import ADAPTER, at_temperature
from motionsim.propose import Candidate, explain, propose, requirements, switching_footing

SOURCE = Path(__file__).parent.parent / "src" / "motionsim"
BASE = OperatingPoint(v_dc=V_REF, i_rms=0.0, modulation_index=0.0, power_factor=1.0, f_sw=8000.0, t_sink=60.0)

INDUCTION = dict(type="induction", pole_pairs=2, rs=4.0, rr=3.5, lm=0.32, lls=0.015, llr=0.015, i_magnetising=2.4)
SYNRM = dict(type="synrm", pole_pairs=2, ld=0.22, lq=0.045, rs=2.2)


def summary(stage) -> dict[str, float]:
    return {label: float(value) for label, value, _ in stage.summary}


def text(advice) -> str:
    return " ".join(advice.lines)


def igbt(name: str, v0: float, **more):
    d = linear_device(
        sw_curves=[line(25.0, v0, 0.03)],
        d_curves=[line(25.0, 1.0, 0.025)],
        k_on=20e-6,
        k_off=15e-6,
        k_rr=5e-6,
        **more,
    )
    d.part_number = name
    return d


# ---------- motors ----------


@pytest.mark.parametrize(("ld", "lq"), [(0.008, 0.008), (0.006, 0.015)])
def test_a_saturating_pmsm_settles_on_inductances_that_belong_to_its_own_currents(ld, lq) -> None:
    # vd = Rs*id - w*Lq*iq and vq = Rs*iq + w*(Ld*id + psi), with each inductance at the
    # value its own axis current gives it: L0 / sqrt(1 + (i / i_sat)^2).
    pairs, psi, rs, i_sat, rpm, torque = 4, 0.1, 1.0, 5.0, 1000.0, 4.8
    motor = Motor(pole_pairs=pairs, flux_linkage=psi, ld=ld, lq=lq, rs=rs, i_sat=i_sat)
    s = operating_state(motor, rpm, torque, 1e4)
    w = pairs * 2 * math.pi * rpm / 60
    lq_now = lq / math.sqrt(1 + (s.i_q / i_sat) ** 2)
    ld_now = ld / math.sqrt(1 + (s.i_d / i_sat) ** 2)
    assert abs(s.i_d) > 1.0  # the d axis carries current here, so its inductance is in play
    assert s.v_d == pytest.approx(rs * s.i_d - w * lq_now * s.i_q, rel=1e-5)
    assert s.v_q == pytest.approx(rs * s.i_q + w * (ld_now * s.i_d + psi), rel=1e-5)
    assert 1.5 * pairs * (psi + (ld_now - lq_now) * s.i_d) * s.i_q == pytest.approx(torque, rel=1e-5)


def test_a_hot_brushed_motor_needs_more_current_because_its_magnets_give_less() -> None:
    # 100 K above the catalogue temperature a neodymium magnet has lost 0.11% per kelvin.
    hot = at_temperature(BrushedDc(type="dc", kt=0.05, r=0.4), 125.0)
    weaker = 0.05 * (1 - 0.0011 * 100)
    stage = hot.stage(1000.0, 0.5, 24.0, Pwm.sine)
    assert summary(stage)["armature current"] == pytest.approx(0.5 / weaker)
    assert stage.p_motor_loss == pytest.approx(0.4 * (1 + 0.00393 * 100) * (0.5 / weaker) ** 2)
    assert "magnet flux 0.89 times" in hot.temperature_note


def test_a_hot_induction_motor_loses_more_in_its_rotor_as_well_as_its_stator() -> None:
    # Copper and aluminium both resist more when hot: 0.393% per kelvin on both resistances.
    hot = at_temperature(ADAPTER.validate_python(INDUCTION), 125.0)
    rise = 1 + 0.00393 * 100
    pairs, lm, lr, i_d, torque = 2, 0.32, 0.32 + 0.015, 2.4, 4.0
    i_q = torque / (1.5 * pairs * lm**2 / lr * i_d)
    stator = 1.5 * 4.0 * rise * (i_d**2 + i_q**2)
    rotor = 1.5 * 3.5 * rise * (lm / lr * i_q) ** 2
    stage = hot.stage(300.0, torque, 540.0, Pwm.space_vector)
    assert summary(stage)["field weakening"] == 0.0
    assert stage.p_motor_loss == pytest.approx(stator + rotor)


def test_an_induction_motor_ripples_against_its_leakage_not_its_magnetising_inductance() -> None:
    # The stator's transient inductance: Ls - Lm^2 / Lr.
    motor = ADAPTER.validate_python(INDUCTION)
    ls, lr = 0.32 + 0.015, 0.32 + 0.015
    stage = motor.stage(300.0, 4.0, 540.0, Pwm.space_vector)
    assert stage.l_phase == pytest.approx(ls - 0.32**2 / lr)
    assert stage.l_phase < 0.1 * 0.32


@pytest.mark.parametrize(("spec", "rpm", "torque"), [(INDUCTION, 1400.0, 8.0), (SYNRM, 1500.0, 6.0)])
def test_a_motor_weakens_its_field_to_fit_the_voltage_the_stage_really_gives(spec, rpm, torque) -> None:
    # Space-vector modulation reaches v_dc / sqrt(3) peak per phase; a stage that gives
    # three quarters of the ideal reaches three quarters of that.
    v_dc, usable = 540.0, 0.75
    ideal = ADAPTER.validate_python(spec)
    limit_rms = usable * v_dc / math.sqrt(3) / math.sqrt(2)
    unhindered = ideal.stage(rpm, torque, v_dc, Pwm.space_vector)
    assert summary(unhindered)["phase voltage"] > limit_rms and summary(unhindered)["field weakening"] == 0.0
    held = ideal.model_copy(update={"usable_voltage": usable}).stage(rpm, torque, v_dc, Pwm.space_vector)
    assert summary(held)["field weakening"] == 1.0
    assert summary(held)["phase voltage"] == pytest.approx(limit_rms, rel=1e-6)
    assert summary(held)["phase current"] > summary(unhindered)["phase current"]


def test_a_series_wound_motor_is_refused_a_negative_speed() -> None:
    motor = SeriesDc(type="dc_series", k=0.004, r=0.25)
    assert motor.stage(1000.0, 0.5, 24.0, Pwm.sine).p_shaft > 0
    with pytest.raises(Unreachable, match="turns one way"):
        motor.stage(-1000.0, 0.5, 24.0, Pwm.sine)


def test_a_series_motor_on_an_h_bridge_ripples_against_its_whole_winding() -> None:
    # One leg chops the link across the whole winding for a share d of the period:
    # the current swings V * d * (1 - d) / (L * f).
    k, r, inductance, v_dc, f_sw, rpm, torque = 0.004, 0.25, 0.0008, 24.0, 20000.0, 1500.0, 0.4
    motor = SeriesDc(type="dc_series", k=k, r=r, l=inductance)
    op = OperatingPoint(v_dc=v_dc, i_rms=0, modulation_index=0, power_factor=1, f_sw=f_sw, t_sink=40, t_dead=100e-9)
    op = replace(op, v_drive=10, rg_on=5, rg_off=3)
    p = at_speed_and_torque(load_device(SOURCE / "example_mosfet.yaml"), motor, rpm, torque, op)
    current = math.sqrt(torque / k)
    d = (k * current * rpm * math.pi / 30 + r * current) / v_dc
    assert p.ripple_pp == pytest.approx(v_dc * d * (1 - d) / (inductance * f_sw), rel=1e-6)


def test_interior_magnets_with_lq_below_ld_are_refused() -> None:
    motor = dict(type="pmsm", magnets="interior", pole_pairs=4, flux_linkage=0.1, ld=0.010, lq=0.005, rs=1.0)
    with pytest.raises(ValidationError, match="Lq is at least as large as Ld"):
        ADAPTER.validate_python(motor)
    assert ADAPTER.validate_python({**motor, "ld": 0.005, "lq": 0.010}).lq == 0.010


@pytest.mark.parametrize("torque", [0.9, -0.9])
def test_a_block_commutated_motor_holding_still_is_not_said_to_brake(torque) -> None:
    # Nothing turns, so no energy goes either way through the shaft: the link feeds the winding loss.
    motor = Bldc(type="bldc", pole_pairs=7, kt=0.09, r=0.08)
    stage = motor.stage(0.0, torque, 48.0, Pwm.sine)
    assert not [n for n in stage.notes if "braking" in n]
    assert stage.p_electrical == pytest.approx(0.08 * (0.9 / 0.09) ** 2)


def test_a_brushed_motor_is_held_to_its_current_limit_when_braking_too() -> None:
    motor = BrushedDc(type="dc", kt=0.05, r=0.4, i_max=20)
    assert motor.stage(3000.0, -0.9, 24.0, Pwm.sine).i_peak == pytest.approx(0.9 / 0.05)
    with pytest.raises(Unreachable, match="needs 30 A, above the 20 A limit"):
        motor.stage(3000.0, -1.5, 24.0, Pwm.sine)


def test_a_stepper_loses_i_squared_r_in_each_of_its_two_phases() -> None:
    # Two phases, each carrying a sine of amplitude I: rms I / sqrt(2) in each.
    i_phase, r = 2.8, 0.9
    motor = Stepper(type="stepper", i_phase=i_phase, r=r, l=0.0025, holding_torque=1.2)
    stage = motor.stage(120.0, 0.6, 48.0, Pwm.sine)
    assert stage.p_motor_loss == pytest.approx(2 * r * (i_phase / math.sqrt(2)) ** 2)


# ---------- first advice ----------


def test_the_igbt_crossover_is_one_and_a_half_volts_over_the_peak_current() -> None:
    # 5 N·m at 0.5 N·m/A is 10 A; a transistor drops less than 1.5 V there below 150 mΩ.
    a = advise(BrushedDc(type="dc", kt=0.5, r=2.0), 2000, 5.0, 300, 8e3)
    assert a.i_peak == pytest.approx(10.0)
    assert a.r_crossover == pytest.approx(1.5 / 10.0)
    assert "An IGBT drops about 1.5 V whatever the current." in text(a)
    assert "below about 150 mΩ" in text(a)


def test_a_supply_beyond_every_voltage_class_is_pointed_at_the_highest_one() -> None:
    a = advise(BrushedDc(type="dc", kt=0.5, r=2.0), 2000, 5.0, 1200, 8e3)
    # 1200 V at 80% of the rating asks for 1500 V, at 60% for 2000 V: only 1700 V parts are left.
    assert (a.v_minimum, a.v_comfortable) == (1700, 1700)
    assert "Voltage: 1700 V parts" in text(a)


def test_fast_switching_at_600_v_class_names_gan_and_the_20_khz_igbt_ceiling() -> None:
    a = advise(BrushedDc(type="dc", kt=0.5, r=2.0), 2000, 5.0, 300, 40e3)
    assert a.v_comfortable == 600
    assert "at 40 kHz switching loss leads, which favours silicon-carbide or GaN transistors." in text(a)
    assert "IGBTs are the low-cost choice up to about 20 kHz." in text(a)
    assert "silicon superjunction MOSFETs, take only types with a fast body diode" in text(a)


def test_fast_switching_at_1200_v_class_names_silicon_carbide_alone_and_the_16_khz_ceiling() -> None:
    a = advise(BrushedDc(type="dc", kt=0.5, r=2.0), 2000, 5.0, 600, 40e3)
    assert a.v_comfortable == 1200
    assert "which favours silicon-carbide MOSFETs." in text(a)
    assert "IGBTs are the low-cost choice up to about 16 kHz." in text(a)
    assert "superjunction" not in text(a) and "GaN" not in text(a)


def test_slow_switching_at_600_v_class_offers_gan_beside_silicon_carbide() -> None:
    a = advise(BrushedDc(type="dc", kt=0.5, r=2.0), 2000, 5.0, 300, 8e3)
    assert "Silicon-carbide or GaN transistors lose less" in text(a)


def test_advice_leaves_out_standstill_when_the_torque_cannot_be_held_there() -> None:
    # Braking 10 N·m at 0.5 N·m/A is 20 A through 2 Ω: 40 V. Turning, the back-EMF of
    # 0.5 V·s x 60 rad/s takes 30 V of it and 24 V is enough; standing still it is not.
    motor = BrushedDc(type="dc", kt=0.5, r=2.0)
    rpm = 60 * 30 / math.pi
    with pytest.raises(Unreachable):
        motor.stage(0.0, -10.0, 24.0, Pwm.sine)
    a = advise(motor, rpm, -10.0, 24, 20e3)
    assert a.i_stall is None
    assert "Current: 20 A peak at the design point. Start with devices rated for 40 A or more" in text(a)


def test_a_250_v_device_suits_a_150_v_supply_which_is_mains_level_and_still_low_for_wound_motors() -> None:
    # Two thirds of 250 V is 167 V: the highest usual supply under it is 150 V.
    bus, fits = motors_for(250, 1)
    assert bus == 150
    assert fits["induction"].fit == "suits" and "mains-level" in fits["induction"].why
    assert fits["synrm"].fit == "suits"
    assert fits["dc"].fit == "suits" and fits["stepper"].fit == "suits"


def test_brushed_motors_and_steppers_are_said_to_be_seldom_wound_above_200_v() -> None:
    bus, fits = motors_for(650, 1)
    assert bus == 400
    for kind in ("dc", "stepper"):
        assert fits[kind].fit == "unusual"
        assert fits[kind].why.endswith("seldom wound for more than about 200 V; this device is meant for about 400 V")


def test_a_two_leg_package_recommends_a_brushed_motor_only_at_low_voltage() -> None:
    _, low = motors_for(100, 4)
    assert low["dc"].fit == "recommended" and low["pmsm"].fit == "suits"
    _, high = motors_for(650, 4)
    assert high["dc"].fit == "unusual" and "seldom wound" in high["dc"].why
    assert high["pmsm"].fit == "recommended"
    assert [k for k, f in high.items() if f.fit == "recommended"] == ["pmsm"]


# ---------- ranking ----------


def test_devices_in_parallel_multiply_the_packages_and_the_switches_left_over() -> None:
    two = replace(BASE, parallel=2)
    # Six positions, two devices at each: twelve discrete parts.
    single = igbt("SINGLE", 0.9, topology=Topology.discrete)
    assert requirements(single, 6, two)[0] == "12 packages for the 6 switches, 2 in parallel at each"
    # Four switches to a package: two packages hold six, twice over; 16 switches for 12 places.
    quad = igbt("QUAD", 0.9, topology=Topology.h_bridge)
    assert requirements(quad, 6, two)[0] == (
        "4 packages for the 6 switches, 2 in parallel at each (4 switches left unused)"
    )
    assert requirements(quad, 6, BASE)[0] == "2 packages for the 6 switches (2 switches left unused)"


def test_a_built_in_driver_is_priced_at_the_loss_it_adds_not_at_its_whole_loss() -> None:
    motor = ADAPTER.validate_python(dict(type="pmsm", pole_pairs=4, flux_linkage=0.1, ld=0.008, lq=0.008, rs=1.0))
    discrete, module = igbt("DISCRETE", 0.7), igbt("MODULE", 1.6)
    module.package.integrated_driver = True
    alone = [at_speed_and_torque(d, motor, 3000, 2.0, BASE).result.p_inverter for d in (discrete, module)]
    assert alone[1] - alone[0] > 1.0
    lines = explain(propose([module, discrete], motor, 3000, 2.0, BASE))
    assert (
        f"It needs separate gate drivers. synthetic MODULE has them built in, for {alone[1] - alone[0]:.1f} W more loss."
        in lines
    )


def test_a_device_that_could_not_be_evaluated_never_reads_as_the_lowest_loss() -> None:
    unknown = Candidate(igbt("UNKNOWN", 0.9), None, None, [], "no stable temperature")
    assert unknown.loss == math.inf
    assert unknown.level is guard.Level.fail and unknown.margin is None


def test_switching_loss_is_said_to_follow_the_datasheet_figure_only_inside_its_range() -> None:
    device = igbt("FIGURE", 0.9)
    device.switch.e_on.v_values = [200.0, 400.0]
    device.switch.e_on.v_factor = [0.6, 1.4]
    inside = switching_footing(device, replace(BASE, v_dc=350.0))
    assert inside.text == "measured at 300 V; brought to 350 V along the datasheet's figure"
    assert not inside.stretched
    above = switching_footing(device, replace(BASE, v_dc=450.0))
    assert above.text == "measured at 300 V; brought to 450 V in proportion"
    assert above.stretched
    below = switching_footing(device, replace(BASE, v_dc=150.0))
    assert below.text == "measured at 300 V; brought to 150 V in proportion"
    assert not below.stretched


def test_a_device_whose_loss_outruns_its_cooling_is_ruled_out_and_told_why() -> None:
    # Resistance rising 2 mΩ per kelvin behind 1000 K/W: at a few amps each kelvin adds more
    # than a milliwatt of loss, and each milliwatt more than a kelvin. There is no settled temperature.
    motor = ADAPTER.validate_python(dict(type="pmsm", pole_pairs=4, flux_linkage=0.1, ld=0.008, lq=0.008, rs=1.0))
    runaway = linear_device(
        sw_curves=[line(25.0, 0.0, 0.05), line(125.0, 0.0, 0.25)], d_curves=[line(25.0, 1.0, 0.025)], rth_sw=1000.0
    )
    runaway.part_number = "RUNAWAY"
    steady = igbt("STEADY", 0.9)
    ranked = propose([runaway, steady], motor, 3000, 2.0, BASE)
    assert [c.device.part_number for c in ranked] == ["STEADY", "RUNAWAY"]
    assert ranked[1].level is guard.Level.fail and ranked[1].design is None
    lines = explain(ranked)
    assert lines[0].startswith("synthetic STEADY has the lowest power-stage loss among the devices that pass")
    assert lines[-1] == (
        "synthetic RUNAWAY is ruled out: no stable temperature: losses grow faster than the heat can leave."
    )


# ---------- motors: either direction, saturation, standstill ----------


def test_iron_loss_is_the_same_whichever_way_the_motor_turns() -> None:
    # Half rises with speed and half with its square: at twice the test speed, 0.5 * 2 + 0.5 * 4 times as much.
    motor = BrushedDc(type="dc", kt=0.05, r=0.4, p_iron=10.0, n_iron=1000.0)
    assert motor.iron_loss(2000.0) == pytest.approx(10.0 * 3.0)
    assert motor.iron_loss(-2000.0) == pytest.approx(10.0 * 3.0)


def test_a_saturating_reluctance_motor_carries_the_current_its_fallen_inductances_ask_for() -> None:
    # Below the voltage limit id = iq = i, so both inductances have fallen by sqrt(1 + (i / i_sat)^2) and
    # torque = 1.5 p (Ld - Lq) i^2 / sqrt(1 + (i / i_sat)^2), a quadratic in i^2. The rms phase current is i.
    pairs, ld, lq, i_sat, torque = SYNRM["pole_pairs"], SYNRM["ld"], SYNRM["lq"], 4.0, 6.0
    motor = ADAPTER.validate_python({**SYNRM, "i_sat": i_sat})
    c = torque / (1.5 * pairs * (ld - lq))
    i = math.sqrt((c**2 / i_sat**2 + math.sqrt(c**4 / i_sat**4 + 4 * c**2)) / 2)
    assert i > 0.9 * i_sat  # well into saturation
    figures = summary(motor.stage(300.0, torque, 540.0, Pwm.space_vector))
    assert figures["field weakening"] == 0.0
    assert figures["phase current"] == pytest.approx(i, rel=1e-6)


def test_an_induction_motor_s_torque_current_follows_the_rotor_inductance_and_not_the_stator_s() -> None:
    # torque = 1.5 p (Lm / Lr) (Lm id) iq with Lr = Lm + Llr, and the slip is (Rr / Lr) iq / id.
    pairs, rr, lm, llr, i_d, torque = 2, 3.5, 0.32, 0.030, 2.4, 4.0
    motor = ADAPTER.validate_python({**INDUCTION, "lls": 0.010, "llr": llr})
    lr = lm + llr
    i_q = torque / (1.5 * pairs * lm**2 / lr * i_d)
    figures = summary(motor.stage(300.0, torque, 540.0, Pwm.space_vector))
    assert figures["field weakening"] == 0.0
    assert figures["phase current"] == pytest.approx(math.hypot(i_d, i_q) / math.sqrt(2), rel=1e-9)
    assert figures["slip frequency"] == pytest.approx(rr / lr * i_q / i_d / (2 * math.pi), rel=1e-9)


@pytest.mark.parametrize("torque", [0.5, -0.5])
def test_a_brushed_motor_holding_still_is_not_said_to_brake(torque) -> None:
    # Nothing turns, so no energy goes either way through the shaft: the link feeds the winding loss.
    motor = BrushedDc(type="dc", kt=0.05, r=0.4)
    stage = motor.stage(0.0, torque, 24.0, Pwm.sine)
    assert not [n for n in stage.notes if "braking" in n]
    assert stage.p_electrical == pytest.approx(0.4 * (0.5 / 0.05) ** 2)


def test_a_block_commutated_motor_held_still_heats_a_case_with_all_that_one_position_loses() -> None:
    # Held at one rotor position, the low-side switch that stays on carries the winding current without
    # a break: its package loses (0.9 V + 30 mΩ * I) * I there, three times its average over a turn.
    amps, layer = 10.0, 0.5
    motor = Bldc(type="bldc", pole_pairs=7, kt=0.09, r=0.08)
    device = linear_device(sw_curves=[line(25.0, 0.9, 0.03)], d_curves=[line(25.0, 0.5, 0.025)], rth_cs=layer)
    point = at_speed_and_torque(device, motor, 0.0, 0.09 * amps, replace(BASE, v_dc=48.0))
    assert point.result.t_case - BASE.t_sink == pytest.approx(layer * (0.9 + 0.03 * amps) * amps, rel=1e-9)


# ---------- first advice: standstill ----------


def test_the_rating_to_look_for_covers_standstill_when_that_takes_more_than_the_design_point() -> None:
    # An induction motor holds its whole magnetising current at standstill and weakens its field at
    # speed: 2.4 A of flux current with 1 A of torque current is 2.6 A standing still, and twice that 5.2 A.
    pairs, lm, lr, i_d, i_q = 2, 0.32, 0.32 + 0.015, 2.4, 1.0
    torque = 1.5 * pairs * lm**2 / lr * i_d * i_q
    a = advise(ADAPTER.validate_python(INDUCTION), 3000, torque, 540, 8e3)
    assert a.i_stall == pytest.approx(math.hypot(i_d, i_q), rel=1e-4)
    assert a.i_peak < 0.9 * a.i_stall
    assert "2.6 A holding the same torque at standstill. Start with devices rated for 5.2 A or more" in text(a)


# ---------- ranking: footing, standstill, cautions ----------

SURFACE = dict(type="pmsm", pole_pairs=4, flux_linkage=0.1, ld=0.008, lq=0.008, rs=1.0)


def test_a_device_with_its_gate_drive_built_in_is_not_told_about_the_user_s_gate_resistor() -> None:
    device = igbt("BUILT-IN", 0.9)
    device.switch.e_on.rg = device.switch.e_off.rg = 10.0
    own_drive = replace(BASE, rg_on=22.0, rg_off=22.0)
    assert switching_footing(device, own_drive).text == (
        "measured at 300 V, 10 Ω; your gate resistor is not applied, for want of a figure against it"
    )
    device.package.integrated_driver = True
    assert switching_footing(device, own_drive).text == "measured at 300 V, 10 Ω; gate drive built in"


def test_switching_loss_stretched_to_a_higher_voltage_is_pointed_out_only_beside_one_that_is_not() -> None:
    motor = ADAPTER.validate_python(SURFACE)
    first, second = igbt("FIRST", 0.9), igbt("SECOND", 1.2)
    higher = replace(BASE, v_dc=350.0)  # both were measured at 300 V
    both = propose([first, second], motor, 3000, 2.0, higher)
    assert [c.footing.stretched for c in both] == [True, True]
    assert not [said for said in explain(both) if "higher voltage" in said]
    second.switch.e_on.v_values = [200.0, 400.0]
    second.switch.e_on.v_factor = [0.6, 1.4]
    one = propose([first, second], motor, 3000, 2.0, higher)
    assert [c.footing.stretched for c in one] == [True, False]
    assert (
        "The switching loss of synthetic FIRST is brought in proportion to a higher voltage "
        "than it was measured at, and is likely stated low against the others."
    ) in explain(one)


def test_a_device_that_cannot_hold_the_torque_at_standstill_is_ruled_out() -> None:
    # Every chip drops 1 V up to 100 °C, and the switch far more beyond. 2 N·m takes 3.33 A peak. Turning,
    # a switch and its diode lose 1 V * I / pi = 1.06 W between them: 30 K over the sink through 28 K/W.
    # Held still at the worst rotor position they lose 1 V * I / 2 = 1.67 W, which is 47 K over a 60 °C
    # sink: past 100 °C, where each kelvin adds more loss than the case can shed.
    motor = ADAPTER.validate_python(SURFACE)
    drop = [line(25.0, 1.0, 0.0), line(100.0, 1.0, 0.0), line(125.0, 1.0, 2.0)]
    device = linear_device(sw_curves=drop, d_curves=[line(25.0, 1.0, 0.0)], rth_sw=0.5, rth_d=0.5, rth_cs=28.0)
    device.part_number = "KINKED"
    (candidate,) = propose([device], motor, 3000, 2.0, BASE)
    assert candidate.design is not None and candidate.problem is None
    assert candidate.margin > 50  # turning, it has room to spare
    assert candidate.level is guard.Level.fail
    assert explain([candidate]) == [
        "None of these devices passes every check at this operating point.",
        "synthetic KINKED is ruled out: at standstill: no stable temperature: "
        "losses grow faster than the heat can leave.",
    ]


def test_the_best_device_is_said_to_pass_with_cautions_when_it_does() -> None:
    # 500 V on a 600 V part is 83% of its rating: over the 80% that leaves room for overshoot.
    motor = ADAPTER.validate_python(SURFACE)
    (candidate,) = propose([igbt("NEAR", 0.9)], motor, 3000, 2.0, replace(BASE, v_dc=500.0))
    assert candidate.level is guard.Level.caution
    assert any(c.topic == "voltage" and "supply is 83% of the 600 V rating" in c.message for c in candidate.checks)
    assert explain([candidate])[1] == (
        "synthetic NEAR passes with cautions, listed below; read them before relying on it."
    )
