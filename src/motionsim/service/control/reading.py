"""How a control-lab request is read before anything is worked out from it.

One reader for each kind of field, each refusing by the field's path what is not of its kind:
a name (`name_of`), a list of names (`names_of`), a set of names and values (`set_of`), a list
(`list_of`), and the numbers of service/validate.py. A value of the wrong kind is never passed
on to code that would look it up, add it or walk it.

`shape` is the first thing every address does with a request: it refuses a body nested deeper
than `MOST_DEPTH` (worked out without recursion, so that no nesting can exhaust the stack),
and returns a line for every field the address does not know, at the top or inside the parts
whose fields are fixed (`vary`, `scheme`, `window`), so that a field that was left out is said
to have been left out. The parts that refuse an unknown figure themselves (`scenario`, `shaft`,
`inverter`, `mismatch`) go on doing that.

`budget` is the time a run may take, decided before it starts from the sampling instants it
would go through and what an instant costs: never by a clock.
"""

from __future__ import annotations

import math
from typing import Any

from motionsim.control import scenario
from motionsim.errors import Refusal
from motionsim.text import whole, written

MOST_DEPTH = 24  # levels of nesting in a request: a scheme's block parameters sit at 5
RUN_BUDGET = scenario.RUN_BUDGET  # s one run may take: the default tests are sized to it
COST = scenario.COST  # s a sampling instant costs
SWEEP_BUDGET = 120.0  # s all the runs of a sweep may take together

# `mains`, `front_end`, `c_link` and `brakes` are the front end of a drive fed from the mains: a
# run reads them for the DC link through the test (service/control/linking.py).
COMMON = (
    "motor",
    "conditions",
    "device",
    "load",
    "shaft",
    "application",
    "profile",
    "mission",
    "mains",
    "front_end",
    "c_link",
    "brakes",
    "link_share",
)
RUN = (*COMMON, "scheme", "scenario", "fidelity", "inverter", "mismatch", "plant", "window", "points", "seed")
TOP: dict[str, tuple[str, ...]] = {
    "presets": COMMON,
    "explorations": COMMON,
    "loops": (*COMMON, "scheme"),
    "run": RUN,
    "sweep": (*RUN, "exploration", "vary", "fixed", "reads"),
}
INSIDE: dict[str, tuple[str, ...]] = {
    "vary": ("label", "unit", "path", "values", "schemes", "baseline", "also"),
    "window": ("from", "to"),
    # `tests` is what the presets say of a scheme, sent back with it: read by no run.
    "scheme": ("id", "label", "about", "timing", "actuation", "blocks", "tests", "aside"),
    "scheme.timing": ("update", "delay", "f_control"),
    "scheme.actuation": ("kind", "wires", "period"),
}
BLOCK = ("name", "kind", "inputs", "params", "sources")
# Fields of the main page's own request that a page may send along with a design and that no
# control address reads: left out without a word. `supply` (one-way or battery) is whether the
# supply takes braking energy back, which a control run does not model.
QUIET = ("supply",)


def _kind(value: Any) -> str:
    if value is None:
        return "nothing"
    if isinstance(value, bool):
        return "true or false"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, str):
        return "text"
    return "a list" if isinstance(value, list) else "a set of names and values"


def name_of(value: Any, field: str, choices=None, what: str | None = None) -> str:
    """A name: text, and one of the choices where there are any."""
    what = what or field
    if not isinstance(value, str):
        fix = f"one of {', '.join(choices)}" if choices else "give its name as text"
        raise Refusal(f"{what} is a name, and {_kind(value)} was given", fix, field)
    if choices is not None and value not in choices:
        raise Refusal(f"{what} is one of {', '.join(choices)}", f"one of {', '.join(choices)}", field)
    return value


def list_of(value: Any, field: str, what: str | None = None) -> list:
    if not isinstance(value, list):
        raise Refusal(f"{what or field} is a list, and {_kind(value)} was given", "give a list", field)
    return value


def names_of(value: Any, field: str, what: str | None = None) -> list[str]:
    """A list of names, each text."""
    for k, item in enumerate(list_of(value, field, what)):
        if not isinstance(item, str):
            raise Refusal(
                f"{what or field} is a list of names, and its entry {k + 1} is {_kind(item)}",
                "give each name as text",
                f"{field}[{k}]",
            )
    return list(value)


def set_of(value: Any, field: str, what: str | None = None) -> dict:
    if not isinstance(value, dict):
        raise Refusal(
            f"{what or field} is a set of names and values, and {_kind(value)} was given",
            "give its figures by name",
            field,
        )
    return value


def deep(data: Any) -> None:
    """Refuses a body nested deeper than MOST_DEPTH, by the path where it passes it."""
    stack: list[tuple[Any, str, int]] = [(data, "", 0)]
    while stack:
        value, path, level = stack.pop()
        if level > MOST_DEPTH:
            raise Refusal(
                f"the request is nested more than {MOST_DEPTH} levels deep at {path[:80]}",
                "send the request as the page builds it: nothing in it nests that far",
                path.split(".", 1)[0].split("[", 1)[0],
            )
        if isinstance(value, dict):
            stack += [(v, f"{path}.{k}" if path else str(k), level + 1) for k, v in value.items()]
        elif isinstance(value, list):
            stack += [(v, f"{path}[{k}]", level + 1) for k, v in enumerate(value)]


# Where a figure that is looked for in the wrong place really lives.
ELSEWHERE = {
    "noise": "the noise on the sampled currents is the `noise` of the scheme's current_sampling block "
    "(scheme.blocks.<its name>.params.noise), and its seed is `seed`, at the top of the request",
}


def _lives(name: str, value: Any, top: tuple[str, ...]) -> str:
    """Where a field the address does not know here is really given, where that is known: a
    figure of a block, or a field of the request's top put inside another part."""
    if name in ELSEWHERE:
        return ELSEWHERE[name]
    found = [name] if name in top else [str(k) for k in value if k in top] if isinstance(value, dict) else []
    if not found:
        return ""
    return f"{', '.join(f'`{k}`' for k in found)} {'is a field' if len(found) == 1 else 'are fields'} at the top of the request"


def _left_out(held: dict, names: list[str], where: str, known: tuple[str, ...], top: tuple[str, ...]) -> list[str]:
    out = []
    for name in names:
        line = (
            f"the request's {where}{name} is not a field {'of this address' if not where else 'there'} and was left "
            f"out: {where or 'the address'} takes {', '.join(known)}"
        )
        lives = _lives(name, held.get(name), top)
        out.append(f"{line}; {lives}" if lives else line)
    return out


def shape(route: str, data: dict) -> list[str]:
    """The request's nesting checked, and a line for each field the address does not know,
    with where it really lives where that is known."""
    deep(data)
    known = TOP[route]
    notes = _left_out(data, [str(k) for k in data if k not in known and k not in QUIET], "", known, known)
    for part, fields in INSIDE.items():
        held: Any = data
        for key in part.split("."):
            held = held.get(key) if isinstance(held, dict) else None
        if part.split(".")[0] in known and isinstance(held, dict):
            notes += _left_out(held, [str(k) for k in held if k not in fields], f"{part}.", fields, known)
    scheme = data.get("scheme") if "scheme" in known else None
    blocks = scheme.get("blocks") if isinstance(scheme, dict) else None
    for k, block in enumerate(blocks if isinstance(blocks, list) else []):
        if isinstance(block, dict):
            notes += _left_out(block, [str(n) for n in block if n not in BLOCK], f"scheme.blocks[{k}].", BLOCK, known)
    return notes


def noted(answer: dict, notes: list[str]) -> dict:
    """The answer with what was left out of the request said in its `taken`."""
    if notes or "taken" not in answer:
        answer["taken"] = [*answer.get("taken", []), *notes]
    return answer


def seconds(instants: int, actuation: str) -> float:
    """What a run of so many sampling instants is reckoned to take."""
    return instants * COST[actuation]


def over(needed: float, most: float, instants: int, what: str) -> Refusal:
    return Refusal(
        f"this would take longer than {most:g} s: {what} {whole(instants)} sampling instants, about "
        f"{written(math.ceil(needed), 3)} s",
        "shorten the test or lower the sampling rate",
        "scenario.duration",
    )
