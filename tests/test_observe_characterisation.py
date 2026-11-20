"""The figure readers on figures drawn here, each from a curve whose equation is known.

What is expected of a reading is the curve the figure was drawn from, or the sentence the
reader gives when it sets a figure aside. These hold the readers still while their long
functions are divided into steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image, ImageDraw

from motionsim.device.schema import ReviewStatus
from motionsim.observe import figures, raster
from motionsim.observe.charge import digitise_capacitance, digitise_gate_charge
from motionsim.observe.family import (
    digitise_family,
    digitise_gate_resistance,
    digitise_normalised_resistance,
    digitise_voltage,
)
from motionsim.observe.schema import (
    AxisClaim,
    FigureKind,
    Observation,
    Quantity,
    ReadAxes,
    ReadFigure,
    ReadSeries,
)
from motionsim.observe.thermal import digitise_thermal


@dataclass(frozen=True)
class Plot:
    """A plot area on a page, and the axes it is drawn to."""

    x: tuple[float, float, bool]  # low, high, logarithmic
    y: tuple[float, float, bool]
    x0: float = 100.0
    x1: float = 400.0
    top: float = 50.0
    bottom: float = 250.0

    @staticmethod
    def _share(value, axis) -> np.ndarray:
        lo, hi, log = axis
        value = np.asarray(value, dtype=float)
        if log:
            return (np.log10(value) - np.log10(lo)) / (np.log10(hi) - np.log10(lo))
        return (value - lo) / (hi - lo)

    def px(self, value) -> np.ndarray:
        return self.x0 + self._share(value, self.x) * (self.x1 - self.x0)

    def py(self, value) -> np.ndarray:
        return self.bottom + self._share(value, self.y) * (self.top - self.bottom)

    @staticmethod
    def _ticks(axis) -> list[float]:
        lo, hi, log = axis
        if not log:
            return [lo + k / 10 * (hi - lo) for k in range(11)]
        decades = range(int(np.floor(np.log10(lo))), int(np.ceil(np.log10(hi))) + 1)
        return [m * 10.0**d for d in decades for m in range(1, 10) if lo * 0.999 <= m * 10.0**d <= hi * 1.001]

    def grid(self) -> list[dict]:
        lines = []
        for value in self._ticks(self.x):
            x = float(self.px(value))
            lines.append({"linewidth": 0.23, "x0": x, "x1": x, "top": self.top, "bottom": self.bottom})
        for value in self._ticks(self.y):
            y = float(self.py(value))
            lines.append({"linewidth": 0.23, "x0": self.x0, "x1": self.x1, "top": y, "bottom": y})
        return lines

    def curve(self, xs, ys, **extra) -> dict:
        px, py = self.px(xs), self.py(ys)
        points = list(zip(px.tolist(), py.tolist(), strict=True))
        return {
            "linewidth": 0.96,
            "path": [("m", points[0])] + [("l", p) for p in points[1:]],
            "x0": px.min(),
            "x1": px.max(),
            "top": py.min(),
            "bottom": py.max(),
            **extra,
        }

    def page(self, *curves: dict):
        return SimpleNamespace(lines=self.grid(), curves=list(curves))

    def claim(self, x_unit: str, y_unit: str, series=(), **extra) -> ReadAxes:
        return ReadAxes(
            label="Figure 9",
            x=AxisClaim(lo=self.x[0], hi=self.x[1], log=self.x[2]),
            y=AxisClaim(lo=self.y[0], hi=self.y[1], log=self.y[2]),
            x_unit=x_unit,
            y_unit=y_unit,
            series=list(series),
            **extra,
        )


def tabulated(quantity, typ, *, current=None, voltage=None, tj=None, maximum=None, unit="") -> Observation:
    return Observation(
        quantity=quantity,
        typ=typ,
        max=maximum,
        printed_typ=None if typ is None else str(typ),
        printed_max=None if maximum is None else str(maximum),
        unit=unit,
        current_a=current,
        voltage_v=voltage,
        tj_c=tj,
        page=2,
        status=ReviewStatus.unverified,
        flags=[],
    )


def figure(kind: FigureKind) -> ReadFigure:
    return ReadFigure(page=5, label="Figure 9", shows="drawn here", kind=kind)


def at(curve, x: float) -> float:
    return float(np.interp(x, curve.x, curve.y))


# ---- switching energy against gate resistance, and against the voltage switched ----

RG = Plot(x=(0.0, 50.0, False), y=(0.0, 10.0, False))  # ohm, mJ
RG_TEST, I_TEST, TJ_TEST = 10.0, 40.0, 150.0


def e_on_mj(rg):
    return 2.0 + 0.08 * np.asarray(rg)


def e_off_mj(rg):
    return 1.5 + 0.02 * np.asarray(rg)


def rg_page(*functions):
    rg = np.linspace(2.0, 48.0, 60)
    return RG.page(*[RG.curve(rg, f(rg)) for f in functions])


def rg_axes(**changes) -> ReadAxes:
    given = {
        "series": [ReadSeries(name="e_on", tj_c=TJ_TEST), ReadSeries(name="e_off", tj_c=TJ_TEST)],
        "test_current_a": I_TEST,
        "test_voltage_v": 600.0,
        **changes,
    }
    return RG.claim("Ω", "mJ", **given)


def rg_tables(e_on=None, e_off=None, resistor=RG_TEST) -> list[Observation]:
    e_on = float(e_on_mj(RG_TEST)) * 1e-3 if e_on is None else e_on
    e_off = float(e_off_mj(RG_TEST)) * 1e-3 if e_off is None else e_off
    return [
        tabulated(Quantity.e_on, e_on, current=I_TEST, voltage=600.0, tj=TJ_TEST),
        tabulated(Quantity.e_off, e_off, current=I_TEST, voltage=600.0, tj=TJ_TEST),
        tabulated(Quantity.rg_on_test, resistor),
        tabulated(Quantity.rg_off_test, resistor),
    ]


def read_rg(page, axes, tables):
    (frame,) = figures.find_frames(page)
    return digitise_gate_resistance(page, frame, figure(FigureKind.switching_energy_vs_gate_resistance), axes, tables)


@pytest.mark.parametrize("drawn", [(e_on_mj, e_off_mj), (e_off_mj, e_on_mj)])
def test_energy_against_gate_resistance_is_tied_to_the_table_whatever_the_drawing_order(drawn) -> None:
    on, off = read_rg(rg_page(*drawn), rg_axes(), rg_tables())
    assert (on.quantity, off.quantity) == (Quantity.e_on_rg_curve, Quantity.e_off_rg_curve)
    assert on.flags == [] and off.flags == [] and on.status is ReviewStatus.unverified
    for curve, truth in ((on, e_on_mj), (off, e_off_mj)):
        assert curve.tj_c == TJ_TEST and curve.test_voltage_v == 600.0 and curve.method == "vector"
        assert len(curve.x) == 40 and curve.x[0] == pytest.approx(2.0) and curve.x[-1] == pytest.approx(48.0)
        for rg in (5.0, 30.0, 45.0):
            assert at(curve, rg) == pytest.approx(float(truth(rg)) * 1e-3, rel=1e-3)
        assert curve.anchor_error == pytest.approx(0.0, abs=1e-3)
        assert curve.notes == ["at 40 A; passes through the tabulated energy at 10 ohm"]


def test_a_gate_resistance_figure_that_cannot_be_tied_to_the_table_is_set_aside() -> None:
    page = rg_page(e_on_mj, e_off_mj)

    def reason(axes=None, tables=None, pg=page) -> str:
        (only,) = read_rg(pg, axes or rg_axes(), rg_tables() if tables is None else tables)
        assert only.status is ReviewStatus.flagged and only.x == [] and only.quantity is Quantity.e_on_rg_curve
        (flag,) = only.flags
        return flag

    assert reason(RG.claim("V", "mJ", series=rg_axes().series, test_current_a=I_TEST)) == (
        "axis units 'V', 'mJ' do not fit this kind of figure"
    )
    assert reason(RG.claim("Ω", "furlong", series=rg_axes().series, test_current_a=I_TEST)) == (
        "axis units 'Ω', 'furlong' do not fit this kind of figure"
    )
    assert reason(rg_axes(test_current_a=None)) == "the figure does not state the current it was measured at"
    assert reason(pg=rg_page(e_on_mj)) == "1 curves drawn but the reader described 2"
    assert reason(rg_axes(series=[ReadSeries(name="other", tj_c=None), ReadSeries(name="other", tj_c=None)])) == (
        "2 curves drawn but the reader described 2"
    )
    untied = "no tabulated energy at this figure's current and temperature to tie the curves to"
    assert reason(tables=[]) == untied
    assert reason(tables=rg_tables()[:2]) == untied  # the energies, and no gate resistor to place them at
    assert reason(rg_axes(test_current_a=25.0)) == untied
    # Turn-on energy tabulated at twice what the curve reads at the table's resistor.
    doubled = rg_tables(e_on=2 * float(e_on_mj(RG_TEST)) * 1e-3)
    assert reason(tables=doubled) == (
        "the curves do not pass through the tabulated energy at the table's own gate resistor (off by 50%)"
    )
    # A table measured with a resistor the figure does not reach.
    assert reason(tables=rg_tables(resistor=75.0)) == (
        "the curves do not pass through the tabulated energy at the table's own gate resistor"
    )


def test_a_series_with_no_temperature_is_tied_to_the_table_at_25_degrees() -> None:
    axes = rg_axes(series=[ReadSeries(name="e_on", tj_c=None), ReadSeries(name="e_off", tj_c=None)])
    tables = [o.model_copy(update={"tj_c": 25.0 if o.tj_c else None}) for o in rg_tables()]
    on, off = read_rg(rg_page(e_on_mj, e_off_mj), axes, tables)
    assert on.tj_c is None and off.tj_c is None and on.flags == [] and off.flags == []


VOLTS = Plot(x=(0.0, 800.0, False), y=(0.0, 10.0, False))  # V, mJ


def test_energy_against_the_voltage_switched_meets_the_table_at_its_test_voltage() -> None:
    on_of = lambda v: 0.008 * np.asarray(v)
    off_of = lambda v: 0.5 + 0.003 * np.asarray(v)
    v = np.linspace(100.0, 780.0, 50)
    page = VOLTS.page(VOLTS.curve(v, off_of(v)), VOLTS.curve(v, on_of(v)))
    axes = VOLTS.claim(
        "V",
        "mJ",
        series=[ReadSeries(name="e_on", tj_c=TJ_TEST), ReadSeries(name="e_off", tj_c=TJ_TEST)],
        test_current_a=I_TEST,
    )
    tables = [
        tabulated(Quantity.e_on, float(on_of(600.0)) * 1e-3, current=I_TEST, voltage=600.0, tj=TJ_TEST),
        tabulated(Quantity.e_off, float(off_of(600.0)) * 1e-3, current=I_TEST, voltage=600.0, tj=TJ_TEST),
    ]
    (frame,) = figures.find_frames(page)
    kind = figure(FigureKind.switching_energy_vs_voltage)
    on, off = digitise_voltage(page, frame, kind, axes, tables)
    assert (on.quantity, off.quantity) == (Quantity.e_on_v_curve, Quantity.e_off_v_curve)
    assert at(on, 300.0) == pytest.approx(float(on_of(300.0)) * 1e-3, rel=1e-3)
    assert at(off, 700.0) == pytest.approx(float(off_of(700.0)) * 1e-3, rel=1e-3)
    assert on.notes == ["at 40 A; passes through the tabulated energy at 600 V"] and on.test_voltage_v is None
    # A table that gives the energy and not the voltage it was measured at ties nothing.
    blind = [o.model_copy(update={"voltage_v": None}) for o in tables]
    (aside,) = digitise_voltage(page, frame, kind, axes, blind)
    assert aside.quantity is Quantity.e_on_v_curve and aside.flags == [
        "no tabulated energy at this figure's current and temperature to tie the curves to"
    ]
    off_table = [tables[0].model_copy(update={"typ": 2 * tables[0].typ}), tables[1]]
    (aside,) = digitise_voltage(page, frame, kind, axes, off_table)
    assert aside.flags == [
        "the curves do not pass through the tabulated energy at the table's own test voltage (off by 50%)"
    ]


# ---- on-resistance against temperature, normalised to 25 °C ----

NORMAL = Plot(x=(-50.0, 200.0, False), y=(0.0, 3.0, False))


def r_norm(t, slope=0.006):
    return 1.0 + slope * (np.asarray(t) - 25.0)


def read_normal(*curves):
    page = NORMAL.page(*curves)
    (frame,) = figures.find_frames(page)
    return digitise_normalised_resistance(
        page, frame, figure(FigureKind.normalized_on_resistance), NORMAL.claim("°C", "")
    )


def test_a_normalised_resistance_curve_is_read_and_checks_itself_at_25_degrees() -> None:
    t = np.linspace(-40.0, 175.0, 80)
    found = read_normal(NORMAL.curve(t, r_norm(t)))
    assert found.quantity is Quantity.rds_norm_curve and found.flags == [] and found.notes == []
    assert len(found.x) == 40 and found.x[0] == pytest.approx(-40.0) and found.x[-1] == pytest.approx(175.0)
    for tj in (-20.0, 25.0, 150.0):
        assert at(found, tj) == pytest.approx(float(r_norm(tj)), abs=2e-3)


def test_of_several_normalised_curves_the_steepest_is_used_and_the_others_must_read_one() -> None:
    t = np.linspace(-40.0, 175.0, 80)
    found = read_normal(
        NORMAL.curve(t, r_norm(t, 0.004)),
        NORMAL.curve(t, r_norm(t, 0.008)),
        NORMAL.curve(t, 0.4 + 0.0 * t),  # reads 0.4 at 25 °C: not a normalised curve
    )
    assert found.flags == []
    assert found.notes == ["3 curves drawn; the one that rises most with temperature is used"]
    assert at(found, 150.0) == pytest.approx(float(r_norm(150.0, 0.008)), abs=2e-3)
    # None of them reads 1 at 25 °C: nothing to choose by.
    none = read_normal(NORMAL.curve(t, 0.4 + 0.0 * t), NORMAL.curve(t, 0.6 + 0.0 * t))
    assert none.flags == ["expected one curve, found 2"] and none.x == []
    assert read_normal().flags == ["expected one curve, found 0"]


def test_a_normalised_curve_that_fails_its_own_check_is_flagged() -> None:
    t = np.linspace(-40.0, 175.0, 80)
    assert read_normal(NORMAL.curve(t, 0.2 + r_norm(t))).flags == [
        "reads 1.2 at 25 °C where a normalised curve reads 1"
    ]
    late = np.linspace(60.0, 175.0, 40)
    assert read_normal(NORMAL.curve(late, r_norm(late))).flags == ["curve does not cover 25 °C"]
    falling = read_normal(NORMAL.curve(t, 1.0 - 0.004 * (t - 25.0)))
    assert falling.flags == ["on-resistance does not rise with temperature above 25 °C"]
    assert falling.status is ReviewStatus.flagged


# ---- gate charge and capacitance ----

GATE = Plot(x=(0.0, 100.0, False), y=(0.0, 15.0, False))  # nC, V
Q_PLATEAU, Q_END, V_PLATEAU = 20.0, 45.0, 5.0


def gate_voltage(q):
    """Rises to the plateau, holds it, then rises again more slowly."""
    q = np.asarray(q, dtype=float)
    return np.where(
        q < Q_PLATEAU,
        V_PLATEAU * q / Q_PLATEAU,
        np.where(q < Q_END, V_PLATEAU, V_PLATEAU + (q - Q_END) * 0.14),
    )


def read_gate(tables, *curves, axes=None):
    page = GATE.page(*curves)
    (frame,) = figures.find_frames(page)
    return digitise_gate_charge(page, frame, figure(FigureKind.gate_charge), axes or GATE.claim("nC", "V"), tables)


def test_the_plateau_of_a_drawn_gate_charge_curve_starts_at_the_tabulated_charge() -> None:
    q = np.linspace(0.0, 95.0, 400)
    drain = GATE.curve(q, 12.0 - 0.1 * q)  # the drain voltage falling: not the gate's curve
    found = read_gate([tabulated(Quantity.q_gs, Q_PLATEAU * 1e-9)], drain, GATE.curve(q, gate_voltage(q)))
    assert found.quantity is Quantity.gate_charge_curve and found.flags == []
    assert len(found.x) == 120 and found.x[-1] == pytest.approx(95e-9)
    for charge in (10.0, 30.0, 80.0):
        assert at(found, charge * 1e-9) == pytest.approx(float(gate_voltage(charge)), abs=0.03)
    assert found.anchor_error is not None and found.anchor_error < 0.1
    (note,) = found.notes
    assert note.startswith("plateau at 5 V, from ")
    # Only a maximum tabulated: the plateau may start below it, and that is no disagreement.
    capped = read_gate([tabulated(Quantity.q_gs, None, maximum=30e-9)], GATE.curve(q, gate_voltage(q)))
    assert capped.flags == [] and capped.anchor_error == 0.0
    untabulated = read_gate([], GATE.curve(q, gate_voltage(q)))
    assert untabulated.flags == [] and untabulated.anchor_error is None
    assert untabulated.notes[1] == "no tabulated gate-source charge to compare the start of the plateau with"


def test_a_gate_charge_figure_that_does_not_hold_up_is_flagged() -> None:
    q = np.linspace(0.0, 95.0, 400)
    curve = GATE.curve(q, gate_voltage(q))
    (flag,) = read_gate([tabulated(Quantity.q_gs, 5e-9)], curve).flags
    assert flag.startswith("plateau starts at ") and flag.endswith("the tabulated gate-source charge is 5 nC")
    assert read_gate([], GATE.curve(q, 0.12 * q)).flags == ["no plateau found in the gate-charge curve"]
    assert read_gate([]).flags == ["no curve found in the plot area"]
    assert read_gate([], curve, axes=GATE.claim("V", "nC")).flags == [
        "axis units 'V', 'nC' do not fit this kind of figure",
        "axes could not be confirmed",
    ]


CAPS = Plot(x=(1.0, 1000.0, True), y=(10.0, 10000.0, True))  # V, pF
V_COSS = 100.0


def c_oss_pf(v):
    return 2000.0 / np.sqrt(np.asarray(v, dtype=float))


def read_caps(tables, *curves, axes=None):
    page = CAPS.page(*curves)
    (frame,) = figures.find_frames(page)
    return digitise_capacitance(page, frame, figure(FigureKind.capacitance), axes or CAPS.claim("V", "pF"), tables)


def caps_curves(rival: float = 0.0):
    v = np.geomspace(1.0, 900.0, 120)
    curves = [
        CAPS.curve(v, 3000.0 + 0.0 * v),  # input capacitance
        CAPS.curve(v, c_oss_pf(v)),
        CAPS.curve(v, 600.0 / v**0.6),  # reverse transfer
    ]
    if rival:
        curves.append(CAPS.curve(v, rival * c_oss_pf(v)))
    return curves


def test_the_output_capacitance_curve_is_the_one_through_the_tabulated_value() -> None:
    table = [tabulated(Quantity.c_oss, float(c_oss_pf(V_COSS)) * 1e-12, voltage=V_COSS)]
    found = read_caps(table, *caps_curves())
    assert found.quantity is Quantity.c_oss_curve and found.flags == [] and found.test_voltage_v == V_COSS
    assert len(found.x) == 120 and found.anchor_error == pytest.approx(0.0, abs=2e-3)
    for volts in (2.0, 50.0, 600.0):
        read_at = float(np.interp(np.log(volts), np.log(found.x), found.y))
        assert read_at == pytest.approx(float(c_oss_pf(volts)) * 1e-12, rel=5e-3)


def test_a_capacitance_figure_that_cannot_be_told_apart_or_confirmed_is_flagged() -> None:
    table = [tabulated(Quantity.c_oss, float(c_oss_pf(V_COSS)) * 1e-12, voltage=V_COSS)]
    assert read_caps([], *caps_curves()).flags == [
        "no tabulated output capacitance with its voltage to tell the curves apart by"
    ]
    assert read_caps(table, *caps_curves(rival=1.05)).flags == [
        "two curves fit the tabulated output capacitance about equally well"
    ]
    twice = [tabulated(Quantity.c_oss, 2 * float(c_oss_pf(V_COSS)) * 1e-12, voltage=V_COSS)]
    assert read_caps(twice, *caps_curves()[1:2]).flags == [
        "closest curve differs from the tabulated output capacitance by 50%"
    ]
    beyond = [tabulated(Quantity.c_oss, 1e-10, voltage=5000.0)]
    assert read_caps(beyond, *caps_curves()).flags == ["no curve reaches the tabulated test voltage"]
    v = np.geomspace(1.0, 900.0, 120)
    rising = [tabulated(Quantity.c_oss, 20.0 * V_COSS**0.5 * 1e-12, voltage=V_COSS)]
    assert read_caps(rising, CAPS.curve(v, 20.0 * np.sqrt(v))).flags == [
        "output capacitance does not fall with voltage"
    ]
    assert read_caps(table, *caps_curves(), axes=CAPS.claim("V", "pF").model_copy(update={"x_unit": "A"})).flags == [
        "axis units 'A', 'pF' do not fit this kind of figure",
        "axes could not be confirmed",
    ]
    wrong_span = CAPS.claim("V", "pF").model_copy(update={"x": AxisClaim(lo=1.0, hi=100.0, log=True)})
    flags = read_caps(table, *caps_curves(), axes=wrong_span).flags
    assert flags[0].startswith("x axis limits 1 to 100 match only ") and flags[-1] == "axes could not be confirmed"


# ---- thermal impedance ----

THERMAL = Plot(x=(1e-5, 10.0, True), y=(0.01, 1.0, True), x1=460.0)
R_FOSTER = np.array([0.05, 0.25, 0.30])
TAU_FOSTER = np.array([1e-4, 2e-3, 3e-2])


def zth(t):
    return (R_FOSTER * (1 - np.exp(-np.asarray(t)[:, None] / TAU_FOSTER))).sum(axis=1)


def read_thermal(tables, *curves, axes=None):
    page = THERMAL.page(*curves)
    (frame,) = figures.find_frames(page)
    kind = figure(FigureKind.thermal_impedance_switch)
    return digitise_thermal(page, frame, kind, axes or THERMAL.claim("s", "K/W"), tables)


def test_a_single_pulse_curve_that_stops_where_the_curves_merge_is_followed_along_the_shared_line() -> None:
    short = np.logspace(np.log10(2.5e-5), -1, 150)  # the single-pulse curve, drawn to 0.1 s
    whole = np.logspace(np.log10(2.5e-5), 0, 200)
    duty = zth(whole) + 0.3 * np.exp(-whole / 2e-3)  # above it at short times, the same line by 0.1 s
    table = [tabulated(Quantity.rth_jc_switch, float(R_FOSTER.sum()))]
    found = read_thermal(table, THERMAL.curve(whole, duty), THERMAL.curve(short, zth(short)))
    assert found.flags == []
    assert found.notes == ["the single-pulse curve merges into the others and is followed along the shared line"]
    assert found.x[-1] == pytest.approx(1.0, rel=1e-3) and found.y[-1] == pytest.approx(R_FOSTER.sum(), rel=0.01)
    probe = np.array([1e-4, 1e-3, 1e-2])
    assert np.interp(np.log(probe), np.log(found.x), found.y) == pytest.approx(zth(probe), rel=0.02)


def test_a_thermal_curve_whose_plateau_is_the_tabulated_maximum_is_kept_with_a_note() -> None:
    t = np.logspace(np.log10(2.5e-5), 0, 200)
    table = [tabulated(Quantity.rth_jc_switch, 0.4, maximum=float(R_FOSTER.sum()))]
    found = read_thermal(table, THERMAL.curve(t, zth(t)))
    assert found.flags == []
    assert found.notes == [
        "the curve is the maximum thermal impedance: its plateau matches the tabulated "
        "maximum of 0.6 K/W, not the typical 0.4 K/W"
    ]


def test_a_thermal_figure_that_cannot_be_confirmed_says_why() -> None:
    t = np.logspace(np.log10(2.5e-5), 0, 200)
    curve = THERMAL.curve(t, zth(t))
    assert read_thermal([], curve).flags == ["no tabulated thermal resistance to compare the plateau with"]
    empty = read_thermal([])
    assert empty.flags == ["no vector curve found in the plot area"] and empty.x == []
    linear = THERMAL.claim("s", "K/W").model_copy(update={"y": AxisClaim(lo=0.01, hi=1.0, log=False)})
    aside = read_thermal([], curve, axes=linear)
    assert aside.flags == ["y axis claimed linear; thermal impedance plots are log-log"] and aside.x == []
    units = read_thermal([tabulated(Quantity.rth_jc_switch, 0.6)], curve, axes=THERMAL.claim("ms", "V"))
    assert units.flags == ["time axis unit 'ms' is not seconds", "impedance axis unit 'V' is not a thermal resistance"]
    dipping = zth(t) * (1 - 0.3 * np.exp(-((np.log10(t) + 2) ** 2) / 0.02))
    flags = read_thermal([tabulated(Quantity.rth_jc_switch, 0.6)], THERMAL.curve(t, dipping)).flags
    assert flags == ["curve does not rise steadily with pulse duration"]


# ---- a family of curves told apart by colour alone ----

ENERGY = Plot(x=(0.0, 100.0, False), y=(0.0, 10.0, False))  # A, mJ


def test_energy_curves_with_nothing_tabulated_are_named_by_their_legend_colours() -> None:
    i = np.linspace(5.0, 95.0, 60)
    on_of, off_of = (lambda c: 0.06 * np.asarray(c)), (lambda c: 0.5 + 0.02 * np.asarray(c))
    page = ENERGY.page(
        ENERGY.curve(i, off_of(i), stroking_color=(0.0, 0.0, 1.0)),
        ENERGY.curve(i, on_of(i), stroking_color=(1.0, 0.0, 0.0)),
    )
    (frame,) = figures.find_frames(page)
    series = [ReadSeries(name="e_on", tj_c=None, colour="red"), ReadSeries(name="e_off", tj_c=None, colour="blue")]
    kind = figure(FigureKind.switching_energy_vs_current)
    on, off = digitise_family(page, frame, kind, ENERGY.claim("A", "mJ", series, test_voltage_v=400.0), [])
    assert (on.quantity, off.quantity) == (Quantity.e_on_curve, Quantity.e_off_curve)
    assert on.tj_c == 25.0 and on.test_voltage_v == 400.0 and on.flags == [] and on.anchor_error is None
    assert on.notes == ["identified by its colour in the legend; the datasheet tabulates no value to compare it with"]
    assert at(on, 50.0) == pytest.approx(float(on_of(50.0)) * 1e-3, rel=1e-3)
    assert at(off, 50.0) == pytest.approx(float(off_of(50.0)) * 1e-3, rel=1e-3)
    # Without the voltage it was measured at, an energy named only by colour cannot be scaled.
    (aside,) = digitise_family(page, frame, kind, ENERGY.claim("A", "mJ", series), [])
    assert aside.flags == ["no tabulated value applies to any curve in this figure"]
    (aside,) = digitise_family(page, frame, kind, ENERGY.claim("V", "mJ", series), [])
    assert aside.flags == ["axis units 'V', 'mJ' do not fit this kind of figure", "axes could not be confirmed"]


# ---- plot areas: captions, insets, and figures stored as pictures ----


def searchable(page, hits: dict[str, list[dict]]):
    page.search = lambda label, regex=False: hits[label]
    return page


def test_a_caption_names_the_plot_area_it_sits_under_or_over() -> None:
    upper = Plot(x=(0.0, 1.0, False), y=(0.0, 1.0, False), top=50.0, bottom=250.0)
    lower = Plot(x=(0.0, 1.0, False), y=(0.0, 1.0, False), top=350.0, bottom=550.0)
    page = SimpleNamespace(lines=upper.grid() + lower.grid(), curves=[])
    first, second = figures.find_frames(page)
    assert (first.top, second.top) == (50.0, 350.0)
    hit = lambda top: {"x0": 180.0, "x1": 320.0, "top": top, "bottom": top + 10.0}
    below = searchable(page, {"Figure 1": [hit(262.0)], "Figure 2": [hit(562.0)], "Figure 3": []})
    placed = figures.match_frames(below, [first, second], ["Figure 1", "Figure 2", "Figure 3"])
    assert placed == {"Figure 1": first, "Figure 2": second}
    # Captions printed above their plots: the first caption sits over the first plot.
    above = searchable(page, {"Figure 1": [hit(30.0)], "Figure 2": [hit(330.0)]})
    placed = figures.match_frames(above, [first, second], ["Figure 1", "Figure 2"])
    assert placed == {"Figure 1": first, "Figure 2": second}

    def no_search(label, regex=False):
        raise ValueError("this page cannot be searched")

    page.search = no_search
    assert figures.match_frames(page, [first, second], ["Figure 1"]) == {}


def test_a_legend_box_that_cuts_grid_lines_short_does_not_make_a_second_plot_area() -> None:
    plot = Plot(x=(0.0, 1.0, False), y=(0.0, 1.0, False))
    lines = plot.grid()
    # The legend covers the top-right corner: the lines through it stop at its edge, and their
    # far pieces are drawn again beyond it, as two shorter sets of lines.
    for line in lines:
        upright = line["x0"] == line["x1"]
        if upright and line["x0"] > 300.0:
            line["top"] = 110.0
        elif not upright and line["top"] < 110.0:
            line["x1"] = 310.0
    (frame,) = figures.find_frames(SimpleNamespace(lines=lines, curves=[]))
    assert (frame.x0, frame.x1, frame.top, frame.bottom) == (100.0, 400.0, 50.0, 250.0)
    # The lines the legend cut short are not counted as grid: seven uprights run the whole
    # height (100 to 280 pt) and eight levels the whole width (110 to 250 pt).
    assert frame.grid_x == tuple(100.0 + 30.0 * k for k in range(7))
    assert frame.grid_y == tuple(110.0 + 20.0 * k for k in range(8))


def picture_page():
    """A page holding one figure as a picture, 900 by 640 pixels at 300 dpi, placed at (36, 72)."""
    width, height = 900, 640
    left, right, top, bottom = 120, 860, 30, 560
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    for k in range(11):
        x = left + k / 10 * (right - left)
        y = top + k / 10 * (bottom - top)
        draw.line([(x, top), (x, bottom)], fill=0, width=2)
        draw.line([(left, y), (right, y)], fill=0, width=2)
    xs = np.linspace(left, right, 400)
    shape = lambda f: bottom - 60 - 380 * f
    draw.line(list(zip(xs, shape((xs - left) / (right - left)), strict=True)), fill=0, width=6)
    scale = 72.0 / raster.RESOLUTION
    placed = {"x0": 36.0, "top": 72.0, "x1": 36.0 + width * scale, "bottom": 72.0 + height * scale}
    rendering = SimpleNamespace(to_image=lambda resolution: SimpleNamespace(original=image))
    page = SimpleNamespace(lines=[], curves=[], images=[placed], width=595.0, height=842.0, crop=lambda box: rendering)
    edges = (36.0 + left * scale, 36.0 + right * scale, 72.0 + top * scale, 72.0 + bottom * scale)
    return page, edges, scale, lambda f: 72.0 + shape(f) * scale


def test_a_figure_stored_as_a_picture_gives_a_plot_area_and_its_curve() -> None:
    page, (x0, x1, top, bottom), scale, drawn = picture_page()
    (frame,) = figures.find_frames(page)
    assert frame.raster is not None and frame.grid_width == scale
    assert (frame.x0, frame.x1) == pytest.approx((x0, x1), abs=0.3)
    assert (frame.top, frame.bottom) == pytest.approx((top, bottom), abs=0.3)
    assert len(frame.grid_x) == 11 and len(frame.grid_y) == 11
    ((colour, curve),) = figures.coloured_curves_in(page, frame)
    assert colour is None
    share = (curve[:, 0] - x0) / (x1 - x0)
    assert np.abs(curve[:, 1] - drawn(share)).max() < 7 * scale  # about the stroke's own width
    # A picture where drawing commands already gave a plot area is not read a second time.
    assert raster.plots_on(page, [(x0, x1, top, bottom)], figures.MIN_FRAME_SIZE) == []
    assert raster.plots_on(page, [], 1000.0) == []


def test_a_label_printed_over_a_curve_in_a_picture_does_not_break_it_in_two() -> None:
    width, height = 900, 640
    left, right, top, bottom = 120, 860, 30, 560
    image = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(image)
    for k in range(11):
        x = left + k / 10 * (right - left)
        y = top + k / 10 * (bottom - top)
        draw.line([(x, top), (x, bottom)], fill=0, width=2)
        draw.line([(left, y), (right, y)], fill=0, width=2)
    xs = np.linspace(left, right, 400)
    shape = lambda f: bottom - 60 - 380 * f
    draw.line(list(zip(xs, shape((xs - left) / (right - left)), strict=True)), fill=0, width=6)
    # The label's white box, between two grid lines, hides 30 pixels of the curve.
    draw.rectangle([430, top + 3, 460, bottom - 3], fill=255)
    for k in range(11):
        y = top + k / 10 * (bottom - top)
        draw.line([(left, y), (right, y)], fill=0, width=2)
    plot = raster.find_plot(np.asarray(image) < 128, 0.0, 0.0, 1.0)
    assert plot is not None
    (curve,) = raster.trace(plot)
    assert np.ptp(curve[:, 0]) > 0.97 * (right - left)
    assert not np.any((curve[:, 0] > 432) & (curve[:, 0] < 458))  # nothing is invented under the label
    assert np.abs(curve[:, 1] - shape((curve[:, 0] - left) / (right - left))).max() < 7


# ---- curves that share no current ----

OUTPUT = Plot(x=(0.0, 5.0, False), y=(0.0, 150.0, False))  # V, A


def test_two_curves_that_share_no_current_and_tie_on_the_tables_are_set_aside_not_a_crash() -> None:
    """One curve drawn up to 50 A and the other from 60 A: the one tabulated current speaks
    to the first alone, whichever temperature it is given, and there is no current at which
    the two can be put in order."""
    volts = lambda i: 0.8 + 0.02 * np.asarray(i)
    low, high = np.linspace(1.0, 50.0, 40), np.linspace(60.0, 130.0, 40)
    page = OUTPUT.page(OUTPUT.curve(volts(low), low), OUTPUT.curve(volts(high) + 0.3, high))
    (frame,) = figures.find_frames(page)
    series = [ReadSeries(name="switch_voltage", tj_c=25), ReadSeries(name="switch_voltage", tj_c=175)]
    tables = [
        tabulated(Quantity.vce_sat, float(volts(40.0)), current=40.0, tj=25.0),
        tabulated(Quantity.vce_sat, float(volts(40.0)), current=40.0, tj=175.0),
    ]
    kind = figure(FigureKind.output_characteristic)
    (aside,) = digitise_family(page, frame, kind, OUTPUT.claim("V", "A", series), tables)
    assert aside.status is ReviewStatus.flagged and aside.x == []
    assert aside.flags == [
        "several assignments of curves fit the tables about equally well, and the "
        "temperature ordering does not settle it"
    ]
