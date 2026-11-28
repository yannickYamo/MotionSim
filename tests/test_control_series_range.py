"""A run's wires thinned for the page (control.report.series): where samples are left out, what
they reached is still said. Each bucket of left-out samples hands over its lowest and highest
value for a wire that swings beyond what the kept samples show, so a fast current is never drawn
smaller, or beating, than it ran. Expected values are taken from the samples here."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from motionsim.control import report


@dataclass
class Run:
    time: np.ndarray
    values: np.ndarray
    wires: tuple[str, ...]


def run(n: int) -> Run:
    k = np.arange(n)
    fast = 40.0 * np.sin(2 * math.pi * k / 7.3)  # a phase current: 7.3 samples a period
    ramp = k / n * 3000.0  # a speed
    return Run(k * 5e-5, np.column_stack([fast, ramp]), ("plant.i_a", "plant.w_m"))


def test_every_sample_kept_is_said_as_it_is_and_nothing_more() -> None:
    r = run(1700)
    out = report.series(r, 5000)
    assert out["wires"]["plant.i_a"] == r.values[:, 0].tolist()
    assert "lo" not in out and "hi" not in out


def test_a_thinned_fast_wire_says_each_buckets_lowest_and_highest() -> None:
    r = run(10_000)
    out = report.series(r, 500)
    t = out["t"]
    step = math.ceil(10_000 / 500)
    assert len(t) == len(out["lo"]["plant.i_a"]) == len(out["hi"]["plant.i_a"])
    for j in range(len(t)):
        # Bucket j runs from its kept sample up to the next kept one; the last sample is kept
        # on its own.
        a = min(j * step, 9_999)
        b = min((j + 1) * step, 9_999) if j < len(t) - 1 else 10_000
        bucket = r.values[a:b, 0]
        assert out["lo"]["plant.i_a"][j] == float(bucket.min())
        assert out["hi"]["plant.i_a"][j] == float(bucket.max())
    assert max(out["hi"]["plant.i_a"]) > 39.9 and min(out["lo"]["plant.i_a"]) < -39.9


def test_a_wire_the_kept_samples_already_draw_says_no_range() -> None:
    out = report.series(run(10_000), 500)
    assert "plant.w_m" not in out["lo"] and "plant.w_m" not in out["hi"]


def test_only_the_wires_asked_for_say_their_range() -> None:
    out = report.series(run(10_000), 500, only=("plant.w",))
    assert set(out["wires"]) == {"plant.w_m"}
    assert "lo" not in out
