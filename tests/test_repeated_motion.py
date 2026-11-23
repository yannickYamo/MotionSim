"""A motion long enough to be thinned for the page, gone through more than once: every trace
is of the last time through, and the heatsink warms run after run as one thermal mass does."""

from __future__ import annotations

import math

import pytest

from motionsim import design, page
from motionsim.service.motion import told

STRETCHES, EACH = 104, 1.0  # stretches of the motion and how long each lasts, s
LENGTH = STRETCHES * EACH  # s, one time through
RTH, CAPACITY = 0.5, 200.0  # the heatsink: K/W to the air and J/K, so 100 s to 63% of its rise
AIR = 60.0  # °C, where the heatsink starts and what it cools to


@pytest.fixture(scope="module")
def ws(tmp_path_factory):
    return page.Workspace(tmp_path_factory.mktemp("repeated"))


def _steady_turning(ws, repeats: int) -> dict:
    """The made-up 600 V IGBT turning a steady 2 N·m at 300 rpm, in more stretches than the
    page draws points for, on a heatsink followed from the air's temperature."""
    setup = design.starting_setup("example", ws)
    return {
        "motor": setup["motor"],
        "conditions": {**setup["conditions"], "cooling": "held", "t_sink": AIR},
        "device": "example",
        "load": {"constant_torque": 2.0},
        "profile": {"segments": [{"duration": EACH, "speed_start": 300, "speed_end": 300}] * STRETCHES},
        "heatsink": {"rth": RTH, "capacity": CAPACITY},
        "repeats": repeats,
    }


@pytest.fixture(scope="module")
def once(ws):
    return page.cycle(_steady_turning(ws, 1), ws)


@pytest.fixture(scope="module", params=[2, 3])
def repeated(request, ws):
    return request.param, page.cycle(_steady_turning(ws, request.param), ws)


def test_the_motion_is_long_enough_to_be_thinned(once) -> None:
    assert once["thinned"]["from"] == STRETCHES * 12 > told.THIN_ABOVE


def test_every_trace_of_a_repeated_long_motion_is_as_long_as_its_time(repeated) -> None:
    _, out = repeated
    assert out["thinned"]["from"] == STRETCHES * 12
    assert {key: len(out[key]) for key in told.KEPT} == dict.fromkeys(told.KEPT, len(out["time"]))


def test_the_traces_of_a_repeated_motion_are_of_its_last_time_through(repeated) -> None:
    repeats, out = repeated
    assert out["began"] == pytest.approx((repeats - 1) * LENGTH)
    assert out["time"][0] == pytest.approx(EACH / 12) and out["time"][-1] == pytest.approx(LENGTH)


def test_the_heatsink_warms_run_after_run_as_one_thermal_mass_under_the_mean_loss(once, repeated) -> None:
    repeats, out = repeated
    # One mass under a steady loss rises by P·R·(1 - exp(-t / RC)) above the air. The loss
    # rises a little with temperature, so the figures agree to a few percent, not exactly.
    share = lambda runs: 1 - math.exp(-runs * LENGTH / (RTH * CAPACITY))
    rise = out["t_sink"][-1] - AIR
    assert rise == pytest.approx(out["summary"]["mean_loss"] * RTH * share(repeats), rel=0.03)
    assert rise / (once["t_sink"][-1] - AIR) == pytest.approx(share(repeats) / share(1), rel=0.03)


def test_the_junction_of_a_later_run_is_not_below_that_of_the_first(once, repeated) -> None:
    _, out = repeated
    assert out["summary"]["peak"] > once["summary"]["peak"]
    assert min(out["tj"]) >= max(once["tj"]) - 1e-9  # one steady point: the junction only rises
    assert out["tj"] == sorted(out["tj"])


def test_the_swing_within_a_turn_is_told_for_the_last_run_as_for_the_first(once, repeated) -> None:
    _, out = repeated
    # The same point of the stage, on a heatsink some kelvin warmer: the same swing to a few percent.
    assert once["worst_swing"]["swing"] > 0.1
    assert out["worst_swing"]["swing"] == pytest.approx(once["worst_swing"]["swing"], rel=0.05)
    assert all(v == pytest.approx(once["swing"][-1], rel=0.05) for v in out["swing"])
