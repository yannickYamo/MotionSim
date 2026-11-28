"""`motionsim control`: the control lab from the terminal. The design is a design file, as
`motionsim event` and `motionsim cycle` take it; what is asked goes to the same addresses
the page uses (service/control), and --json prints their answers whole."""

from __future__ import annotations

import argparse
import json
from typing import Any

from motionsim.cli import show
from motionsim.errors import Refusal
from motionsim.service.routes import run as ask
from motionsim.text import written


def _value(text: str) -> Any:
    """A figure given on the command line: a number, true or false, or a word."""
    try:
        return json.loads(text)
    except ValueError:
        return text


def _pairs(given: list[str] | None, what: str, field: str) -> dict:
    out = {}
    for item in given or []:
        name, sep, value = item.partition("=")
        if not sep or not name:
            raise Refusal(f"{what} is given as name=value, and {item} was given", f"write {what} as name=value", field)
        out[name] = _value(value)
    return out


def _request(args: argparse.Namespace, ws) -> dict:
    """The design request a design file makes, with what the command line adds."""
    from motionsim import design

    setup, front = design.with_front_end(design.normalise_setup(design.load_setup(args.setup, ws)), ws)
    if front is not None and "refused" in front:
        raise Refusal(front["refused"], front.get("fix", ""), front.get("field", ""))
    devices = setup["devices"]
    device = args.device or devices[0]
    if device not in devices:
        raise Refusal(f"{device} is not among the design's devices", f"name one of {', '.join(devices)}", "device")
    request: dict = {"motor": setup["motor"], "conditions": setup["conditions"], "device": device}
    # Fed from the mains: the lab runs the link with the front end's control.
    request |= {k: setup[k] for k in ("supply", "mains", "front_end", "c_link") if setup.get(k) is not None}
    if setup.get("load"):
        request["load"] = setup["load"]
    if setup.get("load_kind"):
        request["application"] = setup["load_kind"]  # the application the load is of, as the page sends it
    if getattr(args, "scheme", None):
        request["scheme"] = args.scheme
    if getattr(args, "fidelity", None):
        request["fidelity"] = args.fidelity
    scenario = _pairs(getattr(args, "set", None), "a figure of the test", "scenario")
    if getattr(args, "scenario", None):
        scenario = {"kind": args.scenario, **scenario}
    if scenario:
        request["scenario"] = scenario
    mismatch = _pairs(getattr(args, "mismatch", None), "a mismatch", "mismatch")
    if mismatch:
        request["mismatch"] = mismatch
    stage = {key: True for key in ("dead_time", "device_drop") if getattr(args, key, False)}
    if stage:
        request["inverter"] = stage
    return request


def _n(value: float | None, unit: str = "", factor: float = 1.0, digits: int = 3) -> str:
    if value is None:
        return "–"
    return f"{written(value * factor, digits)}{' ' + unit if unit else ''}"


def _print_presets(answer: dict) -> None:
    print(f"Chosen for this design: {answer['chosen']}: {answer['why']}")
    print("Schemes:")
    for s in answer["schemes"]:
        print(f"  {s['id']}: {s['label']}")
    print("Tests: " + ", ".join(s["kind"] for s in answer["scenarios"]))
    print(f"Blocks: {len(answer['blocks'])} kinds ({', '.join(answer['blocks'])})")
    show.taken(answer["taken"])


def _print_loops(answer: dict) -> None:
    tuning = answer["tuning"]
    print(f"{answer['scheme']['id']}: {answer['scheme']['label']}")
    print(f"  the tuning rule: {_n(tuning['bandwidth_hz'], 'Hz')} current-loop bandwidth, {tuning['rule']}")
    for key in ("current_d", "current_q", "speed"):
        loop = answer[key]
        if loop is None:
            continue
        margins = loop["margins"]
        worst = max((p["re"] ** 2 + p["im"] ** 2) ** 0.5 for p in loop["poles"])
        print(
            f"  {loop['name']}: bandwidth {_n(loop['bandwidth_hz'], 'Hz')}, phase margin "
            f"{_n(margins['phase_deg'], '°')}, gain margin {_n(margins['gain_db'], 'dB')}, largest pole "
            f"|z| = {_n(worst, digits=4)} ({'stable' if loop['stable'] else 'unstable'})"
        )
    for line in answer["missing"]:
        print(f"  not analysed: {line}")


def _print_run(answer: dict) -> None:
    scenario = answer["scenario"]
    figures = ", ".join(
        f"{k} {written(v, 4) if isinstance(v, (int, float)) else v}" for k, v in scenario.items() if k != "kind"
    )
    print(f"{answer['scheme']['id']}, {scenario['kind']} ({figures}), {answer['fidelity']}")
    losses, channels = answer["losses"], answer["channels"]
    print(
        f"  loss {_n(losses['loss'], 'W')} (conduction {_n(losses['conduction'], 'W')}, switching "
        f"{_n(losses['switching'], 'W')}), junction peak {_n(channels['tj_peak'], '°C')}, swing "
        f"{_n(channels['tj_swing'], 'K')}"
    )
    print(
        f"  switch current {_n(channels['i_switch_rms'], 'A rms')}, peak {_n(channels['i_switch_peak'], 'A')}; "
        f"mean switching frequency {_n(channels['f_switch_mean'], 'kHz', 1e-3)}, current at commutation "
        f"{_n(channels['i_at_commutation'], 'A')}"
    )
    if channels["ripple_rms"] is not None:
        print(
            f"  ripple {_n(channels['ripple_rms'], 'A rms')} ({_n(channels['ripple_pp'], 'A')} peak to peak), "
            f"distortion {_n(channels['thd'], '%', 100)}, torque ripple {_n(channels['torque_ripple_pp'], 'N·m')}"
        )
    motor = answer["motor_loss"]
    print(
        f"  motor: copper {_n(motor['copper'], 'W')}, iron {_n(motor['iron'], 'W')}; with the inverter "
        f"{_n(motor['system'], 'W')}"
    )
    step = answer["step"]
    if step and step["kind"] == "step":
        print(
            f"  step on {step['wire']}: rise {_n(step['rise_time'], 'ms', 1e3)}, overshoot "
            f"{_n(step['overshoot'], '%', 100)}, settled in {_n(step['settling_time'], 'ms', 1e3)}"
        )
    elif step:
        print(f"  load step: deviation {_n(step['deviation'])}, recovered in {_n(step['recovery_time'], 'ms', 1e3)}")
    sensing = answer["sensing"]
    if sensing and "angle_error_mean" in sensing:
        print(
            f"  estimated angle: {_n(sensing['angle_error_mean'], '°')} mean error, "
            f"{_n(sensing['angle_error_rms'], '° rms')}"
        )
    print(f"  stability: {answer['stability']['said']}")
    show.checks(answer["checks"])
    show.taken(answer["taken"])


def _print_explorations(answer: dict) -> None:
    for group in answer["groups"]:
        print(f"{group}:")
        for e in answer["explorations"]:
            if e["group"] != group:
                continue
            print(f"  {e['id']}: {e['question']}")
            if not e["applies"]:
                print(f"      not on this design: {e['why_not']}")


def _print_sweep(answer: dict) -> None:
    vary = answer["vary"]
    print(
        f"{answer['exploration'] or 'sweep'}: {vary.get('label') or vary['path']}, {len(answer['variants'])} variants"
    )
    for n, v in enumerate(answer["variants"]):
        mark = " (baseline)" if n == answer["baseline"] else ""
        if v["refused"] is not None:
            print(f"  {v['label']}{mark}: could not be run: {v['refused']['refused']}")
            continue
        losses = v["losses"]
        print(
            f"  {v['label']}{mark}: loss {_n(losses['loss'], 'W')}, switching {_n(losses['switching'], 'W')}, "
            f"junction {_n(losses['tj_peak'], '°C')}, ripple {_n(v['channels']['ripple_rms'], 'A rms')}, "
            f"{v['level']}"
        )
    print("What it shows:")
    for line in answer["said"]:
        print(f"  {line}")


def _vary(args: argparse.Namespace) -> dict:
    if not args.vary:
        return {}
    values = [_value(v) for v in (args.values or "").split(",") if v != ""]
    if not values:
        raise Refusal("the sweep has no values to go through", "give --values as a list with commas", "vary.values")
    vary: dict = {"label": args.vary.rsplit(".", 1)[-1], "unit": "", "path": args.vary}
    vary["schemes" if args.vary == "scheme" else "values"] = values
    return {"vary": vary}


PRINTS = {
    "presets": ("/api/control/presets", _print_presets),
    "loops": ("/api/control/loops", _print_loops),
    "run": ("/api/control/run", _print_run),
    "explore": ("/api/control/explorations", _print_explorations),
    "sweep": ("/api/control/sweep", _print_sweep),
}


def _export_c(args: argparse.Namespace) -> int:
    """`motionsim control export-c`: the bundle written, the replay said; 1 where it failed."""
    from pathlib import Path

    from motionsim.cli import asking
    from motionsim.service.control.export_c import bundle

    args.setup = args.setup or args.design_file
    if not args.setup:
        raise Refusal("no design file was given", "give one: motionsim control export-c design.yaml", "design")
    with asking.workspace() as ws:
        made = bundle(_request(args, ws), ws, run_replay=not args.no_replay)
    target = Path(args.out or made["name"])
    target.write_bytes(made.pop("zip"))
    made["path"] = str(target)
    if args.json:
        show.as_json(made)
    else:
        print(f"{made['label']} ({made['scheme']}): {target}, {len(made['files'])} files")
        replay = made["replay"]
        print(f"Replay of the {made['test']} test, {made['samples']} samples: {replay.get('said')}")
    return 1 if made["replay"].get("passed") is False else 0


def control(args: argparse.Namespace) -> int:
    from motionsim.cli import asking

    if args.what == "export-c":
        return _export_c(args)
    route, printed = PRINTS[args.what]
    with asking.workspace() as ws:
        request = _request(args, ws)
        if args.what == "sweep":
            if args.exploration:
                request["exploration"] = args.exploration
            request |= _vary(args)
        answer = ask(route, request, ws)
    if args.json:
        show.as_json(answer)
        return 0
    printed(answer)
    return 0
