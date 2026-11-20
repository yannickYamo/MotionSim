"""Answers that fit the schema and are nonsense: pages that do not exist, numbers that are
not numbers, axes from nothing to nothing, temperatures of infinity. Whatever a model says
within the form asked for, the reader's checks end in flags on what it said, never in a
crash. (An answer outside the form is refused as such: see test_reader_anthropic.)"""

from __future__ import annotations

import math

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from evals.reader import recordings, sheets
from motionsim import observe
from motionsim.device import Topology
from motionsim.device.schema import ReviewStatus
from motionsim.observe import digitise
from motionsim.observe.schema import (
    TABLE_QUANTITIES,
    AxisClaim,
    Document,
    FigureKind,
    ReadAxes,
    ReadFigure,
    ReadPageAxes,
    ReadPoint,
    ReadResult,
    ReadSeries,
)
from motionsim.observe.verify import check, recheck, summary

PAGE = (
    "Drain-source on-state resistance RDS(on) VGS = 10 V, ID = 30 A, Tj = 25 °C - 8.00 9.60 mΩ\n"
    "Gate-source charge Qgs VDS = 50 V, ID = 30 A - 12 - nC\n"
    "Collector-emitter saturation voltage VCE(sat) IC = 7.5 A, Tj = 150 °C - 1.7 - V\n"
)

number = st.one_of(
    st.none(),
    st.floats(allow_nan=True, allow_infinity=True),
    st.sampled_from([0.0, -1.0, 25.0, 150.0, 30.0, 7.5, 1e308, -1e308, 5e-324]),
)
printed = st.one_of(
    st.none(),
    st.sampled_from(
        ["8.00", "9.60", "12", "1.7", "", "-", "±15", "-40 ~ 150", "1e999", "nan", "inf", "8,00", "٣", "0x10", "1/0"]
    ),
    st.text(max_size=12),
)
unit = st.one_of(
    st.sampled_from(["mΩ", "Ω", "nC", "µC", "V", "A", "°C", "K/W", "mJ", "", "furlongs"]), st.text(max_size=5)
)
page = st.one_of(st.integers(min_value=-(2**40), max_value=2**40), st.sampled_from([0, 1, 2, 3, 99]))
points = st.builds(
    ReadPoint,
    quantity=st.sampled_from(sorted(TABLE_QUANTITIES, key=lambda q: q.value)),
    printed_typ=printed,
    printed_max=printed,
    printed_min=printed,
    unit=unit,
    current_a=number,
    voltage_v=number,
    tj_c=number,
    page=page,
)
figure_claims = st.builds(
    ReadFigure,
    page=page,
    label=st.text(max_size=12),
    shows=st.text(max_size=20),
    kind=st.sampled_from(list(FigureKind)),
)
results = st.builds(
    ReadResult,
    vendor=st.text(max_size=10),
    part_number=st.text(max_size=10),
    technology=st.sampled_from(["Si IGBT", "Si MOSFET", "SiC MOSFET", "GaN HEMT"]),
    topology=st.sampled_from(list(Topology)),
    integrated_driver=st.booleans(),
    points=st.lists(points, max_size=6),
    figures=st.lists(figure_claims, max_size=3),
)


@settings(max_examples=300, deadline=None)
@given(result=results, transcribed=st.booleans())
def test_no_answer_within_the_form_breaks_the_checks(result: ReadResult, transcribed: bool) -> None:
    document = Document(file="x.pdf", sha256="0" * 64, pages=2, transcribed={1: PAGE} if transcribed else {})
    obs = check(result, document, [PAGE, ""], reader="fuzz")
    assert len(obs.observations) == len(result.points)
    for point, read in zip(result.points, obs.observations, strict=True):
        assert read.status in (ReviewStatus.unverified, ReviewStatus.flagged)
        assert (read.status is ReviewStatus.flagged) == bool(read.flags)
        if not 1 <= point.page <= 2:
            assert any("does not exist" in flag for flag in read.flags)
        for value in (read.typ, read.max, read.min):
            if value is not None and not math.isfinite(value):
                assert read.flags  # a figure that is not a finite number never passes
    assert summary(obs)[0].endswith("flagged")
    again = recheck(obs, [PAGE, ""])
    assert [o.status for o in again.observations] == [o.status for o in obs.observations]


@settings(max_examples=60, deadline=None)
@given(result=results)
def test_what_the_checks_make_of_any_answer_can_be_saved_and_read_back(result: ReadResult, tmp_path_factory) -> None:
    obs = check(result, Document(file="x.pdf", sha256="0" * 64, pages=1), [PAGE], reader="fuzz")
    path = tmp_path_factory.mktemp("fuzz") / "obs.yaml"
    observe.save_observations(obs, path)
    assert len(observe.load_observations(path).observations) == len(obs.observations)


@pytest.fixture(scope="module")
def igbt(tmp_path_factory):
    sheet = sheets.labelled_set()[0]
    data, layout = sheets.build(sheet)
    path = tmp_path_factory.mktemp("fuzz") / "igbt.pdf"
    path.write_bytes(data)
    faithful = ReadResult.model_validate(recordings.faithful(sheet, layout)["tables"])
    return path, check(faithful, Document(file="igbt.pdf", sha256="0" * 64, pages=4), [""] * 4, reader="fuzz")


edge = st.one_of(
    st.floats(allow_nan=True, allow_infinity=True), st.sampled_from([0.0, 1.0, -1.0, 4.0, 80.0, 1e-5, 1e308])
)
axis = st.builds(AxisClaim, lo=edge, hi=edge, log=st.booleans())
series = st.builds(
    ReadSeries,
    name=st.sampled_from(["switch_voltage", "diode_voltage", "e_on", "e_off", "e_rr", "other"]),
    tj_c=number,
    colour=st.sampled_from([None, "black", "red", "blue", "purple"]),
)
claims = st.builds(
    ReadAxes,
    label=st.sampled_from(["Figure 1", "Figure 2", "Figure 3", "Figure 4", "Figure 9", ""]),
    x=axis,
    y=axis,
    x_unit=unit,
    y_unit=unit,
    series=st.lists(series, max_size=4),
    test_voltage_v=number,
    test_current_a=number,
)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    answers=st.lists(st.lists(claims, max_size=3), min_size=2, max_size=2),
    kinds=st.lists(st.sampled_from(list(FigureKind)), min_size=4, max_size=4),
)
def test_no_axes_within_the_form_break_the_digitiser(igbt, answers, kinds) -> None:
    """Real plots, and any claim at all about their axes and about what each figure is."""
    path, obs = igbt
    obs = obs.model_copy(
        update={"figures": [f.model_copy(update={"kind": kind}) for f, kind in zip(obs.figures, kinds, strict=True)]}
    )
    waiting = iter(answers)
    curves = digitise.digitise_curves(str(path), obs, ask=lambda *a, **k: ReadPageAxes(figures=next(waiting)))
    for curve in curves:
        assert len(curve.x) == len(curve.y)
        assert curve.flags or all(math.isfinite(v) for v in [*curve.x, *curve.y])
        assert (curve.status is ReviewStatus.flagged) == bool(curve.flags) or curve.status is ReviewStatus.unverified
