"""The reader's eval, replayed: stored answers played through the reader and scored against
the parts the made-up datasheets were written from. No model is asked anything."""

from __future__ import annotations

import json

import numpy as np
import pytest

from evals.reader import recordings, replay, run, score, sheets
from motionsim.observe import provider, reader, verify

pytestmark = pytest.mark.reader_eval


# Replaying every recording of every sheet takes some forty seconds on an idle machine, and
# several times that on a loaded one. It is done once, in the one test that reads it, so that
# workers running in parallel never replay it twice, and that test is given the time it needs.
@pytest.mark.timeout(1200)
def test_replay_reaches_every_threshold_and_plays_every_sheet_and_every_wrong_reading(tmp_path) -> None:
    outcome = run.run_replay(tmp_path)
    assert outcome["failed"] == [], run.table(outcome)
    counts = outcome["counts"]
    assert counts["sheets"] >= 12
    assert counts["devices_built"] == f"{counts['sheets']} of {counts['sheets']}"
    # Each sheet has at least nine wrong readings besides the faithful one.
    assert counts["recordings"] >= 10 * counts["sheets"]
    assert counts["wrong_values"] >= 100
    # The one reading that breaks the form asked for is refused whole, in words, on every sheet.
    assert len(counts["refused"]) == counts["sheets"]
    assert all("is read from a figure, not from a table" in why for why in counts["refused"].values())


def test_the_set_covers_the_ways_datasheets_differ() -> None:
    made = sheets.labelled_set()
    assert len({s.name for s in made}) == len(made) >= 12
    assert {s.technology for s in made} == {"Si IGBT", "Si MOSFET", "SiC MOSFET", "GaN HEMT"}
    assert any(s.topology == "six_pack" for s in made)
    traits = set().union(*(s.traits for s in made))
    wanted = {"typ and max", "ohms", "milliohms", "microcoulombs", "nanocoulombs", "footnotes", "two temperatures"}
    wanted |= {"log axes", "colour", "scanned page", "split table", "decoy", "injection", "missing figure"}
    assert wanted <= traits


def test_a_sheet_is_the_same_file_every_time_it_is_made() -> None:
    sheet = sheets.labelled_set()[0]
    assert sheets.build(sheet)[0] == sheets.build(sheet)[0]


def test_the_recordings_kept_are_the_ones_the_code_writes() -> None:
    for sheet in sheets.labelled_set():
        _, layout = sheets.build(sheet)
        kept = recordings.path(sheet.name).read_text(encoding="utf-8")
        assert kept == recordings.as_text(recordings.all_for(sheet, layout)), sheet.name
        assert json.loads(kept)["faithful"]["tables"]["part_number"] == sheet.part_number


def test_the_printed_table_is_the_part_evaluated_at_its_test_conditions() -> None:
    # Worked by hand from the part's curves, not through the code that prints the rows.
    sheet = next(s for s in sheets.labelled_set() if s.name == "igbt_copack")
    printed = {(r.quantity, r.tj_c): r.typ for r in sheet.rows}
    assert printed[("vce_sat", 25.0)] == f"{0.55 + 0.08 * 40**0.5 + 0.0124 * 40:.2f}" == "1.55"
    assert printed[("vce_sat", 150.0)] == f"{0.40 + 0.09 * 40**0.5 + 0.0208 * 40:.2f}" == "1.80"
    fet = next(s for s in sheets.labelled_set() if s.name == "sic_mosfet")
    ohms = {r.tj_c: r for r in fet.rows if r.quantity == "rds_on"}
    assert (ohms[25.0].unit, ohms[25.0].typ) == ("Ω", "0.0750")
    assert ohms[25.0].si(ohms[25.0].typ) == 0.075


def _play(tmp_path, name: str, recording: str) -> score.Played:
    sheet = next(s for s in sheets.labelled_set() if s.name == name)
    data, layout = sheets.build(sheet)
    path = tmp_path / f"{name}.pdf"
    path.write_bytes(data)
    with replay.as_if_anthropic():
        return score.play(sheet, layout, path, recording, recordings.load(name)[recording])


def test_an_order_printed_on_the_page_and_obeyed_is_flagged(tmp_path) -> None:
    played = _play(tmp_path, "si_mosfet_injected", "the order printed on the page obeyed")
    assert (played.tables["wrong"], played.tables["wrong_flagged"]) == (1, 1)
    assert played.tables["missed"] == []


def test_the_bars_fail_a_reader_that_checks_nothing(tmp_path, monkeypatch) -> None:
    """The thresholds are worth something only if a worse reader misses them: with the
    check against the page taken out, the wrong values pass and the score says so."""
    monkeypatch.setattr(verify, "_values_on_the_page", lambda *given: (verify.Evidence.row, ""))
    played = _play(tmp_path, "si_mosfet", "gate charges read into each other's rows")
    assert played.tables["wrong"] == 2 and played.tables["wrong_flagged"] == 0
    summary = run.summarise([played], {})
    assert any(line.startswith("wrong_flagged is 0") for line in summary["failed"])


def test_a_curve_read_a_tenth_too_high_is_scored_as_wrong(tmp_path) -> None:
    sheet = next(s for s in sheets.labelled_set() if s.name == "igbt_copack")
    _, layout = sheets.build(sheet)
    obs = score.true_observations(sheet, layout)
    assert score.curve_score(sheet, obs)["read"] == 7 and score.curve_score(sheet, obs)["worst"] < 1e-3
    obs.curves[0].y = (np.array(obs.curves[0].y) * 1.12).tolist()
    scored = score.curve_score(sheet, obs)
    assert (scored["read"], scored["silently_wrong"]) == (6, 1)


def test_failures_names_each_score_on_the_wrong_side_of_its_bar() -> None:
    good = {name: (0.0 if name in run.CEILINGS else 1.0) for name in run.THRESHOLDS}
    assert run.failures(good) == []
    missed = run.failures(good | {"curve_worst": 0.2, "values_read": 0.9})
    assert [line.split(" ")[0] for line in missed] == ["values_read", "curve_worst"]


def test_live_mode_says_what_it_would_spend_and_asks_nothing_without_a_yes(monkeypatch, capsys) -> None:
    def never(*args, **kwargs):
        raise AssertionError("a model was asked")

    monkeypatch.setattr(reader, "read_tables", never)
    monkeypatch.setattr(provider, "ask", never)
    with replay.as_if_anthropic():
        assert run.main(["--mode", "live"]) == 0
    said = capsys.readouterr().out
    assert "at most" in said and "model calls in all" in said
    assert "nothing was asked" in said
    assert "replay-uses-no-key" not in said


def test_a_transistor_read_from_its_sheet_has_the_total_gate_charge_printed(tmp_path) -> None:
    # The made-up FETs print 48 nC at a 10 V gate; the drain-voltage slip is flagged, not used.
    from motionsim.fit import build_device

    sheet = next(s for s in sheets.labelled_set() if s.name == "si_mosfet_micro")
    data, _ = sheets.build(sheet)
    path = tmp_path / "si_mosfet_micro.pdf"
    path.write_bytes(data)
    from motionsim.observe import run as reading

    with replay.as_if_anthropic():
        good = reading.read_datasheet(
            path, tmp_path / "a.yaml", client=replay.ReplayClient(path, recordings.load(sheet.name)["faithful"])
        )
        slip = reading.read_datasheet(
            path,
            tmp_path / "b.yaml",
            client=replay.ReplayClient(
                path, recordings.load(sheet.name)["the total gate charge given at the drain voltage"]
            ),
        )
    charge = build_device(good.observations).switch.charge
    assert (charge.q_g, charge.q_g_drive) == (pytest.approx(48e-9), 10.0)
    flagged = [o for o in slip.observations.observations if o.quantity.value == "q_g"]
    assert flagged and all(o.flags for o in flagged)
    assert build_device(slip.observations).switch.charge.q_g is None


def test_a_figure_listed_and_not_drawn_is_said_to_be_not_read(tmp_path) -> None:
    """The reader lists a figure the sheet does not draw: it is kept as one set aside with
    why, and the reading's summary says so, never left out."""
    played = _play(tmp_path, "igbt_missing_figure", "faithful")
    assert any("not read" in line and "no plot area" in line for line in played.summary), played.summary


def test_the_switchs_and_the_diodes_junction_to_case_figures_exchanged_are_both_flagged(tmp_path) -> None:
    played = _play(tmp_path, "igbt_copack", "the switch's and the diode's junction-to-case resistances exchanged")
    assert (played.tables["wrong"], played.tables["wrong_flagged"]) == (2, 2)


def test_silicon_read_as_silicon_carbide_is_flagged(tmp_path) -> None:
    played = _play(tmp_path, "si_mosfet", "silicon and silicon carbide exchanged")
    assert (played.tables["wrong"], played.tables["wrong_flagged"]) == (1, 1)
