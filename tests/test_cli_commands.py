"""Each command of the command line, run: what it prints and writes, against figures
known another way."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest
import yaml

from motionsim import cli
from motionsim.device import load_device

ROOT = Path(__file__).parent.parent
IGBT = str(ROOT / "examples/synthetic_igbt_600v_30a.yaml")
MOSFET = str(ROOT / "examples/synthetic_mosfet_100v_100a.yaml")
PMSM = str(ROOT / "examples/motor_robot_joint_pmsm.yaml")
APPLIANCE = str(ROOT / "examples/motor_appliance_pmsm.yaml")
LOAD = str(ROOT / "examples/load_robot_joint.yaml")
PROFILE = str(ROOT / "examples/profile_joint_move.yaml")
POINT = ["--vdc", "300", "--m", "0.9", "--pf", "0.85", "--fsw", "8000", "--tsink", "60"]
JOINT = ["--motor", PMSM, "--vdc", "48", "--fsw", "20000", "--tsink", "60"]


def run(capsys, *argv: str) -> tuple[int, str]:
    status = cli.main(list(argv))
    said = capsys.readouterr()
    assert said.err == "", said.err
    return status, said.out


def figure(text: str, label: str) -> float:
    return float(re.search(rf"{re.escape(label)}\s+(-?[\d.]+)", text).group(1))


@pytest.mark.parametrize("limit, flags", [(150.0, []), (120.0, ["--tj", "120"])])
def test_max_current_is_the_largest_current_whose_range_stays_at_the_limit(capsys, limit, flags) -> None:
    status, out = run(capsys, "max-current", IGBT, *POINT, *flags)
    assert status == 0
    i_max, typical = figure(out, "maximum current"), figure(out, "on the typical estimate alone")
    # The answer, simulated: the top of the hottest junction's range stands at the limit, and
    # a little more current takes it over.
    _, again = run(capsys, "simulate", IGBT, *POINT, "--irms", f"{i_max:.2f}", "--json")
    assert json.loads(again)["result"]["tj_range"][1] == pytest.approx(limit, abs=0.5)
    _, more = run(capsys, "simulate", IGBT, *POINT, "--irms", f"{1.03 * i_max:.2f}", "--json")
    assert json.loads(more)["result"]["tj_range"][1] > limit
    # The figure beside it puts the typical estimate itself at the limit, and is more current.
    _, beside = run(capsys, "simulate", IGBT, *POINT, "--irms", f"{typical:.2f}", "--json")
    assert json.loads(beside)["result"]["tj_peak"] == pytest.approx(limit, abs=0.5)
    assert typical > i_max


def test_the_typical_maximum_is_not_a_pass_and_the_command_never_says_it_is(capsys) -> None:
    """At the current where the typical estimate meets the rating the range crosses it:
    simulate calls that undecided, so max-current must not hand it over as its answer."""
    _, out = run(capsys, "max-current", IGBT, *POINT, "--json")
    answer = json.loads(out)
    status, _ = run(capsys, "simulate", IGBT, *POINT, "--irms", f"{answer['i_max_typical'] * 0.995:.3f}")
    assert status == 4
    assert answer["result"]["tj_range"][1] <= 150.0 + 1e-6
    assert answer["level"] in ("ok", "caution")


@pytest.mark.parametrize("flags", [["--tsink", "150"], ["--tsink", "170"], ["--tj", "0"], ["--tj", "60"]])
def test_max_current_refuses_a_heatsink_at_or_above_the_limit(capsys, flags) -> None:
    point = [*POINT[:-2], *(flags if flags[0] == "--tsink" else ["--tsink", "60", *flags])]
    status = cli.main(["max-current", IGBT, *point])
    said = capsys.readouterr()
    assert status == 2
    assert "no current is small enough" in said.err and said.out == ""


def test_max_current_holds_a_limit_above_the_rating_to_the_rating(capsys) -> None:
    _, rated = run(capsys, "max-current", IGBT, *POINT)
    status, above = run(capsys, "max-current", IGBT, *POINT, "--tj", "200")
    assert status == 0
    assert "above the part's 150 °C rating: the rating is used" in above
    assert figure(above, "maximum current") == figure(rated, "maximum current")


def test_max_current_on_the_average_junction_allows_more_than_on_its_peak(capsys) -> None:
    _, on_peak = run(capsys, "max-current", IGBT, *POINT)
    _, on_average = run(capsys, "max-current", IGBT, *POINT, "--average")
    assert figure(on_average, "maximum current") > figure(on_peak, "maximum current") + 0.5


def test_advise_names_the_motor_and_says_what_to_look_for(capsys) -> None:
    status, out = run(
        capsys, "advise", "--motor", PMSM, "--vdc", "48", "--fsw", "20000", "--rpm", "1000", "--torque", "1"
    )
    lines = out.splitlines()
    assert status == 0 and lines[0] == "my motor (pmsm): 1 N·m at 1000 rpm from 48 V"
    advice = [line for line in lines if line.startswith("- ")]
    assert len(advice) >= 3 and any("V" in line for line in advice)
    status, out = run(
        capsys, "advise", "--motor", PMSM, "--vdc", "48", "--fsw", "20000", "--rpm", "1000", "--torque", "1", "--json"
    )
    assert [f"- {line}" for line in json.loads(out)["advice"]["lines"]] == advice


def test_a_map_is_the_motor_command_at_each_point_of_the_grid(capsys, tmp_path) -> None:
    table = tmp_path / "map.csv"
    # The gate drive is given: left open it is chosen at each command's own current.
    drive = ["--vdrive", "10", "--rgon", "5", "--rgoff", "5", "--tdead", "1e-7"]
    status, out = run(
        capsys, "map", MOSFET, *JOINT, *drive, "--rpm", "500:1500:3", "--torque", "0.5:1.5:2", "-o", str(table)
    )
    assert status == 0 and f"full map written to {table}" in out
    for title in ("Peak junction temperature, °C", "Inverter loss, W", "Shaft power over DC power, %"):
        assert title in out
    rows = list(csv.DictReader(table.read_text().splitlines()))
    assert [(float(r["rpm"]), float(r["torque_nm"])) for r in rows] == [
        (500.0, 0.5), (1000.0, 0.5), (1500.0, 0.5), (500.0, 1.5), (1000.0, 1.5), (1500.0, 1.5),
    ]  # fmt: skip
    at = next(r for r in rows if (float(r["rpm"]), float(r["torque_nm"])) == (1000.0, 1.5))
    _, one = run(capsys, "motor", MOSFET, *JOINT, *drive, "--rpm", "1000", "--torque", "1.5", "--json")
    point = json.loads(one)
    assert float(at["p_inverter_w"]) == pytest.approx(point["result"]["loss"], rel=1e-6)
    assert float(at["tj_peak_c"]) == pytest.approx(point["result"]["tj_peak"], abs=1e-6)
    assert float(at["i_peak_a"]) == pytest.approx(point["stage"]["i_peak"], rel=1e-6)


def test_a_point_the_motor_cannot_reach_is_a_dash_on_the_map(capsys) -> None:
    status, out = run(capsys, "map", MOSFET, *JOINT, "--rpm", "1000:200000:2", "--torque", "1:1:1")
    assert status == 0
    row = next(line for line in out.splitlines() if line.strip().startswith("1.00"))
    assert row.split()[-1] == "-" and row.split()[1] != "-"


def test_measure_puts_the_measured_energies_into_the_device(capsys, tmp_path) -> None:
    out_file = tmp_path / "measured.device.yaml"
    status, out = run(capsys, "measure", IGBT, str(ROOT / "examples/double_pulse_example.json"), "-o", str(out_file))
    assert status == 0 and "measured switching energy written" in out
    device = load_device(out_file)
    # The file's own figures: 0.86 mJ on and 0.52 mJ off at 40 A and 25 °C, taken at 400 V.
    cold = device.switch.e_on.curves[0]
    assert cold.tj == 25 and cold.current == [0.0, 20.0, 40.0]
    assert cold.value == pytest.approx([0.0, 0.33e-3, 0.86e-3])
    assert device.switch.e_off.curves[1].value == pytest.approx([0.0, 0.40e-3, 0.74e-3])
    assert device.switch.e_on.v_ref == 400 and device.switch.e_on.source.kind.value == "measured"


def test_a_measurement_that_is_not_one_is_refused(capsys, tmp_path) -> None:
    for name, text in (("not.json", "{not json"), ("empty.json", "{}"), ("list.json", "[1]")):
        file = tmp_path / name
        file.write_text(text)
        assert cli.main(["measure", IGBT, str(file), "-o", str(tmp_path / "out.yaml")]) == 2
        err = capsys.readouterr().err
        assert err.startswith("cannot measure: ") and "Traceback" not in err
    assert not (tmp_path / "out.yaml").exists()


def test_compare_ranks_by_loss_and_sweeps_the_frequency(capsys, tmp_path) -> None:
    # The same part with twice the on-state voltage loses more: it is ranked second.
    data = yaml.safe_load(Path(IGBT).read_text())
    data["part_number"] = "LOSSY-600V-30A"
    for curve in data["switch"]["conduction"]["curves"]:
        curve["value"] = [2 * v for v in curve["value"]]
    lossy = tmp_path / "lossy.yaml"
    lossy.write_text(yaml.safe_dump(data))
    status, out = run(capsys, "compare", str(lossy), IGBT, *POINT, "--irms", "10", "--sweep-fsw", "2000:20000")
    lines = out.splitlines()
    assert status == 0 and lines[0].split() == [
        "device",
        "loss",
        "W",
        "eff",
        "%",
        "Tj",
        "peak",
        "margin",
        "data",
        "support",
    ]
    assert "600 V IGBT" in lines[1] and "LOSSY-600V-30A" in lines[2]
    first = float(lines[1].split("600 V IGBT", 1)[1].split()[0])
    second = float(lines[2].split("LOSSY-600V-30A", 1)[1].split()[0])
    assert first == pytest.approx(45.4, abs=0.06)  # the README's 45.37 W, to one decimal
    assert second > first
    sweep = [line for line in lines if re.match(r"^\d+\.\d\s", line)]
    assert [float(line.split()[0]) for line in sweep] == [2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0]
    at_8k = next(line for line in sweep if line.startswith("8.0"))
    assert float(at_8k.split()[2]) == pytest.approx(45.4, abs=0.06)  # the second column is the second device named


PROPOSAL = [MOSFET, IGBT, "--motor", PMSM, "--fsw", "20000", "--tsink", "60", "--rpm", "1000", "--torque", "1"]


def test_propose_passes_where_any_device_passes(capsys) -> None:
    """At 150 V the 100 V transistor is past its rating and the 600 V part is not: the
    proposal is judged as a design is, by the device that passes, and exits 0."""
    status, out = run(capsys, "propose", *PROPOSAL, "--vdc", "150", "--json")
    levels = {c["name"]: c["level"] for c in json.loads(out)["candidates"]}
    assert levels == {"made-up 600 V IGBT": "ok", "made-up 100 V MOSFET": "fail"}
    assert status == 0
    # The one that passes leads alone: nothing is said to be level with it.
    status, table = run(capsys, "propose", *PROPOSAL, "--vdc", "150")
    assert status == 0 and "made-up 600 V IGBT" in table and "level on loss" not in table


@pytest.mark.parametrize(
    "levels, status",
    [(["undecided", "fail"], 4), (["fail", "fail"], 3), (["undecided", "caution"], 0), (["fail", "ok"], 0)],
)
def test_propose_with_none_passing_is_undecided_where_the_data_cannot_say(capsys, monkeypatch, levels, status) -> None:
    """The levels are set by hand on the answer the service gives: 4 when no device passes
    and one cannot be decided, 3 when every one fails, 0 whenever one passes."""
    from motionsim.cli import commands

    real = commands.ask

    def judged(route, request, ws):
        answer = real(route, request, ws)
        for candidate, level in zip(answer["candidates"], levels, strict=True):
            candidate["level"] = level
        return answer

    monkeypatch.setattr(commands, "ask", judged)
    assert run(capsys, "propose", *PROPOSAL, "--vdc", "48", "--json")[0] == status


def test_a_sweep_written_wrongly_is_refused(capsys) -> None:
    assert cli.main(["compare", IGBT, IGBT, *POINT, "--irms", "10", "--sweep-fsw", "2000"]) == 2
    assert "a sweep is written low:high" in capsys.readouterr().err


CYCLE = ["cycle", IGBT, "--motor", APPLIANCE, "--load", LOAD, "--profile", PROFILE, "--vdc", "300", "--fsw", "16000"]


def test_cycle_prints_the_motion_and_writes_every_instant(capsys, tmp_path) -> None:
    table = tmp_path / "instants.csv"
    status, out = run(capsys, *CYCLE, "--tsink", "60", "-o", str(table))
    assert status in (0, 3, 4)
    # The dead time filled in is said first, as on main: an IGBT's usual one, with no turn-off times.
    assert out.splitlines()[0].startswith("dead time taken as 1 µs, usual for an IGBT")
    assert out.splitlines()[1:3] == [
        "appliance PMSM (synthetic) (pmsm) driving my load through my move",
        "made-up 600 V IGBT (Si IGBT)",
    ]
    # The profile's own stretches: 0.3 + 0.45 + 0.3 + 2.0 s, twelve instants to each.
    assert figure(out, "duration") == pytest.approx(3.05)
    rows = list(csv.DictReader(table.read_text().splitlines()))
    assert len(rows) == 4 * 12
    assert list(rows[0]) == [
        "time_s", "motor_rpm", "motor_torque_nm", "p_stage_w", "p_dc_w", "tj_c", "tj_if_held_forever_c", "t_sink_c", "problem",
    ]  # fmt: skip
    assert float(rows[-1]["time_s"]) == pytest.approx(3.05, abs=1e-6)
    assert figure(out, "hottest junction") == pytest.approx(max(float(r["tj_c"]) for r in rows), abs=0.06)
    assert all(float(r["t_sink_c"]) == 60.0 for r in rows)  # held, with no heatsink followed
    assert "over the whole motion" in out and "checks:" in out


def test_cycle_follows_a_heatsink_as_it_warms(capsys) -> None:
    status, out = run(capsys, *CYCLE, "--tsink", "40", "--rth-sink", "0.5", "--c-sink", "50", "--repeat", "3")
    assert status in (0, 3, 4) and ", run 3 times" in out
    low, high, settles = (
        float(x) for x in re.search(r"heatsink\s+([\d.]+) to ([\d.]+) °C \(settles at ([\d.]+)", out).groups()
    )
    mean_loss = figure(out, "mean power-stage loss")
    assert low == 40.0 and low < high < settles
    assert settles == pytest.approx(40.0 + 0.5 * mean_loss, abs=0.06)  # ambient plus loss times resistance


def test_cycle_sizes_a_heatsink_when_given_the_air(capsys) -> None:
    status, out = run(capsys, *CYCLE, "--tsink", "60", "--tambient", "40")
    assert status in (0, 3, 4) and "heatsink for this motion repeated without pause" in out


def test_a_heatsink_given_by_half_is_refused(capsys) -> None:
    assert cli.main([*CYCLE, "--tsink", "60", "--rth-sink", "0.5"]) == 2
    assert "a heatsink needs both --rth-sink and --c-sink" in capsys.readouterr().err


def test_trajectory_checks_the_most_current_any_leg_carries(capsys, tmp_path) -> None:
    # One leg, 2 A for most of the time and 25 A for five samples in forty: a mean of 4.9 A.
    trace = tmp_path / "burst.csv"
    rows = ["time_s,i_a,d_a"] + [f"{k * 1e-3:.3f},{25 if 18 <= k <= 22 else 2},0.5" for k in range(40)]
    trace.write_text("\n".join(rows) + "\n")
    status, out = run(
        capsys, "trajectory", IGBT, str(trace), "--vdc", "300", "--fsw", "8000", "--tsink", "60", "--json"
    )
    answer = json.loads(out)
    assert answer["i_peak"] == pytest.approx(25.0, abs=1e-9)
    current = next(c for c in answer["checks"] if c["topic"] == "current")
    assert "peak current 25 A against a 30 A rating" in current["message"]
    assert status in (0, 3, 4)


def test_recommend_takes_the_limits_given_on_the_command_line(capsys) -> None:
    base = [
        "recommend",
        MOSFET,
        *JOINT,
        "--rpm",
        "1000",
        "--torque",
        "1",
        "--vdrive",
        "10",
        "--rgon",
        "5",
        "--rgoff",
        "5",
    ]
    _, usual = run(capsys, *base, "--json")
    _, slow = run(capsys, *base, "--dvdt", "0.5", "--json")
    gate = lambda text: next(i for i in json.loads(text)["items"] if i["topic"] == "gate resistors")["value"]
    # A tenth of the slew rate allowed asks for more resistance at turn-on.
    assert gate(slow)["rg_on"] > gate(usual)["rg_on"]
