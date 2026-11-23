"""The switching event always ends: figures whose edge does not settle are refused with the
figure at fault, a very small loop is followed in a bounded number of steps, and the events
that ended before are the same events."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from motionsim import design, page
from motionsim.event import run
from motionsim.service.workspace import EXAMPLES

# A robot joint's motor on 48 V at 20 kHz, with no edge limit: the request a page sent with a
# 600 V, 30 A IGBT and 30 nH typed for the common-source inductance.
JOINT = {
    "motor": {
        "type": "pmsm",
        "magnets": "surface",
        "pole_pairs": 7,
        "kv": 78.12,
        "l": 0.00007071,
        "rs": 0.02525,
        "i_max": 63.36,
    },
    "conditions": {
        "v_dc": 48,
        "rpm": 3000,
        "torque": 4.74,
        "f_sw": 20000,
        "t_sink": 60,
        "t_min_pulse": 0,
        "parallel": 1,
        "edge_limit": "none",
        "cooling": "held",
        "t_ambient": 40,
    },
    "supply": "one-way",
}
FIGURES = ("energy", "factor", "recovery", "i_peak", "v_peak", "di_dt", "dv_dt", "t_delay", "tail")


@pytest.fixture
def ws(tmp_path):
    return page.Workspace(Path(tmp_path))


def ask(ws, body: dict) -> dict:
    return json.loads(page.call("/api/event", json.dumps(body), ws))


def default_event(ws, key: str, **conditions) -> dict:
    start = design.starting_setup(key, ws)
    return ask(ws, {**start, "conditions": {**start["conditions"], **conditions}, "device": key})


@pytest.mark.timeout(60)
def test_a_common_source_inductance_that_is_the_whole_loop_is_refused_by_its_name(ws) -> None:
    """With all 30 nH of the loop shared with the gate, the loop's ringing lifts the gate past
    its threshold each cycle and never dies: there is no settled edge to draw, and the refusal
    says which figure to change."""
    got = ask(ws, {**JOINT, "device": "example", "event": {"l_cs_nh": "30"}})
    assert got["status"] == 422, got["body"].get("turn_off", got["body"])
    assert got["body"]["field"] == "l_cs"
    assert got["body"]["refused"].startswith("the switching event could not be followed to its end")
    assert "30 nH of common-source inductance" in got["body"]["refused"]
    assert "smaller common-source inductance" in got["body"]["fix"]


@pytest.mark.timeout(240)
def test_the_igbt_at_the_least_loop_inductance_gives_an_event(ws) -> None:
    """At 0.1 nH the loop rings thousands of times within the time its gate takes: the edge is
    still followed in a bounded number of steps. So small a loop stores next to nothing, and
    the voltage does not overshoot the supply as it does in the part's usual 30 nH."""
    got = default_event(ws, "example", l_loop=0.1e-9)
    assert got["status"] == 200, got
    body = got["body"]
    assert body["used"]["l_loop"] == pytest.approx(0.1e-9)
    for edge in ("turn_on", "turn_off"):
        assert body[edge]["met"], body["notes"]
    stored = 0.5 * 0.1e-9 * body["current"] ** 2
    assert stored < 1e-4 * body["turn_off"]["target"]
    assert body["turn_off"]["v_peak"] < 1.01 * body["v_dc"]


@pytest.mark.parametrize("key", list(EXAMPLES))
def test_the_step_rule_and_the_budget_leave_a_made_up_parts_event_as_it_was(ws, key, monkeypatch) -> None:
    """The second path: the same event with no least step and no budget, which is how every
    event was worked out before. An event of the usual kind never meets either."""
    now = default_event(ws, key)["body"]
    monkeypatch.setattr(run, "FINEST", math.inf)
    monkeypatch.setattr(run, "BUDGET", math.inf)
    before = default_event(ws, key)["body"]
    for edge in ("turn_on", "turn_off"):
        assert now[edge]["t"] == before[edge]["t"]
        for name in FIGURES:
            was = before[edge][name]
            # A figure an edge does not have (no ringing found, no tail) is absent on both paths.
            if was is None:
                assert now[edge][name] is None, (edge, name)
            else:
                assert now[edge][name] == pytest.approx(was, rel=1e-9), (edge, name)


@pytest.mark.parametrize(
    "given, field, said",
    [
        ({}, "l_loop", "the edge does not settle in a commutation loop of 20 nH"),
        ({"l_g_nh": "5"}, "l_g", "the gate does not settle with 5 nH of gate-loop inductance"),
        ({"l_g_nh": "5", "l_cs_nh": "1.5"}, "l_cs", "the gate loop does not settle with 1.5 nH of common-source"),
    ],
)
def test_an_edge_past_its_budget_is_refused_with_the_figure_most_likely_at_fault(
    ws, monkeypatch, given, field, said
) -> None:
    """With a budget no edge can meet, the path every runaway edge takes: a refusal in words,
    the inductance the gate shares named first, then the gate loop's own, then the loop's."""
    monkeypatch.setattr(run, "BUDGET", 300)
    start = design.starting_setup("example-mosfet", ws)
    got = ask(ws, {**start, "device": "example-mosfet", "event": given})
    assert got["status"] == 422, got
    assert got["body"]["field"] == field
    assert said in got["body"]["refused"]
    assert got["body"]["fix"]


def test_the_budget_counts_what_the_equations_are_asked_and_not_time(monkeypatch) -> None:
    """The same count on every machine: an edge is refused on the first asking past the budget."""
    from motionsim.event.circuit import Capacitance, Circuit, Gate, Loop, Reverse, Switch

    c_oss = Capacitance(1e-9, 2.0)
    circuit = Circuit(
        Loop(48.0, 20.0, 20e-9, 0.0),
        Gate(10.0, 0.0, 5.0, 0.0, 2e-9, Capacitance(0.5e-9, 1.0), 3.0, 8.0),
        Switch(c_oss, 5e-3),
        Reverse(c_oss, 0.8, 5e-3, 0.0, 1e-12),
    )
    asked = []
    rates = run.rates
    monkeypatch.setattr(run, "rates", lambda *a: asked.append(1) or rates(*a))
    monkeypatch.setattr(run, "BUDGET", 250)
    with pytest.raises(run.Refusal) as refused:
        run.edge_wave(circuit, "off", 5.0)
    assert refused.value.field == "l_loop"
    assert len(asked) == 250
