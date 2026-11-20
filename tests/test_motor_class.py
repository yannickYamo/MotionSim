"""The motor a part starts on: the kind an engineer would expect for its rating, current,
technology and package, with figures a real motor of that class has.

The expected kinds are the rules of D163, written out here part by part. The figures are
held to closed forms worked out apart from the code: the back-EMF a motor makes at its rated
speed against the most the inverter gives from the supply, the current limit against the
part's rating, the time constants and speeds of real motors of the class."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from motionsim import design, page
from motionsim.advise import motors_for
from motionsim.service.validate import _motor

ROOT = Path(__file__).parent.parent / "src" / "motionsim"

# name: (V rating, A rating, technology, package), and the kind and pole pairs it starts on.
PARTS = {
    "igbt-1200-100": ((1200, 100, "Si IGBT", "six_pack"), "induction", 2),
    "sic-1200-20": ((1200, 20, "SiC MOSFET", "discrete"), "pmsm", 4),
    "igbt-650-40": ((650, 40, "Si IGBT", "discrete"), "pmsm", 4),
    "gan-650-15": ((650, 15, "GaN HEMT", "discrete"), "pmsm", 4),
    "igbt-650-400": ((650, 400, "Si IGBT", "six_pack"), "pmsm", 4),
    "si-100-2": ((100, 2, "Si MOSFET", "discrete"), "bldc", 4),
    "si-100-100": ((100, 100, "Si MOSFET", "discrete"), "pmsm", 7),
    "si-40-bridge": ((40, 20, "Si MOSFET", "h_bridge"), "dc", None),
}


def _part(folder: Path, key: str, v: float, i: float, technology: str, topology: str) -> None:
    igbt = "IGBT" in technology
    text = yaml.safe_load((ROOT / ("example_device.yaml" if igbt else "example_mosfet.yaml")).read_text())
    text["technology"] = technology
    text["ratings"] = {**text["ratings"], "v_max": v, "i_nominal": i}
    text["package"] = {**text["package"], "topology": topology}
    if topology != "discrete":
        text["package"].pop("outline", None)
    (folder / f"{key}.device.yaml").write_text(yaml.safe_dump(text))


@pytest.fixture(scope="module")
def suggested(tmp_path_factory) -> dict:
    folder = tmp_path_factory.mktemp("parts")
    for key, ((v, i, tech, topology), _, _) in PARTS.items():
        _part(folder, key, v, i, tech, topology)
    ws = page.Workspace(folder)
    return {key: page.suggest({"device": key}, ws) for key in PARTS} | {"_ws": ws}


@pytest.mark.parametrize("key", list(PARTS))
def test_each_part_starts_on_the_kind_its_class_of_drive_runs(suggested, key) -> None:
    _, kind, pairs = PARTS[key]
    motors = suggested[key]["motors"]
    assert [k for k, m in motors.items() if m["fit"] == "recommended"] == [kind]
    if pairs is not None:
        assert motors[kind]["values"]["pole_pairs"] == pairs
    # Reluctance is never the start, and what was unusual stays unusual.
    assert motors["synrm"]["fit"] != "recommended"


def test_the_starting_rules_follow_the_current_and_the_supply() -> None:
    def start(v, i, tech="Si IGBT", positions=6):
        return next(k for k, f in motors_for(v, positions, i, tech)[1].items() if f.fit == "recommended")

    assert start(1200, 100) == "induction" and start(1200, 50) == "induction"
    assert start(1200, 49) == "pmsm" and start(1700, 300) == "induction"
    assert start(650, 5) == start(650, 40) == start(650, 400) == "pmsm"
    assert start(100, 9, "Si MOSFET", 1) == "bldc" and start(100, 10, "Si MOSFET", 1) == "pmsm"
    assert start(40, 20, "Si MOSFET", 4) == "dc"
    assert start(650, 20, "Si MOSFET", 4) == "pmsm"  # a two-leg package on the mains: still a three-phase motor
    # The judgements of what is unusual are as they were.
    _, high = motors_for(1200, 6, 100, "Si IGBT")
    assert high["dc"].fit == "unusual" and high["stepper"].fit == "unusual"
    _, low = motors_for(100, 1, 2, "Si MOSFET")
    assert low["induction"].fit == "unusual" and low["synrm"].fit == "unusual"


def test_the_line_says_why_in_the_part_s_own_terms(suggested) -> None:
    why = {k: next(m["why"] for m in suggested[k]["motors"].values() if m["fit"] == "recommended") for k in PARTS}
    assert why["igbt-1200-100"] == "1200 V, 100 A IGBT module: industrial drives of this size run induction motors"
    assert (
        why["si-100-2"] == "100 V, 2 A silicon MOSFET: fans, pumps and small tools of this size run brushless DC motors"
    )
    assert why["gan-650-15"].startswith("650 V, 15 A GaN transistor: servo")
    assert why["si-40-bridge"].startswith("40 V, 20 A silicon MOSFET H-bridge: ")


def _back_emf_share(kind: str, values: dict, rpm: float, v_dc: float) -> float:
    """The back-EMF at rpm over the most the inverter gives from v_dc, from the catalogue
    figures as a datasheet states them."""
    if kind == "pmsm":  # kv: rpm per volt of line-to-line peak; space-vector gives v_dc line to line
        return rpm / values["kv"] / v_dc
    if kind == "bldc":  # six-step: kt · ω across two phases, against v_dc
        return values["kt"] * rpm * math.pi / 30 / v_dc
    # Induction: air-gap EMF at the frequency the rotor turns at, ω · Lm · Im, phase peak, against v_dc / √3.
    w = 2 * math.pi * values["pole_pairs"] * rpm / 60
    return w * values["lm"] * values["i_magnetising"] / (v_dc / math.sqrt(3))


def _time_constant(kind: str, values: dict) -> float:
    if kind == "induction":  # the rotor's, which sets how the flux follows
        return (values["lm"] + values["llr"]) / values["rr"]
    return values["l"] / values.get("rs", values.get("r"))


# Where real motors of each kind sit: electrical time constant, s, and rated speed, rpm.
REAL = {
    "pmsm": ((3e-4, 0.05), (1000, 8000)),
    "bldc": ((2e-4, 0.01), (1000, 10000)),
    "induction": ((0.05, 1.0), (1350, 1500)),
}


@pytest.mark.parametrize("key", [k for k, p in PARTS.items() if p[1] != "dc"])
def test_the_starting_motor_is_one_a_real_drive_of_its_class_has(suggested, key) -> None:
    (_, i_rated, _, _), kind, _ = PARTS[key]
    m = suggested[key]["motors"][kind]
    values, start = m["values"], m["start"]
    share = _back_emf_share(kind, values, start["rpm"], start["v_dc"])
    assert 0.7 <= share <= 0.86, share  # 75 to 85% by the rule, with the rounding and the slip around it
    peak = values["i_max"] * (1 if kind == "bldc" else math.sqrt(2))
    assert peak <= i_rated and peak >= 0.8 * i_rated  # just inside the part's rating
    assert isinstance(values["pole_pairs"], int) and values["pole_pairs"] >= 1
    (tau_low, tau_high), (rpm_low, rpm_high) = REAL[kind]
    assert tau_low <= _time_constant(kind, values) <= tau_high
    assert rpm_low <= start["rpm"] <= rpm_high
    # The rated point is reached without weakening the field, on less than the limit.
    motor = _motor({"type": kind, **values})
    stage = motor.stage(start["rpm"], start["torque"], start["v_dc"], motor.default_pwm)
    assert 0 < stage.i_peak < peak
    assert dict((s[0], s[1]) for s in stage.summary).get("field weakening", 0.0) == 0.0


def test_the_switching_frequency_starts_where_the_technology_is_used(suggested) -> None:
    f = {
        k: next(m["start"]["f_sw"] for m in suggested[k]["motors"].values() if m["fit"] == "recommended") for k in PARTS
    }
    assert f["igbt-1200-100"] == 8000 and f["igbt-650-40"] == 16000
    assert f["gan-650-15"] == 40000 and f["sic-1200-20"] == 20000 and f["si-100-100"] == 20000


def test_a_design_file_starts_on_the_same_motor_as_the_page(suggested) -> None:
    ws = suggested["_ws"]
    for key, (_, kind, _) in PARTS.items():
        setup = design.starting_setup(key, ws)
        assert setup["motor"] == {"type": kind, **suggested[key]["motors"][kind]["values"]}
        assert setup["conditions"]["f_sw"] == suggested[key]["motors"][kind]["start"]["f_sw"]
