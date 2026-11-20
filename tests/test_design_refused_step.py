"""A design with a step that could not be run is refused as a whole: its outcome says so in
the JSON, the Markdown report and the exit status alike, whatever the steps that ran said."""

from __future__ import annotations

import json

import pytest
import yaml

from motionsim import cli

REFUSED = 2


def _design(tmp_path, change) -> str:
    file = tmp_path / "design.yaml"
    assert cli.main(["design", "init", "-o", str(file)]) == 0
    setup = yaml.safe_load(file.read_text())
    change(setup)
    file.write_text(yaml.safe_dump(setup))
    return str(file)


def _gear(setup) -> None:
    setup["load"]["gear_efficiency"] = 7


def _duration(setup) -> None:
    setup["profile"]["segments"][0]["duration"] = -1


@pytest.mark.parametrize("change", [_gear, _duration])
def test_a_refused_motion_step_is_a_refused_design(capsys, tmp_path, change) -> None:
    file = _design(tmp_path, change)
    capsys.readouterr()
    assert cli.main(["design", "run", file, "--json", "--skip", "drive", "--skip", "build"]) == REFUSED
    answer = json.loads(capsys.readouterr().out)
    assert answer["refusals"] == ["motion"]
    assert answer["outcome"] == "refused"
    assert answer["verdict"]["candidates"][0]["result"] is not None  # the point itself ran
    report = tmp_path / "report.md"
    assert cli.main(["design", "run", file, "--md", str(report), "--skip", "drive", "--skip", "build"]) == REFUSED
    text = report.read_text()
    assert "**Outcome: refused.**" in text and "Not run: motion." in text
    assert "**Outcome: passes" not in text


def test_the_guide_says_a_refused_step_refuses_the_design(capsys) -> None:
    assert cli.main(["agent"]) == 0
    assert "`outcome` is `refused` even where the steps that ran passed" in " ".join(capsys.readouterr().out.split())
