"""The made-up parts the page can be tried with: each opens on the application such a part is
found in, from the supply such products run from, and gives an answer there that a design
review could use, not a refusal or a part that fails on its own example."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from motionsim import cli, dclink, guard
from motionsim.design import starting_setup
from motionsim.device import load_device
from motionsim.service.applications import APPLICATIONS
from motionsim.service.presets import suggest
from motionsim.service.workspace import EXAMPLES, USES, Workspace

ROOT = Path(__file__).parent.parent
OPENS_ON = {
    "example": ("drum", 325, "one-way"),
    "example-mosfet": ("joint", 48, "one-way"),
    "example-mosfet-40v": ("tool", 24, "battery"),
    "example-gan": ("vacuum", 25.2, "battery"),
    "example-sic": ("compressor", 325, "one-way"),
    "example-sic-module": ("vehicle", 800, "battery"),
}


def test_six_made_up_parts_cover_each_technology_and_a_use_each() -> None:
    assert set(EXAMPLES) == set(USES) == set(OPENS_ON)
    technologies = {load_device(path).technology for path in EXAMPLES.values()}
    assert technologies == {"Si IGBT", "Si MOSFET", "GaN HEMT", "SiC MOSFET"}
    assert all(use.application in APPLICATIONS for use in USES.values())
    # Each is also among the example files a pip user is shown, under the same figures.
    shipped = {p.read_text(encoding="utf-8") for p in (ROOT / "examples").glob("synthetic_*.yaml")}
    assert all(path.read_text(encoding="utf-8") in shipped for path in EXAMPLES.values())


@pytest.mark.parametrize("key", list(OPENS_ON))
def test_a_made_up_part_opens_on_its_application_from_the_supply_such_products_run_from(key, tmp_path) -> None:
    ws = Workspace(tmp_path / "ws")
    application, v_dc, supply = OPENS_ON[key]
    told = suggest({"device": key}, ws)
    assert told["application"]["id"] == application and told["application"]["supply"] == supply
    assert told["v_supply"] == pytest.approx(v_dc)
    assert [k for k, m in told["motors"].items() if m["fit"] == "recommended"] == [told_kind(told)]
    assert all(m["start"]["v_dc"] == pytest.approx(v_dc) for m in told["motors"].values())
    design = starting_setup(key, ws)
    assert design["load_kind"] == application and design["supply"] == supply


def told_kind(told: dict) -> str:
    return next(k for k, m in told["motors"].items() if m["fit"] == "recommended")


@pytest.mark.parametrize("key", list(OPENS_ON))
def test_each_made_up_part_gives_an_answer_on_its_own_application(key, tmp_path, capsys) -> None:
    """A part that failed on the application it opens on would teach nothing but distrust."""
    file = tmp_path / "design.yaml"
    file.write_text(yaml.safe_dump(starting_setup(key, Workspace(tmp_path / "ws"))), encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["design", "run", str(file), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["outcome"] in ("passes", "passes with cautions"), out["outcome"]
    checks = (out["verdict"].get("checks") or []) + (out["motion"].get("checks") or [])
    assert out["motion"]["checks"], "the motion of its application was followed"
    failed = [c for c in checks if c["level"] == "fail"]
    assert not failed, failed


def test_the_other_kinds_are_wound_again_for_the_supply_the_application_brings(tmp_path) -> None:
    """The IGBT's washer runs from rectified mains, below the 400 V the part suits: every other
    kind of motor is wound for 325 V too, so each still reaches its own starting point."""
    from motionsim.service.validate import _motor

    told = suggest({"device": "example"}, Workspace(tmp_path / "ws"))
    for kind, m in told["motors"].items():
        motor = _motor({"type": kind, **m["values"]})
        s = m["start"]
        motor.stage(s["rpm"], s["torque"], s["v_dc"], motor.default_pwm)  # raises where it cannot


def test_braking_any_link_capacitor_holds_is_no_caution() -> None:
    """A compressor coasting to a stop gives back a few millijoules: no link needs a capacitor for that."""
    tiny = dclink.Returned(0.0025, 0.0025, 0.0033, 0.75, None, 3e-8, 600.0)
    assert [c.level for c in dclink.check(tiny, 325, 650, supply="one-way")] == [guard.Level.ok]
    real = dclink.Returned(1910, 983, 15, 106, None, 0.0158, 600.0)
    assert [c.level for c in dclink.check(real, 325, 600, supply="one-way")] == [guard.Level.caution]


def test_ripple_is_weighed_against_the_motions_peak_not_a_pause(tmp_path, capsys) -> None:
    """The washer's ripple is largest in a pause, when almost no current flows: against that it
    read as 2684%, against the 6 A the tumble and the spin draw it is a few per cent."""
    file = tmp_path / "design.yaml"
    file.write_text(yaml.safe_dump(starting_setup("example", Workspace(tmp_path / "ws"))), encoding="utf-8")
    capsys.readouterr()
    assert cli.main(["design", "run", str(file), "--json"]) == 0
    ripple = [c for c in json.loads(capsys.readouterr().out)["motion"]["checks"] if c["topic"] == "ripple"]
    assert [c["level"] for c in ripple] == ["ok"], ripple


def test_the_command_line_names_every_made_up_part() -> None:
    from motionsim.cli.parser import DEVICE

    assert all(key in DEVICE.split(": ")[-1].split(", ") for key in EXAMPLES)
