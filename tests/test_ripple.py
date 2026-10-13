"""Junction temperature within the output period."""

from __future__ import annotations

import math

import numpy as np
import pytest
from conftest import V_REF, line, linear_device

from motionsim.device import FosterNetwork, Source
from motionsim.engine import OperatingPoint, PeakBasis, solve
from motionsim.engine.thermal import periodic_rise

SRC = Source(kind="synthetic")


def test_single_stage_sinusoidal_power_matches_closed_form() -> None:
    """Level A: p = P0 + P1 cos(wt) into one RC stage."""
    r, tau, period, p0, p1 = 2.0, 0.004, 0.02, 5.0, 3.0
    n = 1024
    t = period * np.arange(n) / n
    w = 2 * math.pi / period
    rise = periodic_rise(FosterNetwork(r=[r], tau=[tau], source=SRC), p0 + p1 * np.cos(w * t), period)
    gain = r / math.sqrt(1 + (w * tau) ** 2)
    expected = p0 * r + p1 * gain * np.cos(w * t - math.atan(w * tau))
    assert rise == pytest.approx(expected, abs=1e-9)


def test_matches_independent_time_stepping() -> None:
    """Level B: half-sine power pulses into a three-stage network, integrated step by step."""
    net = FosterNetwork(r=[0.3, 0.6, 0.4], tau=[0.0008, 0.006, 0.05], source=SRC)
    period, n = 0.02, 4000
    t = period * np.arange(n) / n
    power = np.maximum(0.0, 20.0 * np.sin(2 * math.pi * t / period))
    rise = periodic_rise(net, power, period)

    dt = period / n
    state = np.zeros(3)
    r, tau = np.array(net.r), np.array(net.tau)
    decay = np.exp(-dt / tau)
    for _ in range(40):  # 40 periods: 16 time constants of the slowest stage
        trace = np.empty(n)
        for k in range(n):
            trace[k] = state.sum()
            state = state * decay + r * power[k] * (1 - decay)
    assert rise.max() == pytest.approx(trace.max(), rel=0.005)
    assert rise.mean() == pytest.approx(net.rth * power.mean(), rel=1e-6)


def test_fast_and_slow_limits() -> None:
    period, n = 0.02, 512
    power = np.maximum(0.0, np.sin(2 * math.pi * np.arange(n) / n))
    fast = periodic_rise(FosterNetwork(r=[1.5], tau=[1e-7], source=SRC), power, period)
    slow = periodic_rise(FosterNetwork(r=[1.5], tau=[1e3], source=SRC), power, period)
    assert fast == pytest.approx(1.5 * power, abs=1e-3)
    assert slow == pytest.approx(np.full(n, 1.5 * power.mean()), abs=1e-3)


def device(tau):
    d = linear_device(sw_curves=[line(25.0, 1.0, 0.02)], d_curves=[line(25.0, 1.0, 0.02)], k_on=20e-6, rth_sw=2.0)
    d.switch.thermal.tau = tau
    d.diode.thermal.tau = tau
    return d


OP = OperatingPoint(v_dc=V_REF, i_rms=15.0, modulation_index=0.9, power_factor=0.8, f_sw=8000.0, t_sink=60.0)


def test_missing_transient_data_uses_an_assumed_response_and_reports_a_range() -> None:
    with_data = solve(device([0.005]), OP)
    without = solve(device(None), OP)
    assert with_data.peak_basis is PeakBasis.transient and with_data.tj_peak_range is None
    assert without.peak_basis is PeakBasis.assumed
    assert without.tj_switch == pytest.approx(with_data.tj_switch)  # averages do not depend on it
    low, high = without.tj_peak_range
    assert without.tj_switch < low < without.tj_switch_peak < high
    # never above what a chip with no thermal mass at all would reach
    assert high < without.t_case + 2.0 * 3.5 * (without.tj_switch - without.t_case) / 2.0 + 60
    assert any("response computed for a generic" in a for a in without.assumptions)


def test_computed_coupling_applies_only_to_multi_chip_packages_without_a_given_value() -> None:
    from motionsim.device import Topology
    from motionsim.engine import assumed

    alone = device([0.005])
    assert solve(alone, OP).assumptions == []  # a discrete part has no neighbours

    def module(construction: str, mutual=None):
        d = device([0.005])
        d.package.topology = Topology.six_pack
        d.package.rth_mutual = mutual
        d.package.construction = construction
        return d

    base = solve(module("unknown", mutual=0.0), OP)
    position = base.switch.total + base.diode.total

    unknown = solve(module("unknown"), OP)
    coupling = assumed.module_coupling("unknown", 30.0, "typical")
    assert any("computed for a generic module, construction not given" in a for a in unknown.assumptions)
    assert unknown.tj_switch == pytest.approx(
        base.tj_switch + coupling * (6 * position - unknown.switch.total), rel=0.02
    )
    low, high = unknown.tj_peak_range
    assert low < unknown.tj_switch_peak < high

    moulded, ceramic = solve(module("leadframe"), OP), solve(module("substrate"), OP)
    assert ceramic.tj_switch < moulded.tj_switch  # a ceramic substrate confines the heat
    assert moulded.tj_switch == pytest.approx(unknown.tj_switch)  # unknown takes the cautious kind
    assert any("generic ceramic-substrate module" in a for a in ceramic.assumptions)


def test_discrete_outline_supplies_a_case_to_heatsink_resistance() -> None:
    from motionsim.engine import assumed

    def part(outline=None, interface="grease", r_cs=None):
        d = device([0.005])
        d.package.rth_case_sink = r_cs
        d.package.outline = outline
        d.package.interface = interface
        return d

    bare = solve(part(), OP)
    assert any("sink temperature is used as the case temperature" in x for x in bare.limits)

    r = solve(part("TO-247"), OP)
    r_cs = assumed.interface_resistance("TO-247", 30.0, "typical")
    assert r.t_case == pytest.approx(OP.t_sink + r_cs * (r.switch.total + r.diode.total))
    assert any("computed for a TO-247 on grease" in a for a in r.assumptions)
    assert r.tj_peak_range[0] < r.tj_switch_peak < r.tj_peak_range[1]
    assert r.tj_switch > bare.tj_switch

    assert solve(part("TO-247", "pad"), OP).t_case > r.t_case  # a pad is worse than grease
    assert solve(part("TO-247", r_cs=0.0), OP).assumptions == []  # the user's value is used


def test_ripple_shrinks_as_output_frequency_rises() -> None:
    slow = solve(device([0.005]), OperatingPoint(**{**OP.__dict__, "f_out": 5.0}))
    fast = solve(device([0.005]), OperatingPoint(**{**OP.__dict__, "f_out": 500.0}))
    assert slow.tj_switch_peak - slow.tj_switch > 5 * (fast.tj_switch_peak - fast.tj_switch)
