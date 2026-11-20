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
    (tmp_path / "layout.yaml").write_text("l_loop_nh: 9\n")
    body = json.loads(run("event", "d.yaml", "--layout", "layout.yaml", "--json"))
    assert body["used"]["l_loop"] == pytest.approx(9e-9)
    told = run("event", "d.yaml", "--csv", "traces.csv", "--lcs", "1", "--voff", "-2")
    assert "Turn-off: energy" in told and "assumed: Loop inductance assumed 20 nH" in told
    assert "Common-source" not in told
    assert (tmp_path / "traces.csv").read_text().startswith("edge,t_s,v_gs_v,v_ds_v,i_a,p_w\nturn_on,")


def test_a_device_the_design_does_not_name_is_refused(tmp_path, capsys, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.main(["design", "init", "--device", "example-mosfet", "-o", "d.yaml"]) == 0
    assert cli.main(["event", "d.yaml", "--device", "example"]) == 2
    assert "cannot work out the event: example is not among the design's devices" in capsys.readouterr().err


def test_the_layout_template_is_written_by_the_command_line(capsys) -> None:
    assert cli.main(["template", "layout"]) == 0
    assert capsys.readouterr().out == TEMPLATE
