"""Currents read through shunts in the stage: a low-side shunt reads its phase only while that
leg's low switch is on about the sampling instant, (1 − d)·Ts of the carrier; one shunt in the
DC link reads, in each active vector, the current of the leg alone in its state. Checked against
the duty cycles and phase currents of the same run, worked out here independently."""

from __future__ import annotations

import copy

import numpy as np
import pytest
from test_control_bench import block_of, posted, started, workspace

from motionsim.control.applications import SENSINGS, shunted
from motionsim.control.blocks import BLOCKS, Context
from motionsim.control.sensing import shifted
from motionsim.service.control.running import execute

KEY = "example-mosfet"


@pytest.fixture(scope="module")
def ws():
    return workspace()


def _ran(ws, shunts: str, fidelity: str, **params):
    base = started(KEY, ws)
    told = posted("/api/control/presets", base, ws)
    scheme = copy.deepcopy(next(s for s in told["schemes"] if s["id"] == "foc_servo"))
    if shunts != "sensor":
        sample = block_of(scheme, "sample")
        sample["kind"] = "shunt_sampling"
        for k in ("window_a", "window_b", "window_c", "i_dc_1", "vector_1", "span_1", "i_dc_2", "vector_2", "span_2"):
            sample["inputs"][k] = f"inverter.{k}"
        sample["params"] = {"shunts": shunts, **params}
    steps = execute({**base, "scheme": scheme, "scenario": {"kind": "hold", "periods": 2}, "fidelity": fidelity}, ws)
    while True:
        try:
            next(steps)
        except StopIteration as done:
            return done.value.trace


@pytest.mark.parametrize("fidelity", ["averaged", "switched"])
def test_a_low_side_window_is_the_low_switch_on_time_of_the_period_before(ws, fidelity) -> None:
    trace = _ran(ws, "three", fidelity, fix="none")
    ts = trace.ts
    duties = np.clip([trace.wire(f"modulator.d_{x}") for x in "abc"], 0.0, 1.0)
    for i, x in enumerate("abc"):
        window = trace.wire(f"inverter.window_{x}")
        # What is read at instant k is of the period after k − 1, driven by the duties of k − 2
        # under the delay (one instant to compute, one to apply).
        assert window[0] == 0.0
        np.testing.assert_allclose(window[3:], (1.0 - duties[i][1:-2]) * ts, atol=1e-12)


@pytest.mark.parametrize("fidelity", ["averaged", "switched"])
def test_a_dc_link_shunt_reads_the_current_of_the_leg_alone_in_each_vector(ws, fidelity) -> None:
    trace = _ran(ws, "single", fidelity, fix="none")
    ts = trace.ts
    d = np.clip([trace.wire(f"modulator.d_{x}") for x in "abc"], 0.0, 1.0)[:, 1:-2]
    order = np.argsort(-d, axis=0)
    hi, mid, lo = (np.take_along_axis(d, order[j : j + 1], 0)[0] for j in range(3))
    span1, span2 = trace.wire("inverter.span_1")[3:], trace.wire("inverter.span_2")[3:]
    v1, v2 = trace.wire("inverter.vector_1")[3:], trace.wire("inverter.vector_2")[3:]
    # Peak to valley: the highest duty rises first, (1 − d_hi)·Ts/2 after the peak; one leg high
    # stands until the middle one rises, two until the lowest.
    np.testing.assert_allclose(span1, (hi - mid) * ts / 2, atol=1e-12)
    np.testing.assert_allclose(span2, (mid - lo) * ts / 2, atol=1e-12)
    want1 = np.where(span1 > 0, 2.0 ** order[0], 0.0)
    want2 = np.where(span2 > 0, 2.0 ** order[0] + 2.0 ** order[1], 0.0)
    np.testing.assert_array_equal(v1[span1 > 1e-15], want1[span1 > 1e-15])
    np.testing.assert_array_equal(v2[span2 > 1e-15], want2[span2 > 1e-15])
    # The current read lies between the high leg's current at the two instants about it (one
    # leg high: its own), within the ripple of one period.
    phases = np.array([trace.wire(f"plant.i_{x}") for x in "abc"])
    i1 = trace.wire("inverter.i_dc_1")[3:]
    own = np.take_along_axis(phases[:, 2:-1], order[0:1], 0)[0]
    swing = np.abs(np.diff(phases, axis=1)).max()
    assert np.all(np.abs(i1[span1 > 0] - own[span1 > 0]) <= swing + 1e-9)


def test_the_currents_read_sum_to_nought_and_held_marks_what_could_not_be_read(ws) -> None:
    trace = _ran(ws, "single", "switched", window=3e-6, fix="none")
    read = np.array([trace.wire(f"sample.i_{x}") for x in "abc"])
    np.testing.assert_allclose(read.sum(axis=0), 0.0, atol=1e-9)
    held = trace.wire("sample.held")
    spans = np.minimum(trace.wire("inverter.span_1"), trace.wire("inverter.span_2"))
    # Read when both vectors stand for the window; held when either is too short.
    np.testing.assert_array_equal(held[1:] == 1.0, spans[1:] < 3e-6)


def test_a_block_read_alone_makes_the_third_phase_and_holds_what_it_cannot_see() -> None:
    ctx = Context(1e-4, 1e4, 48.0, 0.1, 1e-3, 1e-3, 0.01, 3, seed=1)
    block = BLOCKS["shunt_sampling"]("sample", {"shunts": "two", "window": 2e-6}, ctx)
    block.setup()
    block.reset()
    # Both of a and b readable: c made from them.
    out = block.step(0.0, 3.0, -1.0, -2.0, 5e-5, 5e-5, 5e-5, 0, 0, 0, 0, 0, 0)
    assert out == (3.0, -1.0, -2.0, 0.0)
    # b's window shut: a read, b and c kept from before and shifted to sum to nought.
    out = block.step(0.0, 4.0, -1.5, -2.5, 5e-5, 1e-6, 5e-5, 0, 0, 0, 0, 0, 0)
    assert out[0] == 4.0 and out[3] == 1.0
    assert out[1] == pytest.approx(-1.0 - 0.5) and out[2] == pytest.approx(-2.0 - 0.5)
    # One DC-link shunt: vector 1 (a high) reads i_a; vector 3 (a and b high) reads −i_c.
    one = BLOCKS["shunt_sampling"]("sample", {"shunts": "single", "window": 2e-6}, ctx)
    one.setup()
    one.reset()
    out = one.step(0.0, 0, 0, 0, 0, 0, 0, 3.0, 1, 1e-5, 2.0, 3, 1e-5)
    assert out == (3.0, pytest.approx(-1.0), -2.0, 0.0)


def test_shunted_reads_through_the_stage_and_sensor_leaves_the_scheme_as_it_was(ws) -> None:
    from motionsim.control.presets import BUILDERS
    from motionsim.service.control.design import _designed

    base = started(KEY, ws)
    d, _ = _designed(dict(base), ws)
    scheme = BUILDERS["foc_servo"](d)
    assert shunted(scheme, "sensor") is scheme
    assert SENSINGS == ("sensor", "three", "two", "single")
    one = next(b for b in shunted(scheme, "single").blocks if b.name == "sample")
    assert one.kind == "shunt_sampling" and one.params["shunts"] == "single"
    assert one.inputs["window_a"] == "inverter.window_a"


def test_a_scheme_with_a_current_sensor_runs_as_it_always_has(ws) -> None:
    # No shunt block, no shunt readings: the stage's wires stay nought.
    trace = _ran(ws, "sensor", "switched")
    for name in ("inverter.window_a", "inverter.i_dc_1", "inverter.span_2"):
        assert not trace.wire(name).any()


def test_the_timer_shifts_the_vectors_apart_and_gives_it_back_in_the_falling_half() -> None:
    # Ts = 100 µs, half 50 µs, window 2 µs: 0.04 of a half apart. a 0.51, b 0.50, c 0.20: a is
    # 0.01 above b, so a rises at 0.54 and falls at 0.48 (mean 0.51); c is far enough below.
    up = shifted([0.51, 0.50, 0.20], "single", 2e-6, 50e-6, True)
    down = shifted([0.51, 0.50, 0.20], "single", 2e-6, 50e-6, False)
    assert up == pytest.approx([0.54, 0.50, 0.20]) and down == pytest.approx([0.48, 0.50, 0.20])
    # All three together (no voltage asked): the highest up, the lowest down, by the window each.
    up = shifted([0.5, 0.5, 0.5], "single", 2e-6, 50e-6, True)
    assert sorted(up) == pytest.approx([0.46, 0.5, 0.54])
    # Under three low-side shunts: the window is w/Ts = 0.02 of the duty about the peak, so the
    # two lowest legs must be at most 0.98; 0.995 in the middle lowers all three by 0.015.
    assert shifted([1.0, 0.995, 0.3], "three", 2e-6, 50e-6, True) == pytest.approx([0.985, 0.98, 0.285])
    # As far as the lowest leg has room, and no further.
    assert shifted([1.0, 0.998, 0.002], "three", 2e-6, 50e-6, True) == pytest.approx(
        [0.998, 0.996, 0.0]
    )  # 0.018 short, 0.002 of room
    # Two shunts (a and b) need their own windows whatever c does.
    assert shifted([0.5, 0.995, 1.0], "two", 2e-6, 50e-6, True) == pytest.approx([0.485, 0.98, 0.985])


@pytest.mark.parametrize("fidelity", ["averaged", "switched"])
def test_with_the_shift_a_dc_link_shunt_reads_nearly_every_period(ws, fidelity) -> None:
    plain = _ran(ws, "single", fidelity, fix="none").wire("sample.held")[3:].mean()
    fixed = _ran(ws, "single", fidelity).wire("sample.held")[3:].mean()
    assert plain > 0.1 and fixed < 0.02
    spans = np.minimum(*(_ran(ws, "single", fidelity).wire(f"inverter.span_{n}")[3:] for n in (1, 2)))
    assert np.mean(spans >= 2e-6 - 1e-12) > 0.98


def test_at_the_first_instant_there_is_no_period_before_and_the_drive_reads_as_it_starts() -> None:
    # A run warm-started at its operating point: reading nought there would kick every loop.
    ctx = Context(1e-4, 1e4, 48.0, 0.1, 1e-3, 1e-3, 0.01, 3)
    for shunts in ("three", "two", "single"):
        block = BLOCKS["shunt_sampling"]("sample", {"shunts": shunts}, ctx)
        block.reset()
        assert block.step(0.0, 5.0, -2.0, -3.0, 0, 0, 0, 0, 0, 0, 0, 0, 0) == (5.0, -2.0, -3.0, 0.0)


def test_a_reading_is_rounded_to_the_converter_and_held_within_its_full_scale() -> None:
    ctx = Context(1e-4, 1e4, 48.0, 0.1, 1e-3, 1e-3, 0.01, 3)
    # 8 bits over ±10 A: a step of 20/256 = 0.078125 A. 3.0 is 38.4 steps: 38 of them.
    block = BLOCKS["shunt_sampling"]("sample", {"shunts": "three", "bits": 8, "full_scale": 10.0}, ctx)
    block.reset()
    out = block.step(0.0, 3.0, -1.0, -2.0, 5e-5, 5e-5, 5e-5, 0, 0, 0, 0, 0, 0)
    # The two longest windows (a and b tie with c: the first two) are read, c made from them.
    assert out[0] == pytest.approx(38 * 0.078125) and out[1] == pytest.approx(-13 * 0.078125)
    assert block.step(0.0, 25.0, -12.0, -13.0, 5e-5, 5e-5, 5e-5, 0, 0, 0, 0, 0, 0)[0] == 10.0


def test_the_run_says_how_often_a_phase_was_not_read_and_the_verdict_offers_the_shift(ws) -> None:
    base = started(KEY, ws)
    told = posted("/api/control/presets", base, ws)
    scheme = copy.deepcopy(next(s for s in told["schemes"] if s["id"] == "foc_servo"))
    plain = posted("/api/control/run", {**base, "scheme": scheme, "scenario": {"kind": "hold"}}, ws)
    assert plain["channels"]["unread_share"] is None and plain["channels"]["read_error_rms"] is None
    assert not any(f["id"] == "shunt_unread" for f in plain["verdict"]["findings"])
    sample = block_of(scheme, "sample")
    sample["kind"] = "shunt_sampling"
    for k in ("window_a", "window_b", "window_c", "i_dc_1", "vector_1", "span_1", "i_dc_2", "vector_2", "span_2"):
        sample["inputs"][k] = f"inverter.{k}"
    sample["params"] = {"shunts": "single", "fix": "none"}
    ran = posted("/api/control/run", {**base, "scheme": scheme, "scenario": {"kind": "hold"}}, ws)
    assert ran["channels"]["unread_share"] > 0.1 and ran["channels"]["read_error_rms"] > 0.0
    found = next(f for f in ran["verdict"]["findings"] if f["id"] == "shunt_unread")
    assert found["tag"] == "improve"
    assert found["lever"] == {"kind": "block", "block": "sample", "param": "fix", "direction": "set", "to": "shift"}
    sample["params"] = {"shunts": "three"}
    ran = posted("/api/control/run", {**base, "scheme": scheme, "scenario": {"kind": "hold"}}, ws)
    assert ran["channels"]["read_error_rms"] == 0.0
    assert next(f for f in ran["verdict"]["findings"] if f["id"] == "shunt_unread")["tag"] == "good"


def test_a_sweep_reads_the_currents_otherwise_only_where_the_scheme_reads_them(ws) -> None:
    base = started(KEY, ws)
    from motionsim.service.routes import dispatch

    asked = {**base, "scheme": "foc_servo", "vary": {"path": "scheme.sensing", "values": ["sensor", "magic"]}}
    status, body = dispatch("/api/control/sweep", asked, ws)
    told = {v["value"]: v["refused"] for v in body["variants"]}
    assert status == 200 and told["sensor"] is None
    assert "sensor, three, two, single" in told["magic"]["refused"] and told["magic"]["fix"]


def test_the_shift_keeps_the_period_mean_and_the_rails_for_any_duty_cycles() -> None:
    rng = np.random.default_rng(7)
    for _ in range(2000):
        duty = list(rng.choice([0.0, 1.0, 0.5], 3) * rng.integers(0, 2, 3) + rng.random(3) * rng.integers(0, 2, 3))
        duty = [min(max(d, 0.0), 1.0) for d in duty]
        for shunts in ("single", "three", "two"):
            up = shifted(duty, shunts, 2e-6, 12.5e-6, True)
            down = shifted(duty, shunts, 2e-6, 12.5e-6, False)
            assert all(-1e-12 <= x <= 1 + 1e-12 for x in up + down)
            if shunts == "single":
                np.testing.assert_allclose([(u + d) / 2 for u, d in zip(up, down, strict=True)], duty, atol=1e-12)
            else:  # the legs together: the line voltages as they were
                np.testing.assert_allclose(np.diff(up), np.diff(duty), atol=1e-12)


def test_where_the_rails_stop_the_highest_leg_the_middle_one_moves_back() -> None:
    # 12.5 µs halves, 2 µs window: 0.16 of a half apart. a 0.95 can rise only to 1.0 (0.05 of
    # room); b, 0.9, goes back to 0.84 so the vector a alone stands 0.16; c is far enough below.
    assert shifted([0.95, 0.9, 0.1], "single", 2e-6, 12.5e-6, True) == pytest.approx([1.0, 0.84, 0.1])
    assert shifted([0.95, 0.9, 0.1], "single", 2e-6, 12.5e-6, False) == pytest.approx([0.9, 0.96, 0.1])
    # a on the rail itself cannot move, nor b further than the falling half gives back (0.01).
    assert shifted([1.0, 0.99, 0.3], "single", 2e-6, 12.5e-6, True) == pytest.approx([1.0, 0.98, 0.3])


@pytest.mark.parametrize("shunts", ["three", "single"])
def test_updated_twice_a_period_the_shunts_are_read_once_and_the_other_instant_is_no_miss(ws, shunts) -> None:
    # Under the low switches a phase is read at the carrier's peak; at the valley every high
    # switch is on and nothing is due. One shunt in the DC link reads the rising half's vectors at
    # the valley. Either way, one reading a period is the design, not a miss.
    from motionsim.control.applications import SHUNT_INPUTS

    base = started(KEY, ws)
    told = posted("/api/control/presets", base, ws)
    scheme = copy.deepcopy(next(s for s in told["schemes"] if s["timing"]["update"] == "double"))
    sample = block_of(scheme, "sample")
    sample["kind"] = "shunt_sampling"
    sample["inputs"] |= {k: f"inverter.{k}" for k in SHUNT_INPUTS}
    sample["params"] = {"shunts": shunts}
    ran = posted("/api/control/run", {**base, "scheme": scheme, "scenario": {"kind": "hold"}}, ws)
    assert ran["channels"]["unread_share"] < 0.05, ran["channels"]["unread_share"]
    assert next(f for f in ran["verdict"]["findings"] if f["id"] == "shunt_unread")["tag"] == "good"
