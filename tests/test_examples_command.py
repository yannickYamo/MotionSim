"""The example files that come with the tool are listed with where they are, and a command
takes one by its bare name from wherever it is run: a pip user has no clone to point into."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from motionsim import cli, shipped

REPO_EXAMPLES = Path(__file__).parent.parent / "examples"
POINT = ["--vdc", "48", "--irms", "30", "--m", "0.8", "--pf", "0.9", "--fsw", "20000", "--tsink", "60"]
GATE = ["--vdrive", "10", "--rgon", "5", "--rgoff", "5"]


def test_the_examples_are_listed_with_their_paths(capsys) -> None:
    """Listed from wherever this install keeps them: the clone's folder in place, the package's own from a wheel."""
    assert cli.main(["examples"]) == cli.PASSED
    out = capsys.readouterr().out
    files = sorted(p.name for p in REPO_EXAMPLES.iterdir() if p.is_file())
    assert files and all(name in out for name in files)
    assert str(shipped.folder().resolve()) in out
    assert cli.main(["examples", "--json"]) == cli.PASSED
    listed = json.loads(capsys.readouterr().out)
    assert sorted(x["name"] for x in listed["files"]) == files
    kinds = {x["name"]: x["kind"] for x in listed["files"]}
    assert kinds["synthetic_mosfet_100v_100a.yaml"] == "device"
    assert kinds["motor_robot_joint_pmsm.yaml"] == "motor"
    assert kinds["load_robot_joint.yaml"] == "load"
    assert kinds["profile_joint_move.yaml"] == "profile"
    assert kinds["double_pulse_example.json"] == "measurement"
    assert all(Path(x["path"]).is_file() for x in listed["files"])


def test_a_wheel_holds_its_examples_inside_the_package(tmp_path, monkeypatch) -> None:
    inside = tmp_path / "examples"
    inside.mkdir()
    (inside / "motor_x.yaml").write_text("type: dc\n", encoding="utf-8")
    monkeypatch.setattr(shipped, "IN_PACKAGE", inside)
    assert shipped.folder() == inside
    assert shipped.resolved("motor_x.yaml") == str(inside / "motor_x.yaml")


def test_a_command_takes_an_example_by_its_bare_name_from_anywhere(capsys, tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    by_name = ["simulate", "synthetic_mosfet_100v_100a.yaml", *POINT, *GATE]
    assert cli.main(by_name) == cli.PASSED
    named = capsys.readouterr().out
    by_path = ["simulate", str(REPO_EXAMPLES / "synthetic_mosfet_100v_100a.yaml"), *POINT, *GATE]
    assert cli.main(by_path) == cli.PASSED
    assert capsys.readouterr().out == named
    cycle = [
        "cycle",
        "synthetic_mosfet_100v_100a.yaml",
        "--motor",
        "motor_robot_joint_pmsm.yaml",
        "--load",
        "load_robot_joint.yaml",
        "--profile",
        "profile_joint_move.yaml",
        "--vdc",
        "48",
        "--fsw",
        "20000",
        "--tsink",
        "60",
    ]
    assert cli.main(cycle) in (cli.PASSED, cli.FAILED, cli.UNDECIDED)
    assert "cannot" not in capsys.readouterr().err


def test_a_file_of_the_users_own_by_that_name_comes_first(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "motor_robot_joint_pmsm.yaml").write_text("type: dc\n", encoding="utf-8")
    assert shipped.resolved("motor_robot_joint_pmsm.yaml") == "motor_robot_joint_pmsm.yaml"
    # A path, or a name no example has, is left as it was given.
    assert shipped.resolved("sub/motor_robot_joint_pmsm.yaml") == "sub/motor_robot_joint_pmsm.yaml"
    assert shipped.resolved("nothing.yaml") == "nothing.yaml"


@pytest.mark.parametrize("name", ["example", "example-mosfet"])
def test_the_made_up_parts_by_name_are_still_the_built_in_ones(name) -> None:
    assert shipped.resolved(name) == name


def test_a_cycle_says_the_dead_time_it_filled_in(capsys, tmp_path, monkeypatch) -> None:
    """A dead time left open is filled in and its loss counted; the command says so, with the
    flag that gives one's own, as simulate does."""
    monkeypatch.chdir(tmp_path)
    cycle = ["cycle", "example-mosfet", "--motor", "motor_robot_joint_pmsm.yaml", "--load", "load_robot_joint.yaml"]
    cycle += ["--profile", "profile_joint_move.yaml", "--vdc", "48", "--fsw", "20000", "--tsink", "60", *GATE]
    cli.main(cycle)
    out = capsys.readouterr().out
    assert out.startswith("dead time taken as 130 ns") and "(--tdead)" in out.splitlines()[0]
    cli.main([*cycle, "--tdead", "3e-7"])
    assert "dead time taken" not in capsys.readouterr().out
