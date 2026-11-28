"""What a board's figures cost is counted in work, never in time: the same file gives the same
figures on a machine that is busy and on one that is not, and a board's file is held to the
things it holds that the figures are worked out from."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from motionsim import board
from motionsim.board import figures, solve
from motionsim.errors import Refusal

pytestmark = pytest.mark.timeout(280)

BOARDS = Path(__file__).parent / "fixtures" / "boards"
THREE = BOARDS / "three_phase.kicad_pcb"


def said(answer: dict) -> str:
    return json.dumps(answer, sort_keys=True)


@pytest.fixture(scope="module")
def quiet() -> dict:
    return board.read(THREE)


def test_every_search_of_the_made_up_board_settles_within_its_work(quiet) -> None:
    for bridge in quiet["bridges"]:
        assert bridge["mesh"]["settled"] is True
        assert "stopped early" not in " ".join(bridge["figures"]["l_loop_nh"]["rests_on"])


def test_the_figures_are_the_same_with_the_machine_busy(quiet) -> None:
    """Eight processes that do nothing but spin take the processor from the search. Were the
    search stopped by the clock, it would stop sooner, leave its figure high and widen its
    band: the figures would say how busy the machine was."""
    busy = [subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(8)]
    try:
        time.sleep(0.5)  # until they all spin
        loaded = board.read(THREE)
    finally:
        for process in busy:
            process.kill()
        for process in busy:
            process.wait(timeout=30)
    assert said(loaded) == said(quiet)


def test_a_clock_that_runs_a_hundred_times_as_fast_moves_no_figure(quiet, monkeypatch) -> None:
    """The machine as slow as can be told from inside: every second that passes is counted as
    a hundred. Nothing a figure rests on may ask the clock."""
    real, began = time.monotonic, time.monotonic()
    fast = SimpleNamespace(monotonic=lambda: began + 100 * (real() - began))
    monkeypatch.setattr(figures, "CEILING", 1e9)  # the one thing the clock may still do is refuse
    for module in (figures, solve):
        monkeypatch.setattr(module, "time", fast, raising=False)
    assert said(board.read(THREE)) == said(quiet)


def test_a_board_that_takes_longer_than_the_ceiling_is_refused_and_never_answered_in_part(monkeypatch) -> None:
    monkeypatch.setattr(figures, "CEILING", 0.0)
    with pytest.raises(Refusal, match="took longer than") as refused:
        board.read(THREE)
    assert refused.value.field == "board" and "one leg" in refused.value.fix


def test_less_work_stops_a_search_early_and_says_so(monkeypatch) -> None:
    """The budget is real: with a hundredth of it the search stops at the same step every
    time, the figure is left on the high side and its band is widened."""
    monkeypatch.setattr(figures, "WORK", figures.WORK / 1000)
    monkeypatch.setattr(figures, "MOST_WORK", figures.MOST_WORK / 1000)
    monkeypatch.setattr(figures, "LEAST_WORK", figures.LEAST_WORK / 1000)
    choose = {"switch_nodes": ["SW_U"]}
    first, second = board.read(THREE, choose=choose), board.read(THREE, choose=choose)
    assert said(first) == said(second)
    assert first["bridges"][0]["mesh"]["settled"] is False
    assert "stopped early" in " ".join(first["figures"]["l_loop_nh"]["rests_on"])


def segments(count: int) -> str:
    """The half bridge with this many more track segments on a signal net of their own."""
    more = "".join(
        f'  (segment (start {i % 200} {i // 200}) (end {i % 200 + 0.5} {i // 200}) (width 0.2) (layer "B.Cu") (net 4))\n'
        for i in range(count)
    )
    return (BOARDS / "half_bridge.kicad_pcb").read_text(encoding="utf-8").rstrip()[:-1] + more + ")"


def test_a_board_of_forty_thousand_tracks_is_read_with_the_figures_of_the_board_without_them() -> None:
    """Three megabytes of board. Its forty thousand tracks are forty thousand of the things
    the reader counts, each written with a dozen brackets and values: counted as those, the
    board was refused for holding 400,000 tracks, pads and corners, which it does not."""
    plain = board.read(BOARDS / "half_bridge.kicad_pcb")
    busy = board.read(segments(40_000).encode(), "half_bridge.kicad_pcb")
    assert busy["figures"] == plain["figures"]


def test_a_board_of_more_tracks_than_are_taken_is_refused_by_their_true_count(monkeypatch) -> None:
    from motionsim.board import model

    monkeypatch.setattr(model, "MOST_ITEMS", 30_000)
    with pytest.raises(Refusal, match="holds more than 30 000 tracks, vias, pads and polygon corners"):
        board.read(segments(40_000).encode(), "many.kicad_pcb")
    # Just under: the board's own few hundred and 29,000 more.
    assert board.read(segments(29_000).encode(), "fewer.kicad_pcb")["taken"] == "SW"
