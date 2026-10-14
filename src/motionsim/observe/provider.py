"""Which language model reads a datasheet, and how it is asked.

Anthropic's models are asked through Anthropic's own library. Every other maker's, and a
model run on your own machine, is asked through the chat-completions interface they have in
common: OpenAI, Google's Gemini, xAI's Grok, and local servers such as Ollama, vLLM and
llama.cpp all speak it. The choice is made from the environment, so no key is ever written
into a file:

- MOTIONSIM_LLM_URL: the address of a chat-completions service, yours or anyone's. With it,
  MOTIONSIM_LLM_MODEL names the model, and MOTIONSIM_LLM_KEY is its key where it wants one.
- ANTHROPIC_API_KEY: Anthropic, with the model this tool was built and checked on.
- OPENAI_API_KEY, GEMINI_API_KEY or XAI_API_KEY: that maker's service, with
  MOTIONSIM_LLM_MODEL naming the model.

The first that is set, in that order, is the one used. Whatever reads, the same checks hold
every value to the page it was cited from: a weaker reader is set aside more often, not
believed more.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

ANTHROPIC_MODEL = "claude-opus-5-5"
TIMEOUT = 600.0  # s; a long datasheet takes a model some minutes

# A maker's key in the environment, and the address its chat-completions service answers at.
SERVICES = (
    ("OPENAI_API_KEY", "https://api.openai.com/v1"),
    ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai"),
    ("XAI_API_KEY", "https://api.x.ai/v1"),
)


class NoReader(RuntimeError):
    """No language model is set up to read with, or the one set up is not fully named."""


class ReaderFailed(RuntimeError):
    """The model was reached and did not give an answer that can be used."""


@dataclass(frozen=True)
class Reader:
    kind: str  # "anthropic", or "chat" for the interface the others share
    model: str
    url: str = ""
    key: str = ""

    @property
    def name(self) -> str:
        """What is recorded beside a reading, so a result can say what read it."""
        return self.model


def _named(env: dict) -> str:
    model = env.get("MOTIONSIM_LLM_MODEL", "").strip()
    if not model:
        raise NoReader(
            "a language model is set up to read with, and MOTIONSIM_LLM_MODEL does not say which model: "
            "set it to the name its service knows the model by"
        )
    return model


def chosen(env: dict | None = None) -> Reader:
    """The reader the environment sets up. Raises NoReader with what to set where none is."""
    env = os.environ if env is None else env
    url = env.get("MOTIONSIM_LLM_URL", "").strip().rstrip("/")
    if url:
        return Reader("chat", _named(env), url, env.get("MOTIONSIM_LLM_KEY", "").strip())
    if env.get("ANTHROPIC_API_KEY"):
        return Reader("anthropic", ANTHROPIC_MODEL)
    for variable, address in SERVICES:
        if env.get(variable):
            return Reader("chat", _named(env), address, env[variable].strip())
    raise NoReader(
        "reading a datasheet needs a language model, and none is set up: set ANTHROPIC_API_KEY, or "
        "OPENAI_API_KEY, GEMINI_API_KEY or XAI_API_KEY with MOTIONSIM_LLM_MODEL, or MOTIONSIM_LLM_URL "
        "and MOTIONSIM_LLM_MODEL for a model of your own"
    )


def available(env: dict | None = None) -> bool:
    try:
        chosen(env)
    except NoReader:
        return False
    return True


def _post(reader: Reader, body: dict) -> dict:
    request = urllib.request.Request(
        f"{reader.url}/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {reader.key}"} if reader.key else {}),
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
        return json.loads(answer.read())


def _content(image_png: bytes | None, text: str):
    """What the user's turn holds: text, or a picture of a page with the text about it."""
    if image_png is None:
        return text
    import base64

    picture = "data:image/png;base64," + base64.standard_b64encode(image_png).decode("ascii")
    return [{"type": "image_url", "image_url": {"url": picture}}, {"type": "text", "text": text}]


def ask(reader: Reader, system: str, text: str, image_png: bytes | None = None, shape: type[BaseModel] | None = None):
    """One question to a chat-completions service. With `shape`, the answer is that record,
    checked; without, it is the model's text.

    A service is first asked to hold its answer to the record's schema. One that does not
    know how is asked again for plain JSON, the schema being in the instructions as well.
    """
    if shape is not None:
        system = (
            f"{system}\n\nAnswer with one JSON object and nothing else, matching this JSON schema:\n"
            f"{json.dumps(shape.model_json_schema())}"
        )
    body = {
        "model": reader.model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": _content(image_png, text)}],
    }
    formats = [None]
    if shape is not None:
        strict = {"type": "json_schema", "json_schema": {"name": shape.__name__, "schema": shape.model_json_schema()}}
        formats = [strict, {"type": "json_object"}, None]
    failure: Exception | None = None
    for response_format in formats:
        try:
            answer = _post(reader, body if response_format is None else {**body, "response_format": response_format})
        except urllib.error.HTTPError as refused:
            detail = refused.read().decode(errors="replace")[:300]
            failure = ReaderFailed(f"{reader.url} answered {refused.code}: {detail}")
            if refused.code in (400, 404, 422) and response_format is not None:
                continue  # it does not know this way of holding an answer to a shape: try the next
            raise failure from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as broken:
            raise ReaderFailed(f"{reader.url} could not be reached or did not answer in JSON: {broken}") from None
        try:
            said = answer["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise ReaderFailed(f"{reader.url} answered in a form this tool does not know") from None
        if isinstance(said, list):  # some services answer in parts
            said = "".join(part.get("text", "") for part in said if isinstance(part, dict))
        if shape is None:
            return said or ""
        try:
            return shape.model_validate_json(_json_of(said or ""))
        except ValidationError as wrong:
            raise ReaderFailed(
                f"{reader.model} did not answer in the form asked for ({wrong.error_count()} faults, the first: "
                f"{wrong.errors()[0]['msg']}). A model that follows a schema is needed to read a datasheet"
            ) from None
    raise failure or ReaderFailed("no answer")


def _json_of(said: str) -> str:
    """The JSON in an answer that may have words or a code fence round it."""
    start, end = said.find("{"), said.rfind("}")
    return said[start : end + 1] if 0 <= start < end else said
