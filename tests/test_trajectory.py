"""An imported trajectory must reproduce what the engine gives for the same waveforms."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import V_REF, line, linear_device, load_trajectory, zth

from motionsim.device import FosterNetwork, Source, Topology
from motionsim.engine import OperatingPoint, solve
from motionsim.trajectory import BadTrajectory, Trajectory, example, roles, run

NETWORK = FosterNetwork(r=[0.3, 0.7], tau=[0.002, 0.05], source=Source(kind="synthetic"))


def device():
    d = linear_device(
        sw_curves=[line(25.0, 0.9, 0.03)],
        d_curves=[line(25.0, 1.0, 0.025)],
        k_on=20e-6,
        k_off=15e-6,
        k_rr=5e-6,
        topology=Topology.six_pack,
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
    direct = solve(
        device(), OperatingPoint(i_rms=10.0, modulation_index=0.8, power_factor=0.85, f_out=50.0, **conditions)
    )
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
    trajectory = Trajectory(
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
    assert outcome.tj_from_start[-1] - 50.0 == pytest.approx(loss * float(zth(NETWORK, trajectory.duration)), rel=0.01)
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


def test_a_file_from_a_spreadsheet_is_read_and_a_broken_one_is_refused_in_words(tmp_path) -> None:
    good = "time_s,i_a,d_a\n0,1,0.5\n0.001,2,0.5\n0.002,1,0.5\n"
    path = tmp_path / "t.csv"
    # A spreadsheet's export starts with a byte-order mark; it is not part of the first name.
    path.write_bytes(b"\xef\xbb\xbf" + good.encode())
    assert load_trajectory(path).legs == ["a"]
    for text, reason in (
        (good.replace("0.001,2,0.5", "0.001,nan,0.5"), "finite"),
        (good.replace("0.001,2,0.5", "0.001,inf,0.5"), "finite"),
        (good.replace("0.001,2,0.5", "0.001,2"), "as many values"),
        (good.replace("time_s,i_a,d_a", "time_s,i_a,i_a"), "same name"),
    ):
        path.write_text(text, encoding="utf-8")
        with pytest.raises(BadTrajectory, match=reason):
            load_trajectory(path)


# ---------- files that cannot be a trajectory, each refused with its reason ----------

POINT = ["--vdc", "300", "--fsw", "8000", "--tsink", "60"]
IGBT = "example"  # the made-up 600 V IGBT


def _refused(capsys, tmp_path, text: str) -> str:
    """The refusal a trajectory file ends in on the command line: exit status 2, no warning."""
    from motionsim import cli

    assert cli.main(["trajectory", IGBT, str(write(tmp_path, text)), *POINT]) == 2
    return capsys.readouterr().err


def test_a_trace_shorter_than_one_switching_period_is_refused(capsys, tmp_path) -> None:
    """Three rows a femtosecond apart span 3e-15 s; at 8 kHz a switching period is 125 µs, and
    a duty cycle is an average over one."""
    said = _refused(capsys, tmp_path, "time_s,i_a,d_a\n0,10,0.5\n1e-15,10,0.5\n2e-15,10,0.5\n")
    assert "shorter than one switching period" in said and "125 µs" in said and "8 kHz" in said
    # One switching period and a little is a trace: 256 instants over 130 µs.
    from motionsim import cli

    long_enough = "time_s,i_a,d_a\n0,10,0.5\n65e-6,10,0.5\n130e-6,10,0.5\n"
    assert cli.main(["trajectory", IGBT, str(write(tmp_path, long_enough)), *POINT]) in (0, 3, 4)


def test_a_current_no_stage_carries_is_refused(capsys, tmp_path) -> None:
    """A current is held to the 100 000 A a point told outright is held to, either way."""
    row = "time_s,i_a,d_a\n0,10,0.5\n0.01,{},0.5\n0.02,10,0.5\n"
    for current in ("1e300", "-1e300", "100001"):
        said = _refused(capsys, tmp_path, row.format(current))
        assert "i_a" in said and "100000 A" in said
    load_trajectory(write(tmp_path, row.format("-100000")))


def test_a_column_the_trajectory_does_not_know_is_refused_by_name(capsys, tmp_path) -> None:
    """ib and db are not i_b and d_b: read past, the file would be followed as one leg."""
    said = _refused(capsys, tmp_path, "time_s,i_a,d_a,ib,db\n0,10,0.5,10,0.5\n0.01,10,0.5,10,0.5\n0.02,10,0.5,10,0.5\n")
    assert "ib and db" in said and "i_b" in said
    with pytest.raises(BadTrajectory, match="d_c"):  # a duty cycle with no current
        load_trajectory(write(tmp_path, "time_s,i_a,d_a,d_c\n0,1,0.5,0.5\n1,1,0.5,0.5\n"))
    with pytest.raises(BadTrajectory, match="i_e"):  # a fifth leg
        load_trajectory(write(tmp_path, "time_s,i_a,d_a,i_e,d_e\n0,1,0.5,1,0.5\n1,1,0.5,1,0.5\n"))


def test_a_waveform_that_repeats_far_faster_than_the_junction_follows_sits_at_its_mean() -> None:
    """3 W and 5 W, 1e-20 s each, into 2 K/W with a time constant of 10 ms: the stage sees
    their mean, 4 W, and rises 8 K, at every instant alike. The step is so far under the time
    constant that what the stage keeps over it rounds to all of it."""
    from motionsim.engine.thermal import repeating_rise

    rise = repeating_rise([2.0], [0.01], np.array([3.0, 5.0]), 1e-20)
    assert rise == pytest.approx([8.0, 8.0], rel=1e-9)
    # Slow beside the stage it follows each level: 3 W gives 6 K, 5 W gives 10 K.
    assert repeating_rise([2.0], [0.01], np.array([3.0, 5.0]), 10.0) == pytest.approx([6.0, 10.0], rel=1e-9)
