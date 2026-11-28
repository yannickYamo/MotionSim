"""The DC link in the control lab, for a drive fed from the mains: the link through a run, what
the verdict says of it, the two explorations, and the front end's controller in the C bundle."""

from __future__ import annotations

import io
import math
import zipfile

import pytest
from test_control_bench import started, workspace

from motionsim.control.codegen.replay import compiler
from motionsim.control.verdict_link import link_findings
from motionsim.service.routes import dispatch

ONE = {"v": 230, "f": 50, "phases": 1}
THREE = {"v": 400, "f": 50, "phases": 3}


@pytest.fixture(scope="module")
def ws():
    return workspace()


@pytest.fixture(scope="module")
def servo(ws):
    base = started("example-sic", ws)
    _, presets = dispatch("/api/control/presets", {k: base[k] for k in ("motor", "conditions", "device")}, ws)
    return next(s for s in presets["schemes"] if s["id"] == "foc_servo")


def design(ws, mains=ONE, v_dc=390, **front_end) -> dict:
    base = started("example-sic", ws)
    return {
        "motor": base["motor"],
        "conditions": base["conditions"] | {"v_dc": v_dc},
        "device": base["device"],
        "supply": "mains",
        "mains": mains,
        "front_end": {"topology": None} | front_end,
    }


def ran(ws, servo, **more) -> dict:
    status, body = dispatch(
        "/api/control/run", design(ws, **more) | {"scheme": servo, "scenario": {"kind": "load_step"}}, ws
    )
    assert status == 200, body
    return body


@pytest.fixture(scope="module")
def tied(ws, servo):
    return ran(ws, servo)


@pytest.fixture(scope="module")
def speed(ws, servo):
    asked = design(ws) | {"scheme": servo, "scenario": {"kind": "speed_step"}}
    return dispatch("/api/control/run", asked, ws)[1]


@pytest.fixture(scope="module")
def alone(ws, servo):
    return ran(ws, servo, feed_forward=False)


def found(body: dict, ident: str) -> dict | None:
    return next((f for f in body["verdict"]["findings"] if f["id"] == ident), None)


def test_a_run_fed_from_the_mains_carries_its_link(ws, tied, speed) -> None:
    link, series = tied["link"], tied["series"]
    _, stage = dispatch("/api/front-end", {k: v for k, v in design(ws).items() if k != "supply"}, ws)
    limit = next(b["params"]["limit"] for b in tied["scheme"]["blocks"] if b["kind"] == "speed_pi")
    sized_for = stage["result"]["p_link"] * limit / design(ws)["conditions"]["torque"]
    assert limit > design(ws)["conditions"]["torque"]
    # Another test of the same design: the same capacitor, the same controller.
    assert speed["link"]["c"] == link["c"]
    assert link["stage"] == "totem_pole" and link["shapes"] and link["feed_forward"]
    assert link["v_ref"] == 390.0 and link["v_rating"] == 650.0
    # No capacitance given: one sized for a twentieth of the link's voltage at twice the mains, on
    # the most the drive's control can ask at the design speed; the test run has no say in it.
    assert link["c_sized"] and link["c"] == pytest.approx(sized_for / (2 * math.pi * 50 * 390**2 * 0.05), rel=1e-6)
    assert not link["collapsed"] and not link["braked"]
    # What the mains gives is what the inverter drew, once settled: the last period of the mains.
    t, p_in = series["t"], series["wires"]["link.p_in"]
    last = [p for at, p in zip(t, p_in, strict=True) if at >= t[-1] - 0.02]
    assert sum(last) / len(last) == pytest.approx(link["p_mean"], rel=0.08)
    for name in ("link.v_dc", "link.p_in", "link.i_line"):
        assert len(series["wires"][name]) == len(series["t"])
        assert any(w["name"] == name and w["block"] == "link" for w in tied["wires"])
    assert min(series["wires"]["link.v_dc"]) >= link["v_min"] - 1e-9
    assert not any("mains" in line or "front_end" in line for line in tied["taken"])


def test_tied_to_the_motor_s_control_the_link_holds_and_alone_it_sags(tied, alone) -> None:
    held, sag = found(tied, "link_held"), found(alone, "link_sag")
    assert held is not None and held["tag"] == "good" and "told of the motor's power" in held["said"]
    assert found(tied, "link_sag") is None
    assert sag is not None and sag["tag"] == "improve"
    assert sag["lever"] == {"kind": "design", "param": "fe_link"}
    assert "nothing told it of the motor's power" in sag["said"]
    assert 390.0 - alone["link"]["v_min"] > 2.5 * (390.0 - tied["link"]["v_min"])
    # The motor's own run is the same: the tie changes the link, which this run holds steady.
    assert alone["losses"]["loss"] == pytest.approx(tied["losses"]["loss"], rel=1e-9)


def test_three_phases_and_a_rectifier(ws, servo) -> None:
    whole = ran(ws, servo, mains=THREE, v_dc=680, topology="active")
    active = whole["link"]
    assert active["phases"] == 3 and active["returns"] and active["ripple"] < 2.0
    assert 680.0 - active["v_min"] < 5.0
    # A set point over the part's rating is the front end's own check; no braking is said of it.
    assert not active["braked"] and not any(f["id"] == "link_over" for f in whole["verdict"]["findings"])
    plain = ran(ws, servo, v_dc=309, topology="rectifier")
    assert plain["link"]["shapes"] is False and plain["link"]["thd"] is None
    assert plain["link"]["v_max"] == pytest.approx(230 * 2**0.5, rel=0.005)
    assert found(plain, "link_ripple") is not None and found(plain, "link_held") is None
    # A line's current goes both ways through a bridge.
    line = plain["series"]["wires"]["link.i_line"]
    assert min(line) < -5.0 and max(line) > 5.0


def test_cells_side_by_side_act_as_one_of_their_inductance_shared(ws, servo) -> None:
    one = ran(ws, servo, topology="boost")["link"]
    two = ran(ws, servo, topology="interleaved")["link"]
    assert two["stage"] == "interleaved" and not two["returns"] and not two["collapsed"]
    assert two["v_min"] == pytest.approx(one["v_min"], abs=3.0) and two["thd"] < 0.05


def test_a_link_that_is_not_held_is_said_so_and_nothing_else_of_it(ws, servo) -> None:
    asked = design(ws) | {"scheme": servo, "scenario": {"kind": "load_step"}, "c_link": 5e-6}
    status, body = dispatch("/api/control/run", asked, ws)
    assert status == 200 and body["link"]["collapsed"]
    assert body["link"]["v_min"] > 0 and body["link"]["v_max"] < 4 * 390.0
    said = [f for f in body["verdict"]["findings"] if f["topic"] == "link"]
    assert [f["id"] for f in said] == ["link_lost"] and "5 µF" in said[0]["said"]


@pytest.mark.parametrize("share", ["abc", -1, 1e-9])
def test_a_share_of_the_capacitance_that_cannot_be_is_refused(ws, servo, share) -> None:
    asked = design(ws) | {"scheme": servo, "scenario": {"kind": "load_step"}, "link_share": share}
    status, body = dispatch("/api/control/run", asked, ws)
    assert status == 422 and body["field"] == "link.capacitance"


def test_a_tie_that_is_neither_on_nor_off_is_refused(ws, servo) -> None:
    asked = design(ws, feed_forward="false") | {"scheme": servo, "scenario": {"kind": "load_step"}}
    status, body = dispatch("/api/control/run", asked, ws)
    assert status == 422 and body["field"] == "front_end.feed_forward"


def test_a_drive_not_fed_from_the_mains_has_no_link(ws, servo) -> None:
    asked = design(ws) | {"scheme": servo, "scenario": {"kind": "load_step"}, "supply": "battery"}
    status, body = dispatch("/api/control/run", asked, ws)
    assert status == 200 and "link" not in body and "link.v_dc" not in body["series"]["wires"]
    assert not any(f["topic"] == "link" for f in body["verdict"]["findings"])


LINK = {
    "stage": "boost",
    "name": "Boost PFC",
    "shapes": True,
    "returns": False,
    "phases": 1,
    "f": 50.0,
    "feed_forward": True,
    "v_ref": 390.0,
    "v_min": 388.0,
    "v_max": 392.0,
    "ripple": 3.0,
    "thd": 0.02,
    "i_peak": 9.0,
    "c": 600e-6,
    "c_sized": False,
    "need": 260.0,
    "v_rating": 650.0,
    "braked": True,
    "collapsed": False,
}


def test_braking_past_the_rating_is_the_first_thing_said_of_the_link() -> None:
    over = link_findings({"link": LINK | {"v_max": 700.0}})
    assert over[0]["id"] == "link_over" and over[0]["severity"] == 5
    assert "past the device's 650 V rating" in over[0]["said"] and "gives nothing back" in over[0]["said"]
    assert over[0]["lever"] == {"kind": "design", "param": "front_end"}
    near = link_findings({"link": LINK | {"v_max": 600.0}})
    assert near[0]["severity"] == 3 and "within a tenth" in near[0]["said"]
    back = link_findings({"link": LINK | {"v_max": 700.0, "returns": True}})
    assert back[0]["lever"] == {"kind": "design", "param": "c_link"}
    assert [f["id"] for f in link_findings({"link": LINK})] == ["link_held"]
    # A link that is high without having braked, or that braked without rising, is not this.
    assert not any(f["id"] == "link_over" for f in link_findings({"link": LINK | {"v_max": 700.0, "braked": False}}))
    high = LINK | {"v_ref": 680.0, "v_min": 678.0, "v_max": 681.0}
    assert not any(f["id"] == "link_over" for f in link_findings({"link": high}))
    assert [f["id"] for f in link_findings({"link": LINK | {"collapsed": True}})] == ["link_lost"]
    assert link_findings({}) == []


def test_a_link_under_what_the_motor_needs_is_said_with_what_the_run_does_not_show() -> None:
    low = link_findings({"link": LINK | {"v_min": 250.0, "feed_forward": False}})
    assert low[0]["id"] == "link_sag" and low[0]["severity"] == 4
    assert "under the 260 V the motor needs" in low[0]["said"] and "does not show" in low[0]["said"]
    # A rectifier's troughs are its ripple, unless they reach under the need.
    plain = LINK | {"shapes": False, "feed_forward": False, "v_ref": 303.0, "v_min": 275.0, "ripple": 48.0}
    assert [f["id"] for f in link_findings({"link": plain})] == ["link_ripple"]
    assert link_findings({"link": plain | {"v_min": 255.0}})[0]["id"] == "link_sag"
    bent = link_findings({"link": LINK | {"thd": 0.09}})
    assert any(f["id"] == "link_distortion" and f["tag"] == "note" and "9 % off a sine" in f["said"] for f in bent)


def test_a_load_that_swings_reaches_the_mains_through_the_tie_and_the_verdict_says_so() -> None:
    swung = LINK | {"thd": 0.4, "p_swing": 900.0, "p_mean": 1000.0}
    said = next(f for f in link_findings({"link": swung}) if f["id"] == "link_distortion")
    assert said["tag"] == "improve" and said["lever"] == {"kind": "design", "param": "fe_link"}
    assert "swings 900 W" in said["said"] and "40 % off a sine" in said["said"]
    assert "capacitor takes the swing" in said["expect"]
    # A power that hardly moves: a note, with no lever to pull.
    note = next(f for f in link_findings({"link": swung | {"p_swing": 50.0}}) if f["id"] == "link_distortion")
    assert note["tag"] == "note" and note["lever"] is None
    # Untied with a power still moving, the last period is a transient: nothing is said of the shape.
    untied = link_findings({"link": swung | {"feed_forward": False}})
    assert not any(f["id"] == "link_distortion" for f in untied)


def test_the_link_s_explorations_are_offered_only_to_a_drive_on_the_mains(ws) -> None:
    _, on = dispatch("/api/control/explorations", design(ws), ws)
    off = {k: v for k, v in design(ws).items() if k in ("motor", "conditions", "device")}
    _, without = dispatch("/api/control/explorations", off, ws)
    ids = [e["id"] for e in on["explorations"]]
    assert ids[-2:] == ["link_tie", "link_capacitance"]
    assert not {"link_tie", "link_capacitance"} & {e["id"] for e in without["explorations"]}
    assert {"link.v_min", "link.sag", "link.ripple", "link.v_max"} <= set(on["reads"])


def test_the_tie_and_the_capacitor_as_explorations(ws) -> None:
    status, tie = dispatch("/api/control/sweep", design(ws) | {"exploration": "link_tie"}, ws)
    assert status == 200, tie
    on, off = (v["link"] for v in tie["variants"])
    assert off["sag"] > 2.5 * on["sag"] and "lowest DC-link voltage" in tie["said"][0]
    assert tie["reads"] == ["link.v_min", "link.ripple", "link.thd"]
    status, cap = dispatch("/api/control/sweep", design(ws) | {"exploration": "link_capacitance"}, ws)
    assert status == 200, cap
    full, half, quarter = (v["link"] for v in cap["variants"])
    # Twice the mains on one phase: the ripple goes as one over the capacitance.
    assert half["ripple"] == pytest.approx(2 * full["ripple"], rel=0.05)
    assert quarter["ripple"] == pytest.approx(4 * full["ripple"], rel=0.08)


def test_the_bundle_carries_the_front_end_s_controller_and_its_replay(ws, servo) -> None:
    if compiler() is None:
        pytest.skip("no C compiler on this machine")
    from motionsim.service.control.export_c import bundle

    made = bundle(design(ws) | {"scheme": servo, "scenario": {"kind": "load_step"}}, ws)
    front = made["front_end"]
    assert front["stage"] == "totem_pole" and front["replay"]["passed"] is True
    double = front["replay"]["precisions"]["double"]
    assert double["worst"] <= 1e-12 and double["limits"]["passed"] and double["limits"]["samples"] == 6000
    assert made["replay"]["passed"] is True
    with zipfile.ZipFile(io.BytesIO(made["zip"])) as held:
        names = set(held.namelist())
        readme = held.read(next(n for n in names if n.endswith("README.md"))).decode()
        source = held.read(next(n for n in names if n.endswith("front_end/motionsim_front_end.c"))).decode()
    assert len(front["files"]) == 5 and all(any(n.endswith(f) for n in names) for f in front["files"])
    assert "## The front end's controller" in readme and "p_ff" in readme and "This design uses it." in readme
    assert "#define FE_FEED_FORWARD 1" in source and "Totem-pole PFC on 230 V, 50 Hz, one phase" in source


def test_a_rectifier_has_no_controller_to_export(ws, servo) -> None:
    from motionsim.service.control.export_c import bundle

    asked = design(ws, v_dc=309, topology="rectifier") | {"scheme": servo, "scenario": {"kind": "load_step"}}
    made = bundle(asked, ws, run_replay=False)
    assert made["front_end"] is None and not any("front_end" in name for name in made["files"])


def test_the_stage_recommended_is_read_once_for_the_motor_s_run_and_for_the_link(ws) -> None:
    # No stage named: the totem-pole is recommended, and it gives energy back. A trip above the
    # bridge speed says the same of the supply as the link's run would.
    asked = design(ws) | {"scheme": "foc_torque", "scenario": {"kind": "trip"}}
    status, body = dispatch("/api/control/run", asked, ws)
    assert status == 200, body
    assert body["trip"]["supply"] == "battery"
    named = design(ws, topology="boost") | {"scheme": "foc_torque", "scenario": {"kind": "trip"}}
    assert dispatch("/api/control/run", named, ws)[1]["trip"]["supply"] == "one-way"


def test_a_load_that_swings_within_a_turn_is_left_untied_unless_the_design_says() -> None:
    from motionsim.service.control.linking import tied

    swinging = {"load": {"pulsation": {"torque": 1.5, "per_turn": 1}}}
    assert tied({}) and tied({"load": {"constant_torque": 2.0}})
    assert not tied(swinging)
    assert tied(swinging | {"front_end": {"feed_forward": "on"}})
    assert not tied({"front_end": {"feed_forward": "off"}})


def test_a_point_held_by_weakening_the_field_is_not_a_link_too_low(ws) -> None:
    from motionsim.service import front_end as service

    # The made-up washer spins with its field weakened on its own supply: the stage is fully
    # modulated, and there is no figure of a link it would fall short of.
    washer = started("example", ws)
    design = service._Design({k: washer[k] for k in ("motor", "conditions", "device")}, ws)
    assert design.least(washer["conditions"]["v_dc"]) is None
    # A point with room on its link uses less than the link, and no margin is put on what it uses.
    servo = started("example-sic", ws)
    design = service._Design({k: servo[k] for k in ("motor", "conditions", "device")}, ws)
    least, need = design.least(390.0), design.need(390.0)
    assert least is not None and need is not None and least < need < 390.0
    assert need == pytest.approx(service.ROOM * least)


def test_a_link_under_what_the_motor_uses_is_named_so_and_not_as_a_sag() -> None:
    held = LINK | {"v_ref": 680.0, "v_min": 679.6, "v_max": 680.4, "need": 700.0, "v_rating": 1200.0}
    found = [f for f in link_findings({"link": held}) if f["id"] == "link_sag"]
    assert found and "is under the 700 V the motor uses" in found[0]["head"]
    # A link that fell far says how far it fell.
    fell = [f for f in link_findings({"link": LINK | {"v_min": 250.0}}) if f["id"] == "link_sag"]
    assert "sags 140 V" in fell[0]["head"]
