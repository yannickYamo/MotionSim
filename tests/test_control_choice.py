"""The scheme a design starts on: one rule table by application, as such products are built,
read with the physics of the design (whether an open-loop start lifts the load at rest, and
what the carrier ratio asks, by the same rule the verdict judges a run by). And each made-up
part opened on its own application, through the presets and a default run of the scheme
chosen: the run is over, and its verdict finds nothing wrong with the choice itself."""

from __future__ import annotations

from dataclasses import replace

import pytest
from test_control_bench import design, posted, started, workspace

from motionsim.control.presets import (
    BUILDERS,
    PRACTICE,
    carrier_meets,
    carrier_need,
    chosen,
)
from motionsim.service.applications import APPLICATIONS
from motionsim.service.workspace import EXAMPLES, USES

SENSORLESS = "sensorless_emf"

# On the bench motor (seven pole pairs, 20 kHz): 2000 rpm is 85 switching periods a turn,
# 8000 rpm 21 (sampled twice a period, or a regulator designed at the sampling rate), and
# 20 000 rpm under nine (only a regulator designed at the sampling rate).
RULE = [
    # application, at 2000 rpm, at 8000 rpm, at 20 000 rpm
    (None, "foc_servo", "foc_high_speed", "discrete_high_speed"),
    ("joint", "servo_joint", "foc_high_speed", "discrete_high_speed"),
    ("axis", "foc_servo", "foc_high_speed", "discrete_high_speed"),
    ("vehicle", "foc_torque", "discrete_torque", "discrete_torque"),
    ("tool", "foc_torque", "discrete_torque", "discrete_torque"),
    ("drum", SENSORLESS, SENSORLESS, SENSORLESS),
    ("compressor", SENSORLESS, SENSORLESS, SENSORLESS),
    ("vacuum", SENSORLESS, SENSORLESS, SENSORLESS),
    ("ceiling_fan", SENSORLESS, SENSORLESS, SENSORLESS),
    ("fan", SENSORLESS, SENSORLESS, SENSORLESS),
    ("conveyor", SENSORLESS, SENSORLESS, SENSORLESS),
    ("drone", SENSORLESS, SENSORLESS, SENSORLESS),
]


@pytest.mark.parametrize("application, usual, low, very_low", RULE)
def test_the_rule_table_by_application_and_carrier_ratio(application, usual, low, very_low) -> None:
    for rpm, expected in ((2000.0, usual), (8000.0, low), (20000.0, very_low)):
        d = design(application=application, rpm=rpm)
        first, why = chosen(d)
        assert first == expected, (application, rpm, why)
        assert why and "\n" not in why
        # The verdict's own carrier rule finds nothing to change in the scheme chosen.
        scheme = BUILDERS[first](d)
        need = carrier_need(d.f_sw / d.f_out)
        assert carrier_meets(need, scheme.timing["update"], [b.kind for b in scheme.blocks]), (application, rpm)


def test_every_application_the_page_offers_has_a_row_and_its_start_agrees() -> None:
    assert set(PRACTICE) == set(APPLICATIONS)
    for key, practice in PRACTICE.items():
        assert practice.scheme in BUILDERS and practice.family in ("speed", "torque", "sensorless")
        # A product the loss engine starts open loop has no rotor sensor: the lab starts it so too.
        if APPLICATIONS[key].start == "open_loop":
            assert practice.family == "sensorless", key


def test_the_why_says_what_the_low_ratio_changed() -> None:
    first, why = chosen(design(application="joint", rpm=8000.0))
    assert first == "foc_high_speed" and "robot joint" in why and "21" in why and "S-curve" in why
    first, why = chosen(design(application="drum", rpm=20000.0))
    assert first == SENSORLESS and "already sampled twice a period" in why
    first, why = chosen(design(application="vehicle", rpm=8000.0))
    assert first == "discrete_torque" and "designed at the sampling rate" in why


def test_a_load_no_open_loop_start_can_lift_is_started_on_a_sensor_where_one_can_be_fitted() -> None:
    d = design(application="fan")
    lifts = replace(d, load_standstill=0.5 * d.torque_limit, load_rest_mean=0.5 * d.torque_limit)
    assert chosen(lifts)[0] == SENSORLESS
    heavy = replace(d, load_standstill=1.2 * d.torque_limit, load_rest_mean=1.1 * d.torque_limit)
    first, why = chosen(heavy)
    assert first == "foc_servo" and "no open-loop start follows" in why and "rotor sensor" in why
    # A compressor's shell takes no sensor: kept, and the why says what is needed instead.
    first, why = chosen(replace(heavy, application="compressor"))
    assert first == SENSORLESS and "larger current limit" in why


# --- the made-up parts, each on its own application, as the page opens them

EXPECTED = {
    "example": ("drum", SENSORLESS),  # a washer's direct drive, at 28.6 switching periods a turn
    "example-mosfet": ("joint", "servo_joint"),
    "example-mosfet-40v": ("tool", "foc_torque"),
    "example-gan": ("vacuum", SENSORLESS),  # 100 000 rpm: 24 switching periods a turn
    "example-mosfet-80v": ("drone", SENSORLESS),  # 50 000 rpm on two pole pairs at 48 kHz: 28.8 a turn
    "example-sic": ("compressor", SENSORLESS),
    "example-sic-module": ("vehicle", "foc_torque"),
}
# What a verdict says against the scheme itself, not against the device or the test's figures.
AGAINST_THE_CHOICE = {"carrier", "incomplete", "angle", "start", "lost"}


@pytest.fixture(scope="module")
def ws():
    return workspace()


def test_every_made_up_part_is_covered() -> None:
    assert set(EXPECTED) == set(EXAMPLES) and all(USES[k].application == a for k, (a, _) in EXPECTED.items())


def _run(ws, key: str, kind: str) -> dict:
    data = started(key, ws)  # no application: the page sends one only once a load is picked
    offered = posted("/api/control/presets", data, ws)
    assert offered["chosen"] == EXPECTED[key][1], offered["why"]
    answer = posted("/api/control/run", data | {"scenario": {"kind": kind}}, ws)
    assert answer["scheme"]["id"] == EXPECTED[key][1]
    assert answer["timing"]["ended"] == "duration", answer["timing"]
    against = [f for f in answer["verdict"]["findings"] if f["id"] in AGAINST_THE_CHOICE and f["tag"] != "good"]
    assert not against, against
    return answer


@pytest.mark.parametrize("key", sorted(EXPECTED))
def test_a_made_up_part_starts_on_its_applications_scheme_and_its_default_run_is_over(ws, key) -> None:
    answer = _run(ws, key, "hold")
    assert answer["scenario"]["kind"] == "hold"
    assert any("made-up part is tried on" in line for line in answer["taken"])


@pytest.mark.parametrize("key", ["example", "example-sic", "example-gan", "example-mosfet-80v"])
def test_a_sensorless_choice_starts_its_load_from_rest(ws, key) -> None:
    answer = _run(ws, key, "start")
    assert answer["sensing"] is not None and answer["sensing"]["angle_error_rms"] < 5.0
    assert answer["step"]["reached"], answer["step"]


def test_the_drone_part_is_a_low_carrier_ratio_design_on_its_own_battery(ws) -> None:
    data = started("example-mosfet-80v", ws)
    offered = posted("/api/control/presets", data, ws)
    d = offered["design"]
    assert d["v_dc"] == pytest.approx(44.4) and d["rpm"] == pytest.approx(50_000) and d["f_sw"] == 48_000
    # Two pole pairs at 50 000 rpm: 1667 Hz, 28.8 switching periods of 48 kHz a turn.
    assert d["carrier_ratio"] == pytest.approx(28.8) and carrier_need(d["carrier_ratio"]) == "double"
    assert "already sampled twice a period" in offered["why"]


# --- designs a user brings: their own device file, their own motor, with and without an
# application, across the space the rule has to cover.


def _conditions(**given) -> dict:
    return {"t_sink": 60, "cooling": "held", "parallel": 1, **given}


USERS = {
    # A slow axis with a heavy table on it: 300 rpm on five pole pairs, 0.05 kg·m².
    "slow_servo": (
        "foc_servo",
        {
            "device": "mine-mosfet",
            "application": "axis",
            "shaft": {"inertia": 0.05, "constant": 0.3},
            "motor": {
                "type": "pmsm",
                "magnets": "surface",
                "pole_pairs": 5,
                "kv": 40,
                "l": 3e-4,
                "rs": 0.1,
                "i_max": 30,
            },
            "conditions": _conditions(v_dc=48, rpm=300, torque=3.0, f_sw=20000),
        },
    ),
    # Buried magnets, Lq three times Ld, and no application given.
    "salient_traction": (
        "foc_torque",
        {
            "device": "mine-module",
            "motor": {
                "type": "pmsm",
                "magnets": "interior",
                "pole_pairs": 4,
                "kv": 12.5,
                "ld": 1.5e-4,
                "lq": 4.5e-4,
                "rs": 0.015,
                "i_max": 200,
            },
            "conditions": _conditions(v_dc=400, rpm=4000, torque=100.0, f_sw=10000),
        },
    ),
    # A tiny fan at 30 000 rpm.
    "tiny_fan": (
        SENSORLESS,
        {
            "device": "mine-gan",
            "application": "fan",
            "shaft": {"inertia": 2e-6, "quadratic": 8e-10},
            "motor": {
                "type": "pmsm",
                "magnets": "surface",
                "pole_pairs": 2,
                "kv": 1200,
                "l": 3e-4,
                "rs": 0.5,
                "i_max": 4,
            },
            "conditions": _conditions(v_dc=24, rpm=30000, torque=0.008, f_sw=40000),
        },
    ),
    # A mains pump with no encoder and no inertia given.
    "pump": (
        SENSORLESS,
        {
            "device": "mine-sic",
            "application": "fan",
            "motor": {
                "type": "pmsm",
                "magnets": "surface",
                "pole_pairs": 3,
                "kv": 11.5,
                "l": 0.012,
                "rs": 1.2,
                "i_max": 3.2,
            },
            "conditions": _conditions(v_dc=325, rpm=3000, torque=2.0, f_sw=16000),
        },
    ),
    # 15 000 rpm on four pole pairs at 8 kHz: eight switching periods a turn, no application.
    "ratio_8": (
        "discrete_high_speed",
        {
            "device": "mine-mosfet",
            "motor": {
                "type": "pmsm",
                "magnets": "surface",
                "pole_pairs": 4,
                "kv": 390,
                "l": 5e-5,
                "rs": 0.02,
                "i_max": 30,
            },
            "conditions": _conditions(v_dc=48, rpm=15000, torque=0.3, f_sw=8000),
        },
    ),
}
# Each user's device is a file of their own: a made-up part's figures under a name of theirs,
# so that nothing of the made-up part's own application is taken.
OWN = {
    "mine-mosfet": "example-mosfet",
    "mine-module": "example-sic-module",
    "mine-gan": "example-gan",
    "mine-sic": "example-sic",
}


@pytest.fixture(scope="module")
def mine():
    ws = workspace()
    for name, key in OWN.items():
        (ws.folder / f"{name}.device.yaml").write_text(EXAMPLES[key].read_text(encoding="utf-8"), encoding="utf-8")
    return ws


@pytest.mark.parametrize("user", sorted(USERS))
def test_a_users_own_design_starts_on_the_scheme_its_figures_call_for_and_runs(mine, user) -> None:
    expected, data = USERS[user]
    offered = posted("/api/control/presets", data, mine)
    assert offered["chosen"] == expected, offered["why"]
    assert not any("made-up part is tried on" in line for line in offered["taken"])
    # What the design does not give and the scheme is tuned on is said where the choice is.
    assumed = "No inertia is given" in offered["why"]
    assert assumed == ("shaft" not in data and expected != "foc_torque"), offered["why"]
    for kind in ("hold", "start") if expected == SENSORLESS else ("hold",):
        answer = posted("/api/control/run", data | {"scenario": {"kind": kind}}, mine)
        assert answer["scheme"]["id"] == expected and answer["timing"]["ended"] in ("duration", "speed")
        against = [f for f in answer["verdict"]["findings"] if f["id"] in AGAINST_THE_CHOICE and f["tag"] != "good"]
        assert not against, (user, kind, against)
        if kind == "start":
            assert answer["step"]["reached"], answer["step"]
