"""How the page says where a part's model comes from, true of each way a part arrives: made
up with the tool, typed from its datasheet's figures, read from its datasheet's PDF, a device
file as it was given, and a copy carrying the user's own double-pulse measurements. A typed
part is never said to be built from curves: its on-resistance is kept as a line, but it is
two figures typed from a table."""

from __future__ import annotations

import json

import pytest
import yaml

from motionsim import page
from motionsim.fit.typed import TEMPLATE, TYPED
from motionsim.text import whole

FET = yaml.safe_load(TEMPLATE)
BENCH = {
    "v_dc": 300,
    "energy_unit": "uJ",
    "points": [
        {"tj": 25, "current": 10, "e_on": 300, "e_off": 200},
        {"tj": 25, "current": 30, "e_on": 900, "e_off": 600},
    ],
}


@pytest.fixture
def ws(tmp_path):
    return page.Workspace(tmp_path)


def test_a_typed_part_is_built_from_the_figures_typed_not_from_curves(ws) -> None:
    added = page.add_typed(FET, ws)["device"]
    # Its on-resistance at two temperatures is kept as a curve: the words are of what was typed.
    assert ws.device(added["id"]).switch.conduction.basis.value == "curve"
    assert added["support"] == "the figures typed from the datasheet's tables, with shapes assumed between them"
    assert added["switching"] == "estimated from the gate and output charges typed from the datasheet"


def test_a_made_up_part_says_its_figures_are_made_up(ws) -> None:
    said = {d["id"]: (d["switching"], d["support"]) for d in ws.listing()}
    assert said["example"] == ("made-up switching energy", "made-up curves")
    assert said["example-gan"] == ("estimated from made-up gate and output charges", "made-up curves")
    assert said["example-mosfet"][1] == "made-up curves and table points, with shapes assumed between the points"


def test_a_device_file_and_a_datasheet_read_say_whose_figures_they_are(ws) -> None:
    text = page.add_typed(FET, ws)["text"].replace(TYPED, "a datasheet")
    added = page.add_device("given.device.yaml", text, ws)["device"]
    assert added["switching"] == "estimated from the device file's gate and output charges"
    assert added["support"] == "the device file's curves and table points, with shapes assumed between the points"
    # A part read from its PDF keeps what the reader took beside it.
    (ws.folder / "given.observations.yaml").write_text("{}", encoding="utf-8")
    read = ws.summary("given", ws.device("given"))
    assert read["switching"] == "estimated from the datasheet's gate and output charges"
    assert read["support"] == "the datasheet's curves and table points, with shapes assumed between the points"


def test_a_measured_copy_says_its_switching_is_the_users_own_measurement(ws) -> None:
    added = page.add_measurement("example", "bench.json", json.dumps(BENCH), ws)["device"]
    assert added["switching"] == "measured in your own double-pulse tests"
    assert added["support"] == "made-up curves"  # the rest of the part is the made-up one's


@pytest.mark.parametrize("text", ["a: [", "\t- x: y\n  : z", "[" * 3000], ids=["unclosed", "tab", "nested"])
def test_a_file_that_cannot_be_read_is_said_in_one_sentence_with_the_fix(ws, text) -> None:
    with pytest.raises(page.Refused) as refused:
        page.add_device("notes.yaml", text, ws)
    reason, fix = refused.value.reason, refused.value.fix
    assert reason.startswith("that file is not a device model: it is ")
    assert reason.count("file") == 1 and "<unicode string>" not in reason and "while " not in reason
    assert "`" not in fix and "motionsim build" in fix


def test_a_whole_number_in_a_sentence_is_written_as_the_page_writes_it() -> None:
    assert whole(1400) == "1 400"
    assert whole(100000.4) == "100 000"
    assert whole(-2000) == "-2 000"
    assert whole(999) == "999"
