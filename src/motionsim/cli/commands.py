"""The commands that ask the service: each builds the request, asks, and prints the answer
or hands it over as JSON. The exit status is the verdict's, where the answer has one."""

from __future__ import annotations

import argparse
import csv
import io

from motionsim.cli import asking, show
from motionsim.errors import Refusal
from motionsim.files import read_record, read_text, write_text
from motionsim.service.routes import run as ask
from motionsim.text import written


def _status(level: str) -> int:
    return asking.EXIT_OF_LEVEL[level]


def _write_csv(path: str, header: list[str], rows) -> None:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    write_text(path, out.getvalue(), "CSV file")


def simulate(args: argparse.Namespace) -> int:
    with asking.workspace() as ws:
        request = {"device": asking.device(args.device, ws), "conditions": asking.conditions(args)}
        answer = ask("/api/simulate", request, ws)
    if args.json:
        show.as_json(answer)
        return _status(answer["level"])
    _said_first(answer)
    print(show.title(answer["device"]))
    show.result(answer["device"], answer["result"])
    # A point every check passes at is printed as it always was; one that does not says why.
    if answer["level"] != "ok":
        show.checks(answer["checks"])
    return _status(answer["level"])


def _said_first(answer: dict) -> None:
    """What was filled in before the answer: the gate drive a transistor is run with, as the
    motor command says it, and the other figures taken."""
    gate = answer.get("gate") or {"lines": []}
    for line in gate["lines"]:
        print(line)
    show.taken([line for line in answer["taken"] if line not in gate["lines"]])


def max_current(args: argparse.Namespace) -> int:
    with asking.workspace() as ws:
        request = {
            "device": asking.device(args.device, ws),
            "conditions": asking.conditions(args),
            "tj_limit": args.tj,
            "average": args.average,
        }
        answer = ask("/api/max-current", request, ws)
    if args.json:
        show.as_json(answer)
        return _status(answer["level"])
    _said_first(answer)
    if answer["limit_note"]:
        print(answer["limit_note"])
    print(show.title(answer["device"]))
    print(f"  maximum current     {answer['i_max']:8.2f} A rms")
    if answer["basis"] == "range":
        limit = answer["tj_limit"]
        print(f"  the top of the junction's range is at {limit:g} °C there")
        print(f"  on the typical estimate alone {answer['i_max_typical']:.2f} A rms would reach {limit:g} °C")
    else:
        print(f"  the average junction is at {answer['tj_limit']:g} °C there, on the typical estimate")
    if answer["covered"] is not None:
        print(f"  the data covers     {answer['covered']:8.2f} A rms")
        print("  above that the losses are drawn past the datasheet's last point: the maximum is an estimate")
    if answer["result"] is not None:
        show.result(answer["device"], answer["result"])
        if answer["level"] != "ok":
            show.checks(answer["checks"])
    return _status(answer["level"])


def _motor_request(args: argparse.Namespace, ws) -> dict:
    return {"motor": asking.motor(args), "conditions": asking.conditions(args)}


def motor(args: argparse.Namespace) -> int:
    with asking.workspace() as ws:
        request = {**_motor_request(args, ws), "device": asking.device(args.device, ws)}
        answer = ask("/api/point", request, ws)
    if args.json:
        show.as_json(answer)
        return _status(answer["level"])
    st, m = answer["stage"], answer["motor"]
    for line in answer["gate"]["lines"]:
        print(line)
    print(f"{m['name']} ({m['type']}): {args.torque:g} N·m at {args.rpm:g} rpm")
    usual = "" if args.pwm is not None or m["fixed_scheme"] else " (the usual choice for this motor)"
    print(f"  modulation          {st['scheme']}{usual}")
    print(f"  shaft power         {st['p_shaft']:8.1f} W")
    for row in st["summary"]:
        if row["unit"] == "yes/no":
            print(f"  {row['label']:<20}{'yes' if row['value'] else 'no':>8}")
        else:
            print(f"  {row['label']:<20}{row['value']:8.3g} {row['unit']}")
    print(f"  motor winding loss  {st['p_motor_loss']:8.1f} W")
    if answer["efficiency"] is not None:
        print(f"  shaft / DC power    {100 * answer['efficiency']:8.2f} %")
    print(show.title(answer["device"]))
    show.result(answer["device"], answer["result"])
    show.checks(answer["checks"])
    return _status(answer["level"])


def speed_torque_map(args: argparse.Namespace) -> int:
    with asking.workspace() as ws:
        request = {
            **_motor_request(args, ws),
            "device": asking.device(args.device, ws),
            "rpm": asking.grid(args.rpm, "rpm"),
            "torque": asking.grid(args.torque, "torque"),
        }
        answer = ask("/api/map", request, ws)
        name = ws.summary(request["device"], ws.device(request["device"]))["name"]
    if args.output:
        rows = [
            [n, t, answer["i_peak"][a][b], answer["loss"][a][b], answer["tj"][a][b], answer["efficiency"][a][b]]
            + [answer["reason"][a][b]]
            for a, t in enumerate(answer["torque"])
            for b, n in enumerate(answer["rpm"])
        ]
        header = ["rpm", "torque_nm", "i_peak_a", "p_inverter_w", "tj_peak_c", "efficiency", "note"]
        _write_csv(args.output, header, [["nan" if v is None else v for v in row] for row in rows])
    if args.json:
        show.as_json(answer)
        return 0
    print(f"{name} driving {request['motor'].get('name', 'motor')}")
    print(f"'-' the motor cannot reach this point; '*' above the {answer['tj_max']:g} °C junction rating\n")
    show.table("Peak junction temperature, °C", answer["tj"], answer, ".1f")
    show.table("Inverter loss, W", answer["loss"], answer, ".1f")
    show.table("Shaft power over DC power, %", answer["efficiency"], answer, ".1f", 100.0)
    if args.output:
        print(f"full map written to {args.output}")
    return 0


def _ranking(answer: dict) -> None:
    print(f"{'device':<28}{'loss W':>9}{'Tj peak':>9}{'margin':>8}{'at stall':>10}{'margin':>8}  verdict")
    word = {"ok": "ok", "caution": "caution", "undecided": "undecided", "fail": "FAIL"}
    for c in answer["candidates"]:
        name, r = c["name"][:27], c["result"]
        if r is None:
            print(f"{name:<28}{'-':>9}{'-':>9}{'-':>8}{'-':>10}{'-':>8}  FAIL")
            continue
        stall = "-" if c["stall_tj"] is None else f"{c['stall_tj']:.0f}"
        room = "-" if c["stall_margin"] is None else f"{c['stall_margin']:.0f}"
        tie = "  level on loss" if len(answer["tied"]) > 1 and c["id"] in answer["tied"] else ""
        print(
            f"{name:<28}{r['loss']:9.1f}{r['tj_peak']:9.0f}{c['margin']:8.0f}{stall:>10}{room:>8}  {word[c['level']]}{tie}"
        )


def _overall(candidates: list[dict]) -> str:
    """As a design is judged: it passes where any device does."""
    levels = [c["level"] for c in candidates if c["result"] is not None]
    if any(x in ("ok", "caution") for x in levels):
        return "ok"
    return "undecided" if "undecided" in levels else "fail"


def propose(args: argparse.Namespace) -> int:
    with asking.workspace() as ws:
        request = {**_motor_request(args, ws), "devices": [asking.device(d, ws) for d in args.devices]}
        answer = ask("/api/proposal", request, ws)
    status = _status(_overall(answer["candidates"]))
    if args.json:
        show.as_json(answer)
        return status
    m = answer["motor"]
    print(f"{m['name']} ({m['type']}): {args.torque:g} N·m at {args.rpm:g} rpm from {args.vdc:g} V")
    print()
    _ranking(answer)
    print()
    print("margin: °C left to the junction limit, from the top of the range where values are assumed")
    for c in answer["candidates"]:
        chosen = " (gate drive chosen for the lowest loss within the limits)" if c["gate"]["kind"] == "chosen" else ""
        if c["switching"] is not None:
            print(f"  {c['name']}: switching loss {c['switching']['text']}{chosen}.")
    print()
    for line in answer["explain"]:
        print(line)
    for c in answer["candidates"]:
        if c["problem"]:
            print()
            print(f"{c['name']}: {c['problem']}" + (f"\n  {c['fix']}" if c["fix"] else ""))
        if c["checks"]:
            print()
            print(c["name"])
            if c["needs"]:
                print("  needs")
                for need in c["needs"]:
                    print(f"    - {need}")
            show.checks(c["checks"])
    return status


def _sweep(text: str | None) -> list[float] | None:
    if not text:
        return None
    try:
        low, high = (float(v) for v in text.split(":"))
    except ValueError:
        raise Refusal(
            f"a sweep is written low:high, and {text} was given", "for example 2000:20000", "sweep_f_sw"
        ) from None
    return [low, high]


def _print_sweep(sweep: dict, rows: list[dict], order: list[str]) -> None:
    parts = {r["id"]: r["part_number"] for r in rows}
    print()
    print(f"{'fsw kHz':<10}" + "".join(f"{parts[k][:14]:>16}" for k in order))
    for j, f in enumerate(sweep["f_sw"]):
        cells = "".join(f"{'-':>16}" if row[j] is None else f"{row[j]:16.1f}" for row in sweep["loss"])
        print(f"{f / 1000:<10.1f}{cells}")
    for x in sweep["crossings"]:
        print(f"  {x['a']} and {x['b']} have equal loss near {x['f_sw'] / 1000:.1f} kHz")


def compare(args: argparse.Namespace) -> int:
    with asking.workspace() as ws:
        keys = [asking.device(d, ws) for d in args.devices]
        request = {"devices": keys, "conditions": asking.conditions(args), "sweep_f_sw": _sweep(args.sweep_fsw)}
        answer = ask("/api/compare", request, ws)
    if args.json:
        show.as_json(answer)
        return _status(answer["level"])
    for row in answer["rows"]:
        show.taken(row["taken"])
    print(f"{'device':<28}{'loss W':>9}{'eff %':>8}{'Tj peak':>9}{'margin':>8}  data support")
    for row in answer["rows"]:
        name, r = row["name"][:27], row["result"]
        if r is None:
            print(f"{name:<28}{'thermal runaway':>34}")
            continue
        bound = "~" if r["tj_range"] is not None else " "
        eff = f"{100 * r['efficiency']:8.2f}" if r["efficiency"] is not None else f"{'-':>8}"
        print(f"{name:<28}{r['loss']:9.1f}{eff}{bound:>3}{r['tj_peak']:6.1f}{row['margin']:8.1f}  {r['validity']}")
    for row in answer["rows"]:
        if row["result"] is not None and row["margin"] < 0:
            print(f"  {row['part_number']}: over its junction temperature rating")
    print()
    for row in answer["rows"]:
        print(f"  {row['name']}: switching loss {row['switching']}")
    for row in answer["rows"]:
        raised = [c for c in row["checks"] if c["level"] != "ok"]
        if raised:
            print()
            print(row["name"])
            show.checks(raised)
    if answer["sweep"] is not None:
        _print_sweep(answer["sweep"], answer["rows"], keys)
    return _status(answer["level"])


def trajectory(args: argparse.Namespace) -> int:
    with asking.workspace() as ws:
        conditions = {
            "cooling": "held",
            "v_dc": args.vdc,
            "f_sw": args.fsw,
            "t_sink": args.tsink,
            "t_dead": args.tdead,
            "v_drive": args.vdrive,
            "rg_on": args.rgon,
            "rg_off": args.rgoff,
            "l_loop": args.lloop,
            "edge_limit": args.edge_limit,
            "rth_case_sink": args.rth_case_sink,
            "interface": args.interface,
        }
        request = {
            "device": asking.device(args.device, ws),
            "conditions": conditions,
            "trajectory": read_text(args.trajectory, "trajectory", "trajectory"),
        }
        answer = ask("/api/trajectory", request, ws)
    level = show.level(answer["checks"])
    if args.output:
        _write_csv(
            args.output,
            ["time_s", "tj_hottest_from_start_c"],
            zip(answer["time"], answer["tj_from_start"], strict=True),
        )
    if args.json:
        show.as_json(answer)
        return _status(level)
    print(f"{show.title(answer['device'])} along {args.trajectory}")
    print(
        f"  duration            {answer['duration']:8.4g} s, {answer['legs']} legs, "
        f"peak current {written(answer['i_peak'], 3)} A"
    )
    print("  taking the trajectory to repeat without end")
    show.result(answer["device"], answer["result"])
    print(
        f"  run once from a heatsink-temperature start, the hottest junction reaches {answer['peak_from_start']:.1f} °C"
    )
    show.checks(answer["checks"])
    if args.output:
        print(f"  temperature against time written to {args.output}")
    return _status(level)


def recommend(args: argparse.Namespace) -> int:
    with asking.workspace() as ws:
        request = {
            **_motor_request(args, ws),
            "device": asking.device(args.device, ws),
            # The air given with the cooling is the air.
            "t_ambient": args.tambient if args.tambient is not None else args.tair,
            "dvdt": args.dvdt,
            "driver_peak": args.driver_peak,
            "driver_mismatch": args.driver_mismatch,
        }
        request["conditions"]["t_sink_max"] = args.tsink_max
        answer = ask("/api/recommend", request, ws)
        name = ws.summary(request["device"], ws.device(request["device"]))["name"]
    if args.json:
        show.as_json(answer)
        return 0
    print(
        f"{name} driving {request['motor'].get('name', 'motor')}: "
        f"{args.torque:g} N·m at {args.rpm:g} rpm from {args.vdc:g} V"
    )
    print("Starting values for a first prototype. Settle them on the bench.")
    print()
    for item in answer["items"]:
        show.recommendation(item)
    return 0


def advise(args: argparse.Namespace) -> int:
    figures = asking.motor(args)
    conditions = {"v_dc": args.vdc, "f_sw": args.fsw, "rpm": args.rpm, "torque": args.torque}
    with asking.workspace() as ws:
        answer = ask("/api/stage", {"motor": figures, "conditions": conditions, "supply": args.supply}, ws)
    if args.json:
        show.as_json(answer)
        return 0
    kind = figures.get("type", "pmsm")
    print(f"{figures.get('name', 'motor')} ({kind}): {args.torque:g} N·m at {args.rpm:g} rpm from {args.vdc:g} V")
    print("What to look for. These are rules of thumb to pick datasheets by; simulate the")
    print("candidates with `motionsim propose` before choosing.")
    print()
    for line in answer["advice"]["lines"]:
        print(f"- {line}")
    return 0


def _cycle_request(args: argparse.Namespace, ws) -> dict:
    """The motion as the service takes it. A heatsink that warms is --rth-sink with --c-sink
    from a start at --tsink; one is sized instead where only --tambient is given."""
    if args.tsink_max is not None and args.tambient is None:
        raise Refusal(
            "--tsink-max limits the heatsink that is sized, and one is sized only with --tambient",
            "give --tambient",
            "t_sink_max",
        )
    followed = args.rth_sink is not None or args.c_sink is not None
    if followed and (args.rth_sink is None or args.c_sink is None):
        raise Refusal("a heatsink needs both --rth-sink and --c-sink", "give both", "heatsink")
    request = {
        **_motor_request(args, ws),
        "device": asking.device(args.device, ws),
        "load": read_record(args.load, "load file", "load"),
        "profile": read_record(args.profile, "profile file", "profile"),
        "repeats": args.repeat,
        "c_link": args.clink,
        "supply": args.supply,
    }
    air = args.tambient if args.tambient is not None else args.tair
    if followed:
        if request["conditions"]["cooling"] != "held":
            raise Refusal(
                "a heatsink is followed as it warms from --tsink, with --rth-sink, --c-sink and --tambient",
                "--tair with --rth-heatsink takes the heatsink as already warm; with no heatsink there is none to follow",
                "heatsink",
            )
        # The air is where the heatsink starts from: --tambient, or the temperature given for the cooling.
        request["heatsink"] = {"rth": args.rth_sink, "capacity": args.c_sink, "t_ambient": air}
    elif air is not None:
        request["size_heatsink"] = {"t_ambient": air, "t_sink_max": args.tsink_max}
    return request


def _print_cycle(args: argparse.Namespace, answer: dict) -> None:
    q, names, worst = answer["summary"], answer["names"], answer["worst"]
    print(f"{names['motor']} ({names['type']}) driving {names['load']} through {names['profile']}")
    print(show.title(answer["device"]))
    runs = f", run {args.repeat} times" if args.repeat > 1 else ""
    print(f"  duration            {q['duration']:8.2f} s{runs}")
    print(f"  motor speed         {min(answer['rpm']):8.0f} to {max(answer['rpm']):.0f} rpm")
    print(
        f"  motor torque        {min(answer['torque']):8.2f} to {max(answer['torque']):.2f} N·m, {q['rms_torque']:.2f} rms"
    )
    print(f"  mean power-stage loss {q['mean_loss']:6.2f} W")
    print(f"  shaft energy        {q['shaft_energy']:8.1f} J")
    print(f"  energy lost         {q['loss_energy']:8.1f} J (power stage and motor windings)")
    print(
        f"  hottest junction    {q['peak']:8.1f} °C at t = {worst['time']:.2f} s "
        f"({worst['torque']:.2f} N·m, {worst['rpm']:.0f} rpm)"
    )
    print(f"    if every instant lasted forever it would be {q['forever']:.1f} °C")
    sink = answer["heatsink"]
    if sink is not None:
        print(
            f"  heatsink            {sink['t_start']:8.1f} to {q['sink_peak']:.1f} °C "
            f"(settles at {sink['settles']:.1f} °C if the motion repeats without pause)"
        )
    failed = [(t, p) for t, p in zip(answer["instants"], answer["problems"], strict=True) if p]
    if failed:
        print(f"  {len(failed)} of {len(answer['problems'])} instants could not be reached:")
        for problem in dict.fromkeys(p for _, p in failed):
            print(f"    - from t = {next(t for t, p in failed if p == problem):.2f} s: {problem}")
    print("  over the whole motion")
    show.checks(answer["checks"], indent="  ")
    if answer["sizing"] is not None:
        print("  heatsink for this motion repeated without pause")
        for line in answer["sizing"]["lines"]:
            print(f"    - {line}")


CYCLE_COLUMNS = [
    "time_s",
    "motor_rpm",
    "motor_torque_nm",
    "p_stage_w",
    "p_dc_w",
    "tj_c",
    "tj_if_held_forever_c",
    "t_sink_c",
    "problem",
]


def _cycle_rows(answer: dict):
    blank = lambda v: "" if v is None else v  # noqa: E731
    for k, problem in enumerate(answer["problems"]):
        yield [
            f"{written(answer['time'][k] + answer['began'], 6)}",
            answer["rpm"][k],
            answer["torque"][k],
            blank(answer["p_stage"][k]),
            blank(answer["p_dc"][k]),
            answer["tj"][k],
            "nan" if answer["steady"][k] is None else answer["steady"][k],
            answer["t_sink"][k],
            problem or "",
        ]


def cycle(args: argparse.Namespace) -> int:
    with asking.workspace() as ws:
        answer = ask("/api/cycle", _cycle_request(args, ws), ws)
    level = show.level(answer["checks"])
    if args.output:
        _write_csv(args.output, CYCLE_COLUMNS, _cycle_rows(answer))
    if args.json:
        show.as_json(answer)
        return _status(level)
    show.taken(answer["taken"])
    _print_cycle(args, answer)
    if args.output:
        print(f"  every instant written to {args.output}")
    return _status(level)


def _design_init(args: argparse.Namespace, ws) -> int:
    from pathlib import Path

    import yaml

    from motionsim import design

    key = asking.device(args.device, ws)
    setup = design.starting_setup(key, ws, args.motor)
    # As the user named it; a file is named in full, so the design finds it from wherever it is kept.
    setup["devices"] = [str(Path(args.device).resolve()) if Path(args.device).is_file() else args.device]
    text = design.SETUP_HEAD + yaml.safe_dump(setup, sort_keys=False, allow_unicode=True)
    if args.output:
        write_text(args.output, text, "design")
        print(f"written to {args.output}: edit it, then `motionsim design run {args.output}`")
    else:
        print(text, end="")
    return 0


def design(args: argparse.Namespace) -> int:
    """A whole design from one file. The exit status is the outcome's: see EXIT_STATUS."""
    from motionsim import design as designs

    with asking.workspace(args.workspace) as ws:
        if args.action == "init":
            return _design_init(args, ws)
        if args.verbose:
            import logging

            logging.basicConfig(level=logging.INFO, format="%(message)s")
        setup = designs.load_setup(args.setup, ws)
        steps = tuple(x for x in designs.STEPS if x not in (args.skip or []))
        result = designs.run(setup, ws, steps=steps, traces=args.traces, date=args.date)
    report = designs.markdown(result)
    if args.md:
        write_text(args.md, report, "report")
    if args.csv:
        write_text(args.csv, designs.csv_text(result), "table")
    if args.json:
        show.as_json(result)
    elif not args.md:
        print(report, end="")
    else:
        print(f"{result['outcome']}: report written to {args.md}")
    # A step that could not be run is a design that cannot be run as written, whatever the rest says.
    if result.get("refusals"):
        return 2
    return {"refused": 2, "does not pass": 3, "undecided": 4}.get(result["outcome"], 0)
