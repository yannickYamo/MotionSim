"""An IPC-2581 file (the XML that Altium, Cadence, KiCad and others export) read into a Board.

Taken: the copper layers and their heights from <Stackup> where it is there; the nets from
<LogicalNet> and from each <Set net="...">; the parts from <Component>, with their values
from the bill of materials; and from each copper <LayerFeature>: lines and polylines as
tracks, contours as pours with their cut-outs, pads that name their pin (<PinRef>) as the
parts' pads, and plated holes of the drill layers as vias.
Not taken: a pad that names no pin (a via's land, a test point), text, and anything on a
layer that is not copper. The file is refused where it declares a document type or an
entity: no board file needs one, and that is how a few lines are made to stand for gigabytes.
"""

from __future__ import annotations

import math
import re
from typing import cast
from xml.etree import ElementTree
from xml.parsers import expat

from motionsim.board.kicad import ARC_STEP
from motionsim.board.model import (
    LONGEST_NAME,
    MOST_BYTES,
    MOST_DEPTH,
    MOST_ELEMENTS,
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
from motionsim.errors import Refusal
from motionsim.text import whole

Element = ElementTree.Element
COPPER = {"CONDUCTOR", "SIGNAL", "PLANE", "MIXED", "CONDFILM", "CONDFOIL"}
UNITS = {"MILLIMETER": 1.0, "MM": 1.0, "MICRON": 1e-3, "INCH": 25.4, "MILS": 0.0254, "MIL": 0.0254}
EXPORT = "export IPC-2581 again from the layout tool, revision B or C"
CHUNK = 1 << 20  # characters handed to the parser at a time
MOST_ATTRIBUTES = 256  # of one element: an element of a board file holds a dozen


def _refuse(name: str, why: str) -> Refusal:
    return Refusal(f"the board file {name} is not an IPC-2581 file that can be read: {why}", EXPORT, "board")


# Looked for through the whole file: a declaration may stand behind any length of comment.
_DECLARES = re.compile(r"<!\s{0,16}(?:DOCTYPE|ENTITY)", re.IGNORECASE)
# An opening tag with more attributes than any element of a board file holds, found before
# the parser is handed it: the parser makes a text of every name and value of a tag before it
# says how many there were, a second or more for one tag of a million and a half. Each part
# is taken whole and never given back, so a tag is walked once, and at most so many of its
# attributes are walked at all.
_CROWDED = re.compile(
    rf"<([^\s<>/!?=\"']{{1,64}})(?:\s++[^\s<>/=\"']++\s*+=\s*+(?:\"[^\"]*+\"|'[^']*+')){{{MOST_ATTRIBUTES + 1}}}"
)


def _as_kept(value: str) -> bool:
    return len(value) <= LONGEST_NAME and value.isprintable()


def _too_many(name: str) -> Refusal:
    return Refusal(
        f"the board file {name} holds more than {whole(MOST_ELEMENTS)} elements, more than a board file "
        f"of {MOST_BYTES // (1024 * 1024)} MB does",
        "give the board of the power stage alone",
        "board",
    )


def _held(text: str, name: str) -> None:
    """Refuses a file that holds more than a board file does (elements, attributes of one
    element, or elements inside elements) before any of it is kept: the parser alone walks
    the file, and is stopped at the first thing too many. A file that is not well-formed is
    left for the reading itself to say what is wrong with it."""
    walker = expat.ParserCreate()
    walker.ordered_attributes = True  # as a list, name and value in turn: no table is built of them
    depth = count = 0

    def start(tag: str, attributes: list[str]) -> None:
        nonlocal depth, count
        depth += 1
        count += 1
        # One test for the three on every element, a million and more times: which it was is
        # told only once one of them is past.
        if depth <= MOST_DEPTH and count <= MOST_ELEMENTS and len(attributes) <= 2 * MOST_ATTRIBUTES:
            return
        if depth > MOST_DEPTH:
            raise _refuse(name, f"it is nested more than {MOST_DEPTH} deep")
        if count > MOST_ELEMENTS:
            raise _too_many(name)
        raise _refuse(
            name,
            f"its <{clean(tag, 30)}> holds {whole(len(attributes) // 2)} attributes, and no element of a board "
            f"file holds more than {MOST_ATTRIBUTES}",
        )

    def end(tag: str) -> None:
        nonlocal depth
        depth -= 1

    walker.StartElementHandler, walker.EndElementHandler = start, end
    try:
        for at in range(0, len(text), CHUNK):
            walker.Parse(text[at : at + CHUNK], False)
        walker.Parse("", True)  # what the parser held back until the file's end
    except expat.ExpatError:
        return


def parse(text: str, name: str, names: Names | None = None) -> Element:
    """The document, or a refusal: no document type and no entity is taken, and nothing
    nested deeper or holding more elements than a board file does. names: every value of an
    attribute that is longer than a name is, or holds a line end, is cleaned with it."""
    if _DECLARES.search(text):
        raise _refuse(name, "it declares a document type or an entity, which no board file needs")
    # A tag of so many attributes holds as many signs of equality: a file with fewer has none.
    crowded = _CROWDED.search(text) if text.count("=") > MOST_ATTRIBUTES else None
    if crowded:
        raise _refuse(
            name,
            f"its <{clean(crowded.group(1), 30)}> holds more than {MOST_ATTRIBUTES} attributes, and no element of "
            "a board file holds that many",
        )
    _held(text, name)
    names = Names() if names is None else names
    parser: ElementTree.XMLPullParser = ElementTree.XMLPullParser(events=("start",))
    root: Element | None = None

    def take() -> None:
        nonlocal root
        for _, element in cast("list[tuple[str, Element]]", list(parser.read_events())):
            root = element if root is None else root
            element.tag = element.tag.rsplit("}", 1)[-1]  # the names without their namespace
            for key, value in element.attrib.items():
                if not _as_kept(value):
                    element.attrib[key] = names(value)

    try:
        for at in range(0, len(text), CHUNK):
            parser.feed(text[at : at + CHUNK])
            take()
        parser.close()
        take()  # what the parser held back until the file's end
    except ElementTree.ParseError as exc:
        raise _refuse(name, f"it is not well-formed XML ({str(exc)[:80]})") from None
    if root is None or root.tag != "IPC-2581":
        raise _refuse(name, f"it starts with <{root.tag[:30] if root is not None else ''}>, not <IPC-2581>")
    return root


class _Reader:
    def __init__(self, root: Element, name: str) -> None:
        self.root, self.name, self.budget = root, name, Budget(name)
        header = root.find(".//CadHeader")
        self.unit = self._unit(header)
        self.shapes: dict[str, tuple[float, float]] = {}
        self.widths: dict[str, float] = {}
        for book in _each(root, "DictionaryStandard", "DictionaryUser"):
            scale = self._unit(book)
            for entry in book:
                size = self._size(entry, scale)
                if size and entry.get("id"):
                    self.shapes[entry.get("id", "")] = size
        for book in root.iter("DictionaryLineDesc"):
            scale = self._unit(book)
            for entry in book:
                line = entry.find("LineDesc")
                if line is not None and entry.get("id"):
                    self.widths[entry.get("id", "")] = self.number(line, "lineWidth") * scale / self.unit

    def _unit(self, element: Element | None) -> float:
        units = (element.get("units") or "MILLIMETER").upper() if element is not None else "MILLIMETER"
        if units not in UNITS:
            raise _refuse(self.name, f"its lengths are in {units[:20]!r}, a unit not known here")
        return UNITS[units]

    def number(self, element: Element, key: str, default: float | None = None) -> float:
        """An attribute as a number in the file's unit."""
        text = element.get(key)
        if text is None and default is not None:
            return default
        try:
            value = float(text)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise _refuse(self.name, f"<{element.tag}> holds {key}={str(text)[:30]!r} where a number belongs") from None
        if not math.isfinite(value) or abs(value) > 1e9:
            raise _refuse(self.name, f"<{element.tag}> holds {key}={str(text)[:30]!r}, which is no length on a board")
        return value

    def mm(self, element: Element, key: str, default: float | None = None) -> float:
        return self.number(element, key, default) * self.unit

    def _size(self, holder: Element, scale: float) -> tuple[float, float] | None:
        """The box around a pad's shape, in millimetres, from the shape itself or the one it names."""
        for shape in holder.iter():
            if shape.tag == "StandardPrimitiveRef" or shape.tag == "UserPrimitiveRef":
                return self.shapes.get(shape.get("id", ""))
            if shape.tag == "Circle":
                d = self.number(shape, "diameter") * scale
                return d, d
            if shape.tag in ("RectCenter", "RectRound", "RectCham", "Oval", "RectCorner"):
                if shape.tag == "RectCorner":
                    w = abs(self.number(shape, "upperRightX") - self.number(shape, "lowerLeftX"))
                    h = abs(self.number(shape, "upperRightY") - self.number(shape, "lowerLeftY"))
                    return w * scale, h * scale
                return self.number(shape, "width") * scale, self.number(shape, "height") * scale
            if shape.tag == "Polygon":
                pts = self.ring(shape)
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                return (max(xs) - min(xs)) * scale / self.unit, (max(ys) - min(ys)) * scale / self.unit
        return None

    def ring(self, polygon: Element) -> list[tuple[float, float]]:
        """A polygon's corners in millimetres, its curves drawn as chords."""
        pts: list[tuple[float, float]] = []
        for step in polygon:
            if step.tag not in ("PolyBegin", "PolyStepSegment", "PolyStepCurve"):
                continue
            self.budget.take()
            end = (self.mm(step, "x"), self.mm(step, "y"))
            if step.tag == "PolyStepCurve" and pts:
                centre = (self.mm(step, "centerX"), self.mm(step, "centerY"))
                pts += _curve(pts[-1], end, centre, step.get("clockwise", "false").lower() == "true")
            else:
                pts.append(end)
        return pts

    def width(self, feature: Element) -> float:
        line = feature.find("LineDesc")
        if line is not None:
            return self.mm(line, "lineWidth")
        named = feature.find("LineDescRef")
        return self.widths.get(named.get("id", ""), 0.0) * self.unit if named is not None else 0.0


def _each(element: Element, *tags: str):
    return (e for e in element.iter() if e.tag in tags)


def _curve(start, end, centre, clockwise: bool) -> list[tuple[float, float]]:
    radius = math.hypot(start[0] - centre[0], start[1] - centre[1])
    a1 = math.atan2(start[1] - centre[1], start[0] - centre[0])
    a2 = math.atan2(end[1] - centre[1], end[0] - centre[0])
    sweep = (a1 - a2) % (2 * math.pi) if clockwise else (a2 - a1) % (2 * math.pi)
    sweep = sweep or 2 * math.pi
    steps = max(math.ceil(sweep / ARC_STEP - 1e-3), 1)
    sign = -1 if clockwise else 1
    mid = [
        (
            centre[0] + radius * math.cos(a1 + sign * sweep * k / steps),
            centre[1] + radius * math.sin(a1 + sign * sweep * k / steps),
        )
        for k in range(1, steps)
    ]
    return [*mid, end]


def _stackup(r: _Reader) -> tuple[Stackup, dict[str, tuple[str, str]]]:
    """The copper layers in the order they lie, and what each drill layer joins."""
    kinds = {layer.get("name", ""): (layer.get("layerFunction") or "").upper() for layer in r.root.iter("Layer")}
    copper = [name for name, kind in kinds.items() if kind in COPPER]
    spans = {}
    for layer in r.root.iter("Layer"):
        span = layer.find("Span")
        if span is not None and span.get("fromLayer") in copper and span.get("toLayer") in copper:
            spans[layer.get("name", "")] = (span.get("fromLayer", ""), span.get("toLayer", ""))
    rows = sorted(r.root.iter("StackupLayer"), key=lambda row: r.number(row, "sequence", 0.0))
    layers, z = [], 0.0
    for row in rows:
        name = row.get("layerOrGroupRef") or row.get("layerRef") or ""
        thickness = r.mm(row, "thickness", 0.0)
        if name in copper:
            layers.append(Layer(name, thickness if thickness > 0 else USUAL_COPPER, z + thickness / 2))
        if name in copper or kinds.get(name, "").startswith("DIEL"):
            z += thickness
    if (
        len(layers) < 2
        or len(layers) != len(copper)
        or any(b.z - a.z <= 0 for a, b in zip(layers, layers[1:], strict=False))
    ):
        return spread_stackup(copper), spans
    if wrong := implausible(layers):
        return spread_stackup(copper, why=f"{wrong}, so it is not taken"), spans
    top = layers[0].z
    return Stackup([Layer(layer.name, layer.thickness, layer.z - top) for layer in layers], False), spans


def _components(r: _Reader, board: Board) -> dict[str, Component]:
    values = {}
    for item in r.root.iter("BomItem"):
        said = [
            t.get("textualCharacteristicValue", "")
            for t in item.iter("Textual")
            if "value" in (t.get("textualCharacteristicName") or "").lower()
        ]
        for ref in item.iter("RefDes"):
            values[ref.get("name", "")] = said[0] if said else item.get("OEMDesignNumberRef", "")
    parts = {}
    for node in r.root.iter("Component"):
        name = node.get("refDes", "")
        where = node.find("Location")
        if not name or where is None:
            continue
        r.budget.take()
        value = values.get(name) or node.get("part") or ""
        parts[name] = Component(
            name, value, node.get("packageRef", ""), r.mm(where, "x"), r.mm(where, "y"), node.get("layerRef", "")
        )
    return parts


def _pin_nets(r: _Reader) -> dict[tuple[str, str], str]:
    return {
        (pin.get("componentRef", ""), pin.get("pin", "")): net.get("name", "")
        for net in r.root.iter("LogicalNet")
        for pin in net.iter("PinRef")
    }


def _pad(r: _Reader, node: Element, net: str, layer: str, parts: dict[str, Component], nets) -> None:
    pin = node.find("PinRef")
    where = node.find("Location")
    size = r._size(node, r.unit)
    if pin is None or where is None or size is None or pin.get("componentRef") not in parts:
        return
    part = parts[pin.get("componentRef", "")]
    turn = node.find("Xform")
    angle = math.radians(r.number(turn, "rotation", 0.0)) if turn is not None else 0.0
    w = abs(size[0] * math.cos(angle)) + abs(size[1] * math.sin(angle))
    h = abs(size[0] * math.sin(angle)) + abs(size[1] * math.cos(angle))
    name = pin.get("pin", "")
    net = net or nets.get((part.ref, name), "")
    x, y = r.mm(where, "x"), r.mm(where, "y")
    same = next(
        (k for k, pad in enumerate(part.pads) if pad.name == name and abs(pad.x - x) + abs(pad.y - y) < 1e-6), None
    )
    if same is None:
        part.pads.append(Pad(part.ref, name, net, x, y, w, h, (layer,)))
    elif layer not in part.pads[same].layers:  # a through-hole pin: the same pad on another layer
        old = part.pads[same]
        part.pads[same] = Pad(old.ref, old.name, old.net, old.x, old.y, old.w, old.h, (*old.layers, layer))


def _features(r: _Reader, group: Element, net: str, layer: str, board: Board) -> None:
    for feature in _each(group, "Line", "Polyline", "Contour"):
        r.budget.take()
        if feature.tag == "Contour":
            outline = feature.find("Polygon")
            if outline is not None and len(pts := r.ring(outline)) >= 3:
                board.zones.append(Zone(net, layer, pts, [r.ring(cut) for cut in feature.findall("Cutout")]))
            continue
        width = r.width(feature)
        if feature.tag == "Line":
            pts = [(r.mm(feature, "startX"), r.mm(feature, "startY")), (r.mm(feature, "endX"), r.mm(feature, "endY"))]
        else:
            pts = r.ring(feature)
        if width > 0:
            board.tracks += [
                Track(net, layer, a[0], a[1], b[0], b[1], width) for a, b in zip(pts, pts[1:], strict=False)
            ]


def read(text: str, name: str = "board.xml") -> Board:
    names = Names()
    r = _Reader(parse(text, name, names), name)
    stackup, spans = _stackup(r)
    board = Board("ipc2581", name, stackup)
    if stackup.assumed:
        board.warnings.append(stackup.said)
    parts, nets = _components(r, board), _pin_nets(r)
    copper = stackup.names()
    for sheet in r.root.iter("LayerFeature"):
        layer = sheet.get("layerRef", "")
        for group in sheet.iter("Set"):
            net = group.get("net", "")
            if layer in spans:
                for hole in group.iter("Hole"):
                    r.budget.take()
                    if (hole.get("platingStatus") or "").upper() != "NONPLATED" and net:
                        d = r.mm(hole, "diameter")
                        board.vias.append(Via(net, r.mm(hole, "x"), r.mm(hole, "y"), d + 0.3, d, spans[layer]))
            if layer not in copper:
                continue
            for node in group.iter("Pad"):
                r.budget.take()
                _pad(r, node, net, layer, parts, nets)
            if net and net.upper() != "NO_NET":
                _features(r, group, net, layer, board)
    board.components = [part for part in parts.values() if part.pads]
    if said := names.said("names or other values"):
        board.warnings.append(said)
    return board
