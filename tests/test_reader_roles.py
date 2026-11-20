"""The reader's checks that tell a switch's figure from a diode's, a rating from the next,
and one kind of transistor from another, held to page text written here."""

from __future__ import annotations

from motionsim.observe.schema import Quantity
from motionsim.observe.verify import _locate, _role_fault, kind_fault

PAGE = """Maximum ratings
Collector-emitter voltage VCES 650 V
Continuous collector current IC 40 A
Pulsed collector current ICM 120 A
Thermal resistance junction-case, IGBT Rth(j-c)Q 0.50 0.60 K/W
Thermal resistance junction-case, diode Rth(j-c)D 0.90 1.05 K/W
"""


def test_a_junction_to_case_figure_is_held_to_the_chip_its_line_names() -> None:
    assert _role_fault(0.50, Quantity.rth_jc_switch, PAGE) is None
    assert _role_fault(0.90, Quantity.rth_jc_diode, PAGE) is None
    assert "diode's" in _role_fault(0.90, Quantity.rth_jc_switch, PAGE)
    assert "switch's" in _role_fault(0.60, Quantity.rth_jc_diode, PAGE)
    # A line that names no chip, as a transistor's sheet prints it, says nothing either way.
    single = "Thermal resistance junction-case Rth(j-c) 0.40 0.50 K/W\n"
    assert _role_fault(0.40, Quantity.rth_jc_switch, single) is None


def test_a_rating_found_only_on_another_ratings_line_is_that_ratings() -> None:
    assert _locate(120.0, Quantity.i_pulsed, 1, PAGE).flag is None
    assert _locate(40.0, Quantity.i_rated, 1, PAGE).flag is None
    flag = _locate(40.0, Quantity.i_pulsed, 1, PAGE).flag
    assert flag is not None and "i rated" in flag


def test_the_kind_of_transistor_is_held_to_the_words_of_the_document() -> None:
    silicon = ["Made Up Devices MU-N-100-60\n100 V, 60 A power MOSFET\n"]
    carbide = ["Made Up Devices MU-S-1200-30\n1200 V, 30 A silicon carbide MOSFET\n"]
    assert kind_fault("Si MOSFET", silicon) is None
    assert kind_fault("SiC MOSFET", carbide) is None
    assert "never names" in kind_fault("SiC MOSFET", silicon)
    assert "names SiC MOSFET" in kind_fault("Si MOSFET", carbide)
    # A page that names no kind at all holds the reading to nothing.
    assert kind_fault("GaN HEMT", ["Ratings\nVDS 650 V\n"]) is None
