"""What a typed transistor's figures left empty are taken as (D160): the highest junction
temperature by its kind, the plateau as the threshold plus 2 V, the gate-source charge as 1.4
times the gate-drain charge, and a name by its kind, numbered. Each figure taken is written
into the device with its rule, said with every result, and holds the verdict at a caution.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from motionsim.device.schema import Taken
from motionsim.text import rounded

Figure = Literal["tj_max", "v_plateau", "q_gs"]

# The highest junction temperature a typed part is taken to be rated for where it is left
# empty: the usual rating of its kind. Silicon and silicon carbide transistors are commonly
# rated to 175 °C, GaN transistors to 150 °C.
TJ_MAX_BY_TECHNOLOGY = {"Si MOSFET": 175.0, "SiC MOSFET": 175.0, "GaN HEMT": 150.0}
# The optional figures the form keeps beside the required ones: each is taken by a rule when empty.
DEFAULTED = frozenset({"tj_max", "v_plateau", "q_gs"})
PLATEAU_ABOVE_THRESHOLD = 2.0  # V: the plateau taken where it is left empty, over the threshold
GATE_SOURCE_PER_MILLER = 1.4  # Qgs taken as this times Qgd where it is left empty
# The name a typed part is given where none is typed, by its kind, numbered from 1.
KIND_NAME = {"Si MOSFET": "MOSFET", "SiC MOSFET": "MOSFET", "GaN HEMT": "GaN", "Si IGBT": "IGBT"}


def default_name(technology: str, taken: Callable[[str], bool] = lambda name: False) -> str:
    """The first of "Typed MOSFET 1", "Typed MOSFET 2", ... that is not taken already."""
    kind = KIND_NAME.get(technology, "part")
    n = 1
    while taken(f"Typed {kind} {n}") and n < 10000:
        n += 1
    return f"Typed {kind} {n}"


def taken_for(v: dict[str, float], technology: str) -> list[Taken]:
    """The figures left empty that a stated rule fills: each is written into `v` and said
    with every result, which it caps at a caution."""
    rules: dict[Figure, tuple[str, str, str, Callable[[], float]]] = {
        "tj_max": ("highest junction temperature", "°C", f"the usual rating of a {technology}",
                   lambda: TJ_MAX_BY_TECHNOLOGY[technology]),
        "v_plateau": ("gate plateau voltage", "V", "the threshold voltage plus 2 V",
                      lambda: rounded(v["v_th"] + PLATEAU_ABOVE_THRESHOLD, 6)),
        "q_gs": ("gate-source charge", "nC", "1.4 times the gate-drain charge",
                 lambda: rounded(GATE_SOURCE_PER_MILLER * v["q_gd"], 6)),
    }  # fmt: skip
    out = []
    for figure, (name, unit, rule, value) in rules.items():
        if figure not in v:
            v[figure] = value()
            out.append(Taken(figure=figure, name=name, value=v[figure], unit=unit, rule=rule))
    return out
