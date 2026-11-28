"""Every scheme the control lab offers holds the design point of unlike designs, every block
it is made of says what it is, and the lab can be driven from the terminal."""

from __future__ import annotations

import json
import math

import pytest
import yaml
from test_control_bench import design, posted, started, workspace

from motionsim import cli
from motionsim.control import context
from motionsim.control.blocks import kind_of
from motionsim.control.presets import BUILDERS
from motionsim.design import starting_setup
from motionsim.service.workspace import Workspace

DESIGNS = ("example-mosfet", "example-sic")
NEW_KINDS = (
    "observer_emf_pll",
    "observer_smo",
    "observer_flux",
    "if_startup",
    "if_current",
    "variable_frequency",
    "dead_time_compensation",
    "thermal_supervisor",
    "current_discrete_dq",
    "deadbeat_dq",
    "dtc",
)
# The torque a scheme holds against the torque asked. Direct torque control lets go at the
# reference and takes hold a band below it, so it sits half a band under (its definition says
# so); the supervisor and the others are on it.
TOLERANCE = {"dtc_torque": 0.08}


@pytest.fixture(scope="module")
def ws():
    return workspace()


@pytest.fixture(scope="module", params=DESIGNS)
def offered(request, ws):
    return request.param, posted("/api/control/presets", started(request.param, ws), ws)


def test_every_scheme_offered_holds_the_design_point(ws, offered) -> None:
    key, told = offered
    asked = started(key, ws)["conditions"]["torque"]
    assert len(told["schemes"]) >= 15
    for scheme in told["schemes"]:
        answer = posted("/api/control/run", {**started(key, ws), "scheme": scheme["id"]}, ws)
        held = answer["ripple"]["torque_mean"]
        assert held == pytest.approx(asked, rel=TOLERANCE.get(scheme["id"], 0.03)), scheme["id"]
        assert answer["level"] != "fail", scheme["id"]
        assert answer["start"]["torque"] == pytest.approx(answer["settled"]["torque"]), "a hold starts where it is held"
        verdict = answer["stability"]
        assert verdict["linear_stable"] is True and verdict["said"], scheme["id"]
        if any(b["kind"].startswith("observer") for b in scheme["blocks"]):  # a scheme with no rotor sensor
            assert abs(answer["sensing"]["angle_error_mean"]) < 0.5 and answer["sensing"]["angle_error_rms"] < 0.5
        else:
            assert answer["sensing"] is None


def test_every_scheme_says_where_each_figure_it_sets_comes_from(offered) -> None:
    _, told = offered
    for scheme in told["schemes"]:
        assert scheme["label"] and scheme["blocks"]
        for block in scheme["blocks"]:
            assert block["kind"] in told["blocks"], block["kind"]
            for name, said in (block.get("sources") or {}).items():
                assert name in block["params"] and said, (scheme["id"], block["name"], name)


def test_every_new_block_says_what_it_is_in_words_and_in_mathematics(offered) -> None:
    _, told = offered
    for kind in NEW_KINDS:
        block = told["blocks"][kind]
        assert block["title"] and len(block["definition"]) > 80, kind
        assert block["math"], kind
        assert block["inputs"] and block["outputs"], kind
        for param in block["params"]:
            assert param["about"], (kind, param["name"])


def test_a_step_starts_from_its_own_point_and_settled_stays_the_design_point(ws) -> None:
    base = started("example-mosfet", ws)
    step = {"kind": "torque_step", "from": 1.0, "to": 3.0, "rpm": 1000.0}
    answer = posted("/api/control/run", {**base, "scheme": "foc_torque", "scenario": step}, ws)
    assert answer["start"]["torque"] == 1.0
    assert answer["start"]["omega_m"] == pytest.approx(1000.0 * math.pi / 30.0)
    assert answer["settled"]["torque"] == base["conditions"]["torque"]
    assert answer["settled"]["omega_m"] == pytest.approx(base["conditions"]["rpm"] * math.pi / 30.0)
    # A controller with no transfer function is not called stable or unstable: it is said why.
    answer = posted("/api/control/run", {**base, "scheme": "mpc_torque"}, ws)
    assert answer["stability"]["analysed"] is False and answer["stability"]["linear_stable"] is True
    assert answer["stability"]["said"].startswith("not analysed")


def test_the_compensation_adds_the_dead_times_volt_seconds_and_the_drop_against_each_current() -> None:
    d = design(t_dead=200e-9, v_drop=0.6)
    scheme = BUILDERS["foc_compensated"](d)
    spec = next(b for b in scheme.blocks if b.kind == "dead_time_compensation")
    assert spec.params["dead_time"] == 200e-9 and spec.params["drop"] == 0.6
    block = kind_of("dead_time_compensation")("comp", {**spec.params, "band": 0.0}, context(d, scheme))
    # 200 ns of a 50 µs period at 48 V is 0.192 V, and the drop 0.6 V: 0.792 V a phase.
    by_hand = 200e-9 * 20000.0 * 48.0 + 0.6
    alpha, beta, added = block.step(0.0, 5.0, -3.0, 10.0, -4.0, -6.0, 48.0)
    assert added == pytest.approx(by_hand)
    # Phase a carries current forwards, b and c backwards: +, −, −.
    assert alpha == pytest.approx(5.0 + (2 * by_hand + by_hand + by_hand) / 3.0)
    assert beta == pytest.approx(-3.0 + (-by_hand + by_hand) / math.sqrt(3.0))
    # Inside the band the sign is brought in with the current: half the band, half of it.
    soft = kind_of("dead_time_compensation")("comp", {**spec.params, "band": 8.0}, context(d, scheme))
    alpha, beta, _ = soft.step(0.0, 0.0, 0.0, 4.0, -4.0, 0.0, 48.0)
    assert alpha == pytest.approx((2 * 0.5 * by_hand + 0.5 * by_hand) / 3.0)
    assert beta == pytest.approx(-0.5 * by_hand / math.sqrt(3.0))


def test_a_stage_with_dead_time_loses_torque_at_the_voltage_limit_and_the_compensation_gives_it_back(ws) -> None:
    # A deadbeat-free check on the whole path: the made-up servo of the first example runs at
    # its voltage limit, where what the dead time takes cannot be made up by the regulator.
    base = {**started("example", ws), "inverter": {"dead_time": True, "device_drop": True}}
    plain = posted("/api/control/run", {**base, "scheme": "foc_torque"}, ws)
    made_up = posted("/api/control/run", {**base, "scheme": "foc_compensated"}, ws)
    asked = base["conditions"]["torque"]
    assert abs(made_up["ripple"]["torque_mean"] - asked) < abs(plain["ripple"]["torque_mean"] - asked)


@pytest.fixture(scope="module")
def setup_file(tmp_path_factory) -> str:
    folder = tmp_path_factory.mktemp("control")
    file = folder / "design.yaml"
    file.write_text(yaml.safe_dump(starting_setup("example-mosfet", Workspace(folder / "ws"))), encoding="utf-8")
    return str(file)


def said(capsys, *argv: str) -> tuple[int, str]:
    capsys.readouterr()
    status = cli.main(["control", *argv])
    out = capsys.readouterr()
    # An answer goes to the output and leaves the error stream empty; a refusal in words goes
    # to the error stream, as with every other command.
    assert (out.err == "") is (status == 0 or "--json" in argv), out.err
    return status, out.out + out.err


def test_the_terminal_lists_the_schemes_and_the_explorations(capsys, setup_file) -> None:
    status, text = said(capsys, "presets", setup_file)
    assert status == 0 and "Chosen for this design: servo_joint" in text
    for scheme in ("foc_torque", "sensorless_flux", "thermal_guard", "deadbeat_torque"):
        assert f"  {scheme}: " in text
    assert "stall" in text
    status, text = said(capsys, "presets", setup_file, "--json")
    assert status == 0 and json.loads(text)["chosen"] == "servo_joint"
    status, text = said(capsys, "explore", setup_file)
    assert status == 0 and "  pwm_choice: " in text and "not on this design: " in text
    status, text = said(capsys, "explore", setup_file, "--json")
    listed = json.loads(text)
    assert len(listed["explorations"]) >= 15


def test_the_terminal_analyses_and_runs_a_scheme(capsys, setup_file) -> None:
    status, text = said(capsys, "loops", setup_file, "--scheme", "foc_torque")
    assert status == 0 and "phase margin" in text and "(stable)" in text
    status, text = said(capsys, "loops", setup_file, "--scheme", "foc_torque", "--json")
    margin = json.loads(text)["current_q"]["margins"]["phase_deg"]
    assert 55.0 < margin < 70.0, "the rule aims at 60°"
    step = ("--scheme", "foc_torque", "--scenario", "torque_step", "--set", "to=3", "--fidelity", "averaged")
    status, text = said(capsys, "run", setup_file, *step)
    assert status == 0 and "foc_torque, torque_step" in text and "to 3" in text and "step on plant.torque: rise" in text
    assert "stability: every pole" in text
    status, text = said(capsys, "run", setup_file, *step, "--mismatch", "flux=0.9", "--json")
    answer = json.loads(text)
    assert answer["scenario"]["to"] == 3 and answer["fidelity"] == "averaged"
    assert any("90 %" in line for line in answer["taken"])
    # What cannot be read is refused in a sentence, with nothing on the error stream.
    status, text = said(capsys, "run", setup_file, "--set", "oops")
    assert status != 0 and "name=value" in text
    status, text = said(capsys, "run", setup_file, "--scheme", "nonesuch", "--json")
    assert status != 0 and json.loads(text)["outcome"] == "refused"


def test_the_terminal_runs_an_exploration_and_a_sweep_of_ones_own(capsys, setup_file) -> None:
    status, text = said(capsys, "sweep", setup_file, "pwm_choice")
    assert status == 0 and "(baseline)" in text and "What it shows:" in text and "switching loss: " in text
    own = ("--vary", "conditions.f_sw", "--values", "10000,20000", "--scheme", "foc_torque")
    status, text = said(capsys, "sweep", setup_file, *own, "--json")
    answer = json.loads(text)
    assert [v["value"] for v in answer["variants"]] == [10000, 20000]
    low, high = (v["losses"]["switching"] for v in answer["variants"])
    assert high == pytest.approx(2 * low, rel=0.05)
    status, text = said(capsys, "sweep", setup_file, "nonesuch")
    assert status != 0 and "no exploration called nonesuch" in text


def test_the_registry_gives_every_kind_a_role_and_says_where_a_schemes_sources_are(offered) -> None:
    from motionsim.control.blocks import ROLES

    _, told = offered
    assert len(ROLES) == 10
    for kind, block in told["blocks"].items():
        if kind.startswith("test_"):
            continue  # a kind another test registers for itself
        assert block["role"] in ROLES, kind
        assert all(p["source"] == "" for p in block["params"]), "the registry is of kinds: a scheme's rules are its own"
    roles = {kind: block["role"] for kind, block in told["blocks"].items()}
    assert roles["speed_pi"] == "outer_regulator" and roles["current_pi_dq"] == "inner_regulator"
    assert roles["clarke"] == "transform_feedback" and roles["inverse_park"] == "transform_forward"
    assert roles["observer_flux"] == "estimation" and roles["thermal_supervisor"] == "supervisor"
    assert roles["current_reference"] == "reference_generator" and roles["modulator"] == "actuation"
    assert roles["current_sampling"] == "sensing" and roles["speed_reference"] == "reference"
    servo = next(s for s in told["schemes"] if s["id"] == "foc_servo")
    assert any(b["sources"] for b in servo["blocks"])


def test_a_tests_figures_come_with_their_unit_default_bounds_and_choices(offered) -> None:
    _, told = offered
    by_kind = {s["kind"]: s for s in told["scenarios"]}
    for kind, test in by_kind.items():
        for f in test["fields"]:
            assert set(f) == {"name", "unit", "about", "default", "low", "high", "choices"}, (kind, f["name"])
            assert f["default"] == test["defaults"][told["chosen"]][f["name"]]
            if f["choices"]:
                assert f["default"] in f["choices"] and f["low"] is None and f["high"] is None
            else:
                assert f["low"] <= f["default"] <= f["high"], (kind, f["name"])
    shape = next(f for f in by_kind["start"]["fields"] if f["name"] == "shape")
    assert shape["choices"] == ["hard", "slew", "s-curve"]
    duration = next(f for f in by_kind["torque_step"]["fields"] if f["name"] == "duration")
    assert (duration["unit"], duration["high"]) == ("s", 5.0)


def test_a_regulators_parts_add_up_to_what_it_asks_and_a_limit_shows_on_its_wire(ws) -> None:
    base = started("example-mosfet", ws)
    step = {"kind": "torque_step", "from": 0.5, "to": 2.0, "duration": 0.006}
    answer = posted("/api/control/run", {**base, "scheme": "foc_torque", "scenario": step, "points": 5000}, ws)
    w = answer["series"]["wires"]
    for axis in "dq":
        parts = zip(w[f"current.prop_{axis}"], w[f"current.int_{axis}"], w[f"current.ff_{axis}"], strict=True)
        whole, limited = w[f"current.v_{axis}"], w["current.limited"]
        free = [n for n, flag in enumerate(limited) if flag == 0.0]
        assert len(free) > 50
        summed = [sum(p) for p in parts]
        assert all(summed[n] == pytest.approx(whole[n], abs=1e-9) for n in free)
    # Held at the design point, the q axis is fed forward the back-EMF and the d-axis coupling,
    # ω·(ψ + Ld·id): all of the settled voltage but the drop across the resistance.
    held = posted("/api/control/run", {**base, "scheme": "foc_torque"}, ws)
    settled = held["settled"]
    by_hand = settled["v_q"] - base["motor"]["rs"] * settled["i_q"]
    fed = held["series"]["wires"]["current.ff_q"]
    assert sum(fed) / len(fed) == pytest.approx(by_hand, rel=0.01)
    names = {x["name"] for x in answer["wires"]}
    assert {"shaper.limited", "current_ref.limited", "modulator.limited", "current.limited"} <= names
    assert set(w["shaper.limited"]) == {0.0}
    # With the shaper's limit set under the torque asked for, it holds it and says so; the
    # speed regulator of a start sits on its limit and says so too.
    offered = posted("/api/control/presets", base, ws)
    scheme = next(x for x in offered["schemes"] if x["id"] == "foc_torque")
    next(b for b in scheme["blocks"] if b["name"] == "shaper")["params"]["limit"] = 1.0
    answer = posted("/api/control/run", {**base, "scheme": scheme, "scenario": step, "fidelity": "averaged"}, ws)
    held = answer["series"]["wires"]["shaper.limited"]
    assert held[0] == 0.0 and held[-1] == 1.0
    assert answer["series"]["wires"]["shaper.torque"][-1] == 1.0
    start = {"kind": "start", "duration": 0.02}
    answer = posted("/api/control/run", {**base, "scheme": "foc_servo", "scenario": start, "fidelity": "averaged"}, ws)
    w = answer["series"]["wires"]
    assert w["speed.limited"][5] == 1.0
    assert {"speed.prop", "speed.int"} <= set(w)


def test_the_predictive_controller_shows_every_states_cost_and_takes_the_least(ws) -> None:
    base = started("example-mosfet", ws)
    answer = posted("/api/control/run", {**base, "scheme": "mpc_torque", "points": 5000}, ws)
    w = answer["series"]["wires"]
    costs = [w[f"predictive.cost_{s}"] for s in range(8)]
    chosen, least = w["predictive.chosen"], w["predictive.cost"]
    assert len(chosen) > 100 and {int(c) for c in chosen} <= set(range(8)) and len(set(chosen)) > 3
    for n, state in enumerate(chosen):
        at = [c[n] for c in costs]
        assert at[int(state)] == pytest.approx(min(at), abs=1e-9) and least[n] == pytest.approx(min(at), abs=1e-9)
        assert (w["predictive.s_a"][n], w["predictive.s_b"][n], w["predictive.s_c"][n]) == (
            float(int(state) & 1),
            float((int(state) >> 1) & 1),
            float((int(state) >> 2) & 1),
        )


def test_the_loops_come_as_latex_too_and_a_streamed_run_carries_the_controllers_wires(ws) -> None:
    from motionsim.service.routes import STREAMS

    base = started("example-mosfet", ws)
    loops = posted("/api/control/loops", {**base, "scheme": "foc_servo"}, ws)
    for key in ("current_d", "current_q", "speed"):
        words, latex = loops[key]["transfer"], loops[key]["transfer_latex"]
        assert len(latex) == len(words) + 2
        assert latex[0].startswith("C(z) = K_p") and "\\frac" in latex[1]
        assert latex[-2].startswith("L(z) = \\frac{") and latex[-1].startswith("T(z) = \\frac{")
        assert all(x.count("{") == x.count("}") for x in latex)
    # The closed loop's leading coefficient is one: its denominator begins with the bare power.
    order = len(loops["current_q"]["closed"]["den"]) - 1
    assert f"}}{{z^{{{order}}} " in loops["current_q"]["transfer_latex"][-1]
    probes = [s for s in STREAMS["/api/control/run"]({**base, "scheme": "foc_servo"}, ws) if "series" in s]
    assert probes
    wires = set(probes[-1]["series"]["wires"])
    scheme = loops["scheme"]
    assert {"plant.i_q", "cmd.speed"} <= wires
    first = {"speed": "torque", "current": "v_d", "modulator": "d_a", "park": "d", "position": "theta"}
    assert {b["name"] for b in scheme["blocks"]} >= set(first)
    assert {f"{name}.{output}" for name, output in first.items()} <= wires
    assert len([x for x in wires if not x.startswith(("plant.", "cmd."))]) == len(scheme["blocks"])


def test_a_refusal_names_a_scheme_by_its_label_with_its_id_in_parentheses(ws) -> None:
    from motionsim.service.routes import dispatch

    base = started("example-mosfet", ws)
    status, body = dispatch("/api/control/run", {**base, "scheme": "foc_servo", "scenario": {"kind": "stall"}}, ws)
    assert status == 422
    assert "Cascaded speed and current control (servo) (foc_servo)" in body["refused"]
    assert "Torque control with least current and field weakening (traction) (foc_torque)" in body["fix"]
    status, body = dispatch("/api/control/run", {**base, "scheme": "nonesuch"}, ws)
    assert status == 422 and body["field"] == "scheme"
    assert "Deadbeat predictive torque control (with a modulator) (deadbeat_torque)" in body["fix"]
    vary = {"label": "x", "unit": "", "path": "scheme.blocks.nonesuch.kp", "values": [1, 2]}
    status, body = dispatch("/api/control/sweep", {**base, "scheme": "foc_torque", "vary": vary}, ws)
    # A sweep keeps a variant that cannot be run: each says why, by the same name.
    assert status == 200 and len(body["variants"]) == 2
    for v in body["variants"]:
        assert v["refused"]["refused"].startswith(
            "the scheme Torque control with least current and field weakening (traction) (foc_torque) has no block"
        )
