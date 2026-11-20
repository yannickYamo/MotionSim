"""A whole design run from one file, as a terminal or a coding agent drives it: the same
answers as the page gives step by step, a report in Markdown, and an exit status that says
how it went."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from motionsim import cli, design, page
from motionsim.design import report
from motionsim.fit.typed import TEMPLATE

ROOT = Path(__file__).parent.parent


def started(tmp_path, device="example-mosfet", **changes) -> Path:
    file = tmp_path / "design.yaml"
    assert cli.main(["design", "init", "--device", device, "-o", str(file)]) == 0
    setup = yaml.safe_load(file.read_text(encoding="utf-8"))
    for key, value in changes.items():
        setup[key] = {**setup[key], **value} if isinstance(value, dict) else value
    file.write_text(yaml.safe_dump(setup), encoding="utf-8")
    return file


def test_a_design_started_for_a_part_runs_as_it_is_and_says_what_the_page_says(tmp_path, capsys) -> None:
    file = started(tmp_path)
    capsys.readouterr()
    assert cli.main(["design", "run", str(file), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    # The joint lowers what it lifted, and on a supply that takes nothing back that energy is a
    # caution: the design point itself passes.
    assert out["outcome"] == "passes with cautions" and out["followed"] == "example-mosfet"
    assert [c["topic"] for c in out["motion"]["checks"] if c["level"] == "caution"] == ["braking"]
    assert set(out) >= {"fit", "stage", "verdict", "motion", "build", "drive", "setup", "devices"}
    # The same figures as the page's own steps, asked one by one.
    ws = page.Workspace(tmp_path / "ws")
    setup = yaml.safe_load(file.read_text(encoding="utf-8"))
    request = {"motor": setup["motor"], "conditions": setup["conditions"], "supply": "one-way"}
    on_page = page.proposal({**request, "devices": ["example-mosfet"]}, ws)["candidates"][0]
    assert out["verdict"]["candidates"][0]["result"]["loss"] == pytest.approx(on_page["result"]["loss"])
    motion = page.cycle({**request, "device": "example-mosfet", "load": setup["load"], "profile": setup["profile"]}, ws)
    assert out["motion"]["summary"]["mean_loss"] == pytest.approx(motion["summary"]["mean_loss"])
    assert "time" not in out["motion"]  # traces only when asked for
    assert cli.main(["design", "run", str(file), "--json", "--traces", "--skip", "drive", "--skip", "build"]) == 0
    traced = json.loads(capsys.readouterr().out)
    assert (
        len(traced["motion"]["time"]) == len(traced["motion"]["tj"]) > 10
        and "drive" not in traced
        and "build" not in traced
    )


def test_the_report_says_what_was_tested_the_verdict_and_what_it_rests_on(tmp_path, capsys) -> None:
    file, report = started(tmp_path), tmp_path / "report.md"
    assert cli.main(["design", "run", str(file), "--md", str(report)]) == 0
    text = report.read_text(encoding="utf-8")
    for heading in (
        "## What was tested",
        "## Does the motor fit the part",
        "## Verdict at the design point",
        "## Through the motion",
        "## What to build",
        "can drive",
        "## What this rests on",
    ):
        assert heading in text, heading
    assert "**Outcome: passes with cautions.**" in text and "3000 rpm, 4.74 N·m" in text and "e+0" not in text
    assert "| made-up 100 V MOSFET | passes |" in text and "Verify by measurement" in text


def test_what_cannot_be_run_is_said_in_place_not_thrown(tmp_path, capsys) -> None:
    # A step that cannot be run holds the reason and the figure at issue.
    wrong = started(tmp_path, conditions={"cooling": "heatsink"})
    capsys.readouterr()
    assert cli.main(["design", "run", str(wrong), "--json"]) == 2
    said = json.loads(capsys.readouterr().out)
    assert (
        said["outcome"] == "refused"
        and said["stage"]["field"] == "rth_sink"
        and "thermal resistance" in said["stage"]["refused"]
    )
    # No such file, and a file that is not a design.
    assert cli.main(["design", "run", str(tmp_path / "missing.yaml"), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["outcome"] == "refused"
    (tmp_path / "list.yaml").write_text("- 1\n", encoding="utf-8")
    assert cli.main(["design", "run", str(tmp_path / "list.yaml")]) == 2


def test_a_part_that_does_not_pass_is_status_three_with_the_failing_check(tmp_path, capsys) -> None:
    over = started(tmp_path, conditions={"v_dc": 150})
    capsys.readouterr()
    assert cli.main(["design", "run", str(over), "--json", "--skip", "drive", "--skip", "motion"]) == 3
    out = json.loads(capsys.readouterr().out)
    failed = [c for c in out["verdict"]["candidates"][0]["checks"] if c["level"] == "fail"]
    assert (
        out["outcome"] == "does not pass"
        and failed
        and failed[0]["topic"] == "voltage"
        and "100 V rating" in failed[0]["message"]
    )


def test_a_part_with_a_caution_at_the_design_point_passes_with_cautions(tmp_path, capsys) -> None:
    """85 V on the 100 V part is above the 80% that leaves room for overshoot, and under the
    rating: a caution, not a failure. The outcome says so, and the status is still 0."""
    near = started(tmp_path, conditions={"v_dc": 85})
    capsys.readouterr()
    skip = ["--skip", "drive", "--skip", "motion", "--skip", "build"]
    assert cli.main(["design", "run", str(near), "--json", *skip]) == 0
    out = json.loads(capsys.readouterr().out)
    (candidate,) = out["verdict"]["candidates"]
    assert candidate["level"] == "caution" and out["outcome"] == "passes with cautions"
    assert {c["topic"] for c in candidate["checks"] if c["level"] == "caution"} == {"voltage"}


def test_a_motion_the_data_cannot_decide_does_not_lift_a_part_that_fails(tmp_path, capsys, monkeypatch) -> None:
    """150 V on the 100 V part fails at the design point. A motion whose checks the data
    cannot decide (made so here by hand) leaves it failing: status 3, never undecided's 4."""
    real = design.cycle

    def undecided(request, workspace):
        found = real(request, workspace)
        found["checks"] = [{**c, "level": "undecided"} if c["level"] == "fail" else c for c in found["checks"]]
        return {**found, "level": "undecided"}

    monkeypatch.setattr(design, "cycle", undecided)
    over = started(tmp_path, conditions={"v_dc": 150})
    capsys.readouterr()
    assert cli.main(["design", "run", str(over), "--json", "--skip", "drive", "--skip", "build"]) == 3
    out = json.loads(capsys.readouterr().out)
    assert out["outcome"] == "does not pass" and out["motion"]["level"] == "undecided"
    assert "fail" not in {c["level"] for c in out["motion"]["checks"]}


def test_a_motor_load_and_profile_named_as_files_beside_the_design_are_read_from_there(tmp_path) -> None:
    """The motor, the load and the profile named by file, beside the design and not where the
    command runs: the design read is the same design with the three written into it."""
    import shutil

    folder = tmp_path / "beside"
    folder.mkdir()
    parts = {
        "motor": "motor_robot_joint_pmsm.yaml",
        "load": "load_robot_joint.yaml",
        "profile": "profile_joint_move.yaml",
    }
    for name in parts.values():
        shutil.copy(ROOT / "examples" / name, folder / name)
    conditions = {"v_dc": 48, "rpm": 2000, "torque": 1.0, "f_sw": 20000, "cooling": "held", "t_sink": 60}
    by_name = {"devices": ["example-mosfet"], "conditions": conditions, **parts}
    written_in = {
        **by_name,
        **{key: yaml.safe_load((folder / name).read_text(encoding="utf-8")) for key, name in parts.items()},
    }
    ws = page.Workspace(tmp_path / "ws")
    read = []
    for file, setup in (("named.yaml", by_name), ("written.yaml", written_in)):
        (folder / file).write_text(yaml.safe_dump(setup), encoding="utf-8")
        read.append(design.load_setup(folder / file, ws))
    assert read[0] == read[1]
    assert read[0]["motor"]["rs"] == 0.045 and read[0]["load"]["gear_ratio"] == 50
    assert [s["duration"] for s in read[0]["profile"]["segments"]] == [0.3, 0.45, 0.3, 2.0]


def test_a_design_names_up_to_five_devices(tmp_path) -> None:
    """Five devices, the most compared at once, are a design; a sixth is refused by count."""
    setup = design.starting_setup("example-mosfet", page.Workspace(tmp_path))
    design.validate_setup({**setup, "devices": ["example-mosfet"] * 5})
    with pytest.raises(design.Refusal) as caught:
        design.validate_setup({**setup, "devices": ["example-mosfet"] * 6})
    assert str(caught.value) == "6 devices are named, and 5 is the most compared at once"
    assert caught.value.fix == "name up to 5" and caught.value.field == "devices"


def test_devices_come_by_name_as_files_or_as_typed_figures_and_are_compared(tmp_path, capsys) -> None:
    (tmp_path / "typed.yaml").write_text(TEMPLATE, encoding="utf-8")
    file = started(
        tmp_path, devices=["example-mosfet", "typed.yaml", str(ROOT / "examples/synthetic_mosfet_100v_100a.yaml")]
    )
    capsys.readouterr()
    assert (
        cli.main(["design", "run", str(file), "--json", "--skip", "drive", "--skip", "motion", "--skip", "build"]) == 0
    )
    out = json.loads(capsys.readouterr().out)
    names = [c["name"] for c in out["verdict"]["candidates"]]
    assert len(names) == 3 and "Made-up Semiconductor MU100N04" in names and out["verdict"]["explain"]
    # A figure that cannot be right is refused with its name.
    (tmp_path / "typed.yaml").write_text(TEMPLATE.replace("rds_on: 4.0", "rds_on: 4000"), encoding="utf-8")
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
    assert (ROOT / "AGENTS.md").read_text(encoding="utf-8").count("motionsim agent") >= 1


def test_several_motors_on_one_inverter_and_every_device_through_the_motion(tmp_path, capsys) -> None:
    import csv

    file = started(tmp_path, devices=["example-mosfet", str(ROOT / "examples/synthetic_mosfet_100v_100a.yaml")])
    setup = yaml.safe_load(file.read_text(encoding="utf-8"))
    lighter = {**setup["motor"], "name": "half the current limit", "i_max": setup["motor"]["i_max"] / 2}
    cannot = {**setup["motor"], "name": "wound for mains", "kv": 2}
    setup["motors"] = [{**setup["motor"], "name": "as it is"}, lighter, cannot]
    del setup["motor"]
    file.write_text(yaml.safe_dump(setup), encoding="utf-8")
    table = tmp_path / "table.csv"
    capsys.readouterr()
    assert (
        cli.main(["design", "run", str(file), "--json", "--csv", str(table), "--skip", "drive", "--skip", "build"]) == 0
    )
    out = json.loads(capsys.readouterr().out)
    # Every device that ran goes through the motion; the one followed is the same answer twice.
    assert set(out["motions"]) == {c["id"] for c in out["verdict"]["candidates"]} and len(out["motions"]) == 2
    assert out["motions"][out["followed"]]["summary"] == out["motion"]["summary"]
    # Three motors on the device followed: the first is the design's own, the third cannot reach the point.
    first, second, third = out["motors"]
    assert first["name"] == "as it is" and first["loss"] == pytest.approx(
        out["verdict"]["candidates"][0]["result"]["loss"]
    )
    assert second["i_peak"] == pytest.approx(first["i_peak"]) and second["level"] in ("ok", "caution")
    assert "refused" in third and "wound for" in third["fix"] + third["refused"]
    # The table holds a row a device and a row a motor, with the figures of the report.
    listed = list(csv.DictReader(table.read_text(encoding="utf-8").splitlines()))
    assert [r["kind"] for r in listed] == ["device", "device", "motor", "motor", "motor"]
    assert float(listed[0]["loss_w"]) == pytest.approx(out["verdict"]["candidates"][0]["result"]["loss"])
    assert (
        float(listed[0]["motion_mean_loss_w"]) == pytest.approx(out["motion"]["summary"]["mean_loss"])
        and listed[0]["t_dead_s"]
    )
    assert listed[4]["verdict"] == "cannot run" and listed[4]["not_ok"]
    report = design.markdown(out)
    assert "## Through the motion, each device" in report and "## Motors compared" in report


def test_the_same_inputs_carry_the_same_marks_and_a_changed_one_does_not(tmp_path) -> None:
    ws = page.Workspace(tmp_path)
    setup = design.starting_setup("example-mosfet", ws)
    one, again = design.run(setup, ws, steps=()), design.run(setup, ws, steps=())
    assert one["marks"] == again["marks"] and len(one["marks"]["design"]) == 12
    moved = design.run({**setup, "conditions": {**setup["conditions"], "f_sw": 16000}}, ws, steps=())
    assert moved["marks"]["design"] != one["marks"]["design"] and moved["marks"]["devices"] == one["marks"]["devices"]
    assert f"Design {one['marks']['design']}" in design.markdown(one)


def test_a_design_with_a_slip_in_it_is_refused_in_words_never_a_fault(tmp_path, capsys) -> None:
    """A slip is said in words, at its figure: none is passed over, and none ends in a traceback."""
    good = yaml.safe_load(started(tmp_path).read_text(encoding="utf-8"))

    def status(change, name="d.yaml") -> tuple[int, dict]:
        file = tmp_path / name
        setup = {
            **good,
            **{
                k: ({**good[k], **v} if isinstance(v, dict) and isinstance(good.get(k), dict) else v)
                for k, v in change.items()
            },
        }
        file.write_text(yaml.safe_dump(setup), encoding="utf-8")
        capsys.readouterr()
        code = cli.main(["design", "run", str(file), "--json", "--skip", "drive"])
        return code, json.loads(capsys.readouterr().out)

    for change, field in (
        ({"conditions": {"t_snk": 170}}, "t_snk"),  # a mistyped name is not passed over
        ({"suply": "battery"}, "suply"),
        ({"supply": "nuclear"}, "supply"),
        ({"conditions": {"pwm": "abc"}}, "pwm"),
        ({"conditions": {"v_dc": "abc"}}, "v_dc"),
        ({"conditions": {"parallel": "abc"}}, "parallel"),
        ({"devices": 5}, "devices"),
        ({"devices": ["example-mosfet"] * 6}, "devices"),
        ({"motors": [good["motor"]]}, "motors"),  # both motor and motors
        ({"load": 5}, "load"),
    ):
        code, out = status(change)
        assert (code == 2 and out["outcome"] == "refused") or out.get("refusals"), (change, code, out.get("outcome"))
        assert out["field"] == field and out["refused"], (change, out)
    # A load with a mistyped figure: the motion is refused, said at the top, and the reason names the figure.
    code, out = status({"load": {"gear_ration": 3}})
    assert (
        code == 2
        and out["refusals"] == ["motion"]
        and "gear_ration" in out["refused"]
        and "pydantic" not in out["refused"]
    )
    # No torque at all is a point like any other.
    code, out = status({"conditions": {"torque": 0}})
    assert code == 0 and out["outcome"].startswith("passes")
    # Bytes that are not text, and a report that cannot be written.
    (tmp_path / "junk.yaml").write_bytes(bytes(range(256)))
    assert cli.main(["design", "run", str(tmp_path / "junk.yaml"), "--json"]) == 2
    capsys.readouterr()
    assert (
        cli.main(
            ["design", "run", str(started(tmp_path)), "--md", str(tmp_path / "nowhere" / "r.md"), "--skip", "drive"]
        )
        == 2
    )
    assert "cannot write" in capsys.readouterr().err


def test_the_winding_temperature_counts_wherever_it_is_given_and_two_files_of_one_name_are_two_devices(
    tmp_path, capsys
) -> None:
    ws = page.Workspace(tmp_path / "ws")
    setup = design.starting_setup("example-mosfet", ws)
    cold = design.run(setup, ws, steps=())["stage"]["stage"]["p_motor_loss"]
    in_conditions = design.run({**setup, "conditions": {**setup["conditions"], "t_motor": 150}}, ws, steps=())["stage"][
        "stage"
    ]["p_motor_loss"]
    in_motor = design.run({**setup, "motor": {**setup["motor"], "t_motor": 150}}, ws, steps=())["stage"]["stage"][
        "p_motor_loss"
    ]
    # Copper is about half as resistive again at 150 °C as at 25 °C, and the magnets weaker: the winding loses at least that much more.
    assert in_conditions == pytest.approx(in_motor) and in_conditions > cold * (1 + 0.00393 * 125) * 0.99
    # 48 and 48.0 are one design; a different figure is another.
    as_int = design.run({**setup, "conditions": {**setup["conditions"], "v_dc": 48}}, ws, steps=())["marks"]["design"]
    as_float = design.run({**setup, "conditions": {**setup["conditions"], "v_dc": 48.0}}, ws, steps=())["marks"][
        "design"
    ]
    assert (
        as_int
        == as_float
        != design.run({**setup, "conditions": {**setup["conditions"], "v_dc": 47}}, ws, steps=())["marks"]["design"]
    )
    # Two folders, two files called part.yaml, two different parts.
    for folder, rds in (("a", 4.0), ("b", 8.0)):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "part.yaml").write_text(
            TEMPLATE.replace("rds_on: 4.0", f"rds_on: {rds}").replace("rds_on_hot: 7.2", f"rds_on_hot: {rds * 1.8}"),
            encoding="utf-8",
        )
    file = started(tmp_path, devices=["a/part.yaml", "b/part.yaml"])
    capsys.readouterr()
    assert (
        cli.main(["design", "run", str(file), "--json", "--skip", "drive", "--skip", "build", "--skip", "motion"]) == 0
    )
    found = json.loads(capsys.readouterr().out)
    losses = sorted(c["result"]["conduction"] for c in found["verdict"]["candidates"])
    assert len(found["marks"]["devices"]) == 2 and losses[1] == pytest.approx(2 * losses[0], rel=0.05)


def test_the_page_answers_a_malformed_request_with_a_refusal_not_a_fault(tmp_path) -> None:
    ws = page.Workspace(tmp_path)
    good = design.starting_setup("example-mosfet", ws)
    one = {**good, "device": "example-mosfet"}
    asked = [
        (route, body)
        for route in (
            "/api/stage",
            "/api/proposal",
            "/api/cycle",
            "/api/map",
            "/api/capability",
            "/api/largest",
            "/api/recommend",
            "/api/fit",
            "/api/report",
        )
        for body in ([], 5, {}, {**one, "motor": None}, {**one, "conditions": 3}, {**one, "device": [], "devices": 5})
    ]
    asked += [
        ("/api/cycle", {**one, "start": 5}),
        ("/api/recommend", {**one, "driver_peak": "x"}),
        ("/api/fit", {**one, "parallel": "x"}),
        ("/api/largest", {**one, "load": {**good["load"], "inertia": "heavy"}}),
        ("/api/device", {}),
        ("/api/device", {"name": 3, "text": []}),
        ("/api/typed", []),
        ("/api/measure", {"device": 1}),
        ("/api/stage", {**one, "conditions": {**good["conditions"], "pwm": "abc"}}),
        ("/api/loads", {"kind": "pmsm", "rpm": 1e300, "torque": 1}),
    ]
    for route, body in asked:
        answer = json.loads(page.call(route, json.dumps(body), ws))
        assert answer["status"] in (200, 400, 422), (route, body, answer)
    # An answer never carries a figure that is not a number: none at all is what a browser can read.
    odd = json.loads(page.call("/api/stage", json.dumps({**one, "motor": {**good["motor"], "l": 1e-300}}), ws))
    assert "NaN" not in json.dumps(odd) and "Infinity" not in json.dumps(odd)


def test_the_page_can_ask_for_a_report_with_everything_it_sends(tmp_path) -> None:
    """The page's own request holds more than a design file may: how the drive starts, a
    mission, the link's capacitor. A file with a name out of place is refused; the page is not."""
    ws = page.Workspace(tmp_path)
    setup = design.starting_setup("example-mosfet", ws)
    sent = {
        **setup,
        "mission": None,
        "start": {"method": "sensor"},
        "precharge": None,
        "c_link": None,
        "heatsink": {"rth": None, "capacity": None, "t_ambient": 60},
        "repeats": 1,
    }
    answer = json.loads(page.call("/api/report", json.dumps(sent), ws))
    assert answer["status"] == 200 and "## Verdict at the design point" in answer["body"]["markdown"]
    with pytest.raises(page.Refused):
        design.run(sent, ws)  # the same, as a file: `mission`, `start` and `precharge` are not names of a design


def test_a_start_that_is_not_a_record_is_refused_in_words(tmp_path, capsys) -> None:
    setup = yaml.safe_load(started(tmp_path).read_text(encoding="utf-8"))
    file = tmp_path / "start.yaml"
    file.write_text(yaml.safe_dump({**setup, "start": "open_loop"}), encoding="utf-8")
    assert cli.main(["design", "run", str(file), "--json"]) in (0, 2, 3, 4)
    said = capsys.readouterr()
    assert "start: {method: open_loop}" in said.out + said.err and "Traceback" not in said.out + said.err


def test_the_design_mark_is_the_same_whether_a_figure_was_typed_or_written() -> None:
    """The page sends what was typed as text and a design file holds a number: kv 100 typed
    in and kv: 100.0 written down are one design, and carry one mark."""
    from motionsim.design.setup_file import _canon

    assert _canon({"motor": {"kv": "100"}}) == _canon({"motor": {"kv": 100.0}}) == _canon({"motor": {"kv": 100}})
    assert _canon({"motor": {"kv": " 1e2 "}}) == _canon({"motor": {"kv": 100}})
    assert _canon({"name": "my motor"}) != _canon({"name": "my  motor"})


@pytest.mark.parametrize(("parallel", "said"), [(1, "1 device a switch"), (2, "2 devices a switch")])
def test_the_report_says_how_many_devices_make_a_switch(tmp_path, parallel, said) -> None:
    setup = design.starting_setup("example-mosfet", page.Workspace(tmp_path))
    conditions = {**setup["conditions"], "parallel": parallel, "cooling": "held", "t_sink": 60}
    result = {
        "setup": {**setup, "conditions": conditions},
        "devices": {
            "example-mosfet": dict.fromkeys(("name", "technology", "switching"), "x")
            | {"v_max": 100, "i_nominal": 50, "tj_max": 175}
        },
    }
    switching = next(line for line in report._tested(result) if line.startswith("- Switching:"))
    assert switching.endswith(f", {said}")


def test_a_device_that_could_not_be_solved_is_reported_with_what_to_do() -> None:
    lines = report._candidate_section(
        {"name": "made-up part", "problem": "no stable temperature here.", "fix": "Lower the current.", "checks": []}
    )
    assert "No stable temperature here. Lower the current." in lines
