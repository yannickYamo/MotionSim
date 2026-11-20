"""How well a reading of a made-up datasheet matches the part it was written from.

Four things are measured, each against the part itself and never against another reading:

- table values: is each printed value there, in SI units, with its conditions and page;
- flags: of the values the reader got wrong, how many were flagged; of the ones it got
  right, how many were left alone;
- figures: was each plot area found where it was drawn, and how far each digitised curve
  is from the curve that was drawn;
- the result: the loss and junction temperature at one operating point from the device
  built off the reading, against the device built off the part's own figures.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from evals.reader import replay, sheets
from motionsim.device.schema import ReviewStatus
from motionsim.observe import provider
from motionsim.observe.schema import AxisClaim, CurveObservation, Document, Observation, ObservationSet, ReadFigure

SAME = 1e-6  # relative; a printed value converted to SI either is the part's or is not
CURVE_WRONG = 0.10  # relative; a curve further than this from the one drawn is a wrong curve
FRAME = 1.0  # pt; a plot area is found if each edge is this close to where it was drawn


def _same(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return math.isclose(a, b, rel_tol=SAME, abs_tol=1e-30)


def _is_row(o: Observation, row: sheets.Row, page: int) -> bool:
    return (
        o.quantity.value == row.quantity
        and o.page == page
        and _same(o.typ, row.si(row.typ))
        and _same(o.max, row.si(row.max))
        and _same(o.min, row.si(row.min))
        and _same(o.tj_c, row.tj_c)
        and _same(o.current_a, row.current_a)
        and _same(o.voltage_v, row.voltage_v)
    )


def table_score(sheet: sheets.Sheet, layout: sheets.Layout, obs: ObservationSet) -> dict:
    """Of the part's table values, how many were read exactly and left unflagged; and of
    what the reader reported, how the flags fell on the right values and the wrong ones."""
    rows = [(row, layout.row_page[n]) for n, row in enumerate(sheet.rows)]
    read = sum(any(_is_row(o, row, page) and not o.flags for o in obs.observations) for row, page in rows)
    right = [o for o in obs.observations if any(_is_row(o, row, page) for row, page in rows)]
    wrong = [o for o in obs.observations if o not in right]
    # The kind of transistor is read as a table value is, and counted as one.
    kind_right = obs.technology == sheet.technology
    return {
        "values": len(rows),
        "values_read": read,
        "right": len(right) + kind_right,
        "right_flagged": sum(bool(o.flags) for o in right) + (kind_right and bool(obs.flags)),
        "wrong": len(wrong) + (not kind_right),
        "wrong_flagged": sum(bool(o.flags) for o in wrong) + (not kind_right and bool(obs.flags)),
        "missed": [
            f"{o.quantity.value} at {o.tj_c} °C reported as {o.printed_typ} {o.unit}" for o in wrong if not o.flags
        ]
        + ([f"kind of transistor reported as {obs.technology}"] if not kind_right and not obs.flags else []),
        "false_flags": [f"{o.quantity.value}: {'; '.join(o.flags)}" for o in right if o.flags]
        + (obs.flags if kind_right else []),
        "transcribed": sum(o.evidence is not None and o.evidence.value == "transcript" for o in obs.observations),
    }


def _read_at(curve: CurveObservation, x: np.ndarray, log: bool) -> np.ndarray:
    xs, ys = np.asarray(curve.x, dtype=float), np.asarray(curve.y, dtype=float)
    order = np.argsort(xs)
    xs, ys = xs[order], ys[order]
    return np.interp(np.log(x), np.log(xs), ys) if log else np.interp(x, xs, ys)


def curve_error(figure: sheets.Figure, truth: sheets.Curve, read: CurveObservation) -> tuple[float, float]:
    """Largest and root-mean-square relative distance of a digitised curve from the drawn
    one, over the stretch both cover. Relative to the true value, or to a fiftieth of the
    curve's span where the true value is near zero."""
    lo, hi = max(truth.domain[0], min(read.x)), min(truth.domain[1], max(read.x))
    log = (figure.y if figure.swapped else figure.x)[2]
    x = np.geomspace(lo, hi, 60) if log else np.linspace(lo, hi, 60)
    true = np.asarray(truth.truth(x), dtype=float)
    floor = 0.02 * float(np.ptp(np.asarray(truth.truth(np.linspace(*truth.domain, 50)), dtype=float)))
    error = np.abs(_read_at(read, x, log) - true) / np.maximum(np.abs(true), floor)
    return float(error.max()), float(np.sqrt((error**2).mean()))


def curve_score(sheet: sheets.Sheet, obs: ObservationSet) -> dict:
    """Each curve the part's figures draw: read right, set aside, or read wrong in silence."""
    out: dict = {"drawn": 0, "read": 0, "set_aside": 0, "silently_wrong": 0, "worst": 0.0, "rms": [], "detail": []}
    for figure in sheet.figures:
        for truth in figure.curves if figure.drawn else ():
            out["drawn"] += 1
            found = [
                c
                for c in obs.curves
                if c.label == figure.label and c.quantity.value == truth.quantity and c.tj_c == truth.tj_c
            ]
            usable = [c for c in found if not c.flags and len(c.x) >= 2]
            if not usable:
                out["set_aside"] += 1
                why = "; ".join(f for c in obs.curves if c.label == figure.label for f in c.flags) or "not digitised"
                out["detail"].append(f"{figure.label} {truth.quantity}: set aside ({why})")
                continue
            worst, rms = curve_error(figure, truth, usable[0])
            if worst > CURVE_WRONG:
                out["silently_wrong"] += 1
                out["detail"].append(f"{figure.label} {truth.quantity}: off by {worst:.0%} and not flagged")
                continue
            out["read"] += 1
            out["worst"] = max(out["worst"], worst)
            out["rms"].append(rms)
    return out


def frame_score(pdf_bytes: bytes, layout: sheets.Layout) -> dict:
    """Plot areas found against plot areas drawn. No model is involved: this is geometry."""
    import pdfplumber

    from motionsim.observe import figures

    drawn, found, extra, offset = 0, 0, 0, 0.0
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as document:
        for number in sorted(set(layout.figure_page.values())):
            boxes = [box for label, box in layout.frames.items() if layout.figure_page[label] == number]
            frames = [(f.x0, f.top, f.x1, f.bottom) for f in figures.find_frames(document.pages[number - 1])]
            drawn += len(boxes)
            matched = 0
            for box in boxes:
                gaps = [max(abs(a - b) for a, b in zip(box, frame, strict=True)) for frame in frames]
                if gaps and min(gaps) <= FRAME:
                    matched += 1
                    offset = max(offset, min(gaps))
            found += matched
            extra += len(frames) - matched
    return {"drawn": drawn, "found": found, "extra": extra, "worst_offset_pt": offset}


def true_observations(sheet: sheets.Sheet, layout: sheets.Layout) -> ObservationSet:
    """The reading that makes no mistake and digitises without error: the part's own table
    values and its own curves, sampled. The device built from it is the true device."""
    observations = [
        Observation(
            quantity=row.quantity,
            typ=row.si(row.typ),
            max=row.si(row.max),
            min=row.si(row.min),
            printed_typ=row.typ,
            printed_max=row.max,
            printed_min=row.min,
            unit=row.unit,
            current_a=row.current_a,
            voltage_v=row.voltage_v,
            tj_c=row.tj_c,
            page=layout.row_page[n],
            status=ReviewStatus.unverified,
            flags=[],
        )
        for n, row in enumerate(sheet.rows)
    ]
    curves = []
    for figure in sheet.figures:
        for truth in figure.curves if figure.drawn else ():
            log = (figure.y if figure.swapped else figure.x)[2]
            x = np.geomspace(*truth.domain, 120) if log else np.linspace(*truth.domain, 120)
            curves.append(
                CurveObservation(
                    quantity=truth.quantity,
                    page=layout.figure_page[figure.label],
                    label=figure.label,
                    tj_c=truth.tj_c,
                    x=x.tolist(),
                    y=np.asarray(truth.truth(x), dtype=float).tolist(),
                    x_axis=AxisClaim(lo=figure.x[0], hi=figure.x[1], log=figure.x[2]),
                    y_axis=AxisClaim(lo=figure.y[0], hi=figure.y[1], log=figure.y[2]),
                    test_voltage_v=figure.test_voltage_v,
                    anchor_error=0.0,
                    method="vector",
                    status=ReviewStatus.unverified,
                    flags=[],
                )
            )
    return ObservationSet(
        document=Document(file=f"{sheet.name}.pdf", sha256="0" * 64, pages=len(layout.pages)),
        reader="the part itself",
        vendor=sheets.VENDOR,
        part_number=sheet.part_number,
        technology=sheet.technology,
        topology=sheet.topology,
        integrated_driver=sheet.integrated_driver,
        outline=None,
        observations=observations,
        figures=[
            ReadFigure(page=layout.figure_page[f.label], label=f.label, shows=f.title, kind=f.kind)
            for f in sheet.figures
        ],
        curves=curves,
    )


def _solved(obs: ObservationSet, reference: dict) -> tuple[float, float]:
    from motionsim.engine import OperatingPoint, solve
    from motionsim.fit import build_device

    point = OperatingPoint(
        v_dc=reference["vdc"],
        i_rms=reference["i_rms"],
        modulation_index=0.9,
        power_factor=0.85,
        f_sw=reference["f_sw"],
        t_sink=80.0,
        **reference.get("drive", {}),
    )
    result = solve(build_device(obs), point)
    return float(result.p_inverter), float(max(result.tj_switch, result.tj_diode))


def result_score(sheet: sheets.Sheet, layout: sheets.Layout, obs: ObservationSet) -> dict:
    """Loss and junction temperature from the reading against the true device's, at the
    sheet's reference operating point (heatsink at 80 °C)."""
    true_loss, true_tj = _solved(true_observations(sheet, layout), sheet.reference)
    try:
        loss, tj = _solved(obs, sheet.reference)
    except Exception as failed:  # no device, or no solution: the reading did not get there
        return {"built": False, "why": provider.plain(failed), "true_loss_w": true_loss, "true_tj_c": true_tj}
    return {
        "built": True,
        "loss_w": loss,
        "true_loss_w": true_loss,
        "loss_error": abs(loss - true_loss) / true_loss,
        "tj_c": tj,
        "true_tj_c": true_tj,
        "rise_error": abs((tj - 80.0) - (true_tj - 80.0)) / (true_tj - 80.0),
    }


@dataclass
class Played:
    """One recording played through the reader."""

    sheet: str
    recording: str
    refused: str | None = None  # the reader stopped with this line, reading nothing
    plan: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    cost: str = ""
    tables: dict = field(default_factory=dict)
    curves: dict = field(default_factory=dict)
    result: dict = field(default_factory=dict)
    summary: list[str] = field(default_factory=list)


def play(
    sheet: sheets.Sheet,
    layout: sheets.Layout,
    pdf_path: Path,
    name: str,
    recording: dict,
    *,
    client=None,
    chat: replay.ChatService | None = None,
) -> Played:
    """Read `pdf_path` with a recording standing in for the model (or with `client`, live),
    and score what came out against the part. With `chat`, the recording answers through a
    chat-completions service on this machine, the reader's other path."""
    from motionsim.observe import run

    played = Played(sheet.name, name)
    asked = client or replay.ReplayClient(pdf_path, recording)
    if chat is not None:
        chat.client = asked
    try:
        reading = run.read_datasheet(
            pdf_path,
            pdf_path.with_suffix(".observations.yaml"),
            client=None if chat is not None else asked,
            say=played.plan.append,
        )
    except provider.ReaderFailed as refused:
        played.refused = str(refused)
        played.calls = list(getattr(asked, "asked", []))
        return played
    obs = reading.observations
    played.calls = list(getattr(asked, "asked", []))
    played.cost, played.summary = reading.ledger.summary(), reading.summary()
    played.tables = table_score(sheet, layout, obs)
    played.curves = curve_score(sheet, obs)
    played.result = result_score(sheet, layout, obs) if name == "faithful" or client is not None else {}
    return played
