"""A whole design run from one file, as a terminal or a coding agent drives it: the same
answers as the page gives step by step, a report in Markdown, and an exit status that says
how it went."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from motionsim import cli, design, page
from motionsim.fit.typed import TEMPLATE

ROOT = Path(__file__).parent.parent


def started(tmp_path, device="example-mosfet", **changes) -> Path:
    file = tmp_path / "design.yaml"
    assert cli.main(["design", "init", "--device", device, "-o", str(file)]) == 0
    setup = yaml.safe_load(file.read_text())
    for key, value in changes.items():
        setup[key] = {**setup[key], **value} if isinstance(value, dict) else value
    file.write_text(yaml.safe_dump(setup))
    return file


def test_a_design_started_for_a_part_runs_as_it_is_and_says_what_the_page_says(tmp_path, capsys) -> None:
    file = started(tmp_path)
    capsys.readouterr()
    assert cli.main(["design", "run", str(file), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["outcome"] == "passes" and out["followed"] == "example-mosfet"
    assert set(out) >= {"fit", "stage", "verdict", "motion", "build", "drive", "setup", "devices"}
    # The same figures as the page's own steps, asked one by one.
    ws = page.Workspace(tmp_path / "ws")
    setup = yaml.safe_load(file.read_text())
    request = {"motor": setup["motor"], "conditions": setup["conditions"], "supply": "one-way"}
    on_page = page.proposal({**request, "devices": ["example-mosfet"]}, ws)["candidates"][0]
    assert out["verdict"]["candidates"][0]["result"]["loss"] == pytest.approx(on_page["result"]["loss"])
    motion = page.cycle({**request, "device": "example-mosfet", "load": setup["load"], "profile": setup["profile"]}, ws)
    assert out["motion"]["summary"]["mean_loss"] == pytest.approx(motion["summary"]["mean_loss"])
    assert "time" not in out["motion"]  # traces only when asked for
    assert cli.main(["design", "run", str(file), "--json", "--traces", "--skip", "drive", "--skip", "build"]) == 0
    traced = json.loads(capsys.readouterr().out)
    assert len(traced["motion"]["time"]) == len(traced["motion"]["tj"]) > 10 and "drive" not in traced and "build" not in traced


def test_the_report_says_what_was_tested_the_verdict_and_what_it_rests_on(tmp_path, capsys) -> None:
    file, report = started(tmp_path), tmp_path / "report.md"
    assert cli.main(["design", "run", str(file), "--md", str(report)]) == 0
    text = report.read_text()
    for heading in ("## What was tested", "## Does the motor fit the part", "## Verdict at the design point",
                    "## Through the motion", "## What to build", "can drive", "## What this rests on"):
        assert heading in text, heading
    assert "**Outcome: passes.**" in text and "2000 rpm, 1 N·m" in text and "e+0" not in text
    assert "| synthetic MOSFET-100V-100A | passes |" in text and "Verify by measurement" in text


def test_what_cannot_be_run_is_said_in_place_not_thrown(tmp_path, capsys) -> None:
    # A step that cannot be run holds the reason and the figure at issue.
    wrong = started(tmp_path, conditions={"cooling": "heatsink"})
    capsys.readouterr()
    assert cli.main(["design", "run", str(wrong), "--json"]) == 2
    said = json.loads(capsys.readouterr().out)
    assert said["outcome"] == "refused" and said["stage"]["field"] == "rth_sink" and "thermal resistance" in said["stage"]["refused"]
    # No such file, and a file that is not a design.
    assert cli.main(["design", "run", str(tmp_path / "missing.yaml"), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["outcome"] == "refused"
    (tmp_path / "list.yaml").write_text("- 1\n")
    assert cli.main(["design", "run", str(tmp_path / "list.yaml")]) == 2


def test_a_part_that_does_not_pass_is_status_three_with_the_failing_check(tmp_path, capsys) -> None:
    over = started(tmp_path, conditions={"v_dc": 150})
    capsys.readouterr()
    assert cli.main(["design", "run", str(over), "--json", "--skip", "drive", "--skip", "motion"]) == 3
    out = json.loads(capsys.readouterr().out)
    failed = [c for c in out["verdict"]["candidates"][0]["checks"] if c["level"] == "fail"]
    assert out["outcome"] == "does not pass" and failed and failed[0]["topic"] == "voltage" and "100 V rating" in failed[0]["message"]


def test_devices_come_by_name_as_files_or_as_typed_figures_and_are_compared(tmp_path, capsys) -> None:
    (tmp_path / "typed.yaml").write_text(TEMPLATE)
    file = started(tmp_path, devices=["example-mosfet", "typed.yaml", str(ROOT / "examples/synthetic_mosfet_100v_100a.yaml")])
    capsys.readouterr()
    assert cli.main(["design", "run", str(file), "--json", "--skip", "drive", "--skip", "motion", "--skip", "build"]) == 0
    out = json.loads(capsys.readouterr().out)
    names = [c["name"] for c in out["verdict"]["candidates"]]
    assert len(names) == 3 and "Made-up Semiconductor MU100N04" in names and out["verdict"]["explain"]
    # A figure that cannot be right is refused with its name.
    (tmp_path / "typed.yaml").write_text(TEMPLATE.replace("rds_on: 4.0", "rds_on: 4000"))
    assert cli.main(["design", "run", str(file), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["field"] == "rds_on"


def test_the_page_hands_out_the_same_report(tmp_path) -> None:
    ws = page.Workspace(tmp_path)
    setup = design.starting_setup("example-mosfet", ws)
    answer = json.loads(page.call("/api/report", json.dumps(setup), ws))
    assert answer["status"] == 200 and answer["body"]["markdown"] == design.markdown(design.run(setup, ws))


def test_the_guide_for_agents_names_commands_that_exist(capsys) -> None:
    assert cli.main(["agent"]) == 0
    guide = capsys.readouterr().out
    assert "motionsim design init" in guide and "motionsim design run" in guide and "Exit status" in guide
    # Every key the guide tells an agent to read is in what a run returns.
    ws_keys = {"outcome", "fit", "stage", "verdict", "followed", "motion", "build", "drive"}
    for key in ws_keys:
        assert f"`{key}" in guide, key
    assert (ROOT / "AGENTS.md").read_text().count("motionsim agent") >= 1
