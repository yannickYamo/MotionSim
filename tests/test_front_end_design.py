"""A design file fed from the mains: its front end worked out before every other step, the
link voltage taken from it, and the control command's request carrying the mains."""

from __future__ import annotations

import pytest
from test_control_bench import started, workspace

from motionsim import design
from motionsim.errors import Refusal


@pytest.fixture(scope="module")
def ws():
    return workspace()


@pytest.fixture(scope="module")
def setup(ws) -> dict:
    base = started("example-sic", ws)
    return {
        "devices": ["example-sic"],
        "motor": base["motor"],
        "conditions": {k: v for k, v in base["conditions"].items() if k != "v_dc"},
        "supply": "mains",
        "mains": {"v": 230, "f": 50, "phases": 1},
    }


def test_the_link_is_the_recommended_stage_s_and_every_step_runs_on_it(ws, setup) -> None:
    out = design.run(setup, ws, steps=("build",))
    assert out["outcome"] in ("passes", "passes with cautions") and "refusals" not in out
    assert out["front_end"]["chosen"] == out["front_end"]["recommended"] == "totem_pole"
    # No link voltage was given: 1.2 times the mains' crest, to 10 V.
    assert out["setup"]["conditions"]["v_dc"] == 390.0
    assert out["setup"]["front_end"] == {"topology": "totem_pole"} and out["setup"]["mains"]["v"] == 230
    said = design.markdown(out)
    section = said[said.index("## Front end") : said.index("## What to build")]
    assert "Totem-pole PFC on 230 V, 50 Hz, one phase" in section and "holds the DC link at 390 V" in section
    assert "power factor 1" in section


def test_a_stage_and_a_link_given_in_the_design_are_the_ones_used(ws, setup) -> None:
    own = setup | {"conditions": setup["conditions"] | {"v_dc": 380}, "front_end": {"topology": "boost"}}
    out = design.run(own, ws, steps=())
    assert out["front_end"]["chosen"] == "boost" and out["front_end"]["v_dc_given"] is True
    assert out["setup"]["conditions"]["v_dc"] == 380.0
    said = design.markdown(out)
    assert "chosen in the design" in said and "(given in the design)" in said


def test_a_rectifier_says_its_harmonics_in_the_report(ws, setup) -> None:
    out = design.run(setup | {"front_end": {"topology": "rectifier"}}, ws, steps=())
    assert out["setup"]["conditions"]["v_dc"] == pytest.approx(0.95 * 230 * 2**0.5, rel=0.02)
    assert "over the harmonic limits of IEC 61000-3-2 class A" in design.markdown(out)


def test_a_stage_that_cannot_be_is_the_design_s_refusal(ws, setup) -> None:
    out = design.run(setup | {"front_end": {"topology": "vienna"}}, ws, steps=())
    assert out["outcome"] == "refused" and out["refusals"] == ["front_end"]
    assert out["field"] == "front_end.topology" and "verdict" not in out


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"mains": None}, "mains.v"),
        ({"supply": "battery"}, "mains"),
        ({"front_end": {"kind": "boost"}}, "front_end"),
        ({"mains": {"v": 230, "hz": 50}}, "mains"),
    ],
)
def test_a_mains_that_is_not_one_is_refused_before_any_step(ws, setup, change, field) -> None:
    with pytest.raises(Refusal) as refused:
        design.run(setup | change, ws, steps=())
    assert refused.value.field == field


def test_a_design_on_a_supply_is_as_it_was(ws, setup) -> None:
    plain = {k: v for k, v in setup.items() if k not in ("mains", "supply")}
    plain["conditions"] = plain["conditions"] | {"v_dc": 325}
    out = design.run(plain, ws, steps=())
    assert "front_end" not in out and out["setup"]["supply"] == "one-way" and "mains" not in out["setup"]
    assert "## Front end" not in design.markdown(out)


def test_the_control_command_s_request_carries_the_mains(ws, setup, tmp_path) -> None:
    import argparse

    import yaml

    from motionsim.cli.control import _request

    path = tmp_path / "drive.yaml"
    path.write_text(yaml.safe_dump(setup), encoding="utf-8")
    request = _request(argparse.Namespace(setup=str(path), device=None), ws)
    assert request["supply"] == "mains" and request["mains"] == {"v": 230, "f": 50, "phases": 1}
    assert request["front_end"] == {"topology": "totem_pole"} and request["conditions"]["v_dc"] == 390.0
