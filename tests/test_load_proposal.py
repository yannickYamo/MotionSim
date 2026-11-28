"""The load proposed for a part: the application's own load made as heavy as the part carries
with every check of the motion passing and the junction 25 K under its rating, what stops it
going further named, kept for the design once worked out, and refused where nothing passes."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from motionsim import page
from motionsim.design.setup_file import starting_setup
from motionsim.errors import Refusal
from motionsim.service import remembered
from motionsim.service.motion import proposed
from motionsim.service.motion.follow import cycle
from motionsim.service.routes import dispatch, stream

ROOT = Path(__file__).parent.parent

# What stops each made-up part's application on its starting design: the motor sized to the
# part (its current limit at 0.9 of the part's rating) is reached before the junction, the
# washer's spin is past the motor's reach on its supply first, and the compressor, sealed and
# so started open loop, is past what its start lifts from rest first.
LIMITS = {
    "example": "motor voltage",
    "example-mosfet": "motor current",
    "example-mosfet-40v": "motor current",
    "example-mosfet-80v": "motor current",
    "example-gan": "motor current",
    "example-sic": "start",
    "example-sic-module": "motor current",
}


LONG = ("example",)  # the washer's programme, followed instant by instant


def design(device: str, ws) -> dict:
    """The design the page starts a made-up part on, its load left for the proposal."""
    s = starting_setup(device, ws)
    return {
        "motor": s["motor"],
        "conditions": s["conditions"],
        "device": device,
        "supply": s["supply"],
        "application": s["load_kind"],
    }


def followed(data: dict, preset: dict, ws) -> dict:
    """A preset's load followed through its motion in full, as the results follow it."""
    return cycle({**data, "load": preset["load"], "profile": preset["profile"]}, ws)


def holds(out: dict, light: Counter) -> bool:
    """Whether a motion passes as the proposal is held to: nothing fails or is undecided, the
    junction is the margin under its rating, and no check that tightens with the load has a
    caution more than `light`."""
    checks = out["checks"]
    if any(c["level"] in ("fail", "undecided") for c in checks):
        return False
    if any(c["topic"] == "temperature" and c["level"] != "ok" for c in checks):
        return False
    now = Counter(c["topic"] for c in checks if c["level"] == "caution" and c["topic"] in proposed.GROWING)
    return all(n <= light.get(t, 0) for t, n in now.items())


@pytest.fixture
def ws(tmp_path):
    remembered.forget()
    return page.Workspace(tmp_path)


@pytest.mark.parametrize("device", sorted(LIMITS))
def test_each_made_up_part_is_proposed_a_load_that_passes_and_one_slightly_heavier_does_not(ws, device) -> None:
    data = design(device, ws)
    answer = proposed.load_proposal(data, ws)
    assert answer["application"] == data["application"]
    assert answer["binding"]["limit"] == LIMITS[device]
    assert answer["binding"]["check"] and answer["binding"]["words"]
    assert answer["margin"]["junction"] >= proposed.MARGIN
    assert answer["figures"]["tj_max"] - answer["figures"]["tj_top"] == pytest.approx(answer["margin"]["junction"])
    # The proposal's load is the application's own made k times as heavy, its motion the same.
    usual = proposed._preset(data)
    assert answer["preset"]["profile"] == usual["profile"]
    assert answer["preset"] == proposed.scaled_preset(usual, answer["scale"])
    # Every check of the motion passes at the proposal, worked out in full as the results are.
    if device in LONG:
        # A duty of half an hour: the proposal's own checks are those of its full motion, and
        # following it twice more would be most of the suite's time on its own.
        assert holds({"checks": answer["checks"]}, Counter(c["topic"] for c in answer["checks"]))
        assert answer["scale"] < answer["binding"]["scale"] <= 1.05 * answer["scale"]  # a load that failed
        return
    at = followed(data, answer["preset"], ws)
    light = Counter(c["topic"] for c in at["checks"] if c["level"] == "caution" and c["topic"] in proposed.GROWING)
    assert holds(at, light), [c for c in at["checks"] if c["level"] != "ok"]
    assert at["checks"] == answer["checks"]
    # A little heavier, something gives: the motion, or the open-loop start.
    heavier = proposed.scaled_preset(usual, answer["scale"] * 1.05)
    if answer["binding"]["limit"] == "start":
        assert not lifted(data, heavier, ws)
    else:
        assert not holds(followed(data, heavier, ws), light)


def recommended(data: dict, preset: dict, ws):
    """The control lab's design for a load, and the scheme recommended for it (presets.chosen)."""
    from motionsim.control.presets import BUILDERS, chosen
    from motionsim.service.control.design import _designed

    built, _ = _designed({**data, "load": preset["load"], "profile": preset["profile"]}, ws)
    return built, BUILDERS[chosen(built)[0]](built)


def starts_open_loop(scheme) -> bool:
    return any(b.kind == "if_startup" for b in scheme.blocks)


def lifted(data: dict, preset: dict, ws) -> bool:
    """Whether the open-loop start lifts a load from rest, by presets.chosen's own rule: the
    torque of the drive's current limit above what the load asks of a shaft leaving rest."""
    from motionsim.control.sensorless import rest_load, starting_torque

    built, _ = recommended(data, preset, ws)
    return starting_torque(built, built.limit) > rest_load(built)


@pytest.mark.parametrize("device", sorted(LIMITS))
def test_where_the_scheme_recommended_starts_open_loop_the_proposal_is_one_its_start_lifts(ws, device) -> None:
    """The compressor at 1.48 times passed every check of the motion, but its sensorless
    scheme's start makes 3.80 N·m at the current limit against the 4.37 N·m that load asks of
    a shaft leaving rest: the proposal has to include the start."""
    data = design(device, ws)
    usual = proposed._preset(data)
    _, scheme = recommended(data, usual, ws)
    answer = proposed.load_proposal(data, ws)
    if not starts_open_loop(scheme):
        assert answer["binding"]["limit"] != "start"
        return
    assert lifted(data, answer["preset"], ws)
    # The scheme recommended for the proposal is still the one that starts open loop.
    assert starts_open_loop(recommended(data, answer["preset"], ws)[1])
    if answer["binding"]["limit"] == "start":
        assert answer["binding"]["words"] == "the open-loop start"
        assert "open-loop start makes at most" in answer["binding"]["check"]
        assert not lifted(data, proposed.scaled_preset(usual, answer["binding"]["scale"]), ws)


def test_the_compressor_is_held_by_its_start_not_by_the_motion(ws) -> None:
    """The figures worked by hand: 3.80 N·m from the start at the drive's current limit, the
    usual compressor asking 2.95 N·m of a shaft leaving rest, so no more than 1.29 times."""
    from motionsim.control.sensorless import rest_load, starting_torque

    data = design("example-sic", ws)
    built, scheme = recommended(data, proposed._preset(data), ws)
    assert starts_open_loop(scheme)
    gives, asks = starting_torque(built, built.limit), rest_load(built)
    assert gives == pytest.approx(3.80, abs=0.01) and asks == pytest.approx(2.95, abs=0.01)
    answer = proposed.load_proposal(data, ws)
    assert answer["binding"]["limit"] == "start"
    assert 0.98 * gives / asks <= answer["scale"] < gives / asks


def test_the_proposal_is_kept_for_the_design_and_handed_back_without_a_search(ws) -> None:
    data = design("example-mosfet", ws)
    first = list(stream("/api/load-proposal", data, ws))
    assert len(first) > 3 and all("probe" in x for x in first[:-1])
    assert first[-1]["status"] == 200
    hits = remembered.counts["hits"]
    # The load the page holds, or none, is no part of the design the proposal is for.
    again = list(stream("/api/load-proposal", {**data, "load": {"inertia": 9.0}, "profile": None}, ws))
    assert again == [first[-1]]
    assert remembered.counts["hits"] == hits + 1
    assert dispatch("/api/load-proposal", data, ws) == (200, first[-1]["body"])
    # Another design is another proposal.
    other = {**data, "conditions": {**data["conditions"], "t_sink": 90}}
    assert proposed.design_of(other) != proposed.design_of(data)
    assert remembered.held(proposed.ROUTE, proposed.design_of(other), ws) is None


def test_another_application_is_proposed_on_its_own_load(ws) -> None:
    data = design("example-mosfet", ws)
    answer = proposed.load_proposal({**data, "application": "fan"}, ws)
    assert answer["application"] == "fan"
    assert answer["margin"]["junction"] >= proposed.MARGIN


def test_a_part_of_the_users_own_is_proposed_a_load(ws) -> None:
    text = (ROOT / "examples/synthetic_mosfet_100v_100a.yaml").read_text(encoding="utf-8")
    device = page.add_device("mine.device.yaml", text, ws)["device"]["id"]
    data = design(device, ws)
    answer = proposed.load_proposal(data, ws)
    assert answer["binding"]["limit"] in proposed.WORDS
    assert answer["margin"]["junction"] >= proposed.MARGIN
    assert holds(followed(data, answer["preset"], ws), Counter(c["topic"] for c in answer["checks"]))


def test_a_design_on_which_no_load_passes_is_refused_in_words(ws) -> None:
    data = design("example-mosfet", ws)
    # A heatsink held 10 K under the junction's rating: no load leaves 25 K.
    hot = {**data, "conditions": {**data["conditions"], "t_sink": 165}}
    with pytest.raises(Refusal, match="no load of this kind passes on this design"):
        proposed.load_proposal(hot, ws)
    status, body = dispatch("/api/load-proposal", hot, ws)
    assert status == 422 and "no load of this kind" in body["refused"]


def test_an_application_this_motor_is_not_offered_is_refused_by_name(ws) -> None:
    data = design("example-mosfet", ws)
    with pytest.raises(Refusal, match="no load called"):
        proposed.load_proposal({**data, "application": "spaceship"}, ws)


def test_a_request_without_a_device_is_refused_before_anything_is_worked_out(ws) -> None:
    data = design("example-mosfet", ws)
    status, body = dispatch("/api/load-proposal", {k: v for k, v in data.items() if k != "device"}, ws)
    assert status == 422 and body["field"] == "device"
