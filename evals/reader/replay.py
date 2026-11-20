"""A stand-in for Anthropic's client that answers from a recording.

It is handed to the reader where a real client would go, so everything the reader does
round a call runs as it does live: the request is built, the stop reason read, the answer
checked against its schema, the tokens counted. Only the model is missing.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
from types import SimpleNamespace

from motionsim.observe import ingest, reader


class ReplayClient:
    max_retries = 0

    def __init__(self, pdf_path, recording: dict) -> None:
        self.pdf_path, self.recording = pdf_path, recording
        self.asked: list[str] = []
        self.messages = self  # the reader calls client.messages.create
        self._pictures: dict[bytes, str] | None = None

    def _page_of(self, picture: bytes) -> str:
        """Which page a picture is of: the pages with a transcript are drawn and compared."""
        if self._pictures is None:
            self._pictures = {ingest.render_page(self.pdf_path, int(n)): n for n in self.recording["transcripts"]}
        return self._pictures[picture]

    def create(self, **request):
        system, content = request["system"], request["messages"][0]["content"]
        if system == reader.SYSTEM:
            self.asked.append("tables")
            said = json.dumps(self.recording["tables"])
        elif system == reader.TRANSCRIBE_SYSTEM:
            page = self._page_of(base64.standard_b64decode(content[0]["source"]["data"]))
            self.asked.append(f"transcript of page {page}")
            said = self.recording["transcripts"][page]
        elif system == reader.AXES_SYSTEM:
            labels = content[1]["text"].removeprefix("Figures, top to bottom: ").split("; ")
            page = next(
                n for n, axes in self.recording["axes"].items() if labels[0] in {f["label"] for f in axes["figures"]}
            )
            self.asked.append(f"axes of page {page}")
            said = json.dumps(self.recording["axes"][page])
        else:
            raise AssertionError("a question this recording has no answer to")
        # No model ran, so nothing was used: the figures are rough sizes, for the ledger to add up.
        sent = len(system) // 4 + (1500 if isinstance(content, list) else len(content) // 4)
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text=said)],
            usage=SimpleNamespace(input_tokens=sent, output_tokens=len(said) // 4),
        )


@contextlib.contextmanager
def as_if_anthropic():
    """The environment set so that the reader takes the Anthropic path. The word that stands
    for a key is never sent anywhere: the client the reader is handed has no network in it."""
    names = ("MOTIONSIM_LLM_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")
    before = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ.pop(name, None)
        os.environ["ANTHROPIC_API_KEY"] = "replay-uses-no-key"
        yield
    finally:
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class ChatService:
    """A chat-completions service on this machine that answers from a recording, so that the
    reader's other path is played as the first is: the request goes over HTTP as JSON, the
    answer comes back in the service's form, and the provider reads it. Only the model is
    missing, and the address is local: nothing leaves the machine."""

    def __init__(self) -> None:
        import http.server
        import threading

        service = self

        class Answer(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                said = service.answer(body)
                data = json.dumps(said).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args) -> None:
                pass

        self.client: ReplayClient | None = None
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Answer)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def answer(self, body: dict) -> dict:
        """A chat-completions request put to the recording as the other path asks it."""
        assert self.client is not None
        system = body["messages"][0]["content"].split("\n\nAnswer with one JSON object")[0]
        content = body["messages"][1]["content"]
        if isinstance(content, list):  # a picture of a page, with the text about it
            picture = content[0]["image_url"]["url"].split(",", 1)[1]
            content = [{"source": {"data": picture}}, {"text": content[1]["text"]}]
        said = self.client.create(system=system, messages=[{"content": content}])
        return {
            "choices": [{"message": {"content": said.content[0].text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": said.usage.input_tokens, "completion_tokens": said.usage.output_tokens},
        }

    @contextlib.contextmanager
    def running(self):
        """The service up, and the environment set so that the reader takes the chat path."""
        names = ("MOTIONSIM_LLM_URL", "MOTIONSIM_LLM_MODEL", "MOTIONSIM_LLM_KEY", "ANTHROPIC_API_KEY")
        names += ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL")
        before = {name: os.environ.get(name) for name in names}
        self.thread.start()
        try:
            for name in names:
                os.environ.pop(name, None)
            os.environ["MOTIONSIM_LLM_URL"] = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
            os.environ["MOTIONSIM_LLM_MODEL"] = "replay"
            yield self
        finally:
            self.server.shutdown()
            self.server.server_close()
            for name, value in before.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


@contextlib.contextmanager
def shared_work():
    """Every recording of a sheet is played on the same bytes: the text of its pages and the
    pictures of them are worked out once a sheet and handed to each reading, as the reading
    of a file the same to the byte would give them. What the reader does with them, and
    every check, still runs for each recording."""
    import hashlib
    from pathlib import Path

    from motionsim.observe import ingest

    read_pages, render = ingest.read_pages, ingest.render_page
    texts: dict = {}
    pictures: dict = {}

    def digest(path) -> str:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def shared_read_pages(path, **kwargs):
        key = (digest(path), tuple(sorted(kwargs.items())))
        if key not in texts:
            texts[key] = read_pages(path, **kwargs)
        document, pages = texts[key]
        return document.model_copy(update={"file": Path(path).name}), list(pages)

    def shared_render(path, number, *args, **kwargs):
        key = (digest(path), number, args, tuple(sorted(kwargs.items())))
        if key not in pictures:
            pictures[key] = render(path, number, *args, **kwargs)
        return pictures[key]

    ingest.read_pages, ingest.render_page = shared_read_pages, shared_render
    try:
        yield
    finally:
        ingest.read_pages, ingest.render_page = read_pages, render
