"""The commands that work on files: a datasheet read, a device built or given a
measurement, a model set against a reference, a template written, the page served."""

from __future__ import annotations

import argparse
import contextlib
import sys
import warnings
from collections.abc import Iterator
from pathlib import Path

from motionsim.errors import Refusal
from motionsim.files import write_text


def serve(args: argparse.Namespace) -> int:
    import logging

    from motionsim.server import serve as serve_page

    logging.basicConfig(level=getattr(logging, args.log_level.upper()), format="%(asctime)s %(levelname)s %(message)s")
    try:
        serve_page(port=args.port, folder=args.devices, open_browser=not args.no_browser)
    except OSError as exc:  # the port is taken, or may not be opened
        raise Refusal(
            f"the page cannot be served on port {args.port}: {exc.strerror or exc}", "give another with --port", "port"
        ) from None
    return 0


def agent(args: argparse.Namespace) -> int:
    from motionsim.cli.parser import EXIT_STATUS

    guide = (Path(__file__).parent.parent / "AGENT_GUIDE.md").read_text(encoding="utf-8")
    print(guide.replace("{EXIT_STATUS}", EXIT_STATUS.rstrip()), end="")
    return 0


def examples(args: argparse.Namespace) -> int:
    """The example files that come with the tool, each with where it is."""
    import json

    from motionsim import shipped

    files, place = shipped.listed(), shipped.folder()
    if args.json:
        print(json.dumps({"folder": str(place.resolve()) if place else None, "files": files}, indent=1))
        return 0
    if place is None:
        print("this install has no example files")
        return 0
    print(f"example files, in {place.resolve()}")
    print("any command takes one by its bare name, as in: motionsim cycle synthetic_mosfet_100v_100a.yaml --motor ...")
    for f in files:
        print(f"  {f['kind']:<11}  {f['path']}")
    return 0


def _saved(device, path: str) -> None:
    from motionsim.device import save_device

    try:
        save_device(device, path)
    except OSError as exc:
        raise Refusal(f"cannot write {Path(path).name}: {exc.strerror or type(exc).__name__}") from None


def _reference_table(rows, reference) -> None:
    print(f"{'point':>5} {'quantity':<19}{'model':>9}   {'reference':>8}   {'difference':>10}")
    numbers = {id(p): k for k, p in enumerate(reference.points, start=1)}
    for row in rows:
        unit = "W" if row.quantity.startswith("p_") else "K" if row.quantity.endswith("swing") else "°C"
        shown = f"{row.relative:+.1%}" if unit == "W" else f"{row.difference:+.1f} K"
        print(
            f"{numbers[id(row.point)]:>5} {row.quantity:<19}{row.model:>9.2f} {unit:<2}"
            f"{row.reference:>8.2f} {unit:<2}{shown:>10}"
        )


def _named_device(entry: str):
    """A device as every command takes one: a file, a file of typed figures, or one of the
    made-up parts by its name."""
    from motionsim.cli import asking

    with asking.workspace() as ws:
        return ws.device(asking.device(entry, ws))


def validate(args: argparse.Namespace) -> int:
    from motionsim.reference import compare, load_reference

    device = _named_device(args.device)
    reference = load_reference(args.reference)
    try:
        rows = compare(device, reference)
    except ValueError as exc:  # as compare says of a point it cannot follow
        raise Refusal(f"a reference point cannot be simulated: {exc}", "check the point's figures") from None
    print(f"{device.vendor} {device.part_number} against {reference.name} ({reference.kind})")
    for k, p in enumerate(reference.points, start=1):
        if p.on_time is not None:
            print(
                f"point {k}: on {p.on_time:g} s, off {p.off_time:g} s. Its losses and case temperature "
                "are means over the whole pattern, the pause included"
            )
    _reference_table(rows, reference)
    losses = [abs(r.relative) for r in rows if r.quantity.startswith("p_")]
    temperatures = [abs(r.difference) for r in rows if not r.quantity.startswith("p_")]
    if losses:
        print(f"largest loss difference        {max(losses):.1%}")
    if temperatures:
        print(f"largest temperature difference {max(temperatures):.1f} K")
    support = {r.result.validity.value for r in rows}
    print(f"data support of the model at these points: {', '.join(sorted(support))}")
    return 0


def package(args: argparse.Namespace) -> int:
    import numpy as np

    from motionsim.package import build as construct
    from motionsim.package import summarise

    print(f"{args.template}, {args.irated:g} A switch, on {args.interface}")
    if args.template.endswith("module"):
        print("between chips is over the package's own face; interface is from that face to the heatsink")
    print("junction to heatsink surface, K/W; low and high span plausible constructions")
    print(f"{'':<10}{'switch alone':>14}{'diode alone':>13}{'between chips':>15}{'interface':>11}")
    for variant in ("low", "typical", "high"):
        s = summarise(construct(args.template, args.irated, variant, args.interface, diode=not args.no_diode))
        diode = f"{s.self_diode:13.2f}" if s.self_diode is not None else f"{'-':>13}"
        print(f"{variant:<10}{s.self_switch:14.2f}{diode}{s.coupling:15.3f}{s.interface:11.3f}")
    model = construct(args.template, args.irated, "typical", args.interface, diode=not args.no_diode)
    print(f"heat spreads about {model.stack.spreading_length * 1000:.1f} mm sideways in the copper")
    names = model.chip_names
    if len(names) <= 4:
        print("typical matrix, rise of row chip per watt in column chip:")
        for name, row in zip(names, np.round(model.matrix(), 3), strict=True):
            print(f"  {name:<10}" + "".join(f"{v:9.3f}" for v in row))
    return 0


def template(args: argparse.Namespace) -> int:
    from motionsim.event.layout import TEMPLATE as LAYOUT_TEMPLATE
    from motionsim.fit.typed import TEMPLATE as DEVICE_TEMPLATE
    from motionsim.fit.typed_igbt import TEMPLATE as IGBT_TEMPLATE
    from motionsim.load import LOAD_TEMPLATE, PROFILE_TEMPLATE
    from motionsim.motor import TEMPLATES
    from motionsim.reference import TEMPLATE as REFERENCE_TEMPLATE
    from motionsim.trajectory import example

    text = {
        **TEMPLATES,
        "device": DEVICE_TEMPLATE,
        "igbt": IGBT_TEMPLATE,
        "load": LOAD_TEMPLATE,
        "profile": PROFILE_TEMPLATE,
        "reference": REFERENCE_TEMPLATE,
        "trajectory": example(),
        "layout": LAYOUT_TEMPLATE,
    }[args.kind]
    if args.output:
        write_text(args.output, text, "template")
        print(f"written to {args.output}; edit the values to match yours")
    else:
        print(text, end="")
    return 0


def measure(args: argparse.Namespace) -> int:
    from motionsim.measured import apply_double_pulse, load_double_pulse

    try:
        device = apply_double_pulse(
            _named_device(args.device), load_double_pulse(args.measurement), Path(args.measurement).name
        )
    except Refusal:
        raise
    except ValueError as exc:  # pydantic's refusal of the figures, or the measurement's own
        from motionsim.service.answers import reason_of

        raise Refusal(f"this measurement cannot be used: {reason_of(exc)}", "check the measurement file") from None
    _saved(device, args.output)
    print(f"{device.vendor} {device.part_number}: measured switching energy written to {args.output}")
    return 0


def _flags(obs) -> None:
    for o in (o for o in obs.observations if o.flags):
        for flag in o.flags:
            print(f"    - {o.quantity.value} (page {o.page}): {flag}")


def _print_curves(obs) -> None:
    print(f"  {len(obs.curves)} curves digitised")
    for curve in obs.curves:
        state = "; ".join(curve.flags) if curve.flags else f"{len(curve.x)} points"
        if not curve.flags and curve.anchor_error is not None:
            state += f", within {curve.anchor_error:.1%} of the table"
        at = "" if curve.tj_c is None else f" at {curve.tj_c:g} °C"
        print(f"    - page {curve.page}: {curve.label} ({curve.quantity.value}{at}): {state}")
    done = {(c.page, c.label) for c in obs.curves if not c.flags}
    waiting = [f for f in obs.figures if (f.page, f.label) not in done and f.kind.value != "other"]
    print(f"  {len(waiting)} characteristic curves noticed, not yet digitised")
    for fig in waiting:
        print(f"    - page {fig.page}: {fig.label}: {fig.shows}")


def _there(path: str, what: str) -> None:
    """A file a reader is about to open, known to be one: said in a line where it is not."""
    if not Path(path).is_file():
        raise Refusal(f"there is no {what} at {Path(path).name}", "check the path")


@contextlib.contextmanager
def _reading() -> Iterator[None]:
    """Around anything that may ask the reader: a reader that is not set up, or one that
    stops, is a refusal in its own one line. A key about to cross a network unencrypted is
    said once, before the reading, in a line of its own; the library's own warning of the
    same thing is then not printed a second time in its own form."""
    from motionsim.observe import provider, run

    try:
        run.ready()
        warning = run.key_warning()
        if warning:
            print(f"warning: {warning}", file=sys.stderr)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", provider.KeyInTheClear)
            yield
    except (provider.NoReader, provider.ReaderFailed) as stopped:
        raise Refusal(str(stopped)) from None


def extract(args: argparse.Namespace) -> int:
    from motionsim.observe import run

    with _reading():
        _there(args.pdf, "datasheet")
        reading = run.read_datasheet(
            args.pdf, args.output, max_calls=args.max_calls, max_pages=args.max_pages, curves=not args.no_curves
        )
    obs = reading.observations
    print(f"{obs.vendor} {obs.part_number} ({obs.technology}, {obs.topology.value})")
    first, *rest = reading.summary()
    print(f"  {first}")
    _flags(obs)
    for line in rest:
        print(f"  {line}")
    if obs.document.transcribed:
        print(
            f"  {len(obs.document.transcribed)} of {obs.document.pages} pages had no usable text and were read "
            "from their image"
        )
    _print_curves(obs)
    print(f"  written to {args.output}")
    return 0


def _same_document(args: argparse.Namespace):
    """The observations and the pages of the PDF they were read from, or a refusal where
    the PDF is another file."""
    from motionsim.observe import load_observations
    from motionsim.observe.ingest import read_pages

    _there(args.pdf, "datasheet")
    _there(args.observations, "observations file")
    document, pages = read_pages(args.pdf)
    obs = load_observations(args.observations)
    if document.sha256 != obs.document.sha256:
        raise Refusal(
            "this PDF is not the file the observations were read from", "give the datasheet they were read from"
        )
    return obs, pages


def curves(args: argparse.Namespace) -> int:
    """Read the figures again for a datasheet whose tables are already read."""
    from motionsim.observe import digitise, save_observations

    with _reading():
        obs, _ = _same_document(args)
        obs.curves = digitise.digitise_curves(args.pdf, obs)
    save_observations(obs, args.observations)
    _print_curves(obs)
    return 0


def check(args: argparse.Namespace) -> int:
    from motionsim.observe import ingest, save_observations
    from motionsim.observe.verify import recheck

    with _reading():
        obs, pages = _same_document(args)
        obs = recheck(obs, ingest.with_transcripts(obs.document, pages))
    save_observations(obs, args.observations)
    flagged = [o for o in obs.observations if o.flags]
    print(f"  {len(obs.observations)} table values checked, {len(flagged)} flagged")
    _flags(obs)
    return 0


def build(args: argparse.Namespace) -> int:
    from motionsim.files import read_yaml
    from motionsim.fit import build_device
    from motionsim.fit.typed import from_figures, is_figures
    from motionsim.observe import load_observations

    typed = read_yaml(args.observations, "file of figures")
    # A file of figures typed in by hand (motionsim template device) is built directly.
    if is_figures(typed):
        device = from_figures(typed)
    else:
        device = build_device(load_observations(args.observations), allow_flagged=args.allow_flagged)
    _saved(device, args.output)
    print(f"{device.vendor} {device.part_number}: device model written to {args.output}", file=sys.stdout)
    return 0
