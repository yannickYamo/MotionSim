"""A KiCad board file (.kicad_pcb, versions 6 to 9) read into a Board.

Taken: the stack-up (setup/stackup) where the file has one; nets; footprints with their
reference, value and pads; track segments and arcs; vias; zones with their filled polygons.
Not taken: text, graphics, keep-out areas, pads of custom shape beyond the box around them,
and the teardrops and thermal spokes a fill does not already hold.
"""

from __future__ import annotations

import math

from motionsim.board import sexpr
from motionsim.board.model import (
    USUAL_BOARD,
    USUAL_COPPER,
    Board,
    Budget,
    Component,
    Layer,
    Names,
    Pad,
    Stackup,
    Track,
    Via,
    Zone,
    clean,
    implausible,
    spread_stackup,
)
from motionsim.board.sexpr import Node, child, children, head, numbers, words
from motionsim.errors import Refusal

ARC_STEP = math.radians(10)  # an arc is drawn as chords no longer than this


def _copper_names(root: Node) -> list[str]:
    """The copper layers in the order they lie: front, the inner ones by number, back."""
    names = [w[1] for layer in (child(root, "layers") or []) if isinstance(layer, list) and len(w := layer) > 1]
    # KiCad's own names for copper, which hold nothing that is not printed: any other is no layer.
    copper = [n for n in dict.fromkeys(names) if isinstance(n, str) and n.endswith(".Cu") and clean(n) == n]
    inner = sorted(
        (n for n in copper if n not in ("F.Cu", "B.Cu")), key=lambda n: int("".join(filter(str.isdigit, n)) or 0)
    )
    return [n for n in ["F.Cu"] if n in copper] + inner + [n for n in ["B.Cu"] if n in copper]


def _stackup(root: Node, name: str) -> Stackup:
    names = _copper_names(root)
    general = child(root, "general")
    thick = numbers(child(general, "thickness") if general else None, name, "the board's thickness")
    board = thick[0] if thick and 0.05 <= thick[0] <= 20 else USUAL_BOARD
    given = child(child(root, "setup") or [], "stackup")
    if given is None:
        return spread_stackup(names, board)
    layers, z, guessed = [], 0.0, []
    for entry in children(given, "layer"):
        kind = (words(child(entry, "type")) or [""])[0]
        called = (words(entry) or [""])[0]
        thickness = sum(sum(numbers(t, name, "a layer's thickness")[:1]) for t in children(entry, "thickness"))
        if kind == "copper":
            if called not in names:
                continue  # copper the board's list of layers does not hold
            if not thickness > 0:
                thickness = USUAL_COPPER
                guessed.append(called)
            layers.append(Layer(called, thickness, z + thickness / 2))
        if kind == "copper" or kind in ("core", "prepreg") or called.startswith("dielectric"):
            z += thickness  # the mask, the silk and the paste are not between the coppers
    if len(layers) < 2 or any(b.z - a.z <= 0 for a, b in zip(layers, layers[1:], strict=False)):
        return spread_stackup(names, board)
    if wrong := implausible(layers):
        # A height of nought, or of a kilometre, is a slip of the tool that wrote the file: a
        # figure worked out from it would be confident and wrong.
        return spread_stackup(names, board, why=f"{wrong}, so it is not taken")
    top = layers[0].z
    layers = [Layer(layer.name, layer.thickness, layer.z - top) for layer in layers]
    said = (
        f"copper of {USUAL_COPPER * 1000:g} µm taken for {', '.join(guessed)}, which the stack-up leaves open"
        if guessed
        else ""
    )
    return Stackup(layers, bool(guessed), said)


class _Nets:
    """The file's nets by the numbers it gives them, and every name as it is kept."""

    def __init__(self, root: Node, names: Names) -> None:
        self.names = names
        self.table = {w[0]: names(w[1]) for net in children(root, "net") if len(w := words(net)) >= 2}

    def of(self, node: Node | None) -> str:
        """The net's name, from (net 3 "SW"), (net 3) or (net "SW")."""
        given = words(node)
        if not given:
            return ""
        if len(given) >= 2:
            return self.names(given[1])
        found = self.table.get(given[0])
        return self.names(given[0]) if found is None else found  # a number the file numbered, else the name itself


def _net(node: Node | None, nets: _Nets) -> str:
    return nets.of(node)


def _turn(x: float, y: float, degrees: float) -> tuple[float, float]:
    """KiCad's turn: anticlockwise as drawn, with y pointing down."""
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return x * c + y * s, -x * s + y * c


def _pad_layers(node: Node, copper: list[str]) -> tuple[str, ...]:
    out: list[str] = []
    for word in words(child(node, "layers")):
        if word == "*.Cu":
            out += copper
        elif word == "F&B.Cu":
            out += [n for n in ("F.Cu", "B.Cu") if n in copper]
        elif word in copper:
            out.append(word)
    return tuple(dict.fromkeys(out))


def _pad(node: Node, part: Component, turn: float, ctx) -> Pad | None:
    name, nets, copper = ctx
    given = words(node)
    if len(given) < 2 or given[1] == "np_thru_hole":
        return None
    at = numbers(child(node, "at"), name, f"a pad of {part.ref}")
    size = numbers(child(node, "size"), name, f"a pad of {part.ref}")
    layers = _pad_layers(node, copper)
    if len(at) < 2 or len(size) < 2 or not layers:
        return None
    dx, dy = _turn(at[0], at[1], turn)
    angle = math.radians(at[2] if len(at) > 2 else 0.0)
    w = abs(size[0] * math.cos(angle)) + abs(size[1] * math.sin(angle))
    h = abs(size[0] * math.sin(angle)) + abs(size[1] * math.cos(angle))
    drill = [v for v in words(child(node, "drill")) if v.replace(".", "", 1).isdigit()]
    return Pad(
        part.ref,
        nets.names(given[0]),
        _net(child(node, "net"), nets),
        part.x + dx,
        part.y + dy,
        w,
        h,
        layers,
        float(drill[0]) if drill else 0.0,
    )


def _texts(node: Node) -> dict[str, str]:
    """A footprint's reference and value, as versions 8 and 9 write them and as 6 and 7 did."""
    out = {w[0]: w[1] for prop in children(node, "property") if len(w := words(prop)) >= 2}
    out |= {w[0].capitalize(): w[1] for text in children(node, "fp_text") if len(w := words(text)) >= 2}
    return out


def _footprint(node: Node, ctx, budget: Budget) -> Component | None:
    name, nets = ctx[0], ctx[1]
    at = numbers(child(node, "at"), name, "a footprint's place")
    if len(at) < 2:
        return None
    texts = _texts(node)
    layer = clean((words(child(node, "layer")) or ["F.Cu"])[0])
    part = Component(
        nets.names(texts.get("Reference", "")),
        clean(texts.get("Value", "")),
        clean((words(node) or [""])[0]),
        at[0],
        at[1],
        layer,
    )
    for pad_node in children(node, "pad"):
        budget.take()
        pad = _pad(pad_node, part, at[2] if len(at) > 2 else 0.0, ctx)
        if pad is not None:
            part.pads.append(pad)
    return part if part.ref and part.pads else None


def _arc(start, mid, end) -> list[tuple[float, float]]:
    """The points of an arc through three, a chord every ten degrees; the three in a line are a line."""
    (x1, y1), (x2, y2), (x3, y3) = start, mid, end
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-12:
        return [start, end]
    ux = ((x1**2 + y1**2) * (y2 - y3) + (x2**2 + y2**2) * (y3 - y1) + (x3**2 + y3**2) * (y1 - y2)) / d
    uy = ((x1**2 + y1**2) * (x3 - x2) + (x2**2 + y2**2) * (x1 - x3) + (x3**2 + y3**2) * (x2 - x1)) / d
    radius = math.hypot(x1 - ux, y1 - uy)
    a1, a2, a3 = (math.atan2(y - uy, x - ux) for x, y in (start, mid, end))
    sweep = (a3 - a1) % (2 * math.pi)
    if (a2 - a1) % (2 * math.pi) > sweep:
        sweep -= 2 * math.pi  # the middle is on the other way round
    steps = max(math.ceil(abs(sweep) / ARC_STEP - 1e-3), 1)
    turn = [a1 + sweep * k / steps for k in range(1, steps)]
    # The ends are the file's own, so that what joins the arc there still meets it.
    return [start, *((ux + radius * math.cos(a), uy + radius * math.sin(a)) for a in turn), end]


def _xy(node: Node | None, name: str, what: str) -> tuple[float, float]:
    at = numbers(node, name, what)
    if len(at) < 2:
        raise Refusal(f"the board file {name} has {what} with no place", "save the board again from KiCad", "board")
    return at[0], at[1]


def _tracks(root: Node, ctx, budget: Budget) -> list[Track]:
    name, nets, copper = ctx
    out = []
    for kind in ("segment", "arc"):
        for node in children(root, kind):
            budget.take()
            layer = (words(child(node, "layer")) or [""])[0]
            width = numbers(child(node, "width"), name, "a track's width")
            if layer not in copper or not width or not width[0] > 0:
                continue
            ends = [_xy(child(node, "start"), name, "a track"), _xy(child(node, "end"), name, "a track")]
            if kind == "arc" and child(node, "mid") is not None:
                ends = _arc(ends[0], _xy(child(node, "mid"), name, "an arc"), ends[1])
            net = _net(child(node, "net"), nets)
            out += [Track(net, layer, a[0], a[1], b[0], b[1], width[0]) for a, b in zip(ends, ends[1:], strict=False)]
    return out


def _vias(root: Node, ctx, budget: Budget) -> list[Via]:
    name, nets, copper = ctx
    out = []
    for node in children(root, "via"):
        budget.take()
        x, y = _xy(child(node, "at"), name, "a via")
        size = numbers(child(node, "size"), name, "a via's size") or [0.6]
        drill = numbers(child(node, "drill"), name, "a via's drill") or [size[0] / 2]
        layers = [w for w in words(child(node, "layers")) if w in copper]
        if len(layers) >= 2:
            out.append(Via(_net(child(node, "net"), nets), x, y, size[0], drill[0], (layers[0], layers[-1])))
    return out


def _points(node: Node | None, name: str, budget: Budget) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for entry in (child(node, "pts") or [])[1:] if node else []:
        if head(entry) == "xy":
            pts.append(_xy(entry, name, "a zone's corner"))
        elif head(entry) == "arc":
            three = [_xy(child(entry, k), name, "a zone's arc") for k in ("start", "mid", "end") if child(entry, k)]
            pts += _arc(*three) if len(three) == 3 else three
        budget.take()
    return pts


def _zones(root: Node, ctx, budget: Budget, board: Board) -> None:
    name, nets, copper = ctx
    unfilled = set()
    for node in children(root, "zone"):
        named = words(child(node, "net_name"))
        net = nets.names(named[0]) if named else _net(child(node, "net"), nets)
        if not net or child(node, "keepout") is not None:
            continue
        fills = children(node, "filled_polygon")
        for fill in fills:
            layer = (words(child(fill, "layer")) or words(child(node, "layer")) or [""])[0]
            pts = _points(fill, name, budget)
            if layer in copper and len(pts) >= 3:
                board.zones.append(Zone(net, layer, pts))
        if fills:
            continue
        layers = [
            w for w in words(child(node, "layers")) + words(child(node, "layer")) if w in copper or w.endswith(".Cu")
        ]
        layers = copper if any(w in ("*.Cu", "F&B.Cu") for w in layers) else [w for w in layers if w in copper]
        outline = _points(child(node, "polygon"), name, budget)
        if len(outline) >= 3:
            board.zones += [Zone(net, layer, outline, filled=False) for layer in layers]
            unfilled.add(net)
    if unfilled:
        board.warnings.append(
            f"the pour on {', '.join(sorted(unfilled))} is in the file as its outline only, not as the copper "
            "filled: the outline is taken as solid copper. Fill the zones in KiCad (B) and save, for the copper as made"
        )


def read(text: str, name: str = "board.kicad_pcb") -> Board:
    root = sexpr.parse(text, name)
    if head(root) != "kicad_pcb":
        raise Refusal(
            f"the file {name} is KiCad's, but it is not a board: it starts with {head(root)[:30]!r}",
            "give the .kicad_pcb file, not the schematic or the project",
            "board",
        )
    budget = Budget(name)
    stackup = _stackup(root, name)
    names = Names()
    ctx = (name, _Nets(root, names), stackup.names())
    board = Board("kicad", name, stackup)
    if stackup.assumed and stackup.said:
        board.warnings.append(stackup.said)
    for node in children(root, "footprint") + children(root, "module"):
        part = _footprint(node, ctx, budget)
        if part is not None:
            board.components.append(part)
    board.tracks = _tracks(root, ctx, budget)
    board.vias = _vias(root, ctx, budget)
    _zones(root, ctx, budget, board)
    if said := names.said("names of nets, parts or pads"):
        board.warnings.append(said)
    return board
