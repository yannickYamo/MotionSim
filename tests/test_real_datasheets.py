"""Regression checks on real datasheets.

The PDFs are the vendors' property and are not in the repository, so these
tests run only where a `datasheets/` folder holds them. They need no network:
axis limits are written here by hand, and only the geometry code is exercised.
The expected values are the datasheets' own tabulated figures.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pdfplumber
import pytest

from motionsim.observe.figures import Axis, curves_in, digitise, find_frames, match_frames

FOLDER = Path(__file__).parent.parent / "datasheets"


def page(name: str, number: int):
    path = FOLDER / name
    if not path.exists():
        pytest.skip(f"{name} is not in datasheets/")
    return pdfplumber.open(path).pages[number - 1]


def at(x, y, where):
    order = np.argsort(x)
    return float(np.interp(where, x[order], y[order]))


def spanning(curves, frame, share=0.4):
    return [
        c
        for c in curves
        if np.ptp(c[:, 0]) > share * (frame.x1 - frame.x0) or np.ptp(c[:, 1]) > share * (frame.bottom - frame.top)
    ]


ONSEMI = "onsemi_FGHL40T65MQD.pdf"
EPC = "epc_EPC2302.pdf"
MODULE_C = "module_c.pdf"


@pytest.mark.parametrize(
    ("name", "number", "count"),
    [
        (ONSEMI, 4, 6),
        (ONSEMI, 6, 6),
        (ONSEMI, 7, 2),
        (EPC, 3, 6),
        (EPC, 4, 6),
        (EPC, 5, 2),
        (MODULE_C, 14, 12),
    ],
)
def test_plot_areas_found(name: str, number: int, count: int) -> None:
    assert len(find_frames(page(name, number))) == count


def test_onsemi_saturation_voltage_curves() -> None:
    p = page(ONSEMI, 4)
    frame = find_frames(p)[2]
    curves = spanning(curves_in(p, frame), frame)
    assert len(curves) == 2
    volts = sorted(at(*digitise(c, frame, Axis(0, 5, False), Axis(0, 200, False))[::-1], 40.0) for c in curves)
    assert volts == pytest.approx([1.45, 1.77], rel=0.03)  # table: 25 °C and 175 °C at 40 A


def test_onsemi_switching_energy_curves() -> None:
    p = page(ONSEMI, 6)
    frame = find_frames(p)[1]
    curves = spanning(curves_in(p, frame), frame)
    assert len(curves) == 4
    at_40 = sorted(at(*digitise(c, frame, Axis(0, 150, False), Axis(100, 10000, True)), 40.0) for c in curves)
    assert at_40 == pytest.approx([520, 770, 860, 1280], rel=0.04)  # table, in µJ


def test_onsemi_diode_forward_curves() -> None:
    p = page(ONSEMI, 6)
    frame = find_frames(p)[2]
    assert len(spanning(curves_in(p, frame), frame)) == 3


def test_onsemi_thermal_impedance_plateaus() -> None:
    p = page(ONSEMI, 7)
    for frame, y_axis, table in zip(
        find_frames(p), (Axis(0.01, 1, True), Axis(0.001, 2, True)), (0.63, 1.6), strict=True
    ):
        curves = spanning(curves_in(p, frame), frame)
        single = max(curves, key=lambda c: c[np.argmin(c[:, 0]), 1])
        _, z = digitise(single, frame, Axis(1e-5, 10, True), y_axis)
        assert z.max() == pytest.approx(table, rel=0.04)


def test_epc_normalised_resistance_curve() -> None:
    p = page(EPC, 4)
    frame = match_frames(p, find_frames(p), ["Figure 9"])["Figure 9"]
    curves = spanning(curves_in(p, frame), frame)
    assert len(curves) == 1
    t, r = digitise(curves[0], frame, Axis(-25, 175, False), Axis(0.5, 2.5, False))
    assert at(t, r, 25.0) == pytest.approx(1.0, abs=0.03)


def test_captions_locate_their_plot_areas() -> None:
    p = page(ONSEMI, 6)
    frames = find_frames(p)
    found = match_frames(p, frames, [f"Figure {n}." for n in range(13, 19)])
    assert [frames.index(found[f"Figure {n}."]) for n in range(13, 19)] == [0, 1, 2, 3, 4, 5]


def test_module_saturation_curves_drawn_in_pieces() -> None:
    """Dotted grid, coloured curves built from hundreds of short pieces."""
    p = page(MODULE_C, 14)
    frame = find_frames(p)[0]
    curves = spanning(curves_in(p, frame), frame)
    assert len(curves) == 2


def test_module_energy_curves_each_come_back_whole() -> None:
    """Four curves per figure (two temperatures, high and low side), solid and dashed."""
    p = page(MODULE_C, 14)
    frames = find_frames(p)
    for k in (3, 4, 5):
        assert len(spanning(curves_in(p, frames[k]), frames[k], share=0.8)) == 4


def test_module_against_the_vendor_simulator() -> None:
    """A model built from the datasheet alone, with surveyed thermal assumptions,
    against the vendor's simulator. Needs the locally built device file."""
    import yaml

    from motionsim.device import load_device
    from motionsim.engine import OperatingPoint, solve

    built = FOLDER.parent / "runs" / "module_c.device.yaml"
    if not built.exists():
        pytest.skip("runs/module_c.device.yaml has not been built")
    device = load_device(built)
    results = FOLDER.parent / "private" / "simulator_modules.yaml"
    if not results.exists():
        pytest.skip("no simulator results kept locally")
    data = yaml.safe_load(results.read_text())
    reference = data["parts"][data["aliases"]["module_c"]]
    for row in reference["points"]:
        f_out, f_sw, pf, total, t_case = row[0], row[1], row[2], row[5], row[6]
        r = solve(
            device,
            OperatingPoint(
                v_dc=300,
                i_rms=reference["i_rms"],
                modulation_index=0.8,
                power_factor=pf,
                f_sw=f_sw * 1000,
                t_sink=t_case,
                f_out=f_out,
            ),
        )
        # Up to 13% high: turn-off energy still comes from the table, because this
        # datasheet's hot turn-off curve and its table disagree by 17%.
        assert r.p_inverter == pytest.approx(total, rel=0.15)
        low, high = r.tj_peak_range
        assert low <= max(row[11], row[15]) <= high  # the simulator's hottest junction
