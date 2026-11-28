"""A board file through the service: the made-up three-phase board's figures lie in the ranges
a layout file takes, each comes with its band and what it rests on, and the layout handed to
the switching event moves its overshoot the way the loop inductance says."""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

import pytest

from motionsim import board, design, page
from motionsim.event.layout import FIELD, FIGURES, read_layout
from motionsim.service import routes

pytestmark = pytest.mark.timeout(240)

BOARDS = Path(__file__).parent / "fixtures" / "boards"
SIX = ["l_loop_nh", "l_cs_nh", "l_gate_nh", "r_loop_mohm", "c_dc_uf", "esl_nh"]


@pytest.fixture(scope="module")
def ws(tmp_path_factory):
    return page.Workspace(Path(tmp_path_factory.mktemp("board")))


def ask(ws, route: str, body: dict) -> dict:
    return json.loads(page.call(route, json.dumps(body), ws))


def sent(name: str, **more) -> dict:
    return {"name": name, "text": (BOARDS / name).read_text(encoding="utf-8"), **more}


@pytest.fixture(scope="module")
def three(ws) -> dict:
    got = ask(ws, "/api/board", sent("three_phase.kicad_pcb"))
    assert got["status"] == 200, got
    return got["body"]


@pytest.fixture(scope="module")
def half(ws) -> dict:
    got = ask(ws, "/api/board", sent("half_bridge.kicad_pcb"))
    assert got["status"] == 200, got
    return got["body"]


def test_the_answer_has_the_shape_the_service_says(three) -> None:
    assert list(three) == [
        "format",
        "name",
        "stackup",
        "nets",
        "parts",
        "bridges",
        "candidates",
        "taken",
        "figures",
        "layout",
        "warnings",
        "hints",
    ]
    assert (three["format"], three["name"], three["parts"], three["taken"]) == (
        "kicad",
        "three_phase.kicad_pcb",
        22,
        "SW_U",
    )
    assert three["stackup"]["layers"][1] == {"name": "In1.Cu", "copper_um": 35.0, "depth_mm": 0.2525}
    assert (three["nets"]["dc_plus"], three["nets"]["dc_minus"], three["nets"]["largest"][0]["name"]) == (
        "VBUS",
        "GND",
        "GND",
    )
    assert [b["leg"] for b in three["bridges"]] == ["SW_U", "SW_V", "SW_W"]
    first = three["bridges"][0]
    assert list(first) == [
        "leg",
        "switch_node",
        "high_side",
        "low_side",
        "capacitors",
        "series",
        "gate_drive",
        "figures",
        "mesh",
    ]
    assert first["gate_drive"]["high_side"] | {"figures": None} == {
        "figures": None,
        "found": True,
        "switch": "Q1",
        "driver": "U1",
        "resistors": ["R1"],
        "gate_net": "GH_U",
        "return_net": "SW_U",
        "kelvin": False,
    }
    assert list(first["gate_drive"]["low_side"]["figures"]) == ["l_gate_nh", "l_cs_nh"]
    assert list(three["candidates"]) == ["rails", "switch_nodes", "switches", "capacitors", "high_side", "low_side"]
    assert three["figures"] == first["figures"]
    assert any("3 legs were found" in line for line in three["warnings"])
    json.dumps(three, allow_nan=False)


def test_no_figure_is_a_bare_number(three) -> None:
    for bridge in three["bridges"]:
        assert list(bridge["figures"]) == SIX
        for key, fig in bridge["figures"].items():
            assert list(fig)[:6] == ["value", "low", "high", "unit", "assumed", "rests_on"]
            assert fig["unit"] == FIGURES[key][0]
            assert fig["low"] <= fig["value"] <= fig["high"] and fig["low"] < fig["high"], key
            assert fig["rests_on"] and all(isinstance(line, str) and line for line in fig["rests_on"])
    loop = three["figures"]["l_loop_nh"]
    assert loop["parts"]["board_nh"] + loop["parts"]["package_nh"] == pytest.approx(loop["value"], rel=1e-3)
    assert loop["assumed"] and loop["parts"]["package_nh"] == 8.0  # two surface-mount packages of 4 nH, said as assumed
    said = " ".join(loop["rests_on"])
    for word in (
        "C1, C2",
        "Q1",
        "Q2",
        "F.Cu and In1.Cu",
        "via positions",
        "bars of",
        "least magnetic energy",
        "assumed for Q1",
        "25% under",
    ):
        assert word in said, word


def test_the_three_phase_boards_figures_lie_where_a_layout_file_takes_them(three) -> None:
    for bridge in three["bridges"]:
        for key, fig in bridge["figures"].items():
            _, _, low, high, _ = FIGURES[key]
            assert low <= fig["value"] <= high, key
    # The three legs are the same copper side by side: their loops agree.
    loops = [b["figures"]["l_loop_nh"]["parts"]["board_nh"] for b in three["bridges"]]
    assert max(loops) == pytest.approx(min(loops), rel=0.05)
    # A loop on a plane 0.2 mm under the top copper: a few nanohenries of board, not tens.
    assert 2.0 < loops[0] < 10.0
    # Two 1 µF capacitors of 1206 by each leg: 2 µF, and half of one's 1.0 nH.
    assert three["figures"]["c_dc_uf"]["value"] == 2.0
    assert three["figures"]["esl_nh"]["value"] == 0.5 and three["figures"]["esl_nh"]["assumed"]


def test_the_layout_text_is_a_layout_file_holding_the_same_figures(three) -> None:
    detail = read_layout(three["layout"], "from the board")
    for key in SIX:
        assert getattr(detail, FIELD[key]) == pytest.approx(three["figures"][key]["value"] * FIGURES[key][1], rel=1e-3)
    assert "leg SW_U" in three["layout"].splitlines()[0]


def over(body: dict) -> float:
    return body["turn_off"]["v_peak"] - body["v_dc"]


def test_the_boards_layout_moves_the_events_overshoot_as_its_loop_says(ws, three, half) -> None:
    """The made-up 100 V MOSFET in its leaded package is assumed a 20 nH loop where none is
    given. The three-phase board, its return on a plane under the switches, comes to less than
    that and the tracked half bridge to more: the turn-off overshoot follows, less and more."""
    start = design.starting_setup("example-mosfet", ws)
    event = lambda extra: ask(ws, "/api/event", {**start, "device": "example-mosfet", **extra})
    assumed = event({})["body"]
    assert assumed["used"]["l_loop"] == pytest.approx(20e-9)
    assert three["figures"]["l_loop_nh"]["value"] < 20.0 < half["figures"]["l_loop_nh"]["value"]
    tight, loose = (event({"event": {"layout": made["layout"]}}) for made in (three, half))
    assert tight["status"] == loose["status"] == 200, (tight, loose)
    assert tight["body"]["used"]["l_loop"] == pytest.approx(three["figures"]["l_loop_nh"]["value"] * 1e-9, rel=1e-3)
    assert not {"l_loop", "l_cs", "l_g"} & {a["field"] for a in tight["body"]["assumed"]}
    assert over(tight["body"]) < over(assumed) < over(loose["body"])
    # With the loop's own figures alone, nothing else of the layout moving the edges, the same order.
    only = lambda made: "\n".join(
        line for line in made["layout"].splitlines() if line.startswith(("l_loop_nh", "esl_nh"))
    )
    tight_loop, loose_loop = (event({"event": {"layout": only(made)}})["body"] for made in (three, half))
    assert over(tight_loop) < 0.9 * over(assumed) and over(loose_loop) > 1.5 * over(assumed)


def test_the_same_board_in_both_formats_gives_the_same_figures(ws, half) -> None:
    xml = ask(ws, "/api/board", sent("half_bridge.xml"))["body"]
    assert xml["format"] == "ipc2581"
    for key in SIX:
        assert xml["figures"][key]["value"] == pytest.approx(half["figures"][key]["value"], rel=0.01), key
    # A loop of 2 mm track some 12 by 30 mm: tens of nanohenries of board, as the rectangle formula gives.
    assert 25.0 < half["figures"]["l_loop_nh"]["parts"]["board_nh"] < 50.0


def test_what_was_assumed_widens_the_band_and_is_said(ws, three) -> None:
    one_leg = {"choose": {"switch_nodes": ["SW_U"]}}
    drawn = ask(ws, "/api/board", sent("three_phase_unfilled.kicad_pcb", **one_leg))["body"]
    width = lambda fig: (fig["high"] - fig["low"]) / fig["value"]
    assert [b["leg"] for b in drawn["bridges"]] == ["SW_U"]
    assert width(drawn["figures"]["l_loop_nh"]) > width(three["figures"]["l_loop_nh"])
    assert any("outline only" in line for line in drawn["warnings"])
    assert "a pour was taken from its outline, not its fill" in " ".join(drawn["figures"]["l_loop_nh"]["rests_on"])
    plain = ask(ws, "/api/board", sent("unhelpful.kicad_pcb"))["body"]
    assert plain["stackup"]["assumed"] and "no stack-up in the file" in plain["stackup"]["said"]
    assert "the copper's thickness was assumed" in " ".join(plain["figures"]["l_loop_nh"]["rests_on"])
    # No footprint here says what package or what case: nothing is added for either, and that is said.
    assert plain["figures"]["l_loop_nh"]["parts"]["package_nh"] == 0.0 and not plain["figures"]["l_loop_nh"]["assumed"]
    assert "package is not known" in " ".join(plain["figures"]["l_loop_nh"]["rests_on"])
    esl = plain["figures"]["esl_nh"]
    assert (esl["value"], esl["low"], esl["high"]) == (None, None, None) and esl["rests_on"][0].startswith(
        "not worked out: "
    )
    assert "# esl_nh:" in plain["layout"] and read_layout(plain["layout"]).esl is None


def test_the_users_choice_reaches_the_figures(ws, half) -> None:
    one = ask(ws, "/api/board", sent("half_bridge.kicad_pcb", choose={"capacitors": ["C1"]}))["body"]
    assert one["bridges"][0]["capacitors"] == ["C1"]
    assert one["figures"]["c_dc_uf"]["value"] == pytest.approx(0.1)
    # C1 alone is the capacitor nearer the switches: the loop is no larger without the other.
    assert one["figures"]["l_loop_nh"]["value"] == pytest.approx(half["figures"]["l_loop_nh"]["value"], rel=0.15)
    leg = ask(ws, "/api/board", sent("three_phase.kicad_pcb", choose={"switch_nodes": ["SW_W"], "leg": "SW_W"}))["body"]
    assert leg["taken"] == "SW_W" and "leg SW_W" in leg["layout"]


KELVIN = [
    ('\n  (net 11 "VCC")\n', '\n  (net 11 "VCC")\n  (net 12 "KS")\n'),
    (
        '(pad "4" smd roundrect (at -2.7 1.905) (size 1.5 0.6) (layers "F.Cu" "F.Paste" "F.Mask") (net 3 "GND"))',
        '(pad "4" smd roundrect (at -2.7 1.905) (size 1.5 0.6) (layers "F.Cu" "F.Paste" "F.Mask") (net 12 "KS"))',
    ),
    (
        '(segment (start 5.3 31.905) (end 5.3 52) (width 0.5) (layer "F.Cu") (net 3))',
        '(segment (start 5.3 31.905) (end 5.3 52) (width 0.5) (layer "F.Cu") (net 12))',
    ),
    (
        '(segment (start 5.3 52) (end 22.5 52) (width 0.5) (layer "F.Cu") (net 3))',
        '(segment (start 5.3 52) (end 20 52) (width 0.5) (layer "F.Cu") (net 12))',
    ),
    ('  (segment (start 22.5 52) (end 22.5 48) (width 0.5) (layer "F.Cu") (net 3))\n', ""),
    (
        '(pad "3" smd roundrect (at 2.5 10) (size 1.2 3) (layers "F.Cu" "F.Paste" "F.Mask") (net 3 "GND"))',
        '(pad "3" smd roundrect (at 2.5 10) (size 1.2 3) (layers "F.Cu" "F.Paste" "F.Mask") (net 3 "GND"))\n    (pad "4" smd roundrect (at 0 14) (size 1.2 1.2) (layers "F.Cu" "F.Paste" "F.Mask") (net 12 "KS"))',
    ),
]


def test_a_kelvin_source_pad_makes_the_common_source_inductance_nought(ws, half) -> None:
    """The half bridge with its low-side driver return moved off the power ground onto a pad
    of the switch's own: nothing of the source is shared, and the figure is nought with a band."""
    text = (BOARDS / "half_bridge.kicad_pcb").read_text(encoding="utf-8")
    for old, new in KELVIN:
        assert text.count(old) == 1, old
        text = text.replace(old, new)
    got = ask(ws, "/api/board", {"name": "kelvin.kicad_pcb", "text": text})["body"]
    low = got["bridges"][0]["gate_drive"]["low_side"]
    assert (low["return_net"], low["kelvin"]) == ("KS", True)
    shared = low["figures"]["l_cs_nh"]
    assert (shared["value"], shared["low"]) == (0.0, 0.0) and 0.2 <= shared["high"] < 3.0
    assert "a Kelvin source pad of its own" in shared["rests_on"][0]
    before = half["bridges"][0]["gate_drive"]["low_side"]["figures"]["l_cs_nh"]
    assert before["value"] >= 2.0  # at the least the 2 nH assumed for the package's shared source lead


@pytest.mark.parametrize(
    "body, said, field",
    [
        ({}, "a board file comes with its name", "name"),
        ({"name": "b.kicad_pcb"}, "its text or in base64, one of the two", "text"),
        ({"name": "b.kicad_pcb", "text": "(kicad_pcb)", "data_base64": "KA=="}, "one of the two", "text"),
        ({"name": "b.kicad_pcb", "text": ["(kicad_pcb)"]}, "is not text", "text"),
        ({"name": "b.zip", "data_base64": "not base64!"}, "it is not base64", "data_base64"),
        ({"name": 7, "text": "(kicad_pcb)"}, "comes with its name", "name"),
        (
            {"name": "b.kicad_pcb", "text": "(kicad_pcb (version 20240108))"},
            "no half bridge was found on this board",
            "choose",
        ),
        ({"name": "part.step", "text": "ISO-10303-21;\nDATA;\nENDSEC;\n"}, "it holds shapes and no nets", "board"),
        (
            {
                "name": "b.PcbDoc",
                "data_base64": base64.b64encode(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 64).decode(),
            },
            "Altium's own format",
            "board",
        ),
    ],
)
def test_a_request_that_cannot_be_answered_is_refused_with_reason_fix_and_field(ws, body, said, field) -> None:
    got = ask(ws, "/api/board", body)
    assert got["status"] == 422, got
    assert said in got["body"]["refused"]
    assert got["body"]["field"] == field
    assert got["body"]["fix"]
    # Said to the person who chose the file: which part of the request is at fault is the
    # field's to say, and no name of the request's own is in the words.
    words = got["body"]["refused"] + " " + got["body"]["fix"]
    assert not any(f'"{key}"' in words for key in ("name", "text", "data_base64", "choose")), words


def test_a_choice_it_does_not_take_is_refused_with_the_near_name(ws) -> None:
    got = ask(ws, "/api/board", sent("half_bridge.kicad_pcb", choose={"dc_plu": "VBUS"}))
    assert got["status"] == 422
    assert got["body"] == {
        "refused": "what was chosen holds 'dc_plu', which is not a choice there is",
        "fix": "did you mean dc_plus, the supply's positive net?",
        "field": "choose",
    }
    got = ask(ws, "/api/board", sent("half_bridge.kicad_pcb", choose=["VBUS"]))
    assert (got["status"], got["body"]["field"]) == (422, "choose")
    got = ask(ws, "/api/board", sent("half_bridge.kicad_pcb", choose={"leg": "SW_X"}))
    assert (got["status"], got["body"]["field"]) == (422, "choose.leg")
    assert "the legs found are at SW" in got["body"]["fix"]


def test_an_archive_arrives_in_base64_and_odb_is_refused_in_words(ws) -> None:
    held = io.BytesIO()
    with zipfile.ZipFile(held, "w") as archive:
        archive.writestr("made_up/matrix/matrix", "STEP {\n}\n")
    got = ask(ws, "/api/board", {"name": "made_up.zip", "data_base64": base64.b64encode(held.getvalue()).decode()})
    assert got["status"] == 422
    assert got["body"]["refused"] == "ODB++ is not read yet: export IPC-2581 or give the KiCad file"


def test_a_budget_that_runs_short_is_said_and_the_figure_still_given(ws, half, monkeypatch) -> None:
    """Fewer cells than the copper asks for: the mesh is made coarser and says so. No time for
    the search for the fast edge's current: the steady current's figure stands, which is the
    higher, the band reaches further down, and that is said too."""
    from motionsim.board import figures, solve

    monkeypatch.setattr(figures, "MOST_CELLS", 1500)
    coarse = ask(ws, "/api/board", sent("half_bridge.kicad_pcb"))["body"]
    cells = coarse["bridges"][0]["mesh"]["cells"]
    assert cells[0] * cells[1] <= 1600
    assert any("meshed coarser" in line for line in coarse["warnings"])
    assert coarse["figures"]["l_loop_nh"]["value"] == pytest.approx(half["figures"]["l_loop_nh"]["value"], rel=0.25)
    monkeypatch.undo()

    monkeypatch.setattr(solve, "MOST_STEPS", 1)
    hurried = ask(ws, "/api/board", sent("half_bridge.kicad_pcb"))["body"]
    assert hurried["bridges"][0]["mesh"]["settled"] is False
    loop, settled = hurried["figures"]["l_loop_nh"], half["figures"]["l_loop_nh"]
    assert "stopped early, which leaves the figure high" in " ".join(loop["rests_on"])
    assert settled["value"] <= loop["value"] <= 1.1 * settled["value"]
    assert (loop["value"] - loop["low"]) / loop["value"] > (settled["value"] - settled["low"]) / settled["value"]


def test_the_address_is_known_and_the_python_way_gives_the_same(half) -> None:
    assert routes.known("/api/board")
    own = board.read(BOARDS / "half_bridge.kicad_pcb")
    assert own["figures"] == half["figures"] and own["layout"] == half["layout"]
    assert own["bridges"][0]["mesh"]["settled"] is True


def test_the_example_board_reads(ws) -> None:
    example = Path(__file__).parent.parent / "examples" / "board_half_bridge.kicad_pcb"
    text = example.read_text(encoding="utf-8")
    assert "made-up board" in text
    assert board.bridge.find(board.load(example)).legs[0].switch_node == "SW"
