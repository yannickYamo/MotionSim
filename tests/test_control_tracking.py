"""Every scheme the lab offers makes the torque the design asks, on every made-up part; the
hysteresis band of direct torque control is centred on its reference and sized from what the
design asks; and a comparison of schemes that did not make the same torque says so first."""

from __future__ import annotations

import math

import numpy as np
import pytest
from test_control_bench import design, posted, run, started, workspace

from motionsim.control import Trial
from motionsim.control.applications import dtc_band, dtc_torque
from motionsim.control.presets import BUILDERS, MPC_RATE

KEYS = (
    "example",
    "example-mosfet",
    "example-mosfet-40v",
    "example-mosfet-80v",
    "example-gan",
    "example-sic",
    "example-sic-module",
)
# The one scheme that is let off the 2 %: its cost weighs the commutations against the torque
# error, and on the part with the fewest sampling instants a turn it holds a state long
# enough to sit above the reference. It says so in a check.
WEIGHS_SWITCHING = "mpc_loss_weighted"


@pytest.fixture(scope="module")
def ws():
    return workspace()


@pytest.mark.parametrize("key", KEYS)
# Injection is offered only on a motor whose two axes differ, which no part here is: it is held
# on a salient motor in test_control_injection.py.
@pytest.mark.parametrize("scheme", [s for s in BUILDERS if s != "sensorless_hfi"])
def test_a_hold_makes_the_torque_asked_within_two_percent(ws, key: str, scheme: str) -> None:
    base = started(key, ws)
    answer = posted("/api/control/run", {**base, "scheme": scheme, "fidelity": "averaged", "points": 200}, ws)
    asked, made = posted("/api/control/presets", base, ws)["design"]["torque"], answer["ripple"]["torque_mean"]
    said = [c for c in answer["checks"] if c["topic"] == "tracking"]
    if abs(made - asked) <= 0.02 * abs(asked):
        assert not said, said
        return
    assert scheme == WEIGHS_SWITCHING, f"{scheme} made {made:.4g} N·m of {asked:.4g} N·m on {key}"
    assert abs(made - asked) <= 0.04 * abs(asked)
    assert said and "N·m was asked" in said[0]["message"] and answer["level"] != "ok"


def test_the_torque_band_is_five_percent_of_the_design_torque_where_the_sampling_allows() -> None:
    # 2 N·m asked of a drive whose limit is 6.6 N·m: 0.1 N·m either side, not 5 % of the limit.
    # One sampling period at 100 kHz moves the torque by 1.5·p·ψ·v·Ts/L: the zero state by
    # the back-EMF of 2000 rpm, 15.39 V, 0.212 N·m; the full voltage by 32 − 15.39 V, 0.229 N·m.
    # Half the larger is 0.114 N·m, above 0.1: the sampling decides on this motor.
    d = design()
    per_volt = 1.5 * 7 * 0.0105 / (MPC_RATE * 20000.0) / 80e-6
    back = 2000.0 * math.pi / 30.0 * 7 * 0.0105
    assert back == pytest.approx(15.39, abs=0.01)
    band, rule = dtc_band(d)
    assert band == pytest.approx(0.5 * per_volt * (32.0 - back), rel=1e-9)
    assert band == pytest.approx(0.1145, abs=5e-4)
    assert "sampling period decides" in rule and "5 % of the design torque" in rule
    # With ten times the inductance a period moves a tenth of that: 5 % of 2 N·m decides.
    slow = design(ld=800e-6, lq=800e-6)
    band, rule = dtc_band(slow)
    assert band == pytest.approx(0.1, rel=1e-12) and "design torque decides" in rule
    # And it does not move with the drive's limit.
    assert dtc_band(design(ld=800e-6, lq=800e-6, i_limit=120.0))[0] == pytest.approx(0.1, rel=1e-12)


def test_the_preset_carries_the_band_and_states_its_rule() -> None:
    d = design(ld=800e-6, lq=800e-6)
    block = next(b for b in dtc_torque(d).blocks if b.kind == "dtc")
    assert block.params["torque_band"] == pytest.approx(0.1)
    assert "of the torque the design asks and not of the drive's limit" in block.sources["torque_band"]


@pytest.mark.parametrize("way", (1.0, -1.0))
def test_the_torque_of_direct_torque_control_turns_about_its_reference(way: float) -> None:
    # A band of h either side: the torque turns back at the reference plus h and at the
    # reference less h, each by no more than what a sampling period moves it, and its mean
    # is the reference. (Let go at the reference itself, as a two-level comparator does, it
    # sits half a band under it.) At 600 rpm the back-EMF is 4.6 V of the 32 V a state gives,
    # and with 240 µH the stator flux leads the rotor by atan(L·i/ψ) = 22°, under the 30° up
    # to which every state the table picks to raise the torque does raise it.
    d = design(ld=240e-6, lq=240e-6, f_sw=40000.0, rpm=way * 600.0, torque=way * 2.0)
    assert math.degrees(math.atan(240e-6 * d.i_design / 0.0105)) < 30.0
    assert dtc_band(d)[0] == pytest.approx(0.1)
    band = dtc_band(d)[0]
    test = Trial(
        duration=40 / d.f_out,
        speed=lambda t: d.omega,
        torque=lambda t: d.torque,
        initial={"omega_m": d.omega},
    )
    trace = run(dtc_torque(d), d, test, held=True)
    torque = trace.wire("plant.torque")[trace.time > 20 / d.f_out]
    # N·m a period at the most: the full 32 V of a state, and a tenth for what the delay adds
    step = 1.1 * 1.5 * 7 * 0.0105 * 32.0 / (MPC_RATE * 40000.0) / 240e-6
    assert torque.mean() == pytest.approx(d.torque, rel=0.005)
    assert np.abs(torque).max() <= 2.0 + band + step
    assert np.abs(torque).min() >= 2.0 - band - step
    # It uses the band: the torque comes within a step of each edge.
    assert np.abs(torque).max() >= 2.0 + band - step and np.abs(torque).min() <= 2.0 - band + step


def test_a_comparison_of_schemes_says_first_which_did_not_make_the_torque_asked(ws) -> None:
    base = started("example-gan", ws)
    answer = posted(
        "/api/control/sweep",
        {
            **base,
            "vary": {"path": "scheme", "schemes": ["foc_torque", WEIGHS_SWITCHING]},
            "scenario": {"kind": "hold"},
            "fidelity": "averaged",
            "reads": ["losses.loss"],
        },
        ws,
    )
    asked = answer["variants"][0]["torque_mean"]
    made = answer["variants"][1]["torque_mean"]
    assert asked == pytest.approx(base["conditions"]["torque"], rel=0.005)
    assert made > 1.02 * asked
    # Each scheme is said by its name, as the page names it, never by its id.
    named = next(v["label"] for v in answer["variants"] if v.get("scheme") == WEIGHS_SWITCHING)
    assert named != WEIGHS_SWITCHING
    assert answer["said"][0].startswith(f"{named}: the drive made ")
    assert "N·m was asked" in answer["said"][0] and "more" in answer["said"][0]
    # Then the torque each delivered, and only then the figure compared.
    assert answer["said"][1].startswith("torque delivered: ") and named in answer["said"][1]
    assert answer["said"][2].startswith("inverter loss:")
