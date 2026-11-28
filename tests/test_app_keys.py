"""The datasheet reader's key as the page sets it: kept in a file only its owner can read,
never shown, second to the environment, and read with at once. No model is ever asked."""

from __future__ import annotations

import json
import stat
import sys

import pytest

from motionsim.app import home, keys
from motionsim.errors import Refusal
from motionsim.observe import provider, reader

KEY = "sk-made-up-0123456789"


@pytest.fixture(autouse=True)
def own_folder(tmp_path, monkeypatch):
    """A folder of the test's own, an environment that sets no reader up, and the reader's
    lookup put back as it was when the test is over."""
    monkeypatch.setenv(home.HOME, str(tmp_path / "home"))
    # ANTHROPIC_BASE_URL sets no reader up, and would still change the one chosen.
    for name in (*provider.SETS_UP, "ANTHROPIC_BASE_URL", "MOTIONSIM_LLM_MODEL", "MOTIONSIM_LLM_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(provider, "saved_key", provider.saved_key)
    return tmp_path / "home"


def test_the_folder_is_the_one_the_environment_names_or_the_users_own(tmp_path, monkeypatch) -> None:
    assert home.home() == tmp_path / "home" and home.devices() == tmp_path / "home" / "devices"
    monkeypatch.delenv(home.HOME)
    monkeypatch.setattr(home.Path, "home", lambda: tmp_path / "someone")
    # Where the device files have always been kept.
    assert home.devices() == tmp_path / "someone" / ".motionsim" / "devices"


def test_a_key_saved_is_the_key_read_back_and_one_forgotten_is_gone(own_folder) -> None:
    assert keys.saved() == "" and keys.forget() is False
    keys.save(KEY)
    assert keys.saved() == KEY and (own_folder / "reader.key").read_text() == KEY
    assert [p.name for p in own_folder.iterdir()] == ["reader.key"]  # nothing left beside it
    assert keys.forget() is True
    assert keys.saved() == "" and not (own_folder / "reader.key").exists()


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows has no such modes: the folder's own access rules hold there"
)
def test_the_key_file_and_its_folder_are_their_owners_alone(own_folder) -> None:
    keys.save(KEY)
    assert stat.S_IMODE((own_folder / "reader.key").stat().st_mode) == 0o600
    assert stat.S_IMODE(own_folder.stat().st_mode) == 0o700
    # A file left open to others by an earlier hand is closed when a key is saved over it.
    (own_folder / "reader.key").chmod(0o644)
    keys.save(KEY + "-second")
    assert stat.S_IMODE((own_folder / "reader.key").stat().st_mode) == 0o600


@pytest.mark.parametrize(
    "key",
    ["", None, 7, ["sk-a"], "sk with space", " sk-a", "sk-a\n", "sk-\ta", "sk-\x00a", "sk-é", "sk-​a", "k" * 513],
)
def test_what_has_not_the_shape_of_a_key_is_refused_and_never_repeated(own_folder, key) -> None:
    with pytest.raises(Refusal) as refused:
        keys.save(key)
    assert refused.value.field == "key" and refused.value.fix
    said = refused.value.reason + refused.value.fix
    if isinstance(key, str) and len(key.strip()) > 3:
        assert key not in said and key.strip() not in said
    assert not own_folder.exists() or list(own_folder.iterdir()) == []


def test_the_longest_key_taken_is_512_characters(own_folder) -> None:
    keys.save("k" * 512)
    assert len(keys.saved()) == 512


def test_a_key_file_that_holds_no_key_is_no_key(own_folder) -> None:
    own_folder.mkdir()
    (own_folder / "reader.key").write_bytes(b"\xff\xfe not a key")
    assert keys.saved() == "" and keys.state()["reader"]["key"] == "unset"


def test_the_state_says_where_the_key_in_use_comes_from_and_never_the_key(monkeypatch) -> None:
    assert keys.state()["reader"] | {"available": True} == {
        "available": True,
        "key": "unset",
        "source": None,
        "saved": False,
    }
    keys.save(KEY)
    state = keys.state()
    assert (state["reader"]["key"], state["reader"]["source"], state["reader"]["saved"]) == ("set", "saved", True)
    assert KEY not in repr(state)
    # The environment's wins, and the one kept is still said to be kept: it can be forgotten.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-the-shell")
    state = keys.state()
    assert (state["reader"]["key"], state["reader"]["source"], state["reader"]["saved"]) == ("set", "environment", True)
    assert "sk-from-the-shell" not in repr(state)
    keys.forget()
    assert keys.state()["reader"]["source"] == "environment" and keys.state()["reader"]["saved"] is False


def test_the_state_says_whether_the_readers_libraries_are_installed(monkeypatch) -> None:
    monkeypatch.setattr(keys, "find_spec", lambda name: None if name == "pdfplumber" else object())
    assert keys.state()["reader"]["available"] is False
    monkeypatch.setattr(keys, "find_spec", lambda name: object())
    assert keys.state()["reader"]["available"] is True


def test_a_saved_key_is_read_with_at_once_and_a_forgotten_one_no_longer() -> None:
    """The reader looks the key up each time it chooses what to read with: no restart
    stands between saving a key and reading a datasheet with it."""
    keys.use_saved()
    with pytest.raises(provider.NoReader):
        provider.chosen()
    keys.save(KEY)
    assert provider.chosen() == provider.Reader("anthropic", provider.ANTHROPIC_MODEL)
    assert provider.environment()["ANTHROPIC_API_KEY"] == KEY
    assert provider.anthropic_arguments() == {"api_key": KEY}
    keys.forget()
    with pytest.raises(provider.NoReader):
        provider.chosen()
    assert provider.anthropic_arguments() == {}


@pytest.mark.parametrize(
    "variable",
    [
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "MOTIONSIM_LLM_URL",
        "OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "XAI_API_KEY",
    ],
)
def test_a_reader_set_up_in_the_environment_wins_over_the_saved_key(monkeypatch, variable) -> None:
    keys.use_saved()
    keys.save(KEY)
    monkeypatch.setenv(variable, "http://127.0.0.1:9/v1" if variable.endswith("URL") else "from-the-shell")
    monkeypatch.setenv("MOTIONSIM_LLM_MODEL", "a-model")
    # The environment as it is, with nothing of the saved key in it or handed on beside it.
    assert provider.environment().get("ANTHROPIC_API_KEY") == (
        "from-the-shell" if variable == "ANTHROPIC_API_KEY" else None
    )
    assert provider.anthropic_arguments() == {}
    assert provider.chosen().kind == ("anthropic" if variable.startswith("ANTHROPIC") else "chat")
    assert keys.state()["reader"]["source"] == "environment"


def test_a_command_of_the_command_line_reads_the_environment_alone(own_folder) -> None:
    keys.save(KEY)  # kept, and no program serving a page has put its lookup in place
    assert provider.environment().get("ANTHROPIC_API_KEY") is None
    with pytest.raises(provider.NoReader):
        provider.chosen()


def test_anthropics_library_is_handed_the_saved_key_and_no_model_is_asked(monkeypatch) -> None:
    """The client is made with the saved key; the question itself is a stub's to answer."""
    made: list[dict] = []

    class Sdk:
        AnthropicError = RuntimeError

        @staticmethod
        def Anthropic(**arguments):
            made.append(arguments)
            raise RuntimeError("stopped where the test wanted")

    monkeypatch.setattr(provider, "needs", lambda module, what: Sdk)
    keys.use_saved()
    keys.save(KEY)
    ask = lambda client: pytest.fail("no model is asked in a test")
    with pytest.raises(provider.ReaderFailed) as failed:
        reader._from_anthropic(provider.chosen(), None, ask, 100, "a test", None)
    assert made == [{"api_key": KEY}]
    assert KEY not in str(failed.value)
    # With a key in the environment the library reads it itself, as it always has.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-the-shell")
    with pytest.raises(provider.ReaderFailed):
        reader._from_anthropic(provider.chosen(), None, ask, 100, "a test", None)
    assert made[1] == {}


def test_keys_saved_at_once_from_many_requests_each_land_whole(own_folder) -> None:
    """Fifty saves at the same moment, and a reader looking all the while: every save is
    kept, and the file holds one whole key at every moment it is read."""
    import threading

    sent = [f"sk-made-up-{n:02d}-" + "abcdefghijklmnopqrstuvwxyz"[n % 26] * (20 + 7 * n) for n in range(50)]
    keys.save(sent[0])
    faults: list[BaseException] = []
    seen: set[str] = set()
    done = threading.Event()

    def save(key: str) -> None:
        try:
            keys.save(key)
        except BaseException as fault:
            faults.append(fault)

    def watch() -> None:
        while not done.is_set():
            seen.add((own_folder / "reader.key").read_text())
            seen.add(keys.saved())

    watcher = threading.Thread(target=watch)
    watcher.start()
    for _ in range(4):
        savers = [threading.Thread(target=save, args=(key,)) for key in sent]
        for saver in savers:
            saver.start()
        for saver in savers:
            saver.join()
    done.set()
    watcher.join()
    assert faults == []
    assert seen <= set(sent)
    assert keys.saved() in sent
    assert [p.name for p in own_folder.iterdir()] == ["reader.key"]


@pytest.mark.skipif(sys.platform == "win32", reason="a link to a file is made with privileges on Windows")
def test_a_link_planted_in_the_folder_is_never_followed(own_folder, tmp_path) -> None:
    """Whoever could write in the folder could put a link where the key is written, to have
    it written into a file of theirs, or read from one: a link is replaced, never followed."""
    import os

    outside = tmp_path / "theirs"
    outside.write_text("theirs")
    own_folder.mkdir(parents=True, mode=0o700)
    # Where a key was once written before it was put in its place, and the place itself.
    (own_folder / f"reader.key.{os.getpid()}.new").symlink_to(outside)
    keys.save(KEY)
    assert outside.read_text() == "theirs" and keys.saved() == KEY
    (own_folder / "reader.key").unlink()
    (own_folder / "reader.key").symlink_to(outside)
    outside.write_text(KEY + "-theirs")
    assert keys.saved() == ""  # a link is no key
    keys.save(KEY)
    assert outside.read_text() == KEY + "-theirs"
    assert not (own_folder / "reader.key").is_symlink() and keys.saved() == KEY


class Echo:
    """A stand-in for a model's service on a port of this machine: it refuses every request
    with words that repeat the key it was sent, as a careless service's error may. No model
    is asked."""

    def __init__(self, status: int = 400) -> None:
        import http.server
        import threading

        heard: list[str] = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                self.rfile.read(int(self.headers.get("Content-Length") or 0))
                key = self.headers.get("x-api-key") or self.headers.get("Authorization") or ""
                heard.append(key)
                body = json.dumps(
                    {"type": "error", "error": {"type": "invalid_request_error", "message": f"bad credential {key}"}}
                ).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                pass

        self.heard = heard
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=10)


def test_a_service_that_repeats_the_saved_key_has_its_words_said_without_it(monkeypatch) -> None:
    pytest.importorskip("anthropic", reason="Anthropic's library is the reader's")
    echo = Echo(400)
    try:
        monkeypatch.setenv("ANTHROPIC_BASE_URL", echo.url)
        keys.use_saved()
        keys.save(KEY)
        ask = lambda client: client.messages.create(
            model="made-up", max_tokens=10, messages=[{"role": "user", "content": "x"}]
        )
        with pytest.raises(provider.ReaderFailed) as failed:
            reader._from_anthropic(provider.chosen(), None, ask, 10, "a test", None)
    finally:
        echo.stop()
    assert echo.heard and KEY in echo.heard[0]  # the service was sent the key, and said it back
    assert "bad credential" in str(failed.value) and KEY not in str(failed.value)


@pytest.mark.parametrize("variable", ["ANTHROPIC_API_KEY", "MOTIONSIM_LLM_KEY", "OPENAI_API_KEY"])
def test_a_key_of_the_environment_is_taken_out_of_any_words(monkeypatch, variable) -> None:
    monkeypatch.setenv(variable, KEY + "-shell")
    assert provider.scrub(f"refused {KEY}-shell, twice: {KEY}-shell") == "refused [key], twice: [key]"
    keys.use_saved()
    keys.save(KEY + "-saved")
    assert provider.scrub(f"{KEY}-saved and {KEY}-shell") == "[key] and [key]"
