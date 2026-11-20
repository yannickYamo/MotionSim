"""Every figure of a datasheet that the reader located, digitised into curves.

Shared by the command line and the local page, which both read datasheets; kept here, with
the rest of the reader, so that neither has to borrow it from the other.

What the reader said of the figures is not trusted to be possible: a figure cited on a page
the file does not have, axes no curve can be read against, a model call that fails half-way.
Each ends as a curve that is empty and flagged with the reason, beside the curves that were
read, and never as an error that throws away the pages already paid for.
"""

from __future__ import annotations

from collections.abc import Callable

from motionsim.device.schema import ReviewStatus
from motionsim.observe import provider
from motionsim.observe.schema import (
    AxisClaim,
    CurveObservation,
    FigureKind,
    ObservationSet,
    Quantity,
    ReadAxes,
    ReadFigure,
)

# The quantity an empty, flagged curve is filed under when its figure could not be read.
_FILED_AS = {
    FigureKind.output_characteristic: Quantity.vce_curve,
    FigureKind.diode_forward: Quantity.vf_curve,
    FigureKind.switching_energy_vs_current: Quantity.e_on_curve,
    FigureKind.switching_energy_vs_gate_resistance: Quantity.e_on_rg_curve,
    FigureKind.switching_energy_vs_voltage: Quantity.e_on_v_curve,
    FigureKind.thermal_impedance_switch: Quantity.zth_jc_switch,
    FigureKind.thermal_impedance_diode: Quantity.zth_jc_diode,
    FigureKind.normalized_on_resistance: Quantity.rds_norm_curve,
    FigureKind.gate_charge: Quantity.gate_charge_curve,
    FigureKind.capacitance: Quantity.c_oss_curve,
}
_NO_AXIS = AxisClaim(lo=0.0, hi=0.0, log=False)
ROW = 6.0  # pt; plots whose tops and bottoms agree this closely stand in one row


def set_aside(figure: ReadFigure, reason: str, axes: ReadAxes | None = None) -> CurveObservation:
    """What stands for a figure that could not be read: an empty curve carrying the reason."""
    return CurveObservation(
        quantity=_FILED_AS.get(figure.kind, Quantity.vce_curve),
        page=figure.page,
        label=figure.label,
        x=[],
        y=[],
        x_axis=axes.x if axes else _NO_AXIS,
        y_axis=axes.y if axes else _NO_AXIS,
        method="vector",
        status=ReviewStatus.flagged,
        flags=[reason],
    )


def _wanted(figure: ReadFigure, fet: bool) -> bool:
    """Whether a figure is of a kind that is digitised for this technology."""
    from motionsim.observe.charge import is_capacitance, is_gate_charge
    from motionsim.observe.family import is_family, is_gate_resistance, is_normalised_resistance, is_voltage
    from motionsim.observe.thermal import is_thermal

    return (
        is_thermal(figure)
        or is_family(figure)
        or is_normalised_resistance(figure)
        or is_gate_resistance(figure)
        or is_voltage(figure)
        # gate-charge and capacitance figures feed only the FET model
        or (fet and (is_gate_charge(figure) or is_capacitance(figure)))
    )


def _split_rows(wanted: list[ReadFigure], frames: list, by_caption: dict) -> None:
    """One caption over a row of plots (the same figure at two temperatures, say): each
    plot the caption did not claim is read as a part of that figure. Changes `wanted` and
    `by_caption` in place."""
    from motionsim.observe.family import is_family

    claimed = {id(frame) for frame in by_caption.values()}
    for figure in list(wanted):
        first = by_caption.get(figure.label)
        if first is None or not is_family(figure):
            continue
        row = [
            f
            for f in frames
            if id(f) not in claimed and abs(f.top - first.top) < ROW and abs(f.bottom - first.bottom) < ROW
        ]
        if not row:
            continue
        parts = sorted([first] + row, key=lambda f: f.x0)
        wanted.remove(figure)
        del by_caption[figure.label]
        for k, frame in enumerate(parts, start=1):
            part = figure.model_copy(update={"label": f"{figure.label} (plot {k} of {len(parts)}, left to right)"})
            wanted.append(part)
            by_caption[part.label] = frame
            claimed.add(id(frame))


def _located(page, listed: list[ReadFigure], wanted: list[ReadFigure]) -> tuple[list[ReadFigure], dict]:
    """The wanted figures whose plot areas were found on the page, and the area of each."""
    from motionsim.observe import figures

    frames = figures.find_frames(page)
    by_caption = figures.match_frames(page, frames, [f.label for f in listed])
    if len(by_caption) < len(listed) and len(frames) == len(listed):
        # Captions not found as printed: fall back to reading order.
        by_caption = {f.label: frame for f, frame in zip(listed, frames, strict=True)}
    wanted = list(wanted)
    _split_rows(wanted, frames, by_caption)
    return wanted, by_caption


def _curves_of(page, frame, figure: ReadFigure, claim: ReadAxes, observations: list) -> list[CurveObservation]:
    """One figure, read by the reader of its kind."""
    from motionsim.observe.charge import digitise_capacitance, digitise_gate_charge, is_capacitance, is_gate_charge
    from motionsim.observe.family import (
        digitise_family,
        digitise_gate_resistance,
        digitise_normalised_resistance,
        digitise_voltage,
        is_gate_resistance,
        is_normalised_resistance,
        is_voltage,
    )
    from motionsim.observe.thermal import digitise_thermal, is_thermal

    if is_normalised_resistance(figure):
        new = [digitise_normalised_resistance(page, frame, figure, claim)]
    elif is_gate_resistance(figure):
        new = digitise_gate_resistance(page, frame, figure, claim, observations)
    elif is_voltage(figure):
        new = digitise_voltage(page, frame, figure, claim, observations)
    elif is_thermal(figure):
        new = [digitise_thermal(page, frame, figure, claim, observations)]
    elif is_gate_charge(figure):
        new = [digitise_gate_charge(page, frame, figure, claim, observations)]
    elif is_capacitance(figure):
        new = [digitise_capacitance(page, frame, figure, claim, observations)]
    else:
        new = digitise_family(page, frame, figure, claim, observations)
    if frame.raster is not None:
        for curve in new:
            curve.method = "picture"
    return new


def _read_safely(page, frame, figure: ReadFigure, claim: ReadAxes, observations: list) -> list[CurveObservation]:
    """One figure read, or set aside with the reason where what the reader claimed of its
    axes cannot be worked with at all (an axis from 5 to 5, a logarithmic one from zero).

    Arithmetic on such axes gives infinities and empty means, which numpy reports as
    warnings. They are not let out as such: a curve that came out with a sample that is not
    a finite number is flagged, which says the same thing where a person will see it.
    """
    import math
    import warnings

    import numpy as np

    try:
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            curves = _curves_of(page, frame, figure, claim, observations)
    except (ArithmeticError, ValueError, IndexError, KeyError, TypeError) as wrong:
        reason = provider.plain(wrong) or type(wrong).__name__
        return [set_aside(figure, f"could not be read against the axes the reader gave: {reason}", claim)]
    for curve in curves:
        if not all(math.isfinite(value) for value in (*curve.x, *curve.y)):
            curve.flags.append("not every point of this curve is a finite number: check the axes the reader gave")
            curve.status = ReviewStatus.flagged
    return curves


class _Asker:
    """Asks for the axes of a page's figures until one question fails. After that nothing
    more is asked: a key that was rejected or a budget used up fails the same way each time."""

    def __init__(self, ask: Callable, pdf_path: str, ledger, client) -> None:
        self.ask, self.pdf_path, self.ledger, self.client = ask, pdf_path, ledger, client
        self.stopped: str | None = None

    def axes(self, number: int, labels: list[str]) -> dict[str, ReadAxes] | None:
        from motionsim.observe.ingest import render_page

        if self.stopped is None:
            try:
                claims = self.ask(render_page(self.pdf_path, number), labels, self.client, ledger=self.ledger)
                return {claim.label: claim for claim in claims.figures}
            except provider.ReaderFailed as failed:
                self.stopped = str(failed)
        return None


def _page_curves(pdf, number: int, listed: list[ReadFigure], obs: ObservationSet, asker: _Asker) -> list:
    """The curves of one page's figures, each read or set aside with why."""
    fet = obs.technology != "Si IGBT"
    wanted = [f for f in listed if _wanted(f, fet)]
    if not wanted:
        return []
    if not 1 <= number <= len(pdf.pages):
        return [set_aside(f, f"page {number} does not exist: the file has {len(pdf.pages)} pages") for f in wanted]
    page = pdf.pages[number - 1]
    wanted, by_caption = _located(page, listed, wanted)
    located = [f for f in wanted if f.label in by_caption]
    # A figure that cannot be read is kept as one set aside with why, never left out: what
    # was not read is said beside what was.
    curves: list = [set_aside(f, f"no plot area was found for it on page {number}") for f in wanted if f not in located]
    if not located:
        return curves
    claims = asker.axes(number, [f.label for f in located])
    if claims is None:
        return curves + [set_aside(f, f"its axes were not read: {asker.stopped}") for f in located]
    for figure in located:
        if figure.label not in claims:
            curves.append(set_aside(figure, "the reader gave no axes for it"))
            continue
        curves.extend(_read_safely(page, by_caption[figure.label], figure, claims[figure.label], obs.observations))
    return curves


def digitise_curves(pdf_path: str, obs, *, ledger: provider.Ledger | None = None, client=None, ask=None) -> list:
    """Curves from every page the reader said has usable figures.

    One model call a page, entered in `ledger`. `client` is an Anthropic client to use in
    place of a new one; `ask` stands in for the call itself (`reader.read_axes`).
    """
    from motionsim.observe.reader import read_axes

    pdfplumber = provider.needs("pdfplumber", "reading a PDF")
    by_page: dict[int, list] = {}
    for figure in obs.figures:
        by_page.setdefault(figure.page, []).append(figure)
    asker = _Asker(ask or read_axes, str(pdf_path), ledger, client)
    curves: list = []
    with pdfplumber.open(pdf_path) as pdf:
        for number, listed in sorted(by_page.items()):
            curves.extend(_page_curves(pdf, number, listed, obs, asker))
    _rows_held_to_curves(obs, curves)
    return curves


def _decades_off(ratio: float) -> bool:
    """Whether a ratio is a whole power of ten other than one, within the plateau's tolerance."""
    import math

    if ratio <= 0:
        return False
    decades = math.log10(ratio)
    return round(decades) != 0 and abs(decades - round(decades)) <= math.log10(1.15)


_TABLE_OF = {Quantity.zth_jc_switch: Quantity.rth_jc_switch, Quantity.zth_jc_diode: Quantity.rth_jc_diode}


def _rows_held_to_curves(obs: ObservationSet, curves: list[CurveObservation]) -> None:
    """A junction-to-case figure whose own impedance curve ends elsewhere is flagged with
    the curve: one of the two is wrong, and the page cannot say which. Either alone would
    give a device that quietly rests on the other. Changes obs.observations in place."""
    for curve in curves:
        table = _TABLE_OF.get(curve.quantity)
        if table is None or not curve.y or not any("disagrees with the tabulated" in f for f in curve.flags):
            continue
        end = curve.y[-1]
        mine = [o.typ for o in obs.observations if o.quantity is table and o.typ]
        if mine and _decades_off(end / mine[0]):
            continue  # a whole decade or more out: the axis was misread, which the curve says
        other = Quantity.rth_jc_diode if table is Quantity.rth_jc_switch else Quantity.rth_jc_switch
        theirs = [o.typ for o in obs.observations if o.quantity is other and o.typ]
        swapped = any(abs(end / v - 1) <= 0.15 for v in theirs)
        why = f"disagrees with the end of its thermal impedance curve ({curve.label}, {end:.3g} K/W)" + (
            ", which is the other chip's figure: the two may be exchanged" if swapped else ""
        )
        for k, o in enumerate(obs.observations):
            if o.quantity is table:
                obs.observations[k] = o.model_copy(update={"flags": [*o.flags, why], "status": ReviewStatus.flagged})
