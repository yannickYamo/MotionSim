"""Finding a switch's gate drive from the nets: the driver, the resistors between its output
and the gate, and the net the gate current returns on, which is the switch's own source or a
separate Kelvin source pad.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from motionsim.board.bridge import NOT_A_CAPACITOR, Found, Leg, _wanted, shown
from motionsim.board.mesh import Link
from motionsim.board.model import Board, Component
from motionsim.board.values import GATE, KELVIN, capacitance, reads_as_ohms
from motionsim.errors import Refusal

MOST_LINKS = 12  # of one part's body, between its pads on two nets


@dataclass
class Drive:
    switch: str
    driver: str
    gate_net: str
    return_net: str
    kelvin: bool
    resistors: list[str]
    nets: list[str]
    links: list[Link] = field(default_factory=list)
    said: str = ""


def pairs(part: Component, net_a: str, net_b: str, emf: bool = False) -> list[Link]:
    """A part's body between its pads on two nets: from each pad on the second net to the
    nearest on the first."""
    out, seen = [], set()
    for b in part.on(net_b)[:MOST_LINKS]:
        a = min(part.on(net_a), key=lambda pad: math.hypot(pad.x - b.x, pad.y - b.y), default=None)
        if a is not None and (a.name, a.x, a.y, b.name, b.x, b.y) not in seen:
            seen.add((a.name, a.x, a.y, b.name, b.x, b.y))
            out.append(Link(part.ref, a, b, emf))
    return out


def power_links(board: Board, found: Found, leg: Leg) -> tuple[list[str], list[Link]]:
    """The nets and the bodies of one leg's commutation loop."""
    part = board.component
    links: list[Link] = []
    for ref in leg.capacitors:
        links += pairs(part(ref), found.dc_minus, found.dc_plus, emf=True)  # type: ignore[arg-type]
    for ref in leg.high_side:
        links += pairs(part(ref), found.dc_plus, leg.switch_node)  # type: ignore[arg-type]
    for ref in leg.low_side:
        links += pairs(part(ref), leg.switch_node, leg.low_net)  # type: ignore[arg-type]
    for ref in leg.series:
        links += pairs(part(ref), leg.low_net, found.dc_minus)  # type: ignore[arg-type]
    return list(dict.fromkeys([found.dc_plus, leg.switch_node, leg.low_net, found.dc_minus])), links


def _rank(switch: Component, net: str) -> tuple:
    """Which of a switch's other nets is its gate: the one named as a gate first, the one
    named as a Kelvin source last."""
    names = " ".join(pad.name for pad in switch.on(net))
    kelvin = bool(KELVIN.search(net) or KELVIN.search(names))
    gate = bool(GATE.search(net) or GATE.search(names))
    return (kelvin, not gate, net)


def _ways(
    parts: dict[str, list[Component]], switch: Component, gate: str, source: str
) -> list[tuple[str, list[Component]]]:
    """Where the gate net leads: itself, and the far net of each two-pad part on it that is
    not a capacitor and does not go to the source (a pull-down)."""
    far: dict[str, list[Component]] = {}
    for part in parts.get(gate, []):
        in_series = NOT_A_CAPACITOR.match(part.ref) or reads_as_ohms(part.value)
        if part is switch or len(part.nets()) != 2 or not in_series or capacitance(part.value) is not None:
            continue
        (other,) = part.nets() - {gate}
        if other != source and other not in switch.nets():
            far.setdefault(other, []).append(part)
    return [(gate, []), *far.items()]


def find_drive(board: Board, found: Found, leg: Leg, ref: str, choose: dict) -> Drive | str:
    """The gate drive of one switch, or in words why none was found."""
    switch = board.component(ref)
    assert switch is not None
    high = ref in leg.high_side
    source = leg.switch_node if high else leg.low_net
    power = {found.dc_plus, found.dc_minus, leg.switch_node, leg.low_net}
    others = sorted(switch.nets() - power, key=lambda net: _rank(switch, net))
    if not others:
        return f"{ref} has no pad beside its power pads: no gate to drive"
    wanted = _wanted(choose, "gate_driver", True)
    for name in wanted:
        if board.component(name) is None:
            raise Refusal(
                f"the board has no part called {shown(name)}",
                "give the gate driver's reference designator",
                "choose.gate_driver",
            )
    switches = {r for each in found.legs for r in each.high_side + each.low_side}
    on: dict[str, list[Component]] = {}
    for part in board.components:
        for net in part.nets():
            on.setdefault(net, []).append(part)
    for gate in others:
        for end, series in _ways(on, switch, gate, source):
            for driver in on.get(end, []):
                fits = driver.ref in wanted if wanted else len(driver.nets()) >= 3 and driver.ref not in switches
                kelvin = next((k for k in others if k != gate and driver.on(k)), None)
                back = kelvin or (source if driver.on(source) else None)
                if not fits or back is None or driver is switch:
                    continue
                drive = Drive(
                    ref,
                    driver.ref,
                    gate,
                    back,
                    kelvin is not None,
                    [p.ref for p in series],
                    list(dict.fromkeys([end, gate, back])),
                )
                drive.links = pairs(driver, back, end, emf=True)[:1]
                for resistor in series:
                    drive.links += pairs(resistor, end, gate)
                drive.links += pairs(switch, back, gate)[:1]
                if len(others) > 1 and not kelvin:
                    drive.said = f"{ref} has {len(others)} pads beside its power pads: {gate} was taken as its gate"
                return drive
    looked = ", ".join(others)
    return (
        f"no gate driver was found for {ref}: looked on {looked} for a part of three nets or more that also has a "
        f"pad on {source}, the gate current's way back. The gate driver can be chosen by its reference designator"
    )
