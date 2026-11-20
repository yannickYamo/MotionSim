"""One datasheet read from start to finish: the plan is said first, every call is counted
against one budget, and what was paid for is on disk before anything later can fail.

The model is a recording handed in where Anthropic's client would go. Nothing is sent."""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
import yaml

from evals.reader import pdf, recordings, replay, sheets
from motionsim import observe
from motionsim.device.schema import ReviewStatus
from motionsim.observe import digitise, provider, run
from motionsim.observe.schema import ObservationSet, ReadFigure


class Counted(replay.ReplayClient):
    """A recording that reports a fixed use of tokens for every answer: 100 in, 10 out."""

    fail_on: str = ""

    def create(self, **request):
        answer = super().create(**request)
        if self.fail_on and self.asked[-1].startswith(self.fail_on):
            raise provider.ReaderFailed("the service stopped answering")
        answer.usage = SimpleNamespace(input_tokens=100, output_tokens=10)
        return answer


@pytest.fixture
def anthropic_env(monkeypatch):
    for name in ("MOTIONSIM_LLM_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "never-sent")


@pytest.fixture
def sheet(tmp_path, anthropic_env):
    """An IGBT's datasheet of four pages: two of tables, two of figures."""
    made = sheets.labelled_set()[0]
    data, layout = sheets.build(made)
    path = tmp_path / "sheet.pdf"
    path.write_bytes(data)
    return path, recordings.faithful(made, layout)


def test_the_plan_is_said_before_the_first_call_and_the_cost_is_added_up(sheet, tmp_path) -> None:
    path, recording = sheet
    client = Counted(path, recording)
    said: list[tuple[str, int]] = []
    reading = run.read_datasheet(
        path, tmp_path / "out.yaml", client=client, say=lambda line: said.append((line, len(client.asked)))
    )
    assert said[0] == (
        "4 pages, at most 5 model calls: 1 for the tables, 0 for pages with no usable text, and up to 4 for pages with figures",
        0,
    )
    # One call for the tables and one for each of the two pages of figures.
    assert client.asked == ["tables", "axes of page 3", "axes of page 4"]
    ledger = reading.ledger
    assert (ledger.calls, ledger.input_tokens, ledger.output_tokens) == (3, 300, 30)
    assert reading.summary()[-1] == "3 model calls, 300 tokens in and 30 out"
    assert reading.saved == tmp_path / "out.yaml"
    assert len(observe.load_observations(reading.saved).curves) == len(reading.observations.curves) == 7


def test_a_budget_used_up_among_the_figures_keeps_the_tables(sheet, tmp_path) -> None:
    path, recording = sheet
    client = Counted(path, recording)
    reading = run.read_datasheet(path, tmp_path / "out.yaml", max_calls=2, client=client, say=lambda line: None)
    assert client.asked == ["tables", "axes of page 3"]
    assert len(reading.observations.observations) == 18
    left = [c for c in reading.observations.curves if c.page == 4]
    assert [c.label for c in left] == ["Figure 3", "Figure 4"]
    assert all(c.status is ReviewStatus.flagged and not c.x for c in left)
    assert all("its axes were not read" in c.flags[0] and "2 model calls" in c.flags[0] for c in left)
    assert len(observe.load_observations(tmp_path / "out.yaml").observations) == 18


def test_a_failure_among_the_figures_is_written_beside_them_and_asked_once(sheet, tmp_path) -> None:
    path, recording = sheet
    client = Counted(path, recording)
    client.fail_on = "axes"
    reading = run.read_datasheet(path, tmp_path / "out.yaml", client=client, say=lambda line: None)
    # The first page of figures fails; the second is not asked about, for it would fail the same way.
    assert client.asked == ["tables", "axes of page 3"]
    assert {c.label for c in reading.observations.curves} == {"Figure 1", "Figure 2", "Figure 3", "Figure 4"}
    assert all(
        c.flags == ["its axes were not read: the service stopped answering"] for c in reading.observations.curves
    )


def test_the_tables_are_on_disk_before_the_figures_are_started(sheet, tmp_path, monkeypatch) -> None:
    path, recording = sheet
    out = tmp_path / "out.yaml"

    def stopped(*args, **kwargs):
        assert len(observe.load_observations(out).observations) == 18
        raise KeyboardInterrupt

    monkeypatch.setattr(digitise, "digitise_curves", stopped)
    with pytest.raises(KeyboardInterrupt):
        run.read_datasheet(path, out, client=Counted(path, recording), say=lambda line: None)
    assert len(observe.load_observations(out).observations) == 18


def test_tables_alone_cost_one_call(sheet) -> None:
    path, recording = sheet
    client = Counted(path, recording)
    reading = run.read_datasheet(path, curves=False, client=client, say=lambda line: None)
    assert client.asked == ["tables"] and reading.saved is None and reading.observations.curves == []


def test_more_pages_than_allowed_is_refused_before_any_call(sheet) -> None:
    path, recording = sheet
    client = Counted(path, recording)
    with pytest.raises(provider.ReaderFailed, match=r"has 4 pages, more than the 3 that are read"):
        run.read_datasheet(path, max_pages=3, client=client, say=lambda line: None)
    assert client.asked == []


def test_a_scan_that_would_take_more_calls_than_the_budget_is_refused_before_spending(tmp_path, anthropic_env) -> None:
    path = tmp_path / "blank.pdf"
    path.write_bytes(pdf.write([pdf.Page() for _ in range(60)]))
    client = Counted(path, {"tables": {}, "axes": {}, "transcripts": {}})
    said: list[str] = []
    with pytest.raises(provider.ReaderFailed) as refused:
        run.read_datasheet(path, client=client, say=said.append)
    assert client.asked == []
    assert said and said[0].startswith("60 pages, at most 40 model calls")
    assert "60" in str(refused.value) and "40" in str(refused.value) and "\n" not in str(refused.value)


def test_a_figure_cited_on_a_page_the_file_does_not_have_is_set_aside(sheet) -> None:
    path, recording = sheet
    client = Counted(path, recording)
    reading = run.read_datasheet(path, curves=False, client=client, say=lambda line: None)
    obs: ObservationSet = reading.observations
    obs.figures = [ReadFigure(page=99, label="Figure 1", shows="output characteristics", kind="output_characteristic")]
    curves = digitise.digitise_curves(str(path), obs, client=client)
    assert [(c.label, c.x, c.status) for c in curves] == [("Figure 1", [], ReviewStatus.flagged)]
    assert curves[0].flags == ["page 99 does not exist: the file has 4 pages"]
    assert client.asked == ["tables"]  # and nobody was asked about a page that is not there


def test_axes_that_cannot_be_are_a_flag_on_the_figure_not_a_crash(sheet) -> None:
    path, recording = sheet
    for claim in recording["axes"]["3"]["figures"]:
        claim["x"] = {"lo": 0.0, "hi": 0.0, "log": True}  # a logarithmic axis from nothing to nothing
    reading = run.read_datasheet(path, client=Counted(path, recording), say=lambda line: None)
    on_page_3 = [c for c in reading.observations.curves if c.page == 3]
    assert on_page_3 and all(c.flags and c.status is ReviewStatus.flagged for c in on_page_3)
    assert len([c for c in reading.observations.curves if c.page == 4 and not c.flags]) == 3


def test_a_write_that_is_stopped_leaves_the_file_that_was_there(sheet, tmp_path, monkeypatch) -> None:
    path, recording = sheet
    reading = run.read_datasheet(path, curves=False, client=Counted(path, recording), say=lambda line: None)
    out = tmp_path / "kept.yaml"
    observe.save_observations(reading.observations, out)
    before = out.read_bytes()

    def half_written(data, stream, **options):
        stream.write("document:\n  file: half")
        raise KeyboardInterrupt

    monkeypatch.setattr(yaml, "safe_dump", half_written)
    with pytest.raises(KeyboardInterrupt):
        observe.save_observations(reading.observations, out)
    assert out.read_bytes() == before
    with pytest.raises(KeyboardInterrupt):
        observe.save_observations(reading.observations, tmp_path / "new.yaml")
    # No empty file where there was none, and nothing left lying beside it.
    assert sorted(os.listdir(tmp_path)) == ["kept.yaml", "sheet.pdf"]
