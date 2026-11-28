"""The cooling figure the tool offers where a cooling's own figure was left empty (D160), and
the verdict on a cooling the user took from it: said to be sized by the tool, and held at
a caution."""

from __future__ import annotations

import math

import pytest
import yaml

from motionsim import design, page
from motionsim.motor import TEMPLATES
from motionsim.service.verdict.sizing import _down, _up


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    """The 100 V part's design, on the point the figures below were worked out on: the page's
    own permanent-magnet example made 1.6 times as large, at 2000 rpm and 1.6 N·m."""
    ws = page.Workspace(tmp_path_factory.mktemp("parts"))
    setup = design.starting_setup("example-mosfet", ws)
    example = {k: v for k, v in yaml.safe_load(TEMPLATES["pmsm"]).items() if k != "name"}
    setup["motor"] = page.resized(example, 1.6)
    setup["conditions"] = {**setup["conditions"], "rpm": 2000, "torque": 1.6}
    return ws, setup


def ask(ws, start, **conditions) -> dict:
    status, body = page.dispatch(
        "/api/cooling",
        {"motor": start["motor"], "conditions": {**start["conditions"], **conditions}, "device": "example-mosfet"},
        ws,
    )
    assert status == 200, body
    return body


def candidate(ws, start, **conditions) -> dict:
    asked = {"motor": start["motor"], "conditions": {**start["conditions"], **conditions}}
    return page.proposal({**asked, "devices": ["example-mosfet"]}, ws)["candidates"][0]


def test_the_heatsink_offered_holds_the_heatsink_at_60_degrees_by_its_own_loss(made) -> None:
    """Held at 60 °C the stage loses P; (60 − 40) / P in air at 40 °C then puts the heatsink
    at 40 + R·P = 60 °C with that same loss: the fixed point the offer is."""
    ws, start = made
    offer = ask(ws, start, cooling="heatsink", rth_sink="", t_ambient=40)
    held = candidate(ws, start, cooling="held", t_sink=60)["result"]["loss"]
    assert offer["loss"] == pytest.approx(held, rel=1e-9)
    assert offer["exact"] == pytest.approx(20.0 / held, rel=1e-12)
    assert offer["value"] == _down(offer["exact"]) <= offer["exact"]
    on_it = candidate(ws, start, cooling="heatsink", rth_sink=offer["exact"], t_ambient=40)["result"]
    assert on_it["t_sink"] == pytest.approx(60.0, abs=1e-3)
    assert on_it["loss"] == pytest.approx(held, rel=1e-4)


def test_no_heatsink_is_offered_in_air_at_60_degrees_or_above(made) -> None:
    ws, start = made
    offer = ask(ws, start, cooling="heatsink", rth_sink="", t_ambient=60)
    assert offer["value"] is None and "no heatsink in it is held at 60 °C" in offer["why"]


def temperature(ws, start, **conditions) -> str:
    """The level of the verdict's own check of the junction against its rating."""
    checks = candidate(ws, start, **conditions)["checks"]
    return next(c["level"] for c in checks if c["topic"] == "temperature")


def test_the_board_offered_is_the_smallest_on_which_the_verdict_on_the_junction_is_decided(made) -> None:
    """At 2.4 N·m the verdict's check of the junction is decided on the area offered, the loss
    drawn beyond the datasheet's data counted, and is not on a board 2% smaller than the
    area found: the search closed on the edge the verdict itself draws."""
    ws, start = made
    harder = {"cooling": "board", "rth_ja": 40, "t_ambient": 40, "torque": 2.4}
    offer = ask(ws, start, **harder, board_area="")
    assert offer["value"] == _up(offer["exact"]) >= offer["exact"]
    assert temperature(ws, start, **harder, board_area=offer["value"]) in ("ok", "caution")
    assert temperature(ws, start, **harder, board_area=offer["exact"]) in ("ok", "caution")
    assert temperature(ws, start, **harder, board_area=offer["exact"] * 0.98) in ("undecided", "fail")


def test_the_board_offered_counts_the_loss_drawn_beyond_the_data(made) -> None:
    """At the starting point in air at 40 °C the junction's range tops out under 175 °C on
    about 47 cm², where part of the loss is drawn beyond the datasheet's data, which could take
    it over: that board leaves the verdict undecided, so the board offered is larger, and on it
    the verdict on the junction is decided."""
    ws, start = made
    air = {"cooling": "board", "t_ambient": 40}
    offer = ask(ws, start, **air, board_area="")
    assert temperature(ws, start, **air, board_area=47) == "undecided"
    assert offer["value"] > 47
    assert temperature(ws, start, **air, board_area=offer["value"]) in ("ok", "caution")
    sized = candidate(ws, start, **air, board_area=offer["value"], sized="board_area")
    assert not [c for c in sized["checks"] if c["topic"] == "temperature" and c["level"] == "undecided"]


def test_where_no_board_settles_the_verdict_none_is_offered_and_that_is_said(made, monkeypatch) -> None:
    """A point where, on every board, the loss drawn beyond the data could take the junction
    over its rating: no area gives a decided verdict, so none is offered."""
    from motionsim.guard import Level
    from motionsim.service.verdict import sizing

    ws, start = made
    monkeypatch.setattr(sizing, "_board", lambda *_: Level.undecided)
    offer = ask(ws, start, cooling="board", board_area="", t_ambient=40)
    assert offer["value"] is None
    assert offer["why"].startswith("no board gives a decided verdict here")


def test_where_the_junction_is_cool_on_any_board_the_offer_is_the_board_its_copper_fits_on(made) -> None:
    """At 1.6 N·m the six packages' square inch of copper each, 6 × 6.45 = 38.7 cm², is what
    sets the board: the search closes on that edge from above, and 39 cm² is offered."""
    ws, start = made
    offer = ask(ws, start, cooling="board", board_area="", rth_ja=40, t_ambient=40)
    assert offer["exact"] == pytest.approx(6 * 6.45, rel=1e-3) and offer["exact"] >= 6 * 6.45
    assert offer["value"] == 39.0


def test_a_board_that_no_area_saves_is_said_to_need_a_heatsink(made) -> None:
    ws, start = made
    offer = ask(
        ws, start, cooling="board", board_area="", rth_ja=40, t_ambient=40, torque=start["conditions"]["torque"] * 4
    )
    assert offer["value"] is None and "needs a heatsink" in offer["why"]


@pytest.mark.parametrize(
    ("x", "down", "up"), [(4.3828, 4.3, 4.4), (0.76803, 0.76, 0.77), (38.716, 38.0, 39.0), (1234.5, 1200.0, 1300.0)]
)
def test_an_offer_is_rounded_to_two_figures_on_the_safe_side(x, down, up) -> None:
    assert (_down(x), _up(x)) == (down, up)
    assert math.isclose(_down(4.3), 4.3) and _down(4.3) == 4.3


@pytest.mark.parametrize(
    ("cooling", "figure", "value", "said"),
    [
        ("heatsink", "rth_sink", 4.3, "the heatsink's 4.3 K/W was sized by the tool"),
        ("board", "board_area", 39, "the board's 39 cm² was sized by the tool"),
    ],
)
def test_a_cooling_taken_from_the_offer_holds_the_verdict_at_a_caution_and_says_so(
    made, cooling, figure, value, said
) -> None:
    ws, start = made
    common = {"cooling": cooling, figure: value, "rth_ja": 40, "t_ambient": 40}
    plain = candidate(ws, start, **common)
    sized = candidate(ws, start, **common, sized=figure)
    told = [c for c in sized["checks"] if c.get("field") == figure]
    assert len(told) == 1 and told[0]["level"] == "caution" and told[0]["topic"] == "data"
    assert told[0]["message"].startswith(said)
    assert sized["result"]["loss"] == plain["result"]["loss"]  # the figures are the same; only the verdict is held
    assert sized["level"] in ("caution", "undecided", "fail")


def test_sized_said_of_another_cooling_is_left_alone_and_a_name_it_does_not_hold_is_refused(made) -> None:
    ws, start = made
    held = candidate(ws, start, cooling="held", t_sink=60, sized="rth_sink")
    assert not [c for c in held["checks"] if c.get("field") == "rth_sink"]
    status, body = page.dispatch(
        "/api/proposal",
        {"motor": start["motor"], "conditions": {**start["conditions"], "sized": "t_sink"}, "devices": ["example"]},
        ws,
    )
    assert status == 422 and body["field"] == "sized"


@pytest.mark.parametrize(
    ("cooling", "figure", "value", "said"),
    [
        ("heatsink", "rth_sink", 4.3, "the heatsink's 4.3 K/W was sized by the tool for an earlier design point"),
        ("board", "board_area", 39, "the board's 39 cm² was sized by the tool for an earlier design point"),
    ],
)
def test_a_cooling_sized_for_an_earlier_point_is_said_to_be_and_still_holds_the_verdict(
    made, cooling, figure, value, said
) -> None:
    """The design point moved after the cooling was sized: the verdict does not say it was
    sized here, or from the loss worked out here, and it is still held at a caution."""
    ws, start = made
    common = {"cooling": cooling, figure: value, "rth_ja": 40, "t_ambient": 40, "sized": figure}
    here = candidate(ws, start, **common)
    earlier = candidate(ws, start, **common, sized_earlier=True)
    (told,) = [c for c in earlier["checks"] if c.get("field") == figure]
    assert told["level"] == "caution" and told["message"].startswith(said)
    assert "worked out here" not in told["message"] and "at this design point" not in told["message"]
    assert "size it again" in told["message"].lower()
    assert earlier["level"] in ("caution", "undecided", "fail")
    assert earlier["result"]["loss"] == here["result"]["loss"]
    (now,) = [c for c in here["checks"] if c.get("field") == figure]
    assert "earlier" not in now["message"]


def test_sized_earlier_is_refused_when_it_is_not_a_yes_or_a_no(made) -> None:
    ws, start = made
    status, body = page.dispatch(
        "/api/proposal",
        {
            "motor": start["motor"],
            "conditions": {**start["conditions"], "sized": "", "sized_earlier": "maybe"},
            "devices": ["example-mosfet"],
        },
        ws,
    )
    assert status == 422 and body["field"] == "sized_earlier"
