"""A phrased verdict is held to the findings' own figures: each number with its unit and its
sign, no number written as a word or a fraction, nothing glued to a letter, and a label such as
fs/20 never taken for a figure. A phrasing kept from before is held to the same, and the store's
phrasings cannot be written from outside. Every model here is a fake."""

from __future__ import annotations

import pytest

from motionsim.control import verdict, verdict_phrase

FINDINGS = [
    {
        "id": "current_margin",
        "topic": "current loop",
        "tag": "good",
        "severity": 0,
        "said": "current loop: phase margin 62.7°, gain margin 9.98 dB, crossover 1.01 kHz (fs/20)",
        "lever": None,
        "expect": None,
        "change": None,
    },
    {
        "id": "loss_split",
        "topic": "losses",
        "tag": "good",
        "severity": 0,
        "said": "device loss 21.6 W: 77.1% conduction, 22.9% switching (0.25 W per kHz of switching frequency)",
        "lever": None,
        "expect": None,
        "change": None,
    },
    {
        "id": "junction",
        "topic": "thermal",
        "tag": "good",
        "severity": 0,
        "said": "junction peaks at 65.6 °C, 109 K below its 175 °C rating, swinging 3.1 K",
        "lever": None,
        "expect": None,
        "change": None,
    },
    {
        "id": "carrier",
        "topic": "timing",
        "tag": "good",
        "severity": 0,
        "said": "carrier ratio 57.1 switching periods a turn",
        "lever": None,
        "expect": None,
        "change": None,
    },
]
VERDICT = {"findings": FINDINGS, "key": "k" * 40}
FACTS = verdict_phrase.payload(VERDICT)


@pytest.mark.parametrize(
    "said",
    [
        "Phase margin 9.98° and gain margin 62.7 dB.",  # the units swapped between two figures
        "The loop is fine; raise Kp x10 for more.",  # a figure glued to a letter
        "Raise Kp x3 and Ki x5.",
        "Switching loss would fall by a third, or by half, or tenfold.",  # numbers as words
        "Margin is sixty-three degrees and the THD is ½ %.",
        "The junction swings -3.1 K and the loss is −21.6 W.",  # the sign ignored
        "The device loses 20 W and the junction peaks at 175 °C.",  # 20 only inside fs/20
        "The loop crosses over at fs/10.",  # a label no finding carries
        "THD is 57.1% at a carrier ratio of 2.4.",  # a number moved to another unit
        "Margin is 6.27e1 degrees.",  # an exponent
        "Margin 62.7°, i.e. fs/2e1.",
        "Crossover is 1013 Hz.",  # converted
        "Phase margin is 62.7 and the loss 21.6 W.",  # a unit dropped
        "Loss falls by 1/3 of 21.6 W.",  # a fraction
        "The phase margin of 62.7° is double what it needs.",
    ],
)
def test_a_phrasing_that_moves_a_figure_or_writes_one_otherwise_is_set_aside(said) -> None:
    assert verdict_phrase.holds(said, FACTS) is not None, said


@pytest.mark.parametrize(
    "said",
    [
        "The current loop holds 62.7° of phase margin and 9.98 dB of gain margin, crossing over at 1.01 kHz.",
        "The device loses 21.6 W, 22.9% of it in switching, and the junction peaks at 65.6 °C, 109 K under its "
        "175 °C rating.",
        "The carrier ratio is 57.1 switching periods a turn, and the junction swings 3.1 K.",
        "Phase margin 62.7 degrees, junction at 65.6°C.",
    ],
)
def test_a_phrasing_that_keeps_each_figure_with_its_unit_is_taken(said) -> None:
    assert verdict_phrase.holds(said, FACTS) is None, said


def test_a_sign_and_a_word_are_taken_where_the_findings_carry_them() -> None:
    facts = [
        {"tag": "improve", "fact": "against as tuned: junction peak −3.1 K, worse on balance"},
        {"tag": "improve", "fact": "loss 10 W", "expect": "a third fewer commutations"},
    ]
    assert verdict_phrase.holds("The junction peak moved −3.1 K; a third fewer commutations help.", facts) is None
    assert verdict_phrase.holds("The junction peak moved 3.1 K.", facts) is not None
    assert verdict_phrase.holds("Half the commutations go.", facts) is not None
    times = [{"tag": "improve", "fact": "against as tuned (current.kp_q ×3): phase margin 62.7°→40°"}]
    assert verdict_phrase.holds("The edit, current.kp_q ×3, took the margin from 62.7° to 40°.", times) is None
    assert verdict_phrase.holds("The edit, current.kp_q x3, took the margin to 40°.", times) is not None
    # A figure the findings write with an exponent is taken as written, and only so.
    tiny = [{"tag": "good", "fact": "torque step: 3.5e-05% overshoot, settles in 1 ms"}]
    assert verdict_phrase.holds("The torque step overshoots 3.5e-05% and settles in 1 ms.", tiny) is None
    assert verdict_phrase.holds("The torque step overshoots 0.000035% and settles in 1 ms.", tiny) is not None


def test_a_phrasing_kept_before_is_checked_again_when_read() -> None:
    planted = {VERDICT["key"]: {"summary": "Everything fails: 999 W of loss, retune all gains.", "model": "claude"}}
    calls = []

    def model(system: str, text: str):
        calls.append(1)
        return "The device loses 21.6 W.", "fake"

    got = verdict_phrase.phrased(VERDICT, planted.get, planted.__setitem__, model)
    assert got["summary"] == "The device loses 21.6 W." and got["cached"] is False and calls == [1]
    assert planted[VERDICT["key"]]["summary"] == "The device loses 21.6 W."
    again = verdict_phrase.phrased(VERDICT, planted.get, planted.__setitem__, model)
    assert again["cached"] is True and calls == [1]


def test_the_template_summary_always_holds() -> None:
    for summary_of in (verdict.summary(FINDINGS),):
        assert verdict_phrase.holds(summary_of, FACTS) is None, summary_of


def test_the_store_s_phrasings_cannot_be_written_from_the_page(tmp_path, monkeypatch) -> None:
    pytest.importorskip("fastapi", reason="the ASGI app needs the app extra")
    from test_app_http import served

    from motionsim.app import home
    from motionsim.observe import provider

    monkeypatch.setenv(home.HOME, str(tmp_path / "home"))
    monkeypatch.setattr(provider, "available", lambda env=None: True)
    monkeypatch.setattr(verdict_phrase, "ask_model", lambda s, t: ("unused", "fake"))
    with served(tmp_path / "asgi") as app:
        status, _ = app.json("PUT", f"/api/store/{verdict_phrase.KIND}/{'a' * 40}", {"summary": "999 W", "model": "x"})
        assert status == 403
        assert app.json("DELETE", f"/api/store/{verdict_phrase.KIND}/{'a' * 40}")[0] == 403
        assert app.json("GET", f"/api/store/{verdict_phrase.KIND}")[0] == 200
        # Other kinds are still kept from the page.
        assert app.json("PUT", "/api/store/control-run/one", {"a": 1})[0] == 200
