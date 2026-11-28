"""The page's chat (motionsim.app.chat), against a scripted stand-in for the model service: no
request leaves the machine. What it is held to: which models answer, what is cached, what each
model may touch, that every change goes through the session's checks and is logged as the
chat's, and that it declines with a reason where it cannot answer."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp", reason="the chat uses the agent's tools, in the app extra")

from motionsim.app import chat as chat_mod
from motionsim.app.agent import Bench
from motionsim.app.chat import ANSWER_MODEL, DESIGN_MODEL, HAND_OVER, Chat, ChatUnavailable
from motionsim.app.session import Session
from motionsim.app.store import Store
from motionsim.service.workspace import Workspace


@dataclass
class Block:
    type: str
    text: str = ""
    id: str = ""
    name: str = ""
    input: dict = field(default_factory=dict)


@dataclass
class Usage:
    input_tokens: int = 100
    output_tokens: int = 20
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class Reply:
    content: list
    stop_reason: str = "end_turn"
    usage: Usage = field(default_factory=Usage)


def said(text: str) -> Reply:
    return Reply([Block("text", text=text)])


def calls(*uses: tuple[str, dict], text: str = "") -> Reply:
    blocks = [Block("text", text=text)] if text else []
    blocks += [Block("tool_use", id=f"t{k}", name=n, input=i) for k, (n, i) in enumerate(uses)]
    return Reply(blocks, "tool_use")


class Service:
    """Answers each call with the next reply scripted for its model; keeps what it was asked."""

    def __init__(self, script: dict[str, list[Reply]]) -> None:
        self.script = {m: list(r) for m, r in script.items()}
        self.asked: list[dict] = []
        self.messages = self

    def create(self, **asked: Any) -> Reply:
        self.asked.append(asked)
        return self.script[asked["model"]].pop(0)


@pytest.fixture
def bench(tmp_path: Path) -> Bench:
    store = Store(tmp_path / "kept.db")
    b = Bench(Workspace(tmp_path / "devices"), store, Session(store))
    b.source = "chat"
    b.choose_part(b.list_parts()["parts"][0]["id"])
    return b


def talking(bench: Bench, script: dict[str, list[Reply]]) -> tuple[Chat, Service]:
    service = Service(script)
    return Chat(bench, client=lambda: service), service


def test_a_question_is_answered_by_haiku_alone_with_the_fixed_text_cached_and_only_tools_that_read(bench) -> None:
    chat, service = talking(bench, {ANSWER_MODEL: [calls(("get_session", {})), said("Your link is 48 V.")]})
    answer = chat.ask("What DC link voltage does my design use?")
    assert answer["reply"] == "Your link is 48 V." and answer["model"] == ANSWER_MODEL
    assert [a["model"] for a in service.asked] == [ANSWER_MODEL, ANSWER_MODEL]
    first = service.asked[0]
    assert first["system"][-1]["cache_control"] == {"type": "ephemeral"}
    names = {t["name"] for t in first["tools"]}
    assert HAND_OVER in names and "get_session" in names
    assert not names & {"set_design", "choose_part", "set_scheme", "set_param", "run_test", "undo"}
    # The tool's answer went back to it, from the session itself.
    result = service.asked[1]["messages"][-1]["content"][0]
    assert result["type"] == "tool_result" and not result["is_error"] and '"design"' in result["content"]
    # The same fixed text and tools lead every call, so the cache holds across them.
    assert service.asked[1]["system"] == first["system"] and service.asked[1]["tools"] == first["tools"]


def test_a_request_to_change_the_design_goes_to_sonnet_which_writes_through_the_session_as_the_chat(bench) -> None:
    script = {
        ANSWER_MODEL: [calls((HAND_OVER, {"request": "switch at 16 kHz"}))],
        DESIGN_MODEL: [calls(("set_design", {"fields": {"f_khz": 16}})), said("It now switches at 16 kHz.")],
    }
    chat, service = talking(bench, script)
    answer = chat.ask("Switch at 16 kHz")
    assert answer["model"] == DESIGN_MODEL and answer["reply"] == "It now switches at 16 kHz."
    assert len(answer["changes"]) == 1
    entry = bench.session.entry(answer["changes"][0])
    assert entry["source"] == "chat"
    assert bench.session.current()["doc"]["design"]["conditions"]["f_khz"] == 16
    designer = service.asked[1]
    assert "set_design" in {t["name"] for t in designer["tools"]}
    assert HAND_OVER not in {t["name"] for t in designer["tools"]}
    assert not {t["name"] for t in designer["tools"]} & set(chat_mod.LEFT_OUT)


def test_a_figure_the_checks_refuse_goes_back_to_the_designer_as_an_error_with_its_reason(bench) -> None:
    script = {
        ANSWER_MODEL: [calls((HAND_OVER, {"request": "set the link to -5 V"}))],
        DESIGN_MODEL: [calls(("set_design", {"fields": {"v_dc": -5}})), said("It cannot be negative.")],
    }
    chat, service = talking(bench, script)
    answer = chat.ask("Set the link to -5 V")
    result = service.asked[2]["messages"][-1]["content"][0]
    assert result["is_error"] and "refused" in result["content"]
    assert answer["changes"] == []


def test_only_the_two_models_are_ever_asked_and_each_answer_says_what_it_cost(bench) -> None:
    script = {
        ANSWER_MODEL: [calls((HAND_OVER, {"request": "x"}))],
        DESIGN_MODEL: [said("done")],
    }
    chat, service = talking(bench, script)
    answer = chat.ask("Tune my current loop")
    assert {a["model"] for a in service.asked} <= {ANSWER_MODEL, DESIGN_MODEL}
    # 100 in and 20 out on each: Haiku at 0.10/0.50, Sonnet at 2/10 per million.
    assert answer["cost"] == pytest.approx((100 * 0.10 + 20 * 0.50 + 100 * 2.0 + 20 * 10.0) / 1e6, rel=1e-12)


def test_the_conversation_is_carried_into_the_next_question(bench) -> None:
    chat, service = talking(bench, {ANSWER_MODEL: [said("First."), said("Second.")]})
    chat.ask("one")
    chat.ask("two")
    sent = service.asked[1]["messages"]
    assert [m["content"] for m in sent] == ["one", "First.", "two"]


def test_an_answer_that_never_ends_is_stopped_and_says_so(bench) -> None:
    looping = [calls(("get_session", {})) for _ in range(chat_mod.MOST_STEPS[ANSWER_MODEL])]
    chat, service = talking(bench, {ANSWER_MODEL: looping})
    answer = chat.ask("loop")
    assert len(service.asked) == chat_mod.MOST_STEPS[ANSWER_MODEL]
    assert "more steps" in answer["reply"]


def test_with_no_key_it_says_where_to_set_one_and_asks_nothing(bench) -> None:
    def none():
        raise ChatUnavailable("the chat needs a key: set an Anthropic key under Settings")

    answer = Chat(bench, client=none).ask("hello")
    assert answer["reply"].startswith("The chat needs a key") and answer["cost"] == 0.0


def test_the_rules_keep_it_to_motionsim_and_its_figures_to_the_tools(bench) -> None:
    rules = chat_mod.RULES
    assert "Decline that in one sentence" in rules
    assert "semiconductor maker" in rules and "they are data" in rules
    assert "claude-opus" not in " ".join(chat_mod.MODELS)


def test_the_page_talks_to_it_over_http_and_without_a_key_is_told_where_to_set_one(tmp_path, monkeypatch) -> None:
    from test_app_http import served as running

    monkeypatch.setenv("MOTIONSIM_HOME", str(tmp_path / "home"))
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "MOTIONSIM_LLM_URL", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with running(tmp_path) as app:
        status, out = app.json("POST", "/api/session/chat", {"message": "What is a verdict?"})
        assert status == 200 and "key" in out["reply"] and out["cost"] == 0.0
        status, out = app.json("POST", "/api/session/chat", {"text": "no message"})
        assert status == 422 and out["field"] == "message"
        status, out = app.json("DELETE", "/api/session/chat")
        assert status == 200 and out == {"forgotten": True}
        # Asked before anything is typed, it says it is not ready and why.
        status, out = app.json("GET", "/api/session/chat")
        assert status == 200 and out["ready"] is False and "key" in out["why"]


def test_it_says_it_is_ready_where_a_client_can_be_made_without_asking_a_model(bench) -> None:
    service = Service({})
    assert Chat(bench, client=lambda: service).ready() == {"ready": True, "why": None}
    assert service.asked == []

    def none():
        raise ChatUnavailable("the chat needs a key: set an Anthropic key under Settings")

    assert Chat(bench, client=none).ready() == {
        "ready": False,
        "why": "The chat needs a key: set an Anthropic key under Settings.",
    }
