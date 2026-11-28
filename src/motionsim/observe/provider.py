"""Which language model reads a datasheet, and how it is asked.

Anthropic's models are asked through Anthropic's own library. Every other maker's, and a
model run on your own machine, is asked through the chat-completions interface they have in
common: OpenAI, Google's Gemini, xAI's Grok, and local servers such as Ollama, vLLM and
llama.cpp all speak it. The choice is made from the environment, so no key is ever written
into a file:

- MOTIONSIM_LLM_URL: the address of a chat-completions service, yours or anyone's. With it,
  MOTIONSIM_LLM_MODEL names the model, and MOTIONSIM_LLM_KEY is its key where it wants one.
- ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN: Anthropic, with the model this tool was built
  and checked on. Anthropic's library reads both itself, the key before the token, and
  reads ANTHROPIC_BASE_URL for an address other than Anthropic's own. A sign-in kept on
  disk by Anthropic's command line is not looked for here: set one of the two variables.
- OPENAI_API_KEY, GEMINI_API_KEY or XAI_API_KEY: that maker's service, with
  MOTIONSIM_LLM_MODEL naming the model.

The first that is set, in that order, is the one used. Whatever reads, the same checks hold
every value to the page it was cited from: a weaker reader is set aside more often, not
believed more.

A key is sent to the service it belongs to and nowhere else: it is not followed across a
redirect, not put in a message, not written to a file.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import warnings
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from motionsim.text import whole

ANTHROPIC_MODEL = "claude-opus-5-5"
TIMEOUT = 600.0  # s; a long datasheet takes a model some minutes
TRIES = 3  # one question is asked this many times at most: once, and twice more after a fault that may pass
LONGEST_WAIT = 30.0  # s; a service that asks for longer than this between tries is not waited for
MAX_ANSWER = 8_000_000  # bytes; a whole datasheet's values are some tens of kilobytes of JSON
MAX_CALLS = 40  # model calls one datasheet may cost unless more are allowed: tables, scanned pages, figure pages
SAID = 200  # characters of a service's own words about its fault that are passed on

# A maker's key in the environment, and the address its chat-completions service answers at.
SERVICES = (
    ("OPENAI_API_KEY", "https://api.openai.com/v1"),
    ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai"),
    ("XAI_API_KEY", "https://api.x.ai/v1"),
)

# How to add the reader. The package is not on PyPI, where the bare name could be anyone's:
# it is installed from its repository, or from a clone. On publishing, this line becomes
# 'pip install "motionsim[reader]"'.
INSTALL = 'pip install "motionsim[reader] @ git+https://github.com/yannickYamo/MotionSim", or pip install ".[reader]" in a clone'

_sleep = time.sleep  # named so that a test can count the waits and not sit through them


class NoReader(RuntimeError):
    """No language model is set up to read with, or the one set up is not fully named, or
    the libraries that read a PDF are not installed."""


class ReaderFailed(RuntimeError):
    """The model was reached and did not give an answer that can be used, or the file
    cannot be read. The message is one plain line that names the cause; fix, where it is
    known, what to do about that cause."""

    def __init__(self, reason: str, fix: str = "") -> None:
        # A service's own words may repeat the key it was sent: never past here.
        super().__init__(scrub(reason))
        self.fix = scrub(fix)


class ReaderRefused(ReaderFailed):
    """The model declined to read what it was given."""


class KeyInTheClear(UserWarning):
    """A key is about to cross a network without encryption."""


def needs(module: str, what: str) -> Any:
    """A library only the reader uses, loaded when it is first wanted. The engine runs
    without any of them, so a missing one is said in words with what to install."""
    import importlib

    try:
        return importlib.import_module(module)
    except ImportError:
        raise NoReader(f"{what} needs the {module} library, which is not installed: {INSTALL}") from None


@dataclass(frozen=True)
class Reader:
    kind: str  # "anthropic", or "chat" for the interface the others share
    model: str
    url: str = ""
    key: str = field(default="", repr=False)  # never shown, so never logged by accident

    @property
    def name(self) -> str:
        """What is recorded beside a reading, so a result can say what read it."""
        return self.model

    @property
    def where(self) -> str:
        """The service, as a message names it."""
        return self.url or "Anthropic"


@dataclass
class Ledger:
    """What reading one datasheet has cost so far, and the most it may.

    Every question to a model is entered before it is sent, so the one that would pass the
    budget is never sent. Pages are transcribed several at a time, hence the lock.
    """

    max_calls: int = MAX_CALLS
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    unreported: int = 0  # calls whose service did not say what they used
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def spend(self, what: str) -> None:
        with self._lock:
            if self.calls >= self.max_calls:
                raise ReaderFailed(
                    f"the budget of {self.max_calls} model calls for one datasheet is used up before {what}: "
                    "allow more calls, or read fewer pages",
                    "allow more calls (--max-calls), or read fewer pages",
                )
            self.calls += 1

    def used(self, input_tokens: int | None, output_tokens: int | None) -> None:
        with self._lock:
            if input_tokens is None or output_tokens is None:
                self.unreported += 1
            else:
                self.input_tokens += int(input_tokens)
                self.output_tokens += int(output_tokens)

    def summary(self) -> str:
        """One line for the person who pays: calls made and tokens used."""
        calls = f"{self.calls} model call{'' if self.calls == 1 else 's'}"
        line = f"{calls}, {whole(self.input_tokens)} tokens in and {whole(self.output_tokens)} out"
        if self.unreported:
            line += f" ({self.unreported} of the calls did not say what they used)"
        return line


def _named(env: Mapping[str, str]) -> str:
    model = env.get("MOTIONSIM_LLM_MODEL", "").strip()
    if not model:
        raise NoReader(
            "a language model is set up to read with, and MOTIONSIM_LLM_MODEL does not say which model: "
            "set it to the name its service knows the model by"
        )
    return model


# The variables that set a reader up, any one of them.
SETS_UP = ("MOTIONSIM_LLM_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", *(name for name, _ in SERVICES))


def _no_saved_key() -> str:
    return ""


# The key kept by the page's own settings, asked for each time a reader is chosen, so that a
# key saved a moment ago is the one used with no restart. The program that serves the page
# puts its lookup here (motionsim.app); a command of the command line has none, and reads
# the environment alone.
saved_key: Callable[[], str] = _no_saved_key


# The variables a key is given in: whatever they hold is taken out of any words said.
KEYS_IN = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "MOTIONSIM_LLM_KEY", *(name for name, _ in SERVICES))
SHORTEST_KEY = 8  # characters: anything shorter is no key, and taking it out would garble words


def known_keys() -> list[str]:
    """Every key this process could send: the environment's and the one saved from the page,
    longest first so that a key inside another is taken out with it."""
    found = {os.environ.get(name, "").strip() for name in KEYS_IN}
    # A saved key that cannot be looked up is none to take out.
    with contextlib.suppress(Exception):
        found.add(saved_key())
    return sorted((key for key in found if len(key) >= SHORTEST_KEY), key=len, reverse=True)


def scrub(text: str) -> str:
    """The words with every key this process holds taken out, as it is sent, and as JSON
    writes it: whatever leaves the process or is logged has been through this."""
    for key in known_keys():
        text = text.replace(key, "[key]")
        written = json.dumps(key)[1:-1]
        if written != key:
            text = text.replace(written, "[key]")
    return text


class Scrubbed(logging.Filter):
    """A log handler's filter: a record's words, and its traceback's, said without a key."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        clean = scrub(message)
        if clean != message:
            record.msg, record.args = clean, None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = scrub(record.exc_text)
        return True


def in_environment(env: Mapping[str, str] | None = None) -> bool:
    """Whether the environment itself sets a reader up, whole or in part."""
    env = os.environ if env is None else env
    return any(env.get(name) for name in SETS_UP)


def environment() -> Mapping[str, str]:
    """Where a reader and its key are looked up, and the one place they are: the process's
    environment, which wins wherever it sets a reader up, and otherwise the same with the
    key saved from the page standing as Anthropic's."""
    if in_environment():
        return os.environ
    key = saved_key()
    return {**os.environ, "ANTHROPIC_API_KEY": key} if key else os.environ


def anthropic_arguments() -> dict[str, str]:
    """What Anthropic's library is handed besides what it reads from the environment itself:
    the saved key, where that is the one in use, and nothing otherwise."""
    if in_environment():
        return {}
    key = saved_key()
    return {"api_key": key} if key else {}


def chosen(env: Mapping[str, str] | None = None) -> Reader:
    """The reader the environment sets up. Raises NoReader with what to set where none is.

    Precedence, first that is set: MOTIONSIM_LLM_URL (a service of your own); then
    ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN (Anthropic's library uses the key where both
    are set, and ANTHROPIC_BASE_URL as the address where that is set); then OPENAI_API_KEY,
    GEMINI_API_KEY, XAI_API_KEY. The Anthropic key and token are left for its library to
    read: they are never copied into the reader returned here.
    """
    env = environment() if env is None else env
    url = env.get("MOTIONSIM_LLM_URL", "").strip().rstrip("/")
    if url:
        return Reader("chat", _named(env), url, env.get("MOTIONSIM_LLM_KEY", "").strip())
    if env.get("ANTHROPIC_API_KEY") or env.get("ANTHROPIC_AUTH_TOKEN"):
        return Reader("anthropic", ANTHROPIC_MODEL, env.get("ANTHROPIC_BASE_URL", "").strip().rstrip("/"))
    for variable, address in SERVICES:
        if env.get(variable):
            return Reader("chat", _named(env), address, env[variable].strip())
    raise NoReader(
        "reading a datasheet needs a language model, and none is set up: set ANTHROPIC_API_KEY, or "
        "OPENAI_API_KEY, GEMINI_API_KEY or XAI_API_KEY with MOTIONSIM_LLM_MODEL, or MOTIONSIM_LLM_URL "
        "and MOTIONSIM_LLM_MODEL for a model of your own"
    )


def available(env: Mapping[str, str] | None = None) -> bool:
    try:
        chosen(env)
    except NoReader:
        return False
    return True


# What went wrong, in the same words whichever service it went wrong with.


def plain(detail: object, secret: str = "") -> str:
    """A service's own words about its fault, made safe to show: the message out of a JSON
    error where there is one, control characters gone, the key gone, and not too long."""
    text = detail.decode(errors="replace") if isinstance(detail, bytes) else str(detail)
    try:
        parsed = json.loads(text)
    except (ValueError, RecursionError):
        parsed = None
    if isinstance(parsed, dict):
        error = parsed.get("error", parsed)
        message = error.get("message") if isinstance(error, dict) else error
        if isinstance(message, str):
            text = message
    text = scrub(text.replace(secret, "[key]") if secret else text)
    text = " ".join("".join(ch if ch.isprintable() else " " for ch in text).split())
    return text if len(text) <= SAID else text[:SAID].rstrip() + "…"


def status_failure(reader: Reader, status: int, detail: object = "", tries: int = 1) -> ReaderFailed:
    """The failure a refused request is, named by its cause."""
    where, said = reader.where, plain(detail, reader.key)
    after = f" and still was after {tries} tries" if tries > 1 else ""
    if status == 401:
        return ReaderFailed(
            f"the key was rejected by {where} (401): check the key that is set for it",
            "check the key set for the service in the shell that reads, and that it has not expired",
        )
    if status == 403:
        return ReaderFailed(
            f"the key is not allowed to use {reader.model} at {where} (403)",
            "use a key allowed that model, or name another with MOTIONSIM_LLM_MODEL",
        )
    if status == 404:
        return ReaderFailed(
            f"{where} does not know the model {reader.model} or the address asked (404)",
            "check the model's name in MOTIONSIM_LLM_MODEL and the address in MOTIONSIM_LLM_URL",
        )
    if status == 429:
        return ReaderFailed(
            f"{where} is rate limited (429){after}: wait a while, then read again", "wait a while, then read again"
        )
    if status >= 500:
        return ReaderFailed(
            f"{where} had a fault of its own ({status}){after}: nothing is wrong here, try again later",
            "nothing is wrong on this side: try again later",
        )
    if 300 <= status < 400:
        return ReaderFailed(
            f"{where} answered with a redirect ({status}) to another address, and a key is not sent on to one: "
            "set the address the service really answers at",
            "set MOTIONSIM_LLM_URL to the address the service really answers at",
        )
    return ReaderFailed(
        f"{where} would not take the request ({status})" + (f": {said}" if said else ""),
        "check what the service says above; a model that reads pictures and follows a schema is needed",
    )


def no_connection(reader: Reader, reason: object, tries: int = 1) -> ReaderFailed:
    after = f" after {tries} tries" if tries > 1 else ""
    return ReaderFailed(
        f"no connection to {reader.where}{after}: {plain(reason, reader.key)}",
        "check the address, that the service is running, and this machine's connection",
    )


def declined(what: str = "this document") -> ReaderRefused:
    return ReaderRefused(f"the model declined to read {what}")


def cut_off(max_tokens: int | None = None) -> ReaderFailed:
    at = f" at {max_tokens} tokens" if max_tokens else ""
    return ReaderFailed(
        f"the answer was cut off{at} before it was complete: raise the token budget, "
        "or split the datasheet and read it in parts",
        "split the datasheet and read it in parts, or read the tables alone (--no-curves)",
    )


def wrong_form(reader: Reader, wrong: ValidationError) -> ReaderFailed:
    return ReaderFailed(
        f"{reader.model} did not answer in the form asked for ({wrong.error_count()} {'fault' if wrong.error_count() == 1 else 'faults'}, the first: "
        f"{plain(wrong.errors()[0]['msg'])}). A model that follows a schema is needed to read a datasheet",
        "read with a model that follows a JSON schema",
    )


def in_the_clear(reader: Reader) -> str | None:
    """What to warn of when a key would cross a network unencrypted, or None. A service on
    this machine is reached without leaving it, so plain http is no loss there."""
    address = urllib.parse.urlsplit(reader.url)
    if not reader.key or address.scheme != "http":
        return None
    host = address.hostname or ""
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host == "localhost" or host.endswith(".localhost")
    if local:
        return None
    return (
        f"the key for {reader.url} is sent over plain http, not encrypted: anyone on the way can read it. "
        "Use an https address"
    )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is not followed: the request carries a key, and the address it points to
    did not get that key from the user."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _wait(attempt: int, asked: str | None) -> float:
    """Seconds before the next try: what the service asked for where it said, else doubling."""
    try:
        wanted = float(asked) if asked is not None else None
    except ValueError:
        wanted = None
    if wanted is None or wanted < 0:
        wanted = 0.5 * 2**attempt
    return min(wanted, LONGEST_WAIT)


def _post(reader: Reader, body: dict) -> dict:
    """One request, tried again after a fault that may pass: a rate limit, a fault of the
    service's own, a connection that did not open. Anything else is final at once."""
    request = urllib.request.Request(
        f"{reader.url}/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {reader.key}"} if reader.key else {}),
        },
        method="POST",
    )
    for attempt in range(TRIES):
        last = attempt == TRIES - 1
        try:
            with _OPENER.open(request, timeout=TIMEOUT) as answer:
                raw = answer.read(MAX_ANSWER + 1)
        except urllib.error.HTTPError as refused:
            if refused.code not in (429, 500, 502, 503, 504, 529) or last:
                raise  # with its body unread, for the caller to quote and close
            pause = _wait(attempt, refused.headers.get("Retry-After"))
            refused.close()
        except TimeoutError:
            raise  # ten minutes were given once; they are not given three times
        except (urllib.error.URLError, ConnectionError) as broken:
            if last or isinstance(getattr(broken, "reason", None), TimeoutError):
                raise
            pause = _wait(attempt, None)
        else:
            if len(raw) > MAX_ANSWER:
                raise ReaderFailed(
                    f"{reader.url} answered with more than {MAX_ANSWER // 1_000_000} MB, which no reading of a "
                    "datasheet is: the answer was not read"
                )
            try:
                return json.loads(raw)
            except RecursionError:
                # Nested deeper than any answer is: not read, and said as the service's fault.
                raise ReaderFailed(f"{reader.url} answered with JSON nested too deep to be an answer") from None
        _sleep(pause)
    raise AssertionError("unreachable: the last try returns or raises")


def _content(image_png: bytes | None, text: str) -> str | list[dict]:
    """What the user's turn holds: text, or a picture of a page with the text about it."""
    if image_png is None:
        return text
    import base64

    picture = "data:image/png;base64," + base64.standard_b64encode(image_png).decode("ascii")
    return [{"type": "image_url", "image_url": {"url": picture}}, {"type": "text", "text": text}]


def _said(reader: Reader, answer: object) -> str:
    """The model's words out of a service's answer, or the failure the answer is."""
    try:
        choice = answer["choices"][0]  # type: ignore[index]
        message = choice["message"]
        said = message["content"]
    except (KeyError, IndexError, TypeError):
        raise ReaderFailed(f"{reader.url} answered in a form this tool does not know") from None
    if choice.get("finish_reason") == "content_filter" or (said is None and message.get("refusal")):
        raise declined()
    if choice.get("finish_reason") == "length":
        raise cut_off()
    if isinstance(said, list):  # some services answer in parts
        # Only the parts that are text are words; anything else in a part is not read.
        said = "".join(t for part in said if isinstance(part, dict) and isinstance(t := part.get("text"), str))
    return said if isinstance(said, str) else ""


def _usage(answer: object) -> tuple[int | None, int | None]:
    usage = answer.get("usage") if isinstance(answer, dict) else None
    if not isinstance(usage, dict):
        return None, None
    used = usage.get("prompt_tokens"), usage.get("completion_tokens")
    return used if all(isinstance(n, int) for n in used) else (None, None)


def ask(
    reader: Reader,
    system: str,
    text: str,
    image_png: bytes | None = None,
    shape: type[BaseModel] | None = None,
    ledger: Ledger | None = None,
):
    """One question to a chat-completions service. With `shape`, the answer is that record,
    checked; without, it is the model's text.

    A service is first asked to hold its answer to the record's schema. One that does not
    know how is asked again for plain JSON, the schema being in the instructions as well.
    The question is entered in `ledger` before it is sent, and what it used after.
    """
    warning = in_the_clear(reader)
    if warning:
        warnings.warn(warning, KeyInTheClear, stacklevel=2)
    if ledger is not None:
        ledger.spend("this question")
    body, formats = _question(reader, system, text, image_png, shape)
    failure: Exception | None = None
    for response_format in formats:
        try:
            answer = _post(reader, body if response_format is None else {**body, "response_format": response_format})
        except urllib.error.HTTPError as refused:
            with refused:
                failure = status_failure(reader, refused.code, refused.read(4000), TRIES)
            if refused.code in (400, 404, 422) and response_format is not None:
                continue  # it does not know this way of holding an answer to a shape: try the next
            raise failure from None
        except TimeoutError:
            raise ReaderFailed(
                f"{reader.url} did not answer within {TIMEOUT:g} s", "try again later, or a smaller file"
            ) from None
        except (urllib.error.URLError, ConnectionError) as broken:
            raise no_connection(reader, getattr(broken, "reason", broken), TRIES) from None
        except ValueError:
            raise ReaderFailed(
                f"{reader.url} did not answer in JSON: is it a chat-completions service?",
                "set MOTIONSIM_LLM_URL to the service's chat-completions address, which ends in /v1",
            ) from None
        said = _said(reader, answer)
        if ledger is not None:
            ledger.used(*_usage(answer))
        if shape is None:
            return said
        try:
            return shape.model_validate_json(_json_of(said))
        except ValidationError as wrong:
            raise wrong_form(reader, wrong) from None
    raise failure or ReaderFailed("no answer")


def _question(
    reader: Reader, system: str, text: str, image_png: bytes | None, shape: type[BaseModel] | None
) -> tuple[dict, list[dict | None]]:
    """The body of a question, and the ways of asking for its answer to be held to the
    record's shape, to be tried in turn: the schema itself, then any JSON, then none."""
    if shape is not None:
        system = (
            f"{system}\n\nAnswer with one JSON object and nothing else, matching this JSON schema:\n"
            f"{json.dumps(shape.model_json_schema())}"
        )
    body = {
        "model": reader.model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": _content(image_png, text)}],
    }
    formats: list[dict | None] = [None]
    if shape is not None:
        strict = {"type": "json_schema", "json_schema": {"name": shape.__name__, "schema": shape.model_json_schema()}}
        formats = [strict, {"type": "json_object"}, None]
    return body, formats


def _json_of(said: str) -> str:
    """The JSON in an answer that may have words or a code fence round it."""
    start, end = said.find("{"), said.rfind("}")
    return said[start : end + 1] if 0 <= start < end else said
