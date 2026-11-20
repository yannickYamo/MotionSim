"""A measurement that cannot be used is refused in words, with the figure at issue: never the
validator's own text or the address of a page about it."""

from __future__ import annotations

import pytest

from motionsim import page

GOOD = '{"v_dc": 300, "energy_unit": "uJ", "points": [{"tj": 25, "current": 10, "e_on": %s, "e_off": 200}]}'


@pytest.fixture
def workspace(tmp_path):
    return page.Workspace(tmp_path)


@pytest.mark.parametrize("figure", ["NaN", "Infinity", "-Infinity", '"many"', "-5"])
def test_a_measurement_with_a_figure_that_is_not_one_is_refused_in_words(workspace, figure) -> None:
    with pytest.raises(page.Refused) as refused:
        page.add_measurement("example", "bench.json", GOOD % figure, workspace)
    said = refused.value.reason
    assert said.startswith("that file is not double-pulse data")
    for leak in ("http", "pydantic", "input_value", "type=", "[", "errors.pydantic"):
        assert leak not in said, said
    assert "e_on" in said or "turn-on" in said.lower()


def test_through_the_route_it_is_a_refusal_with_no_validator_words(workspace) -> None:
    import json

    asked = json.dumps({"device": "example", "name": "b.json", "text": GOOD % "NaN"})
    answer = json.loads(page.call("/api/measure", asked, workspace))
    status, body = answer["status"], answer["body"]
    assert status == 422
    assert "http" not in body["refused"] and "pydantic" not in body["refused"]
