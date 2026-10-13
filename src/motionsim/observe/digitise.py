"""Every figure of a datasheet that the reader located, digitised into curves.

Shared by the command line and the local page, which both read datasheets; kept here, with
the rest of the reader, so that neither has to borrow it from the other.
"""

from __future__ import annotations

import sys


def digitise_curves(pdf_path: str, obs) -> list:
    """Curves from every page the reader said has usable figures."""
    import pdfplumber

    from motionsim.observe import figures
    from motionsim.observe.charge import (
        digitise_capacitance,
        digitise_gate_charge,
        is_capacitance,
        is_gate_charge,
    )
    from motionsim.observe.family import (
        digitise_family,
        digitise_gate_resistance,
        digitise_normalised_resistance,
        digitise_voltage,
        is_family,
        is_gate_resistance,
        is_normalised_resistance,
        is_voltage,
    )
    from motionsim.observe.ingest import render_page
    from motionsim.observe.reader import read_axes
    from motionsim.observe.thermal import digitise_thermal, is_thermal

    curves = []
    fet = obs.technology != "Si IGBT"  # gate-charge and capacitance figures feed only the FET model
    by_page: dict[int, list] = {}
    for fig in obs.figures:
        by_page.setdefault(fig.page, []).append(fig)
    with pdfplumber.open(pdf_path) as pdf:
        for number, listed in sorted(by_page.items()):
            wanted = [
                f
                for f in listed
                if is_thermal(f)
                or is_family(f)
                or is_normalised_resistance(f)
                or is_gate_resistance(f)
                or is_voltage(f)
                or (fet and (is_gate_charge(f) or is_capacitance(f)))
            ]
            if not wanted:
                continue
            page = pdf.pages[number - 1]
            frames = figures.find_frames(page)
            by_caption = figures.match_frames(page, frames, [f.label for f in listed])
            if len(by_caption) < len(listed) and len(frames) == len(listed):
                # Captions not found as printed: fall back to reading order.
                by_caption = {f.label: frame for f, frame in zip(listed, frames)}
            # One caption over a row of plots (the same figure at two temperatures, say):
            # each plot the caption did not claim is read as a part of that figure.
            claimed = {id(frame) for frame in by_caption.values()}
            for fig in list(wanted):
                first = by_caption.get(fig.label)
                if first is None or not is_family(fig):
                    continue
                row = [
                    f
                    for f in frames
                    if id(f) not in claimed and abs(f.top - first.top) < 6 and abs(f.bottom - first.bottom) < 6
                ]
                if not row:
                    continue
                parts = sorted([first] + row, key=lambda f: f.x0)
                wanted.remove(fig)
                del by_caption[fig.label]
                for k, frame in enumerate(parts, start=1):
                    part = fig.model_copy(update={"label": f"{fig.label} (plot {k} of {len(parts)}, left to right)"})
                    wanted.append(part)
                    by_caption[part.label] = frame
                    claimed.add(id(frame))
            located = [f for f in wanted if f.label in by_caption]
            for fig in wanted:
                if fig not in located:
                    print(f"  page {number}: no plot area found for {fig.label}", file=sys.stderr)
            if not located:
                continue
            claims = read_axes(render_page(pdf_path, number), [f.label for f in located]).figures
            by_label = {c.label: c for c in claims}
            for fig in located:
                frame = by_caption[fig.label]
                if fig.label not in by_label:
                    print(f"  page {number}: no axes reported for {fig.label}", file=sys.stderr)
                    continue
                claim = by_label[fig.label]
                if is_normalised_resistance(fig):
                    new = [digitise_normalised_resistance(page, frame, fig, claim)]
                elif is_gate_resistance(fig):
                    new = digitise_gate_resistance(page, frame, fig, claim, obs.observations)
                elif is_voltage(fig):
                    new = digitise_voltage(page, frame, fig, claim, obs.observations)
                elif is_thermal(fig):
                    new = [digitise_thermal(page, frame, fig, claim, obs.observations)]
                elif is_gate_charge(fig):
                    new = [digitise_gate_charge(page, frame, fig, claim, obs.observations)]
                elif is_capacitance(fig):
                    new = [digitise_capacitance(page, frame, fig, claim, obs.observations)]
                else:
                    new = digitise_family(page, frame, fig, claim, obs.observations)
                if frame.raster is not None:
                    for curve in new:
                        curve.method = "picture"
                curves.extend(new)
    return curves
