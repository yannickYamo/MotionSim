"""What an operating point told outright is held to, whoever tells it: a modulation index
the scheme can reach, enough samples in a period to integrate it, and the same usable
voltage a motor's point is held to."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from motionsim import cli
from motionsim.device import load_device
from motionsim.engine import OperatingPoint, Pwm, solve
from motionsim.errors import BadFigure, Refusal

ROOT = Path(__file__).parent.parent
IGBT = ROOT / "examples/synthetic_igbt_600v_30a.yaml"
BASE = dict(v_dc=300.0, i_rms=10.0, power_factor=0.85, f_sw=8000.0, t_sink=60.0)


@pytest.mark.parametrize(
    "pwm, most",
    [
        (Pwm.sine, 1.0),
        (Pwm.third_harmonic, 2 / math.sqrt(3)),
        (Pwm.space_vector, 2 / math.sqrt(3)),
        (Pwm.discontinuous, 2 / math.sqrt(3)),
    ],
)
def test_a_modulation_index_past_the_schemes_linear_range_is_refused(pwm, most) -> None:
    OperatingPoint(**BASE, modulation_index=most, pwm=pwm)
    with pytest.raises(BadFigure, match="modulation index"):
        OperatingPoint(**BASE, modulation_index=most * 1.001, pwm=pwm)


@pytest.mark.parametrize("n", [0, 1, 16, 63])
def test_too_few_samples_in_a_period_are_refused(n) -> None:
    with pytest.raises(BadFigure, match="samples"):
        OperatingPoint(**BASE, modulation_index=0.9, n_steps=n)


def test_the_fewest_samples_allowed_integrate_the_period_closely() -> None:
    """At the fewest allowed the loss is within a thousandth of the loss with eight times the
    default, which stands for the integral itself."""
    device = load_device(IGBT)
    fine = solve(device, OperatingPoint(**BASE, modulation_index=0.9, n_steps=16384)).p_inverter
    least = solve(device, OperatingPoint(**BASE, modulation_index=0.9, n_steps=64)).p_inverter
    assert least == pytest.approx(fine, rel=1e-3)


SIMULATE = ["--vdc", "48", "--irms", "10", "--m", "0.9", "--pf", "0.85", "--fsw", "20000", "--tsink", "60"]
GATE = ["--vdrive", "12", "--rgon", "5", "--rgoff", "5"]


TOLD = {
    "simulate": ["simulate", "example-mosfet", *SIMULATE],
    "compare": ["compare", "example-mosfet", "example-mosfet", *SIMULATE],
    "max-current": ["max-current", "example-mosfet", *SIMULATE[:2], *SIMULATE[4:]],
}


@pytest.mark.parametrize("command", sorted(TOLD))
def test_a_told_point_is_held_to_the_usable_voltage_as_a_motors_is(capsys, command) -> None:
    """A shortest pulse of 24 µs at 20 kHz takes nearly all of each period: the motor command
    refuses such a stage, and so does every command told its modulation outright."""
    status = cli.main([*TOLD[command], *GATE, "--tmin", "2.4e-5"])
    said = capsys.readouterr()
    assert status == 2, said.out
    assert "each switching period" in said.err


def test_a_modulation_index_the_stage_cannot_give_is_refused(capsys) -> None:
    """At 48 V and 100 A the example transistor drops volts the stage must give; a
    modulation index of one asks for all of the ideal voltage, which is no longer there."""
    point = ["--vdc", "12", "--irms", "100", "--m", "1", "--pf", "0.85", "--fsw", "20000", "--tsink", "60"]
    status = cli.main(["simulate", "example-mosfet", *point, *GATE, "--tdead", "5e-7"])
    said = capsys.readouterr()
    assert status == 2
    assert "modulation index" in said.err and "of the ideal output voltage" in said.err


def test_the_service_refuses_a_modulation_index_past_the_scheme() -> None:
    from motionsim.service.validate import conditions, electrical

    op = conditions({"v_dc": 300, "f_sw": 8000, "t_sink": 60})
    with pytest.raises(Refusal) as refused:
        electrical({"i_rms": 10, "m": 1.05, "pf": 0.85}, op)
    assert refused.value.field == "m" and "sine" in refused.value.reason


def test_the_package_lists_what_it_offers() -> None:
    import motionsim

    listed = dir(motionsim)
    for name in ("OperatingPoint", "Refusal", "load_device", "run_design", "simulate", "__version__"):
        assert name in listed
        assert getattr(motionsim, name) is not None
    assert "TYPE_CHECKING" not in listed
