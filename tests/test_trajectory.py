"""An imported trajectory must reproduce what the engine gives for the same waveforms."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import V_REF, line, linear_device

from motionsim.device import FosterNetwork, Source, Topology
from motionsim.engine import OperatingPoint, solve
from motionsim.engine.thermal import zth
from motionsim.trajectory import BadTrajectory, example, load_trajectory, roles, run

NETWORK = FosterNetwork(r=[0.3, 0.7], tau=[0.002, 0.05], source=Source(kind="synthetic"))


def device():
    d = linear_device(
        sw_curves=[line(25.0, 0.9, 0.03)], d_curves=[line(25.0, 1.0, 0.025)],
        k_on=20e-6, k_off=15e-6, k_rr=5e-6, topology=Topology.six_pack,
    )
    d.switch.thermal = NETWORK
    d.diode.thermal = NETWORK
    return d


def write(tmp_path, text: str):
    path = tmp_path / "trajectory.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_sine_drive_written_as_a_trajectory_matches_the_engine(tmp_path) -> None:
    conditions = dict(v_dc=V_REF, f_sw=8000.0, t_sink=60.0)
    trajectory = load_trajectory(write(tmp_path, example(f_out=50.0, i_rms=10.0, m=0.8, pf=0.85, n=2000)))
    outcome = run(device(), trajectory, OperatingPoint(i_rms=0, modulation_index=0, power_factor=1, **conditions))
    direct = solve(device(), OperatingPoint(i_rms=10.0, modulation_index=0.8, power_factor=0.85, f_out=50.0, **conditions))
    r = outcome.result
    assert len(r.roles) == 6
    assert r.p_inverter == pytest.approx(direct.p_inverter, rel=0.005)
    assert r.p_out == pytest.approx(direct.p_out, rel=0.005)
    assert r.tj_switch_peak == pytest.approx(direct.tj_switch_peak, abs=0.3)
    assert r.tj_diode_peak == pytest.approx(direct.tj_diode_peak, abs=0.3)
    # Every position does the same work, a third of a cycle apart.
    losses = [role.switch.total + role.diode.total for role in r.roles]
    assert max(losses) == pytest.approx(min(losses), rel=0.01)


def test_each_position_carries_what_its_current_direction_says() -> None:
    trajectory = load_trajectory.__globals__["Trajectory"](
        time=np.array([0.0, 1.0]),
        current={"a": np.array([10.0, -10.0])},
        duty={"a": np.array([0.3, 0.3])},
    )
    high, low = roles(trajectory)
    assert high.d_switch.tolist() == [0.3, 0.0] and high.d_reverse.tolist() == [0.0, 0.3]
    assert low.d_reverse.tolist() == [0.7, 0.0] and low.d_switch.tolist() == [0.0, 0.7]
    assert high.switch_events.tolist() == [1.0, 0.0] and low.switch_events.tolist() == [0.0, 1.0]


def test_from_a_cold_start_a_constant_load_follows_the_transient_impedance(tmp_path) -> None:
    """One leg held at a steady current: the high-side switch heats as power times Zth(t)."""
    rows = ["time_s,i_a,d_a"] + [f"{t:.6g},12,0.6" for t in np.linspace(0, 0.02, 400)]
    trajectory = load_trajectory(write(tmp_path, "\n".join(rows) + "\n"))
    d = device()
    d.package.topology = Topology.discrete
    op = OperatingPoint(v_dc=V_REF, i_rms=0, modulation_index=0, power_factor=1, f_sw=8000.0, t_sink=50.0)
    outcome = run(d, trajectory, op)
    hottest = max(outcome.result.roles, key=lambda r: max(r.switch.total, r.diode.total))
    loss = max(hottest.switch.total, hottest.diode.total)
    assert outcome.tj_from_start[-1] - 50.0 == pytest.approx(
        loss * float(zth(NETWORK, trajectory.duration)), rel=0.01
    )
    assert outcome.peak_from_start < outcome.result.tj_switch_peak  # not yet settled


def test_bad_files_are_refused_with_the_reason(tmp_path) -> None:
    for text, reason in (
        ("time_s,i_a\n0,1\n1,1\n", "no duty cycle"),
        ("time_s,i_a,d_a\n0,1,1.4\n1,1,0.5\n", "between 0 and 1"),
        ("time_s,i_a,d_a\n1,1,0.5\n0,1,0.5\n", "time must increase"),
        ("t,i_a,d_a\n0,1,0.5\n1,1,0.5\n", "time_s"),
    ):
        with pytest.raises(BadTrajectory, match=reason):
            load_trajectory(write(tmp_path, text))
