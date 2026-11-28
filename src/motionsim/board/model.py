"""A board as every reader hands it over: its copper layers, its parts with their pads, its
tracks, vias and pours, each on a net. Lengths are in millimetres, as the files write them,
with y as the file has it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from motionsim.errors import Refusal
from motionsim.text import whole

# What a board file may hold before it is refused: a power stage's board is far inside these.
MOST_BYTES = 30 * 1024 * 1024  # the file itself, or an archive unpacked
MOST_ITEMS = 2_000_000  # tracks, vias, pads and polygon corners together: what 30 MB of board can hold
MOST_VALUES = 6_000_000  # brackets and values, or elements, in the file's own writing
MOST_DEPTH = 64  # brackets inside brackets; a board file nests under twenty deep
MOST_MEMBERS = 5_000  # files in an archive
MOST_ELEMENTS = 1_500_000  # elements of an IPC-2581 file: one of 30 MB holds under a million
LONGEST_NAME = 80  # characters of a net's, a part's or a layer's name that are kept

# What a stack-up may say before it is taken for a slip of the layout tool and the usual one
# stands in: copper from a thin foil to a heavy busbar layer, and between two copper layers
# from the thinnest prepreg made to a thick core. A loop's inductance goes with the height
# between its layers, so a height of nought would give a confident figure of nearly nothing.
COPPER_RANGE = (0.005, 0.5)  # mm
BETWEEN_RANGE = (0.02, 8.0)  # mm, from one copper's face to the next one's
THICKEST_BOARD = 20.0  # mm

# Where the file has no stack-up: a 1.6 mm board in 1 oz copper, the layers spread evenly.
USUAL_COPPER = 0.035  # mm
USUAL_BOARD = 1.6  # mm

FIX = "give the board as KiCad's .kicad_pcb or as IPC-2581 (.xml or .cvg)"


@dataclass(frozen=True)
class Layer:
    """One copper layer: its name, its copper's thickness and the height of its middle, mm,
    counted downward from the top copper."""

    name: str
    thickness: float
    z: float


@dataclass
class Stackup:
    layers: list[Layer]
    assumed: bool  # true where the file gave no heights and the usual ones stand in
    said: str = ""

    def layer(self, name: str) -> Layer | None:
        return next((layer for layer in self.layers if layer.name == name), None)

    def names(self) -> list[str]:
        return [layer.name for layer in self.layers]


@dataclass(frozen=True)
class Pad:
    """One pad: the part it belongs to, its name on the part, its net, its middle and the
    box around its copper, and the copper layers it is on."""

    ref: str
    name: str
    net: str
    x: float
    y: float
    w: float
    h: float
    layers: tuple[str, ...]
    drill: float = 0.0


@dataclass
class Component:
    ref: str
    value: str
    footprint: str
    x: float
    y: float
    layer: str
    pads: list[Pad] = field(default_factory=list)

    def nets(self) -> set[str]:
        return {pad.net for pad in self.pads if pad.net}

    def on(self, net: str) -> list[Pad]:
        return [pad for pad in self.pads if pad.net == net]


@dataclass(frozen=True)
class Track:
    net: str
    layer: str
    x1: float
    y1: float
    x2: float
    y2: float
    width: float


@dataclass(frozen=True)
class Via:
    net: str
    x: float
    y: float
    size: float
    drill: float
    layers: tuple[str, str]


@dataclass
class Zone:
    """A pour: one outline and the holes cut in it. filled is false where the file held only
    the outline drawn, not the copper poured."""

    net: str
    layer: str
    outline: list[tuple[float, float]]
    holes: list[list[tuple[float, float]]] = field(default_factory=list)
    filled: bool = True


@dataclass
class Board:
    format: str
    name: str
    stackup: Stackup
    components: list[Component] = field(default_factory=list)
    tracks: list[Track] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)
    zones: list[Zone] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def component(self, ref: str) -> Component | None:
        return next((c for c in self.components if c.ref == ref), None)

    def nets(self) -> dict[str, int]:
        """Every net with a pad on it, and how many pads."""
        count: dict[str, int] = {}
        for part in self.components:
            for pad in part.pads:
                if pad.net:
                    count[pad.net] = count.get(pad.net, 0) + 1
        return count


def clean(text: str, most: int = LONGEST_NAME) -> str:
    """A name as it is kept and said: on one line, with nothing in it that is not printed
    (a line end, a tab, a mark that turns the writing round), and no longer than a name is."""
    if len(text) <= most and text.isprintable() and "  " not in text and text == text.strip():
        return text
    kept = " ".join("".join(ch if ch.isprintable() else " " for ch in text[: 8 * most]).split())
    return kept if len(kept) <= most else kept[: most - 1].rstrip() + "…"


class Names:
    """The names of one kind in a file (its nets, or its parts), each cleaned once. Two names
    that differ in the file still differ once cleaned: the later of two that would come out
    the same is given a number, so that cutting a name never joins two nets."""

    def __init__(self) -> None:
        self.given: dict[str, str] = {}
        self.taken: dict[str, str] = {}
        self.changed = 0

    def __call__(self, raw: str) -> str:
        if not raw:
            return ""
        if raw not in self.given:
            name = clean(raw)
            self.changed += name != raw
            n = 1
            while self.taken.get(name, raw) != raw:
                n += 1
                tail = f"~{n}"
                name = clean(raw, LONGEST_NAME - len(tail)) + tail
            self.given[raw], self.taken[name] = name, raw
        return self.given[raw]

    def said(self, what: str) -> str:
        """What to say of the names that were changed, or nothing."""
        if not self.changed:
            return ""
        return (
            f"{self.changed} {what} in the file {'was' if self.changed == 1 else 'were'} longer than "
            f"{LONGEST_NAME} characters or held line ends or other marks that are not printed: "
            f"{'it is' if self.changed == 1 else 'they are'} shown shortened and on one line"
        )


class Budget:
    """How many tracks, vias, pads and polygon corners a file may still hold: counted down as
    they are read, so that a file that stands for millions of corners is refused before they
    are all kept. Only these are counted, the things the figures are worked out from: a
    board's file holds many times as many brackets and values as it holds of them."""

    def __init__(self, name: str, most: int | None = None) -> None:
        self.name, self.most = name, MOST_ITEMS if most is None else most
        self.left = self.most

    def take(self, n: int = 1) -> None:
        self.left -= n
        if self.left < 0:
            raise Refusal(
                f"the board file {self.name} holds more than {whole(self.most)} tracks, vias, pads and polygon "
                "corners, more than the reader takes",
                "give the board of the power stage alone, or its fills at a coarser setting",
                "board",
            )


def spread_stackup(
    names: list[str], board: float = USUAL_BOARD, copper: float = USUAL_COPPER, why: str = ""
) -> Stackup:
    """The stack-up taken where the file gives none, or one no board has: the copper layers
    evenly through the board. why: what was wrong with the file's own, where it had one."""
    names = names or ["F.Cu", "B.Cu"]
    step = (board - copper) / max(len(names) - 1, 1)
    layers = [Layer(name, copper, k * step) for k, name in enumerate(names)]
    said = (
        f"{why or 'no stack-up in the file'}: {len(names)} copper layers of {copper * 1000:g} µm taken evenly "
        f"through a {board:g} mm board"
    )
    return Stackup(layers, True, said)


def implausible(layers: list[Layer]) -> str:
    """What in a stack-up as the file gives it no board has, in words, or nothing: a copper
    thinner or thicker than is made, two layers closer or further apart than a board's are."""
    low, high = COPPER_RANGE
    for layer in layers:
        if not low <= layer.thickness <= high:
            return f"the file's stack-up gives {layer.name} a copper of {layer.thickness:.3g} mm, which no board has"
    low, high = BETWEEN_RANGE
    for upper, lower in zip(layers, layers[1:], strict=False):
        between = (lower.z - lower.thickness / 2) - (upper.z + upper.thickness / 2)
        if not low <= between <= high:
            return (
                f"the file's stack-up puts {between:.3g} mm between {upper.name} and {lower.name}, which no board has"
            )
    if layers and layers[-1].z - layers[0].z > THICKEST_BOARD:
        return f"the file's stack-up is {layers[-1].z - layers[0].z:.3g} mm from its first copper to its last, which no board is"
    return ""
