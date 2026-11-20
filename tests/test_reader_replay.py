"""One datasheet all the way through, with a recording where the model would be: a PDF made
in the test, its tables read and checked, its figures digitised, a device built and one
operating point solved. What comes out is held to the part the PDF was drawn from, worked
here by direct integration and not by the engine."""

from __future__ import annotations

import math

import numpy as np
import pytest

from evals.reader import recordings, replay, sheets
from motionsim.device import Basis
from motionsim.engine import OperatingPoint, solve
from motionsim.fit import build_device
from motionsim.observe import run

AMPS = 40.0


# The part, written out again by hand: a 650 V, 40 A IGBT and its diode.
def vce(i, tj):
    a, b, c = (0.55, 0.08, 0.0124) if tj == 25 else (0.40, 0.09, 0.0208)
    return a + b * np.sqrt(i) + c * i


def vf(i, tj):
    a, b, c = (0.60, 0.07, 0.0115) if tj == 25 else (0.42, 0.075, 0.0125)
    return a + b * np.sqrt(i) + c * i


def energy(nominal_mj, i):
    return nominal_mj * 1e-3 * (0.7 * (i / AMPS) + 0.3 * (i / AMPS) ** 2)


@pytest.fixture(scope="module")
def reading(tmp_path_factory):
    sheet = sheets.labelled_set()[0]
    assert sheet.part_number == "MU-G-650-40"
    data, _ = sheets.build(sheet)
    path = tmp_path_factory.mktemp("replay") / "igbt.pdf"
    path.write_bytes(data)
    with replay.as_if_anthropic():
        client = replay.ReplayClient(path, recordings.load(sheet.name)["faithful"])
        return run.read_datasheet(path, path.with_suffix(".yaml"), client=client, say=lambda line: None)


def test_the_tables_are_read_as_printed_and_nothing_is_flagged(reading) -> None:
    obs = reading.observations
    assert reading.summary()[0] == "18 table values read, 0 flagged"
    read = {(o.quantity.value, o.tj_c): o for o in obs.observations}
    assert read[("vce_sat", 25.0)].typ == 1.55 and read[("vce_sat", 150.0)].typ == 1.80
    assert read[("e_on", 150.0)].typ == pytest.approx(1.10e-3) and read[("e_on", 150.0)].voltage_v == 400.0
    assert read[("rth_jc_switch", None)].typ == 0.50 and read[("v_rated", None)].max == 650.0
    assert reading.ledger.calls == 3


def test_the_digitised_curves_are_the_curves_that_were_drawn(reading) -> None:
    curves = {(c.quantity.value, c.tj_c): c for c in reading.observations.curves}
    assert len(curves) == 7 and not any(c.flags for c in curves.values())
    for tj in (25.0, 150.0):
        for name, truth in (("vce_curve", vce), ("vf_curve", vf)):
            got = curves[(name, tj)]
            assert np.array(got.y) == pytest.approx(truth(np.array(got.x), tj), rel=0.01)
    on = curves[("e_on_curve", 150.0)]
    assert np.array(on.y)[5:] == pytest.approx(energy(1.10, np.array(on.x))[5:], rel=0.02)


def test_the_device_built_is_the_part(reading) -> None:
    device = build_device(reading.observations)
    assert device.switch.conduction.basis is Basis.curve and device.switch.e_on.v_ref == 400.0
    assert device.ratings.tj_max == 175.0
    # The thermal impedance was drawn from three stages, ending at the typical 0.50 K/W; the
    # fit finds them again, each scaled to the 0.60 K/W maximum printed beside it.
    assert device.switch.thermal.r == pytest.approx([0.06, 0.24, 0.30], rel=0.01)
    assert device.switch.thermal.tau == pytest.approx([1e-4, 2e-3, 3e-2], rel=0.01)


def test_one_operating_point_gives_the_loss_worked_by_hand(reading) -> None:
    """400 V, 16 A rms, modulation 0.9 at power factor 0.85, 8 kHz, on a sink at 80 °C.

    Each loss is the part's own curve integrated over the half period the device conducts,
    with the device at its own temperature (between the 25 °C and 150 °C curves in
    proportion). The engine is given only what was read off the PDF."""
    device = build_device(reading.observations)
    point = OperatingPoint(v_dc=400, i_rms=16, modulation_index=0.9, power_factor=0.85, f_sw=8000, t_sink=80)
    result = solve(device, point)

    theta = np.linspace(0.0, math.pi, 20001)[1:-1]
    i = 16 * math.sqrt(2) * np.sin(theta)
    duty = 0.5 * (1 + 0.9 * np.sin(theta + math.acos(0.85)))

    def mean(values) -> float:
        return float(np.sum((values[1:] + values[:-1]) / 2 * np.diff(theta)) / (2 * math.pi))

    def between(cold, hot, tj):
        return cold + (hot - cold) * (tj - 25.0) / 125.0

    turn_on, turn_off = 8000 * mean(energy(1.10, i)), 8000 * mean(energy(0.85, i))  # the 150 °C curves
    # Temperatures follow from the losses and the losses from the temperatures: a few rounds settle it.
    tj_switch = tj_diode = 80.0
    for _ in range(20):
        conduction = mean(between(vce(i, 25), vce(i, 150), tj_switch) * i * duty)
        diode = mean(between(vf(i, 25), vf(i, 150), tj_diode) * i * (1 - duty))
        recovery = 8000 * mean(between(0.25e-3, 0.55e-3, tj_diode) * i / AMPS)  # table points, linear in current
        # The drawn curve ends at the typical 0.50 K/W and is taken to the 0.60 maximum.
        tj_switch = 80.0 + 0.60 * (conduction + turn_on + turn_off)
        # The diode has no thermal impedance drawn, and its table gives 0.90 K/W typical and
        # 1.05 maximum: the maximum is what a design is held to, and what is used.
        tj_diode = 80.0 + 1.05 * (diode + recovery)

    assert result.switch.conduction == pytest.approx(conduction, rel=0.01)
    assert result.switch.turn_on == pytest.approx(turn_on, rel=0.01)
    assert result.switch.turn_off == pytest.approx(turn_off, rel=0.01)
    assert result.diode.conduction == pytest.approx(diode, rel=0.01)
    # The engine reads a loss at the chip's temperature at each instant, the hand figure at
    # its mean over the period. The diode is warmest while it carries most, so on an energy
    # that rises with temperature the engine's figure is the higher, by 1% here.
    assert result.diode.recovery == pytest.approx(recovery, rel=0.02)
    assert result.diode.recovery >= recovery
    assert result.tj_switch == pytest.approx(tj_switch, abs=0.05)
    assert result.tj_diode == pytest.approx(tj_diode, abs=0.05)
    assert 85.0 < tj_switch < 86.0  # the sum is not vacuous: some 9 W through 0.6 K/W
