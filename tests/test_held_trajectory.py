"""An imported trajectory: how its file is read, and what is reported from it."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import load_trajectory

from motionsim.trajectory import BadTrajectory, Outcome, example


def write(tmp_path, text: str):
    path = tmp_path / "trajectory.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_log_that_does_not_start_at_zero_is_moved_to_zero_and_keeps_its_shape(tmp_path) -> None:
    """Eleven rows from 0.5 s to 1.5 s, the current rising in a straight line from 0 to 10 A.
    On the even grid it is still that line, over one second counted from zero."""
    rows = "\n".join(f"{0.5 + 0.1 * k:.1f},{k:.1f},0.5" for k in range(11))
    t = load_trajectory(write(tmp_path, "time_s,i_a,d_a\n" + rows + "\n"))
    n = t.time.size
    assert n == 256  # a short log is put on at least this many instants
    assert t.time[0] == 0.0 and t.time[-1] == pytest.approx(1.0)
    assert np.diff(t.time) == pytest.approx(np.full(n - 1, 1.0 / (n - 1)))
    assert t.current["a"] == pytest.approx(10.0 * t.time)
    assert t.current["a"][-1] == pytest.approx(10.0)
    # Each instant stands for one step of the grid, the last one included.
    assert t.duration == pytest.approx(1.0 * n / (n - 1))


def test_a_file_with_no_current_column_is_refused(tmp_path) -> None:
    with pytest.raises(BadTrajectory, match="no current column"):
        load_trajectory(write(tmp_path, "time_s,speed\n0,1\n0.1,2\n0.2,3\n"))


def test_the_peak_from_the_start_is_the_highest_instant() -> None:
    tj = np.array([60.0, 82.0, 75.0, 61.0])
    assert Outcome(None, np.arange(4.0), tj).peak_from_start == 82.0


def test_the_example_is_a_balanced_three_phase_drive(tmp_path) -> None:
    """Three legs a third of a period apart: the currents add to nothing at every instant,
    and each leg's current is the one before it, a third of a period later."""
    n = 240
    t = load_trajectory(write(tmp_path, example(f_out=50.0, i_rms=10.0, m=0.8, pf=0.85, n=n)))
    a, b, c = (t.current[leg] for leg in "abc")
    assert t.legs == ["a", "b", "c"]
    assert np.abs(a + b + c).max() < 0.01
    assert np.sqrt(np.mean(a**2)) == pytest.approx(10.0, rel=2e-3)
    assert np.sqrt(np.mean(c**2)) == pytest.approx(10.0, rel=2e-3)
    # In the text itself, on its own grid: b is a moved on by a third of a period, c by two.
    rows = np.array([[float(v) for v in ln.split(",")] for ln in example(n=n).splitlines() if ln[0].isdigit()])
    assert rows[:, 3] == pytest.approx(np.roll(rows[:, 1], n // 3), abs=2e-3)
    assert rows[:, 5] == pytest.approx(np.roll(rows[:, 1], 2 * n // 3), abs=2e-3)
    assert rows[:, 6] == pytest.approx(np.roll(rows[:, 2], 2 * n // 3), abs=2e-4)
