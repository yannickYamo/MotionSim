"""The page's design as the server reads and writes it for the agent: the same request the
page's state.ts makes, the page's key as JSON.stringify writes it, and a figure set as the
page's box sets it, the user's own from then on."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from motionsim.app import pagestate
from motionsim.errors import Refusal
from motionsim.service.presets import setup as setup_of
from motionsim.service.workspace import Workspace


@pytest.fixture(scope="module")
def setup(tmp_path_factory) -> dict:
    return setup_of(Workspace(tmp_path_factory.mktemp("devices")))


@pytest.mark.parametrize(
    ("value", "said"),
    [
        (0, "0"),
        (400, "400"),
        (0.1, "0.1"),
        (1.5e-7, "1.5e-7"),
        (2.0000000000000002e-7, "2.0000000000000002e-7"),
        (1e-6, "0.000001"),
        (1e21, "1e+21"),
        (123456789012345680000.0, "123456789012345680000"),
        (-2.5, "-2.5"),
        (16000.0, "16000"),
    ],
)
def test_a_number_is_written_as_javascript_writes_it(value, said) -> None:
    assert pagestate.js_stringify(value) == said


def test_the_page_key_is_compact_json_in_the_order_of_its_keys() -> None:
    assert pagestate.js_stringify({"b": [1, None, "x"], "a": {"c": True}}) == '{"b":[1,null,"x"],"a":{"c":true}}'


def test_the_request_is_the_one_state_ts_makes_of_a_first_visit(setup) -> None:
    state = pagestate.initial(setup)
    state["conditions"]["t_dead_ns"] = "200"
    req = pagestate.request(state)
    start = setup["motors"]["pmsm"]["start"]
    assert req["motor"]["type"] == "pmsm" and req["motor"]["t_motor"] is None
    assert req["conditions"]["f_sw"] == start["f_sw"]
    assert req["conditions"]["t_dead"] == pytest.approx(2e-7)
    assert req["conditions"]["parallel"] == 1 and req["supply"] == "one-way"
    motion = pagestate.motion_request(state)
    assert motion["profile"]["segments"] == setup["profile"]["segments"]
    assert motion["load"]["gravity"] == setup["load"]["gravity"]


def test_a_figure_set_is_the_users_own_and_the_starting_point_leaves_it_be(setup) -> None:
    state = pagestate.initial(setup)
    paths = pagestate.set_fields(state, {"v_dc": 60, "f_sw": 12000, "motor.rs": 0.1, "supply": "battery"}, setup)
    assert paths == ["conditions.v_dc", "conditions.f_khz", "motors.pmsm.rs", "supply"]
    assert state["conditions"]["f_khz"] == 12
    assert state["pointOf"]["pmsm"] == {"v_dc": 60, "f_khz": 12}
    assert state["motorOwn"]["pmsm"] == ["rs"] and state["supplyOwn"] is True
    pagestate.settle(state, setup, None)
    assert state["conditions"]["v_dc"] == 60 and state["motors"]["pmsm"]["rs"] == 0.1


def test_a_figure_that_cannot_be_is_refused_by_its_name_and_nothing_is_set(setup) -> None:
    state = pagestate.initial(setup)
    for fields, field in (({"v_dc": True}, "v_dc"), ({"parallel": 1.5}, "parallel"), ({"pwm": "square"}, "pwm")):
        with pytest.raises(Refusal) as refused:
            pagestate.set_fields(state, {"rpm": 10, **fields}, setup)
        assert refused.value.field == field
    assert state == pagestate.initial(setup)


def test_the_design_file_names_the_part_the_design_starts_from_first(setup) -> None:
    state = pagestate.initial(setup)
    state["devices"], state["lead"] = ["a", "b"], "b"
    design = pagestate.design_of(state)
    assert design["devices"] == ["b", "a"] and "t_motor" not in design["motor"]


def test_the_wheel_has_the_agent_guide_the_server_offers() -> None:
    assert (Path(pagestate.__file__).parents[1] / "AGENT_GUIDE.md").is_file()


def test_the_sets_that_move_as_one_are_the_pages_own() -> None:
    """pagestate.UNITS and the page's list (web/src/session/units.ts) are the same."""
    text = (Path(__file__).parents[1] / "web/src/session/units.ts").read_text()
    body = text.split("// units:begin", 1)[1].split("// units:end", 1)[0]
    literal = body.split("=", 1)[1].strip().rstrip(";")
    page = json.loads(re.sub(r",(\s*[\]}])", r"\1", literal))
    assert [tuple(u) for u in page] == list(pagestate.UNITS)


def test_parts_on_the_page_and_none_ticked_are_mended_with_the_lead_else_the_first() -> None:
    s = {"added": ["x", "y"], "devices": [], "lead": "y"}
    assert pagestate.parts_held(s) and (s["devices"], s["lead"]) == (["y"], "y")
    s = {"added": ["x", "y"], "devices": [], "lead": ""}
    assert pagestate.parts_held(s) and (s["devices"], s["lead"]) == (["x"], "x")
    for s in ({"added": [], "devices": [], "lead": ""}, {"added": ["x"], "devices": ["x"], "lead": "x"}):
        assert not pagestate.parts_held(dict(s))
