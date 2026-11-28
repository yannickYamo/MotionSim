"""The shaft that twists (plant.Coupling) and the compressor's gas torque (load.Pulsation).

Expected values are worked from the definitions: a free two-mass swing at sqrt(K(1/Jm+1/Jl)),
momentum kept with no load, no torque inside the play, a very stiff shaft running as a rigid
one, and the compressor shape's mean, peak and period.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from motionsim.control.plant import Coupling, Machine, Plant
from motionsim.load import Pulsation

J_M, J_L, K = 2e-5, 8e-5, 50.0
QUIET = Machine(0.05, 1e-3, 1e-3, 1e-12, 4)  # no magnet to speak of: no current, no torque at no voltage


def _free(coupling: Coupling, twist: float, h: float, steps: int) -> list[tuple[float, float, float]]:
    plant = Plant(QUIET, inertia=J_M + J_L, coupling=coupling)
    plant.start()
    plant.twist = twist
    out = []
    for _ in range(steps):
        plant.advance(0.0, 0.0, h)
        out.append((plant.time, plant.twist, J_M * plant.w_m + J_L * plant.w_l))
    return out


def test_a_free_shaft_swings_at_its_natural_frequency():
    c = Coupling(J_M, K)
    expected = math.sqrt(K * (1 / J_M + 1 / J_L))
    assert c.natural(J_M + J_L) == pytest.approx(expected)
    run = _free(c, 1e-3, 5e-6, 4000)
    crossings = [
        t
        for (t, a), (_, b) in zip([(r[0], r[1]) for r in run[:-1]], [(r[0], r[1]) for r in run[1:]], strict=True)
        if a > 0 >= b
    ]
    period = (crossings[-1] - crossings[0]) / (len(crossings) - 1)
    assert 2 * math.pi / period == pytest.approx(expected, rel=2e-3)


def test_with_no_load_the_momentum_is_kept_and_damping_takes_the_swing():
    c = 2e-3
    run = _free(Coupling(J_M, K, damping=c), 1e-3, 5e-6, 6000)
    assert max(abs(r[2]) for r in run) < 1e-12
    # The twist obeys Jeq·x'' + c·x' + K·x = 0, Jeq = Jm·Jl/(Jm+Jl): its envelope falls as e^(−c·t/2Jeq).
    sigma = c / (2 * J_M * J_L / (J_M + J_L))
    w_n = Coupling(J_M, K).natural(J_M + J_L)
    t_d = 2 * math.pi / math.sqrt(w_n * w_n - sigma * sigma)
    x = [r[1] for r in run]
    peaks = [x[k] for k in range(1, len(x) - 1) if x[k - 1] < x[k] >= x[k + 1] and x[k] > 0]
    ratios = [b / a for a, b in zip(peaks[:-1], peaks[1:], strict=True)]
    assert sum(ratios) / len(ratios) == pytest.approx(math.exp(-sigma * t_d), rel=5e-3)


def test_inside_the_play_the_shaft_carries_nothing():
    plant = Plant(QUIET, inertia=J_M + J_L, coupling=Coupling(J_M, K, backlash=2e-3))
    plant.start()
    plant.twist = 0.9e-3
    assert plant.shaft_torque() == 0.0
    plant.twist = 1.5e-3
    assert plant.shaft_torque() == pytest.approx(K * 0.5e-3)


def test_a_very_stiff_shaft_runs_as_a_rigid_one():
    """A load that drives the shaft with 0.01 N·m: a rigid shaft gains 0.01·t/J; a stiff one the same."""
    drive = lambda w, a, t: -0.01
    rigid, stiff = (
        Plant(QUIET, J_M + J_L, drive),
        Plant(QUIET, J_M + J_L, drive, coupling=Coupling(J_M, 1e6, damping=5.0)),
    )
    for p in (rigid, stiff):
        p.start()
        for _ in range(2000):
            p.advance(0.0, 0.0, 50e-6)
    assert rigid.w_m == pytest.approx(0.01 * 0.1 / (J_M + J_L), rel=1e-9)
    assert stiff.w_m == pytest.approx(rigid.w_m, rel=1e-3)
    assert stiff.w_l == pytest.approx(rigid.w_m, rel=1e-3)


def test_the_motor_inertia_must_be_a_part_of_the_whole():
    with pytest.raises(ValueError):
        Plant(QUIET, inertia=1e-5, coupling=Coupling(J_M, K))


def _over_turn(p: Pulsation, n: int = 3600) -> list[float]:
    return [p.at(2 * math.pi * k / n) for k in range(n)]


def test_the_rotary_compressor_pulse_has_mean_nought_its_peak_late_and_a_quiet_start():
    turn = _over_turn(Pulsation(torque=2.0, shape="rotary"))
    assert sum(turn) / len(turn) == pytest.approx(0.0, abs=2e-3)
    assert max(turn) == pytest.approx(2.0, rel=1e-3)
    assert turn.index(max(turn)) > len(turn) // 2
    assert max(turn[: len(turn) // 3]) < 0.0  # suction and early compression ask less than the mean


def test_two_rotors_repeat_each_half_turn_and_a_sine_stays_a_sine():
    twin = _over_turn(Pulsation(torque=1.0, shape="twin_rotary"))
    half = len(twin) // 2
    assert twin[:half] == pytest.approx(twin[half:], abs=1e-9)
    assert Pulsation(torque=1.5, per_turn=2).at(math.pi / 4) == pytest.approx(1.5)


def test_a_shaft_that_starts_running_starts_carrying_its_load():
    # Wound by the load's torque over the stiffness, and across half the play, so that the
    # shaft carries the load from the first instant and nothing swings the test did not start.
    for backlash in (0.0, 0.02):
        plant = Plant(QUIET, inertia=J_M + J_L, load=lambda w, a, t: 1.5, coupling=Coupling(J_M, K, 0.0, backlash))
        plant.start(omega_m=100.0)
        assert plant.shaft_torque() == pytest.approx(1.5, rel=1e-12)
        assert plant.twist == pytest.approx(1.5 / K + 0.5 * backlash, rel=1e-12)


def test_the_linear_view_s_two_mass_shaft_steps_as_the_closed_form_says() -> None:
    # A torque of 1 N·m held from nought on an undamped two-mass shaft: the rotor's speed is
    # t/J plus a swing, J_L/(J·J_m·w)·sin(w·t), w² = k·J/(J_m·J_L) (Newton, by hand).
    from motionsim.control.linear import shaft_transfer
    from motionsim.control.plant import Coupling

    ts, j_m, j_l, k = 1e-4, 2e-4, 6e-4, 50.0
    j = j_m + j_l
    num, den = shaft_transfer(ts, j, Coupling(j_m, k, 0.0))
    # The difference equation driven by a unit step, sample by sample.
    n = 400
    u, y = np.ones(n), np.zeros(n)
    b, a = np.concatenate([np.zeros(len(den) - len(num)), num]), den
    for i in range(n):
        y[i] = sum(b[m] * u[i - m] for m in range(len(b)) if i - m >= 0) - sum(
            a[m] * y[i - m] for m in range(1, len(a)) if i - m >= 0
        )
    w = math.sqrt(k * j / (j_m * j_l))
    t = np.arange(n) * ts
    expected = t / j + j_l / (j * j_m * w) * np.sin(w * t)
    assert np.max(np.abs(y - expected)) < 1e-9 * np.max(np.abs(expected))
    # And with no coupling it is the rigid shaft's Ts/(J·(z − 1)), exactly.
    num, den = shaft_transfer(ts, j, None)
    assert list(num) == [ts / j] and list(den) == [1.0, -1.0]


def test_the_speed_loop_s_linear_view_and_the_run_agree_on_a_twisting_shaft() -> None:
    from test_control_bench import posted, started, workspace

    ws = workspace()
    base = started("example-mosfet", ws)
    plant = {"coupling": {"resonance_hz": 120}}
    rigid = posted("/api/control/loops", {**base, "scheme": "servo_joint"}, ws)["speed"]
    linear = posted("/api/control/loops", {**base, "scheme": "servo_joint", "plant": plant}, ws)["speed"]
    run = posted(
        "/api/control/run",
        {**base, "scheme": "servo_joint", "scenario": {"kind": "speed_step"}, "fidelity": "averaged", "plant": plant},
        ws,
    )
    # The shaft is in the view: its resonance takes gain margin, and the analysis says so.
    assert linear["margins"]["gain_db"] < rigid["margins"]["gain_db"] - 3.0
    assert any("the shaft twists" in s for s in linear["transfer"])
    # The view's closed loop overshoots as the simulated rotor does, to a few points (the run
    # has its limits and its current loop's own non-linearity; the view has neither).
    simulated = run["quality"]["step"]["overshoot"]
    assert linear["step"]["overshoot"] == pytest.approx(simulated, abs=0.04)
    # And the load's own step is read: it overshoots far more than the rotor.
    assert run["quality"]["step"]["load"]["overshoot"] > 2.0 * simulated


def test_a_speed_step_on_a_twisting_shaft_is_judged_at_the_load_too() -> None:
    from test_control_bench import posted, started, workspace

    ws = workspace()
    base = started("example-mosfet", ws)
    step = {"kind": "speed_step"}

    def load_finding(scheme: str, plant: dict | None) -> dict | None:
        body = {
            **base,
            "scheme": scheme,
            "scenario": step,
            "fidelity": "averaged",
            **({"plant": plant} if plant else {}),
        }
        found = posted("/api/control/run", body, ws)["verdict"]["findings"]
        return next((f for f in found if f["id"] == "load_overshoot"), None)

    # On a rigid shaft the load is the rotor: nothing more is said.
    assert load_finding("servo_joint", None) is None
    shaft = {"coupling": {"resonance_hz": 300}}
    plain, notched = load_finding("servo_joint", shaft), load_finding("servo_notch", shaft)
    assert plain is not None and notched is not None
    assert plain["tag"] == "improve" and "twisting shaft" in plain["head"]
    # At the rule's gains the notch takes the loop's own damping away (D209): the load rings
    # more with it, and its advice says so rather than offering a notch.
    assert "the notch takes that away" in notched["expect"] and "helps only where" in plain["expect"]
