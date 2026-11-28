"""Writes the made-up boards of this folder. None is a real product's board: the parts are
described by kind, the footprints are named "made_up:...", and the geometry was laid out by
hand to hold what the tests ask about. Run it again after changing it:

    python tests/fixtures/boards/make_boards.py
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from motionsim.board.model import Board, Component, Layer, Pad, Stackup, Track, Via, Zone

HERE = Path(__file__).parent
SAID = "A made-up board for MotionSim's tests: no real product, no real part."


def part(ref, value, footprint, x, y, pads, turn=0.0, layer="F.Cu"):
    """pads: (name, net, x, y, w, h) at their places on the board; a tuple of 7 has a drill."""
    made = [
        Pad(
            ref,
            p[0],
            p[1],
            p[2],
            p[3],
            p[4],
            p[5],
            ("F.Cu", "B.Cu") if len(p) > 6 else (layer,),
            p[6] if len(p) > 6 else 0.0,
        )
        for p in pads
    ]
    out = Component(ref, value, footprint, x, y, layer, made)
    out.turn = turn  # how the footprint is written turned, to hold the reader to its turning
    return out


def fet(ref, x, y, drain, gate, source):
    """A surface-mount transistor: its tab above, its gate and source pins 10 mm under it."""
    pads = [
        ("2", drain, x, y, 10.0, 8.0),
        ("1", gate, x - 2.5, y + 10, 1.2, 3.0),
        ("3", source, x + 2.5, y + 10, 1.2, 3.0),
    ]
    return part(ref, "made-up 100 V MOSFET", "made_up:TO-263-2", x, y, pads)


def chip(ref, value, case, x, y, net_a, net_b, upright=False, turn=0.0):
    """A chip part: two pads, side by side or one above the other."""
    gap, w, h = {"0603": (1.6, 0.8, 0.9), "1206": (3.2, 1.2, 1.8), "1210": (3.2, 1.2, 2.6)}[case]
    kind = "C" if value[-1:] in "nuFV" else "R"
    if upright:
        pads = [("1", net_a, x, y - gap / 2, h, w), ("2", net_b, x, y + gap / 2, h, w)]
    else:
        pads = [("1", net_a, x - gap / 2, y, w, h), ("2", net_b, x + gap / 2, y, w, h)]
    return part(ref, value, f"made_up:{kind}_{case}", x, y, pads, turn or (90.0 if upright else 0.0))


def driver(ref, x, y, nets):
    """An eight-pin half-bridge gate driver: nets by pin, 1 to 8."""
    rows = [-1.905, -0.635, 0.635, 1.905]
    pads = [(str(k + 1), nets[k], x - 2.7, y + rows[k], 1.5, 0.6) for k in range(4)]
    pads += [(str(8 - k), nets[7 - k], x + 2.7, y + rows[k], 1.5, 0.6) for k in range(4)]
    return part(ref, "made-up half-bridge driver", "made_up:SOIC-8", x, y, pads)


def line(net, points, width, layer="F.Cu"):
    return [Track(net, layer, a[0], a[1], b[0], b[1], width) for a, b in zip(points, points[1:], strict=False)]


def half_bridge() -> Board:
    """One half bridge on tracks, two layers, with its stack-up."""
    stack = Stackup([Layer("F.Cu", 0.07, 0.0), Layer("B.Cu", 0.07, 1.58)], False)
    b = Board("kicad", "half_bridge", stack)
    b.components = [
        fet("Q1", 20, 15, "VBUS", "GH", "SW"),
        fet("Q2", 20, 38, "SW", "GL", "GND"),
        chip("C1", "100n", "1206", 32, 19.6, "VBUS", "GND", upright=True),
        chip("C2", "4.7uF/100V", "1210", 36, 19.6, "VBUS", "GND", upright=True),
        driver("U1", 8, 30, ["VCC", "HIN", "LIN", "GND", "LO", "SW", "HO", "VB"]),
        chip("R1", "10R", "0603", 14, 27, "HO", "GH", turn=180.0),
        chip("R2", "10R", "0603", 14, 44, "LO", "GL"),
        chip("R3", "10k", "0603", 18.3, 46, "GL", "GND"),
        chip("C3", "100n", "0603", 10.7, 25.2, "SW", "VB", upright=True),
        part(
            "J1",
            "made-up 3-pin terminal",
            "made_up:Terminal_3",
            44,
            30,
            [("1", "VBUS", 44, 10, 3, 3, 1.5), ("2", "SW", 44, 30, 3, 3, 1.5), ("3", "GND", 44, 50, 3, 3, 1.5)],
        ),
        part(
            "J2",
            "made-up 3-pin header",
            "made_up:Header_3",
            1,
            29,
            [
                ("1", "VCC", 1, 28.095, 1.2, 1.0, 0.7),
                ("2", "HIN", 1, 29.365, 1.2, 1.0, 0.7),
                ("3", "LIN", 1, 30.635, 1.2, 1.0, 0.7),
            ],
        ),
    ]
    t = b.tracks
    t += line("VBUS", [(36, 18), (32, 18), (22, 18)], 2.0)
    t += line("GND", [(36, 21.2), (32, 21.2), (32, 48), (22.5, 48)], 2.0)
    t += line("SW", [(22.5, 25), (22.5, 35)], 2.0)
    t += line("HO", [(10.7, 29.365), (12, 29.365), (12, 27), (13.2, 27)], 0.3)
    t += line("GH", [(14.8, 27), (17.5, 27), (17.5, 25)], 0.3)
    t += line("SW", [(10.7, 30.635), (22.5, 30.635)], 0.3)
    t += line("LO", [(10.7, 31.905), (12, 31.905), (12, 44), (13.2, 44)], 0.3)
    t += line("GL", [(14.8, 44), (17.5, 44), (17.5, 48)], 0.3)
    t += line("GND", [(5.3, 31.905), (5.3, 52), (22.5, 52), (22.5, 48)], 0.5)
    t += line("GND", [(19.1, 46), (21, 46), (22.5, 48)], 0.3)
    t += line("VB", [(10.7, 28.095), (10.7, 26)], 0.3)
    t += line("VCC", [(1, 28.095), (5.3, 28.095)], 0.3)
    t += line("HIN", [(1, 29.365), (5.3, 29.365)], 0.3)
    t += line("LIN", [(1, 30.635), (5.3, 30.635)], 0.3)
    return b


def box(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def slit(x0, y0, x1, y1, holes):
    """A box with square holes, as KiCad writes a fill: one outline, each hole joined to the
    top edge by a slit of no width."""
    pts = [(x0, y0)]
    for hx, hy, half in sorted(holes):
        pts += [
            (hx, y0),
            (hx, hy - half),
            (hx - half, hy - half),
            (hx - half, hy + half),
            (hx + half, hy + half),
            (hx + half, hy - half),
            (hx, hy - half),
            (hx, y0),
        ]
    return pts + [(x1, y0), (x1, y1), (x0, y1)]


def three_phase(filled=True) -> Board:
    """Three half bridges on pours, four layers: the return of each loop on the ground
    plane 0.2 mm under the top copper, two capacitors by each leg and one bulk capacitor apart."""
    stack = Stackup(
        [
            Layer("F.Cu", 0.07, 0.0),
            Layer("In1.Cu", 0.035, 0.2525),
            Layer("In2.Cu", 0.035, 1.3275),
            Layer("B.Cu", 0.07, 1.58),
        ],
        False,
    )
    b = Board("kicad", "three_phase", stack)
    left, right = -14.0, 92.0
    holes = []
    b.zones.append(Zone("VBUS", "F.Cu", box(left, 5, right, 16), filled=filled))
    b.zones.append(Zone("GND", "F.Cu", box(left, 41.5, right, 46), filled=filled))
    grounds = [(-10.0, 19.0, 0.6)]
    for k, phase in enumerate("UVW"):
        x0 = 34.0 * k
        sw, gh, gl, ho, lo, vb = (f"{name}_{phase}" for name in ("SW", "GH", "GL", "HO", "LO", "VB"))
        b.components += [
            fet(f"Q{2 * k + 1}", x0 + 10, 12, "VBUS", gh, sw),
            fet(f"Q{2 * k + 2}", x0 + 10, 29, sw, gl, "GND"),
            chip(f"C{2 * k + 1}", "1uF/100V", "1206", x0 + 17, 15.6, "VBUS", "GND", upright=True),
            chip(f"C{2 * k + 2}", "1uF/100V", "1206", x0 + 20, 15.6, "VBUS", "GND", upright=True),
            driver(f"U{k + 1}", x0 - 4, 28, ["VCC", f"HIN_{phase}", f"LIN_{phase}", "GND", lo, sw, ho, vb]),
            chip(f"R{2 * k + 1}", "4R7", "0603", x0 + 2, 21, ho, gh),
            chip(f"R{2 * k + 2}", "4R7", "0603", x0 + 2, 37.5, lo, gl),
        ]
        outline = [(x0 + 10.9, 18.4), (x0 + 19, 18.4), (x0 + 19, 34), (x0 + 3, 34), (x0 + 3, 24.5), (x0 + 10.9, 24.5)]
        b.zones.append(Zone(sw, "F.Cu", outline, filled=filled))
        t = b.tracks
        t += line("GND", [(x0 + 12.5, 39), (x0 + 12.5, 43)], 1.5)
        t += line(ho, [(x0 - 1.3, 27.365), (x0 + 0.5, 27.365), (x0 + 0.5, 21), (x0 + 1.2, 21)], 0.3)
        t += line(gh, [(x0 + 2.8, 21), (x0 + 7.5, 21), (x0 + 7.5, 22)], 0.3)
        t += line(sw, [(x0 - 1.3, 28.635), (x0 + 3.5, 28.635)], 0.3)
        t += line(lo, [(x0 - 1.3, 29.905), (x0 + 0.5, 29.905), (x0 + 0.5, 37.5), (x0 + 1.2, 37.5)], 0.3)
        t += line(gl, [(x0 + 2.8, 37.5), (x0 + 7.5, 37.5), (x0 + 7.5, 39)], 0.3)
        t += line("GND", [(x0 - 6.7, 29.905), (x0 - 6.7, 31.5)], 0.4)
        ground = [(x0 + 17, 17.2), (x0 + 20, 17.2), (x0 - 6.7, 31.5)] + [(x0 + 9.5 + 1.5 * j, 43) for j in range(5)]
        b.vias += [Via("GND", x, y, 0.6, 0.3, ("F.Cu", "B.Cu")) for x, y in ground]
        supply = [(x0 + 5, 7.5), (x0 + 15, 7.5)]
        b.vias += [Via("VBUS", x, y, 0.6, 0.3, ("F.Cu", "B.Cu")) for x, y in supply]
        holes += [(x, y, 0.6) for x, y in supply]
        grounds += [(x, y, 0.6) for x, y in ground]
    b.components.append(
        part(
            "C7", "47uF", "made_up:CP_Elec_8x10", -10, 15.5, [("1", "VBUS", -10, 12, 3, 2), ("2", "GND", -10, 19, 3, 2)]
        )
    )
    b.vias.append(Via("GND", -10, 19, 0.6, 0.3, ("F.Cu", "B.Cu")))
    plane = slit(left, 2, right, 48, holes) if filled else box(left, 2, right, 48)
    b.zones.append(Zone("GND", "In1.Cu", plane, filled=filled))
    b.zones.append(
        Zone("VBUS", "In2.Cu", slit(left, 2, right, 48, grounds) if filled else box(left, 2, right, 48), filled=filled)
    )
    return b


def unhelpful() -> Board:
    """The half bridge again with names that say nothing, and no stack-up in the file."""
    b = half_bridge()
    b.name = "unhelpful"
    nets = {
        "VBUS": "N$1",
        "GND": "N$2",
        "SW": "N$3",
        "GH": "N$4",
        "GL": "N$5",
        "HO": "N$6",
        "LO": "N$7",
        "VB": "N$8",
        "VCC": "N$9",
        "HIN": "N$10",
        "LIN": "N$11",
    }
    refs = {
        "Q1": "A1",
        "Q2": "A2",
        "C1": "A3",
        "C2": "A4",
        "U1": "A5",
        "R1": "A6",
        "R2": "A7",
        "R3": "A8",
        "C3": "A9",
        "J1": "A10",
        "J2": "A11",
    }
    for comp in b.components:
        turn = comp.turn
        comp.ref = refs[comp.ref]
        comp.pads = [Pad(comp.ref, p.name, nets[p.net], p.x, p.y, p.w, p.h, p.layers, p.drill) for p in comp.pads]
        comp.footprint = "made_up:outline_" + str(len(comp.pads))
        comp.turn = turn
    b.tracks = [Track(nets[t.net], t.layer, t.x1, t.y1, t.x2, t.y2, t.width) for t in b.tracks]
    b.stackup = Stackup(b.stackup.layers, True)
    return b


def _turn(x, y, degrees):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return x * c + y * s, -x * s + y * c


def _f(v):
    return f"{v:.4f}".rstrip("0").rstrip(".")


def _kicad_stackup(b: Board) -> list[str]:
    out: list[str] = []
    out.append("  (setup (stackup")
    out.append('    (layer "F.SilkS" (type "Top Silk Screen"))')
    out.append('    (layer "F.Mask" (type "Top Solder Mask") (thickness 0.01))')
    layers = b.stackup.layers
    for k, layer in enumerate(layers):
        out.append(f'    (layer "{layer.name}" (type "copper") (thickness {_f(layer.thickness)}))')
        if k + 1 < len(layers):
            between = layers[k + 1].z - layer.z - (layer.thickness + layers[k + 1].thickness) / 2
            kind = "core" if k % 2 else "prepreg"
            out.append(
                f'    (layer "dielectric {k + 1}" (type "{kind}") (thickness {_f(between)}) (material "FR4") (epsilon_r 4.5))'
            )
    out.append('    (layer "B.Mask" (type "Bottom Solder Mask") (thickness 0.01))')
    out.append('    (copper_finish "None")))')
    return out


def _kicad_footprint(c: Component, number: dict, old: bool) -> list[str]:
    out: list[str] = []
    turn = getattr(c, "turn", 0.0)
    out.append(
        f'  (footprint "{c.footprint}" (layer "{c.layer}") (at {_f(c.x)} {_f(c.y)}{" " + _f(turn) if turn else ""})'
    )
    if old:
        out.append(f'    (fp_text reference "{c.ref}" (at 0 -2) (layer "F.SilkS"))')
        out.append(f'    (fp_text value "{c.value}" (at 0 2) (layer "F.Fab"))')
    else:
        out.append(f'    (property "Reference" "{c.ref}" (at 0 -2 {_f(turn)}) (layer "F.SilkS"))')
        out.append(f'    (property "Value" "{c.value}" (at 0 2 {_f(turn)}) (layer "F.Fab"))')
    for p in c.pads:
        lx, ly = _turn(p.x - c.x, p.y - c.y, -turn)
        w, h = (p.h, p.w) if round(turn) % 180 == 90 else (p.w, p.h)
        kind = "thru_hole circle" if p.drill else "smd roundrect"
        layers = '"*.Cu" "*.Mask"' if p.drill else '"F.Cu" "F.Paste" "F.Mask"'
        drill = f" (drill {_f(p.drill)})" if p.drill else ""
        out.append(
            f'    (pad "{p.name}" {kind} (at {_f(lx)} {_f(ly)}{" " + _f(turn) if turn else ""}) (size {_f(w)} {_f(h)}){drill} (layers {layers}) (net {number[p.net]} "{p.net}"))'
        )
    out.append("  )")
    return out


def kicad(b: Board, version: int, old: bool = False) -> str:
    """The board as KiCad writes it. old: as version 6 did, with fp_text and bare net numbers."""
    nets = sorted({p.net for c in b.components for p in c.pads})
    number = {net: k + 1 for k, net in enumerate(nets)}
    ids = (
        {"F.Cu": 0, "B.Cu": 31, "In1.Cu": 1, "In2.Cu": 2}
        if version < 20241000
        else {"F.Cu": 0, "B.Cu": 2, "In1.Cu": 4, "In2.Cu": 6}
    )
    out = [
        f'(kicad_pcb (version {version}) (generator "made_up")',
        "  (general (thickness 1.6))",
        f'  (title_block (comment 1 "{SAID}"))',
        "  (layers",
    ]
    out += [
        f'    ({ids[layer.name]} "{layer.name}" signal)'
        for layer in sorted(b.stackup.layers, key=lambda l: ids[l.name])
    ]
    out += ['    (36 "B.SilkS" user "B.Silkscreen")', '    (44 "Edge.Cuts" user)', "  )"]
    if not b.stackup.assumed:
        out += _kicad_stackup(b)
    out.append('  (net 0 "")')
    out += [f'  (net {number[net]} "{net}")' for net in nets]
    for c in b.components:
        out += _kicad_footprint(c, number, old)
    for t in b.tracks:
        net = f"(net {number[t.net]})"
        out.append(
            f'  (segment (start {_f(t.x1)} {_f(t.y1)}) (end {_f(t.x2)} {_f(t.y2)}) (width {_f(t.width)}) (layer "{t.layer}") {net})'
        )
    for v in b.vias:
        out.append(
            f'  (via (at {_f(v.x)} {_f(v.y)}) (size {_f(v.size)}) (drill {_f(v.drill)}) (layers "{v.layers[0]}" "{v.layers[1]}") (net {number[v.net]}))'
        )
    for z in b.zones:
        pts = lambda ring: " ".join(f"(xy {_f(x)} {_f(y)})" for x, y in ring)
        xs, ys = [p[0] for p in z.outline], [p[1] for p in z.outline]
        drawn = z.outline if len(z.outline) <= 8 else box(min(xs), min(ys), max(xs), max(ys))
        out.append(f'  (zone (net {number[z.net]}) (net_name "{z.net}") (layer "{z.layer}") (hatch edge 0.5)')
        out.append(
            "    (connect_pads yes (clearance 0.3)) (min_thickness 0.25) (fill yes (thermal_gap 0.5) (thermal_bridge_width 0.5))"
        )
        out.append(f"    (polygon (pts {pts(drawn)}))")
        if z.filled:
            out.append(f'    (filled_polygon (layer "{z.layer}") (pts {pts(z.outline)}))')
        out.append("  )")
    return "\n".join(out) + "\n)\n"


def _ipc_features(b: Board, shapes: dict, widths: dict, names: dict) -> list[str]:
    out: list[str] = []
    for layer in ("F.Cu", "B.Cu"):
        out.append(f'        <LayerFeature layerRef="{names[layer]}">')
        for c in b.components:
            for p in c.pads:
                if layer in p.layers:
                    out.append(
                        f'          <Set net="{p.net}"><Pad><Location x="{_f(p.x)}" y="{_f(p.y)}"/><StandardPrimitiveRef id="{shapes[(p.w, p.h)]}"/><PinRef componentRef="{c.ref}" pin="{p.name}"/></Pad></Set>'
                    )
        for t in b.tracks:
            if t.layer == layer:
                out.append(
                    f'          <Set net="{t.net}"><Features><Line startX="{_f(t.x1)}" startY="{_f(t.y1)}" endX="{_f(t.x2)}" endY="{_f(t.y2)}"><LineDescRef id="{widths[t.width]}"/></Line></Features></Set>'
                )
        out.append("        </LayerFeature>")
    out.append('        <LayerFeature layerRef="DRILL_TOP_BOTTOM">')
    for c in b.components:
        for p in c.pads:
            if p.drill:
                out.append(
                    f'          <Set net="{p.net}"><Hole name="H" diameter="{_f(p.drill)}" platingStatus="PLATED" plusTol="0" minusTol="0" x="{_f(p.x)}" y="{_f(p.y)}"/></Set>'
                )
    return out


def _ipc_bom(b: Board) -> list[str]:
    out: list[str] = []
    for c in b.components:
        out.append(
            f'    <BomItem OEMDesignNumberRef="{c.footprint}" quantity="1" category="ELECTRICAL"><RefDes name="{c.ref}" packageRef="{c.footprint}" populate="true" layerRef="TOP"/>'
        )
        out.append(
            f'      <Characteristics category="ELECTRICAL"><Textual definitionSource="made_up" textualCharacteristicName="Value" textualCharacteristicValue="{c.value}"/></Characteristics></BomItem>'
        )
    return out


def ipc2581(b: Board) -> str:
    """The board as an IPC-2581 revision C file, in the shape layout tools export."""
    shapes: dict[tuple[float, float], str] = {}
    widths: dict[float, str] = {}
    for c in b.components:
        for p in c.pads:
            shapes.setdefault((p.w, p.h), f"PAD_{len(shapes) + 1}")
    for t in b.tracks:
        widths.setdefault(t.width, f"LINE_{len(widths) + 1}")
    names = {"F.Cu": "TOP", "B.Cu": "BOTTOM"}
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<IPC-2581 revision="C" xmlns="http://webstds.ipc.org/2581">',
        f"  <!-- {SAID} -->",
    ]
    out += ['  <Content roleRef="Owner">', '    <DictionaryStandard units="MILLIMETER">']
    out += [
        f'      <EntryStandard id="{name}"><RectCenter width="{_f(w)}" height="{_f(h)}"/></EntryStandard>'
        for (w, h), name in shapes.items()
    ]
    out += ["    </DictionaryStandard>", '    <DictionaryLineDesc units="MILLIMETER">']
    out += [
        f'      <EntryLineDesc id="{name}"><LineDesc lineEnd="ROUND" lineWidth="{_f(w)}"/></EntryLineDesc>'
        for w, name in widths.items()
    ]
    out += [
        "    </DictionaryLineDesc>",
        "  </Content>",
        '  <Bom name="made_up"><BomHeader assembly="made_up" revision="1"/>',
    ]
    out += _ipc_bom(b)
    out += ["  </Bom>", '  <Ecad name="made_up">', '    <CadHeader units="MILLIMETER"/>', "    <CadData>"]
    out += [
        '      <Layer name="TOP" layerFunction="CONDUCTOR" side="TOP" polarity="POSITIVE"/>',
        '      <Layer name="CORE" layerFunction="DIELCORE" side="INTERNAL" polarity="POSITIVE"/>',
    ]
    out += ['      <Layer name="BOTTOM" layerFunction="CONDUCTOR" side="BOTTOM" polarity="POSITIVE"/>']
    out += [
        '      <Layer name="DRILL_TOP_BOTTOM" layerFunction="DRILL" side="ALL" polarity="POSITIVE"><Span fromLayer="TOP" toLayer="BOTTOM"/></Layer>'
    ]
    top, bottom = b.stackup.layers[0], b.stackup.layers[-1]
    core = bottom.z - top.z - (top.thickness + bottom.thickness) / 2
    out += [
        f'      <Stackup name="made_up" overallThickness="{_f(core + top.thickness + bottom.thickness)}" tolPlus="0" tolMinus="0" whereMeasured="METAL">',
        '        <StackupGroup name="all" thickness="1.6" tolPlus="0" tolMinus="0">',
    ]
    for k, (name, thick) in enumerate((("TOP", top.thickness), ("CORE", core), ("BOTTOM", bottom.thickness))):
        out.append(
            f'          <StackupLayer layerOrGroupRef="{name}" thickness="{_f(thick)}" tolPlus="0" tolMinus="0" sequence="{k + 1}"/>'
        )
    out += ["        </StackupGroup>", "      </Stackup>", '      <Step name="made_up">']
    for c in b.components:
        out.append(
            f'        <Component refDes="{c.ref}" packageRef="{c.footprint}" layerRef="TOP" part="{c.value}" mountType="SMT"><Xform rotation="0"/><Location x="{_f(c.x)}" y="{_f(c.y)}"/></Component>'
        )
    nets = sorted({p.net for c in b.components for p in c.pads})
    for net in nets:
        pins = "".join(
            f'<PinRef componentRef="{c.ref}" pin="{p.name}"/>' for c in b.components for p in c.pads if p.net == net
        )
        out.append(f'        <LogicalNet name="{net}">{pins}</LogicalNet>')
    out += _ipc_features(b, shapes, widths, names)
    out += ["        </LayerFeature>", "      </Step>", "    </CadData>", "  </Ecad>", "</IPC-2581>"]
    return "\n".join(out) + "\n"


def main() -> None:
    (HERE / "half_bridge.kicad_pcb").write_text(kicad(half_bridge(), 20240108), encoding="utf-8")
    (HERE / "half_bridge.xml").write_text(ipc2581(half_bridge()), encoding="utf-8")
    (HERE / "three_phase.kicad_pcb").write_text(kicad(three_phase(), 20241229), encoding="utf-8")
    unfilled = re.sub(r"\n    \(filled_polygon [^\n]*", "", kicad(three_phase(), 20241229))
    (HERE / "three_phase_unfilled.kicad_pcb").write_text(unfilled, encoding="utf-8")
    (HERE / "unhelpful.kicad_pcb").write_text(kicad(unhelpful(), 20211014, old=True), encoding="utf-8")


if __name__ == "__main__":
    main()
