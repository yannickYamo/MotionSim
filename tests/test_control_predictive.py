"""Predictive control with a finite control set: that it tracks, what the weight on a
commutation buys and costs, and its switching loss beside the modulated drive's."""

from __future__ import annotations

import copy

import pytest
from test_control_bench import block_of, posted, started, workspace

KEY = "example-mosfet"


def held(ws, base: dict, scheme, periods: int = 8) -> dict:
    return posted("/api/control/run", {**base, "scheme": scheme, "scenario": {"kind": "hold", "periods": periods}}, ws)


def predictive(ws, base: dict, weight: float = 0.0, rate: float | None = None) -> dict:
    scheme = next(s for s in posted("/api/control/presets", base, ws)["schemes"] if s["id"] == "mpc_torque")
    scheme = copy.deepcopy(scheme)
    block_of(scheme, "predictive")["params"]["weight"] = weight
    if rate is not None:
        scheme["timing"]["f_control"] = rate
    return scheme


def test_it_tracks_the_currents_asked_for_with_no_modulator() -> None:
    ws = workspace()
    base = started(KEY, ws)
    got = held(ws, base, predictive(ws, base))
    asked = got["settled"]
    assert got["ripple"]["i_q"] == pytest.approx(asked["i_q"], rel=0.01)
    assert got["ripple"]["i_d"] == pytest.approx(asked["i_d"], abs=0.01 * asked["i_q"])
    assert got["ripple"]["torque_mean"] == pytest.approx(asked["torque"], rel=0.01)
    assert got["scheme"]["actuation"]["kind"] == "states"
    # A torque step is followed too, faster than the regulator it replaces.
    step = posted("/api/control/run", {**base, "scheme": predictive(ws, base), "scenario": {"kind": "torque_step"}}, ws)
    modulated = posted("/api/control/run", {**base, "scheme": "foc_torque", "scenario": {"kind": "torque_step"}}, ws)
    assert step["step"]["rise_time"] < modulated["step"]["rise_time"]
    assert abs(step["step"]["steady_state_error"]) < 0.02 * step["step"]["to"]


def test_a_heavier_weight_on_commutations_switches_less_and_ripples_more() -> None:
    ws = workspace()
    base = started(KEY, ws)
    runs = [held(ws, base, predictive(ws, base, weight)) for weight in (0.0, 0.5, 1.0, 2.0, 4.0)]
    rates = [r["channels"]["commutations_per_s"] for r in runs]
    ripples = [r["channels"]["ripple_rms"] for r in runs]
    switching = [r["losses"]["switching"] for r in runs]
    assert all(a > b for a, b in zip(rates, rates[1:], strict=False)), rates
    assert all(a < b for a, b in zip(ripples, ripples[1:], strict=False)), ripples
    assert rates[-1] < 0.5 * rates[0] and ripples[-1] > 2.0 * ripples[0]
    assert switching[-1] < 0.5 * switching[0]
    # Commutations per second and the mean switching frequency of a switch are one count.
    assert runs[0]["channels"]["f_switch_mean"] == pytest.approx(rates[0] / 6.0)


def test_at_the_same_mean_switching_frequency_it_switches_a_smaller_current_and_loses_less() -> None:
    ws = workspace()
    base = started(KEY, ws)
    modulated = held(ws, base, "foc_torque")
    # Sampled at 7.5 times the carrier frequency, with no weight, it commutates as often.
    free = held(ws, base, predictive(ws, base, 0.0, 7.5 * base["conditions"]["f_sw"]))
    assert free["channels"]["f_switch_mean"] == pytest.approx(modulated["channels"]["f_switch_mean"], rel=0.05)
    # It leaves the leg that carries the most current standing where the modulator switches
    # every leg every period: the current it commutates is smaller, and so is the loss.
    assert free["channels"]["i_at_commutation"] < 0.9 * modulated["channels"]["i_at_commutation"]
    assert free["losses"]["switching"] < 0.9 * modulated["losses"]["switching"]
    assert free["losses"]["switching"] > 0.6 * modulated["losses"]["switching"]
    # Its conduction loss is that of the same current.
    assert free["losses"]["conduction"] == pytest.approx(modulated["losses"]["conduction"], rel=0.05)


def test_the_analysis_says_why_it_has_no_bode_plot() -> None:
    ws = workspace()
    base = started(KEY, ws)
    found = posted("/api/control/loops", {**base, "scheme": "mpc_torque"}, ws)
    assert found["current_q"] is None and found["speed"] is None
    assert "no linear transfer function" in found["missing"][0]
