"""The control lab as the service gives it: the three addresses, the tests a run can make,
what is refused and how, and that a run is repeatable and fast enough."""

from __future__ import annotations

import copy
import json
import time

import numpy as np
import pytest
from test_control_bench import SURFACE, block_of, design, kernel, posted, run, started, workspace

from motionsim.control import Trial, Unstable
from motionsim.control.kernel import MOST_STEPS
from motionsim.control.presets import foc_torque
from motionsim.errors import Refusal
from motionsim.service import routes
from motionsim.service.routes import dispatch

KEY = "example-mosfet"


@pytest.fixture(scope="module")
def ws():
    return workspace()


@pytest.fixture(scope="module")
def base(ws) -> dict:
    return started(KEY, ws)


@pytest.fixture(scope="module")
def offered(ws, base) -> dict:
    return posted("/api/control/presets", base, ws)


def scheme_of(offered: dict, name: str) -> dict:
    return copy.deepcopy(next(s for s in offered["schemes"] if s["id"] == name))


def test_the_presets_give_a_scheme_for_the_design_and_every_block_to_click(offered) -> None:
    # The made-up MOSFET is tried on a robot joint: the joint servo, the cascade along an S-curve.
    assert offered["chosen"] == "servo_joint" and "robot joint" in offered["why"]
    ids = [s["id"] for s in offered["schemes"]]
    # The four the page was built on come first, in their order; the others follow.
    assert ids[:4] == ["foc_servo", "foc_torque", "foc_high_speed", "mpc_torque"]
    assert len(ids) == len(set(ids)) and {"sensorless_flux", "deadbeat_torque", "thermal_guard"} <= set(ids)
    kinds = offered["blocks"]
    for needed in (
        "speed_reference",
        "speed_pi",
        "torque_shaper",
        "current_reference",
        "current_pi_dq",
        "clarke",
        "park",
        "inverse_park",
        "modulator",
        "current_sampling",
        "position_sensing",
        "fcs_mpc",
    ):
        block = kinds[needed]
        assert block["title"] and block["definition"] and block["math"], needed
        assert all(port["name"] for port in block["inputs"] + block["outputs"])
        assert all({"name", "unit", "default", "about"} <= set(p) for p in block["params"])
    assert kinds["current_pi_dq"]["linear"] and not kinds["fcs_mpc"]["linear"]
    # Every gain of a preset says the rule it came from.
    current = block_of(scheme_of(offered, "foc_servo"), "current")
    assert all(name in current["sources"] for name in ("kp_d", "ki_d", "kp_q", "ki_q"))
    assert "Kp = ωc·Lq" in current["sources"]["kp_q"]
    kinds = {s["kind"] for s in offered["scenarios"]}
    assert kinds == {"hold", "torque_step", "speed_step", "start", "load_step", "stall", "motion", "trip"}
    assert offered["limits"] == {
        "duration": 5.0,
        "steps": MOST_STEPS,
        "points": 5000,
        "seconds": 30.0,
        "sweep_seconds": 120.0,
    }
    json.dumps(offered)  # plain data all the way down


def test_the_gains_of_the_preset_are_the_rule_worked_by_hand(offered, base) -> None:
    # 20 kHz sampling: ωc = 2π·20000/20 = 2π·1000 rad/s. L = 70.71 µH, R = 25.25 mΩ.
    wc = 2 * np.pi * 1000.0
    gains = block_of(scheme_of(offered, "foc_servo"), "current")["params"]
    assert gains["kp_q"] == pytest.approx(wc * 70.71e-6)
    assert gains["ki_q"] == pytest.approx(wc * 0.02525)
    # Speed loop a decade below, symmetric optimum: a = 1/(ωs·(1/ωc + 1.5·Ts)).
    speed = block_of(scheme_of(offered, "foc_servo"), "speed")["params"]
    inertia, ws_ = offered["design"]["inertia"], wc / 10
    a = 1 / (ws_ * (1 / wc + 1.5 / 20000.0))
    assert speed["kp"] == pytest.approx(inertia * ws_)
    assert speed["ki"] == pytest.approx(inertia * ws_**2 / a)


def test_the_loops_come_with_bode_data_margins_poles_and_a_predicted_step(ws, base) -> None:
    found = posted("/api/control/loops", base, ws)
    assert found["scheme"]["id"] == "servo_joint" and found["missing"] == [] and len(found["assumes"]) == 4
    assert found["tuning"]["bandwidth_hz"] == pytest.approx(1000.0)
    for key in ("current_d", "current_q", "speed"):
        loop = found[key]
        bode = loop["bode"]
        assert len(bode["f"]) == len(bode["open_db"]) == len(bode["closed_deg"]) > 100
        assert loop["stable"] and all(p["stable"] for p in loop["poles"])
        assert loop["margins"]["phase_deg"] > 45 and loop["margins"]["gain_db"] > 6
        assert loop["step"]["rise_time"] > 0 and len(loop["step"]["t"]) == len(loop["step"]["y"])
        assert len(loop["open"]["den"]) >= len(loop["open"]["num"])
    # The current loop crosses over near the bandwidth it was tuned for, the speed loop a decade below.
    assert found["current_q"]["margins"]["crossover_hz"] == pytest.approx(1000.0, rel=0.05)
    assert found["speed"]["margins"]["crossover_hz"] == pytest.approx(100.0, rel=0.05)
    json.dumps(found)


def test_a_run_hands_over_every_wire_the_waveform_the_losses_and_the_five_channels(ws, base) -> None:
    got = posted("/api/control/run", {**base, "points": 200}, ws)
    assert got["scenario"]["kind"] == "hold" and got["fidelity"] == "switched"
    named = [w["name"] for w in got["wires"]]
    assert set(got["series"]["wires"]) == set(named) and "current.v_q" in named and "plant.torque" in named
    assert all(len(v) == len(got["series"]["t"]) <= 201 for v in got["series"]["wires"].values())
    wave = got["waveform"]
    assert wave["to"] - wave["from"] == pytest.approx(4 / got["settled"]["f_out"], rel=0.01)
    assert set(wave["switch_current"]) == {"a_high", "a_low", "b_high", "b_low", "c_high", "c_low"}
    # A leg's two switches carry its current between them, one at a time.
    high, low = np.array(wave["switch_current"]["a_high"]), np.array(wave["switch_current"]["a_low"])
    assert np.allclose(high - low, wave["i_a"]) and not np.any((high != 0) & (low != 0))
    assert len(got["losses"]["per_switch"]) == 6 and got["losses"]["loss"] > 0
    # Every channel but the two of shunts, which a drive with a current sensor has none of.
    shunts = ("unread_share", "read_error_rms")
    assert all(v is not None for k, v in got["channels"].items() if k not in shunts)
    assert all(got["channels"][k] is None for k in shunts)
    assert got["engine"]["loss"] > 0 and got["step"] is None
    assert got["level"] in ("ok", "caution", "undecided", "fail") and got["checks"]
    json.dumps(got)


def test_a_torque_step_and_a_speed_step_are_judged_on_their_own_signals(ws, base) -> None:
    torque = posted(
        "/api/control/run", {**base, "scheme": "foc_torque", "scenario": {"kind": "torque_step", "to": 2.0}}, ws
    )
    step = torque["step"]
    assert step["wire"] == "plant.torque" and step["to"] == 2.0
    assert 0 < step["rise_time"] < 0.001 and abs(step["steady_state_error"]) < 0.05
    speed = posted("/api/control/run", {**base, "scheme": "foc_servo", "scenario": {"kind": "speed_step"}}, ws)
    step = speed["step"]
    assert step["wire"] == "plant.omega_m" and step["to"] == pytest.approx(3000 * np.pi / 30)
    assert step["rise_time"] > 0 and step["settling_time"] is not None
    assert abs(step["steady_state_error"]) < 0.02 * (step["to"] - step["from"])


def test_a_load_step_pushes_the_speed_and_the_loop_brings_it_back(ws, base) -> None:
    request = {
        **base,
        "load": None,
        "shaft": {"inertia": 5e-4, "constant": 1.0},
        "scheme": "foc_servo",
        "scenario": {"kind": "load_step", "torque": 2.0},
    }
    got = posted("/api/control/run", request, ws)
    step = got["step"]
    assert step["kind"] == "disturbance" and step["deviation"] < 0 and step["recovery_time"] > 0
    speed = got["series"]["wires"]["plant.omega_m"]
    assert speed[-1] == pytest.approx(step["held"], rel=1e-3)
    load = got["series"]["wires"]["plant.load_torque"]
    assert (load[0], load[-1]) == pytest.approx((1.0, 3.0), rel=1e-3)
    # The torque of the motor ends on the load it now carries.
    assert got["series"]["wires"]["speed.torque"][-1] == pytest.approx(3.0, rel=0.02)


def test_a_start_from_standstill_keeps_to_the_current_limit_however_the_torque_comes_up(ws, base) -> None:
    limit = 40.0 * np.sqrt(2.0)
    ripple = 5.0  # A peak to peak of ripple rides on the limited current
    reached = {}
    for shape in ("hard", "slew", "s-curve"):
        request = {
            **base,
            "load": None,
            "shaft": {"inertia": 5e-4, "viscous": 0.005},
            "scheme": "foc_servo",
            "scenario": {"kind": "start", "shape": shape, "current_limit": 40.0, "duration": 0.15},
        }
        got = posted("/api/control/run", request, ws)
        assert limit * 0.95 < got["channels"]["i_switch_peak"] < limit + ripple, shape
        speed = got["series"]["wires"]["plant.omega_m"]
        assert speed[0] == 0.0 and speed[-1] == pytest.approx(3000 * np.pi / 30, rel=5e-3)
        assert got["step"]["overshoot"] < 0.05
        i_q = np.abs(np.array(got["series"]["wires"]["plant.i_q"]))
        reached[shape] = got["series"]["t"][int(np.argmax(i_q > 0.9 * limit))]
    # The harder the torque comes up, the sooner the current is at its limit.
    assert reached["hard"] < reached["slew"] < reached["s-curve"] < 0.01


def test_the_dead_time_and_the_devices_drop_are_off_until_asked_for(ws, base) -> None:
    plain = posted("/api/control/run", {**base, "scheme": "foc_torque"}, ws)
    real = posted(
        "/api/control/run", {**base, "scheme": "foc_torque", "inverter": {"dead_time": True, "device_drop": True}}, ws
    )
    assert not any("dead time in use" in said for said in plain["taken"])
    assert any("dead time in use" in said for said in real["taken"])
    # The regulator makes up the voltage the stage loses: more is asked for, the current stays.
    asked = [
        np.hypot(r["series"]["wires"]["current.v_d"][-1], r["series"]["wires"]["current.v_q"][-1])
        for r in (plain, real)
    ]
    assert asked[1] > asked[0] + 0.1
    assert real["ripple"]["i_q"] == pytest.approx(plain["ripple"]["i_q"], rel=0.005)


def test_the_streamed_run_says_how_far_it_is_and_ends_on_the_same_answer(ws, base) -> None:
    request = {**base, "scheme": "foc_servo", "scenario": {"kind": "speed_step"}, "points": 50}
    assert "/api/control/run" in routes.STREAMS
    lines = list(routes.stream("/api/control/run", request, ws))
    probes = [line["probe"] for line in lines[:-1]]
    assert len(probes) >= 10
    shares = [p["progress"] for p in probes]
    assert shares == sorted(shares) and 0 < shares[0] < shares[-1] <= 1.0
    assert all(set(p["series"]["wires"]) >= {"plant.i_q", "plant.omega_m", "cmd.speed"} for p in probes)
    # Of the controller a probe carries the first output of each block, and no more.
    sent = probes[0]["series"]["wires"]
    assert "current.v_d" in sent and "current.err_q" not in sent and "current.limited" not in sent
    assert probes[-1]["series"]["t"][-1] > probes[0]["series"]["t"][-1]
    assert lines[-1] == {"status": 200, "body": dispatch("/api/control/run", request, ws)[1]}
    # A request refused ends at once, as the plain address ends it.
    refused = list(routes.stream("/api/control/run", {**request, "fidelity": "exact"}, ws))
    assert len(refused) == 1 and refused[0]["status"] == 422 and refused[0]["body"]["field"] == "fidelity"


def _torque_scheme(offered: dict, change) -> dict:
    scheme = scheme_of(offered, "foc_torque")
    change(scheme)
    return scheme


REFUSED = {
    "scenario.kind": {"scenario": {"kind": "wobble"}},
    "scenario.duration": {"scenario": {"kind": "torque_step", "duration": 10}},
    "scenario.t_step": {"scenario": {"kind": "torque_step", "t_step": 0.02, "duration": 0.01}},
    "scenario.to": {"scenario": {"kind": "torque_step", "from": 1, "to": 1}},
    "scenario.from": {"scenario": {"kind": "torque_step", "from": "a lot"}},
    "scenario.periods": {"scenario": {"kind": "hold", "periods": 0}},
    "scenario.current_limit": {"scenario": {"kind": "start", "current_limit": 0}},
    "scenario.shape": {"scenario": {"kind": "start", "shape": "round"}},
    "scenario.rpm": {"scenario": {"kind": "torque_step", "rpm": 1e9}},
    "fidelity": {"fidelity": "exact"},
    "scheme": {"scheme": "nothing"},
    "points": {"points": 1},
    "seed": {"seed": -1},
    "window.to": {"window": {"from": 0, "to": 9}},
    "shaft.inertia": {"load": None, "shaft": {"inertia": 0}},
    "shaft": {"load": None, "shaft": {"inertia": 1e-3, "sticky": 1}},
    "inverter": {"inverter": {"dead": True}},
    "inverter.dead_time": {"inverter": {"dead_time": "yes"}},
    "device": {"device": ""},
    # The motor cannot give this torque at this speed whatever the control.
    "point": {"scenario": {"kind": "torque_step", "to": 400}},
}


@pytest.mark.parametrize("field", sorted(REFUSED))
def test_an_impossible_figure_is_refused_by_name(ws, base, field: str) -> None:
    status, body = dispatch("/api/control/run", {"scheme": "foc_torque", **base, **REFUSED[field]}, ws)
    assert status == 422, body
    assert body["field"] == field and body["refused"]


def test_a_scheme_that_cannot_be_built_is_refused_at_the_place_that_is_wrong(ws, base, offered) -> None:
    def refused(change) -> dict:
        status, body = dispatch("/api/control/run", {**base, "scheme": _torque_scheme(offered, change)}, ws)
        assert status == 422, body
        return body

    assert (
        refused(lambda s: block_of(s, "current")["params"].update(kp_q=-1.0))["field"] == "scheme.blocks.current.kp_q"
    )
    assert (
        refused(lambda s: block_of(s, "park")["inputs"].update(theta="nobody.theta"))["field"]
        == "scheme.blocks.park.inputs.theta"
    )
    assert refused(lambda s: block_of(s, "clarke").update(kind="clark"))["field"] == "scheme.blocks.clarke.kind"
    assert (
        refused(lambda s: block_of(s, "modulator")["params"].update(pwmm="sine"))["field"]
        == "scheme.blocks.modulator.pwmm"
    )
    assert refused(lambda s: block_of(s, "park")["inputs"].pop("theta"))["field"] == "scheme.blocks.park.inputs.theta"
    assert refused(lambda s: s["actuation"].update(wires=["modulator.d_a"]))["field"].startswith("scheme.actuation")
    assert refused(lambda s: s["timing"].update(update="triple"))["field"].startswith("scheme.timing")
    # A test the scheme has no input for names the scheme that has.
    status, body = dispatch(
        "/api/control/run", {**base, "scheme": "foc_torque", "scenario": {"kind": "speed_step"}}, ws
    )
    assert (status, body["field"]) == (422, "scenario.kind") and "foc_servo" in body["fix"]


def test_a_motor_of_another_kind_is_refused(ws, base) -> None:
    motor = {
        "type": "induction",
        "pole_pairs": 2,
        "rs": 0.1,
        "rr": 0.1,
        "lm": 0.02,
        "lls": 1e-3,
        "llr": 1e-3,
        "i_magnetising": 5,
    }
    status, body = dispatch("/api/control/presets", {**base, "motor": motor}, ws)
    assert (status, body["field"]) == (422, "motor") and "permanent-magnet" in body["refused"]
    status, body = dispatch("/api/control/run", {"motor": base["motor"], "conditions": base["conditions"]}, ws)
    assert status == 422 and body["field"] == "device"


def test_gains_that_do_not_hold_are_run_with_a_caution_and_a_runaway_is_refused(ws, base, offered) -> None:
    def eightfold(s: dict) -> None:
        gains = block_of(s, "current")["params"]
        gains.update(kp_d=8 * gains["kp_d"], kp_q=8 * gains["kp_q"])

    # Eight times the gain is past the gain margin of 10 dB: the linear analysis sees it, says
    # which pole, and the run goes ahead to show the oscillation the voltage limit holds it in.
    status, body = dispatch("/api/control/run", {**base, "scheme": _torque_scheme(offered, eightfold)}, ws)
    assert status == 200
    verdict = body["stability"]
    assert verdict["linear_stable"] is False and verdict["analysed"] and verdict["loop"].startswith("current_")
    assert verdict["pole"]["abs"] > 1.0 and "outside the unit circle" in verdict["said"]
    assert verdict["said"].startswith("the loop is unstable with these gains")
    cautions = [c for c in body["checks"] if c["topic"] == "stability"]
    assert [c["level"] for c in cautions] == ["caution"] and cautions[0]["message"] == verdict["said"]
    assert body["level"] in ("caution", "undecided", "fail")
    # The oscillation is there to see: many times the ripple of the gains the rule gives.
    status, sound = dispatch("/api/control/run", {**base, "scheme": _torque_scheme(offered, lambda s: None)}, ws)
    assert status == 200 and sound["stability"]["linear_stable"] is True
    assert not [c for c in sound["checks"] if c["topic"] == "stability"]
    assert body["channels"]["ripple_rms"] > 3 * sound["channels"]["ripple_rms"]
    # The angle taken from the wrong wire: nothing linear sees it, and the current runs away.
    lost = _torque_scheme(offered, lambda s: block_of(s, "park")["inputs"].update(theta="time.t"))
    status, body = dispatch("/api/control/run", {**base, "scheme": lost}, ws)
    assert status == 422 and body["field"] == "scheme"
    assert body["refused"].startswith("the loop is unstable with these gains")
    assert "phase current passed" in body["refused"]


def test_the_kernel_itself_ends_a_runaway_as_unstable() -> None:
    d = design()
    data = foc_torque(d).data()
    # Positive feedback: the measured currents fed back on the wrong axes.
    block_of(data, "current")["inputs"].update(i_d="park.q", i_q="park.d")
    block_of(data, "current")["params"].update(kp_d=3.0, kp_q=3.0)
    from motionsim.control import scheme_from

    asked = Trial(duration=0.05, torque=lambda t: 2.0, trip=200.0)
    with pytest.raises(Unstable) as said:
        run(scheme_from(data), d, asked)
    assert "the loop is unstable with these gains" in str(said.value)


def test_a_run_of_too_many_sampling_instants_is_refused_before_it_starts(ws, base, offered) -> None:
    fast = scheme_of(offered, "mpc_torque")
    fast["timing"]["f_control"] = 150e3
    request = {**base, "scheme": fast, "scenario": {"kind": "torque_step", "duration": 5, "t_step": 1}}
    began = time.perf_counter()
    status, body = dispatch("/api/control/run", request, ws)
    assert status == 422 and body["field"] == "scenario.duration" and "500 000" in body["refused"]
    assert time.perf_counter() - began < 1.0
    with pytest.raises(Refusal):
        kernel(foc_torque(design()), design(), Trial(duration=(MOST_STEPS + 1) / 20000.0))


def _noisy(seed: int):
    d = design()
    data = foc_torque(d).data()
    block_of(data, "sample")["params"].update(noise=0.3, bits=12, full_scale=80.0)
    from motionsim.control import scheme_from

    w = d.omega
    asked = Trial(duration=0.02, speed=lambda t: w, torque=lambda t: 2.0, initial={"omega_m": w})
    return run(scheme_from(data), d, asked, seed=seed)


def test_a_run_with_noise_is_the_same_run_for_the_same_seed() -> None:
    first, again, other = _noisy(7), _noisy(7), _noisy(8)
    assert np.array_equal(first.values, again.values) and np.array_equal(first.corners, again.corners)
    assert np.array_equal(first.events, again.events) and np.array_equal(first.squared, again.squared)
    assert not np.array_equal(first.values, other.values)
    # And the noise is there: the sampled current is not the plant's.
    read, real = first.wire("sample.i_b"), first.wire("plant.i_b")
    assert 0.2 < np.std(read - real) < 0.4


def test_the_service_answers_the_same_seed_with_the_same_answer(ws, base, offered) -> None:
    noisy = scheme_of(offered, "foc_torque")
    block_of(noisy, "sample")["params"]["noise"] = 0.5
    request = {**base, "scheme": noisy, "seed": 11, "points": 100}
    first, again = (posted("/api/control/run", request, ws) for _ in range(2))
    assert first == again
    assert posted("/api/control/run", {**request, "seed": 12}, ws)["series"] != first["series"]


def test_a_second_of_switched_simulation_at_20_khz_takes_under_8_seconds() -> None:
    d = design()
    w = d.omega
    asked = Trial(duration=1.0, speed=lambda t: w, torque=lambda t: 2.0, initial={"omega_m": w})
    began = time.perf_counter()
    trace = run(foc_torque(d), d, asked, fidelity="switched")
    took = time.perf_counter() - began
    assert trace.time.size == 20000 and trace.ended == "duration"
    assert trace.wire("plant.i_q")[-1] == pytest.approx(2.0 / (1.5 * SURFACE.pole_pairs * SURFACE.psi), rel=0.01)
    assert took < 8.0, f"{took:.2f} s"
