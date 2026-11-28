"""What the control lab's addresses do with a request that is not what they expect: every
field of every address given values of the wrong kind answers in words (a refusal with its
field) or runs, and never ends in a fault; nesting has a limit; a run or a sweep too long to
wait for is refused before it starts; and a field an address does not know is said to have
been left out."""

from __future__ import annotations

import copy
import json
import math
import time

import pytest
from test_control_bench import block_of, posted, started, workspace

from motionsim.service.control import FIELDS, MISMATCH, reading
from motionsim.service.routes import dispatch

KEY = "example-gan"  # the part with the fewest sampling instants in a hold: the quickest to run
ROUTES = ("presets", "loops", "run", "explorations", "sweep")
NAN, INF = float("nan"), float("inf")
HOSTILE = (True, False, 0, -1, 2.5, 1e300, -1e300, NAN, INF, 2**70, "x", "1e3", [], [1, 2], ["a"], {}, {"a": 1}, [[]])


@pytest.fixture(scope="module")
def ws():
    return workspace()


@pytest.fixture(scope="module")
def base(ws):
    """A request every address answers quickly: the gate of a hold over one turn, averaged."""
    return {**started(KEY, ws), "fidelity": "averaged", "scenario": {"kind": "hold", "periods": 1}}


@pytest.fixture(scope="module")
def scheme(ws):
    return next(s for s in posted("/api/control/presets", started(KEY, ws), ws)["schemes"] if s["id"] == "foc_servo")


def fields() -> list[tuple[str, ...]]:
    """Every field a control request has, as a path: from the shapes the addresses read by."""
    paths: list[tuple[str, ...]] = [(name,) for name in reading.TOP["sweep"]]
    paths += [(part, name) for part, names in reading.INSIDE.items() if "." not in part for name in names]
    paths += [("scheme", "timing", name) for name in reading.INSIDE["scheme.timing"]]
    paths += [("scheme", "actuation", name) for name in reading.INSIDE["scheme.actuation"]]
    paths += [("scheme", "blocks", "0", name) for name in reading.BLOCK]
    paths += [("scheme", "blocks", "speed", "params", "kp"), ("scheme", "blocks", "speed", "inputs", "ref")]
    paths += [("scenario", "kind")]
    paths += [("scenario", kind, name) for kind, names in FIELDS.items() for name in names]
    paths += [("shaft", name) for name in ("inertia", "constant", "viscous", "quadratic")]
    paths += [("inverter", name) for name in ("dead_time", "device_drop")]
    paths += [("mismatch", name) for name in MISMATCH]
    paths += [("fixed", "scheme.gains.current"), ("fixed", "conditions.f_sw"), ("fixed", "scenario.periods")]
    paths += [("conditions", name) for name in ("v_dc", "f_sw", "rpm", "torque", "t_sink", "pwm")]
    paths += [("motor", name) for name in ("type", "pole_pairs", "flux_linkage", "ld", "lq", "rs")]
    return paths


def with_field(base: dict, scheme: dict, path: tuple[str, ...], value) -> dict:
    """The quick request with one field set to a value."""
    data = copy.deepcopy(base)
    if len(path) == 1:
        data[path[0]] = value
        return data
    if path[0] == "scheme":
        data["scheme"] = copy.deepcopy(scheme)
        if len(path) == 2:
            data["scheme"][path[1]] = value
        elif path[1] == "blocks":
            block = data["scheme"]["blocks"][0] if path[2] == "0" else block_of(data["scheme"], path[2])
            if len(path) == 4:
                block[path[3]] = value
            else:
                block[path[3]][path[4]] = value
        else:
            data["scheme"][path[1]][path[2]] = value
        return data
    if path[0] == "scenario" and len(path) == 3:
        by_speed = path[1] in ("speed_step", "load_step")
        data["scheme"] = "foc_servo" if by_speed else "foc_torque"
        data["scenario"] = {"kind": path[1], path[2]: value}
        return data
    if path[0] == "shaft":
        data.pop("load", None)
        data["shaft"] = {"inertia": 1e-6, path[1]: value}
        return data
    held = data.get(path[0])
    data[path[0]] = {**(held if isinstance(held, dict) else {}), path[1]: value}
    return data


def answered(route: str, data: dict, ws) -> tuple[int, dict]:
    """One request to one address. A sweep that names nothing to vary is refused at once, so
    it is given the smallest there is."""
    if route == "sweep" and "vary" not in data and "exploration" not in data:
        data = {**data, "vary": {"path": "seed", "values": [0]}}
    return dispatch(f"/api/control/{route}", data, ws)


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("path", fields(), ids=".".join)
def test_a_field_given_a_value_of_the_wrong_kind_is_refused_in_words_or_runs(ws, base, scheme, route, path) -> None:
    for value in HOSTILE:
        status, body = answered(route, with_field(base, scheme, path, value), ws)
        assert status in (200, 422), f"{'.'.join(path)} = {value!r}: {status} {body}"
        if status == 422:
            assert isinstance(body.get("refused"), str) and body["refused"].strip(), body
            assert isinstance(body.get("field"), str), body
        else:
            json.dumps(body, allow_nan=False)  # an answer holds no NaN and no infinity


def test_the_generated_fields_cover_the_ones_that_once_ended_in_a_fault() -> None:
    listed = {".".join(p) for p in fields()}
    for once in ("scenario.kind", "scenario.start.shape", "reads", "exploration", "vary.also", "vary.schemes"):
        assert once in listed
    assert ("fixed", "scheme.gains.current") in fields()


def nested(levels: int) -> dict:
    top: dict = {}
    inner = top
    for _ in range(levels):
        inner["a"] = {}
        inner = inner["a"]
    return top


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("where", ("scenario", "scheme", "params", "vary", "fixed", "motor", "load"))
def test_a_request_nested_past_the_limit_is_refused_by_the_place_it_nests(ws, base, route: str, where: str) -> None:
    status, body = answered(route, {**base, where: nested(5000)}, ws)
    assert status == 422
    assert body["field"] == where and "nested more than 24 levels deep" in body["refused"]


def test_a_request_nested_to_the_limit_is_read(ws, base, scheme) -> None:
    # A scheme's block parameter sits five levels down: scheme, blocks, the block, params, the name.
    assert reading.MOST_DEPTH >= 5
    reading.deep(nested(reading.MOST_DEPTH))
    with pytest.raises(Exception, match="nested more than"):
        reading.deep(nested(reading.MOST_DEPTH + 1))
    assert answered("run", {**base, "scheme": scheme}, ws)[0] == 200


def test_a_run_too_long_to_wait_for_is_refused_before_it_starts(ws, base) -> None:
    told = posted("/api/control/presets", started(KEY, ws), ws)
    f_sw = told["design"]["f_sw"]
    assert told["limits"]["seconds"] == 30.0 and told["limits"]["sweep_seconds"] == 120.0
    # A scheme of duty cycles sampled twice a period goes through 2·f_sw instants a second,
    # each reckoned at 100 µs: 30 s is 300 000 instants.
    duration = 400_000 / (2.0 * f_sw)
    assert duration <= told["limits"]["duration"] and told["limits"]["steps"] > 400_000
    began = time.perf_counter()
    status, body = dispatch(
        "/api/control/run",
        {**base, "scheme": "foc_high_speed", "scenario": {"kind": "speed_step", "duration": duration}},
        ws,
    )
    assert time.perf_counter() - began < 5.0  # decided from the count, not by running
    assert status == 422 and body["field"] == "scenario.duration"
    assert body["refused"] == (
        "this would take longer than 30 s: the run goes through 400 000 sampling instants, about 40 s"
    )
    assert body["fix"] == "shorten the test or lower the sampling rate"
    # One instant under the 30 s is run... as far as this test waits: it is not refused for its length.
    assert reading.seconds(299_999, "duties") < reading.RUN_BUDGET < reading.seconds(300_001, "duties")
    assert reading.seconds(600_001, "states") > reading.RUN_BUDGET


def test_a_sweep_whose_runs_together_take_too_long_is_refused_before_the_first(ws, base) -> None:
    f_sw = posted("/api/control/presets", started(KEY, ws), ws)["design"]["f_sw"]
    # Six runs of 250 000 instants: 25 s each, which a run may take, and 150 s together.
    test = {"kind": "speed_step", "duration": 250_000 / (2.0 * f_sw)}
    began = time.perf_counter()
    status, body = dispatch(
        "/api/control/sweep",
        {**base, "scheme": "foc_high_speed", "scenario": test, "vary": {"path": "seed", "values": [0, 1, 2, 3, 4, 5]}},
        ws,
    )
    assert time.perf_counter() - began < 10.0
    assert status == 422
    assert body["refused"] == (
        "this would take longer than 120 s: its 6 runs go through 1 500 000 sampling instants, about 150 s"
    )


def test_a_field_an_address_does_not_know_is_said_to_have_been_left_out(ws, base, scheme) -> None:
    for route in ROUTES:
        status, body = answered(route, {**base, "noise": {"seed": 1}}, ws)
        assert status == 200, body
        assert any(line.startswith("the request's noise is not a field of this address") for line in body["taken"])
    edited = copy.deepcopy(scheme)
    edited["colour"] = "red"
    edited["timing"]["jitter"] = 1e-6
    edited["blocks"][0]["note"] = "mine"
    status, body = answered("run", {**base, "scheme": edited, "window": {"from": 0.0, "to": 1e-4, "zoom": 2}}, ws)
    assert status == 200, body
    said = " | ".join(body["taken"])
    for left_out in ("scheme.colour", "scheme.timing.jitter", "scheme.blocks[0].note", "window.zoom"):
        assert f"the request's {left_out} is not a field there and was left out" in said
    # Where a field that was put in the wrong place really lives is said with it.
    status, body = answered("run", {**base, "noise": {"seed": 1}}, ws)
    assert any(
        line.endswith(
            "the noise on the sampled currents is the `noise` of the scheme's current_sampling block "
            "(scheme.blocks.<its name>.params.noise), and its seed is `seed`, at the top of the request"
        )
        for line in body["taken"]
    ), body["taken"]
    status, body = answered("run", {**base, "window": {"from": 0.0, "to": 1e-4, "seed": 1}}, ws)
    assert any(line.endswith("`seed` is a field at the top of the request") for line in body["taken"])
    # A sweep's own fields are not a run's.
    status, body = answered("run", {**base, "vary": {"path": "seed", "values": [0]}}, ws)
    assert any(line.startswith("the request's vary is not a field") for line in body["taken"])
    # And a request with nothing unknown says nothing of the kind.
    assert not any("left out" in line for line in answered("run", base, ws)[1]["taken"])


def test_the_seed_seeds_the_noise_of_the_samples_and_says_so_where_there_is_none(ws, base, scheme) -> None:
    noisy = copy.deepcopy(scheme)
    block_of(noisy, "sample")["params"]["noise"] = 0.5  # A rms on each sample
    ran = [
        answered("run", {**base, "scheme": noisy, "seed": seed}, ws)[1]["series"]["wires"]["sample.i_a"]
        for seed in (1, 1, 2)
    ]
    assert ran[0] == ran[1] and ran[0] != ran[2]
    quiet = answered("run", {**base, "scheme": scheme, "seed": 2}, ws)[1]
    assert any(line.startswith("the seed 2 has nothing to seed") for line in quiet["taken"])
    assert not any(
        "nothing to seed" in line for line in answered("run", {**base, "scheme": noisy, "seed": 2}, ws)[1]["taken"]
    )
    assert math.isfinite(sum(ran[0]))


def test_a_regulator_with_gains_of_nought_is_run_and_said_not_to_close_its_loop(ws, base, scheme) -> None:
    open_loop = copy.deepcopy(scheme)
    for gain in ("kp_d", "ki_d", "kp_q", "ki_q"):
        block_of(open_loop, "current")["params"][gain] = 0.0
    status, body = answered("loops", {**base, "scheme": open_loop}, ws)
    assert status == 200 and body["current_d"] is None
    assert body["missing"] == ["the gains of current on the d axis are all nought: the current loop is not closed"]
