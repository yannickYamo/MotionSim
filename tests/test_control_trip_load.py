"""A trip at speed, what the motor turns and what feeds it: an arm held against its weight that
falls until its holding brake bites, and a DC link on a supply that takes nothing back."""

from __future__ import annotations

import math

import pytest
from test_control_bench import workspace
from test_control_injection import salient

from motionsim.load import Load
from motionsim.service.control.running import prepared
from motionsim.service.control.running import run as service_run
from motionsim.text import written


@pytest.fixture(scope="module")
def ws():
    return workspace()


def joint(ws, **scenario) -> dict:
    """The made-up robot joint (an arm of 61.6 kg at 0.25 m through a 75:1 gear) tripped."""
    return service_run(salient(ws, "linear") | {"scheme": "foc_servo", "scenario": {"kind": "trip", **scenario}}, ws)


def unloaded(ws, supply: str, **scenario) -> dict:
    request = salient(ws, "linear") | {
        "scheme": "foc_torque",
        "supply": supply,
        "scenario": {"kind": "trip", **scenario},
    }
    request.pop("load", None)
    return service_run(request, ws)


# The arm.


def test_an_arm_that_carries_a_weight_is_tripped_level_on_a_free_shaft_shorted_with_a_brake(ws) -> None:
    answer = joint(ws)
    asked = answer["scenario"]
    load = Load.model_validate(salient(ws)["load"])
    weight = load.at_motor(0.0, 0.0, math.pi / 2)[1] - load.at_motor(0.0, 0.0, 0.0)[1]
    assert asked["shaft"] == "free" and asked["safe"] == "short" and asked["rpm"] == 0.0
    assert asked["brake_torque"] == pytest.approx(2.0 * weight, rel=1e-9)
    assert asked["brake_delay"] == pytest.approx(0.03)
    taken = " ".join(answer["taken"])
    assert "held level" in taken and "holding brake is taken" in taken


def test_switched_off_the_arm_falls_as_its_weight_less_its_friction_accelerates_it_until_the_brake_bites(ws) -> None:
    # Over the brake's delay the currents have long died and the arm is near level: the motor's
    # shaft turns by ½·T/J·t², T the weight's torque at the motor less the friction, as the load
    # itself gives them for a falling arm.
    delay = 0.03
    answer = joint(ws, safe="off", brake_delay=delay)
    load = Load.model_validate(salient(ws)["load"])
    falling = -1e-3  # rad/s at the joint, the arm going down
    net = load.at_motor(falling, 0.0, math.pi / 2)[1]
    design = prepared(salient(ws, "linear") | {"scheme": "foc_servo"}, ws).design
    want = 0.5 * net / design.shaft_inertia * delay**2
    trip = answer["trip"]
    assert trip["fall_at_brake"] == pytest.approx(want, rel=0.1)
    # The brake then holds it: the arm stands still at the end of the run, not creeping.
    assert trip["rpm_end"] == 0.0 and trip["creep"] == 0.0
    assert trip["fall_deg"] == pytest.approx(math.degrees(trip["fall"]) / load.gear_ratio, rel=1e-9)


def test_shorted_the_winding_brakes_the_fall_and_the_arm_falls_less(ws) -> None:
    off = joint(ws, safe="off")["trip"]
    short = joint(ws, safe="short")["trip"]
    assert 0.0 < short["fall"] < 0.8 * off["fall"]
    assert short["fall_peak_rpm"] < off["fall_peak_rpm"]


def test_the_verdict_says_how_far_the_arm_fell_and_offers_the_short_where_the_gates_were_off(ws) -> None:
    answer = joint(ws, safe="off")
    found = {f["id"]: f for f in answer["verdict"]["findings"]}
    fall = found["trip_fall"]
    assert f"{written(answer['trip']['fall_deg'], 3)}°" in fall["said"]
    assert fall["lever"] == {"kind": "test", "param": "safe"}
    # Shorted, this arm falls under a degree before its brake bites: caught, with nothing to change.
    short = joint(ws, safe="short")
    assert short["trip"]["fall_deg"] < 1.0
    shorted = {f["id"]: f for f in short["verdict"]["findings"]}
    assert shorted["trip_fall"]["tag"] == "good" and shorted["trip_fall"]["lever"] is None


def test_a_fall_smaller_than_one_count_of_an_encoder_is_a_load_held() -> None:
    from motionsim.control.verdict import _trip_fall

    assert _trip_fall({"fall_deg": 7.61e-5, "fall_peak_rpm": 0.0, "brake_delay": 0.01}, ["off"]) is None
    found = _trip_fall({"fall_deg": 0.5, "fall_peak_rpm": 3.0, "brake_delay": 0.01}, ["off"])
    assert found is not None and "0.5°" in found["said"]


def test_a_shaft_held_through_the_trip_has_no_fall(ws) -> None:
    answer = joint(ws, shaft="held", rpm=1000.0)
    assert answer["trip"].get("fall") is None
    assert "trip_fall" not in {f["id"] for f in answer["verdict"]["findings"]}


# The DC link.


def test_with_no_weight_the_default_is_still_chosen_by_speed_on_a_held_shaft(ws) -> None:
    asked = unloaded(ws, "one-way")["scenario"]
    assert asked["safe"] == "hybrid" and asked["shaft"] == "held"


@pytest.mark.parametrize("over", [1.6, 2.6])
def test_on_a_one_way_supply_the_link_charges_to_the_magnet_s_line_voltage_against_the_device(ws, over) -> None:
    # Nothing takes the energy back: the capacitor charges until the bridge stops conducting,
    # where the peak of the line voltage, √3·ωe·ψ, is the link's and two diodes' drops.
    first = unloaded(ws, "one-way", safe="off", rpm=1000.0)
    bridge = first["trip"]["bridge_rpm"]
    # At a torque the motor still reaches that far into field weakening.
    answer = unloaded(ws, "one-way", safe="off", rpm=over * bridge, torque=1.0)
    design = prepared(salient(ws, "linear") | {"scheme": "foc_torque"}, ws).design
    w_e = design.pole_pairs * over * bridge * math.pi / 30.0
    want = math.sqrt(3.0) * w_e * design.psi - 2.0 * design.v_drop
    trip = answer["trip"]
    assert trip["v_link_settles"] == pytest.approx(want, rel=1e-9)
    found = {f["id"]: f for f in answer["verdict"]["findings"]}["trip_link"]
    assert f"{written(want, 3)} V" in found["said"]
    rating = trip["v_rating"]
    if want > rating:
        assert f"past the device's {written(rating, 3)} V rating" in found["said"] and found["severity"] == 3
    else:
        assert f"within the device's {written(rating, 3)} V rating" in found["said"]


def test_on_a_battery_the_link_takes_the_current_back_as_charge(ws) -> None:
    first = unloaded(ws, "battery", safe="off", rpm=1000.0)
    answer = unloaded(ws, "battery", safe="off", rpm=1.6 * first["trip"]["bridge_rpm"])
    found = {f["id"]: f for f in answer["verdict"]["findings"]}["trip_link"]
    assert "the battery takes it back" in found["said"]
    assert answer["trip"]["v_link_settles"] is None


# What a trip is not read for.


def test_a_trip_leaves_the_running_quality_unread_where_a_hold_reads_it(ws) -> None:
    # Switched off, the current, torque and speed are a coast-down, not a drive's quality: no
    # THD, ripple or speed swing is said of them, so a comparison of schemes on a trip says none.
    tripped = unloaded(ws, "four-quadrant", rpm=3000)
    for figure in ("thd", "ripple_pp", "ripple_rms", "torque_ripple_pp", "speed_ripple_pp"):
        assert tripped["channels"][figure] is None, figure
    held = service_run(salient(ws, "linear") | {"scheme": "foc_torque", "scenario": {"kind": "hold"}}, ws)
    assert held["channels"]["thd"] is not None and held["channels"]["torque_ripple_pp"] is not None


def test_a_small_fall_with_the_winding_shorted_is_a_load_caught_not_a_change_to_make() -> None:
    """Shorted is the most the stage can do for a falling load; under a degree at the load before
    the brake bites, nothing is left to change. Gates off, the short is still offered."""
    from motionsim.control.verdict import _trip_fall

    caught = _trip_fall({"fall_deg": 0.103, "fall_peak_rpm": 40.0, "brake_delay": 0.03}, ["short"])
    assert caught is not None and caught["tag"] == "good" and caught["lever"] is None
    assert "0.103°" in caught["said"] and caught["head"] == "the load is caught within 0.103°"
    far = _trip_fall({"fall_deg": 3.0, "fall_peak_rpm": 400.0, "brake_delay": 0.03}, ["short"])
    assert far is not None and far["tag"] == "improve" and far["lever"] == {"kind": "test", "param": "brake_delay"}
    off = _trip_fall({"fall_deg": 0.103, "fall_peak_rpm": 40.0, "brake_delay": 0.03}, ["off"])
    assert off is not None and off["tag"] == "improve" and off["lever"] == {"kind": "test", "param": "safe"}


def test_a_tripped_drive_asks_nothing_more_its_regulators_stand_still(ws) -> None:
    """Once the stage is in its safe state the controller is off: no torque or current is asked,
    and nothing winds up to its limit against a stage that no longer answers. What is measured
    (the currents, the angle) is still read."""
    import numpy as np

    answer = joint(ws, safe="off")
    t, wires = np.array(answer["series"]["t"]), answer["series"]["wires"]
    after = t > answer["trip"]["t_trip"] + 2e-4
    assert after.sum() > 5
    for name in ("speed.torque", "reference.i_q", "reference.i_d"):
        if name in wires:
            assert np.all(np.array(wires[name], dtype=float)[after] == 0.0), name
    assert "speed.torque" in wires
    # The measured side is alive: the shaft's speed after the trip is read as it is.
    assert np.any(np.array(wires["plant.omega_m"], dtype=float)[after] != 0.0)
