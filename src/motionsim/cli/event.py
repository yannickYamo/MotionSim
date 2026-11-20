"""`motionsim event`: the switching event of a design's hottest switch, zoomed in."""

from __future__ import annotations

import argparse
import csv
import io

from motionsim.cli import show
from motionsim.errors import Refusal
from motionsim.files import read_text, write_text
from motionsim.service.routes import run as ask
from motionsim.text import written

TRACES = ("t", "v_gs", "v_ds", "i", "p")


def _request(args: argparse.Namespace, ws) -> dict:
    from motionsim import design

    setup = design.normalise_setup(design.load_setup(args.setup, ws))
    devices = setup["devices"]
    device = args.device or devices[0]
    if device not in devices:
        raise Refusal(f"{device} is not among the design's devices", f"name one of {', '.join(devices)}", "device")
    asked: dict = {"l_cs_nh": args.lcs, "l_g_nh": args.lgate, "v_off": args.voff}
    if args.layout:
        asked |= {"layout": read_text(args.layout, "layout file", "layout"), "layout_name": args.layout}
    return {"motor": setup["motor"], "conditions": setup["conditions"], "device": device, "event": asked}


def _n(value: float | None, factor: float, unit: str, digits: int = 3) -> str:
    return "–" if value is None else f"{written(abs(value) * factor, digits)} {unit}"


def _edge_lines(name: str, e: dict, v_dc: float) -> list[str]:
    energy = f"{_n(e['energy'], 1e6, 'µJ')} (the loss model: {_n(e['target'], 1e6, 'µJ')}"
    energy += ")" if e["met"] else ", not met)"
    lines = [
        f"{name}: energy {energy}",
        f"  di/dt {_n(e['di_dt'], 1e-9, 'A/ns')}, dv/dt {_n(e['dv_dt'], 1e-9, 'V/ns')}",
        f"  delay {_n(e['t_delay'], 1e9, 'ns')}, rise {_n(e['t_rise'], 1e9, 'ns')}, fall {_n(e['t_fall'], 1e9, 'ns')}",
        f"  peak current {_n(e['i_peak'], 1, 'A')}, peak voltage {_n(e['v_peak'], 1, 'V')} "
        f"({_n(e['v_peak'] - v_dc, 1, 'V')} over the supply)",
    ]
    if e["ring"]:
        lines.append(f"  rings at {_n(e['ring'], 1e-6, 'MHz')}")
    return lines


def _print(answer: dict) -> None:
    print(
        f"{answer['name']}, {answer['position']}: {written(answer['current'], 3)} A at {written(answer['v_dc'], 3)} V, "
        f"junction {written(answer['tj'], 3)} °C"
    )
    for key, name in (("turn_on", "Turn-on"), ("turn_off", "Turn-off")):
        print("\n".join(_edge_lines(name, answer[key], answer["v_dc"])))
    sheet = answer.get("datasheet")
    if sheet:
        rows = ", ".join(
            f"{r['what']} {_n(r['model'], 1e9, 'ns')} (datasheet {_n(r['datasheet'], 1e9, 'ns')})"
            for r in sheet["rows"]
        )
        print(f"In the datasheet's test: {rows}")
    for a in answer["assumed"]:
        print(f"  assumed: {a['text']}")
    for note in answer["notes"]:
        print(f"  {note}")


def _traces_csv(answer: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["edge", "t_s", "v_gs_v", "v_ds_v", "i_a", "p_w"])
    for key in ("turn_on", "turn_off"):
        e = answer[key]
        for row in zip(*(e[k] for k in TRACES), strict=True):
            w.writerow([key, *row])
    return out.getvalue()


def event(args: argparse.Namespace) -> int:
    from motionsim.cli import asking

    with asking.workspace() as ws:
        answer = ask("/api/event", _request(args, ws), ws)
    if args.csv:
        write_text(args.csv, _traces_csv(answer), "traces")
    if args.json:
        show.as_json(answer)
        return 0
    _print(answer)
    if args.csv:
        print(f"  both edges through time written to {args.csv}")
    return 0
