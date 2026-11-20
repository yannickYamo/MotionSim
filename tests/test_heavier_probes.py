"""The search for the largest load, probe by probe: what each probe says as it finishes, and
an answer that is the one the search gave before it said anything."""

from __future__ import annotations

import pytest

from motionsim import page
from motionsim.errors import Refusal
from motionsim.service.motion import heavier
from motionsim.service.motion.heavier import _tried, largest, search


def _before(data: dict, workspace) -> dict:
    """The search as it was written before it reported its probes: kept here word for word, so
    that the answer the probes end in can be held to it."""

    def tried(k: float, coarse: bool = True):
        return _tried(data, workspace, k, coarse)

    fine, why, at = tried(1.0)
    if not fine:
        low, high = 0.0, 1.0
    else:
        low, high = 1.0, 2.0
        for _ in range(9):
            fine, why_high, found = tried(high)
            if not fine:
                why = why_high
                break
            low, at, high = high, found, 2 * high
        else:
            return {
                "scale": low,
                "open": True,
                "why": "",
                "peak": (at or {})["summary"]["peak"],
                "tj_max": (at or {})["summary"]["tj_max"],
            }
    for _ in range(6):
        middle = (low + high) / 2
        fine, why_middle, found = tried(middle)
        if fine:
            low, at = middle, found
        else:
            high, why = middle, why_middle
    if low > 0:
        fine, _, full = tried(low, coarse=False)
        at = full if fine else at
    return {
        "scale": low,
        "open": False,
        "why": why,
        "peak": None if at is None else at["summary"]["peak"],
        "tj_max": None if at is None else at["summary"]["tj_max"],
    }


def _request(workspace, preset: str = "conveyor") -> dict:
    motors = page.setup(workspace)["motors"]
    start = page.STARTING["pmsm"]
    load = next(p for p in page.load_presets("pmsm", start["rpm"], start["torque"]) if p["id"] == preset)
    return {
        "motor": {"type": "pmsm", **motors["pmsm"]["values"]},
        "conditions": {**start, "t_sink": 60},
        "supply": "battery",
        "device": "example",
        "load": load["load"],
        "profile": load["profile"],
    }


def _drained(data: dict, workspace) -> tuple[list[dict], dict]:
    probes = []
    found = search(data, workspace)
    while True:
        try:
            probes.append(next(found))
        except StopIteration as done:
            return probes, done.value


@pytest.fixture()
def workspace(tmp_path) -> page.Workspace:
    return page.Workspace(tmp_path)


def test_the_answer_the_probes_end_in_is_the_one_the_search_gave_before(workspace) -> None:
    data = _request(workspace)
    probes, answer = _drained(data, workspace)
    assert answer == _before(data, workspace) == largest(data, workspace)
    assert probes, "a search that reports nothing"


def test_each_probe_is_one_step_of_the_halving_in_the_order_it_is_tried(workspace, monkeypatch) -> None:
    """With what passes decided by hand, the scales the search tries are known in advance: it
    passes up to 2.7 times. 1 passes, 2 passes, 4 fails, then halving between 2 and 4:
    3 fails, 2.5 passes, 2.75 fails, 2.625 passes, 2.6875 passes, 2.71875 fails, and the
    answer, 2.6875, worked out in full."""
    calls: list[tuple[float, bool]] = []

    def tried(data, ws, k, coarse=True):
        calls.append((k, coarse))
        fine = k <= 2.7
        summary = {"peak": 100.0 + 20 * k, "tj_max": 150.0}
        return fine, "" if fine else "junction too hot", {"summary": summary, "checks": []}

    monkeypatch.setattr(heavier, "_tried", tried)
    probes, answer = _drained({"load": {}}, workspace)
    scales = [1.0, 2.0, 4.0, 3.0, 2.5, 2.75, 2.625, 2.6875, 2.71875, 2.6875]
    assert [p["scale"] for p in probes] == scales == [k for k, _ in calls]
    assert [p["passes"] for p in probes] == [True, True, False, False, True, False, True, True, False, True]
    assert [p["full"] for p in probes] == [False] * 9 + [True]
    assert probes[2] == {
        "scale": 4.0,
        "passes": False,
        "full": False,
        "why": "junction too hot",
        "peak": 180.0,
        "tj_max": 150.0,
        "low": 2.0,
        "high": 4.0,
    }
    # The bounds as they stand after each probe: what the page says the answer lies between.
    assert [(p["low"], p["high"]) for p in probes[3:5]] == [(2.0, 3.0), (2.5, 3.0)]
    assert answer == {"scale": 2.6875, "open": False, "why": "junction too hot", "peak": 153.75, "tj_max": 150.0}


def test_a_load_already_too_much_reports_its_probes_down_from_one(workspace, monkeypatch) -> None:
    def tried(data, ws, k, coarse=True):
        return k <= 0.3, "too hot", None

    monkeypatch.setattr(heavier, "_tried", tried)
    probes, answer = _drained({"load": {}}, workspace)
    assert [p["scale"] for p in probes] == [1.0, 0.5, 0.25, 0.375, 0.3125, 0.28125, 0.296875, 0.296875]
    assert probes[0]["peak"] is None and probes[0]["passes"] is False
    assert answer["scale"] == 0.296875 and answer["peak"] is None


def test_a_search_given_up_works_out_nothing_more(workspace, monkeypatch) -> None:
    tried_at: list[float] = []

    def tried(data, ws, k, coarse=True):
        tried_at.append(k)
        return True, "", {"summary": {"peak": 50.0, "tj_max": 150.0}, "checks": []}

    monkeypatch.setattr(heavier, "_tried", tried)
    found = search({"load": {}}, workspace)
    next(found)
    next(found)
    found.close()
    assert tried_at == [1.0, 2.0]


def test_a_load_that_does_not_fit_is_refused_before_any_probe(workspace) -> None:
    found = search({"load": {"inertia": "heavy"}}, workspace)
    with pytest.raises(Refusal):
        next(found)
