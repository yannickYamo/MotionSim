"""The switching event as the page and the command line ask for it: the same voltage,
current and energies as the loss chart, each assumption named until a figure replaces it,
the layout file read alike everywhere, and the existing checks left as they were."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from motionsim import cli, design, page
from motionsim.errors import Refusal
from motionsim.event.calibrate import TOLERANCE
from motionsim.event.layout import TEMPLATE, read_layout


@pytest.fixture(scope="module")
def ws(tmp_path_factory):
    return page.Workspace(Path(tmp_path_factory.mktemp("event")))


def ask(ws, route: str, body: dict) -> dict:
    return json.loads(page.call(route, json.dumps(body), ws))


@pytest.fixture(scope="module")
def answers(ws) -> dict:
    """The event and the loss chart's period of the two example parts at their starting designs."""
    out = {}
    for key in ("example-mosfet", "example"):
        start = design.starting_setup(key, ws)
        chart = ask(ws, "/api/proposal", {**start, "devices": [key]})["body"]["candidates"][0]["pwm"]
        out[key] = (start, chart, ask(ws, "/api/event", {**start, "device": key}))
    return out


@pytest.mark.parametrize("key", ["example-mosfet", "example"])
def test_the_event_is_the_loss_charts_own_switching(answers, key) -> None:
    """The event is worked out at the chart's current, and each edge is made to lose the
    chart's energy, within the stated tolerance: the zoom never contradicts the overview."""
    _, chart, got = answers[key]
    assert got["status"] == 200, got
    body = got["body"]
    assert body["current"] == chart["current"]
    assert body["position"] == chart["position"]
    for edge, energy in (("turn_on", "e_on"), ("turn_off", "e_off")):
        assert body[edge]["target"] == chart[energy]
        assert body[edge]["met"], body["notes"]
        assert body[edge]["energy"] == pytest.approx(chart[energy], rel=TOLERANCE)


@pytest.mark.parametrize("key", ["example-mosfet", "example"])
def test_every_trace_is_there_and_finite(answers, key) -> None:
    body = answers[key][2]["body"]
    for edge in ("turn_on", "turn_off"):
        e = body[edge]
        n = len(e["t"])
        assert n > 200
        assert all(len(e[k]) == n for k in ("v_gs", "v_ds", "i", "p"))
        assert all(b > a for a, b in zip(e["t"], e["t"][1:], strict=False))
        assert e["v_peak"] >= body["v_dc"] * 0.99


def test_each_figure_nobody_gave_is_named_as_assumed(answers) -> None:
    body = answers["example-mosfet"][2]["body"]
    said = {a["field"]: a["text"] for a in body["assumed"]}
    assert said["l_loop"].startswith("Loop inductance assumed 20 nH (a TO-220 on a compact board)")
    assert "give yours" in said["l_loop"]
    assert {"l_cs", "l_g", "v_off", "damping"} <= set(said)


def test_a_figure_given_replaces_its_assumption(ws, answers) -> None:
    start, _, _ = answers["example-mosfet"]
    conditions = {**start["conditions"], "l_loop": 7e-9}
    body = {**start, "conditions": conditions, "device": "example-mosfet", "event": {"l_cs_nh": "1.5", "v_off": "-3"}}
    got = ask(ws, "/api/event", body)["body"]
    fields = {a["field"] for a in got["assumed"]}
    assert not fields & {"l_loop", "l_cs", "v_off"}
    assert got["used"]["l_loop"] == pytest.approx(7e-9)
    assert got["used"]["l_cs"] == pytest.approx(1.5e-9)
    assert got["used"]["v_off"] == -3


def test_a_tighter_loop_overshoots_less(ws, answers) -> None:
    start, _, loose = answers["example-mosfet"]
    tight = ask(
        ws, "/api/event", {**start, "conditions": {**start["conditions"], "l_loop": 4e-9}, "device": "example-mosfet"}
    )
    over = lambda b: b["turn_off"]["v_peak"] - b["v_dc"]
    assert over(tight["body"]) < 0.9 * over(loose["body"])


def test_the_layout_file_is_read_and_its_figures_used(ws, answers) -> None:
    start, _, _ = answers["example-mosfet"]
    text = "l_loop_nh: 9\nl_cs_nh: 0.5\nr_loop_mohm: 3\n"
    got = ask(ws, "/api/event", {**start, "device": "example-mosfet", "event": {"layout": text}})["body"]
    assert got["used"]["l_loop"] == pytest.approx(9e-9)
    assert got["used"]["l_cs"] == pytest.approx(0.5e-9)
    assert got["used"]["r_loop"] == pytest.approx(3e-3)
    # A box in the fold stands over the file.
    boxed = {"layout": text, "l_cs_nh": "2"}
    assert ask(ws, "/api/event", {**start, "device": "example-mosfet", "event": boxed})["body"]["used"][
        "l_cs"
    ] == pytest.approx(2e-9)


def test_the_layout_template_reads_as_nothing_given() -> None:
    assert all(v is None for v in read_layout(TEMPLATE).__dict__.values())


@pytest.mark.parametrize(
    "text, said, field",
    [
        ("l_lop_nh: 9", "did you mean l_loop_nh", "layout"),
        ("l_loop_nh: 5000", "outside 0.1 to 1000 nH", "l_loop_nh"),
        ("l_loop_nh: lots", "is not a number", "l_loop_nh"),
        ("- 9\n- 10", "does not hold names and values", "layout"),
        ("l_loop_nh: [9", "is not YAML that can be read", "layout"),
    ],
)
def test_a_layout_file_that_cannot_be_used_is_refused_in_words(text, said, field) -> None:
    with pytest.raises(Refusal) as refused:
        read_layout(text)
    assert said in refused.value.reason + refused.value.fix
    assert refused.value.field == field


def test_a_box_out_of_its_range_is_refused_with_its_name(ws, answers) -> None:
    start, _, _ = answers["example-mosfet"]
    got = ask(ws, "/api/event", {**start, "device": "example-mosfet", "event": {"v_off": "5"}})
    assert got["status"] == 422
    assert got["body"]["field"] == "v_off"


def test_an_igbt_has_a_tail_and_no_avalanche(answers) -> None:
    body = answers["example"][2]["body"]
    assert body["kind"] == "igbt"
    assert body["turn_off"]["tail"] > 0
    # Once the channel has closed the tail is what is left of the current, and it dies away.
    i = body["turn_off"]["i"]
    assert max(abs(x) for x in i[-20:]) < 0.05 * body["current"]


def test_the_command_line_gives_the_same_event(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    def run(*argv: str) -> str:
        assert cli.main(list(argv)) == 0
        return capsys.readouterr().out

    run("design", "init", "--device", "example-mosfet", "-o", "d.yaml")
    (tmp_path / "layout.yaml").write_text("l_loop_nh: 9\n", encoding="utf-8")
    body = json.loads(run("event", "d.yaml", "--layout", "layout.yaml", "--json"))
    assert body["used"]["l_loop"] == pytest.approx(9e-9)
    told = run("event", "d.yaml", "--csv", "traces.csv", "--lcs", "1", "--voff", "-2")
    assert "Turn-off: energy" in told and "assumed: Loop inductance assumed 20 nH" in told
    assert "Common-source" not in told
    assert (tmp_path / "traces.csv").read_text(encoding="utf-8").startswith("edge,t_s,v_gs_v,v_ds_v,i_a,p_w\nturn_on,")


def test_a_device_the_design_does_not_name_is_refused(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["design", "init", "--device", "example-mosfet", "-o", "d.yaml"]) == 0
    assert cli.main(["event", "d.yaml", "--device", "example"]) == 2
    assert "cannot work out the event: example is not among the design's devices" in capsys.readouterr().err


def test_the_layout_template_is_written_by_the_command_line(capsys) -> None:
    assert cli.main(["template", "layout"]) == 0
    assert capsys.readouterr().out == TEMPLATE


# ---------- figures the event cannot be drawn with, and figures left out ----------


@pytest.mark.parametrize("key", ["example-mosfet", "example"])
@pytest.mark.parametrize("henries", [0, 0.05e-9])
def test_a_loop_of_no_inductance_is_taken_for_the_losses_and_refused_for_the_event(ws, answers, key, henries) -> None:
    """The loss model reads the loop inductance for the overshoot alone, and nought leaves it
    out. The event's current moves through that inductance: with none there is no time for it
    to move in, and nothing to ring. Under the layout file's own least, 0.1 nH, it is refused."""
    start, _, _ = answers[key]
    body = {**start, "conditions": {**start["conditions"], "l_loop": henries}, "device": key}
    assert ask(ws, "/api/point", body)["status"] == 200
    got = ask(ws, "/api/event", body)
    assert got["status"] == 422, got
    assert got["body"]["field"] == "l_loop"
    assert "loop inductance of at least 0.1 nH" in got["body"]["refused"]
    assert f"{henries * 1e9:g} nH" in got["body"]["refused"]
    assert "leave it empty" in got["body"]["fix"]


def test_the_event_and_a_layout_file_hold_the_loop_inductance_to_the_same_least() -> None:
    from motionsim.event.layout import FIGURES
    from motionsim.event.parts import LEAST_LOOP

    _, factor, low, _, _ = FIGURES["l_loop_nh"]
    assert pytest.approx(low * factor) == LEAST_LOOP == 0.1e-9


def test_a_loop_whose_only_inductance_is_the_capacitors_own_is_drawn(ws, answers) -> None:
    start, _, _ = answers["example-mosfet"]
    conditions = {**start["conditions"], "l_loop": 0}
    asked = {**start, "conditions": conditions, "device": "example-mosfet", "event": {"layout": "esl_nh: 5\n"}}
    got = ask(ws, "/api/event", asked)
    assert got["status"] == 200, got
    assert got["body"]["used"]["l_loop"] == 0
    assert got["body"]["turn_off"]["v_peak"] > got["body"]["v_dc"]  # 5 nH still overshoots


def test_gate_loop_and_common_source_inductance_given_as_nought_are_the_event_with_them_left_out(ws, answers) -> None:
    start, _, plain = answers["example-mosfet"]
    got = ask(ws, "/api/event", {**start, "device": "example-mosfet", "event": {"l_g_nh": "0", "l_cs_nh": 0}})
    assert got["status"] == 200, got
    assert not {"l_g", "l_cs"} & {a["field"] for a in got["body"]["assumed"]}
    for edge in ("turn_on", "turn_off"):
        for figure in ("energy", "v_peak", "i_peak", "dv_dt", "di_dt"):
            assert got["body"][edge][figure] == plain["body"][edge][figure], (edge, figure)


@pytest.mark.parametrize(
    "key, change, field, said",
    [
        ("example-mosfet", {"rg_on": 0}, "rg_on", "turn-on gate resistance cannot be below 0.01 Ω"),
        ("example", {"rg_off": 0}, "rg_off", "turn-off gate resistance cannot be below 0.01 Ω"),
        ("example", {"v_drive": 0}, "v_drive", "gate drive voltage cannot be below 0.1 V"),
        # The made-up MOSFET's gate charge gives its plateau as 4.6 V.
        ("example-mosfet", {"v_drive": 3}, "v_drive", "gate drive voltage 3 V does not exceed the plateau (4.6 V)"),
        ("example-mosfet", {"v_drive": 4.6}, "v_drive", "gate drive voltage 4.6 V does not exceed the plateau (4.6 V)"),
        ("example", {"v_drive": 0.1}, "v_drive", "gate drive voltage above the plateau: 0.1 V was given"),
    ],
)
def test_a_gate_drive_that_cannot_switch_the_part_is_refused_with_its_name(
    ws, answers, key, change, field, said
) -> None:
    start, _, _ = answers[key]
    got = ask(ws, "/api/event", {**start, "conditions": {**start["conditions"], **change}, "device": key})
    assert got["status"] == 422, got
    assert got["body"]["field"] == field
    assert said in got["body"]["refused"]
    assert got["body"]["fix"]


def test_an_igbt_driven_to_its_plateau_and_no_further_is_refused_for_the_event(ws, answers) -> None:
    """At the plateau the channel carries the load's current and no more: nothing is left to
    charge the gate-drain capacitance with, and the edge never ends."""
    start, _, plain = answers["example"]
    plateau = plain["body"]["used"]["v_plateau"]
    assert 5 < plateau < 12  # an IGBT's, between its threshold and the 15 V it is driven with
    conditions = {**start["conditions"], "v_drive": plateau}
    got = ask(ws, "/api/event", {**start, "conditions": conditions, "device": "example"})
    assert got["status"] == 422, got
    assert got["body"]["field"] == "v_drive"
    assert f"the plateau is {plateau:g} V" in got["body"]["refused"]
