"""The so-what of a run: the findings a run's figures give, each with its number, its lever and
the way it moves; what an edit changed against the scheme as tuned; the summary in words;
and the phrasing by a language model, held to the findings' own numbers. No model is ever
called here: every model is a fake."""

from __future__ import annotations

import copy
import types

import pytest
from test_control_bench import posted, started, workspace

from motionsim.control import verdict, verdict_phrase
from motionsim.observe import provider
from motionsim.service.routes import dispatch

KEY = "example-mosfet"


@pytest.fixture(scope="module")
def ws():
    return workspace()


@pytest.fixture(scope="module")
def base(ws) -> dict:
    return started(KEY, ws)


@pytest.fixture(scope="module")
def held(ws, base) -> dict:
    return posted("/api/control/run", {**base, "scenario": {"kind": "hold"}}, ws)


@pytest.fixture(scope="module")
def edited(ws, base) -> dict:
    offered = posted("/api/control/presets", base, ws)
    scheme = copy.deepcopy(next(s for s in offered["schemes"] if s["id"] == "foc_servo"))
    current = next(b for b in scheme["blocks"] if b["name"] == "current")
    current["params"]["kp_q"] *= 3.0
    return posted("/api/control/run", {**base, "scheme": scheme, "scenario": {"kind": "hold"}}, ws)


def by_id(v: dict, ident: str) -> dict:
    return next(f for f in v["findings"] if f["id"] == ident)


def test_a_run_comes_with_its_figures_and_its_verdict(held, ws, base) -> None:
    q, v = held["quality"], held["verdict"]
    loops = posted("/api/control/loops", base, ws)
    # The margins judged are the linear view's own, and the loss split the run's.
    assert q["loops"]["current"]["phase_deg"] == pytest.approx(loops["current_q"]["margins"]["phase_deg"])
    assert q["loops"]["speed"]["crossover_hz"] == pytest.approx(loops["speed"]["margins"]["crossover_hz"])
    assert q["loss"]["switching"] == pytest.approx(held["losses"]["switching"])
    assert q["tuned"] == {"id": "servo_joint", "edits": [], "loops": None}
    # The scheme as tuned is good on every count for this design: nothing to improve.
    assert [f["tag"] for f in v["findings"]] and all(f["tag"] == "good" for f in v["findings"])
    margin = by_id(v, "current_margin")
    assert "62.7°" in margin["said"] and "fs/20" in margin["said"]
    assert v["summary"].startswith("Good: the current loop keeps 62.7° of phase margin, crossing over at fs/20.")
    assert v["summary"].endswith("Nothing here asks for a change.")
    assert not v["edited"] and v["against"] is None and len(v["key"]) == 40


def test_an_edit_is_said_against_the_scheme_as_tuned_with_its_lever(edited, held, ws) -> None:
    q, v = edited["quality"], edited["verdict"]
    assert q["tuned"]["edits"] == [
        {
            "block": "current",
            "param": "kp_q",
            "tuned": pytest.approx(q["tuned"]["edits"][0]["now"] / 3),
            "now": q["tuned"]["edits"][0]["now"],
            "words": "Kp,q of the current regulator",
        }
    ]
    assert v["edited"] and v["against"] == "tuned"
    lead = v["findings"][0]
    assert lead["id"] == "edit" and lead["tag"] == "improve" and "Kp,q of the current regulator ×3" in lead["said"]
    assert "62.7°→" in lead["said"] and lead["lever"] == {"kind": "tuned"}
    margin = by_id(v, "current_margin")
    # Three times the gain leaves a few degrees of margin: the worst there is, with its lever.
    assert margin["tag"] == "improve" and margin["severity"] == 3
    assert margin["lever"] == {"kind": "block", "block": "current", "param": "kp_q", "direction": "lower", "to": None}
    assert margin["change"]["against"] == "tuned" and margin["change"]["better"] is False
    assert margin["change"]["was"] == pytest.approx(held["quality"]["loops"]["current"]["phase_deg"])
    # A margin that low needs a change, and the summary says the edit brought it.
    assert v["summary"].startswith("Needs a change: the current loop has 6.02° of phase margin; a lower Kp,q")
    assert (
        "It came with the edit (Kp,q of the current regulator ×3): going back to the scheme as tuned undoes it. "
        "Against as tuned, current-loop phase margin 62.7°→6.02°." in v["summary"]
    )


def test_the_verdict_address_sets_a_run_beside_the_run_before(edited, held, ws) -> None:
    v = posted("/api/control/verdict", {"quality": held["quality"], "before": edited["quality"]}, ws)
    # The tuned scheme after the edit: its margin is better than the run before's.
    margin = by_id(v, "current_margin")
    assert margin["tag"] == "good" and margin["change"]["against"] == "before" and margin["change"]["better"] is True
    assert v["against"] == "before"
    assert posted("/api/control/verdict", {"quality": held["quality"]}, ws) == held["verdict"]


@pytest.mark.parametrize(
    "body, field",
    [
        ({}, "quality"),
        ({"quality": "high"}, "quality"),
        ({"quality": {}, "before": 3}, "before"),
        ({"quality": {"blocks": "x", "loops": {"current": 1}}}, "quality"),
    ],
)
def test_figures_that_are_not_a_run_s_are_refused_by_name(ws, body, field) -> None:
    status, answer = dispatch("/api/control/verdict", body, ws)
    assert status == 422 and answer["field"] == field


# Figures made up to sit on either side of each threshold.
def quality(**changes) -> dict:
    q = {
        "scheme": {"id": "foc_servo", "update": "single", "pwm": "space-vector"},
        "test": "hold",
        "f_control": 20000.0,
        "f_sw": 20000.0,
        "carrier_ratio": 60.0,
        "loops": {
            "current": {"phase_deg": 60.0, "gain_db": 10.0, "crossover_hz": 1000.0},
            "speed": {"phase_deg": 60.0, "crossover_hz": 100.0},
        },
        "loss": {"total": 10.0, "conduction": 7.0, "switching": 3.0},
        "tj": {"peak": 80.0, "max": 175.0, "swing": 5.0},
        "ripple": {"thd": 0.02, "pp": 1.0, "fundamental": 10.0, "torque_pp": 0.02, "torque_mean": 1.0},
        "step": None,
        "limited": [],
        "anti_windup": {"speed": True},
        "checks": [],
        "stability": {"linear_stable": True},
        "blocks": [
            {"name": "speed_ref", "kind": "speed_reference", "loop": "", "params": {"shape": "step"}},
            {"name": "speed", "kind": "speed_pi", "loop": "speed", "params": {"kp": 1.0, "ki": 1.0, "limit": 5.0}},
            {"name": "current", "kind": "current_pi_dq", "loop": "current", "params": {"kp_q": 1.0, "ki_q": 1.0}},
            {"name": "modulator", "kind": "modulator", "loop": "", "params": {"pwm": "space-vector"}},
        ],
    }
    for path, value in changes.items():
        *head, last = path.split("__")
        at = q
        for k in head:
            at = at[k]
        at[last] = value
    return q


def test_each_threshold_turns_a_finding_with_the_lever_that_moves_it() -> None:
    good = verdict.judge(quality())
    assert all(f["tag"] == "good" for f in good["findings"])
    cases = [
        (
            "loops__current__phase_deg",
            40.0,
            "current_margin",
            {"block": "current", "param": "kp_q", "direction": "lower"},
        ),
        ("loops__current__crossover_hz", 3000.0, "current_fast", {"param": "kp_q", "direction": "lower"}),
        ("loops__current__crossover_hz", 300.0, "current_slow", {"param": "kp_q", "direction": "raise"}),
        ("loops__speed__crossover_hz", 400.0, "speed_separation", {"block": "speed", "param": "kp"}),
        ("loops__speed__phase_deg", 35.0, "speed_margin", {"param": "ki", "direction": "lower"}),
        ("loss__switching", 7.0, "loss_split", {"block": "modulator", "param": "pwm", "to": "discontinuous"}),
        # A speed scheme: active thermal control is a torque scheme, and not offered for it.
        ("tj__peak", 160.0, "junction", {"kind": "design", "param": "f_sw"}),
        ("tj__swing", 50.0, "swing", {"kind": "design", "param": "f_sw"}),
        ("ripple__thd", 0.08, "thd", {"kind": "design", "param": "f_sw"}),
        ("carrier_ratio", 20.0, "carrier", {"kind": "scheme", "to": "foc_high_speed"}),
        ("carrier_ratio", 8.0, "carrier", {"kind": "scheme", "to": "discrete_high_speed"}),
    ]
    for path, value, ident, lever in cases:
        v = verdict.judge(quality(**{path: value}))
        found = by_id(v, ident)
        assert found["tag"] == "improve", (path, value)
        assert lever.items() <= found["lever"].items(), (path, found["lever"])
        assert found["expect"], ident
        # What is to improve comes before what is good.
        assert v["findings"][0]["tag"] == "improve"


def test_a_step_is_judged_by_its_overshoot_its_settling_and_its_error() -> None:
    step = {
        "kind": "step",
        "wire": "plant.omega_m",
        "from": 100.0,
        "to": 200.0,
        "rise_time": 0.003,
        "overshoot": 0.25,
        "settling_time": 0.02,
        "steady_state_error": 5.0,
    }
    v = verdict.judge(quality(test="speed_step", ripple=None, step=step))
    over = by_id(v, "overshoot")
    assert over["tag"] == "improve" and over["severity"] == 2 and "25 % overshoot" in over["said"]
    # A lower Ki, not an S-curve: on a regulator tuned by the symmetric optimum an S-curve was
    # seen to add overshoot (tests/test_control_verdict_truth.py).
    assert over["lever"] == {"kind": "block", "block": "speed", "param": "ki", "direction": "lower", "to": None}
    assert by_id(v, "step_error")["lever"]["param"] == "ki"
    calm = verdict.judge(
        quality(test="speed_step", ripple=None, step={**step, "overshoot": 0.04, "steady_state_error": 0.1})
    )
    assert by_id(calm, "overshoot")["tag"] == "good" and "step_error" not in [f["id"] for f in calm["findings"]]


def test_a_limit_held_and_a_failed_check_are_findings_with_their_figure() -> None:
    v = verdict.judge(
        quality(
            limited=[{"block": "speed", "kind": "speed_pi", "share": 0.3}],
            checks=[
                {
                    "level": "fail",
                    "topic": "temperature",
                    "message": "junction over its rating",
                    "field": "scheme.blocks.current.kp_q",
                }
            ],
        )
    )
    assert by_id(v, "check_temperature")["severity"] == 3
    assert by_id(v, "check_temperature")["lever"]["block"] == "current"
    held = by_id(v, "limited_speed")
    assert held["tag"] == "improve" and "30 %" in held["said"] and held["lever"]["param"] == "limit"
    # In a step test a limit held for a while with anti-windup on is the drive doing its work.
    step = verdict.judge(
        quality(test="speed_step", ripple=None, limited=[{"block": "speed", "kind": "speed_pi", "share": 0.3}])
    )
    assert by_id(step, "limited_speed")["tag"] == "good"


def test_the_summary_is_two_sentences_from_the_findings_alone() -> None:
    v = verdict.judge(quality(**{"loss__switching": 7.0, "loss__conduction": 3.0}))
    assert v["summary"].startswith("Good: the current loop keeps 60° of phase margin, crossing over at fs/20.")
    assert "To improve: the devices lose 10 W, 70 % of it in switching; a discontinuous modulation" in v["summary"]
    assert verdict_phrase.sentences(v["summary"]) == 2
    facts = verdict_phrase.payload(v)
    assert verdict_phrase.holds(v["summary"], facts) is None


# The phrasing, with a fake model.


@pytest.fixture
def judged() -> dict:
    return verdict.judge(quality(**{"loss__switching": 7.0, "loss__conduction": 3.0}))


def test_a_phrasing_that_cites_the_findings_numbers_is_taken(judged) -> None:
    asked = []

    def model(system: str, text: str) -> tuple[str, str]:
        asked.append((system, text))
        return (
            "The current loop holds 60° of phase margin. Switching is 70 % of the 10 W device loss: try a discontinuous modulation.",
            "fake",
        )

    got = verdict_phrase.phrase(judged, model)
    assert got == {
        "summary": "The current loop holds 60° of phase margin. Switching is 70 % of the 10 W device loss: try a "
        "discontinuous modulation.",
        "model": "fake",
        "why": None,
    }
    system, text = asked[0]
    assert "only the facts" in system and "device loss 10 W" in text


@pytest.mark.parametrize(
    "said, why",
    [
        ("The current loop holds 61° of phase margin.", "61"),
        ("One. Two. Three.", "two sentences"),
        ("", "no sentence"),
        ("x" * 600, "more than a summary"),
    ],
)
def test_a_phrasing_that_strays_from_the_findings_is_set_aside(judged, said, why) -> None:
    got = verdict_phrase.phrase(judged, lambda s, t: (said, "fake"))
    assert got["summary"] is None and why in got["why"]


def test_a_model_that_fails_is_a_reason_and_never_the_key(judged, monkeypatch) -> None:
    secret = "sk-test-0123456789abcdef"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)

    def model(system: str, text: str):
        raise provider.ReaderFailed(f"rejected key {secret}")

    got = verdict_phrase.phrase(judged, model)
    assert got["summary"] is None and secret not in got["why"] and "[key]" in got["why"]
    monkeypatch.setattr(provider, "available", lambda env=None: False)
    assert verdict_phrase.phrase(judged)["why"] == "no language model is set up"


def test_a_phrasing_is_kept_by_the_verdict_s_key_and_asked_once(judged) -> None:
    kept: dict = {}
    calls = []

    def model(system: str, text: str):
        calls.append(1)
        return "The current loop holds 60° of phase margin.", "fake"

    first = verdict_phrase.phrased(judged, kept.get, kept.__setitem__, model)
    again = verdict_phrase.phrased(judged, kept.get, kept.__setitem__, model)
    assert first["cached"] is False and again["cached"] is True and len(calls) == 1
    assert again["summary"] == first["summary"] and set(kept) == {judged["key"]}


def test_anthropic_is_asked_with_its_small_model_and_a_short_answer(judged, monkeypatch) -> None:
    made: dict = {}

    class Messages:
        def create(self, **asked):
            made.update(asked)
            text = types.SimpleNamespace(type="text", text="The current loop holds 60° of phase margin.")
            return types.SimpleNamespace(stop_reason="end_turn", content=[text])

    class Anthropic:
        def __init__(self, **kwargs):
            made["client"] = kwargs
            self.messages = Messages()

    monkeypatch.setattr(provider, "chosen", lambda env=None: provider.Reader("anthropic", provider.ANTHROPIC_MODEL))
    monkeypatch.setattr(provider, "available", lambda env=None: True)
    monkeypatch.setattr(provider, "needs", lambda module, what: types.SimpleNamespace(Anthropic=Anthropic))
    got = verdict_phrase.phrase(judged)
    assert got["summary"] and got["model"] == "claude-haiku-5-5"
    assert made["model"] == "claude-haiku-5-5" and made["max_tokens"] == verdict_phrase.MAX_TOKENS
    assert made["system"] == verdict_phrase.SYSTEM and made["client"]["timeout"] == verdict_phrase.TIMEOUT


def test_another_maker_is_asked_through_chat_completions_with_a_short_answer(judged, monkeypatch) -> None:
    sent: dict = {}
    reader = provider.Reader("chat", "small-model", "https://api.example.com/v1", "sk-other-0123456789")

    def post(r, body):
        sent.update(body)
        return {"choices": [{"message": {"content": "Switching is 70 % of the 10 W device loss."}}]}

    monkeypatch.setattr(provider, "chosen", lambda env=None: reader)
    monkeypatch.setattr(provider, "available", lambda env=None: True)
    monkeypatch.setattr(provider, "_post", post)
    got = verdict_phrase.phrase(judged)
    assert got["summary"] == "Switching is 70 % of the 10 W device loss." and got["model"] == "small-model"
    assert sent["max_tokens"] == verdict_phrase.MAX_TOKENS and "sk-other" not in str(sent)


def test_the_app_phrases_a_verdict_once_and_keeps_it(tmp_path, monkeypatch, held) -> None:
    pytest.importorskip("fastapi", reason="the ASGI app needs the app extra")
    from test_app_http import served

    from motionsim.app import home

    monkeypatch.setenv(home.HOME, str(tmp_path / "home"))
    calls = []

    def model(system: str, text: str):
        calls.append(text)
        return "The current loop holds 62.7° of phase margin.", "fake"

    monkeypatch.setattr(provider, "available", lambda env=None: True)
    monkeypatch.setattr(verdict_phrase, "ask_model", model)
    with served(tmp_path / "asgi") as app:
        body = {"quality": held["quality"]}
        status, first = app.json("POST", "/api/control/phrase", body)
        assert status == 200 and first["summary"] == "The current loop holds 62.7° of phase margin."
        assert first["key"] == held["verdict"]["key"] and first["cached"] is False
        assert app.json("POST", "/api/control/phrase", body)[1]["cached"] is True and len(calls) == 1
        assert app.json("POST", "/api/control/phrase", {})[0] == 422
        # Only this page may spend the key.
        other = {"Origin": "http://elsewhere.example", "Sec-Fetch-Site": "cross-site"}
        assert app.json("POST", "/api/control/phrase", body, other)[0] == 403


def test_a_motor_barely_salient_is_not_taken_for_one_with_buried_magnets() -> None:
    from dataclasses import replace

    from test_control_bench import design

    from motionsim.control.presets import SALIENT, chosen

    surface = design()
    assert chosen(surface)[0] == "foc_servo"
    # Two percent of saturation saliency is not a buried magnet: the default stays the cascade.
    assert chosen(replace(surface, lq=surface.ld * 1.02))[0] == "foc_servo"
    assert chosen(replace(surface, lq=surface.ld * SALIENT * 1.01))[0] == "foc_torque"


def test_no_sentence_of_an_edit_names_a_block_or_a_kind_by_its_code() -> None:
    from test_control_bench import design

    from motionsim.control.presets import foc_servo
    from motionsim.control.scheme import scheme_from
    from motionsim.control.verdict import _edit_said
    from motionsim.service.control.judging import edits

    tuned = foc_servo(design())
    data = tuned.data()
    speed = next(b for b in data["blocks"] if b["kind"] == "speed_pi")
    speed["params"]["kp"] = 2.0 * speed["params"]["kp"]
    current = next(b for b in data["blocks"] if b["kind"] == "current_pi_dq")
    current["kind"], current["params"] = "deadbeat_dq", {}
    said = [_edit_said(e) for e in edits(tuned, scheme_from(data))]
    assert "Kp of the speed regulator ×2" in said
    assert any("current regulator (pi, rotor frame)→deadbeat predictive current control" in s.lower() for s in said)
    assert not any("_" in s or "speed.kp" in s for s in said)


def test_a_speed_loop_faster_than_the_current_loop_is_said_to_be_above_it() -> None:
    from motionsim.control.verdict import _speed_loop

    q = {"loops": {"speed": {"phase_deg": -72.4, "crossover_hz": 4890.0}, "current": {"crossover_hz": 2000.0}}}
    (found,) = _speed_loop(q)
    assert "2.4 times above the current loop" in found["said"] and "below" not in found["said"]
    assert found["head"] == "the speed loop crosses over 2.4 times above the current loop"
    q["loops"]["speed"]["crossover_hz"] = 500.0
    (found,) = _speed_loop(q)
    assert "4 times below the current loop" in found["said"]


def test_a_motor_the_lab_does_not_simulate_is_named_in_words(monkeypatch) -> None:
    from types import SimpleNamespace

    from motionsim.errors import Refusal
    from motionsim.service.control import design as lab_design

    monkeypatch.setattr(lab_design, "_motor", lambda data: SimpleNamespace(type=data["type"]))
    for kind in ("induction", "bldc", "dc", "stepper"):
        with pytest.raises(Refusal) as refused:
            lab_design._pmsm({"motor": {"type": kind}})
        said = f"{refused.value.reason} {refused.value.fix}"
        assert lab_design.OTHER_MOTORS[kind] in said
        assert "pmsm" not in said and "of the kind" not in said


def test_a_ripple_that_is_only_the_arithmetic_is_not_written_as_a_figure() -> None:
    from motionsim.control.verdict import _ripple

    (found,) = _ripple({"ripple": {"thd": 1e-9, "pp": 1.81e-8, "fundamental": 44.8}})
    assert "e-0" not in found["said"] and "peak to peak" not in found["said"]
    (real,) = _ripple({"ripple": {"thd": 0.024, "pp": 4.96, "fundamental": 44.8}})
    assert "ripple 4.96 A peak to peak" in real["said"]
