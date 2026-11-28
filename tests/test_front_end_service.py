"""The front end as the page asks for it: every stage for the mains solved on the design, one
recommended with its reason, the chosen one in full."""

from __future__ import annotations

import pytest
from test_control_bench import started, workspace

from motionsim.service.routes import dispatch
from motionsim.service.validate import supply

ONE = {"v": 230, "f": 50, "phases": 1}
THREE = {"v": 400, "f": 50, "phases": 3}


@pytest.fixture(scope="module")
def ws():
    return workspace()


def asked(ws, key: str, mains: dict, **more) -> tuple[int, dict]:
    base = started(key, ws)
    return dispatch(
        "/api/front-end", {k: base[k] for k in ("motor", "conditions", "device")} | {"mains": mains} | more, ws
    )


def test_every_stage_for_the_mains_is_solved_and_one_is_recommended(ws) -> None:
    status, body = asked(ws, "example-sic", ONE)
    assert status == 200
    assert [c["id"] for c in body["choices"]] == ["rectifier", "boost", "interleaved", "totem_pole"]
    assert all(c["loss"] > 0 and 0.9 < c["efficiency"] < 1 for c in body["choices"])
    # A silicon-carbide part: the totem-pole loses the least, and the reason says against what.
    assert body["recommended"] == body["chosen"] == "totem_pole"
    assert "W lost against" in body["why"] and "reverse recovery is small enough" in body["why"]
    assert body["v_dc"] == 390.0 and body["v_dc_given"] is False
    result = body["result"]
    assert result["level"] == "ok" and result["positions"] == 4
    assert {c["topic"] for c in result["checks"]} >= {"voltage", "temperature", "mains current"}
    assert any(c["message"].startswith("the link is 60%") for c in result["checks"])
    assert result["p_in"] == pytest.approx(result["p_link"] + result["loss"], rel=1e-3)
    assert result["inductor"]["henry"] > 0 and result["capacitor"]["slow"] > 0


def test_the_user_s_choice_is_the_one_worked_out(ws) -> None:
    status, body = asked(ws, "example-sic", ONE, front_end={"topology": "boost", "f_sw": 100e3})
    assert status == 200 and body["chosen"] == "boost" and body["recommended"] == "totem_pole"
    assert body["result"]["f_sw"] == 100e3 and body["result"]["loss_diodes"] > 0
    assert any("boost diode" in n for n in body["result"]["notes"])


def test_a_rectifier_is_said_to_miss_the_limit_and_is_not_recommended(ws) -> None:
    _, body = asked(ws, "example-sic", ONE, front_end={"topology": "rectifier"})
    plain = body["result"]
    assert plain["within_limit"] is False and plain["level"] == "caution"
    said = next(c["message"] for c in plain["checks"] if c["topic"] == "mains current")
    assert "harmonic 3" in said and "2.30 A" in said and "power factor" in said
    assert body["v_dc"] == pytest.approx(0.95 * 230 * 2**0.5, rel=0.02)
    assert plain["capacitor"]["sized"] is True and plain["harmonics"][0]["order"] == 3


def test_three_phases_have_their_own_stages(ws) -> None:
    status, body = asked(ws, "example-sic", THREE)
    assert status == 200
    assert [c["id"] for c in body["choices"]] == ["six_pulse", "vienna", "active"]
    # About a kilowatt on three phases: six diodes stay within the limits, and are the stage to have.
    assert body["recommended"] == "six_pulse" and "within the harmonic limits" in body["why"]
    # The motion brakes: the stage that gives the energy back, where one passes with this part.
    _, braking = asked(ws, "example-sic-module", THREE, brakes=True)
    assert braking["recommended"] == "active" and "gives that energy back" in braking["why"]
    # A 650 V part cannot be a two-level stage on a 680 V link, and the list says so.
    assert next(c for c in body["choices"] if c["id"] == "active")["level"] == "fail"
    assert next(c for c in body["choices"] if c["id"] == "vienna")["level"] == "ok"


def test_the_link_held_as_low_as_the_motor_needs_is_offered_with_its_saving(ws) -> None:
    _, body = asked(ws, "example-sic", ONE)
    lever = body["lever"]
    assert lever["from"] == 390.0 and lever["v_dc"] == 375.0 and lever["saves"] > 1.0
    # Taken, it is what the stage holds, and nothing further is offered.
    _, lower = asked(ws, "example-sic", ONE, front_end={"v_dc": 375})
    assert lower["v_dc"] == 375.0 and lower["v_dc_given"] is True and lower["lever"] is None
    assert lower["result"]["loss"] < body["result"]["loss"]


def test_what_cannot_be_is_refused_with_its_box(ws) -> None:
    status, body = asked(ws, "example-sic", ONE, front_end={"topology": "vienna"})
    assert status == 422 and body["field"] == "front_end.topology" and "one phase" in body["refused"]
    status, body = asked(ws, "example-sic", {"v": 5})
    assert status == 422 and body["field"] == "mains.v"
    status, body = asked(ws, "example-sic", ONE, front_end={"topology": "boost", "v_dc": 300})
    assert status == 422 and "above the mains' peak" in body["refused"]


def test_a_front_end_that_returns_energy_takes_braking_as_a_battery_does() -> None:
    assert supply({"supply": "mains", "front_end": {"topology": "active"}}) == "battery"
    assert supply({"supply": "mains", "front_end": {"topology": "totem_pole"}}) == "battery"
    assert supply({"supply": "mains", "front_end": {"topology": "boost"}}) == "one-way"
    assert supply({"supply": "mains"}) == "one-way"


def test_one_phase_asked_for_more_than_it_gives_is_said_and_three_phases_are_not(ws) -> None:
    # The made-up module's own point is 73.5 kW: hundreds of amperes from one phase.
    _, one = asked(ws, "example-sic-module", ONE)
    said = [c["message"] for c in one["result"]["checks"] if c["level"] != "ok"]
    assert any("fed from three phases" in m for m in said), said
    _, three = asked(ws, "example-sic-module", THREE)
    assert not any("fed from three phases" in c["message"] for c in three["result"]["checks"])
    # A drive of a kilowatt on one phase is not told so.
    _, small = asked(ws, "example-sic", ONE)
    assert not any("fed from three phases" in c["message"] for c in small["result"]["checks"])
