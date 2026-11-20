"""What a person sees at the command line when a datasheet cannot be read: one plain line
and exit status 2, whatever went wrong and whichever kind of reader is set up."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from evals.reader import sheets
from motionsim.cli import main

SECRET = "sk-not-a-real-key-0123456789"


@pytest.fixture
def clean_env(monkeypatch):
    for name in ("MOTIONSIM_LLM_URL", "MOTIONSIM_LLM_KEY", "MOTIONSIM_LLM_MODEL", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "OPENAI_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def rejecting():
    """A service on this machine that turns every key away, and counts what it was sent."""
    seen: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            seen.append(self.path)
            body = json.dumps({"error": {"message": f"Incorrect API key provided: {SECRET}"}}).encode()
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1", seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_a_file_that_is_not_a_pdf_is_refused_in_words_and_nothing_is_asked(
    tmp_path, clean_env, monkeypatch, rejecting, capsys
) -> None:
    url, seen = rejecting
    monkeypatch.setenv("MOTIONSIM_LLM_URL", url)
    monkeypatch.setenv("MOTIONSIM_LLM_MODEL", "stub")
    notes = tmp_path / "notes.txt"
    notes.write_text("these are not the pages of a datasheet\n" * 50)
    assert main(["extract", str(notes), "-o", str(tmp_path / "out.yaml")]) == 2
    assert capsys.readouterr().err.strip() == "cannot read: that file is not a PDF"
    assert seen == [] and not (tmp_path / "out.yaml").exists()


def test_a_rejected_key_is_one_line_that_does_not_show_the_key(
    tmp_path, clean_env, monkeypatch, rejecting, capsys
) -> None:
    url, seen = rejecting
    monkeypatch.setenv("MOTIONSIM_LLM_URL", url)
    monkeypatch.setenv("MOTIONSIM_LLM_KEY", SECRET)
    monkeypatch.setenv("MOTIONSIM_LLM_MODEL", "stub")
    path = tmp_path / "sheet.pdf"
    path.write_bytes(sheets.build(sheets.labelled_set()[0])[0])
    assert main(["extract", str(path), "-o", str(tmp_path / "out.yaml")]) == 2
    said = capsys.readouterr().err.strip().splitlines()
    refusal = [line for line in said if line.startswith("cannot read: ")]
    assert len(refusal) == 1 and "401" in refusal[0]
    assert SECRET not in "\n".join(said)
    assert len(seen) == 1  # a key that is turned away is not tried again
    assert not (tmp_path / "out.yaml").exists()


def test_no_reader_set_up_says_how_to_set_one_up(tmp_path, clean_env, capsys) -> None:
    path = tmp_path / "sheet.pdf"
    path.write_bytes(sheets.build(sheets.labelled_set()[0])[0])
    assert main(["extract", str(path), "-o", str(tmp_path / "out.yaml")]) == 2
    said = capsys.readouterr().err
    assert said.startswith("cannot read: ") and "ANTHROPIC_API_KEY" in said
