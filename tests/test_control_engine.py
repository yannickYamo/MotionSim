"""The control lab against the tool's own loss engine: a field-oriented drive held at a
steady point has to end where the engine's settled result is, in currents, loss, junction
temperature and ripple."""

from __future__ import annotations

import copy
import math

import pytest
from test_control_bench import engine_answer, posted, started, workspace

from motionsim.service.workspace import EXAMPLES

PARTS = sorted(EXAMPLES)
# The made-up parts whose default design switches fewer than 30 times in a turn of its output
# (24 and 28.8): their starting scheme samples twice a carrier period, and so does the torque
# scheme held here.
TWICE = {"example-gan", "example-mosfet-80v"}
# Updated twice a period, a pulse is no longer centred in it, and the currents it switches
# are not the centred pulse's the engine takes. Where the ripple is a fifth of the current,
# as on the drone's 35 µH winding, the switching loss ends up to 2% under the engine's.
SWITCHING = {"example-mosfet-80v": 0.02}


def held(key: str, fidelity: str, ws, periods: int = 4, update: str | None = None) -> tuple[dict, dict]:
    """The part's own design point held under torque control, and the engine's answer there."""
    base = started(key, ws)
    scheme = next(s for s in posted("/api/control/presets", base, ws)["schemes"] if s["id"] == "foc_torque")
    scheme = copy.deepcopy(scheme)
    scheme["timing"]["update"] = update or ("double" if key in TWICE else "single")
    request = {**base, "scheme": scheme, "fidelity": fidelity, "scenario": {"kind": "hold", "periods": periods}}
    return posted("/api/control/run", request, ws), engine_answer(key, base, ws)


def test_every_made_up_part_starts_on_a_permanent_magnet_design() -> None:
    ws = workspace()
    assert len(PARTS) == 7
    assert all(started(key, ws)["motor"]["type"] == "pmsm" for key in PARTS)


@pytest.mark.parametrize("fidelity", ["averaged", "switched"])
@pytest.mark.parametrize("key", PARTS)
def test_the_held_design_point_settles_on_the_engines_currents(key: str, fidelity: str) -> None:
    got, engine = held(key, fidelity, workspace())
    size = math.hypot(engine["i_d"], engine["i_q"])
    assert got["ripple"]["i_d"] == pytest.approx(engine["i_d"], abs=0.005 * size)
    assert got["ripple"]["i_q"] == pytest.approx(engine["i_q"], abs=0.005 * size)
    # What the run says it starts from is the engine's own settled state.
    assert got["settled"]["i_q"] == pytest.approx(engine["i_q"], rel=1e-6)
    assert got["settled"]["i_d"] == pytest.approx(engine["i_d"], abs=1e-4 * size)


@pytest.mark.parametrize("key", PARTS)
def test_the_switched_run_loses_and_heats_what_the_engine_says(key: str) -> None:
    got, engine = held(key, "switched", workspace())
    losses = got["losses"]
    assert losses["loss"] == pytest.approx(engine["loss"], rel=0.01)
    t_sink = engine["t_sink"]
    assert losses["tj_peak"] - t_sink == pytest.approx(engine["tj_peak"] - t_sink, rel=0.01)
    assert losses["tj_peak"] == pytest.approx(engine["tj_peak"], rel=0.01)
    assert losses["conduction"] == pytest.approx(engine["conduction"], rel=0.015)
    assert losses["switching"] == pytest.approx(engine["switching"], rel=SWITCHING.get(key, 0.015))
    # Six switches share it, and every leg commutates twice a carrier period.
    assert sum(s["total"] for s in losses["per_switch"]) == pytest.approx(losses["loss"], rel=1e-6)
    f_sw = started(key, workspace())["conditions"]["f_sw"]
    assert got["channels"]["f_switch_mean"] == pytest.approx(f_sw, rel=1e-3)
    assert got["channels"]["tj_peak"] == pytest.approx(losses["tj_peak"], abs=1e-6)
    assert got["thermal"]["swing"] > 0 and got["thermal"]["peak_from_start"] <= losses["tj_peak"] + 1e-6


def test_one_sample_a_period_at_a_low_carrier_ratio_reads_the_current_high() -> None:
    # The gap that single sampling leaves on the part that switches 24 times a turn: the loop
    # holds its samples on the reference while the mean of the current sits below it, and
    # the loss with it. Sampling twice a period closes most of it.
    once, engine = held("example-gan", "switched", workspace(), update="single")
    twice, _ = held("example-gan", "switched", workspace(), update="double")
    assert once["ripple"]["i_q"] < twice["ripple"]["i_q"] < engine["i_q"] * 1.0005
    assert abs(once["losses"]["loss"] / engine["loss"] - 1) < 0.013
    assert abs(twice["losses"]["loss"] / engine["loss"] - 1) < 0.006


@pytest.mark.parametrize(
    ("key", "change"),
    [
        ("example-mosfet", {}),
        ("example-mosfet", {"rpm": 1200, "torque": 4.74}),
        ("example-mosfet", {"rpm": 3000, "torque": 1.2}),
        ("example-sic", {}),
        ("example-sic-module", {"rpm": 2000, "torque": 80}),
    ],
)
def test_the_switched_ripple_is_the_engines_analytic_ripple(key: str, change: dict) -> None:
    ws = workspace()
    base = started(key, ws)
    base["conditions"] = {**base["conditions"], **change}
    engine = engine_answer(key, base, ws)
    request = {**base, "scheme": "foc_torque", "scenario": {"kind": "hold", "periods": 4}}
    got = posted("/api/control/run", request, ws)
    assert got["ripple"]["pp"] == pytest.approx(engine["ripple_pp"], rel=0.05)
    assert got["channels"]["ripple_pp"] == got["ripple"]["pp"]
    # The averaged stage has no ripple to show.
    flat = posted("/api/control/run", {**request, "fidelity": "averaged"}, ws)
    assert flat["ripple"]["pp"] < 0.01 * engine["ripple_pp"]
    assert flat["waveform"] is not None and "s_a" not in flat["waveform"]


def test_the_power_into_the_motor_is_the_shaft_power_and_the_copper_loss() -> None:
    ws = workspace()
    base = started("example-sic", ws)
    got = posted("/api/control/run", {**base, "scheme": "foc_torque", "scenario": {"kind": "hold", "periods": 4}}, ws)
    motor, s = base["motor"], got["settled"]
    ripple = got["ripple"]
    shaft = s["torque"] * s["omega_m"]
    copper = 1.5 * motor["rs"] * (ripple["i_d"] ** 2 + ripple["i_q"] ** 2) + 3 * motor["rs"] * ripple["rms"] ** 2
    assert got["losses"]["p_motor"] == pytest.approx(shaft + copper, rel=0.005)
