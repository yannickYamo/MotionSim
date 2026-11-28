"""Finding the half bridges on a board from its nets: the right parts and nets on the made-up
boards of tests/fixtures/boards, the user's choice over the guess, and a board with no bridge
refused with what was looked for."""

from __future__ import annotations

from pathlib import Path

import pytest

from motionsim import board
from motionsim.board import bridge, drive
from motionsim.board.model import Board, Component, Layer, Pad, Stackup
from motionsim.errors import Refusal

pytestmark = pytest.mark.timeout(120)

BOARDS = Path(__file__).parent / "fixtures" / "boards"


@pytest.fixture(scope="module")
def boards() -> dict[str, Board]:
    names = ("half_bridge.kicad_pcb", "half_bridge.xml", "three_phase.kicad_pcb", "unhelpful.kicad_pcb")
    return {name: board.load(BOARDS / name) for name in names}


def legs(found: bridge.Found) -> dict[str, tuple[list[str], list[str], list[str]]]:
    return {leg.switch_node: (leg.high_side, leg.low_side, leg.capacitors) for leg in found.legs}


@pytest.mark.parametrize("name", ["half_bridge.kicad_pcb", "half_bridge.xml"])
def test_the_half_bridge_is_found_alike_in_both_formats(boards, name) -> None:
    found = bridge.find(boards[name])
    assert (found.dc_plus, found.dc_minus) == ("VBUS", "GND")
    assert legs(found) == {"SW": (["Q1"], ["Q2"], ["C1", "C2"])}
    # The terminal block has a pad on each of the three nets and is no switch; the pull-down
    # from the gate to ground is no current-sense resistor.
    assert found.candidates["switches"] == ["Q1", "Q2"]
    assert found.legs[0].series == []
    assert [c["ref"] for c in found.candidates["capacitors"]] == ["C1", "C2"]
    assert found.candidates["capacitors"][1]["farads"] == pytest.approx(4.7e-6)


def test_each_switchs_gate_drive_is_found(boards) -> None:
    found = bridge.find(boards["half_bridge.kicad_pcb"])
    high = drive.find_drive(boards["half_bridge.kicad_pcb"], found, found.legs[0], "Q1", {})
    low = drive.find_drive(boards["half_bridge.kicad_pcb"], found, found.legs[0], "Q2", {})
    assert (high.driver, high.resistors, high.gate_net, high.return_net, high.kelvin) == (
        "U1",
        ["R1"],
        "GH",
        "SW",
        False,
    )
    assert (low.driver, low.resistors, low.gate_net, low.return_net, low.kelvin) == ("U1", ["R2"], "GL", "GND", False)


def test_the_three_legs_and_each_ones_nearest_capacitors(boards) -> None:
    found = bridge.find(boards["three_phase.kicad_pcb"])
    assert (found.dc_plus, found.dc_minus) == ("VBUS", "GND")
    assert legs(found) == {
        "SW_U": (["Q1"], ["Q2"], ["C1", "C2"]),
        "SW_V": (["Q3"], ["Q4"], ["C3", "C4"]),
        "SW_W": (["Q5"], ["Q6"], ["C5", "C6"]),
    }
    # The bulk capacitor apart from the legs is offered and not taken, and that is said.
    assert "C7" in [c["ref"] for c in found.candidates["capacitors"]]
    assert any("2 of 7 capacitors" in line for line in found.said)
    assert found.candidates["rails"][0] == {"dc_plus": "VBUS", "dc_minus": "GND", "capacitors": 7, "legs": 3}


def test_names_that_say_nothing_fall_back_to_the_nets(boards) -> None:
    """No net is called a supply and no part a transistor: the supply is the two nets joined
    by capacitors and by two three-net parts in series, and plus is the one the upper
    switch's largest pad (its drain) is on."""
    found = bridge.find(boards["unhelpful.kicad_pcb"])
    assert (found.dc_plus, found.dc_minus) == ("N$1", "N$2")
    assert legs(found) == {"N$3": (["A1"], ["A2"], ["A3", "A4"])}
    assert any("largest pads" in line for line in found.said)
    gate = drive.find_drive(boards["unhelpful.kicad_pcb"], found, found.legs[0], "A1", {})
    assert (gate.driver, gate.resistors) == ("A5", ["A6"])


def test_what_the_user_names_is_taken_over_the_guess(boards) -> None:
    three = boards["three_phase.kicad_pcb"]
    assert legs(bridge.find(three, {"switch_nodes": ["SW_V"]})) == {"SW_V": (["Q3"], ["Q4"], ["C3", "C4"])}
    assert list(legs(bridge.find(three, {"high_side": ["Q5"]}))) == ["SW_W"]
    assert legs(bridge.find(three, {"capacitors": ["C7"], "switch_nodes": ["SW_U"]}))["SW_U"][2] == ["C7"]
    # Even against the names: the supply the other way up makes the other switch the high side.
    turned = bridge.find(boards["half_bridge.kicad_pcb"], {"dc_plus": "GND", "dc_minus": "VBUS"})
    assert (turned.dc_plus, turned.dc_minus) == ("GND", "VBUS")
    assert legs(turned) == {"SW": (["Q2"], ["Q1"], ["C1", "C2"])}


def test_a_named_gate_driver_is_taken_and_one_that_is_not_there_refused(boards) -> None:
    half = boards["half_bridge.kicad_pcb"]
    found = bridge.find(half)
    assert drive.find_drive(half, found, found.legs[0], "Q1", {"gate_driver": ["U1"]}).driver == "U1"
    with pytest.raises(Refusal) as refused:
        drive.find_drive(half, found, found.legs[0], "Q1", {"gate_driver": ["U9"]})
    assert refused.value.field == "choose.gate_driver"
    # A part that is there and drives nothing: the drive is not found, in words, and nothing is refused.
    assert "no gate driver was found for Q1" in drive.find_drive(
        half, found, found.legs[0], "Q1", {"gate_driver": ["J1"]}
    )


@pytest.mark.parametrize(
    "choose, said, field",
    [
        ({"dc_plus": "VBAT"}, "no half bridge was found", "choose"),
        ({"dc_plus": "VBAT", "dc_minus": "GND"}, "no net called 'VBAT'", "choose.dc_plus"),
        ({"switch_nodes": ["GH"]}, "no leg was found between VBUS and GND at GH", "choose.switch_nodes"),
        ({"high_side": ["Q2"]}, "Q2 has no pad on VBUS", "choose.high_side"),
        ({"capacitors": ["C3"]}, "C3 is not across VBUS and GND", "choose.capacitors"),
        ({"capacitors": ["C99"]}, "no part called 'C99'", "choose.capacitors"),
        ({"capacitors": ["C1", "C2", 7]}, "has to be a list of names", "choose.capacitors"),
        ({"dc_plus": ["VBUS", "GND"]}, "has to be one name", "choose.dc_plus"),
    ],
)
def test_a_choice_that_cannot_be_is_refused_with_its_name(boards, choose, said, field) -> None:
    with pytest.raises(Refusal) as refused:
        bridge.find(boards["half_bridge.kicad_pcb"], choose)
    assert said in refused.value.reason
    assert refused.value.field == field
    assert refused.value.fix


def pads(ref: str, nets: list[str], x: float = 0.0, big: int = 0) -> Component:
    made = [
        Pad(ref, str(k + 1), net, x + 2.0 * k, 0.0, 3.0 if k == big else 1.0, 3.0 if k == big else 1.0, ("F.Cu",))
        for k, net in enumerate(nets)
    ]
    return Component(ref, "", "made_up", x, 0.0, "F.Cu", made)


def made_up(parts: list[Component]) -> Board:
    return Board("made-up", "board", Stackup([Layer("F.Cu", 0.035, 0.0), Layer("B.Cu", 0.035, 1.5)], False), parts)


def test_a_board_with_no_bridge_is_refused_with_what_was_looked_for() -> None:
    """Two regulators one after the other, each with a capacitor: three-net parts in series
    between two nets joined by capacitors, and no half bridge. Each regulator has a pad on
    the other supply net too, which a switch of a leg has not."""
    parts = [
        pads("U1", ["VIN", "5V", "GND"]),
        pads("U2", ["5V", "3V3", "GND"]),
        pads("C1", ["VIN", "GND"]),
        pads("C2", ["5V", "GND"]),
        pads("C3", ["3V3", "GND"]),
    ]
    with pytest.raises(Refusal) as refused:
        bridge.find(made_up(parts))
    assert "no half bridge was found on this board" in refused.value.reason
    assert "two nets joined by a capacitor and by two transistor-like parts in series" in refused.value.reason
    # What to do is said as a person would do it; which choices are meant is the field.
    assert "the two supply nets" in refused.value.fix and "the switch node" in refused.value.fix
    assert '"choose"' not in refused.value.fix and "dc_plus" not in refused.value.fix
    assert refused.value.field == "choose"


def test_a_bridge_with_no_capacitor_is_refused_for_the_capacitor() -> None:
    parts = [pads("Q1", ["VBUS", "SW", "GH"]), pads("Q2", ["SW", "GND", "GL"])]
    with pytest.raises(Refusal, match="no half bridge was found"):
        bridge.find(made_up(parts))
    with pytest.raises(Refusal) as refused:
        bridge.find(made_up(parts), {"dc_plus": "VBUS", "dc_minus": "GND"})
    assert "no decoupling capacitor was found across VBUS and GND" in refused.value.reason
    assert refused.value.field == "choose.capacitors"


def test_a_current_sense_resistor_under_the_low_side_is_part_of_the_leg() -> None:
    parts = [
        pads("Q1", ["VBUS", "SW", "GH"]),
        pads("Q2", ["SW", "ISENSE", "GL"]),
        pads("R1", ["ISENSE", "GND"]),
        pads("R2", ["GL", "GND"]),  # the gate's pull-down: not a shunt
        pads("C1", ["VBUS", "GND"]),
    ]
    found = bridge.find(made_up(parts))
    assert legs(found) == {"SW": (["Q1"], ["Q2"], ["C1"])}
    assert (found.legs[0].series, found.legs[0].low_net) == (["R1"], "ISENSE")


def test_a_kelvin_source_pad_is_told_from_the_drivers_return() -> None:
    """The low-side switch has a fourth pad on a net of its own that only the driver is also
    on: the gate current returns there, and not through the power source."""
    parts = [
        pads("Q1", ["VBUS", "SW", "GH"]),
        pads("Q2", ["SW", "GND", "GL", "KS_L"]),
        pads("U1", ["GH", "SW", "GL", "KS_L", "VCC", "IN"]),
        pads("C1", ["VBUS", "GND"]),
    ]
    made = made_up(parts)
    found = bridge.find(made)
    low = drive.find_drive(made, found, found.legs[0], "Q2", {})
    assert (low.gate_net, low.return_net, low.kelvin) == ("GL", "KS_L", True)
    high = drive.find_drive(made, found, found.legs[0], "Q1", {})
    assert (high.gate_net, high.return_net, high.kelvin) == ("GH", "SW", False)


def test_paralleled_switches_are_one_leg() -> None:
    parts = [
        pads("Q1", ["VBUS", "SW", "GH"]),
        pads("Q2", ["VBUS", "SW", "GH"], x=10),
        pads("Q3", ["SW", "GND", "GL"]),
        pads("Q4", ["SW", "GND", "GL"], x=10),
        pads("C1", ["VBUS", "GND"]),
    ]
    assert legs(bridge.find(made_up(parts))) == {"SW": (["Q1", "Q2"], ["Q3", "Q4"], ["C1"])}
