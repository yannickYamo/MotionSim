"""Package figures kept on disk between runs are the figures worked out, to the last bit,
and a kept file that is not what it should be is passed by."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from motionsim.package import kept, templates

ROOT = Path(__file__).parent.parent
ARGS = ("leadframe-module", 37.0, "high", "grease", True, None)


def _fresh(tmp_path, monkeypatch, name: str = "summary"):
    """The function as a first run meets it: nothing in memory, a folder of its own."""
    monkeypatch.setenv("MOTIONSIM_CACHE", str(tmp_path))
    work = templates.summary.__wrapped__.__wrapped__
    return kept.kept(name, lambda s: [s.self_switch, s.self_diode, s.coupling, s.interface], templates._summary_back)(
        work
    ), work


def test_a_figure_read_back_is_the_figure_worked_out(tmp_path, monkeypatch) -> None:
    first, work = _fresh(tmp_path, monkeypatch)
    worked = work(*ARGS)
    assert first(*ARGS) == worked
    again, _ = _fresh(tmp_path, monkeypatch)  # a second run: the file, not the work
    read = again(*ARGS)
    assert read == worked and read.coupling.hex() == worked.coupling.hex()
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.parametrize("text", ["{not json", "[1, 2]", '{"x": 1}', None])
def test_a_kept_file_that_is_not_figures_is_passed_by(tmp_path, monkeypatch, text) -> None:
    first, work = _fresh(tmp_path, monkeypatch)
    first(*ARGS)
    (file,) = tmp_path.iterdir()
    if text is None:  # the right key with something that is not a figure under it
        data = json.loads(file.read_text())
        data = {key: ["__import__('os')", True, "x", 1] for key in data}
        file.write_text(json.dumps(data))
    else:
        file.write_text(text)
    again, _ = _fresh(tmp_path, monkeypatch)
    assert again(*ARGS) == work(*ARGS)


def test_nothing_is_kept_when_asked_not_to(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MOTIONSIM_CACHE", "off")
    assert kept.folder() is None
    work = templates.summary.__wrapped__.__wrapped__
    keeping = kept.kept(
        "summary", lambda s: [s.self_switch, s.self_diode, s.coupling, s.interface], templates._summary_back
    )(work)
    assert keeping(*ARGS) == work(*ARGS)


def test_a_folder_that_cannot_be_written_is_passed_by(tmp_path, monkeypatch) -> None:
    blocked = tmp_path / "file"
    blocked.write_text("a file where the folder would go")
    first, work = _fresh(blocked, monkeypatch)
    assert first(*ARGS) == work(*ARGS)


def test_a_second_run_of_the_example_gives_the_same_answer_as_the_first(tmp_path) -> None:
    argv = [sys.executable, "-m", "motionsim.cli", "simulate", "example", "--vdc", "300", "--irms", "10"]
    argv += ["--m", "0.9", "--pf", "0.85", "--fsw", "8000", "--tsink", "60", "--json"]
    env = {"PATH": "", "MOTIONSIM_CACHE": str(tmp_path), "PYTHONPATH": str(ROOT / "src")}
    first = subprocess.run(argv, capture_output=True, text=True, env=env, check=True).stdout
    assert any(tmp_path.iterdir())
    second = subprocess.run(argv, capture_output=True, text=True, env=env, check=True).stdout
    off = subprocess.run(argv, capture_output=True, text=True, env={**env, "MOTIONSIM_CACHE": "off"}, check=True).stdout
    assert first == second == off
