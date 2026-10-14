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
    is the ways of holding an answer to a shape that it accepts."""
    state = {"asked": [], "knows": {"json_schema", "json_object"}, "says": json.dumps(READ)}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["asked"].append({"path": self.path, "key": self.headers.get("Authorization"), "body": body})
            wanted = (body.get("response_format") or {}).get("type")
            if wanted and wanted not in state["knows"]:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error": "response_format is not supported"}')
                return
            answer = {"choices": [{"message": {"role": "assistant", "content": state["says"]}}]}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(answer).encode())

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{httpd.server_address[1]}/v1"
    yield state
    httpd.shutdown()


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
    service["says"] = '{"vendor": "Made Up"}'
    with pytest.raises(provider.ReaderFailed, match="did not answer in the form asked for"):
        reader.read_tables(["text"])
    monkeypatch.setenv("MOTIONSIM_LLM_URL", "http://127.0.0.1:9/v1")  # nothing listens there
    with pytest.raises(provider.ReaderFailed, match="could not be reached"):
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
