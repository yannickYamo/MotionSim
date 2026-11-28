"""The board readers on what they are handed: values and units, arcs, vias, pours with holes,
a stack-up present and absent, and files that are cut short, malformed or hostile. Every one
of those is refused in a line: never a fault, never a hang."""

from __future__ import annotations

import base64
import gzip
import io
import math
import tarfile
import zipfile
from pathlib import Path

import numpy as np
import pytest

from motionsim import board
from motionsim.board import formats, ipc2581, kicad, mesh, sexpr, values
from motionsim.board.model import Zone
from motionsim.errors import Refusal

pytestmark = pytest.mark.timeout(60)

BOARDS = Path(__file__).parent / "fixtures" / "boards"


def text_of(name: str) -> str:
    return (BOARDS / name).read_text(encoding="utf-8")


# Values ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, farads",
    [
        ("100n", 100e-9),
        ("100nF", 100e-9),
        ("4.7uF", 4.7e-6),
        ("0.1µF/100V", 0.1e-6),
        ("4u7", 4.7e-6),
        ("10 uF 50V", 10e-6),
        ("2,2µ", 2.2e-6),
        ("470p X7R", 470e-12),
        ("1mF", 1e-3),
        ("100NF", 100e-9),
        ("0.001F", 1e-3),
        ("C 22n 630V", 22e-9),
    ],
)
def test_a_capacitors_value_is_read_as_boards_write_it(text, farads) -> None:
    assert values.capacitance(text) == pytest.approx(farads, rel=1e-12)


@pytest.mark.parametrize("text", ["", "10k", "4R7", "100V", "DNP", "0.1", "X7R", "made-up 100 V MOSFET", None, 5])
def test_what_is_not_a_capacitance_is_none(text) -> None:
    assert values.capacitance(text) is None


def test_ohms_cases_and_packages_are_told_from_what_is_written() -> None:
    assert all(values.reads_as_ohms(t) for t in ("10R", "4R7", "10k", "2.2 Ω", "5mR", "0R"))
    assert not any(values.reads_as_ohms(t) for t in ("100n", "4u7", "", "made-up driver"))
    assert values.case("made_up:C_0603_1608Metric") == "0603"
    assert values.case("made_up:C_1206") == "1206"
    assert values.case("made_up:CP_Elec_8x10") is None
    assert values.case("C_12065") is None  # a longer number is not a case
    assert values.package("made_up:TO-263-2")[0] == "a surface-mount D2PAK"
    assert values.package("made_up:TO-247-3_Vertical")[1:] == (10.0, 5.0, 7.0)
    assert values.package("made_up:outline_3") is None


# The bracket reader ------------------------------------------------------------------------


def test_brackets_and_quoted_text_are_read() -> None:
    node = sexpr.parse('(a 1 "two words" (b "say \\"hi\\"" (c)) -3.5e-1)')
    assert node == ["a", "1", "two words", ["b", 'say "hi"', ["c"]], "-3.5e-1"]
    assert sexpr.numbers(["at", "1", "-2.5", "90"], "f", "a place") == [1.0, -2.5, 90.0]


@pytest.mark.parametrize(
    "text, said",
    [
        ("(kicad_pcb (version 1)", "a bracket is never closed"),
        ("(kicad_pcb))", "a bracket closes that was never opened"),
        ('(kicad_pcb "never ended)', "a quoted text is never closed"),
        ("kicad_pcb", "does not start with a bracket"),
        ("(a) (b)", "more after its last bracket"),
        ("(" * 100_000, "brackets are more than 64 deep"),
    ],
)
def test_a_bracket_file_that_cannot_be_read_is_refused(text, said) -> None:
    with pytest.raises(Refusal) as refused:
        sexpr.parse(text, "b.kicad_pcb")
    assert said in refused.value.reason
    assert refused.value.field == "board"


def test_a_bracket_file_of_more_values_than_a_board_holds_is_refused_by_their_true_count(monkeypatch) -> None:
    """Brackets and values are counted as what they are, and held to what 30 MB of board can
    hold: half a million of them is a board of a few megabytes, and is read."""
    assert len(sexpr.parse("(a " + "x " * 500_000 + ")", "b.kicad_pcb")) == 500_001
    monkeypatch.setattr(sexpr, "MOST_VALUES", 1000)
    assert len(sexpr.parse("(a " + "x " * 997 + ")")) == 998
    with pytest.raises(Refusal, match="holds more than 1 000 brackets and values") as refused:
        sexpr.parse("(a " + "x " * 999 + ")", "b.kicad_pcb")
    assert refused.value.field == "board"


# KiCad -------------------------------------------------------------------------------------


def test_the_stack_up_is_read_where_the_file_has_one() -> None:
    made = kicad.read(text_of("three_phase.kicad_pcb"))
    assert not made.stackup.assumed
    assert made.stackup.names() == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]  # by where they lie, not by number
    assert [layer.thickness for layer in made.stackup.layers] == [0.07, 0.035, 0.035, 0.07]
    # The middle of each copper under the top one's: 0.035 + 0.2 + 0.0175 = 0.2525 mm, and so on.
    assert [layer.z for layer in made.stackup.layers] == pytest.approx([0.0, 0.2525, 1.3275, 1.58])


def test_a_file_with_no_stack_up_gets_the_usual_and_says_so() -> None:
    made = kicad.read(text_of("unhelpful.kicad_pcb"))
    assert made.stackup.assumed
    assert [(layer.name, layer.thickness) for layer in made.stackup.layers] == [("F.Cu", 0.035), ("B.Cu", 0.035)]
    assert made.stackup.layers[1].z == pytest.approx(1.565)  # a 1.6 mm board less one copper
    assert any("no stack-up in the file" in line for line in made.warnings)


def test_footprints_pads_and_their_turning_are_read() -> None:
    made = kicad.read(text_of("half_bridge.kicad_pcb"))
    q1 = made.component("Q1")
    assert (q1.value, q1.footprint) == ("made-up 100 V MOSFET", "made_up:TO-263-2")
    tab = next(p for p in q1.pads if p.name == "2")
    assert (tab.net, tab.x, tab.y, tab.w, tab.h, tab.layers) == ("VBUS", 20.0, 15.0, 10.0, 8.0, ("F.Cu",))
    # C1 is written turned a quarter: its pads are one above the other, each wider than tall.
    c1 = {p.name: p for p in made.component("C1").pads}
    assert (c1["1"].net, c1["1"].x, c1["1"].y) == ("VBUS", pytest.approx(32.0), pytest.approx(18.0))
    assert (c1["2"].net, c1["2"].y) == ("GND", pytest.approx(21.2))
    assert (c1["1"].w, c1["1"].h) == (pytest.approx(1.8), pytest.approx(1.2))
    # R1 is written turned half round: pad 1 is still where the board has it.
    r1 = {p.name: p for p in made.component("R1").pads}
    assert (r1["1"].net, r1["1"].x, r1["2"].net, r1["2"].x) == ("HO", pytest.approx(13.2), "GH", pytest.approx(14.8))
    # A through-hole pad is on every copper layer, with its drill.
    j1 = made.component("J1").pads[0]
    assert (j1.layers, j1.drill) == (("F.Cu", "B.Cu"), 1.5)
    assert len(made.tracks) == 26 and {t.width for t in made.tracks} == {0.3, 0.5, 2.0}  # fourteen runs, 26 pieces


def test_the_older_way_of_writing_references_and_nets_is_read() -> None:
    made = kicad.read(text_of("unhelpful.kicad_pcb"))  # fp_text and (net 3), as version 6 wrote
    assert made.component("A3").value == "100n"
    assert {t.net for t in made.tracks} >= {"N$1", "N$2", "N$3"}


BOARD = """(kicad_pcb (version 20240108) (generator "made_up")
  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))
  (net 0 "") (net 1 "A") (net 2 "B")
  (footprint "made_up:two" (layer "F.Cu") (at 10 10 30)
    (property "Reference" "X1") (property "Value" "1n")
    (pad "1" smd rect (at 2 0 30) (size 2 1) (layers "F.Cu") (net 1 "A"))
    (pad "2" smd rect (at -2 0 30) (size 2 1) (layers "F.Cu") (net "B"))
    (pad "" np_thru_hole circle (at 0 3) (size 1 1) (drill 1) (layers "*.Cu")))
  %s
)"""


def test_an_arc_is_drawn_as_chords_on_its_circle() -> None:
    """A quarter circle of radius 10 about (0, 0), from (10, 0) by (7.0711, 7.0711) to (0, 10):
    nine chords of ten degrees, every corner on the circle, their length just under π·10/2."""
    arc = '(arc (start 10 0) (mid 7.0711 7.0711) (end 0 10) (width 0.5) (layer "F.Cu") (net 1))'
    made = kicad.read(BOARD % arc)
    assert len(made.tracks) == 9
    assert all(math.hypot(t.x1, t.y1) == pytest.approx(10.0, abs=1e-3) for t in made.tracks)
    assert (made.tracks[0].x1, made.tracks[0].y1) == (10.0, 0.0)
    assert (made.tracks[-1].x2, made.tracks[-1].y2) == pytest.approx((0.0, 10.0), abs=1e-3)
    length = sum(math.hypot(t.x2 - t.x1, t.y2 - t.y1) for t in made.tracks)
    assert length == pytest.approx(math.pi * 5, rel=0.002)
    assert {(t.net, t.layer, t.width) for t in made.tracks} == {("A", "F.Cu", 0.5)}


def test_a_footprint_turned_by_any_angle_puts_its_pads_where_kicad_does() -> None:
    """KiCad turns anticlockwise as drawn, y pointing down: a pad 2 mm along x of a footprint
    turned 30° lies at (10 + 2·cos 30°, 10 - 2·sin 30°) = (11.732, 9.0). Its 2 by 1 mm
    copper, turned with it, lies in a box 2·cos 30° + 1·sin 30° = 2.232 by 1.866 mm."""
    pad = kicad.read(BOARD % "").component("X1").pads[0]
    assert (pad.x, pad.y) == pytest.approx((11.732, 9.0), abs=1e-3)
    assert (pad.w, pad.h) == pytest.approx((2.232, 1.866), abs=1e-3)
    both = kicad.read(BOARD % "").component("X1").pads
    assert [p.net for p in both] == ["A", "B"]  # a net by its name alone, and the unplated hole left out


def test_vias_are_read_with_their_layers() -> None:
    made = kicad.read(text_of("three_phase.kicad_pcb"))
    assert len(made.vias) == 31  # eight ground and two supply vias a leg, and one at the bulk capacitor
    one = next(v for v in made.vias if v.net == "VBUS")
    assert (one.x, one.y, one.size, one.drill, one.layers) == (5.0, 7.5, 0.6, 0.3, ("F.Cu", "B.Cu"))


def grid_of(layer: str, window, pitch: float = 0.2) -> mesh.Grid:
    nx, ny = round((window[2] - window[0]) / pitch), round((window[3] - window[1]) / pitch)
    return mesh.Grid(
        window[0],
        window[1],
        pitch,
        nx,
        ny,
        [],
        [],
        np.zeros((1, ny, nx), dtype=np.int16),
        np.zeros((1, ny, nx), dtype=np.int32),
    )


def test_a_filled_zone_is_taken_with_its_holes_and_an_unfilled_one_as_its_outline() -> None:
    filled = kicad.read(text_of("three_phase.kicad_pcb"))
    plane = next(z for z in filled.zones if z.layer == "In1.Cu")
    assert plane.filled and plane.net == "GND"
    grid = grid_of("In1.Cu", (0.0, 2.0, 20.0, 12.0))
    copper = mesh.inside(grid, plane)
    cell = lambda x, y: bool(copper[grid.row(y), grid.column(x)])
    # The supply's via at (5, 7.5) passes through a hole 1.2 mm square in the ground plane.
    assert not cell(5.0, 7.5) and not cell(5.3, 7.9) and not cell(4.5, 7.1)
    assert cell(5.0, 6.7) and cell(5.0, 8.3) and cell(4.2, 7.5) and cell(10.0, 7.5) and cell(5.0, 3.0)
    assert not any("outline only" in line for line in filled.warnings)

    drawn = kicad.read(text_of("three_phase_unfilled.kicad_pcb"))
    plane = next(z for z in drawn.zones if z.layer == "In1.Cu")
    assert not plane.filled and len(plane.outline) == 4
    assert bool(mesh.inside(grid, plane)[grid.row(7.5), grid.column(5.0)])  # no hole is known
    assert any("outline only" in line and "GND" in line for line in drawn.warnings)


@pytest.mark.parametrize(
    "text, said",
    [
        ('(kicad_sch (version 20231120) (generator "eeschema"))', "it is not a board: it starts with 'kicad_sch'"),
        (
            BOARD % '(segment (start 1 two) (end 3 4) (width 0.2) (layer "F.Cu") (net 1))',
            "holds 'two' where a number belongs",
        ),
        (
            BOARD % '(segment (start 1 nan) (end 3 4) (width 0.2) (layer "F.Cu") (net 1))',
            "which is no length on a board",
        ),
        (BOARD % '(via (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1))', "a via with no place"),
    ],
)
def test_a_kicad_file_that_cannot_be_used_is_refused(text, said) -> None:
    with pytest.raises(Refusal) as refused:
        kicad.read(text, "b.kicad_pcb")
    assert said in refused.value.reason
    assert refused.value.field == "board"


# IPC-2581 ----------------------------------------------------------------------------------


def test_the_ipc_file_holds_the_same_board_as_the_kicad_file() -> None:
    xml, pcb = ipc2581.read(text_of("half_bridge.xml")), kicad.read(text_of("half_bridge.kicad_pcb"))
    assert xml.format == "ipc2581" and not xml.stackup.assumed
    assert [(layer.name, layer.thickness, layer.z) for layer in xml.stackup.layers] == [
        ("TOP", 0.07, 0.0),
        ("BOTTOM", 0.07, pytest.approx(1.58)),
    ]
    assert {c.ref: c.value for c in xml.components} == {c.ref: c.value for c in pcb.components}
    place = lambda made: sorted(
        (p.ref, p.name, p.net, round(p.x, 3), round(p.y, 3), round(p.w, 3), round(p.h, 3))
        for c in made.components
        for p in c.pads
    )
    assert place(xml) == place(pcb)
    assert len(xml.tracks) == len(pcb.tracks) == 26
    assert xml.component("J1").pads[0].layers == ("TOP", "BOTTOM")  # a through-hole pin, once on each layer
    assert {(v.net, v.drill, v.layers) for v in xml.vias} >= {("VBUS", 1.5, ("TOP", "BOTTOM"))}


IPC = """<?xml version="1.0"?>
<IPC-2581 revision="C" xmlns="http://webstds.ipc.org/2581">
  <Content><DictionaryStandard units="MILLIMETER"><EntryStandard id="P"><Circle diameter="1.0"/></EntryStandard></DictionaryStandard></Content>
  <Ecad name="made_up"><CadHeader units="INCH"/><CadData>
    <Layer name="L1" layerFunction="SIGNAL"/><Layer name="L2" layerFunction="PLANE"/>
    <Step name="made_up">
      <Component refDes="X1" packageRef="made_up" layerRef="L1" part="10n"><Location x="1" y="1"/></Component>
      <LogicalNet name="A"><PinRef componentRef="X1" pin="1"/></LogicalNet>
      <LayerFeature layerRef="L1">
        <Set><Pad><Location x="1.0" y="1.0"/><Xform rotation="90"/><StandardPrimitiveRef id="P"/><PinRef componentRef="X1" pin="1"/></Pad></Set>
        <Set net="A"><Features>
          <Polyline><PolyBegin x="0" y="0"/><PolyStepSegment x="1" y="0"/><PolyStepCurve x="1.5" y="0.5" centerX="1" centerY="0.5" clockwise="false"/><LineDesc lineEnd="ROUND" lineWidth="0.01"/></Polyline>
          <Contour><Polygon><PolyBegin x="0" y="0"/><PolyStepSegment x="1" y="0"/><PolyStepSegment x="1" y="1"/><PolyStepSegment x="0" y="1"/></Polygon>
            <Cutout><PolyBegin x="0.4" y="0.4"/><PolyStepSegment x="0.6" y="0.4"/><PolyStepSegment x="0.6" y="0.6"/><PolyStepSegment x="0.4" y="0.6"/></Cutout></Contour>
        </Features></Set>
      </LayerFeature>
    </Step></CadData></Ecad>
</IPC-2581>"""


def test_inches_curves_cut_outs_and_a_missing_stack_up_in_an_ipc_file() -> None:
    made = ipc2581.read(IPC)
    assert made.stackup.assumed and made.stackup.names() == ["L1", "L2"]
    # Lengths in inches become millimetres; a shape from the dictionary keeps the dictionary's unit.
    pad = made.component("X1").pads[0]
    assert (pad.net, pad.x, pad.y, pad.w, pad.h) == ("A", 25.4, 25.4, pytest.approx(1.0), pytest.approx(1.0))
    assert made.component("X1").value == "10n"
    # One straight inch, then a quarter circle of half an inch drawn as nine chords, 0.254 mm wide.
    assert len(made.tracks) == 10 and made.tracks[0].width == pytest.approx(0.254)
    assert (made.tracks[0].x2, made.tracks[0].y2) == (25.4, 0.0)
    assert all(math.hypot(t.x2 - 25.4, t.y2 - 12.7) == pytest.approx(12.7, abs=1e-6) for t in made.tracks[1:])
    assert (made.tracks[-1].x2, made.tracks[-1].y2) == pytest.approx((38.1, 12.7))
    # The pour is an inch square with a hole of a fifth of an inch in its middle.
    zone = made.zones[0]
    assert len(zone.outline) == 4 and len(zone.holes) == 1 and zone.filled
    grid = grid_of("L1", (0.0, 0.0, 25.4, 25.4), 0.254)
    copper = mesh.inside(grid, zone)
    assert not copper[grid.row(12.7), grid.column(12.7)] and copper[grid.row(5.0), grid.column(12.7)]
    assert copper.sum() == pytest.approx(100 * 100 - 20 * 20, abs=45)


BOMB = """<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">
<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;"><!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">
<!ENTITY e "&d;&d;&d;&d;&d;&d;&d;&d;&d;&d;"><!ENTITY f "&e;&e;&e;&e;&e;&e;&e;&e;&e;&e;">
<!ENTITY g "&f;&f;&f;&f;&f;&f;&f;&f;&f;&f;"><!ENTITY h "&g;&g;&g;&g;&g;&g;&g;&g;&g;&g;">]>
<IPC-2581 revision="C"><Content>&h;</Content></IPC-2581>"""


@pytest.mark.parametrize(
    "text, said",
    [
        (BOMB, "declares a document type or an entity"),
        ('<!DOCTYPE x SYSTEM "file:///etc/passwd"><IPC-2581/>', "declares a document type or an entity"),
        ("<IPC-2581>" + "<a>" * 200_000, "nested more than 64 deep"),
        ("<IPC-2581><Ecad></IPC-2581>", "not well-formed XML"),
        ("<gerber/>", "it starts with <gerber>, not <IPC-2581>"),
        (IPC.replace('units="INCH"', 'units="FURLONG"'), "a unit not known here"),
        (IPC.replace('x="1.0" y="1.0"', 'x="one" y="1.0"'), "x='one' where a number belongs"),
        (IPC.replace('lineWidth="0.01"', 'lineWidth="inf"'), "which is no length on a board"),
    ],
)
def test_an_ipc_file_that_cannot_be_used_is_refused(text, said) -> None:
    with pytest.raises(Refusal) as refused:
        ipc2581.read(text, "b.xml")
    assert said in refused.value.reason
    assert refused.value.field == "board"


def test_an_ipc_file_of_more_elements_than_a_board_holds_is_refused_by_their_true_count(monkeypatch) -> None:
    many = "<IPC-2581>" + "<a/>" * 400_001 + "</IPC-2581>"
    assert len(ipc2581.parse(many, "b.xml")) == 400_001  # what a few megabytes of board hold
    monkeypatch.setattr(ipc2581, "MOST_ELEMENTS", 1000)
    with pytest.raises(Refusal, match="holds more than 1 000 elements") as refused:
        ipc2581.parse(many, "b.xml")
    assert refused.value.field == "board"
    # Counted too where the file opens with a comment that looks like nesting.
    with pytest.raises(Refusal, match="holds more than 1 000 elements"):
        ipc2581.parse("<!--" + "<a>" * 100 + "-->" + many, "b.xml")


# Kinds of file -----------------------------------------------------------------------------


def zipped(members: dict[str, bytes]) -> bytes:
    held = io.BytesIO()
    with zipfile.ZipFile(held, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return held.getvalue()


def tarred(members: dict[str, bytes]) -> bytes:
    held = io.BytesIO()
    with tarfile.open(fileobj=held, mode="w:gz") as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return held.getvalue()


ODB = {
    "board/matrix/matrix": b"STEP {\n}\n",
    "board/steps/pcb/layers/top/features": b"#\n",
    "board/steps/pcb/eda/data": b"#\n",
}


@pytest.mark.parametrize("pack, name", [(zipped, "board.zip"), (tarred, "board.tgz")])
def test_an_odb_archive_is_refused_with_what_to_export(pack, name) -> None:
    with pytest.raises(Refusal) as refused:
        board.load(pack(ODB), name)
    assert refused.value.reason == "ODB++ is not read yet: export IPC-2581 or give the KiCad file"
    assert "export IPC-2581" in refused.value.fix


@pytest.mark.parametrize("pack, name", [(zipped, "board.zip"), (tarred, "board.tgz")])
@pytest.mark.parametrize("member", ["../../etc/cron.d/job", "/etc/passwd", "board/../../x", "C:\\windows\\x", "..\\x"])
def test_an_archive_with_a_path_that_leaves_it_is_refused_and_nothing_is_written(
    pack, name, member, tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    with pytest.raises(Refusal, match="holds a path that leaves the archive"):
        board.load(pack({**ODB, member: b"x"}), name)
    assert list(tmp_path.iterdir()) == []


def test_archives_that_are_too_much_or_broken_are_refused(monkeypatch) -> None:
    with pytest.raises(Refusal, match="holds more files than any board is made of"):
        board.load(zipped({f"f{k}": b"" for k in range(5001)}), "many.zip")
    with pytest.raises(Refusal, match="cannot be read as a .zip or a .tgz".replace(".", "[.]")):
        board.load(zipped(ODB)[:-40], "cut.zip")
    with pytest.raises(Refusal, match="cannot be read as a .zip or a .tgz".replace(".", "[.]")):
        board.load(b"\x1f\x8b" + b"\x00" * 64, "cut.tgz")
    with pytest.raises(Refusal, match="is an archive of 2 files, not a board file"):
        board.load(zipped({"a.txt": b"a", "b.txt": b"b"}), "other.zip")
    # A few kilobytes that unpack without end: the unpacking is stopped at a size.
    monkeypatch.setattr(formats, "MOST_BYTES", 10_000)
    endless = gzip.compress(tarred({"big": b"\0" * 5_000_000})[:0] + _tar_of(b"\0" * 5_000_000))
    assert len(endless) < 10_000
    with pytest.raises(Refusal, match="unpacks to more than any board is"):
        board.load(endless, "endless.tgz")
    with pytest.raises(Refusal, match="unpacks to more than any board is"):
        board.load(zipped({"big": b"\0" * 5_000_000}), "endless.zip")


def _tar_of(data: bytes) -> bytes:
    held = io.BytesIO()
    with tarfile.open(fileobj=held, mode="w") as archive:
        info = tarfile.TarInfo("big")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return held.getvalue()


STEP = """ISO-10303-21;
HEADER; FILE_DESCRIPTION(('a made-up heatsink'),'2;1'); ENDSEC;
DATA;
#1=(LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.));
#10=CARTESIAN_POINT('',(0.,0.,0.));
#11=CARTESIAN_POINT('',(40.,0.,0.));
#12=CARTESIAN_POINT('',(40.,25.5,0.));
#13=CARTESIAN_POINT('',(0.,25.5,1.2E1));
#14=CARTESIAN_POINT('',(-10.,5.,3.));
#90=MANIFOLD_SOLID_BREP('heatsink',#80);
ENDSEC;
END-ISO-10303-21;
"""


def test_a_step_file_is_refused_for_parasitics_with_its_solids_size_as_geometry_only() -> None:
    assert formats.step_size(STEP) == pytest.approx((50.0, 25.5, 12.0))  # by its corner points
    with pytest.raises(Refusal) as refused:
        board.load(STEP.encode(), "heatsink.step")
    assert "it holds shapes and no nets, so no loop inductance can honestly be read from it" in refused.value.reason
    assert "about 50 × 25.5 × 12 mm" in refused.value.reason and "geometry only" in refused.value.reason
    assert "KiCad" in refused.value.fix and "IPC-2581" in refused.value.fix
    # An assembly, two solids or lengths in a unit not said: the refusal alone, with no size.
    for other in (
        STEP + "#95=NEXT_ASSEMBLY_USAGE_OCCURRENCE('1','','',#5,#6,$);",
        STEP.replace("#90=", "#89=MANIFOLD_SOLID_BREP('b',#81);\n#90="),
        STEP.replace(".MILLI.,", "$,").replace(".METRE.", ".INCH."),
    ):
        assert formats.step_size(other) is None
        with pytest.raises(Refusal) as refused:
            board.load(other.encode(), "heatsink.stp")
        assert "geometry only" not in refused.value.reason


@pytest.mark.parametrize(
    "data, name, said, fix",
    [
        (
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 600,
            "inverter.PcbDoc",
            "Altium's own format, which is closed and not read",
            "export IPC-2581 (File > Fabrication Outputs) or ODB++",
        ),
        (b"text", "inverter.pcbdoc", "Altium's own format", "export IPC-2581"),
        (b"", "empty.kicad_pcb", "is empty", "KiCad"),
        (b"   \n", "blank.xml", "is empty", "KiCad"),
        (b"\xff\x00\x81\x02binary", "board.brd", "not text in UTF-8", "IPC-2581"),
        (b"G04 a gerber*\nG01*\n", "copper.gbr", "not a board file of a kind read here", "IPC-2581"),
        (b"l_loop_nh: 5\n", "layout.yaml", "not a board file of a kind read here", "IPC-2581"),
    ],
)
def test_a_file_of_another_kind_is_refused_with_what_to_give(data, name, said, fix) -> None:
    with pytest.raises(Refusal) as refused:
        board.load(data, name)
    assert said in refused.value.reason
    assert fix in refused.value.fix
    assert refused.value.field == "board"


def test_a_file_that_is_too_large_or_not_there_is_refused(monkeypatch, tmp_path) -> None:
    with pytest.raises(Refusal, match=r"cannot read the board file gone\.kicad_pcb"):
        board.load(tmp_path / "gone.kicad_pcb")
    monkeypatch.setattr(formats, "MOST_BYTES", 1000)
    with pytest.raises(Refusal, match="is larger than"):
        board.load(text_of("half_bridge.kicad_pcb").encode(), "half_bridge.kicad_pcb")


@pytest.mark.parametrize("name", ["half_bridge.kicad_pcb", "half_bridge.xml", "three_phase.kicad_pcb"])
def test_a_file_cut_short_anywhere_is_refused_and_never_a_fault(name) -> None:
    """The file cut at forty places, and with a stretch of it doubled or dropped: each is read
    or refused in words. Anything else raised here would be a fault of the reader."""
    whole = text_of(name).encode()
    answers = set()
    for k in range(1, 41):
        at = len(whole) * k // 41
        for damaged in (whole[:at], whole[:at] + whole[at - 200 :], whole[: at - 37] + whole[at:]):
            try:
                made = board.load(damaged, name)
                board.bridge.find(made)
                answers.add("read")
            except Refusal as refused:
                assert refused.reason and refused.field in ("board", "choose", "choose.capacitors")
                answers.add("refused")
    assert "refused" in answers


def test_a_path_or_bytes_or_base64_all_read_the_same_board() -> None:
    path = BOARDS / "half_bridge.kicad_pcb"
    packed = base64.b64encode(path.read_bytes())
    one, two = board.load(path), board.load(base64.b64decode(packed), "half_bridge.kicad_pcb")
    assert [c.ref for c in one.components] == [c.ref for c in two.components]
    assert one.name == two.name == "half_bridge.kicad_pcb"
    # With no name to go by, the file's own first bytes say what it is.
    assert board.load(path.read_bytes()).format == "kicad"
    assert board.load((BOARDS / "half_bridge.xml").read_bytes()).format == "ipc2581"
    assert isinstance(Zone("A", "F.Cu", []), Zone)
