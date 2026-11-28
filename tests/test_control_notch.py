"""The notch on the torque asked (torque_notch, control/regulators.py), and its place in the
speed loop's linear analysis.

The expected values come from the definition of the notch, evaluated here on the unit circle:
unity at DC and far from the centre, the depth at the centre (the bilinear transform with the
centre prewarped maps it exactly), and a steady torque passed unchanged from a warm start.
"""

from __future__ import annotations

import cmath
import math

import pytest
from test_control_bench import posted, started, workspace

from motionsim.control.blocks import BLOCKS, Context

TS = 1.0 / 16000.0


def _notch(frequency: float, width: float = 0.5, depth: float = 0.05):
    ctx = Context(TS, 1.0 / TS, 48.0, 0.1, 1e-3, 1e-3, 0.01, 3)
    block = BLOCKS["torque_notch"]("notch", {"frequency": frequency, "width": width, "depth": depth}, ctx)
    block.reset()
    return block


def _gain(block, f: float) -> float:
    b, a = block.transfer()
    z = cmath.exp(1j * 2.0 * math.pi * f * TS)
    return abs((b[0] + b[1] / z + b[2] / z**2) / (a[0] + a[1] / z + a[2] / z**2))


def test_the_notch_is_its_depth_at_its_centre_and_passes_the_rest():
    block = _notch(800.0, depth=0.05)
    assert _gain(block, 800.0) == pytest.approx(0.05, rel=1e-6)
    assert _gain(block, 1e-6) == pytest.approx(1.0, rel=1e-9)
    assert _gain(block, 20.0) == pytest.approx(1.0, abs=1e-3)
    assert _gain(block, 7000.0) == pytest.approx(1.0, abs=0.02)
    # Narrower, the band taken out is narrower: at half the centre it passes more.
    assert _gain(_notch(800.0, width=0.1), 400.0) > _gain(block, 400.0)


def test_a_sine_at_the_centre_comes_out_at_the_depth():
    block = _notch(800.0, depth=0.1)
    out = [block.step(k * TS, math.sin(2.0 * math.pi * 800.0 * k * TS))[0] for k in range(16000)]
    assert max(abs(y) for y in out[-400:]) == pytest.approx(0.1, rel=0.01)


def test_a_steady_torque_passes_unchanged_from_a_warm_start():
    block = _notch(800.0)
    block.warm({"torque": 1.7})
    assert all(block.step(k * TS, 1.7)[0] == pytest.approx(1.7, rel=1e-12) for k in range(200))


def test_with_no_centre_or_one_past_half_the_sampling_rate_the_torque_passes():
    for f in (0.0, 0.5 / TS, 0.6 / TS):
        block = _notch(f)
        assert [block.step(k * TS, x)[0] for k, x in enumerate((1.0, -2.0, 3.5))] == [1.0, -2.0, 3.5]


def test_the_notch_takes_the_resonance_given_and_the_speed_loop_s_analysis_carries_it() -> None:
    ws = workspace()
    base = started("example-mosfet", ws)
    plain = posted("/api/control/loops", {**base, "scheme": "servo_notch"}, ws)
    given = posted(
        "/api/control/loops", {**base, "scheme": "servo_notch", "plant": {"coupling": {"resonance_hz": 300}}}, ws
    )
    assert not any("notch" in s for s in plain["speed"]["transfer"])
    assert any("notch notch at 300 Hz" in s for s in given["speed"]["transfer"])
    # A notch costs phase below its centre: the margin falls, and stays a margin (its fast
    # phase swing must not put the loop's phase a whole turn away).
    assert 0.0 < given["speed"]["margins"]["phase_deg"] < plain["speed"]["margins"]["phase_deg"]
    assert -270.0 < given["speed"]["bode"]["open_deg"][0] <= 90.0
