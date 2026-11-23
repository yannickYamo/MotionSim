"""The figures of a motion's load, heatsink, link and start: one that cannot be is refused
with the name of its box, whether or not this motion would have used it, and one that only
looks odd (a slope downhill, no air drag, a gear that speeds up) is taken."""

from __future__ import annotations

import json

import pytest

from motionsim import design, page


@pytest.fixture(scope="module")
def ws(tmp_path_factory):
    return page.Workspace(tmp_path_factory.mktemp("figures"))


@pytest.fixture(scope="module")
def motion(ws) -> dict:
    """The made-up 600 V IGBT running a light load up to 300 rpm and holding it there."""
    setup = design.starting_setup("example", ws)
    return {
        "motor": setup["motor"],
        "conditions": setup["conditions"],
        "device": "example",
        "load": {"gear_ratio": 1, "inertia": 0.01, "friction_coulomb": 0.5},
        "profile": {
            "segments": [
                {"duration": 1, "speed_start": 0, "speed_end": 300},
                {"duration": 1, "speed_start": 300, "speed_end": 300},
            ]
        },
    }


def ask(ws, body: dict) -> dict:
    return json.loads(page.call("/api/cycle", json.dumps(body), ws))


def refused(ws, body: dict, field: str, said: str) -> None:
    got = ask(ws, body)
    assert got["status"] == 422, got["body"].get("summary")
    assert got["body"]["field"] == field
    assert said in got["body"]["refused"]
    assert got["body"]["fix"]


DRUM = {"mass": 8.0, "radius": 0.25}
CAR = {"mass": 20.0, "wheel_radius": 0.08}


@pytest.mark.parametrize(
    "load, field, said",
    [
        ({"tumble": {**DRUM, "mass": -5}}, "tumble_mass", "the tumbling load cannot be below 0 kg"),
        ({"tumble": {**DRUM, "radius": -5}}, "tumble_radius", "the drum radius has to be above 0 m"),
        ({"tumble": {**DRUM, "radius": 0}}, "tumble_radius", "the drum radius has to be above 0 m"),
        ({"gravity": {"mass": -5, "arm": 0.25}}, "mass", "the weight on the arm cannot be below 0 kg"),
        ({"gravity": {"mass": 3, "arm": -0.25}}, "arm", "the arm length cannot be below 0 m"),
        ({"vehicle": {**CAR, "mass": -5}}, "v_mass", "the mass carried has to be above 0 kg"),
        ({"vehicle": {**CAR, "mass": 0}}, "v_mass", "the mass carried has to be above 0 kg"),
        ({"vehicle": {**CAR, "wheel_radius": -5}}, "wheel_radius", "the wheel radius has to be above 0 m"),
        ({"vehicle": {**CAR, "wheel_radius": 0}}, "wheel_radius", "the wheel radius has to be above 0 m"),
        ({"vehicle": {**CAR, "rolling_resistance": -0.1}}, "rolling_resistance", "the rolling resistance cannot be"),
        ({"vehicle": {**CAR, "drag_area": -1}}, "drag_area", "the drag area cannot be below 0 m²"),
        ({"pulsation": {"torque": -1}}, "pulsation_torque", "the torque pulse cannot be below 0 N·m"),
        ({"breakaway": {"torque": -1, "rpm": 5}}, "breakaway_torque", "the break-away torque cannot be below 0 N·m"),
        ({"breakaway": {"torque": 1, "rpm": 0}}, "breakaway_rpm", "has to be above 0 rpm"),
    ],
)
def test_a_figure_of_what_the_load_is_that_cannot_be_is_refused_with_its_box(ws, motion, load, field, said) -> None:
    refused(ws, {**motion, "load": {**motion["load"], **load}}, field, said)


@pytest.mark.parametrize(
    "key, value, said",
    [
        ("inertia", -5, "the load inertia cannot be below 0 kg·m²"),
        ("motor_inertia", -1e-5, "the rotor inertia cannot be below 0 kg·m²"),
        ("friction_coulomb", -0.5, "the friction cannot be below 0 N·m"),
        ("friction_viscous", -0.01, "the friction growing with speed cannot be below 0"),
        ("fan_coefficient", -1e-4, "the fan constant cannot be below 0"),
        ("gear_ratio", 0, "the gear ratio has to be above 0"),
        ("gear_ratio", -5, "the gear ratio has to be above 0"),
        ("gear_efficiency", 0, "the gear efficiency has to be above 0"),
        ("gear_efficiency", 1.5, "the gear efficiency cannot be above 1"),
    ],
)
def test_a_figure_of_the_shaft_and_its_gear_that_cannot_be_is_refused_with_its_box(
    ws, motion, key, value, said
) -> None:
    refused(ws, {**motion, "load": {**motion["load"], key: value}}, key, said)


@pytest.mark.parametrize(
    "load",
    [
        {"vehicle": {**CAR, "slope_percent": -8}},  # downhill
        {"vehicle": {**CAR, "drag_area": 0}},  # air left out
        {"gear_ratio": 0.5},  # a gear that speeds the load up
        {"constant_torque": -0.2},  # a load that helps the motor along
        {"tumble": {**DRUM, "mass": 0}},  # an empty drum
        {"gravity": {"mass": 0, "arm": 0}},
        {"friction_coulomb": 0, "inertia": 0.02},
    ],
)
def test_a_figure_that_only_looks_odd_is_taken(ws, motion, load) -> None:
    got = ask(ws, {**motion, "load": {**motion["load"], **load}})
    assert got["status"] == 200, got["body"]


@pytest.mark.parametrize(
    "given, field, said",
    [
        ({"heatsink": {"rth": -5}}, "rth", "heatsink resistance cannot be below 0.01 K/W"),
        ({"heatsink": {"rth": -5, "capacity": 200}}, "rth", "heatsink resistance cannot be below 0.01 K/W"),
        ({"heatsink": {"rth": 0, "capacity": 200}}, "rth", "heatsink resistance cannot be below 0.01 K/W"),
        ({"heatsink": {"rth": 1e4}}, "rth", "heatsink resistance cannot be above 500 K/W"),
        ({"heatsink": {"capacity": -5}}, "capacity", "heatsink heat capacity cannot be below 0.1 J/K"),
        ({"heatsink": {"rth": 1, "capacity": 0}}, "capacity", "heatsink heat capacity cannot be below 0.1 J/K"),
        ({"heatsink": {"t_ambient": 1e12}}, "t_ambient", "ambient temperature cannot be above 200 °C"),
        ({"heatsink": {"t_ambient": -300}}, "t_ambient", "ambient temperature cannot be below -40 °C"),
        ({"heatsink": {"rth": 1, "capacity": 200, "t_ambient": 1e12}}, "t_ambient", "cannot be above 150 °C"),
        ({"precharge": -5}, "precharge", "precharge resistance cannot be below 0 Ω"),
        ({"precharge": -5, "c_link": 1e-3}, "precharge", "precharge resistance cannot be below 0 Ω"),
        ({"precharge": 1e-6, "c_link": 1e-3}, "precharge", "precharge resistance cannot be below 0.001 Ω"),
        ({"c_link": -5}, "c_link", "DC-link capacitance cannot be below 1e-09 F"),
    ],
)
def test_a_figure_of_the_heatsink_or_the_link_that_cannot_be_is_refused_with_its_box(
    ws, motion, given, field, said
) -> None:
    refused(ws, {**motion, **given}, field, said)


@pytest.mark.parametrize(
    "given",
    [
        {"heatsink": {"rth": "", "capacity": None, "t_ambient": ""}},  # boxes left empty
        {"heatsink": {"rth": None, "capacity": None, "t_ambient": 180}},  # a heatsink held hot, handed on as it is
        {"precharge": 0, "c_link": 1e-3},  # no precharge resistor
        {"precharge": None, "c_link": None},
    ],
)
def test_a_heatsink_or_link_figure_left_out_is_taken(ws, motion, given) -> None:
    got = ask(ws, {**motion, **given})
    assert got["status"] == 200, got["body"]


@pytest.mark.parametrize(
    "start, field, said",
    [
        ({"current": -5}, "current", "start current cannot be below 0"),
        ({"current": 1e12}, "current", "start current cannot be above 100000"),
        ({"handover_rpm": -5}, "handover_rpm", "handover speed cannot be below 0"),
        ({"handover_rpm": 1e12}, "handover_rpm", "handover speed cannot be above 1,000,000"),
        ({"align_time": -1}, "align_time", "alignment time cannot be below 0"),
        ({"align_time": 1e12}, "align_time", "alignment time cannot be above 30"),
    ],
)
def test_a_figure_of_an_open_loop_start_that_cannot_be_is_refused_with_its_box(ws, motion, start, field, said) -> None:
    refused(ws, {**motion, "start": {"method": "open_loop", **start}}, field, said)
