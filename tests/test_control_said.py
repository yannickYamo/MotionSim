"""The sentences a sweep says of its figures: a change is said the way that kind of figure
changes. A loss by a percentage, a temperature by kelvins, a figure that is itself a percentage
by points, a figure with a sign by its size, and a figure that starts at nothing by what it
came to."""

from __future__ import annotations

import re

import pytest
from test_control_bench import posted, started, workspace

from motionsim.service.control.sweep import KINDS, READS, Read, _changed, _sentences

STABLE = {"linear_stable": True, "said": ""}


def variant(label: str, **figures) -> dict:
    """A run of a sweep as the sentences read it, with the figures given by their keys."""
    found: dict = {"label": label, "refused": None, "checks": [], "stability": STABLE}
    for key, value in figures.items():
        held = found
        *parts, last = key.split("__")
        for part in parts:
            held = held.setdefault(part, {})
        held[last] = value
    return found


def said(key: str, start: float, other: float) -> str:
    name = key.replace(".", "__")
    (line,) = _sentences([variant("20 kHz", **{name: start}), variant("40 kHz", **{name: other})], 0, [key], {})
    return line


def test_a_loss_is_said_as_a_percentage_of_the_baseline() -> None:
    assert said("losses.loss", 21.6, 24.8) == "inverter loss: 21.6 W at 20 kHz, 24.8 W at 40 kHz (14.8 % higher)"
    assert said("losses.switching", 8.0, 2.0) == "switching loss: 8 W at 20 kHz, 2 W at 40 kHz (75 % lower)"
    # The factor to the unit said is applied to both: 12 500 Hz is 12.5 kHz.
    assert said("channels.f_switch_mean", 10000.0, 12500.0) == (
        "mean switching frequency: 10 kHz at 20 kHz, 12.5 kHz at 40 kHz (25 % higher)"
    )


def test_a_temperature_is_said_as_a_difference_in_kelvins() -> None:
    # 71.2 °C to 83.5 °C is 12.3 K: 17 % of 71.2 means nothing, the zero of the scale being arbitrary.
    assert said("losses.tj_peak", 71.2, 83.5) == (
        "peak junction temperature, settled: 71.2 °C at 20 kHz, 83.5 °C at 40 kHz (12.3 K higher)"
    )
    assert said("losses.tj_peak_from_start", 140.0, 96.0) == (
        "peak junction temperature from a cold start: 140 °C at 20 kHz, 96 °C at 40 kHz (44 K lower)"
    )
    assert (
        said("losses.tj_swing", 4.0, 9.5) == "junction temperature swing: 4 K at 20 kHz, 9.5 K at 40 kHz (5.5 K higher)"
    )


def test_a_figure_that_is_a_percentage_is_said_in_points() -> None:
    # An overshoot of 0.042 of the step is 4.2 %; to 9.7 % is 5.5 points, not "131 % higher".
    assert said("step.overshoot", 0.042, 0.097) == "overshoot: 4.2 % at 20 kHz, 9.7 % at 40 kHz (5.5 points higher)"
    assert said("channels.thd", 0.08, 0.03) == "current distortion: 8 % at 20 kHz, 3 % at 40 kHz (5 points lower)"


def test_an_angle_is_said_as_a_difference_in_degrees() -> None:
    assert said("sensing.angle_error_mean", -0.4, 3.1) == (
        "mean angle error: −0.4° at 20 kHz, 3.1° at 40 kHz (3.5° higher)"
    )


def test_a_figure_with_a_sign_is_compared_by_its_size() -> None:
    # −4.74 N·m to −4.5 N·m: 0.24 of 4.74 is 5.06 % less torque, though the number is "higher".
    assert said("torque_mean", -4.74, -4.5) == (
        "mean torque: −4.74 N·m at 20 kHz, −4.5 N·m at 40 kHz (5.06 % smaller in size)"
    )
    assert said("torque_mean", -4.0, -5.0) == "mean torque: −4 N·m at 20 kHz, −5 N·m at 40 kHz (25 % larger in size)"
    assert said("torque_mean", -4.0, 5.0) == (
        "mean torque: −4 N·m at 20 kHz, 5 N·m at 40 kHz (it changes sign: 9 N·m apart)"
    )


def test_a_baseline_of_about_zero_is_said_so_and_the_change_given_as_it_is() -> None:
    # 2e-7 A of ripple is nothing: 0.5 A beside it is not "250 000 000 % higher".
    assert said("channels.ripple_rms", 2e-7, 0.5) == (
        "current ripple: about zero at 20 kHz, 0.5 A rms at 40 kHz (0.5 A rms higher)"
    )
    assert said("channels.ripple_rms", 2e-7, 4e-7) == (
        "current ripple: about zero at 20 kHz, about zero at 40 kHz (no change to speak of)"
    )


def test_a_change_under_the_tolerance_is_no_change_to_speak_of() -> None:
    # 7.9100 A to 7.9094 A is 0.008 %: under a thousandth of the figure.
    assert said("channels.i_switch_peak", 7.91, 7.9094) == (
        "peak switch current: 7.91 A at 20 kHz, 7.91 A at 40 kHz (no change to speak of)"
    )
    assert said("losses.tj_peak", 71.20, 71.23).endswith("(no change to speak of)")  # 0.03 K
    assert said("step.overshoot", 0.0420, 0.0423).endswith("(no change to speak of)")  # 0.03 points


def test_a_change_past_a_thousand_percent_is_said_in_times() -> None:
    # 0.5 ms to 30 ms is 5900 % higher: sixty times.
    assert said("step.rise_time", 0.0005, 0.03) == "rise time: 0.5 ms at 20 kHz, 30 ms at 40 kHz (60 times as high)"
    assert _changed(Read("x", "W"), 2.0, 22.0) == "1000 % higher"  # the last that is said in percent


def test_every_figure_a_sweep_reads_declares_how_its_change_is_said() -> None:
    assert KINDS == ("relative", "difference", "points")
    for key, read in READS.items():
        assert read.kind in KINDS, key
        # A temperature is never relative, and nor is a figure that is itself a percentage.
        if read.unit in ("°C", "%"):
            assert read.kind == ("points" if read.unit == "%" else "difference"), key
        assert read.floor > 0 and read.least > 0


@pytest.fixture(scope="module")
def ws():
    return workspace()


def test_the_library_lists_each_figure_with_its_kind(ws) -> None:
    told = posted("/api/control/explorations", started("example-mosfet", ws), ws)["reads"]
    assert told["losses.tj_peak"] == {
        "label": "peak junction temperature, settled",
        "unit": "°C",
        "kind": "difference",
        "scale": 1.0,
    }
    assert told["channels.f_switch_mean"]["unit"] == "kHz" and told["channels.f_switch_mean"]["scale"] == 1e-3
    assert told["step.overshoot"]["kind"] == "points" and told["losses.loss"]["kind"] == "relative"
    assert set(told) == set(READS)


PERCENT = re.compile(r"\(([\d.]+)% (?:higher|lower|larger in size|smaller in size)\)")


def ids() -> list[str]:
    from motionsim.service.control import EXPLORATIONS

    return [e.id for e in EXPLORATIONS]


@pytest.mark.parametrize("key", ("example-mosfet", "example-gan"))
@pytest.mark.parametrize("name", ids())
def test_no_exploration_says_a_percentage_of_a_temperature_or_of_a_percentage(ws, key: str, name: str) -> None:
    answer = posted("/api/control/sweep", {**started(key, ws), "exploration": name}, ws)
    by_label = {(r.label, r.unit): r for r in READS.values()}
    figures = 0
    for line in answer["said"]:
        every = [float(x) for x in re.findall(r"([\d.]+)%", line)]
        match = PERCENT.search(line)
        read = next(
            (
                r
                for (label, unit), r in by_label.items()
                if line.startswith(f"{label}: ") and (f" {unit} at " in line or "about zero" in line or not unit)
            ),
            None,
        )
        if read is None:
            continue  # what a run said of itself, in its own words
        figures += 1
        if read.kind != "relative":
            assert match is None, line
            assert " K " in line or "points" in line or "°" in line or "no change" in line, line
        elif match is not None:
            assert float(match.group(1)) <= 1000.0, line
        assert all(x <= 1000.0 for x in every) or read is None, line
    assert figures or all(v["refused"] for v in answer["variants"]) or answer["variants"][answer["baseline"]]["refused"]


def test_schemes_compared_say_the_torque_each_delivered(ws) -> None:
    # A loss or a ripple read at two schemes is only a comparison of the schemes where both
    # made the same torque: the sweep says what each made, from the runs themselves.
    base = started("example-mosfet", ws)
    answer = posted(
        "/api/control/sweep",
        {**base, "vary": {"path": "scheme", "schemes": ["foc_torque", "dtc_torque"]}, "reads": ["losses.loss"]},
        ws,
    )
    made = [v["torque_mean"] for v in answer["variants"]]
    labels = [v["label"] for v in answer["variants"]]
    (line,) = [s for s in answer["said"] if s.startswith("torque delivered")]
    at = [re.escape(x) for x in labels]
    told = re.fullmatch(rf"torque delivered: ([\d.]+) N·m at {at[0]}, ([\d.]+) N·m at {at[1]}", line)
    assert told is not None, line
    assert [float(x) for x in told.groups()] == pytest.approx(made, rel=5e-3)  # to three figures
    assert all(m == pytest.approx(4.74, rel=0.02) for m in made)
    # And it comes before the figures compared.
    assert answer["said"].index(line) < next(n for n, s in enumerate(answer["said"]) if "loss" in s.lower())


def test_a_sweep_of_one_scheme_s_setting_does_not_list_torques(ws) -> None:
    base = started("example-mosfet", ws)
    answer = posted(
        "/api/control/sweep",
        {
            **base,
            "scheme": "foc_torque",
            "vary": {"path": "inverter.t_dead", "values": [0.0, 5e-7]},
            "reads": ["losses.loss"],
        },
        ws,
    )
    assert not [s for s in answer["said"] if s.startswith("torque delivered")]
