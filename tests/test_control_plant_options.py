"""The plant a run asks for: the motor's iron saturating and a shaft that twists, read from
the request's `plant`, said in `taken`, refused by name, and nothing changed where absent."""

from __future__ import annotations

import json

import pytest
from test_control_bench import posted, started, workspace

from motionsim.service.routes import dispatch


@pytest.fixture(scope="module")
def ws():
    return workspace()


@pytest.fixture(scope="module")
def base(ws):
    return {**started("example-mosfet", ws), "scheme": "foc_servo"}


def test_with_no_plant_asked_or_linear_iron_the_run_is_the_one_it_was(ws, base) -> None:
    plain = posted("/api/control/run", base, ws)
    linear = posted("/api/control/run", {**base, "plant": {"iron": "linear"}}, ws)
    assert json.dumps(plain["channels"], sort_keys=True) == json.dumps(linear["channels"], sort_keys=True)


def test_saturating_iron_asks_more_current_for_the_same_torque_and_says_it_was_taken(ws, base) -> None:
    plain = posted("/api/control/run", base, ws)
    iron = posted("/api/control/run", {**base, "plant": {"iron": "saturating"}}, ws)
    assert iron["channels"]["i_switch_rms"] > plain["channels"]["i_switch_rms"]
    assert any("iron saturates (taken as usual for" in line for line in iron["taken"])


def test_a_shaft_that_twists_rings_through_a_speed_step(ws, base) -> None:
    step = {"kind": "speed_step"}
    rigid = posted("/api/control/run", {**base, "scenario": step}, ws)["step"]
    twisted = posted("/api/control/run", {**base, "scenario": step, "plant": {"coupling": {"resonance_hz": 40}}}, ws)
    assert twisted["step"]["overshoot"] > 2 * rigid["overshoot"]
    assert any("swings against the load at 40 Hz" in line for line in twisted["taken"])


@pytest.mark.parametrize(
    ("plant", "field"),
    [
        ({"oops": 1}, "plant"),
        ({"iron": "soft"}, "plant.iron"),
        ({"iron": {"d_share": 0.1}}, "plant.iron"),
        ({"coupling": {"damping_ratio": 0.1}}, "plant.coupling"),
        ({"coupling": {"resonance_hz": -3}}, "plant.coupling.resonance_hz"),
    ],
)
def test_a_plant_that_cannot_be_read_is_refused_by_name(ws, base, plant, field) -> None:
    status, body = dispatch("/api/control/run", {**base, "plant": plant}, ws)
    assert status != 200 and body["field"] == field, body


def test_a_speed_scheme_holds_against_its_own_load_and_a_torque_scheme_is_refused_it() -> None:
    ws = workspace()
    base = started("example-sic", ws)
    run = posted(
        "/api/control/run",
        {**base, "scheme": "sensorless_emf", "scenario": {"kind": "hold", "against": "load"}, "fidelity": "averaged"},
        ws,
    )
    # The compressor's load pulses by 1.5 N·m about its mean within each turn: the free shaft
    # slows and speeds up with it, where against the bench's steady torque it would not.
    assert run["channels"]["speed_ripple_pp"] > 1.0
    # Asked the load's own torque, and its speed read over whole turns: no caution that the
    # design torque was not made, nor that the shaft is off its speed (it is, at each instant).
    assert not any("was asked" in c["message"] for c in run["checks"]), run["checks"]
    status, body = dispatch(
        "/api/control/run", {**base, "scheme": "foc_torque", "scenario": {"kind": "hold", "against": "load"}}, ws
    )
    assert status != 200 and body["field"] == "scenario.against", body


def test_saturating_iron_on_a_motor_its_current_barely_moves_is_taken_less_not_refused() -> None:
    from motionsim.control.plant import Machine
    from motionsim.service.control.asking import _iron

    class D:  # what _iron reads of a design
        limit = 20.0

    for ld, lq in ((1e-5, 1.05e-5), (1e-5, 2e-5)):  # Ld·I/ψ = 0.004: surface, then interior
        taken: list[str] = []
        iron = _iron({"plant": {"iron": "saturating"}}, D(), Machine(0.05, ld, lq, 0.05, 4), taken)
        assert any("moves its flux little" in line for line in taken), taken
        if iron is not None:
            # What it took is a proper map, with less saturation than usual.
            assert iron.shares[0] > 0.85 and iron.shares[1] > 0.7


def test_a_step_does_not_pass_for_a_swing_within_a_turn_and_a_load_step_says_where_it_was_held(ws, base) -> None:
    """A speed that moves by the step asked is not a swing within a turn: only a hold reads one.
    A load step says the speed it was held at and how far off it the speed ends."""
    run = posted(
        "/api/control/run",
        {**base, "scheme": "foc_servo", "scenario": {"kind": "load_step"}, "fidelity": "averaged"},
        ws,
    )
    assert run["channels"]["speed_ripple_pp"] is None
    step = run["step"]
    assert step["kind"] == "disturbance" and step["held"] > 0
    assert step["steady_state_error"] is not None and abs(step["steady_state_error"]) < 0.05 * step["held"]
    turned = posted(
        "/api/control/run",
        {**base, "scheme": "foc_servo", "scenario": {"kind": "speed_step"}, "fidelity": "averaged"},
        ws,
    )
    assert turned["channels"]["speed_ripple_pp"] is None


def test_a_scheme_made_for_a_load_that_pulses_within_a_turn_is_set_aside_where_the_load_does_not() -> None:
    """The drive that learns a compressor's turn stays in the list, but says it is not for a load
    that asks the same torque all through the turn, so no comparison sets it beside a servo."""
    ws = workspace()
    joint = posted("/api/control/presets", started("example-mosfet", ws), ws)
    learned = next(s for s in joint["schemes"] if s["id"] == "compressor_smooth")
    assert learned["aside"] and "turn" in learned["aside"]
    assert all(s["aside"] is None for s in joint["schemes"] if s["id"] != "compressor_smooth")
    compressor = posted("/api/control/presets", started("example-sic", ws), ws)
    assert next(s for s in compressor["schemes"] if s["id"] == "compressor_smooth")["aside"] is None
