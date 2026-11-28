"""A design point held in each of the four quadrants of speed and torque: a hold at (−ω, −T)
is the mirror image of the hold at (+ω, +T), and a hold that does not hold says so."""

from __future__ import annotations

import copy
import re

import numpy as np
import pytest
from test_control_bench import block_of, posted, started, workspace

from motionsim.control.plant import simple_load
from motionsim.control.presets import Design
from motionsim.engine.modulation import Pwm
from motionsim.service.control.design import _load_torque

KEY = "example-mosfet"
QUADRANTS = {
    "forward motoring": (1, 1),
    "reverse motoring": (-1, -1),
    "forward regenerating": (1, -1),
    "reverse regenerating": (-1, 1),
}
SPEED_SCHEMES = ("foc_servo", "foc_high_speed", "sensorless_flux", "sensorless_emf", "sensorless_smo")


@pytest.fixture(scope="module")
def ws():
    return workspace()


def held(ws, scheme, way_speed: int, way_torque: int, key: str = KEY, **more) -> tuple[dict, float, float]:
    base = started(key, ws)
    rpm, torque = way_speed * base["conditions"]["rpm"], way_torque * base["conditions"]["torque"]
    base["conditions"] = {**base["conditions"], "rpm": rpm, "torque": torque}
    return posted("/api/control/run", {**base, "scheme": scheme, "points": 2000, **more}, ws), rpm, torque


def analysed(answer: dict, wire: str) -> np.ndarray:
    t = np.array(answer["series"]["t"])
    return np.array(answer["series"]["wires"][wire])[t >= answer["timing"]["analysed_from"] - 1e-12]


@pytest.mark.parametrize("scheme", SPEED_SCHEMES)
@pytest.mark.parametrize("quadrant", QUADRANTS)
def test_a_speed_controlled_hold_makes_the_torque_asked_at_the_speed_asked_in_every_quadrant(
    ws, scheme: str, quadrant: str
) -> None:
    answer, rpm, torque = held(ws, scheme, *QUADRANTS[quadrant])
    # The bench brake asks the design torque, with the design's own sign: whichever way the
    # shaft turns, the drive holding its speed has to make exactly that.
    assert analysed(answer, "plant.load_torque").mean() == pytest.approx(torque, rel=1e-6)
    assert answer["ripple"]["torque_mean"] == pytest.approx(torque, rel=0.005)
    assert analysed(answer, "plant.omega_m")[-1] * 30.0 / np.pi == pytest.approx(rpm, rel=1e-3)
    assert not [c for c in answer["checks"] if c["topic"] == "tracking"], answer["checks"]


@pytest.mark.parametrize("scheme", ("foc_servo", "sensorless_flux"))
def test_a_hold_in_reverse_loses_what_its_mirror_image_forwards_loses(ws, scheme: str) -> None:
    # Turn the rotor the other way and ask the opposite torque: the q-axis current and voltage
    # change sign, the phases follow each other in the opposite order, and every switch
    # carries what its mirror image carried. Motoring both ways, then regenerating both ways.
    for mirrored in ((1, 1), (1, -1)):
        there, _, _ = held(ws, scheme, *mirrored)
        back, _, _ = held(ws, scheme, -mirrored[0], -mirrored[1])
        assert back["losses"]["loss"] == pytest.approx(there["losses"]["loss"], rel=2e-3)
        assert back["ripple"]["i_q"] == pytest.approx(-there["ripple"]["i_q"], rel=2e-3)
        assert back["losses"]["loss"] == pytest.approx(back["engine"]["loss"], rel=0.02)


def test_with_no_load_given_the_shaft_asks_the_design_torque_at_the_design_speed_in_every_quadrant() -> None:
    for way_speed, way_torque in QUADRANTS.values():
        d = Design(
            rs=0.03, ld=8e-5, lq=8e-5, psi=0.0105, pole_pairs=7, v_dc=48.0, f_sw=2e4, pwm=Pwm.space_vector,
            rpm=way_speed * 2000.0, torque=way_torque * 2.0, i_design=18.0,
        )  # fmt: skip
        taken: list[str] = []
        load = _load_torque(None, d, taken)
        assert load(d.omega, 0.0, 0.0) == pytest.approx(d.torque)
        # A load that opposes the motion cannot regenerate: where the design point does, the
        # load is one that drives the shaft, and the answer says so.
        assert ("drives the shaft" in " ".join(taken)) == (way_speed * way_torque < 0)


def test_a_load_that_opposes_the_motion_changes_sign_with_the_speed() -> None:
    load = simple_load(constant=2.0, still=1e-3)
    assert load(50.0, 0.0, 0.0) == pytest.approx(2.0) and load(-50.0, 0.0, 0.0) == pytest.approx(-2.0)


def test_a_hold_that_makes_less_torque_than_asked_says_so(ws) -> None:
    # The drive's current limit set under what the design torque needs: 80 % of the current
    # is 80 % of the torque on a motor whose torque is its q-axis current's.
    base = started(KEY, ws)
    scheme = copy.deepcopy(
        next(s for s in posted("/api/control/presets", base, ws)["schemes"] if s["id"] == "foc_torque")
    )
    limit = 0.8 * posted("/api/control/presets", base, ws)["design"]["i_design"]
    block_of(scheme, "current_ref")["params"]["i_limit"] = limit
    answer = posted("/api/control/run", {**base, "scheme": scheme}, ws)
    asked = base["conditions"]["torque"]
    assert answer["ripple"]["torque_mean"] == pytest.approx(0.8 * asked, rel=0.01)
    (check,) = [c for c in answer["checks"] if c["topic"] == "tracking"]
    assert check["level"] == "caution" and answer["level"] in ("caution", "undecided", "fail")
    said = re.fullmatch(
        r"the drive made ([\d.]+) N·m on average where 4\.74 N·m was asked, 20 % less: .+", check["message"]
    )
    assert said is not None, check["message"]
    assert float(said.group(1)) == pytest.approx(0.8 * asked, rel=0.01)


def test_a_hold_whose_speed_is_still_falling_says_so(ws) -> None:
    # A speed regulator allowed half the torque the brake asks cannot hold the speed: the
    # shaft slows through the whole run.
    base = started(KEY, ws)
    scheme = copy.deepcopy(
        next(s for s in posted("/api/control/presets", base, ws)["schemes"] if s["id"] == "foc_servo")
    )
    block_of(scheme, "speed")["params"]["limit"] = 0.5 * base["conditions"]["torque"]
    answer = posted("/api/control/run", {**base, "scheme": scheme}, ws)
    said = " ".join(c["message"] for c in answer["checks"] if c["topic"] == "tracking")
    assert "rpm" in said and "3000 rpm" in said and "still" in said
    assert "N·m" in said  # and half the torque is not the torque asked
    assert answer["level"] != "ok"


@pytest.mark.parametrize("scheme", ("foc_torque", "foc_servo", "mpc_torque", "dtc_torque", "deadbeat_torque"))
def test_a_hold_that_holds_carries_no_such_check(ws, scheme: str) -> None:
    answer, _, torque = held(ws, scheme, 1, 1)
    assert answer["ripple"]["torque_mean"] == pytest.approx(torque, rel=0.02)
    assert not [c for c in answer["checks"] if c["topic"] == "tracking"]
