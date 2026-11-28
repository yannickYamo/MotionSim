"""The verdict's findings phrased by a language model into one or two plain sentences, where
one is set up: the same environment and the same saved key the datasheet reader uses
(observe/provider.py), a small fast model where the maker has one (Anthropic: Claude Haiku),
a short answer, and the findings as the only facts it is given.

What the model writes is held to the findings: every number in its sentences has to be one
the findings carry, written as they write it, and there are at most two sentences. A phrasing
that fails that is not shown; the deterministic summary stands. Nothing here ever fails a run:
a model that cannot be reached, a key that is refused, an answer cut off, are each a reason
the summary was not phrased, said in a line with every key taken out.

The key goes to its provider alone, through the provider's own library or the
chat-completions request the reader makes; it is never logged and never in an answer.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable

from motionsim.observe import provider

ANTHROPIC_SUMMARY_MODEL = "claude-haiku-5-5"
MAX_TOKENS = 200  # two sentences of some forty words each, with room to spare
TIMEOUT = 30.0  # s: a summary that takes longer is not waited for
LONGEST = 480  # characters of phrased summary at the most
MOST_SENTENCES = 2

SYSTEM = (
    "You write the outcome of a motor-drive control design for an expert drive engineer. You are given "
    "findings worked out by a simulator, as JSON: each is a fact with its numbers, tagged good or improve, "
    "with the setting that moves it (lever) and what moving it does (expect). Write one or two plain "
    "sentences: what is good, then what to optimize and how. Use only the facts in the findings. Every "
    "number you write must appear in the findings exactly as written there, with its unit; do not round, "
    "convert or compute numbers. No preamble, no list, no markdown, no quotation marks."
)

# A number as words write it: digits, a decimal point or comma between digits, a sign.
NUMBER = re.compile(r"(?<![A-Za-z_])[-−+]?\d+(?:[.,]\d+)*")
# A stop that ends a sentence is followed by a space or the end: one inside a number is not.
SENTENCE_END = re.compile(r"[.!?](?=\s|$)")

# A figure as the findings write it: a times sign where it is a factor, a sign where it
# stands alone (a dash after a digit is a range), the digits, and the unit after them. A
# unit is one of these, longest first, and is never followed by a letter.
UNITS = (
    ("kg·m²", "kg·m²"),
    ("N·m", "N·m"),
    ("Nm", "N·m"),
    ("°C", "°C"),
    ("degrees", "°"),
    ("degree", "°"),
    ("deg", "°"),
    ("°", "°"),
    ("MHz", "MHz"),
    ("kHz", "kHz"),
    ("Hz", "Hz"),
    ("dB", "dB"),
    ("rpm", "rpm"),
    ("ms", "ms"),
    ("µs", "µs"),
    ("μs", "µs"),
    ("kW", "kW"),
    ("kV", "kV"),
    ("mA", "mA"),
    ("%", "%"),
    ("W", "W"),
    ("K", "K"),
    ("A", "A"),
    ("V", "V"),
    ("s", "s"),
)
SPACE = "[    ]?"
FIGURE = re.compile(
    r"(?<![\w.,])(?P<times>×)?(?P<sign>(?<![\d)])[-−+])?(?P<digits>\d+(?:[.,]\d+)*)(?P<exp>e[-+]?\d+)?"
    rf"(?:{SPACE}(?P<unit>{'|'.join(re.escape(u) for u, _ in UNITS)})(?![A-Za-z]))?(?![\w.,]\d|\w)"
)
UNIT_OF = dict(UNITS)
# Labels that carry digits but are not figures: a rate as a share of the sampling rate
# (fs/20) and a reciprocal named (1/f_sw, 1/Kp).
LABEL = re.compile(r"\bfs\s*/\s*\d+(?:\.\d+)?(?!\w|\.\d)|(?<![\w.])\d+\s*/\s*[A-Za-z_]\w*")
# A number written as a word, a fraction or a factor: taken only where a finding writes it.
NUMBER_WORD = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|"
    r"fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|"
    r"ninety|hundred|hundreds|thousand|thousands|million|millions|half|halve|halved|halves|halving|"
    r"third|thirds|quarter|quarters|fifth|fifths|tenth|tenths|double|doubled|doubles|doubling|twice|"
    r"thrice|triple|tripled|triples|treble|dozen|dozens|\w+fold|percent|per\s?cent)\b",
    re.IGNORECASE,
)
FRACTION = re.compile("[¼-¾⅐-⅞↉]|\\d\\s*/\\s*\\d")


def figures(text: str) -> tuple[list[tuple[float | str, str, bool]], str]:
    """Every figure in some words, as (value, unit, negative), labels left out; and what is
    left of the words once the figures are taken out."""
    text = LABEL.sub(" ", text)
    found: list[tuple[float | str, str, bool]] = []
    rest: list[str] = []
    at = 0
    for m in FIGURE.finditer(text):
        number = _value(m["digits"])
        if number is None:
            continue
        value: float | str = number
        if m["exp"]:
            value = f"{m['digits']}{m['exp']}"  # taken as written: 6.27e1 is not the 62.7 a finding says
        unit = "×" if m["times"] else UNIT_OF.get(m["unit"] or "", "")
        if m["times"] and m["unit"]:
            unit = "×" + UNIT_OF[m["unit"]]
        found.append((value, unit, (m["sign"] or "") in ("-", "−")))
        rest.append(text[at : m.start()])
        at = m.end()
    rest.append(text[at:])
    return found, "\u0000".join(rest)


def payload(verdict: dict) -> list[dict]:
    """What the model is given of a verdict: the findings' words, and nothing else."""
    out = []
    for f in verdict.get("findings") or []:
        item = {"tag": f.get("tag"), "fact": f.get("said")}
        lever = f.get("lever") or {}
        if lever.get("kind") == "block":
            item["lever"] = f"{lever.get('block')}.{lever.get('param')}: {lever.get('direction')}" + (
                f" to {lever['to']}" if lever.get("to") is not None else ""
            )
        elif lever.get("kind") == "scheme":
            item["lever"] = f"take the scheme {lever.get('to')}"
        elif lever.get("kind") == "design":
            item["lever"] = f"the design's {lever.get('param')}"
        elif lever.get("kind") == "test":
            item["lever"] = f"the test's {lever.get('param')}"
        elif lever.get("kind") == "tuned":
            item["lever"] = "back to the scheme as tuned"
        if f.get("expect"):
            item["expect"] = f["expect"]
        if (f.get("change") or {}).get("said"):
            item["change"] = f"{f['change']['said']} against {f['change'].get('against')}"
        out.append(item)
    return out


def _value(text: str) -> float | None:
    try:
        return float(text.replace("−", "-").replace(",", "").lstrip("+"))
    except ValueError:
        return None


def numbers(text: str) -> list[float]:
    """Every number in some words, as a value."""
    return [v for v in (_value(m) for m in NUMBER.findall(text)) if v is not None]


def sentences(text: str) -> int:
    """How many sentences some words make: the stops that end one, not those inside a number."""
    text = text.strip()
    if not text:
        return 0
    stops = len(SENTENCE_END.findall(text))
    return stops + (0 if text[-1] in ".!?" else 1)


def _labels(text: str) -> set[str]:
    return {re.sub(r"\s+", "", m) for m in LABEL.findall(text)}


def _facts_text(facts: list[dict]) -> str:
    return " | ".join(str(v) for item in facts for v in item.values() if isinstance(v, str))


def _strays(text: str, source: str) -> str | None:
    """Why the figures of some words are not the findings' own (`source`), or None."""
    for label in sorted(_labels(text) - _labels(source)):
        return f"the model wrote {label}, which no finding carries"
    known, _ = figures(source)
    cited, rest = figures(text)
    if FRACTION.search(rest):
        return "the model wrote a fraction, which no finding carries"
    if any(ch.isdigit() for ch in rest):
        return "the model wrote a number glued to letters or in a form no finding writes"
    words = {w.lower() for w in re.findall(r"[\w-]+", source)}
    for m in NUMBER_WORD.finditer(text):
        if m.group(0).lower() not in words:
            return f"the model wrote {m.group(0)!r}, a number no finding writes in words"
    have = set(known)
    for value, unit, negative in cited:
        if (value, unit, negative) not in have:
            sign = "−" if negative else ""
            shown = value if isinstance(value, str) else f"{value:g}"
            return f"the model cited {sign}{shown}{' ' + unit if unit else ''}, which no finding carries"
    return None


def holds(said: str, facts: list[dict]) -> str | None:
    """Why a phrasing cannot be shown, or None where it may: in one or two sentences, short,
    and citing only figures the findings carry, each with its unit and its sign. A number
    written as a word or a fraction, a figure glued to a letter, or a label such as fs/20
    the findings do not carry is a reason it may not: in doubt, the summary stands."""
    text = said.strip()
    if not text:
        return "the model gave no sentence"
    if len(text) > LONGEST or "\n" in text:
        return "the model wrote more than a summary"
    if sentences(text) > MOST_SENTENCES:
        return "the model wrote more than two sentences"
    return _strays(text, _facts_text(facts))


Ask = Callable[[str, str], tuple[str, str]]


def _anthropic(system: str, text: str) -> tuple[str, str]:
    sdk = provider.needs("anthropic", "phrasing the verdict")
    client = sdk.Anthropic(**provider.anthropic_arguments(), timeout=TIMEOUT, max_retries=1)
    response = client.messages.create(
        model=ANTHROPIC_SUMMARY_MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "disabled"},
        system=system,
        messages=[{"role": "user", "content": text}],
    )
    if response.stop_reason == "refusal":
        raise provider.declined("the findings")
    if response.stop_reason == "max_tokens":
        raise provider.cut_off(MAX_TOKENS)
    said = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", "") == "text")
    return said, ANTHROPIC_SUMMARY_MODEL


def _chat(reader: provider.Reader, system: str, text: str) -> tuple[str, str]:
    warning = provider.in_the_clear(reader)
    if warning:
        raise provider.ReaderFailed(warning)
    body = {
        "model": reader.model,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": text}],
    }
    return provider._said(reader, provider._post(reader, body)), reader.model


def ask_model(system: str, text: str) -> tuple[str, str]:
    """One short question to the model the environment sets up: its words and its name."""
    reader = provider.chosen()
    if reader.kind == "anthropic":
        return _anthropic(system, text)
    return _chat(reader, system, text)


def phrase(verdict: dict, ask: Ask | None = None) -> dict:
    """The verdict's summary as the model phrases it, checked, or why it is not:
    {"summary": str | None, "model": str | None, "why": str | None}."""
    facts = payload(verdict)
    if not facts:
        return {"summary": None, "model": None, "why": "there are no findings to phrase"}
    if ask is None:
        if not provider.available():
            return {"summary": None, "model": None, "why": "no language model is set up"}
        ask = ask_model
    try:
        said, model = ask(SYSTEM, json.dumps({"findings": facts}, ensure_ascii=False))
    except Exception as failed:  # a summary never fails a run, whatever the service did
        reason = (
            str(failed) if isinstance(failed, (provider.ReaderFailed, provider.NoReader)) else type(failed).__name__
        )
        return {"summary": None, "model": None, "why": provider.scrub(reason)[: provider.SAID]}
    said = " ".join(str(said).split())
    why = holds(said, facts)
    if why:
        return {"summary": None, "model": model, "why": why}
    return {"summary": said, "model": model, "why": None}


KIND = "control-verdict"  # what the store keeps a phrasing under


def phrased(
    verdict: dict, get: Callable[[str], dict | None], put: Callable[[str, dict], None], ask: Ask | None = None
) -> dict:
    """The verdict with its phrased summary, from the store where the same findings were
    phrased before, else asked for and kept. `get` and `put` reach the store by the verdict's key.
    What the store gives back is held to the findings again, as a fresh phrasing is: one that
    no longer holds is not shown, and is asked for again and replaced."""
    key = verdict["key"]
    kept = get(key)
    if kept and isinstance(kept.get("summary"), str) and holds(kept["summary"], payload(verdict)) is None:
        return {"key": key, "summary": kept["summary"], "model": kept.get("model"), "cached": True, "why": None}
    found = phrase(verdict, ask)
    if found["summary"]:
        put(key, {"summary": found["summary"], "model": found["model"]})
    return {"key": key, **found, "cached": False}
