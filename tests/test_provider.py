"""Which language model reads a datasheet, and the interface the makers other than Anthropic
share, held to a service run here: no call leaves this machine and none is paid for."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from motionsim.observe import provider, reader
from motionsim.observe.schema import ReadResult

READ = {
    "vendor": "Made Up",
    "part_number": "MU-100",
    "technology": "Si MOSFET",
    "topology": "discrete",
    "integrated_driver": False,
    "points": [],
    "figures": [],
}


@pytest.fixture
def service():
    """A chat-completions service on this machine. `asked` keeps what it was sent; `knows`
    is the ways of holding an answer to a shape that it accepts; `faults` is a list of
    (status, headers, body) it answers with first, one a request, before it answers well."""
    state = {
        "asked": [],
        "knows": {"json_schema", "json_object"},
        "says": json.dumps(READ),
        "faults": [],
        "finish": "stop",
        "usage": {"prompt_tokens": 1200, "completion_tokens": 300},
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["asked"].append({"path": self.path, "key": self.headers.get("Authorization"), "body": body})
            if state["faults"]:
                status, headers, said = state["faults"].pop(0)
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(said)))
                self.end_headers()
                self.wfile.write(said)
                return
            wanted = (body.get("response_format") or {}).get("type")
            if wanted and wanted not in state["knows"]:
                said = b'{"error": "response_format is not supported"}'
                self.send_response(400)
                self.send_header("Content-Length", str(len(said)))
                self.end_headers()
                self.wfile.write(said)
                return
            if state.get("raw") is not None:  # an answer that is not the service's usual shape
                said = state["raw"]
                self.send_response(200)
                self.send_header("Content-Length", str(len(said)))
                self.end_headers()
                self.wfile.write(said)
                return
            answer = {
                "choices": [
                    {"message": {"role": "assistant", "content": state["says"]}, "finish_reason": state["finish"]}
                ],
                **({"usage": state["usage"]} if state["usage"] else {}),
            }
            said = json.dumps(answer).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(said)))
            self.end_headers()
            self.wfile.write(said)

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{httpd.server_address[1]}/v1"
    yield state
    # Stopped, joined and closed: a listening socket left open is a warning, and a warning is an error.
    httpd.shutdown()
    thread.join()
    httpd.server_close()


@pytest.fixture
def chat(service, monkeypatch):
    """The environment set to read through the service above, and no waiting between tries."""
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MOTIONSIM_LLM_URL", service["url"])
    monkeypatch.setenv("MOTIONSIM_LLM_MODEL", "local-model")
    monkeypatch.setenv("MOTIONSIM_LLM_KEY", "secret-key-123")
    service["waits"] = []
    monkeypatch.setattr(provider, "_sleep", service["waits"].append)
    return service


def test_the_first_reader_set_up_is_the_one_used_and_a_model_has_to_be_named() -> None:
    with pytest.raises(provider.NoReader, match="none is set up"):
        provider.chosen({})
    assert provider.chosen({"ANTHROPIC_API_KEY": "k"}) == provider.Reader("anthropic", provider.ANTHROPIC_MODEL)
    # Another maker's key says where to ask and not which model: that has to be named.
    with pytest.raises(provider.NoReader, match="MOTIONSIM_LLM_MODEL"):
        provider.chosen({"OPENAI_API_KEY": "k"})
    for variable, address in provider.SERVICES:
        found = provider.chosen({variable: "k", "MOTIONSIM_LLM_MODEL": "some-model"})
        assert found == provider.Reader("chat", "some-model", address, "k")
    # A service of the user's own comes before any maker's key, and needs no key at all.
    own = provider.chosen(
        {"MOTIONSIM_LLM_URL": "http://localhost:11434/v1/", "MOTIONSIM_LLM_MODEL": "local", "ANTHROPIC_API_KEY": "k"}
    )
    assert own == provider.Reader("chat", "local", "http://localhost:11434/v1", "")
    assert provider.available({"XAI_API_KEY": "k", "MOTIONSIM_LLM_MODEL": "m"}) and not provider.available({})


def test_a_datasheet_is_read_through_a_service_that_is_not_anthropic(service, monkeypatch) -> None:
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MOTIONSIM_LLM_URL", service["url"])
    monkeypatch.setenv("MOTIONSIM_LLM_MODEL", "local-model")
    monkeypatch.setenv("MOTIONSIM_LLM_KEY", "secret")
    read = reader.read_tables(["page one text", "page two text"])
    assert read == ReadResult.model_validate(READ) and reader.reader_name() == "local-model"
    (asked,) = service["asked"]
    assert asked["path"] == "/v1/chat/completions" and asked["key"] == "Bearer secret"
    body = asked["body"]
    assert body["model"] == "local-model" and body["response_format"]["type"] == "json_schema"
    assert body["messages"][0]["role"] == "system" and "JSON schema" in body["messages"][0]["content"]
    assert "=== page 2 ===\npage two text" in body["messages"][1]["content"]


def test_a_service_that_cannot_hold_an_answer_to_a_schema_is_asked_more_plainly(service, monkeypatch) -> None:
    monkeypatch.setenv("MOTIONSIM_LLM_URL", service["url"])
    monkeypatch.setenv("MOTIONSIM_LLM_MODEL", "small")
    monkeypatch.delenv("MOTIONSIM_LLM_KEY", raising=False)
    service["knows"] = set()  # neither a schema nor plain JSON as a format
    service["says"] = "Here it is:\n```json\n" + json.dumps(READ) + "\n```"
    assert reader.read_tables(["text"]).part_number == "MU-100"
    assert [(a["body"].get("response_format") or {}).get("type") for a in service["asked"]] == [
        "json_schema",
        "json_object",
        None,
    ]
    assert service["asked"][0]["key"] is None  # no key was set, and none is sent


def test_an_answer_in_the_wrong_form_is_said_in_words(service, monkeypatch) -> None:
    monkeypatch.setenv("MOTIONSIM_LLM_URL", service["url"])
    monkeypatch.setenv("MOTIONSIM_LLM_MODEL", "small")
    monkeypatch.setattr(provider, "_sleep", lambda seconds: None)
    service["says"] = '{"vendor": "Made Up"}'
    with pytest.raises(provider.ReaderFailed, match="did not answer in the form asked for"):
        reader.read_tables(["text"])
    monkeypatch.setenv("MOTIONSIM_LLM_URL", "http://127.0.0.1:9/v1")  # nothing listens there
    with pytest.raises(provider.ReaderFailed, match="no connection to"):
        reader.read_tables(["text"])


def test_a_page_with_no_text_is_sent_as_a_picture(service, monkeypatch) -> None:
    monkeypatch.setenv("MOTIONSIM_LLM_URL", service["url"])
    monkeypatch.setenv("MOTIONSIM_LLM_MODEL", "sees")
    service["says"] = "VDS 100 V"
    assert reader.transcribe(b"\x89PNG not really") == "VDS 100 V"
    picture, words = service["asked"][0]["body"]["messages"][1]["content"]
    assert picture["type"] == "image_url" and picture["image_url"]["url"].startswith("data:image/png;base64,")
    assert words == {"type": "text", "text": "Transcribe this page."}
    assert "response_format" not in service["asked"][0]["body"]


# What follows holds the chat interface to what a careless or hostile service can do.


def test_a_key_that_is_rejected_is_said_as_that_and_the_key_is_never_shown(chat) -> None:
    chat["faults"] = [(401, {}, b'{"error": {"message": "Incorrect API key provided: secret-key-123"}}')]
    with pytest.raises(provider.ReaderFailed) as stopped:
        reader.read_tables(["text"])
    said = str(stopped.value)
    assert "key was rejected" in said and "401" in said
    assert "secret-key-123" not in said and "\n" not in said
    assert len(chat["asked"]) == 1  # a rejected key is not tried again


def test_a_rate_limit_and_a_fault_are_tried_twice_more_and_then_named(chat) -> None:
    chat["faults"] = [(429, {"Retry-After": "7"}, b"slow down"), (503, {}, b"busy")]
    assert reader.read_tables(["text"]).part_number == "MU-100"
    assert len(chat["asked"]) == 3
    assert chat["waits"][0] == 7.0  # the service said how long to wait, and that is how long
    assert 0 < chat["waits"][1] <= 2.0

    chat["asked"].clear()
    chat["faults"] = [(429, {}, b"slow down")] * 3
    with pytest.raises(provider.ReaderFailed, match=r"rate limited \(429\).*3 tries"):
        reader.read_tables(["text"])
    assert len(chat["asked"]) == 3

    chat["faults"] = [(500, {}, b"oops")] * 3
    with pytest.raises(provider.ReaderFailed, match=r"fault of its own \(500\)"):
        reader.read_tables(["text"])


def test_no_connection_is_tried_again_and_then_said(chat, monkeypatch) -> None:
    monkeypatch.setenv("MOTIONSIM_LLM_URL", "http://127.0.0.1:9/v1")  # nothing listens there
    with pytest.raises(provider.ReaderFailed, match="no connection to http://127"):
        reader.read_tables(["text"])
    assert len(chat["waits"]) == 2


def test_the_key_is_not_carried_to_another_address_by_a_redirect(chat) -> None:
    """A second service stands where a redirect points. It must never be asked, key or no key."""
    seen = []

    class Elsewhere(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(self.headers.get("Authorization"))
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

        do_GET = do_POST

        def log_message(self, *args):
            pass

    other = ThreadingHTTPServer(("127.0.0.1", 0), Elsewhere)
    thread = threading.Thread(target=other.serve_forever, args=(0.01,), daemon=True)
    thread.start()
    try:
        there = f"http://127.0.0.1:{other.server_address[1]}/v1/chat/completions"
        for status in (301, 302, 307, 308):
            chat["faults"] = [(status, {"Location": there}, b"")]
            with pytest.raises(provider.ReaderFailed, match="redirect"):
                reader.read_tables(["text"])
        assert seen == []
    finally:
        other.shutdown()
        thread.join()
        other.server_close()


def test_what_a_service_says_of_its_fault_is_trimmed_and_cleaned(chat) -> None:
    chat["faults"] = [(400, {}, b"bad \x1b[31mrequest\x00\r\n" + b"x" * 5000)] * 3
    with pytest.raises(provider.ReaderFailed) as stopped:
        reader.read_tables(["text"])
    said = str(stopped.value)
    assert "bad" in said and "request" in said
    assert all(ch.isprintable() for ch in said) and len(said) < 400


def test_an_answer_too_long_to_be_one_is_refused_unread(chat, monkeypatch) -> None:
    monkeypatch.setattr(provider, "MAX_ANSWER", 2000)
    chat["says"] = "x" * 5000
    with pytest.raises(provider.ReaderFailed, match="more than"):
        reader.transcribe(b"png")


DEEP = 100_000  # far past the depth Python's own reading of JSON can follow


@pytest.mark.parametrize(
    "raw",
    [
        b"[" * DEEP + b"]" * DEEP,
        b'{"choices": [{"message": {"content": ' + b"[" * DEEP + b"]" * DEEP + b"}}]}",
    ],
)
def test_an_answer_nested_past_reading_is_a_reading_failure(chat, raw) -> None:
    chat["raw"] = raw
    with pytest.raises(provider.ReaderFailed):
        reader.read_tables(["text"])


def test_words_nested_past_reading_are_a_reading_failure(chat) -> None:
    chat["says"] = '{"a": ' * DEEP + "1" + "}" * DEEP
    with pytest.raises(provider.ReaderFailed):
        reader.read_tables(["text"])


def test_a_fault_nested_past_reading_is_a_reading_failure(chat) -> None:
    chat["faults"] = [(400, {}, b"[" * DEEP + b"]" * DEEP)] * 3
    with pytest.raises(provider.ReaderFailed, match="400"):
        reader.read_tables(["text"])


@pytest.mark.parametrize(
    "parts",
    [
        [{"type": "text", "text": 5}],
        [{"type": "text", "text": None}, "words", 7],
        [{"type": "text", "text": {"nested": "x"}}],
    ],
)
def test_parts_of_an_answer_that_are_not_text_are_a_reading_failure(chat, parts) -> None:
    chat["says"] = parts
    with pytest.raises(provider.ReaderFailed):
        reader.read_tables(["text"])


def test_text_in_parts_is_read(chat) -> None:
    text = json.dumps(READ)
    chat["says"] = [{"type": "text", "text": text[:10]}, {"type": "text", "text": text[10:]}]
    assert reader.read_tables(["text"]) == ReadResult.model_validate(READ)


def test_an_answer_cut_off_and_an_answer_declined_are_told_apart(chat) -> None:
    chat["finish"] = "length"
    chat["says"] = json.dumps(READ)[:40]
    with pytest.raises(provider.ReaderFailed, match="cut off"):
        reader.read_tables(["text"])
    chat["finish"] = "content_filter"
    with pytest.raises(provider.ReaderRefused, match="declined"):
        reader.read_tables(["text"])


def test_what_each_call_used_is_counted_and_a_budget_stops_the_next(chat) -> None:
    ledger = provider.Ledger(max_calls=2)
    reader.read_tables(["text"], ledger=ledger)
    chat["says"] = "VDS 100 V"
    reader.transcribe(b"png", ledger=ledger)
    assert (ledger.calls, ledger.input_tokens, ledger.output_tokens) == (2, 2400, 600)
    assert "2 model calls" in ledger.summary() and "2\u202f400" in ledger.summary()
    with pytest.raises(provider.ReaderFailed, match="budget of 2 model calls"):
        reader.transcribe(b"png", ledger=ledger)
    assert len(chat["asked"]) == 2  # the third was never sent

    chat["usage"] = None  # a service that does not say what it used is said not to have
    quiet = provider.Ledger()
    reader.transcribe(b"png", ledger=quiet)
    assert quiet.unreported == 1 and "did not say" in quiet.summary()


def test_a_key_sent_in_the_clear_to_another_machine_is_warned_of() -> None:
    plain = provider.Reader("chat", "m", "http://models.example.com/v1", "k")
    assert "not encrypted" in provider.in_the_clear(plain)
    for safe in (
        provider.Reader("chat", "m", "https://models.example.com/v1", "k"),
        provider.Reader("chat", "m", "http://localhost:11434/v1", "k"),
        provider.Reader("chat", "m", "http://127.0.0.1:8000/v1", "k"),
        provider.Reader("chat", "m", "http://[::1]:8000/v1", "k"),
        provider.Reader("chat", "m", "http://models.example.com/v1", ""),  # no key to lose
    ):
        assert provider.in_the_clear(safe) is None


def test_the_warning_is_given_before_the_key_is_sent(monkeypatch) -> None:
    sent = []
    monkeypatch.setattr(provider, "_post", lambda reader, body: sent.append(body) or {"choices": []})
    plain = provider.Reader("chat", "m", "http://models.example.com/v1", "k")
    with pytest.warns(provider.KeyInTheClear, match="not encrypted"), pytest.raises(provider.ReaderFailed):
        provider.ask(plain, "system", "text")


def test_anthropic_is_chosen_by_a_key_or_a_token_as_its_own_library_does() -> None:
    assert provider.chosen({"ANTHROPIC_AUTH_TOKEN": "t"}) == provider.Reader("anthropic", provider.ANTHROPIC_MODEL)
    # An address for Anthropic's own interface is the library's to use; it is shown, never the key.
    there = provider.chosen({"ANTHROPIC_API_KEY": "k", "ANTHROPIC_BASE_URL": "http://127.0.0.1:1/"})
    assert there.kind == "anthropic" and there.url == "http://127.0.0.1:1" and there.key == ""
    # An address alone is not a reader: there is nothing to sign in with.
    with pytest.raises(provider.NoReader):
        provider.chosen({"ANTHROPIC_BASE_URL": "http://127.0.0.1:1/"})


def test_a_reader_shown_does_not_show_its_key() -> None:
    assert "hunter2" not in repr(provider.Reader("chat", "m", "https://x.example/v1", "hunter2"))
