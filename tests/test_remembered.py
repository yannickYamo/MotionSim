"""Answers kept for a while: the report reuses what the page has just asked for, never an answer
for other figures or for a device as it was before it changed, and the store stays small."""

from __future__ import annotations

import pytest

from motionsim import design, page
from motionsim.service import remembered, routes


@pytest.fixture()
def workspace(tmp_path) -> page.Workspace:
    return page.Workspace(tmp_path)


def _counting(calls: list[dict]):
    def work(data, ws):
        calls.append(data)
        return {"answer": [len(calls)], "asked": data.get("x")}

    return remembered.remembered("/api/test", work)


def test_the_same_request_is_answered_from_what_was_kept(workspace) -> None:
    calls: list[dict] = []
    work = _counting(calls)
    first = work({"x": 1, "y": None}, workspace)
    # The same request written another way: its names in another order, a name given as
    # nothing left out, a number as text, as the page sends what was typed.
    again = work({"y": None, "x": "1"}, workspace)
    also = work({"x": 1.0}, workspace)
    assert first == again == also == {"answer": [1], "asked": 1}
    assert len(calls) == 1 and remembered.counts == {"hits": 2, "misses": 1}


def test_an_answer_changed_by_whoever_was_given_it_is_not_changed_in_the_store(workspace) -> None:
    work = _counting([])
    given = work({"x": 1}, workspace)
    given["answer"].append("changed")
    again = work({"x": 1}, workspace)
    again["answer"].append("changed again")
    assert work({"x": 1}, workspace) == {"answer": [1], "asked": 1}


def test_other_figures_or_another_address_are_worked_out_afresh(workspace) -> None:
    calls: list[dict] = []
    work = _counting(calls)
    work({"x": 1}, workspace)
    work({"x": 2}, workspace)
    work({"x": 1, "z": 0}, workspace)
    other = remembered.remembered("/api/other", lambda data, ws: {"other": True})
    assert other({"x": 1}, workspace) == {"other": True}
    assert len(calls) == 3


def test_a_device_added_or_changed_is_another_key(workspace, tmp_path) -> None:
    calls: list[dict] = []
    work = _counting(calls)
    work({"x": 1}, workspace)
    part = tmp_path / "mine.device.yaml"
    part.write_text("vendor: A\n", encoding="utf-8")
    work({"x": 1}, workspace)
    part.write_text("vendor: B\n", encoding="utf-8")  # the same name, another part
    work({"x": 1}, workspace)
    part.write_text("vendor: A\n", encoding="utf-8")
    work({"x": 1}, workspace)
    assert len(calls) == 3  # the last is the part of the second request again


def test_another_workspace_is_another_key(tmp_path) -> None:
    calls: list[dict] = []
    work = _counting(calls)
    work({"x": 1}, page.Workspace(tmp_path / "one"))
    work({"x": 1}, page.Workspace(tmp_path / "two"))
    assert len(calls) == 2


def test_a_refusal_is_not_kept(workspace) -> None:
    calls: list[int] = []

    def refuses(data, ws):
        calls.append(1)
        raise page.Refusal("no", "fix", "x")

    work = remembered.remembered("/api/refuses", refuses)
    for _ in range(2):
        with pytest.raises(page.Refusal):
            work({}, workspace)
    assert len(calls) == 2


def test_the_store_keeps_no_more_than_its_bound_and_lets_the_oldest_used_go(workspace) -> None:
    calls: list[dict] = []
    work = _counting(calls)
    for x in range(remembered.MOST):
        work({"x": x}, workspace)
    work({"x": 0}, workspace)  # used again: now the newest
    work({"x": "past the bound"}, workspace)  # the oldest used goes: x = 1
    assert len(remembered._kept) == remembered.MOST
    asked = len(calls)
    work({"x": 0}, workspace)
    assert len(calls) == asked
    work({"x": 1}, workspace)
    assert len(calls) == asked + 1


def _as_the_page_asks(workspace) -> tuple[dict, dict]:
    """A design as the page sends it: every condition named, those not given as nothing."""
    s = design.starting_setup("example-mosfet", workspace)
    conditions = {
        **{k: None for k in ("pwm", "v_drive", "rg_on", "rg_off", "t_dead", "l_loop", "rth_sink", "rth_ja")},
        **{k: None for k in ("board_area", "copper", "copper_ref", "interface", "rth_case_sink")},
        **s["conditions"],
        "t_min_pulse": 0,
        "t_ambient": 40,
    }
    base = {"motor": {**s["motor"], "t_motor": None}, "conditions": conditions, "supply": s["supply"]}
    motion = {
        "load": s["load"],
        "profile": s["profile"],
        "mission": None,
        "heatsink": {"rth": None, "capacity": None, "t_ambient": 60},
        "c_link": None,
        "precharge": None,
        "start": {},
        "repeats": 1,
    }
    return base, motion


def test_the_report_reuses_what_the_page_asked_for_and_says_the_same(workspace) -> None:
    base, motion = _as_the_page_asks(workspace)
    asked = {**base, **motion, "devices": ["example-mosfet"], "follow": "example-mosfet"}
    alone = routes.dispatch("/api/report", asked, workspace)
    remembered.forget()
    for route, data in (
        ("/api/proposal", {**base, "devices": ["example-mosfet"]}),
        ("/api/cycle", {**base, "device": "example-mosfet", **motion}),
        ("/api/capability", {**base, "device": "example-mosfet"}),
        ("/api/recommend", {**base, "device": "example-mosfet", "t_ambient": 40}),
    ):
        assert routes.dispatch(route, data, workspace)[0] == 200
    assert remembered.counts == {"hits": 0, "misses": 4}
    after = routes.dispatch("/api/report", asked, workspace)
    # The design point, its motion, what it can drive and what to build around it: all four
    # come from what was kept. The fit of the motor the page asks in its own words, and it
    # is worked out again.
    assert remembered.counts["hits"] == 4
    assert after == alone
