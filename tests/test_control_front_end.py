"""The front end's control and the DC link through time: the link's loop against its own
closed forms, what the tie to the motor's control does, what braking does to a stage that gives
nothing back, and the C held to the simulation sample by sample."""

from __future__ import annotations

import math

import numpy as np
import pytest

from motionsim.control import front_end as control
from motionsim.control.codegen import front_end as codegen
from motionsim.control.codegen.replay import compiler
from motionsim.front_end import Mains

ONE = Mains(230.0, 50.0, 1)
THREE = Mains(400.0, 50.0, 3)
T = np.linspace(0.0, 0.12, 1200)
STEP = np.where(T < 0.02, 300.0, 1500.0)
STAGES = {
    "one": (ONE, 850e-6, 600e-6, 65e3, 390.0),
    "three": (THREE, 3.5e-3, 150e-6, 40e3, 680.0),
}


def through(which: str, power=STEP, *, returns=False, feed_forward=True, record=0, capacitance=None):
    line, henry, farad, f_s, v_ref = STAGES[which]
    farad = capacitance or farad
    gains = control.tuned(line, v_ref, 1500.0, henry, farad, f_s, returns=returns, feed_forward=feed_forward)
    return gains, control.link_through(line, True, gains, farad, T, power, v_start=v_ref, record=record)


def test_one_phase_gives_its_power_in_pulses_and_the_link_moves_by_the_closed_form() -> None:
    # A steady 1500 W on one phase: the capacitor takes P·(1 − cos 2ωt), so the link moves
    # P/(ω·C·V) peak to peak at twice the mains (any text on power-factor correction).
    steady = np.full_like(T, 1500.0)
    _, r = through("one", steady)
    expected = 1500.0 / (2 * math.pi * 50.0 * 600e-6 * 390.0)
    assert r.ripple == pytest.approx(expected, rel=0.05)
    assert abs(0.5 * (r.v_min + r.v_max) - 390.0) < 2.0
    # The current is a sine to a few percent, and the mains gives what the link takes.
    assert r.thd is not None and r.thd < 0.05
    assert float(r.p_in[-400:].mean()) == pytest.approx(1500.0, rel=0.02)
    assert r.i_peak == pytest.approx(math.sqrt(2) * 1500.0 / 230.0, rel=0.05)


def test_three_phases_give_a_steady_power_and_the_link_stands_still() -> None:
    _, r = through("three", np.full_like(T, 1500.0), returns=True)
    assert r.ripple < 0.5 and abs(r.v_min - 680.0) < 1.0
    assert r.thd is not None and r.thd < 0.01
    assert r.i_peak == pytest.approx(math.sqrt(2) * 1500.0 / (math.sqrt(3) * 400.0), rel=0.03)


@pytest.mark.parametrize("which", ["one", "three"])
def test_told_of_the_motor_s_power_the_link_holds_through_a_load_step(which) -> None:
    _, alone = through(which, feed_forward=False, returns=which == "three")
    _, tied = through(which, feed_forward=True, returns=which == "three")
    v_ref = STAGES[which][4]
    # Alone, the loop answers once the voltage has fallen: by tens of volts on 1200 W more.
    assert v_ref - alone.v_min > 60.0
    # Tied, what is left is the mains' own rhythm on one phase, and nothing on three.
    assert v_ref - tied.v_min < (15.0 if which == "one" else 3.0)
    assert v_ref - tied.v_min < 0.25 * (v_ref - alone.v_min)


def test_an_untied_loop_s_sag_is_what_its_bandwidth_and_capacitor_say() -> None:
    # A step ΔP on a loop that crosses over at ω: the link falls by about ΔP/(ω·C·V) before the
    # loop has answered (the capacitor alone gives the power for a time 1/ω).
    _, r = through("three", feed_forward=False, returns=True)
    w = 2 * math.pi * control.LINK_LOOP * 50.0
    expected = 1200.0 / (w * 150e-6 * 680.0)
    assert 680.0 - r.v_min == pytest.approx(expected, rel=0.35)


def test_braking_charges_the_link_of_a_stage_that_gives_nothing_back() -> None:
    braking = np.where(T < 0.02, 300.0, -800.0)
    _, boost = through("one", braking, returns=False)
    _, totem = through("one", braking, returns=True)
    # ½·C·(V² − V0²) is the energy returned: 800 W for 0.1 s into 600 µF from 390 V.
    expected = math.sqrt(390.0**2 + 2 * 800.0 * 0.1 / 600e-6)
    assert boost.v_max == pytest.approx(expected, rel=0.03)
    assert totem.v_max < 400.0
    assert float(totem.p_in[-400:].mean()) == pytest.approx(-800.0, rel=0.03)


def test_a_rectifier_s_link_follows_the_crests_and_rises_on_braking() -> None:
    r = control.link_through(ONE, False, None, 1.27e-3, T, np.full_like(T, 1500.0), v_start=310.0)
    assert r.v_max == pytest.approx(ONE.peak, rel=0.002)
    assert r.ripple == pytest.approx(0.10 * ONE.peak, rel=0.1)  # the capacitance its solve sizes for a tenth
    assert r.thd is None and r.i_peak > 5 * math.sqrt(2) * 1500.0 / 230.0
    six = control.link_through(THREE, False, None, 100e-6, T, np.full_like(T, 1500.0), v_start=540.0)
    assert six.v_max == pytest.approx(THREE.peak, rel=0.002) and six.ripple < 0.14 * THREE.peak
    up = control.link_through(ONE, False, None, 1.27e-3, T, np.where(T < 0.02, 300.0, -800.0), v_start=310.0)
    assert up.v_max > ONE.peak + 100.0


def test_the_notch_keeps_the_mains_rhythm_out_of_the_power_asked_for() -> None:
    gains, _ = through("one")
    ctl = control.Controller(gains, ONE.peak)
    ctl.settle(390.0, 1000.0)
    t_slow = gains.slow * gains.ts
    asked = [ctl.slow(390.0 + 10.0 * math.sin(2 * math.pi * 100.0 * k * t_slow), 1000.0) for k in range(4000)]
    # Ten volts at 100 Hz would ask kp·10 W through the loop's gain; the notch leaves a fraction.
    assert max(asked[2000:]) - min(asked[2000:]) < 0.1 * 2 * gains.kp_v * 10.0
    assert np.mean(asked[2000:]) == pytest.approx(1000.0, abs=5.0)


def test_the_gains_are_the_rule_s() -> None:
    gains, _ = through("one")
    assert gains.kp_v == pytest.approx(2 * math.pi * 10.0 * 600e-6 * 390.0)
    assert gains.kp_i == pytest.approx(2 * math.pi * (65e3 / 15) * 850e-6)
    assert gains.slow == round(65e3 / 2000.0) and gains.p_min == 0.0
    assert gains.b0 + gains.b1 + gains.b2 == pytest.approx(1 + gains.a1 + gains.a2)  # one at DC
    three, _ = through("three", returns=True)
    assert (three.b0, three.b1, three.b2, three.a1, three.a2) == (1.0, 0.0, 0.0, 0.0, 0.0)
    assert three.p_min == -three.p_max


@pytest.mark.parametrize("which", ["one", "three"])
def test_the_c_gives_the_simulation_s_duty_cycles(which) -> None:
    if compiler() is None:
        pytest.skip("no C compiler on this machine")
    line = STAGES[which][0]
    gains, r = through(which, returns=which == "three", record=4000)
    assert len(r.recorded["out"]) == 4000
    made = codegen.files(gains, math.sqrt(2) * line.v_phase, r, STAGES[which][4], float(STEP[0]), ["a test"])
    assert sorted(made) == [
        "front_end/front_end_replay.c",
        "front_end/front_end_replay_data.txt",
        "front_end/front_end_replay_limits.txt",
        "front_end/motionsim_front_end.c",
        "front_end/motionsim_front_end.h",
    ]
    assert ("fe_fast3(" in made["front_end/motionsim_front_end.h"]) == (which == "three")
    found = codegen.replay(made)
    assert found["passed"] is True, found
    assert found["precisions"]["double"]["worst"] <= 1e-12
    assert found["precisions"]["float"]["samples"] == 4000
    assert found["precisions"]["double"]["limits"]["worst"] <= 1e-12


def test_a_c_that_is_not_the_simulation_s_fails_its_replay() -> None:
    if compiler() is None:
        pytest.skip("no C compiler on this machine")
    gains, r = through("one", record=2000)
    made = codegen.files(gains, ONE.peak, r, 390.0, float(STEP[0]), ["a test"])
    name = "front_end/motionsim_front_end.c"
    kp = f"#define FE_KP_I ((fe_real){codegen._c(gains.kp_i)})"
    assert kp in made[name]
    made[name] = made[name].replace(kp, f"#define FE_KP_I ((fe_real){codegen._c(1.05 * gains.kp_i)})")
    found = codegen.replay(made)
    assert found["passed"] is False and "FAILED" in found["said"]


LIMITS = (
    ("FE_I_MAX", lambda g: g.i_max),
    ("FE_P_MAX", lambda g: g.p_max),
    ("FE_KI_V", lambda g: g.ki_v),
    ("FE_KI_I", lambda g: g.ki_i),
)


@pytest.mark.parametrize("which", ["one", "three"])
@pytest.mark.parametrize("name", [n for n, _ in LIMITS])
def test_a_limit_or_an_integrator_that_is_off_in_the_c_fails_the_replay_past_the_limits(which, name) -> None:
    if compiler() is None:
        pytest.skip("no C compiler on this machine")
    line = STAGES[which][0]
    gains, r = through(which, returns=which == "three", record=1000)
    made = codegen.files(gains, math.sqrt(2) * line.v_phase, r, STAGES[which][4], float(STEP[0]), ["a test"])
    value = dict(LIMITS)[name](gains)
    was = f"#define {name} ((fe_real){codegen._c(value)})"
    assert was in made["front_end/motionsim_front_end.c"]
    made["front_end/motionsim_front_end.c"] = made["front_end/motionsim_front_end.c"].replace(
        was, f"#define {name} ((fe_real){codegen._c(0.75 * value)})"
    )
    assert codegen.replay(made)["passed"] is False


def test_a_c_that_gives_no_number_or_a_file_cut_short_fails_the_replay() -> None:
    if compiler() is None:
        pytest.skip("no C compiler on this machine")
    gains, r = through("one", record=1000)
    made = codegen.files(gains, ONE.peak, r, 390.0, float(STEP[0]), ["a test"])
    broken = dict(made)
    name = "front_end/motionsim_front_end.c"
    assert "  return d_sat;" in broken[name]
    broken[name] = broken[name].replace("  return d_sat;", '  return d_sat * (fe_real)nan("");')
    assert codegen.replay(broken)["passed"] is False
    cut = dict(made)
    data = "front_end/front_end_replay_data.txt"
    cut[data] = "\n".join(cut[data].split("\n")[:11]) + "\n"
    assert codegen.replay(cut)["passed"] is False


def test_three_phases_draw_their_current_in_phase_with_the_voltage() -> None:
    _, r = through("three", np.full_like(T, 1500.0), returns=True)
    # Line a's current against sin and cos of the mains over the last period: all of it in phase.
    last = (T - (T[-1] - 0.02)) >= 0.0
    angle = 2 * math.pi * 50.0 * T[last]
    along = 2 * float(np.mean(r.i_line[last] * np.sin(angle)))
    across = 2 * float(np.mean(r.i_line[last] * np.cos(angle)))
    assert along == pytest.approx(math.sqrt(2) * 1500.0 / (math.sqrt(3) * 400.0), rel=0.03)
    assert abs(across) < 0.03 * along
    assert float(r.p_in[last].mean()) == pytest.approx(1500.0, rel=0.01)


def test_a_stage_with_a_switch_for_its_diode_draws_a_cleaner_current_through_the_crossings() -> None:
    steady = np.full_like(T, 1500.0)
    _, boost = through("one", steady)
    _, totem = through("one", steady, returns=True)
    # The mean square of the voltage is slow enough to leave under a percent of third harmonic.
    assert boost.thd is not None and totem.thd is not None
    assert boost.thd < 0.015 and totem.thd < 0.015
    assert float(totem.p_in.min()) > -1.0


def test_a_capacitor_too_small_to_carry_the_drive_ends_the_link_s_run() -> None:
    _, r = through("one", capacitance=3e-6)
    assert r.collapsed and r.thd is None
    assert 0.5 * ONE.peak <= r.v_min and r.v_max <= 4 * 390.0


def test_a_rectifier_s_line_current_goes_both_ways() -> None:
    steady = np.full_like(T, 1500.0)
    one = control.link_through(ONE, False, None, 1.27e-3, T, steady, v_start=310.0)
    assert one.i_line.min() == pytest.approx(-one.i_line.max(), rel=0.05) and one.i_line.max() > 20.0
    six = control.link_through(THREE, False, None, 100e-6, T, steady, v_start=540.0)
    assert six.i_line.min() == pytest.approx(-six.i_line.max(), rel=0.05)
    assert float(np.mean(six.i_line == 0.0)) > 0.3  # a line rests at least the third of the time it is the middle one
