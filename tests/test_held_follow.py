"""What is followed through time, held by figures the test works out for itself: the rise a
package's other chips give a chip, the range of a trajectory, the rotor's place in a slow
turn, and the d-axis current of a motor with little magnet."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from conftest import V_REF, line, linear_device

from motionsim import trajectory as followed
from motionsim.device import FosterNetwork, Source, Topology, load_device
from motionsim.engine import OperatingPoint
from motionsim.engine.solver import package_waves
from motionsim.load import Load, Profile
from motionsim.motor import Pmsm
from motionsim.motor.pmsm import operating_state
from motionsim.transient import _Follower, follow

ROOT = Path(__file__).parent.parent
IGBT = load_device(ROOT / "examples/synthetic_igbt_600v_30a.yaml")
OP = OperatingPoint(v_dc=300.0, i_rms=0.0, modulation_index=0.8, power_factor=0.85, f_sw=8000.0, t_sink=80.0)


def _example_trajectory(tmp_path, f_out: float = 5.0):
    path = tmp_path / "trajectory.csv"
    path.write_text(followed.example(f_out=f_out, i_rms=15.0), encoding="utf-8")
    return followed.parse_trajectory(path.read_text(encoding="utf-8"))


def test_a_chip_sits_on_its_package_loss_through_the_layer_and_on_the_other_chip_through_the_package(
    tmp_path,
) -> None:
    """A discrete package holding a switch and a diode, 0.3 K/W from case to heatsink and 0.5 K/W
    between the chips. At each instant the switch sits 0.3·(p_switch + p_diode) above the
    heatsink through the layer, and 0.5·p_diode more from its neighbour; the diode the same
    with the roles turned round. Its own loss does not heat it through the package twice."""
    package = IGBT.package.model_copy(update={"topology": Topology.discrete, "rth_case_sink": 0.3, "rth_mutual": 0.5})
    device = IGBT.model_copy(update={"package": package})
    stage = followed.roles(_example_trajectory(tmp_path))
    result = followed.solve_roles(device, stage, OP, period=0.2, p_out=0.0)
    waves = package_waves(device, stage, result, OP)
    for role, wave in zip(result.roles, waves, strict=True):
        p_sw, p_d = role.p_switch, role.p_diode
        assert p_sw.max() > 0 and p_d.max() > 0  # both chips carry loss somewhere in the period
        assert wave["switch"] == pytest.approx(0.3 * (p_sw + p_d) + 0.5 * p_d, rel=1e-12, abs=1e-12)
        assert wave["diode"] == pytest.approx(0.3 * (p_sw + p_d) + 0.5 * p_sw, rel=1e-12, abs=1e-12)


def _settled_lag(r: float, tau: float, power: np.ndarray, period: float) -> np.ndarray:
    """The rise one Foster stage settles to under a power waveform that repeats, each sample
    held for its share of the period, worked out in time: x[k+1] = a·x[k] + (1 - a)·r·p[k]
    with a = exp(-dt/tau), started where the end of a period brings it back to."""
    a = float(np.exp(-period / power.size / tau))
    steps = (1 - a) * r * power
    start = sum(a ** (power.size - 1 - k) * steps[k] for k in range(power.size)) / (1 - a**power.size)
    out, x = np.empty_like(power), start
    for k in range(power.size):
        out[k] = x
        x = a * x + steps[k]
    return out


def test_a_discrete_switch_is_heated_by_its_neighbour_and_not_again_by_itself() -> None:
    """A switch and its diode in one package, 0.3 K/W from case to heatsink and 0.5 K/W from
    one chip to the other. Held still, the switch's hottest instant is one where the diode
    beside it carries nothing: it stands at the heatsink plus (0.3 + 0.8)·p, p its own loss
    there, written out from the device's straight lines. Turning at 50 Hz, it is the sum of
    three settled responses worked out here in time: the layer under the case to both
    chips' loss, the package to the diode's alone, and its own 0.8 K/W, 10 ms stage."""
    from motionsim.engine import solve
    from motionsim.engine.solver import shared_time

    v0, slope, k = 0.9, 0.03, 20e-6
    device = linear_device(
        sw_curves=[line(25.0, v0, slope)],
        d_curves=[line(25.0, 1.0, 0.025)],
        k_on=k,
        k_off=k,
        k_rr=5e-6,
        rth_sw=0.8,
        rth_d=1.2,
        rth_cs=0.3,
        topology=Topology.discrete,
    )
    device.package.rth_mutual = 0.5
    given = dict(v_dc=V_REF, i_rms=15.0, modulation_index=0.6, power_factor=1.0, f_sw=10e3, t_sink=25.0)
    # At the crest the switch carries i = 15·√2 A for (1 + m)/2 of each period, and switches it.
    i_pk = 15.0 * np.sqrt(2)
    p = (1 + 0.6) / 2 * (v0 + slope * i_pk) * i_pk + 10e3 * 2 * k * i_pk
    held = solve(device, OperatingPoint(**given, f_out=0.0))
    assert held.tj_switch_peak == pytest.approx(25.0 + (0.3 + 0.8) * p, rel=1e-5)

    op = OperatingPoint(**given, f_out=50.0)
    turning = solve(device, op)
    (role,) = turning.roles
    p_sw, p_d = role.p_switch, role.p_diode
    tab = shared_time(device, op)
    junction = (
        25.0
        + _settled_lag(0.3, tab, p_sw + p_d, 0.02)
        + _settled_lag(0.5, tab, p_d, 0.02)
        + _settled_lag(0.8, 0.01, p_sw, 0.02)
    )
    assert turning.tj_switch_peak == pytest.approx(float(junction.max()), abs=1e-3)


def test_a_trajectory_moves_its_range_with_its_hottest_junction(tmp_path, monkeypatch) -> None:
    """Following a trajectory through time moves the hottest junction from where the settled
    solution put it. The range across the thermal assumptions is drawn about that junction,
    so it moves with it, whole: its width is what it was, and so is how far its top stands
    above the hottest junction, which is the switch here, some 19 K above the diode."""
    settled = {}
    solve_roles = followed.solve_roles

    def kept(*args, **kwargs):
        settled["result"] = solve_roles(*args, **kwargs)
        return settled["result"]

    monkeypatch.setattr(followed, "solve_roles", kept)
    out = followed.run(IGBT, _example_trajectory(tmp_path), OP).result
    before = settled["result"]
    assert before.tj_switch_peak - before.tj_diode_peak > 10.0
    low, high = before.tj_peak_range
    new_low, new_high = out.tj_peak_range
    assert out.tj_switch_peak != pytest.approx(before.tj_switch_peak, abs=1e-6)  # it did move
    assert new_high - new_low == pytest.approx(high - low, abs=1e-9)
    top = max(before.tj_switch_peak, before.tj_diode_peak)
    assert new_high - max(out.tj_switch_peak, out.tj_diode_peak) == pytest.approx(high - top, abs=1e-9)


def test_in_a_slow_turn_the_rotor_moves_forward_by_the_turns_it_makes(monkeypatch) -> None:
    """At 1.5 rpm a motor of four pole pairs makes 1.5/60·4 = 0.1 electrical turns a second.
    Thirty seconds in 120 instants are 0.25 s each, so the rotor's place within the period moves
    on by 0.025 of a turn from one instant to the next, forward."""
    places = []
    slow = _Follower._slow

    def watched(self, out, at, sink_then, t_sink, dt, turns, position):
        places.append((turns, position))
        return slow(self, out, at, sink_then, t_sink, dt, turns, position)

    monkeypatch.setattr(_Follower, "_slow", watched)
    network = FosterNetwork(r=[0.3, 0.7], tau=[0.002, 0.05], source=Source(kind="synthetic"))
    device = linear_device(
        sw_curves=[line(25.0, 0.9, 0.03)], d_curves=[line(25.0, 1.0, 0.025)], k_on=20e-6, k_off=15e-6, k_rr=5e-6
    )
    device.switch.thermal = network
    device.diode.thermal = network
    base = OperatingPoint(v_dc=V_REF, i_rms=0.0, modulation_index=0.0, power_factor=1.0, f_sw=8000.0, t_sink=60.0)
    motor = Pmsm(pole_pairs=4, flux_linkage=0.1, l=0.008, rs=1.0)
    profile = Profile(segments=[{"duration": 30.0, "speed_start": 1.5, "speed_end": 1.5}])
    follow(device, motor, Load(constant_torque=4.0), profile, base, per_segment=120)
    assert places and all(turns == pytest.approx(0.025, rel=1e-9) for turns, _ in places)
    # Each chip of each position is followed at the same place; one place per instant is kept.
    # The first pass is the one looked at: each later one starts at another place.
    per_instant = [p for k, (_, p) in enumerate(places) if k == 0 or p != places[k - 1][1]][:120]
    steps = np.diff(per_instant) % 1.0
    assert len(steps) == 119
    assert steps == pytest.approx(np.full(len(steps), 0.025), abs=1e-9)


def test_a_motor_with_little_magnet_never_draws_more_d_axis_current_than_its_magnet_holds() -> None:
    """With 0.01 Wb of magnet on a 1 mH d axis, a d-axis current of -10 A cancels the magnet's
    flux; the search for least current keeps above -0.999 of that, -9.99 A. Torque here is
    mostly reluctance torque, whose least-current point lies far beyond: so the answer is the
    best within the bound, found again by brute force over the bound written in the test,
    with the q-axis current from T = 1.5·p·(ψ + (Ld − Lq)·id)·iq."""
    psi, ld, lq, p, torque = 0.01, 1e-3, 5e-3, 4, 10.0
    motor = Pmsm(pole_pairs=p, flux_linkage=psi, ld=ld, lq=lq, rs=0.1, magnets="interior")
    state = operating_state(motor, 100.0, torque, 1e4)
    floor = -0.999 * psi / ld
    assert floor == pytest.approx(-9.99)
    ids = np.linspace(floor, 0.0, 200_001)
    iqs = torque / (1.5 * p * (psi + (ld - lq) * ids))
    best = int(np.argmin(ids**2 + iqs**2))
    assert state.i_d >= floor - 1e-9
    assert state.i_d == pytest.approx(ids[best], abs=1e-3)
    assert np.hypot(state.i_d, state.i_q) == pytest.approx(np.hypot(ids[best], iqs[best]), rel=1e-6)
