from __future__ import annotations

from conftest import V_REF, line, linear_device
from test_mosfet import fet
from test_mosfet import op as fet_op

from motionsim import guard
from motionsim.drivers import at_speed_and_torque
from motionsim.engine import OperatingPoint
from motionsim.motor import Pmsm
from motionsim.propose import explain, propose

MOTOR = Pmsm(pole_pairs=4, flux_linkage=0.1, ld=0.008, lq=0.008, rs=1.0)
BASE = OperatingPoint(v_dc=V_REF, i_rms=0.0, modulation_index=0.0, power_factor=1.0, f_sw=8000.0, t_sink=60.0)


def igbt(name: str, v0: float, rth: float = 1.0, v_max: float = 600.0):
    d = linear_device(
        sw_curves=[line(25.0, v0, 0.03)],
        d_curves=[line(25.0, 1.0, 0.025)],
        k_on=20e-6,
        k_off=15e-6,
        k_rr=5e-6,
        rth_sw=rth,
        rth_d=rth,
    )
    d.part_number = name
    d.ratings.v_max = v_max
    return d


def levels(checks):
    return {c.topic: c.level for c in checks}


def test_checks_on_a_comfortable_point_are_all_ok() -> None:
    device = igbt("A", 0.9)
    point = at_speed_and_torque(device, MOTOR, 3000, 2.0, BASE)
    checks = guard.check(device, BASE, point.result, point.stage.i_peak)
    by = levels(checks)
    assert by["voltage"] is guard.Level.ok and by["temperature"] is guard.Level.ok
    assert by["current"] is guard.Level.ok
    # this synthetic device has one temperature curve, so it is used outside its data
    assert by["data"] is guard.Level.caution


def test_voltage_and_temperature_guardrails() -> None:
    tight = igbt("B", 0.9, v_max=350.0)
    point = at_speed_and_torque(tight, MOTOR, 3000, 2.0, BASE)
    assert levels(guard.check(tight, BASE, point.result, point.stage.i_peak))["voltage"] is guard.Level.caution

    under = igbt("C", 0.9, v_max=250.0)
    point = at_speed_and_torque(under, MOTOR, 3000, 2.0, BASE)
    assert levels(guard.check(under, BASE, point.result, point.stage.i_peak))["voltage"] is guard.Level.fail

    hot = igbt("D", 0.9, rth=120.0)
    point = at_speed_and_torque(hot, MOTOR, 3000, 2.0, BASE)
    assert levels(guard.check(hot, BASE, point.result, point.stage.i_peak))["temperature"] is guard.Level.fail


def test_mosfet_without_dead_time_gets_a_caution() -> None:
    device = fet()
    point = at_speed_and_torque(device, MOTOR, 3000, 2.0, fet_op(i_rms=0.0))
    topics = levels(guard.check(device, fet_op(), point.result, point.stage.i_peak))
    assert topics["dead time"] is guard.Level.caution


def test_proposal_ranks_by_loss_and_rules_out_failures() -> None:
    efficient, lossy, too_hot = igbt("EFFICIENT", 0.7), igbt("LOSSY", 1.6), igbt("HOT", 0.7, rth=60.0)
    ranked = propose([lossy, too_hot, efficient], MOTOR, 3000, 2.0, BASE)
    assert [c.device.part_number for c in ranked] == ["EFFICIENT", "LOSSY", "HOT"]
    assert ranked[-1].level is guard.Level.fail
    text = " ".join(explain(ranked))
    assert "EFFICIENT has the lowest power-stage loss" in text
    assert "LOSSY loses" in text and "HOT is ruled out" in text


def test_standstill_is_checked_as_well_as_the_design_point() -> None:
    """A device that is fine while turning can overheat holding the same torque still."""
    marginal = igbt("MARGINAL", 0.9, rth=9.0)
    (candidate,) = propose([marginal], MOTOR, 3000, 6.0, BASE)
    design = max(candidate.design.result.tj_switch_peak, candidate.design.result.tj_diode_peak)
    stall = max(candidate.stall.result.tj_switch_peak, candidate.stall.result.tj_diode_peak)
    assert stall > design
    assert any(c.topic == "standstill" for c in candidate.checks)


def test_missing_gate_drive_is_a_stated_problem_not_a_crash() -> None:
    (candidate,) = propose([fet()], MOTOR, 3000, 2.0, BASE)
    assert candidate.level is guard.Level.fail
    assert "gate drive voltage" in candidate.problem
    assert "ruled out" in explain([candidate])[-1]


def test_what_a_device_needs_around_it() -> None:
    from motionsim.device import Topology
    from motionsim.propose import requirements

    discrete = igbt("A", 0.9)
    needs = requirements(discrete, 6, BASE)
    assert needs[0] == "6 packages for the 6 switches"
    assert "6 gate-driver channels, 3 of them for high-side" in needs[1]

    module = igbt("M", 0.9)
    module.package.topology = Topology.six_pack
    module.package.integrated_driver = True
    assert requirements(module, 6, BASE) == [
        "1 package for the 6 switches",
        "gate drivers are inside the package",
    ]
    assert requirements(module, 4, BASE)[0] == "1 package for the 4 switches (2 switches left unused)"
    assert requirements(module, 8, BASE)[0] == "2 packages for the 8 switches (4 switches left unused)"

    transistor = fet()
    drive = fet_op(i_rms=0.0)
    line = requirements(transistor, 6, drive)[2]
    charge = transistor.switch.charge
    milliwatts = (charge.q_gs + charge.q_gd) * drive.v_drive * drive.f_sw * 1e3
    assert f"{milliwatts:.3g} mW" in line


def test_proposal_says_when_a_candidate_has_its_drivers_built_in() -> None:
    from motionsim.device import Topology

    discrete = igbt("LOW-LOSS", 0.8)
    module = igbt("MODULE", 0.95)
    module.package.topology = Topology.six_pack
    module.package.rth_mutual = 0.0
    module.package.integrated_driver = True
    text = " ".join(explain(propose([module, discrete], MOTOR, 3000, 2.0, BASE)))
    assert "LOW-LOSS has the lowest power-stage loss" in text
    assert "It needs separate gate drivers. synthetic MODULE has them built in" in text


def test_a_point_with_no_loss_at_all_still_gets_its_explanation() -> None:
    """Zero torque at zero current: nothing to divide by when comparing candidates."""
    lossless = linear_device(sw_curves=[line(25.0, 0.0, 0.0)], d_curves=[line(25.0, 0.0, 0.0)])
    lossless.part_number = "IDEAL"
    text = explain(propose([lossless, igbt("REAL", 0.9)], MOTOR, 1000, 2.0, BASE))
    assert any("REAL loses" in line for line in text)


def undecided(candidate):
    from dataclasses import replace

    held = guard.Check(guard.Level.undecided, "temperature", "the range crosses the rating")
    return replace(candidate, checks=[*candidate.checks, held])


def test_a_part_the_data_cannot_decide_is_never_said_to_pass() -> None:
    efficient, lossy = propose([igbt("EFFICIENT", 0.7), igbt("LOSSY", 1.6)], MOTOR, 3000, 2.0, BASE)
    # Every part undecided: none is among "the devices that pass".
    lines = explain([undecided(efficient), undecided(lossy)])
    text = " ".join(lines)
    assert "that pass" not in text
    assert lines[0] == "None of these devices is shown to pass every check at this operating point."
    assert "EFFICIENT has the lowest power-stage loss among the devices this data cannot decide" in text
    # The part that loses less is undecided and the other passes: the one that passes leads,
    # and the two are not compared as equals.
    lines = explain([lossy, undecided(efficient)])
    text = " ".join(lines)
    assert "LOSSY has the lowest power-stage loss among the devices that pass" in text
    less = lossy.loss - efficient.loss
    assert f"EFFICIENT is not decided by this data, and would lose {less:.1f} W less." in text
    assert "more margin" not in text and "level" not in text


def test_undecided_parts_level_on_loss_are_still_said_not_to_pass() -> None:
    one, other = propose([igbt("ONE", 0.7), igbt("OTHER", 0.7)], MOTOR, 3000, 2.0, BASE)
    lines = explain([undecided(one), undecided(other)])
    assert lines[0] == "None of these devices is shown to pass every check at this operating point."
    assert "on loss they are level" in lines[1] and "that pass" not in " ".join(lines)


def test_a_part_not_decided_is_not_offered_for_its_built_in_drivers() -> None:
    efficient, lossy = propose([igbt("EFFICIENT", 0.7), igbt("LOSSY", 1.6)], MOTOR, 3000, 2.0, BASE)
    efficient.device.package.integrated_driver = True
    text = " ".join(explain([lossy, undecided(efficient)]))
    assert "has them built in" not in text and "for -" not in text
    # Passing, and losing more than a leader that has none, it is offered for what it costs.
    efficient.device.package.integrated_driver = False
    lossy.device.package.integrated_driver = True
    text = " ".join(explain([efficient, lossy]))
    assert f"LOSSY has them built in, for {lossy.loss - efficient.loss:.1f} W more loss." in text
