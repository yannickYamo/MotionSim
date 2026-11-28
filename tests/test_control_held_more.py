"""The control lab held to more: the pulsed rating takes the loop's own overshoot from a run,
an observer's floor is worked out from what it reads through and set beside the design and
its motion, the open-loop start can take a reversal through standstill, and a window of the
design's own motion is run through the loop.

Every expected value is a closed form worked out here, the tool's settled engine, or another
reading of the same run made apart from the code under test."""

from __future__ import annotations

import copy
import math

import numpy as np
import pytest
from test_control_bench import engine_answer, posted, started, workspace

from motionsim import guard
from motionsim.control.floor import EMF_OVER_ERROR
from motionsim.control.observers import EMF_FLOOR
from motionsim.control.startup import HYSTERESIS
from motionsim.recommend.control import EMF_OVER_ERROR as CLOSED_FORM_MARGIN
from motionsim.service.routes import dispatch

KEY = "example-mosfet"
RPM = 30.0 / math.pi


@pytest.fixture(scope="module")
def ws():
    return workspace()


def scheme_of(base: dict, ws, scheme_id: str, **params) -> dict:
    """A preset as tuned for the design, with the open-loop start's parameters changed."""
    found = copy.deepcopy(next(s for s in posted("/api/control/presets", base, ws)["schemes"] if s["id"] == scheme_id))
    found.pop("tests", None)
    start = next((b for b in found["blocks"] if b["kind"] == "if_startup"), None)
    if start is not None:
        start["params"].update(params)
    return found


def flux(base: dict) -> float:
    """Wb peak, from the motor's kv (rpm per volt, line to line peak): ψ = 60/(√3·2π·kv·p)."""
    m = base["motor"]
    return 60.0 / (math.sqrt(3.0) * 2.0 * math.pi * m["kv"] * m["pole_pairs"])


def handover_of(scheme: dict) -> float:
    return next(b for b in scheme["blocks"] if b["kind"] == "if_startup")["params"]["handover"]


def rated(ws, i_pulsed: float) -> str:
    """The made-up part with a pulsed rating, kept in the workspace under its own name."""
    import yaml

    from motionsim.service.workspace import EXAMPLES

    data = yaml.safe_load(EXAMPLES[KEY].read_text(encoding="utf-8"))
    data["ratings"]["i_pulsed"] = i_pulsed
    name = f"pulsed-{i_pulsed:g}".replace(".", "-")
    (ws.folder / f"{name}.device.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return name


# a) The pulsed rating takes the run's own overshoot.


def test_a_torque_step_holds_the_pulsed_rating_to_its_own_overshoot(ws) -> None:
    base = started(KEY, ws)
    answer = posted("/api/control/run", {**base, "scheme": "foc_torque", "scenario": {"kind": "torque_step"}}, ws)
    pulsed, step = answer["pulsed"], answer["step"]
    assert pulsed["measured"] and pulsed["allowance"] == guard.OVERSHOOT and pulsed["ripple_half"] > 0
    # From no torque, the current's size passes its end value by the share the torque passes
    # its step (torque is 1.5·p·ψ·iq on this motor's surface magnets, and id stays near nought):
    # the step's own overshoot, read by metrics.step_response on the torque, within half a point.
    assert pulsed["overshoot"] == pytest.approx(step["overshoot"], abs=0.005)
    assert pulsed["overshoot"] < guard.OVERSHOOT
    # The current the rating is held to is the settled current times one and the overshoot,
    # with the ripple on top: the run's own peak.
    peak = max(s["i_peak"] for s in answer["losses"]["per_switch"])
    assert pulsed["held"] == pytest.approx(pulsed["settled"] * (1 + pulsed["overshoot"]) + pulsed["ripple_half"])
    assert pulsed["held"] == pytest.approx(peak, rel=0.02)


def test_with_too_little_room_the_check_names_the_runs_overshoot_and_a_hold_the_allowance(ws) -> None:
    base = started(KEY, ws)
    step = posted("/api/control/run", {**base, "scheme": "foc_torque", "scenario": {"kind": "torque_step"}}, ws)
    p = step["pulsed"]
    # A rating between the settled current with its ripple and that with the overshoot too.
    between = p["settled"] + p["ripple_half"] + 0.5 * p["settled"] * p["overshoot"]
    device = rated(ws, round(between, 4))
    ran = posted(
        "/api/control/run", {**base, "device": device, "scheme": "foc_torque", "scenario": {"kind": "torque_step"}}, ws
    )
    said = [c for c in ran["checks"] if c["topic"] == "current" and c["level"] == "caution"]
    assert said and "the current overshot by in this run's torque step" in said[0]["message"], ran["checks"]
    # A hold has no step of its own: its peak is held with the fixed allowance on top, and a
    # rating between the two says so.
    plain = posted("/api/control/run", {**base, "scheme": "foc_torque"}, ws)["pulsed"]
    device = rated(ws, round(plain["settled"] * (1 + 0.5 * guard.OVERSHOOT), 4))
    held = posted("/api/control/run", {**base, "device": device, "scheme": "foc_torque"}, ws)
    assert not held["pulsed"]["measured"] and held["pulsed"]["overshoot"] == guard.OVERSHOOT
    words = [c["message"] for c in held["checks"] if c["topic"] == "current" and c["level"] == "caution"]
    assert words and "a fixed allowance" in words[0], held["checks"]


def test_the_five_steps_say_their_overshoot_is_the_fixed_allowance() -> None:
    from motionsim.device import load_device
    from motionsim.engine import OperatingPoint
    from motionsim.engine.solver import solve
    from motionsim.service.workspace import EXAMPLES

    device = load_device(EXAMPLES["example"])
    device.ratings.i_pulsed = 32.0
    op = OperatingPoint(v_dc=300, i_rms=10, modulation_index=0.9, power_factor=0.85, f_sw=8000, t_sink=60)
    result = solve(device, op)
    # 28 A settled, and 15% on it, is 32.2 A: past the 32 A rating, with the allowance said.
    found = guard.check(device, op, result, 28.0)
    words = [c.message for c in found if c.topic == "current" and "pulsed" in c.message]
    assert words and "15%" in words[0] and "a fixed allowance" in words[0]
    taken = guard.check(device, op, result, 28.0, overshoot=0.2, overshoot_from="a run")
    assert any("the 20% the current overshot by in a run" in c.message for c in taken)


def _stepped_trace(i_from: float, i_to: float, ripple: float, f_sw: float = 20e3):
    """A torque step's current, worked here: a second-order answer of 10% overshoot from
    `i_from` to `i_to` on the q axis, with a triangle of ±`ripple` at the switching frequency
    on top, sampled twenty times a period. Returned as the plan and the trace the check reads."""
    import types

    zeta = -math.log(0.10) / math.sqrt(math.pi**2 + math.log(0.10) ** 2)  # 10% overshoot
    wn, t_step = 2 * math.pi * 200.0, 0.002
    t = np.arange(0.0, 0.045, 1 / (20 * f_sw))
    x = np.clip(t - t_step, 0.0, None)
    wd = wn * math.sqrt(1 - zeta**2)
    unit = 1 - np.exp(-zeta * wn * x) * (np.cos(wd * x) + zeta / math.sqrt(1 - zeta**2) * np.sin(wd * x))
    phase = (t * f_sw) % 1.0
    triangle = ripple * (4 * np.abs(phase - 0.5) - 1)
    iq = i_from + (i_to - i_from) * unit + triangle
    wires = {"plant.i_d": np.zeros_like(t), "plant.i_q": iq}
    plan = types.SimpleNamespace(
        tracked={"kind": "step", "wire": "plant.torque", "from": i_from, "to": i_to, "t_step": t_step}
    )
    return plan, types.SimpleNamespace(time=t, wire=wires.__getitem__), 1 / f_sw


def test_the_overshoot_is_read_on_the_current_s_mean_over_a_switching_period() -> None:
    from motionsim.service.control.checks import current_overshoot

    plan, trace, window = _stepped_trace(2.0, 20.0, ripple=1.0)
    found = current_overshoot(plan, trace, window)
    # The peak is 20 + 18·10% = 21.8 A over 20 A settled: 9%, the ripple's ±1 A not in it.
    assert found is not None and found["share"] == pytest.approx(0.09, abs=0.005)
    assert found["settled"] == pytest.approx(20.0, abs=0.01)


def test_a_step_down_of_the_torque_is_held_with_the_allowance(ws) -> None:
    from motionsim.service.control.checks import current_overshoot

    # 20 A down to 2 A with no overshoot of its own: the old current is not an overshoot.
    plan, trace, window = _stepped_trace(20.0, 2.0, ripple=0.0)
    assert current_overshoot(plan, trace, window) is None
    base = started(KEY, ws)
    scenario = {"kind": "torque_step", "from": 2.0, "to": 0.2}
    pulsed = posted("/api/control/run", {**base, "scheme": "foc_torque", "scenario": scenario}, ws)["pulsed"]
    assert not pulsed["measured"] and pulsed["overshoot"] == guard.OVERSHOOT
    # A step up from a torque already carried is read as before.
    up = posted(
        "/api/control/run",
        {**base, "scheme": "foc_torque", "scenario": {"kind": "torque_step", "from": 0.5, "to": 2.0}},
        ws,
    )
    assert up["pulsed"]["measured"] and up["pulsed"]["overshoot"] < guard.OVERSHOOT


# b) The observer's floor.


def test_an_ideal_stage_leaves_the_observer_its_own_floor_and_the_stage_adds_its_dead_time(ws) -> None:
    base = started(KEY, ws)
    pairs, psi = base["motor"]["pole_pairs"], flux(base)
    ideal = posted("/api/control/run", {**base, "scheme": "sensorless_emf", "fidelity": "averaged"}, ws)["floor"]
    # Under the back-EMF of 5 Hz electrical the loop locks onto nothing: 300/p rpm.
    assert ideal["rpm"] == pytest.approx(60.0 * EMF_FLOOR / pairs) and ideal["held_by"] == "lock"
    assert EMF_OVER_ERROR == CLOSED_FORM_MARGIN  # the settled result's closed form and the lab take one margin
    dead = posted(
        "/api/control/run",
        {
            **base,
            "scheme": "sensorless_emf",
            "fidelity": "averaged",
            "inverter": {"dead_time": True, "device_drop": True},
        },
        ws,
    )
    found = dead["floor"]
    c = base["conditions"]
    t_dead = next(
        float(t.split("dead time in use, ")[1].split(" ns")[0]) for t in dead["taken"] if "dead time in use" in t
    )
    drop = next(float(t.split("device's drop: ")[1].split(" V")[0]) for t in dead["taken"] if "device's drop" in t)
    # The dead time's slice of the supply, t_dead·f_sw·V, and the device's drop, four times
    # over, is the back-EMF ψ·ω.
    wrong = t_dead * 1e-9 * c["f_sw"] * c["v_dc"] + drop
    assert found["stage_v"] == pytest.approx(wrong, rel=1e-3)
    assert found["rpm"] == pytest.approx(EMF_OVER_ERROR * wrong / psi / pairs * RPM, rel=1e-3)
    assert found["rpm"] > ideal["rpm"]
    # A real stage has them whether the run simulates them or not: the ideal run's floor on
    # hardware is the same closed form, and the run that carries them says the same.
    hardware = EMF_OVER_ERROR * wrong / psi / pairs * RPM
    assert ideal["hardware_rpm"] == pytest.approx(hardware, rel=1e-3)
    assert found["hardware_rpm"] == pytest.approx(hardware, rel=1e-3)


def test_noise_on_the_samples_raises_the_floor_by_the_observers_own_path(ws) -> None:
    base = started(KEY, ws)
    scheme = scheme_of(base, ws, "sensorless_emf")
    sample = next(b for b in scheme["blocks"] if b["kind"] == "current_sampling")
    sample["params"]["noise"] = 0.5
    observer = next(b for b in scheme["blocks"] if b["kind"] == "observer_emf_pll")
    found = posted("/api/control/run", {**base, "scheme": scheme, "fidelity": "averaged"}, ws)["floor"]
    m = base["motor"]
    m = {"rs": m["rs"], "ld": m["l"], "flux_linkage": flux(base), "pole_pairs": m["pole_pairs"]}
    # The observer subtracts R·i and differentiates L·i through its filter of bandwidth g:
    # half an ampere of noise is 0.5·√(R² + (g·L)²) volts it cannot explain.
    g = 2 * math.pi * observer["params"]["bandwidth"]
    assert found["noise_v"] == pytest.approx(0.5 * math.hypot(m["rs"], g * m["ld"]), rel=1e-6)
    by_error = EMF_OVER_ERROR * found["noise_v"] / m["flux_linkage"] / m["pole_pairs"] * RPM
    assert found["rpm"] == pytest.approx(max(by_error, 60.0 * EMF_FLOOR / m["pole_pairs"]), rel=1e-6)


def test_the_floor_is_set_beside_the_design_point_and_a_motion_that_reverses(ws) -> None:
    base = started(KEY, ws)
    mission = {"time": [0.0, 0.1, 0.2, 0.3], "rpm": [600.0, 10.0, -10.0, -600.0], "torque": [0.5, 0.5, -0.5, -0.5]}
    answer = posted(
        "/api/control/run", {**base, "mission": mission, "scheme": "sensorless_emf", "fidelity": "averaged"}, ws
    )
    found = answer["floor"]
    assert found["design_rpm"] == base["conditions"]["rpm"]
    assert found["motion"]["reverses"] and found["motion"]["lowest_rpm"] == 10.0
    # Each instant stands until the next: two of the four are under the floor, a stretch of 0.1 s each.
    assert found["motion"]["under_share"] == pytest.approx(0.5)
    floor = next(f for f in answer["verdict"]["findings"] if f["id"] == "floor")
    assert floor["tag"] == "improve" and floor["lever"]["param"] == "handback"
    assert floor["lever"]["to"] == pytest.approx(HYSTERESIS * handover_of(answer["scheme"]))
    # What the C export does with a hand-back is said by the export, where it is asked: not here.
    assert "hand-back" in floor["expect"] and "export" not in floor["expect"]


# The hand-back: open loop through standstill.


def test_a_hand_back_holds_the_design_point_where_the_engine_settles(ws) -> None:
    # Above the floor the hand-back never acts: the held point is the run without it, to the
    # last figure, and it ends where the settled engine does within 1%.
    base = started(KEY, ws)
    plain = scheme_of(base, ws, "sensorless_emf")
    handed = scheme_of(base, ws, "sensorless_emf", handback=HYSTERESIS * handover_of(plain))
    without = posted("/api/control/run", {**base, "scheme": plain}, ws)
    withit = posted("/api/control/run", {**base, "scheme": handed}, ws)
    assert withit["losses"]["loss"] == without["losses"]["loss"]
    engine = engine_answer(KEY, base, ws)
    assert withit["losses"]["loss"] == pytest.approx(engine["loss"], rel=0.01)
    assert withit["losses"]["tj_peak"] - engine["t_sink"] == pytest.approx(
        engine["tj_peak"] - engine["t_sink"], rel=0.01
    )


def test_with_a_hand_back_a_reversal_keeps_the_rotor_that_the_observer_alone_loses(ws) -> None:
    base = started(KEY, ws)
    rpm = 0.5 * base["conditions"]["rpm"]
    test = {"kind": "speed_step", "from_rpm": rpm, "to_rpm": -rpm}
    plain = scheme_of(base, ws, "sensorless_smo")
    handed = scheme_of(base, ws, "sensorless_smo", handback=HYSTERESIS * handover_of(plain))
    runs = {}
    for name, scheme in (("without", plain), ("with", handed)):
        runs[name] = posted(
            "/api/control/run", {**base, "scheme": scheme, "scenario": test, "fidelity": "averaged", "points": 1500}, ws
        )
    lost = [c["message"] for c in runs["without"]["checks"] if "loses the rotor" in c["message"]]
    assert lost and "hand-back" in lost[0]
    kept = runs["with"]
    assert not [c for c in kept["checks"] if c["topic"] == "tracking"], kept["checks"]
    assert kept["series"]["wires"]["plant.omega_m"][-1] * RPM == pytest.approx(-rpm, rel=0.01)
    # Wherever the scheme is on the observer, its angle is the rotor's within a few degrees.
    wires = kept["series"]["wires"]
    on = np.array(wires["position.mode"]) >= 1.0
    assert float(np.degrees(np.abs(np.array(wires["observer.error"])[on])).max()) < 10.0
    # Through standstill the drive was open loop: the mode fell to nought and rose again.
    mode = np.array(wires["position.mode"])
    assert mode.min() == 0.0 and mode[-1] == 1.0


def test_the_export_refuses_a_hand_back_it_does_not_carry(ws) -> None:
    base = started(KEY, ws)
    handed = scheme_of(base, ws, "sensorless_emf", handback=100.0)
    status, body = dispatch("/api/control/export_c", {**base, "scheme": handed}, ws)
    assert status == 422 and body["field"] == "scheme.blocks.position.handback"


# c) A window of the motion through the loop.

# A mission with one instant of much more torque than the rest, and a fast change elsewhere.
MISSION = {
    "time": [0.0, 0.2, 0.4, 0.5, 0.6, 0.8, 1.0, 1.02, 1.2],
    "rpm": [2000.0] * 9,
    "torque": [1.0, 1.0, 1.0, 4.0, 1.0, 1.0, 1.0, 3.0, 3.0],
}


def test_the_window_of_peak_torque_is_centred_on_it_and_the_drive_follows_it(ws) -> None:
    base = started(KEY, ws)
    answer = posted(
        "/api/control/run",
        {**base, "mission": MISSION, "scheme": "foc_torque", "scenario": {"kind": "motion", "span": 0.1}},
        ws,
    )
    w = answer["window"]
    assert (w["from"], w["to"]) == pytest.approx((0.45, 0.55)) and w["peak_torque"] == 4.0
    assert w["wire"] == "plant.torque"
    # A mission's instant stands until the next, as the five steps step through it: over the
    # window the motion asks 1 N·m from 0.45 to 0.5 s and 4 N·m from 0.5 to 0.55 s. A torque
    # scheme on a free shaft whose load leaves it the motion's torque makes the mean of that,
    # (1 + 4)/2 = 2.5 N·m, within 1%.
    t = np.array(answer["series"]["t"])
    made = np.array(answer["series"]["wires"]["plant.torque"])
    assert float(np.trapezoid(made, t) / (t[-1] - t[0])) == pytest.approx(2.5, rel=0.01)
    assert any("each instant of the mission stands until the next" in s for s in answer["taken"])
    # No drive makes the step of 3 N·m at 0.5 s at once: the error is read from ten of the
    # current loop's time constants after it, 10/ωc, ωc = 2π/(20·Ts) by the tuning rule (the
    # control period Ts is the carrier's, 50 µs). Read so, and read here on the series apart
    # from the code (5 ms after the step), the drive makes what is asked within 2% of the peak.
    rise = 10.0 / (2 * math.pi / (20 * 50e-6))
    assert w["rise"] == pytest.approx(rise, rel=1e-6)
    assert w["torque_error"]["peak"] < 0.02 * 4.0 and w["torque_error"]["rms"] < 0.02 * 4.0
    asked = np.where(t + 0.45 < 0.5, 1.0, 4.0)
    risen = (t + 0.45 < 0.5) | (t + 0.45 > 0.505)
    assert float(np.sqrt(np.mean((made - asked)[risen] ** 2))) < 0.02 * 4.0
    assert answer["thermal"]["t"] and answer["losses"]["tj_peak"] > base["conditions"]["t_sink"]
    found = next(f for f in answer["verdict"]["findings"] if f["id"] == "motion")
    assert found["tag"] == "good" and answer["verdict"]["summary"].startswith("Good: the drive follows")


def test_the_window_of_fastest_change_and_a_speed_scheme_on_it(ws) -> None:
    base = started(KEY, ws)
    scenario = {"kind": "motion", "pick": "change", "span": 0.1}
    answer = posted("/api/control/run", {**base, "mission": MISSION, "scheme": "foc_servo", "scenario": scenario}, ws)
    w = answer["window"]
    # The fastest change is 2 N·m in 20 ms, between 1.0 and 1.02 s: the window is centred on 1.01 s.
    assert w["at"] == pytest.approx(1.01) and w["rate"] == pytest.approx(100.0)
    assert (w["from"], w["to"]) == pytest.approx((0.96, 1.06))
    # The speed asked for is constant: the speed loop holds it against the load's step.
    assert w["wire"] == "plant.omega_m" and w["speed_error"]["peak"] < 0.02 * 2000.0


def test_a_motion_window_with_no_motion_is_refused_by_the_test(ws) -> None:
    status, body = dispatch("/api/control/run", {**started(KEY, ws), "scenario": {"kind": "motion"}}, ws)
    assert status == 422 and body["field"] == "scenario.kind" and "motion" in body["refused"]


def test_time_at_rest_is_not_time_under_the_observer_s_floor() -> None:
    import numpy as np

    from motionsim.service.control.motion import Motion, against_floor

    fields = {f.name for f in __import__("dataclasses").fields(Motion)}
    t = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    rpm = np.array([0.0, 0.0, 50.0, 1000.0, 1000.0])
    torque = np.array([0.0, 0.0, 1.0, 1.0, 1.0])
    base = {"t": t, "rpm": rpm, "torque": torque, "duration": 5.0, "held": False}
    motion = Motion(**{k: v for k, v in base.items() if k in fields}, **{k: None for k in fields - base.keys()})
    # Two instants off, one driven under the floor, two over it: a fifth of the time, not three.
    assert against_floor(motion, 100.0)["under_share"] == pytest.approx(0.2)
    holding = Motion(**{**{k: getattr(motion, k) for k in fields}, "torque": np.ones(5)})
    assert against_floor(holding, 100.0)["under_share"] == pytest.approx(0.6)


def test_a_load_step_lost_in_the_load_s_own_swing_is_a_note_and_blames_no_gain() -> None:
    import numpy as np

    from motionsim.control import metrics, verdict

    t = np.linspace(0.0, 0.1, 2001)
    held = 440.0
    swinging = held + 16.0 * np.sin(2 * np.pi * 70.0 * t)  # a compressor's turn
    step = metrics.disturbance(t, swinging, 0.02, held) | {"held": held}
    assert step["swing_before"] == pytest.approx(16.0, rel=0.02)
    (found,) = verdict._disturbance({}, step, "speed")
    assert found["tag"] == verdict.NOTE and found.get("lever") is None
    assert "cannot be told from the swing" in found["said"]
    # A steady speed that dips on the step is still judged on its dip.
    steady = np.where(t < 0.02, held, held - 40.0 * np.exp(-(t - 0.02) / 0.01))
    step = metrics.disturbance(t, steady, 0.02, held) | {"held": held}
    assert step["swing_before"] == 0.0
    (found,) = verdict._disturbance({}, step, "speed")
    assert found["tag"] == verdict.IMPROVE
