"""A typed transistor's figures that may be left empty, and what the tool takes for each
(D160): the highest junction temperature by technology, the plateau as the threshold plus
2 V, the gate-source charge as 1.4 times the gate-drain charge, and a name by its kind.
Each figure taken is said in a note with its own code, and holds the verdict at a caution."""

from __future__ import annotations

from dataclasses import replace

import pytest
import yaml

from motionsim import design, guard, page
from motionsim.engine import OperatingPoint, solve
from motionsim.engine.notes import Code
from motionsim.fit.typed import TEMPLATE, Mistyped, from_figures

FIGURES = yaml.safe_load(TEMPLATE)  # threshold 3.0 V, plateau 4.6 V, Qgs 20 nC, Qgd 14 nC
BARE = {k: v for k, v in FIGURES.items() if k not in ("tj_max", "v_plateau", "q_gs", "part_number", "vendor")}
POINT = OperatingPoint(
    v_dc=48, i_rms=30, modulation_index=0.9, power_factor=0.85, f_sw=20e3, t_sink=60, v_drive=10, rg_on=5, rg_off=5
)


@pytest.mark.parametrize(("technology", "tj_max"), [("Si MOSFET", 175.0), ("SiC MOSFET", 175.0), ("GaN HEMT", 150.0)])
def test_the_highest_junction_temperature_left_empty_is_the_usual_rating_of_the_kind(technology, tj_max) -> None:
    figures = {**FIGURES, "technology": technology, "rds_on_hot": None, "rds_hot_tj": None}
    del figures["tj_max"]
    device = from_figures(figures)
    assert device.ratings.tj_max == tj_max
    assert [(t.figure, t.value, t.unit) for t in device.taken or []] == [("tj_max", tj_max, "°C")]


def test_the_plateau_and_the_gate_source_charge_are_taken_by_their_rules() -> None:
    """3.0 V of threshold gives a 5.0 V plateau; 14 nC across the plateau gives 19.6 nC from
    the gate to the source. The charge at threshold follows as Qgs·Vth/Vpl = 11.76 nC."""
    device = from_figures({k: v for k, v in FIGURES.items() if k not in ("v_plateau", "q_gs")})
    charge = device.switch.charge
    assert charge.v_plateau == pytest.approx(5.0)
    assert charge.q_gs == pytest.approx(19.6e-9)
    assert charge.q_g_th == pytest.approx(19.6e-9 * 3.0 / 5.0, rel=1e-4)
    assert [(t.figure, t.value) for t in device.taken or []] == [("v_plateau", 5.0), ("q_gs", 19.6)]


def test_a_part_with_every_figure_given_carries_nothing_taken_and_its_file_says_none() -> None:
    device = from_figures(FIGURES)
    assert device.taken is None
    assert "taken" not in device.model_dump(exclude_none=True)


def test_each_figure_taken_is_a_note_with_its_code_naming_the_value_used() -> None:
    result = solve(from_figures(BARE), POINT)
    notes = {n.code: n for n in result.notes if getattr(n, "code", None) in guard.CAPS}
    assert set(notes) == {Code.tj_max_taken, Code.plateau_taken, Code.gate_source_charge_taken}
    assert notes[Code.plateau_taken].field == "v_plateau"
    assert "threshold voltage plus 2 V (5 V)" in notes[Code.plateau_taken]
    assert "1.4 times the gate-drain charge (19.6 nC)" in notes[Code.gate_source_charge_taken]
    assert "usual rating of a Si MOSFET (175 °C)" in notes[Code.tj_max_taken]


def test_a_figure_taken_holds_the_verdict_at_a_caution_whatever_else_passes() -> None:
    """The same part with every figure given passes cleanly here; with the three taken it is
    a caution, named under the data, one check for each and each with the box it goes in."""
    given = from_figures(FIGURES)
    taken = from_figures({**FIGURES, "v_plateau": None, "q_gs": None, "tj_max": None})
    calm = replace(POINT, i_rms=10.0, t_dead=2e-7, t_dead_given=True)
    plain = guard.check(given, calm, solve(given, calm), 14.1)
    assert guard.verdict(plain) is guard.Level.ok
    checks = guard.check(taken, calm, solve(taken, calm), 14.1)
    data = [c for c in checks if c.topic == "data" and c.level is guard.Level.caution]
    assert [c.field for c in data] == ["tj_max", "v_plateau", "q_gs"]
    assert guard.verdict(checks) is guard.Level.caution


def test_a_taken_figure_that_does_not_fit_the_rest_is_refused_where_the_datasheet_figure_goes() -> None:
    # 30 nC in all: less than 1.4 × 14 + 14 = 33.6 nC, so the charge taken cannot be right.
    with pytest.raises(Mistyped) as caught:
        from_figures({**FIGURES, "q_gs": None, "q_g": 30})
    assert caught.value.field == "q_gs" and "taken as 1.4 times the gate-drain charge" in str(caught.value)
    # A 5 V gate charge on a part whose plateau is taken as 3 + 2 = 5 V.
    with pytest.raises(Mistyped) as caught:
        from_figures({**FIGURES, "v_plateau": None, "q_g_v": 5})
    assert caught.value.field == "v_plateau" and "threshold voltage plus 2 V" in str(caught.value)


def test_a_part_with_no_name_is_called_by_its_kind_and_numbered(tmp_path) -> None:
    ws = page.Workspace(tmp_path)
    names = [page.add_typed({**BARE, "technology": kind}, ws)["device"]["name"] for kind in ("Si MOSFET",) * 2]
    gan = {**BARE, "technology": "GaN HEMT", "rds_on_hot": None, "rds_hot_tj": None}
    names.append(page.add_typed(gan, ws)["device"]["name"])
    names.append(page.add_typed({**BARE, "vendor": "Acme"}, ws)["device"]["name"])
    assert names == ["Typed MOSFET 1", "Typed MOSFET 2", "Typed GaN 1", "Acme Typed MOSFET 1"]
    assert {"typed-mosfet-1", "typed-mosfet-2", "typed-gan-1"} <= set(ws.paths())


def test_the_verdict_of_a_design_says_it_passes_with_cautions(tmp_path) -> None:
    ws = page.Workspace(tmp_path)
    key = page.add_typed(BARE, ws)["device"]["id"]
    start = design.starting_setup("example-mosfet", ws)
    answer = page.proposal({"motor": start["motor"], "conditions": start["conditions"], "devices": [key]}, ws)
    candidate = answer["candidates"][0]
    assert candidate["level"] == "caution"
    fields = [c.get("field") for c in candidate["checks"] if c["topic"] == "data" and c["level"] == "caution"]
    assert fields == ["tj_max", "v_plateau", "q_gs"]
    # Only a check about one figure names it: the rest are as they were.
    assert all("field" not in c for c in candidate["checks"] if c["topic"] != "data")


def test_the_form_marks_the_three_as_optional_and_keeps_them_with_the_required_ones() -> None:
    form = page.typed_form()
    by_key = {f["key"]: f for f in form["fields"]}
    for key in ("tj_max", "v_plateau", "q_gs"):
        assert by_key[key]["required"] is False and by_key[key]["main"] is True
        assert "Left empty" in by_key[key]["help"]
    assert by_key["q_rr"]["main"] is False and by_key["v_th"]["main"] is True


def test_the_form_gives_each_figure_the_range_it_is_held_to_so_the_page_says_every_wrong_box_at_once() -> None:
    from motionsim.fit import typed, typed_igbt

    form = page.typed_form()
    by_key = {f["key"]: f for f in form["fields"]}
    assert (by_key["rds_on"]["low"], by_key["rds_on"]["high"]) == typed._BOUNDS["rds_on"]
    assert (by_key["v_rated"]["low"], by_key["v_rated"]["high"]) == typed._BOUNDS["v_rated"]
    igbt = {f["key"]: f for f in form["igbt"]["fields"]}
    for key, (low, high) in typed_igbt._BOUNDS.items():
        if key in igbt:
            assert (igbt[key]["low"], igbt[key]["high"]) == (low, high)
    # A figure with no range of its own carries none.
    assert all(("low" in f) == ("high" in f) for f in form["fields"])
