"""What a board file can say that is not so, and what can be chosen that cannot be: names made
to add lines to the layout, a stack-up no board has, parts that share a name, a switch chosen
for both sides, and every choice sent as something it is not. Each is cleaned, cautioned or
refused in words; none is a fault and none moves a figure it has no say in."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from motionsim import board, page
from motionsim.board import model
from motionsim.errors import Refusal
from motionsim.event.layout import FIELD, FIGURES, read_layout
from motionsim.service import routes

pytestmark = pytest.mark.timeout(280)

BOARDS = Path(__file__).parent / "fixtures" / "boards"
HALF = (BOARDS / "half_bridge.kicad_pcb").read_text(encoding="utf-8")
HALF_XML = (BOARDS / "half_bridge.xml").read_text(encoding="utf-8")
SIX = ["l_loop_nh", "l_cs_nh", "l_gate_nh", "r_loop_mohm", "c_dc_uf", "esl_nh"]


@pytest.fixture(scope="module")
def ws(tmp_path_factory):
    return page.Workspace(Path(tmp_path_factory.mktemp("choices")))


@pytest.fixture(scope="module")
def half() -> dict:
    return board.read(HALF.encode(), "half_bridge.kicad_pcb")


def quoted(name: str) -> str:
    """A name as KiCad writes it inside quotes."""
    return name.replace("\\", "\\\\").replace('"', '\\"')


def renamed(net: str, name: str) -> str:
    """The half bridge with one of its nets called something else, everywhere it is named."""
    return HALF.replace(f'"{net}"', f'"{quoted(name)}"')


def same_figures(answer: dict, as_in: dict) -> None:
    """The layout's text, read as the switching event reads it, holds the figures worked out
    and nothing else; and they are the figures of the board whatever its nets are called."""
    detail = read_layout(answer["layout"], "from the board")
    for key in SIX:
        value = answer["figures"][key]["value"]
        assert value == as_in["figures"][key]["value"], key
        assert getattr(detail, FIELD[key]) == pytest.approx(value * FIGURES[key][1], rel=1e-3), key
    assert len(answer["layout"].splitlines()) == len(as_in["layout"].splitlines())


INJECTED = [
    "SW\nl_loop_nh: 1",
    "SW\r\nl_loop_nh: 1\r\nl_cs_nh: 0.01",
    "SW l_gate_nh: 1",
    "SW\x0bl_loop_nh: 1",
    "SW\x85esl_nh: 0.01",
    "SW # \nc_dc_uf: 1000",
    "\nl_loop_nh: 1\n",
    "SW: {l_loop_nh: 1}",
    "x" * 10_000,
    "SW\t\t  node",
    'SW "quoted" \\ back',
    "SW\x00\x1b[31m",
    "‮WS",
]


@pytest.mark.parametrize("name", INJECTED)
def test_a_net_name_made_to_add_a_figure_to_the_layout_adds_none(name, half) -> None:
    """The layout's text is read by the switching event: a line end in the name of the leg's
    switch node would otherwise put a line of the name's own into it, and that line a figure."""
    answer = board.read(renamed("SW", name).encode(), "half_bridge.kicad_pcb")
    same_figures(answer, half)
    leg = answer["taken"]
    assert leg == " ".join(leg.split()) and leg.isprintable() and 0 < len(leg) <= model.LONGEST_NAME
    assert len(json.dumps(answer)) < 2 * len(json.dumps(half)), "a long name is said once in full, at the most"


def test_a_name_that_was_cleaned_is_said_to_have_been() -> None:
    answer = board.read(renamed("SW", "SW\nl_loop_nh: 1").encode(), "half_bridge.kicad_pcb")
    assert answer["taken"] == "SW l_loop_nh: 1"
    assert any("shown shortened and on one line" in line for line in answer["warnings"])
    assert not any("shown shortened" in line for line in board.read(HALF.encode(), "h.kicad_pcb")["warnings"])


def test_two_long_names_that_differ_only_at_their_end_stay_two_nets(half) -> None:
    """Cut to eighty characters they would be one name, and the supply's two nets one net."""
    long = "N" * 200
    text = renamed("VBUS", long + "_PLUS").replace('"GND"', f'"{long}_MINUS"')
    answer = board.read(text.encode(), "half_bridge.kicad_pcb")
    plus, minus = answer["nets"]["dc_plus"], answer["nets"]["dc_minus"]
    assert plus != minus and len(plus) <= model.LONGEST_NAME and len(minus) <= model.LONGEST_NAME
    for key in SIX:
        assert answer["figures"][key]["value"] == half["figures"][key]["value"], key


def test_the_same_holds_for_a_name_in_an_ipc_file(half) -> None:
    hostile = HALF_XML.replace('"SW"', '"SW&#10;l_loop_nh: 1"')
    assert hostile != HALF_XML
    answer = board.read(hostile.encode(), "half_bridge.xml")
    assert answer["taken"] == "SW l_loop_nh: 1"
    read = read_layout(answer["layout"], "from the board")
    assert read.l_loop == pytest.approx(answer["figures"]["l_loop_nh"]["value"] * 1e-9, rel=1e-3)


def test_the_files_own_name_can_add_no_line_either(half) -> None:
    answer = board.read(HALF.encode(), "half.kicad_pcb\nl_loop_nh: 1\n" + "n" * 5000)
    same_figures(answer, half)
    assert "\n" not in answer["name"] and len(answer["name"]) <= 200


names = st.text(
    alphabet=st.one_of(
        st.sampled_from(list("\n\r\t\x0b\x0c\x1c\x1d\x1e\x85   #:{}[]'\"\\-|>&*!%@`,")),
        st.characters(blacklist_categories=("Cs",)),
    ),
    min_size=1,
    max_size=300,
)
figure_lines = st.sampled_from(SIX).flatmap(lambda key: st.just(f"\n{key}: 1\n"))


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow]
)
@given(
    name=st.one_of(names, st.tuples(names, figure_lines, names).map("".join)),
    which=st.sampled_from(["SW", "VBUS", "GND"]),
)
def test_whatever_a_net_is_called_the_layout_reads_back_as_the_figures_worked_out(name, which, half) -> None:
    text = renamed(which, name)
    try:
        answer = board.read(text.encode("utf-8", "replace"), "half_bridge.kicad_pcb")
    except Refusal:
        return  # a name that makes two nets one, or no net at all: refused, which injects nothing
    detail = read_layout(answer["layout"], "from the board")
    for key in SIX:
        value = answer["figures"][key]["value"]
        if value is not None and FIGURES[key][2] <= value <= FIGURES[key][3]:
            assert getattr(detail, FIELD[key]) == pytest.approx(value * FIGURES[key][1], rel=1e-3), key
    assert len(answer["layout"].splitlines()) == 8


# --- a stack-up no board has


def stack(text: str, **changed: str) -> str:
    """The made-up three-phase board's stack-up with a layer's thickness written otherwise."""
    for layer, thickness in changed.items():
        text, count = re.subn(
            rf'(\(layer "{re.escape(layer)}" \(type "[a-z]+"\) \(thickness )[0-9.]+', rf"\g<1>{thickness}", text
        )
        assert count == 1, layer
    return text


THREE = (BOARDS / "three_phase.kicad_pcb").read_text(encoding="utf-8")
ONE_LEG = {"switch_nodes": ["SW_U"]}


@pytest.fixture(scope="module")
def three() -> dict:
    return board.read(THREE.encode(), "three_phase.kicad_pcb", ONE_LEG)


@pytest.mark.parametrize(
    "changed, said",
    [
        ({"dielectric 1": "0"}, "between F.Cu and In1.Cu"),
        ({"dielectric 1": "1e-9"}, "between F.Cu and In1.Cu"),
        ({"dielectric 1": "0.001"}, "between F.Cu and In1.Cu"),
        ({"dielectric 2": "1e6"}, "between In1.Cu and In2.Cu"),
        ({"dielectric 3": "25"}, "between In2.Cu and B.Cu"),
        ({"F.Cu": "50"}, "gives F.Cu a copper of 50 mm"),
        ({"In1.Cu": "0.0001"}, "gives In1.Cu a copper of 0.0001 mm"),
    ],
)
def test_a_stack_up_no_board_has_is_not_taken_and_the_figure_is_cautioned(changed, said, three) -> None:
    """Two layers a millionth of a millimetre apart close a loop of nearly no area: taken at
    its word, the file would be given a fraction of a nanohenry as its own, and as certain."""
    answer = board.read(stack(THREE, **changed).encode(), "three_phase.kicad_pcb", ONE_LEG)
    assert answer["stackup"]["assumed"] is True
    assert said in answer["stackup"]["said"] and "which no board has" in answer["stackup"]["said"]
    assert "taken evenly through a 1.6 mm board" in answer["stackup"]["said"]
    assert answer["stackup"]["said"] in answer["warnings"]
    loop, sound = answer["figures"]["l_loop_nh"], three["figures"]["l_loop_nh"]
    assert "the heights between the layers were assumed" in " ".join(loop["rests_on"])
    width = lambda fig: (fig["high"] - fig["low"]) / fig["value"]
    assert width(loop) > width(sound)
    # The usual stack-up's loop: of the size of the file's own, never a fraction of a nanohenry.
    assert loop["parts"]["board_nh"] > 0.5 * sound["parts"]["board_nh"]


def test_a_stack_up_at_the_edge_of_what_boards_have_is_taken(three) -> None:
    thin = board.read(stack(THREE, **{"dielectric 1": "0.05", "F.Cu": "0.105"}).encode(), "t.kicad_pcb", ONE_LEG)
    assert thin["stackup"]["assumed"] is False and thin["stackup"]["said"] == ""
    assert thin["figures"]["l_loop_nh"]["parts"]["board_nh"] < three["figures"]["l_loop_nh"]["parts"]["board_nh"]


def test_an_ipc_stack_up_no_board_has_is_not_taken_either() -> None:
    sound = board.read(HALF_XML.encode(), "half_bridge.xml")
    assert sound["stackup"]["assumed"] is False
    rows = re.findall(r'<StackupLayer [^>]*thickness="([0-9.]+)"', HALF_XML)
    assert rows, "the made-up file gives its layers' thicknesses"
    thickest = max(rows, key=float)
    wrong = HALF_XML.replace(f'thickness="{thickest}"', 'thickness="0.000001"')
    answer = board.read(wrong.encode(), "half_bridge.xml")
    assert answer["stackup"]["assumed"] is True and "which no board has" in answer["stackup"]["said"]


# --- what is chosen


def ask(ws, choose) -> tuple[int, dict]:
    return routes.dispatch("/api/board", {"name": "half_bridge.kicad_pcb", "text": HALF, "choose": choose}, ws)


def test_a_switch_chosen_for_both_sides_is_refused_in_words(ws) -> None:
    status, body = ask(ws, {"high_side": ["Q1"], "low_side": ["Q1"]})
    assert status == 422, body
    assert body["refused"] == "Q1 was chosen for both sides: a switch is on the high side or on the low side"
    assert body["field"] == "choose.low_side" and body["fix"]


def test_parts_that_share_a_reference_are_refused_in_words(ws) -> None:
    for text in (HALF.replace('"Q2"', '"Q1"'), re.sub(r'"(Q|C|U|R)\d+"', r'"\g<1>1"', HALF)):
        status, body = routes.dispatch("/api/board", {"name": "twice.kicad_pcb", "text": text}, ws)
        assert status == 422, body
        assert "more than one part of this board is called" in body["refused"] and "Q1" in body["refused"]
        assert body["field"] == "board" and "reference designator of its own" in body["fix"]


def test_a_switch_chosen_for_the_side_it_is_not_on_is_refused_with_the_net_it_lacks(ws) -> None:
    status, body = ask(ws, {"high_side": ["Q2"]})
    assert (status, body["field"]) == (422, "choose.high_side")
    assert body["refused"] == "Q2 has no pad on VBUS, so it is not a high-side switch"
    assert "VBUS" in body["fix"] and "choose" not in body["fix"].replace("choose a part", "")
    status, body = ask(ws, {"low_side": ["C1"]})
    assert (status, body["field"]) == (422, "choose.low_side")
    assert "do not make a leg" in body["refused"]


def test_the_answer_says_which_switches_can_be_on_each_side_of_each_leg(three, half) -> None:
    """For the page's lists: a low-side switch is not offered for the high side."""
    assert half["candidates"]["high_side"] == {"SW": ["Q1"]} and half["candidates"]["low_side"] == {"SW": ["Q2"]}
    whole = board.read(THREE.encode(), "three_phase.kicad_pcb", {"switch_nodes": ["SW_U", "SW_W"]})
    assert whole["candidates"]["high_side"] == {"SW_U": ["Q1"], "SW_W": ["Q5"]}
    assert whole["candidates"]["low_side"] == {"SW_U": ["Q2"], "SW_W": ["Q6"]}
    for side in ("high_side", "low_side"):
        for refs in whole["candidates"][side].values():
            assert set(refs) <= set(whole["candidates"]["switches"])


def test_a_caution_a_choice_answers_says_so_in_words_and_names_the_choice_apart() -> None:
    """The words are a person's, on the page and off it; the name a program sends is beside
    them, for whatever shows the caution to lead to the right control."""
    answer = board.read(THREE.encode(), "three_phase.kicad_pcb")
    hints = {hint["field"]: hint["said"] for hint in answer["hints"]}
    assert set(hints) == {"leg", "capacitors"}
    assert hints["leg"].endswith("Another leg can be chosen") and "3 legs were found" in hints["leg"]
    assert hints["capacitors"].endswith("Others can be chosen")
    assert all(hint["said"] in answer["warnings"] for hint in answer["hints"])
    spoken = " ".join(answer["warnings"])
    for word in ('"choose"', "Say leg", "dc_plus", "switch_nodes", "under capacitors"):
        assert word not in spoken, word
    from motionsim.board import CHOICES

    assert all(hint["field"] in CHOICES for hint in answer["hints"])


WRONG = [None, [], {}, 0, 1, -1, 3.5, True, "", "Q1", "SW", "VBUS", "GND", "nothing of that name", "x" * 100_000]
WRONG += [["Q1"], ["SW"], ["Q1", "Q1"], ["Q1", "Q2"], [None], [[]], [{}], [1], {"a": 1}, [["Q1"]], {"Q1": ["Q1"]}]
FIELDS = ["dc_plus", "dc_minus", "switch_nodes", "high_side", "low_side", "capacitors", "gate_driver", "leg"]


def deep(levels: int):
    out: list = []
    for _ in range(levels):
        out = [out]
    return out


@pytest.mark.parametrize("field", FIELDS)
def test_a_choice_of_any_kind_is_answered_or_refused_and_never_a_fault(field, ws) -> None:
    for value in [*WRONG, deep(50), {"deep": deep(50)}]:
        status, body = ask(ws, {field: value})
        assert status in (200, 422), (field, repr(value)[:60], body)
        if status == 422:
            assert body["refused"] and len(body["refused"]) < 600 and body["field"].startswith(("choose", "board"))


CONTRADICTORY = [
    {"dc_plus": "GND", "dc_minus": "GND"},
    {"dc_plus": "GND", "dc_minus": "VBUS"},
    {"dc_plus": "SW", "dc_minus": "SW"},
    {"dc_plus": "SW"},
    {"dc_minus": "SW"},
    {"dc_plus": "VBUS", "dc_minus": "SW"},
    {"switch_nodes": ["VBUS"]},
    {"switch_nodes": ["GND", "SW"]},
    {"switch_nodes": ["SW"], "leg": "GND"},
    {"high_side": ["Q1"], "low_side": ["Q1"]},
    {"high_side": ["Q2"], "low_side": ["Q1"]},
    {"high_side": ["Q1", "Q2"]},
    {"low_side": ["Q1", "Q2"]},
    {"high_side": ["C1"], "low_side": ["C2"]},
    {"high_side": ["U1"], "low_side": ["U1"]},
    {"low_side": ["U1"]},
    {"high_side": ["U1"]},
    {"capacitors": ["Q1"]},
    {"capacitors": ["C1", "C1", "C1"]},
    {"capacitors": ["U1"]},
    {"capacitors": ["C1"], "high_side": ["C1"]},
    {"gate_driver": ["Q1"]},
    {"gate_driver": ["Q1", "Q2"]},
    {"gate_driver": ["C1"]},
    {"gate_driver": ["U1"], "high_side": ["U1"]},
    {"dc_plus": "GND", "dc_minus": "VBUS", "high_side": ["Q2"], "low_side": ["Q1"]},
    {"dc_plus": "GND", "dc_minus": "VBUS", "high_side": ["Q1"], "low_side": ["Q2"]},
    {"dc_plus": "GH", "dc_minus": "GL"},
    {"dc_plus": "VBUS", "dc_minus": "GND", "switch_nodes": ["GH"]},
    {"leg": "SW", "switch_nodes": ["SW"], "high_side": ["Q1"], "low_side": ["Q2"], "capacitors": ["C1"]},
]


@pytest.mark.parametrize("choose", CONTRADICTORY, ids=lambda c: ",".join(f"{k}={v}" for k, v in c.items())[:60])
def test_choices_that_contradict_the_board_or_each_other_are_answered_or_refused(choose, ws) -> None:
    status, body = ask(ws, choose)
    assert status in (200, 422), body
    if status == 200:
        json.dumps(body, allow_nan=False)
        assert read_layout(body["layout"], "from the board") is not None


def test_a_request_of_every_wrong_kind_is_refused_and_never_a_fault(ws) -> None:
    for name in (None, 0, [], {}, "", " ", "x" * 100_000, "b.kicad_pcb"):
        for text in (None, 0, [], {}, "", "(", HALF[:200]):
            for packed in (None, 0, [], "!!", ""):
                status, body = routes.dispatch("/api/board", {"name": name, "text": text, "data_base64": packed}, ws)
                assert status == 422, (name, text, packed, body)
    for choose in (0, "x", [], [1], "VBUS", True, 3.5):
        status, body = ask(ws, choose)
        assert status in (200, 422), body
