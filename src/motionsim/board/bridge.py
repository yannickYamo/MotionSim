"""Finding the half bridges on a board from its nets: which two nets are the supply, which
parts are the switches, which net is each switch node and which capacitors close each loop.

A commutation loop runs from a decoupling capacitor's positive pad through the high-side
switch, the switch node and the low-side switch back to the capacitor's negative pad. So the
supply is looked for as two nets joined by capacitors (parts on those two nets only) and by
two transistor-like parts in series through a third net. Names help to tell plus from minus
and are never relied on alone. What the user names is always taken over the guess.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from motionsim.board.model import Board, Component, Pad
from motionsim.board.values import MINUS, PLUS, capacitance, reads_as_ohms
from motionsim.errors import Refusal

MOST_CAPACITORS = 8  # taken for one leg's loop
# What to do about a loop that was not found, or not found as wanted, in words that hold on
# the page and for a program alike. Which choice is meant is the refusal's field: "choose" for
# the lot, "choose.dc_plus" and the like for one (the names are set out in motionsim.board.CHOICES).
HOW = (
    "choose them yourself: the two supply nets, the switch node, the switches of each side and the "
    "capacitors, by the names the board gives them"
)


class Hint(str):
    """A caution that can be answered by a choice: the words, and which choice it is
    (a name of motionsim.board.CHOICES). It is said as any caution is."""

    field: str

    def __new__(cls, said: str, field: str) -> Hint:
        hint = super().__new__(cls, said)
        hint.field = field
        return hint


def shown(name: object) -> str:
    """A name as the user gave it, for a refusal: cut to what a line holds, and in quotes."""
    return repr(str(name)[:40])


NOT_A_CAPACITOR = re.compile(r"^(R|D|L|F|FB|TVS|RV|J|P|TP|JP|SW|LED)\d", re.IGNORECASE)


@dataclass
class Leg:
    """One half bridge: its switch node, its switches, the parts in series with them on the
    way to the supply (a current-sense resistor), and the capacitors taken for its loop."""

    switch_node: str
    high_side: list[str]
    low_side: list[str]
    series: list[str] = field(default_factory=list)
    capacitors: list[str] = field(default_factory=list)
    low_net: str = ""  # the net the low side's source is on: the supply's minus, or the shunt's top


@dataclass
class Found:
    dc_plus: str
    dc_minus: str
    legs: list[Leg]
    candidates: dict
    said: list[str] = field(default_factory=list)


def _wanted(choose: dict, key: str, many: bool):
    """What the user named under one key: text, or a list of text."""
    value = choose.get(key)
    if value in (None, "", []):
        return [] if many else None
    values = value if isinstance(value, list) else [value]
    if not all(isinstance(v, str) and v for v in values) or (not many and len(values) != 1):
        what = "a list of names" if many else "one name"
        raise Refusal(
            f"what was chosen as {WHAT.get(key, key)} has to be {what}",
            "give each as the board names it: a net by its name, a part by its reference designator",
            f"choose.{key}",
        )
    return values if many else values[0]


# Each choice in a person's words, for a refusal about it.
WHAT = {
    "dc_plus": "the supply's positive net",
    "dc_minus": "the supply's negative net",
    "switch_nodes": "the switch nodes",
    "high_side": "the high-side switches",
    "low_side": "the low-side switches",
    "capacitors": "the capacitors",
    "gate_driver": "the gate drivers",
    "leg": "the leg",
}


class _Board:
    """The board's nets as the search needs them: which parts are on each net."""

    def __init__(self, board: Board) -> None:
        self.board = board
        self.parts = {part.ref: part for part in board.components}
        self.on: dict[str, list[Component]] = defaultdict(list)
        for part in board.components:
            for net in part.nets():
                self.on[net].append(part)
        self.pads = board.nets()

    def two_net(self, part: Component) -> bool:
        return len(part.nets()) == 2

    def switch_like(self, part: Component, named: frozenset = frozenset()) -> bool:
        """Three or four nets, as a transistor has (drain, source, gate, and a Kelvin source),
        or a diode by its name: a diode is the other switch of a leg that has one transistor.
        A driver or a controller has more nets; one the user names is taken whatever it has."""
        if part.ref in named:
            return True
        return 3 <= len(part.nets()) <= 4 or (self.two_net(part) and part.ref[:1].upper() == "D")

    def capacitor_like(self, part: Component) -> bool:
        """On two nets, and nothing says it is something else: not its name, not a value in ohms."""
        return self.two_net(part) and not NOT_A_CAPACITOR.match(part.ref) and not reads_as_ohms(part.value)

    def between(self, a: str, b: str) -> list[Component]:
        return [part for part in self.on.get(a, []) if b in part.nets()]

    def net(self, name: str, key: str) -> str:
        if name not in self.on:
            near = sorted(self.on, key=lambda n: (n.lower() != name.lower(), n))[:6]
            raise Refusal(
                f"the board has no net called {shown(name)} with a part on it",
                f"its nets include {', '.join(near)}",
                f"choose.{key}",
            )
        return name

    def part(self, ref: str, key: str) -> Component:
        if ref not in self.parts:
            raise Refusal(
                f"the board has no part called {shown(ref)}",
                "give the reference designator as the board has it",
                f"choose.{key}",
            )
        return self.parts[ref]

    def twice(self) -> list[str]:
        """The references more than one part has, where one of those parts is on two nets
        or more and so could be in a loop: such parts cannot be told apart by name."""
        count = Counter(part.ref for part in self.board.components)
        return sorted({part.ref for part in self.board.components if count[part.ref] > 1 and len(part.nets()) >= 2})


def _legs(b: _Board, plus: str, minus: str, named: frozenset = frozenset()) -> list[Leg]:
    """Every net a switch joins to plus and another switch joins to minus, straight or
    through one two-pad part that is not a capacitor (a shunt). A part with a pad on the
    other supply net too is no switch of a leg (a regulator has all three)."""
    lows: dict[str, list[str]] = {minus: []}  # the supply's minus first, then the net over each shunt
    for shunt in b.on.get(minus, []):
        if b.two_net(shunt) and shunt.ref[:1].upper() == "R" and NOT_A_CAPACITOR.match(shunt.ref):
            (top,) = shunt.nets() - {minus}
            if top != plus:
                lows.setdefault(top, []).append(shunt.ref)
    legs = []
    for node in sorted(b.on):
        if node in (plus, minus):
            continue
        high = [p.ref for p in b.between(plus, node) if b.switch_like(p, named) and (p.ref in named or not p.on(minus))]
        for low_net, shunts in lows.items():
            low = [p.ref for p in b.between(node, low_net) if _low_switch(b, p, plus, minus, low_net, named)]
            if high and low and any(len(b.parts[r].nets()) >= 3 for r in high + low):
                legs.append(Leg(node, high, low, list(shunts), low_net=low_net))
                break
    return legs


def _low_switch(b: _Board, part: Component, plus: str, minus: str, low_net: str, named: frozenset) -> bool:
    """Whether a part between a switch node and the low net is the low-side switch: over a
    shunt, only a transistor with no pad on minus itself (a gate's pull-down resistor also
    hangs a net off minus, and the gate is not the source)."""
    if part.ref in named:
        return True
    if not b.switch_like(part) or part.on(plus):
        return False
    return len(part.nets()) >= 3 and not part.on(minus) if low_net != minus else True


def _biggest_on(part: Component) -> str:
    return max(part.pads, key=lambda pad: pad.w * pad.h).net


def _orient(b: _Board, a: str, c: str) -> tuple[str, str, str]:
    """Which of two supply nets is plus: by their names; else by where the switches' largest
    pads are (a transistor's tab is its drain: on plus for the high side, on the switch node
    for the low side); else the net with more pads on it is taken as minus."""
    score = bool(PLUS.search(a)) + bool(MINUS.search(c)) - bool(PLUS.search(c)) - bool(MINUS.search(a))
    if score:
        return (a, c, "") if score > 0 else (c, a, "")
    tabs = 0
    for plus, minus, sign in ((a, c, 1), (c, a, -1)):
        for leg in _legs(b, plus, minus):
            tabs += sign * sum(_biggest_on(b.parts[r]) == plus for r in leg.high_side if len(b.parts[r].nets()) >= 3)
            tabs += sign * sum(
                _biggest_on(b.parts[r]) == leg.switch_node for r in leg.low_side if len(b.parts[r].nets()) >= 3
            )
    if tabs:
        said = "which supply net is plus was told from the switches' largest pads (their drains), not from the names"
        return (a, c, said) if tabs > 0 else (c, a, said)
    said = Hint(
        "which supply net is plus could not be told: the one with more pads on it was taken as minus. "
        "Choose the supply nets yourself if it is the other way round",
        "dc_plus",
    )
    return (a, c, said) if b.pads.get(c, 0) >= b.pads.get(a, 0) else (c, a, said)


def _rails(b: _Board) -> list[dict]:
    """Every pair of nets that could be the supply, the likeliest first: joined by the most
    legs, then by the most capacitors."""
    joined: Counter = Counter()
    for part in b.board.components:
        if b.capacitor_like(part):
            joined[frozenset(part.nets())] += 1
    out = []
    for pair, count in joined.most_common(40):
        a, c = sorted(pair)
        plus, minus, said = _orient(b, a, c)
        legs = _legs(b, plus, minus)
        if legs:
            out.append({"dc_plus": plus, "dc_minus": minus, "capacitors": count, "legs": len(legs), "said": said})
    return sorted(out, key=lambda rail: (-rail["legs"], -rail["capacitors"]))


def _looked_for(b: _Board) -> Refusal:
    switches = sum(len(part.nets()) >= 3 for part in b.board.components)
    return Refusal(
        "no half bridge was found on this board: looked for two nets joined by a capacitor and by two "
        f"transistor-like parts in series through a third net, among {len(b.on)} nets and {switches} parts of "
        "three nets or more",
        HOW,
        "choose",
    )


def _gap(a: Pad, b: Pad) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _nearest(b: _Board, leg: Leg, plus: str, minus: str, pool: list[Component]) -> list[tuple[float, str]]:
    """Each capacitor's way round this leg, mm: from its plus pad to the nearest high-side
    switch and from the nearest low-side switch back to its minus pad."""
    top = [pad for ref in leg.high_side for pad in b.parts[ref].on(plus)]
    bottom = [pad for ref in leg.low_side for pad in b.parts[ref].on(leg.low_net)]
    bottom = [pad for ref in leg.series for pad in b.parts[ref].on(minus)] or bottom
    if not top or not bottom:
        # Kept out by the checks on what was chosen; said in words should anything slip by them.
        raise Refusal(
            f"the switches taken for the leg at {leg.switch_node} do not reach from {plus} to {minus}",
            HOW,
            "choose.high_side" if not top else "choose.low_side",
        )
    out = []
    for cap in pool:
        there = min(_gap(p, q) for p in cap.on(plus) for q in top)
        back = min(_gap(p, q) for p in cap.on(minus) for q in bottom)
        out.append((there + back, cap.ref))
    return sorted(out)


def _capacitors(b: _Board, found: Found, choose: dict) -> None:
    plus, minus = found.dc_plus, found.dc_minus
    named = [b.part(ref, "capacitors") for ref in _wanted(choose, "capacitors", True)]
    for cap in named:
        if not (cap.on(plus) and cap.on(minus)):
            raise Refusal(
                f"{cap.ref} is not across {plus} and {minus}",
                "choose capacitors that are on both supply nets",
                "choose.capacitors",
            )
    pool = named or [p for p in b.between(plus, minus) if b.capacitor_like(p)]
    if not pool:
        raise Refusal(
            f"no decoupling capacitor was found across {plus} and {minus}: looked for a part on those two nets only",
            HOW,
            "choose.capacitors",
        )
    for leg in found.legs:
        ranked = _nearest(b, leg, plus, minus, pool)
        reach = max(1.5 * ranked[0][0], ranked[0][0] + 10.0)
        leg.capacitors = [ref for way, ref in ranked if named or way <= reach][:MOST_CAPACITORS]
        if len(leg.capacitors) < len(ranked) and not named:
            found.said.append(
                Hint(
                    f"{leg.switch_node}: {len(leg.capacitors)} of {len(ranked)} capacitors across the supply were "
                    "taken for the loop, the nearest by the way round it. Others can be chosen",
                    "capacitors",
                )
            )
    found.candidates["capacitors"] = [
        {"ref": p.ref, "value": p.value, "farads": capacitance(p.value)}
        for p in b.between(plus, minus)
        if b.capacitor_like(p)
    ]


def _named_switches(b: _Board, legs: list[Leg], plus: str, choose: dict) -> list[Leg]:
    """The legs with the switches the user named in place of those guessed."""
    high = [b.part(ref, "high_side") for ref in _wanted(choose, "high_side", True)]
    low = [b.part(ref, "low_side") for ref in _wanted(choose, "low_side", True)]
    for part in high:
        if part in low:
            raise Refusal(
                f"{part.ref} was chosen for both sides: a switch is on the high side or on the low side",
                "choose another switch for one of the two sides",
                "choose.low_side",
            )
        if not part.on(plus):
            raise Refusal(
                f"{part.ref} has no pad on {plus}, so it is not a high-side switch",
                f"choose a part with a pad on {plus} for the high side",
                "choose.high_side",
            )
    if not high and not low:
        return legs
    kept = []
    for leg in legs:
        mine_high = [p.ref for p in high if leg.switch_node in p.nets()]
        # A low-side switch reaches from the switch node to the net the leg comes down to.
        mine_low = [p.ref for p in low if leg.switch_node in p.nets() and p.on(leg.low_net)]
        if (high and not mine_high) or (low and not mine_low):
            continue
        leg.high_side, leg.low_side = mine_high or leg.high_side, mine_low or leg.low_side
        kept.append(leg)
    if not kept:
        raise Refusal(
            "the switches chosen do not make a leg: no switch node has one of them from the supply's plus "
            "and another to its minus",
            "choose for the high side a switch between plus and the switch node, and for the low side one "
            "between the switch node and minus",
            "choose.high_side" if high else "choose.low_side",
        )
    return kept


def _sides(b: _Board, plus: str, minus: str, legs: list[Leg]) -> tuple[dict, dict]:
    """For each leg, the switches that can be on each of its sides: those found there, and
    those taken, which the user may have named."""
    guessed = {leg.switch_node: leg for leg in _legs(b, plus, minus)}
    high, low = {}, {}
    for leg in legs:
        there = guessed.get(leg.switch_node)
        high[leg.switch_node] = list(dict.fromkeys([*(there.high_side if there else []), *leg.high_side]))
        low[leg.switch_node] = list(dict.fromkeys([*(there.low_side if there else []), *leg.low_side]))
    return high, low


def find(board: Board, choose: dict | None = None) -> Found:
    """The supply, the legs and the capacitors of each leg, with what else could have been taken."""
    choose = choose or {}
    if not isinstance(choose, dict):
        raise Refusal("what was chosen is not a set of names and values", HOW, "choose")
    b = _Board(board)
    if twice := b.twice():
        raise Refusal(
            f"more than one part of this board is called {', '.join(twice[:5])}"
            + (f" (and {len(twice) - 5} more names are shared too)" if len(twice) > 5 else "")
            + ": parts that share a name cannot be told apart, so no loop is worked out",
            "give every part a reference designator of its own in the layout tool, and give the file again",
            "board",
        )
    plus, minus = _wanted(choose, "dc_plus", False), _wanted(choose, "dc_minus", False)
    rails = _rails(b)
    said = []
    if plus is None or minus is None:
        fits = [r for r in rails if plus in (None, r["dc_plus"]) and minus in (None, r["dc_minus"])]
        if not fits:
            raise _looked_for(b)
        plus, minus = fits[0]["dc_plus"], fits[0]["dc_minus"]
        said += [fits[0]["said"]] if fits[0]["said"] else []
        if len(fits) > 1:
            said.append(
                Hint(
                    f"{len(fits)} pairs of nets could be the supply: {plus} and {minus} were taken, joined by the "
                    "most legs. Another pair can be chosen",
                    "dc_plus",
                )
            )
    plus, minus = b.net(plus, "dc_plus"), b.net(minus, "dc_minus")
    named = frozenset(_wanted(choose, "high_side", True) + _wanted(choose, "low_side", True))
    legs = _legs(b, plus, minus, named)
    nodes = [b.net(n, "switch_nodes") for n in _wanted(choose, "switch_nodes", True)]
    legs = [leg for leg in legs if leg.switch_node in nodes] if nodes else legs
    if not legs:
        raise Refusal(
            f"no leg was found between {plus} and {minus}"
            + (f" at {', '.join(nodes)}" if nodes else "")
            + ": looked for one switch from plus to a switch node and another from there to minus",
            HOW,
            "choose.switch_nodes" if nodes else "choose",
        )
    legs = _named_switches(b, legs, plus, choose)
    switches = sorted({ref for leg in _legs(b, plus, minus) for ref in leg.high_side + leg.low_side})
    candidates: dict = {"rails": [{k: v for k, v in r.items() if k != "said"} for r in rails[:6]]}
    candidates |= {"switch_nodes": [leg.switch_node for leg in _legs(b, plus, minus)], "switches": switches}
    found = Found(plus, minus, legs, candidates, said)
    _capacitors(b, found, choose)
    candidates["high_side"], candidates["low_side"] = _sides(b, plus, minus, legs)
    return found
