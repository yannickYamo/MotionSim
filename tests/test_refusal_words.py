"""A refusal is a plain sentence a person reads, with the figure it is about given apart.

The page puts the sentence by the box it names and turns its limits into the unit of the
box. So no refusal carries the validator's own words, the address of a page about them or a
figure's name in code, and every limit is said with its unit.
"""

from __future__ import annotations

import json
import re

import pytest

from motionsim import design, page
from motionsim.errors import Refusal

# What a validator says that a person should never be shown.
VALIDATOR = re.compile(
    r"Input should|Value error|validation error|pydantic|type=|Field required|errors\.pydantic|"
    r"\b[a-z]+_[a-z_]+\b"  # a name in code, such as pole_pairs or i_nominal
)


@pytest.fixture
def ws(tmp_path):
    return page.Workspace(tmp_path)


def _refused(route: str, body: dict, ws) -> dict:
    answer = json.loads(page.call(route, json.dumps(body), ws))
    assert answer["status"] == 422, answer
    return answer["body"]


def _start(ws) -> dict:
    return {**design.starting_setup("example-mosfet", ws), "device": "example-mosfet"}


MOTOR_SLIPS = [
    # a change to the example motor, the figure the page marks, and words the sentence holds
    ({"pole_pairs": 2.5}, "pole_pairs", "the pole pairs has to be a whole number"),
    ({"pole_pairs": -3}, "pole_pairs", "the pole pairs"),
    ({"kv": "fast"}, "kv", "the speed constant"),
    ({"rs": -1}, "rs", "the phase resistance cannot be below 0"),
    ({"magnets": "glued"}, "magnets", "the magnets is one of surface, inset or interior"),
    ({"ld": 1e-4, "lq": 2e-4}, "l", "one phase inductance, or the two axis inductances"),
    ({"ke": 5.0}, "kv", "one of the speed constant, the back-EMF constant or the flux linkage"),
    ({"type": "warp"}, "", "there is no kind called warp"),
]


@pytest.mark.parametrize(("change", "field", "said"), MOTOR_SLIPS)
def test_a_motor_figure_that_cannot_be_is_refused_in_words_with_its_box(ws, change, field, said) -> None:
    body = _start(ws)
    body["motor"] = {**body["motor"], **change}
    refused = _refused("/api/stage", body, ws)
    assert said in refused["refused"]
    # The kinds of motor are said as a motor file names them, which is a word the user types.
    assert not VALIDATOR.search(refused["refused"].replace("dc_series", "")), refused["refused"]
    assert refused["field"] == field


LOAD_SLIPS = [
    ({"gear_ratio": "x"}, "the gear ratio is not a number"),
    ({"gear_ratio": 0}, "the gear ratio has to be above 0"),
    ({"gear_efficiency": 1.5}, "the gear efficiency cannot be above 1"),
    ({"motor_inertia": -1}, "the rotor inertia cannot be below 0"),
]


@pytest.mark.parametrize(("change", "said"), LOAD_SLIPS)
def test_a_load_figure_that_cannot_be_is_refused_in_words(ws, change, said) -> None:
    body = _start(ws)
    body["load"] = {**body["load"], **change}
    refused = _refused("/api/cycle", body, ws)
    assert said in refused["refused"]
    assert not VALIDATOR.search(refused["refused"]), refused["refused"]


def test_a_stretch_of_the_motion_is_named_by_its_place(ws) -> None:
    body = _start(ws)
    body["profile"]["segments"][1]["duration"] = -1
    refused = _refused("/api/cycle", body, ws)
    assert "the duration of stretch 2 has to be above 0" in refused["refused"]


def test_a_device_file_with_an_outline_no_one_makes_is_refused_plainly(ws, tmp_path) -> None:
    """An outline outside the known ones is the user's slip, said as one in a sentence."""
    from motionsim.device.io import load_device
    from motionsim.service.workspace import EXAMPLES

    text = EXAMPLES["example-mosfet"].read_text(encoding="utf-8").replace("outline: TO-220", "outline: TO-999")
    file = tmp_path / "odd.device.yaml"
    file.write_text(text, encoding="utf-8")
    with pytest.raises(Refusal) as caught:
        load_device(file)
    assert caught.value.reason == (
        "odd.device.yaml is not a device model: the package outline is one of TO-220, TO-247, TO-263, TO-252 or TOLL"
    )
    added = json.loads(page.call("/api/device", json.dumps({"name": "odd.yaml", "text": text}), ws))
    assert added["status"] == 422
    assert "the package outline is one of" in added["body"]["refused"]
    assert not VALIDATOR.search(added["body"]["refused"])


CONDITION_SLIPS = [
    # The page's switching frequency box is in kHz: the limit is said with its unit, for the
    # page to turn into the box's own.
    ({"f_sw": 50}, "f_sw", "switching frequency cannot be below 100 Hz"),
    ({"f_sw": 2e7}, "f_sw", "switching frequency cannot be above 10,000,000 Hz"),
    ({"v_dc": 5000}, "v_dc", "supply voltage cannot be above 2000 V"),
    ({"t_sink": 300}, "t_sink", "heatsink temperature cannot be above 200 °C"),
    ({"parallel": 13}, "parallel", "devices in parallel cannot be above 12"),
    ({"parallel": 2.5}, "parallel", "devices in parallel has to be a whole number"),
]


@pytest.mark.parametrize(("change", "field", "said"), CONDITION_SLIPS)
def test_a_condition_out_of_bounds_is_refused_with_its_unit(ws, change, field, said) -> None:
    body = _start(ws)
    body["conditions"] = {**body["conditions"], **change}
    refused = _refused("/api/stage", body, ws)
    assert refused["field"] == field
    assert said in refused["refused"], refused["refused"]


def test_a_mission_past_any_motor_is_refused_before_it_is_followed(ws) -> None:
    """A row of 1e9 rpm is no motor's, and neither is 1e7 N·m: each is refused with the row's
    time, by the same bounds a design point is held to."""
    body = _start(ws)
    body.pop("load"), body.pop("profile")
    for rpm, torque, said in ((1e9, 1.0, "1e+09 rpm"), (1000.0, 1e7, "1e+07 N·m")):
        body["mission"] = {"time": [0, 1, 2], "rpm": [0, rpm, 0], "torque": [0, torque, 0]}
        refused = _refused("/api/cycle", body, ws)
        assert refused["field"] == "mission"
        assert said in refused["refused"] and "at 1 s" in refused["refused"], refused["refused"]


def test_a_motion_that_turns_the_motor_past_any_motor_is_refused(ws) -> None:
    """The load's 30,000 rpm through a 50:1 gear is 1.5 million rpm at the motor."""
    body = _start(ws)
    body["load"] = {**body["load"], "gear_ratio": 50.0}
    body["profile"]["segments"][1] = {"duration": 0.45, "speed_start": 30000.0, "speed_end": 30000.0}
    refused = _refused("/api/cycle", body, ws)
    assert refused["field"] == "profile"
    assert "1.5e+06 rpm" in refused["refused"], refused["refused"]
