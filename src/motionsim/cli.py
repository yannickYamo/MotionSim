from __future__ import annotations

import argparse
import sys

import numpy as np

from motionsim import __version__
from motionsim.device import load_device, save_device
from motionsim.engine import OperatingPoint, Pwm, ThermalRunaway, solve
from motionsim.engine.limits import max_current, supported_current
from motionsim.text import written


def _pwm(args: argparse.Namespace) -> Pwm:
    """The scheme asked for; without one, the usual scheme for the motor, or sine."""
    if args.pwm is not None:
        return Pwm(args.pwm)
    if getattr(args, "motor", None):
        from motionsim.motor import load_machine

        return load_machine(args.motor).default_pwm
    return Pwm.sine


def _cooling(args: argparse.Namespace) -> dict:
    """The cooling asked for: a heatsink held at --tsink, or cooling to air at --tair
    through a heatsink (--rth-heatsink) or with none (--rth-ja, completed for a device by
    _in_free_air)."""
    get = lambda name: getattr(args, name, None)  # noqa: E731
    free = _no_heatsink_asked(args)
    in_air = get("rth_heatsink") is not None or free
    if get("rth_heatsink") is not None and free:
        raise SystemExit(
            "give --rth-heatsink, or one of --rth-ja, --no-heatsink and --board-area, not both: "
            "the devices sit on a heatsink or they do not"
        )
    if get("copper") is not None and get("board_area") is None:
        raise SystemExit("--copper needs --board-area: the packages then share a board")
    for name in ("rth_heatsink", "rth_ja", "board_area", "copper", "copper_ref"):
        if get(name) is not None and not get(name) > 0:
            raise SystemExit(f"--{name.replace('_', '-')} has to be above zero")
    under = {}
    if get("rth_case_sink") is not None:
        under["rth_case_sink"] = args.rth_case_sink
    if get("interface") is not None and hasattr(args, "rth_case_sink"):
        under["interface"] = args.interface
    if under and free:
        raise SystemExit(
            "--rth-case-sink and --interface say what lies under a package on a heatsink, and --rth-ja, "
            "--no-heatsink or --board-area says there is none: give one or the other"
        )
    if under.get("rth_case_sink", 0) > 50:
        raise SystemExit("--rth-case-sink cannot be above 50 K/W: it is one package's case to its heatsink")
    if in_air:
        if get("tsink") is not None:
            raise SystemExit("give one cooling: --tsink is a heatsink at a known temperature, --tair is cooling to air")
        if args.tair is None:
            raise SystemExit("cooling to air needs the air's temperature: --tair")
        return {"t_sink": args.tair, "rth_sink": args.rth_heatsink, **under}
    if get("tair") is not None:
        raise SystemExit(
            "--tair needs the way to the air: --rth-heatsink (a heatsink's K/W), --rth-ja or "
            "--no-heatsink (no heatsink), --board-area (parts soldered to one board)"
        )
    if args.tsink is None:
        raise SystemExit(
            "give the cooling: --tsink for a heatsink at a known temperature, or --tair with "
            "--rth-heatsink (a heatsink in air) or --rth-ja (no heatsink)"
        )
    return {"t_sink": args.tsink, **under}


def _no_heatsink_asked(args: argparse.Namespace) -> bool:
    return any(getattr(args, name, None) not in (None, False) for name in ("rth_ja", "no_heatsink", "board_area"))


def _in_free_air(args: argparse.Namespace, device, op: OperatingPoint) -> OperatingPoint:
    """With no heatsink, what lies between this device's case and the air."""
    if not _no_heatsink_asked(args):
        return op
    from dataclasses import replace

    from motionsim.cooling import no_heatsink

    try:
        free = no_heatsink(
            device, args.rth_ja, board_area=args.board_area, copper=args.copper, copper_ref=args.copper_ref
        )
        for line in free.lines:
            if line.startswith("junction to air taken") and not getattr(args, "_air_said", False):
                print(line)
                args._air_said = True
        return replace(op, rth_free=free.rth_free, rth_board=free.rth_board)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None


def _operating_point(args: argparse.Namespace, i_rms: float, device=None) -> OperatingPoint:
    """The conditions from the command line. With no heatsink they depend on the device,
    which is then needed."""
    op = _conditions(args, i_rms)
    if _no_heatsink_asked(args) and device is None:
        raise SystemExit(
            "cooling with no heatsink is not taken by this command: it compares devices under one set of conditions"
        )
    return op if device is None else _dead_time_filled(args, device, _in_free_air(args, device, op))


def _dead_time_filled(args: argparse.Namespace, device, op: OperatingPoint) -> OperatingPoint:
    """As the page does: a dead time left open is the one a drive with this gate drive would
    be set to, so that the same part gives the same loss here and there. Said once."""
    from dataclasses import replace

    from motionsim import recommend
    from motionsim.device.schema import ChipKind

    # For an IGBT the dead time changes only the voltage a motor can be given: a command
    # that is told the modulation outright (simulate, compare) has no use for one.
    if device.switch.kind is not ChipKind.mosfet and getattr(args, "motor", None) is None:
        return op
    found, line = recommend.open_dead_time(device, op)
    if found is None:
        return op
    if not getattr(args, "_dead_said", False):
        print(f"{line} (--tdead)")
        args._dead_said = True
    return replace(op, t_dead=found)


def _conditions(args: argparse.Namespace, i_rms: float) -> OperatingPoint:
    if getattr(args, "m", 0.0) > 2 / 3**0.5 + 1e-9:
        raise SystemExit(f"--m is the modulation index, at most 1.155 with any scheme, and {args.m:g} was given")
    return OperatingPoint(
        **_cooling(args),
        v_dc=args.vdc,
        i_rms=i_rms,
        modulation_index=getattr(args, "m", 0.0),
        power_factor=getattr(args, "pf", 1.0),
        f_sw=args.fsw,
        f_out=getattr(args, "fout", 50.0),
        pwm=_pwm(args),
        t_dead=args.tdead,
        v_drive=args.vdrive,
        rg_on=args.rgon,
        rg_off=args.rgoff,
        l_loop=args.lloop,
        t_min_pulse=getattr(args, "tmin", 0.0),
        parallel=getattr(args, "parallel", 1),
    )


def _machine(args: argparse.Namespace):
    """The motor file, at the winding temperature asked for where one is given."""
    from motionsim.motor import load_machine
    from motionsim.motor.machines import at_temperature

    machine = load_machine(args.motor)
    hot = getattr(args, "tmotor", None)
    return machine if hot is None else at_temperature(machine, hot)


def _simulate(args: argparse.Namespace) -> int:
    device = load_device(args.device)
    try:
        r = solve(device, _operating_point(args, args.irms, device))
    except ThermalRunaway as exc:
        print(f"thermal runaway: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"cannot simulate: {exc}", file=sys.stderr)
        return 1
    print(f"{device.vendor} {device.part_number} ({device.technology})")
    _print_result(device, r)
    return 0


def _max_current(args: argparse.Namespace) -> int:
    device = load_device(args.device)
    i_max, r = max_current(device, _operating_point(args, 0.0, device), tj_limit=args.tj, peak=not args.average)
    print(f"{device.vendor} {device.part_number} ({device.technology})")
    print(f"  maximum current     {i_max:8.2f} A rms")
    op = _operating_point(args, 0.0, device)
    covered = supported_current(device, op, i_max)
    if covered is not None:
        print(f"  the data covers     {covered:8.2f} A rms")
        print("  above that the losses are drawn past the datasheet's last point: the maximum is an estimate")
    if r is not None:
        _print_result(device, r)
    return 0


def _motor(args: argparse.Namespace) -> int:
    from motionsim.drivers import at_speed_and_torque
    from motionsim.motor import Unreachable

    device, motor = load_device(args.device), _machine(args)
    try:
        point = at_speed_and_torque(device, motor, args.rpm, args.torque, _operating_point(args, 0.0, device))
    except (Unreachable, ThermalRunaway, ValueError) as exc:
        print(f"cannot simulate: {exc}", file=sys.stderr)
        return 1
    st = point.stage
    print(f"{motor.name} ({motor.type}): {args.torque:g} N·m at {args.rpm:g} rpm")
    usual = "" if args.pwm is not None or motor.fixed_scheme else " (the usual choice for this motor)"
    print(f"  modulation          {motor.scheme(_pwm(args))}{usual}")
    print(f"  shaft power         {st.p_shaft:8.1f} W")
    for label, value, unit in st.summary:
        if unit == "yes/no":
            print(f"  {label:<20}{'yes' if value else 'no':>8}")
        else:
            print(f"  {label:<20}{value:8.3g} {unit}")
    print(f"  motor winding loss  {st.p_motor_loss:8.1f} W")
    if point.system_efficiency is not None:
        print(f"  shaft / DC power    {100 * point.system_efficiency:8.2f} %")
    print(f"{device.vendor} {device.part_number} ({device.technology})")
    _print_result(device, point.result)
    from motionsim import guard

    _print_checks(guard.check(device, _operating_point(args, 0.0, device), point.result, st.i_peak))
    return 0


def _print_checks(checks, indent: str = "  ") -> None:
    from motionsim import guard

    word = {
        guard.Level.ok: "ok",
        guard.Level.caution: "CAUTION",
        guard.Level.undecided: "UNDECIDED",
        guard.Level.fail: "FAIL",
    }
    print(f"{indent}checks: {word[guard.verdict(checks)]}")
    for c in checks:
        print(f"{indent}  [{word[c.level]:>7}] {c.topic}: {c.message}")


def _propose(args: argparse.Namespace) -> int:
    from motionsim import guard
    from motionsim.engine.solver import hot_share
    from motionsim.motor import Unreachable
    from motionsim.propose import explain, level_with_best, propose
    from motionsim.recommend import choose_gate_drive

    devices = [load_device(path) for path in args.devices]
    motor = _machine(args)
    shared = _conditions(args, 0.0)

    def gate(device):
        base = _in_free_air(args, device, shared)
        # As the page does: a gate drive left open is chosen for each device, at the design
        # point's peak current, so that a part with charge data only can be ranked at all.
        try:
            i_peak = motor.stage(args.rpm, args.torque, base.v_dc, base.pwm).i_peak
        except (Unreachable, ValueError):
            i_peak = device.ratings.i_nominal
        return choose_gate_drive(device, base, max(i_peak * hot_share(device, base.parallel), 1e-3))

    gates = {id(d): gate(d) for d in devices}
    base = shared
    try:
        candidates = propose(devices, motor, args.rpm, args.torque, base, tune=lambda d: gates[id(d)].op)
    except Unreachable as exc:
        print(f"the motor cannot run at this point: {exc}", file=sys.stderr)
        return 1
    word = {
        guard.Level.ok: "ok",
        guard.Level.caution: "caution",
        guard.Level.undecided: "undecided",
        guard.Level.fail: "FAIL",
    }
    print(f"{motor.name} ({motor.type}): {args.torque:g} N·m at {args.rpm:g} rpm from {args.vdc:g} V")
    print()
    print(f"{'device':<28}{'loss W':>9}{'Tj peak':>9}{'margin':>8}{'at stall':>10}{'margin':>8}  verdict")
    level = level_with_best(candidates)
    for c in candidates:
        name = c.name[:27]
        if c.design is None:
            print(f"{name:<28}{'-':>9}{'-':>9}{'-':>8}{'-':>10}{'-':>8}  FAIL")
            continue
        peak = max(c.design.result.tj_switch_peak, c.design.result.tj_diode_peak)
        stall = "-" if c.stall is None else f"{max(c.stall.result.tj_switch_peak, c.stall.result.tj_diode_peak):.0f}"
        room = "-" if c.stall_margin is None else f"{c.stall_margin:.0f}"
        tie = "  level on loss" if len(level) > 1 and c in level else ""
        print(f"{name:<28}{c.loss:9.1f}{peak:9.0f}{c.margin:8.0f}{stall:>10}{room:>8}  {word[c.level]}{tie}")
    print()
    print("margin: °C left to the junction limit, from the top of the range where values are assumed")
    for c in candidates:
        chosen = gates[id(c.device)]
        drive = " (gate drive chosen for the lowest loss within the limits)" if chosen.kind == "chosen" else ""
        print(f"  {c.name}: switching loss {c.footing.text}{drive}.")
    print()
    for line in explain(candidates):
        print(line)
    for c in candidates:
        if c.checks:
            print()
            print(f"{c.device.vendor} {c.device.part_number}")
            if c.needs:
                print("  needs")
                for need in c.needs:
                    print(f"    - {need}")
            _print_checks(c.checks)
    return 0


def _trajectory(args: argparse.Namespace) -> int:
    from motionsim import guard
    from motionsim.trajectory import BadTrajectory, load_trajectory, run

    device = load_device(args.device)
    try:
        trajectory = load_trajectory(args.trajectory)
    except (BadTrajectory, OSError) as exc:
        print(f"cannot read the trajectory: {exc}", file=sys.stderr)
        return 1
    op = OperatingPoint(
        v_dc=args.vdc,
        i_rms=0.0,
        modulation_index=0.0,
        power_factor=1.0,
        f_sw=args.fsw,
        t_sink=args.tsink,
        t_dead=args.tdead,
        v_drive=args.vdrive,
        rg_on=args.rgon,
        rg_off=args.rgoff,
        l_loop=args.lloop,
    )
    try:
        outcome = run(device, trajectory, op)
    except (ThermalRunaway, ValueError) as exc:
        print(f"cannot simulate: {exc}", file=sys.stderr)
        return 1
    r = outcome.result
    i_peak = max(float(np.abs(i).max()) for i in trajectory.current.values())
    print(f"{device.vendor} {device.part_number} ({device.technology}) along {args.trajectory}")
    print(
        f"  duration            {trajectory.duration:8.4g} s, {len(trajectory.legs)} legs, "
        f"peak current {written(i_peak, 3)} A"
    )
    print("  taking the trajectory to repeat without end")
    _print_result(device, r)
    print(
        f"  run once from a heatsink-temperature start, the hottest junction reaches {outcome.peak_from_start:.1f} °C"
    )
    _print_checks(guard.check(device, op, r, i_peak))
    if args.output:
        import csv

        with open(args.output, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["time_s", "tj_hottest_from_start_c"])
            w.writerows(zip(outcome.time, outcome.tj_from_start, strict=True))
        print(f"  temperature against time written to {args.output}")
    return 0


def _serve(args: argparse.Namespace) -> int:
    import logging

    from motionsim.server import serve

    logging.basicConfig(level=getattr(logging, args.log_level.upper()), format="%(asctime)s %(levelname)s %(message)s")
    serve(port=args.port, folder=args.devices, open_browser=not args.no_browser)
    return 0


def _print_recommendation(r) -> None:
    print(f"{r.topic}")
    for line in r.lines:
        print(f"  - {line}")


def _recommend(args: argparse.Namespace) -> int:
    from dataclasses import replace

    from motionsim import recommend
    from motionsim.drivers import at_speed_and_torque
    from motionsim.engine.limits import hottest
    from motionsim.motor import Unreachable

    device, motor = load_device(args.device), _machine(args)
    base = _operating_point(args, 0.0, device)
    if args.tambient is None:
        args.tambient = getattr(args, "tair", None)  # the air given with the cooling is the air
    try:
        stage = motor.stage(args.rpm, args.torque, base.v_dc, base.pwm)
    except Unreachable as exc:
        print(f"the motor cannot run at this point: {exc}", file=sys.stderr)
        return 1
    print(
        f"{device.vendor} {device.part_number} driving {motor.name}: "
        f"{args.torque:g} N·m at {args.rpm:g} rpm from {args.vdc:g} V"
    )
    print("Starting values for a first prototype. Settle them on the bench.")
    print()
    _print_recommendation(
        recommend.gate_resistors(
            device,
            # As the page does: with no loop inductance given, the usual one is taken for the overshoot limit.
            base if base.l_loop is not None else replace(base, l_loop=recommend.USUAL_LOOP),
            stage.i_peak,
            dvdt_max=args.dvdt * 1e9,
            driver_peak=args.driver_peak,
        )
    )
    _print_recommendation(recommend.dead_time(device, base, driver_mismatch=args.driver_mismatch))

    def evaluate(t_sink: float) -> tuple[float, float]:
        worst, loss = float("-inf"), 0.0
        for rpm in (args.rpm, 0.0):  # the design point, and holding the same torque at standstill
            try:
                point = at_speed_and_torque(
                    device,
                    motor,
                    rpm,
                    args.torque,
                    replace(base, t_sink=t_sink, rth_sink=None, rth_free=None, rth_board=None),
                )
            except Unreachable:
                continue
            except ValueError as exc:
                raise SystemExit(f"cannot simulate: {exc}") from exc
            top = point.result.tj_peak_range[1] if point.result.tj_peak_range else hottest(point.result)
            worst, loss = max(worst, top), max(loss, point.result.p_inverter)
        return worst, loss

    losses = {}
    if motor.fixed_scheme is None:
        for scheme in Pwm:
            try:
                point = at_speed_and_torque(device, motor, args.rpm, args.torque, replace(base, pwm=scheme))
                losses[scheme.value] = point.result.p_inverter
            except (Unreachable, ThermalRunaway, ValueError):
                continue
    _print_recommendation(recommend.modulation(losses, motor.default_pwm.value))

    if args.tambient is None:
        print("heatsink")
        print("  - give the ambient temperature (--tambient) to size a heatsink")
    else:
        _print_recommendation(
            recommend.heatsink(device, args.tambient, evaluate, sink_limit=getattr(args, "tsink_max", None))
        )
    return 0


def _validate(args: argparse.Namespace) -> int:
    from motionsim.reference import compare, load_reference

    device, reference = load_device(args.device), load_reference(args.reference)
    try:
        rows = compare(device, reference)
    except (ThermalRunaway, ValueError) as exc:
        print(f"cannot simulate a reference point: {exc}", file=sys.stderr)
        return 1
    print(f"{device.vendor} {device.part_number} against {reference.name} ({reference.kind})")
    for k, p in enumerate(reference.points, start=1):
        if p.on_time is not None:
            print(
                f"point {k}: on {p.on_time:g} s, off {p.off_time:g} s. Its losses and case temperature "
                "are means over the whole pattern, the pause included"
            )
    print(f"{'point':>5} {'quantity':<19}{'model':>9}   {'reference':>8}   {'difference':>10}")
    numbers = {id(p): k for k, p in enumerate(reference.points, start=1)}
    for row in rows:
        unit = "W" if row.quantity.startswith("p_") else "K" if row.quantity.endswith("swing") else "°C"
        shown = f"{row.relative:+.1%}" if unit == "W" else f"{row.difference:+.1f} K"
        print(
            f"{numbers[id(row.point)]:>5} {row.quantity:<19}{row.model:>9.2f} {unit:<2}"
            f"{row.reference:>8.2f} {unit:<2}{shown:>10}"
        )
    losses = [abs(r.relative) for r in rows if r.quantity.startswith("p_")]
    temperatures = [abs(r.difference) for r in rows if not r.quantity.startswith("p_")]
    if losses:
        print(f"largest loss difference        {max(losses):.1%}")
    if temperatures:
        print(f"largest temperature difference {max(temperatures):.1f} K")
    support = {r.result.validity.value for r in rows}
    print(f"data support of the model at these points: {', '.join(sorted(support))}")
    return 0


def _advise(args: argparse.Namespace) -> int:
    from motionsim.advise import advise
    from motionsim.motor import Unreachable

    motor = _machine(args)
    try:
        advice = advise(motor, args.rpm, args.torque, args.vdc, args.fsw, supply=args.supply)
    except Unreachable as exc:
        print(f"the motor cannot run at this point: {exc}", file=sys.stderr)
        return 1
    print(f"{motor.name} ({motor.type}): {args.torque:g} N·m at {args.rpm:g} rpm from {args.vdc:g} V")
    print("What to look for. These are rules of thumb to pick datasheets by; simulate the")
    print("candidates with `motionsim propose` before choosing.")
    print()
    for line in advice.lines:
        print(f"- {line}")
    return 0


def _grid(text: str):
    import numpy as np

    try:
        low, high, count = text.split(":")
        low, high, count = _figure(low), _figure(high), int(count)
    except (ValueError, argparse.ArgumentTypeError):
        raise SystemExit(f"a range is written low:high:count, and {text} was given") from None
    if not 1 <= count <= 200:
        raise SystemExit(f"a range takes 1 to 200 points, and {count} were asked for")
    return np.linspace(low, high, count)


def _map(args: argparse.Namespace) -> int:
    import numpy as np

    from motionsim.drivers import speed_torque_map

    device, motor = load_device(args.device), _machine(args)
    try:
        m = speed_torque_map(device, motor, _grid(args.rpm), _grid(args.torque), _operating_point(args, 0.0, device))
    except ValueError as exc:
        print(f"cannot simulate: {exc}", file=sys.stderr)
        return 1
    limit = device.ratings.tj_max

    def table(title: str, values, fmt: str) -> None:
        print(title)
        corner = "N·m \\ rpm"
        print(f"{corner:>10}" + "".join(f"{n:9.0f}" for n in m.rpm))
        for a in reversed(range(len(m.torque))):
            cells = ""
            for b in range(len(m.rpm)):
                v = values[a, b]
                if np.isnan(v):
                    cells += f"{'-':>9}"
                else:
                    mark = "*" if m.tj_peak[a, b] > limit else " "
                    cells += f"{format(v, fmt):>8}{mark}"
            print(f"{m.torque[a]:10.2f}{cells}")
        print()

    print(f"{device.vendor} {device.part_number} driving {motor.name}")
    print(f"'-' the motor cannot reach this point; '*' above the {limit:g} °C junction rating\n")
    table("Peak junction temperature, °C", m.tj_peak, ".1f")
    table("Inverter loss, W", m.p_inverter, ".1f")
    table("Shaft power over DC power, %", 100 * m.efficiency, ".1f")
    if args.output:
        import csv

        with open(args.output, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["rpm", "torque_nm", "i_peak_a", "p_inverter_w", "tj_peak_c", "efficiency", "note"])
            for a, t in enumerate(m.torque):
                for b, n in enumerate(m.rpm):
                    w.writerow(
                        [n, t, m.i_peak[a, b], m.p_inverter[a, b], m.tj_peak[a, b], m.efficiency[a, b], m.reason[a][b]]
                    )
        print(f"full map written to {args.output}")
    return 0


def _package(args: argparse.Namespace) -> int:
    import numpy as np

    from motionsim.package import build, summarise

    print(f"{args.template}, {args.irated:g} A switch, on {args.interface}")
    if args.template.endswith("module"):
        print("between chips is over the package's own face; interface is from that face to the heatsink")
    print("junction to heatsink surface, K/W; low and high span plausible constructions")
    print(f"{'':<10}{'switch alone':>14}{'diode alone':>13}{'between chips':>15}{'interface':>11}")
    for variant in ("low", "typical", "high"):
        model = build(args.template, args.irated, variant, args.interface, diode=not args.no_diode)
        s = summarise(model)
        diode = f"{s.self_diode:13.2f}" if s.self_diode is not None else f"{'-':>13}"
        print(f"{variant:<10}{s.self_switch:14.2f}{diode}{s.coupling:15.3f}{s.interface:11.3f}")
    model = build(args.template, args.irated, "typical", args.interface, diode=not args.no_diode)
    print(f"heat spreads about {model.stack.spreading_length * 1000:.1f} mm sideways in the copper")
    names = model.chip_names
    if len(names) <= 4:
        print("typical matrix, rise of row chip per watt in column chip:")
        for name, row in zip(names, np.round(model.matrix(), 3), strict=True):
            print(f"  {name:<10}" + "".join(f"{v:9.3f}" for v in row))
    return 0


def _template(args: argparse.Namespace) -> int:
    from motionsim.fit.typed import TEMPLATE as DEVICE_TEMPLATE
    from motionsim.load import LOAD_TEMPLATE, PROFILE_TEMPLATE
    from motionsim.motor import TEMPLATES
    from motionsim.reference import TEMPLATE as REFERENCE_TEMPLATE
    from motionsim.trajectory import example

    text = {
        **TEMPLATES,
        "device": DEVICE_TEMPLATE,
        "load": LOAD_TEMPLATE,
        "profile": PROFILE_TEMPLATE,
        "reference": REFERENCE_TEMPLATE,
        "trajectory": example(),
    }[args.kind]
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"written to {args.output}; edit the values to match yours")
    else:
        print(text, end="")
    return 0


def _cycle(args: argparse.Namespace) -> int:
    from dataclasses import replace

    from motionsim import dclink, guard
    from motionsim.engine.limits import hottest
    from motionsim.load import load_load, load_profile
    from motionsim.transient import Heatsink, follow

    if getattr(args, "tsink_max", None) is not None and args.tambient is None:
        raise SystemExit("--tsink-max limits the heatsink that is sized, and one is sized only with --tambient")
    device, motor = load_device(args.device), _machine(args)
    load, profile = load_load(args.load), load_profile(args.profile)
    base = _operating_point(args, 0.0, device)
    if args.tambient is None:
        args.tambient = getattr(args, "tair", None)
    heatsink = None
    if args.rth_sink is not None or args.c_sink is not None:
        if args.rth_sink is None or args.c_sink is None:
            print("a heatsink needs both --rth-sink and --c-sink", file=sys.stderr)
            return 1
        if _no_heatsink_asked(args) or getattr(args, "rth_heatsink", None) is not None:
            print(
                "to follow a heatsink as it warms, give --tsink (where it starts), --rth-sink, --c-sink and "
                "--tambient. --tair with --rth-heatsink takes the heatsink as already warm; with no heatsink "
                "there is none to follow",
                file=sys.stderr,
            )
            return 1
        # The air is where the heatsink starts from: --tambient, or the temperature given for the cooling.
        ambient = base.t_sink if args.tambient is None else args.tambient
        heatsink = Heatsink(rth=args.rth_sink, capacity=args.c_sink, t_ambient=ambient)
    try:
        cycle, trace = follow(device, motor, load, profile, base, heatsink=heatsink, repeats=args.repeat)
    except ValueError as exc:
        print(f"cannot simulate: {exc}", file=sys.stderr)
        return 1
    print(f"{motor.name} ({motor.type}) driving {load.name} through {profile.name}")
    print(f"{device.vendor} {device.part_number} ({device.technology})")
    failed = [s for s in cycle.steps if s.point is None]
    if not cycle.solved:
        print(f"  no instant of this motion could be solved: {failed[0].problem}", file=sys.stderr)
        return 1
    torques = [s.sample.motor_torque for s in cycle.steps]
    speeds = [s.sample.motor_rpm for s in cycle.steps]
    count = len(cycle.steps)
    at = trace.peak_index
    worst = cycle.steps[at % count]
    if worst.point is None:
        worst = cycle.worst
    forever = float(np.nanmax(trace.steady))
    runs = f", run {args.repeat} times" if args.repeat > 1 else ""
    print(f"  duration            {cycle.duration:8.2f} s{runs}")
    print(f"  motor speed         {min(speeds):8.0f} to {max(speeds):.0f} rpm")
    print(f"  motor torque        {min(torques):8.2f} to {max(torques):.2f} N·m, {cycle.rms_torque:.2f} rms")
    print(f"  mean power-stage loss {cycle.mean_loss:6.2f} W")
    print(f"  shaft energy        {cycle.shaft_energy:8.1f} J")
    print(f"  energy lost         {cycle.loss_energy:8.1f} J (power stage and motor windings)")
    print(
        f"  hottest junction    {trace.peak:8.1f} °C at t = {trace.time[at]:.2f} s "
        f"({worst.sample.motor_torque:.2f} N·m, {worst.sample.motor_rpm:.0f} rpm)"
    )
    print(f"    if every instant lasted forever it would be {forever:.1f} °C")
    if heatsink is not None:
        print(
            f"  heatsink            {base.t_sink:8.1f} to {trace.t_sink.max():.1f} °C "
            f"(settles at {heatsink.t_ambient + cycle.mean_loss * heatsink.rth:.1f} °C if the "
            "motion repeats without pause)"
        )
    if failed:
        print(f"  {len(failed)} of {len(cycle.steps)} instants could not be reached:")
        seen = []
        for s in failed:
            if s.problem not in seen:
                seen.append(s.problem)
                print(f"    - from t = {s.sample.time:.2f} s: {s.problem}")
    # The checks look at the hottest instant with the temperature it reached in time. The
    # spread across the thermal assumptions is carried over from the steady solution there.
    result = worst.point.result
    shift = trace.peak - hottest(result)
    span = result.tj_peak_range
    reached = replace(
        result,
        tj_switch_peak=result.tj_switch_peak + shift,
        tj_diode_peak=result.tj_diode_peak + shift,
        tj_peak_range=None if span is None else (span[0] + shift, span[1] + shift),
    )
    checks = guard.check(device, base, reached, max(s.point.stage.i_peak for s in cycle.solved))
    link = dclink.returned(cycle, base.v_dc, device.ratings.v_max, capacitance=args.clink)
    checks += dclink.check(link, base.v_dc, device.ratings.v_max, supply=args.supply)
    if failed:
        checks.append(guard.Check(guard.Level.fail, "motion", "the motor cannot follow part of this motion"))
    print("  over the whole motion")
    _print_checks(checks, indent="  ")
    if heatsink is None and args.tambient is not None:
        from motionsim import recommend

        spread = 0.0 if span is None else span[1] - hottest(result)

        def evaluate(t_sink: float) -> tuple[float, float]:
            moved, temperatures = follow(
                device,
                motor,
                load,
                profile,
                replace(base, t_sink=t_sink, rth_sink=None, rth_free=None, rth_board=None),
                repeats=args.repeat,
            )
            return temperatures.peak + spread, moved.mean_loss

        needed = recommend.heatsink(device, args.tambient, evaluate, sink_limit=getattr(args, "tsink_max", None))
        print("  heatsink for this motion repeated without pause")
        for line in needed.lines:
            print(f"    - {line}")
    if args.output:
        import csv

        with open(args.output, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(
                [
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
            )
            start = len(trace.time) - count
            for k, s in enumerate(cycle.steps):
                row = [f"{written(trace.time[start + k], 6)}", s.sample.motor_rpm, s.sample.motor_torque]
                if s.point is None:
                    row += ["", ""]
                else:
                    row += [s.point.result.p_inverter, s.point.stage.p_electrical + s.point.result.p_inverter]
                row += [trace.tj[start + k], trace.steady[start + k], trace.t_sink[start + k], s.problem or ""]
                w.writerow(row)
        print(f"  every instant written to {args.output}")
    return 0


def _measure(args: argparse.Namespace) -> int:
    from pathlib import Path

    from motionsim.measured import apply_double_pulse, load_double_pulse

    try:
        device = apply_double_pulse(
            load_device(args.device),
            load_double_pulse(args.measurement),
            Path(args.measurement).name,
        )
    except ValueError as exc:
        print(f"cannot use this measurement: {exc}", file=sys.stderr)
        return 1
    save_device(device, args.output)
    print(f"{device.vendor} {device.part_number}: measured switching energy written to {args.output}")
    return 0


def _compare(args: argparse.Namespace) -> int:
    import numpy as np

    from motionsim.engine.compare import compare, crossover, sweep_switching_frequency

    devices = [load_device(path) for path in args.devices]
    op = _operating_point(args, args.irms)
    rows = compare(devices, op)
    print(f"{'device':<28}{'loss W':>9}{'eff %':>8}{'Tj peak':>9}{'margin':>8}  data support")
    for row in rows:
        name = f"{row.device.vendor} {row.device.part_number}"[:27]
        r = row.result
        if r is None:
            print(f"{name:<28}{'thermal runaway':>34}")
            continue
        peak = max(r.tj_switch_peak, r.tj_diode_peak)
        bound = "~" if r.tj_peak_range is not None else " "
        eff = f"{100 * r.efficiency:8.2f}" if r.efficiency is not None else f"{'-':>8}"
        print(f"{name:<28}{r.p_inverter:9.1f}{eff}{bound:>3}{peak:6.1f}{row.margin:8.1f}  {r.validity.value}")
    for row in rows:
        if row.result is not None and row.margin < 0:
            print(f"  {row.device.part_number}: over its junction temperature rating")
    from motionsim.propose import switching_footing

    print()
    for row in rows:
        print(
            f"  {row.device.vendor} {row.device.part_number}: switching loss {switching_footing(row.device, op).text}"
        )

    if args.sweep_fsw:
        low, high = (float(v) for v in args.sweep_fsw.split(":"))
        frequencies = np.linspace(low, high, 10)
        table = sweep_switching_frequency(devices, op, frequencies)
        print()
        print(f"{'fsw kHz':<10}" + "".join(f"{d.part_number[:14]:>16}" for d in devices))
        for j, f in enumerate(frequencies):
            cells = "".join(f"{'-':>16}" if np.isnan(v) else f"{v:16.1f}" for v in table[:, j])
            print(f"{f / 1000:<10.1f}{cells}")
        for a in range(len(devices)):
            for b in range(a + 1, len(devices)):
                f_cross = crossover(frequencies, table[a], table[b])
                if f_cross is not None:
                    print(
                        f"  {devices[a].part_number} and {devices[b].part_number} have equal loss "
                        f"near {f_cross / 1000:.1f} kHz"
                    )
    return 0


def _extract(args: argparse.Namespace) -> int:
    from motionsim.observe import save_observations
    from motionsim.observe.reader import MODEL, read_document, read_tables
    from motionsim.observe.verify import check

    document, pages = read_document(args.pdf)
    obs = check(read_tables(pages), document, pages, reader=MODEL)
    from motionsim.observe.digitise import digitise_curves  # needs the PDF libraries: only when a datasheet is read

    obs.curves = digitise_curves(args.pdf, obs)
    save_observations(obs, args.output)
    flagged = [o for o in obs.observations if o.flags]
    print(f"{obs.vendor} {obs.part_number} ({obs.technology}, {obs.topology.value})")
    if document.transcribed:
        print(
            f"  {len(document.transcribed)} of {document.pages} pages had no usable text and were read from their image"
        )
    print(f"  {len(obs.observations)} table values read, {len(flagged)} flagged")
    for o in flagged:
        for flag in o.flags:
            print(f"    - {o.quantity.value} (page {o.page}): {flag}")
    _print_curves(obs)
    print(f"  written to {args.output}")
    return 0


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


def _curves(args: argparse.Namespace) -> int:
    """Read the figures again for a datasheet whose tables are already read."""
    from motionsim.observe import load_observations, save_observations
    from motionsim.observe.ingest import read_pages

    document, _ = read_pages(args.pdf)
    obs = load_observations(args.observations)
    if document.sha256 != obs.document.sha256:
        print("this PDF is not the file the observations were read from", file=sys.stderr)
        return 1
    from motionsim.observe.digitise import digitise_curves  # needs the PDF libraries: only when a datasheet is read

    obs.curves = digitise_curves(args.pdf, obs)
    save_observations(obs, args.observations)
    _print_curves(obs)
    return 0


def _check(args: argparse.Namespace) -> int:
    from motionsim.observe import load_observations, save_observations
    from motionsim.observe.ingest import read_pages, with_transcripts
    from motionsim.observe.verify import recheck

    document, pages = read_pages(args.pdf)
    obs = load_observations(args.observations)
    if document.sha256 != obs.document.sha256:
        print("this PDF is not the file the observations were read from", file=sys.stderr)
        return 1
    obs = recheck(obs, with_transcripts(obs.document, pages))
    save_observations(obs, args.observations)
    flagged = [o for o in obs.observations if o.flags]
    print(f"  {len(obs.observations)} table values checked, {len(flagged)} flagged")
    for o in flagged:
        for flag in o.flags:
            print(f"    - {o.quantity.value} (page {o.page}): {flag}")
    return 0


def _build(args: argparse.Namespace) -> int:
    import yaml

    from motionsim.fit import MissingData, build_device
    from motionsim.fit.typed import Mistyped, from_figures, is_figures
    from motionsim.observe import load_observations

    try:
        with open(args.observations, encoding="utf-8") as f:
            typed = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        print(f"cannot read {args.observations}: {str(exc).splitlines()[0]}", file=sys.stderr)
        return 1
    try:
        # A file of figures typed in by hand (motionsim template device) is built directly.
        if is_figures(typed):
            device = from_figures(typed)
        else:
            device = build_device(load_observations(args.observations), allow_flagged=args.allow_flagged)
    except Mistyped as exc:
        print(f"cannot build a device: {exc}", file=sys.stderr)
        return 1
    except MissingData as exc:
        print(f"cannot build a device: {exc}", file=sys.stderr)
        return 1
    save_device(device, args.output)
    print(f"{device.vendor} {device.part_number}: device model written to {args.output}")
    return 0


def _design(args: argparse.Namespace) -> int:
    """A whole design from one file. Exit status: 0 the part passes, 3 it does not,
    2 the design was refused (the reason is in the output), 1 a fault of ours."""
    import json
    import tempfile
    from pathlib import Path

    import yaml

    from motionsim import design, page

    with tempfile.TemporaryDirectory() as folder:
        workspace = page.Workspace(Path(args.workspace) if args.workspace else Path(folder))
        try:
            if args.action == "init":
                key = design.bring_device(args.device, Path.cwd(), workspace)
                setup = design.starting_setup(key, workspace, args.motor)
                # As the user named it; a file is named in full, so the design finds it from wherever it is kept.
                setup["devices"] = [str(Path(args.device).resolve()) if Path(args.device).is_file() else args.device]
                text = design.SETUP_HEAD + yaml.safe_dump(setup, sort_keys=False, allow_unicode=True)
                if args.output:
                    Path(args.output).write_text(text, encoding="utf-8")
                    print(f"written to {args.output}: edit it, then `motionsim design run {args.output}`")
                else:
                    print(text, end="")
                return 0
            if args.verbose:
                import logging

                logging.basicConfig(level=logging.INFO, format="%(message)s")
            setup = design.load_setup(args.setup, workspace)
            steps = tuple(x for x in design.STEPS if x not in (args.skip or []))
            result = design.run(setup, workspace, steps=steps, traces=args.traces)
        except page.Refused as exc:
            refusal = {"outcome": "refused", "refused": exc.reason, "fix": exc.fix, "field": exc.field}
            print(
                json.dumps(refusal, indent=1)
                if getattr(args, "json", False)
                else f"refused: {exc.reason}" + (f"\n  {exc.fix}" if exc.fix else ""),
                file=sys.stdout if getattr(args, "json", False) else sys.stderr,
            )
            return 2
        report = design.markdown(result)
        try:
            if args.md:
                Path(args.md).write_text(report, encoding="utf-8")
            if args.csv:
                Path(args.csv).write_text(design.csv_text(result), encoding="utf-8")
        except OSError as exc:
            print(f"cannot write the report: {exc}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(page.finite(result), indent=1, default=float))
        elif not args.md:
            print(report, end="")
        else:
            print(f"{result['outcome']}: report written to {args.md}")
    # A step that could not be run is a design that cannot be run as written, whatever the rest says.
    if result.get("refusals"):
        return 2
    return {"refused": 2, "does not pass": 3, "undecided": 4}.get(result["outcome"], 0)


def _agent(args: argparse.Namespace) -> int:
    from pathlib import Path

    print((Path(__file__).parent / "AGENT_GUIDE.md").read_text(encoding="utf-8"), end="")
    return 0


def _print_result(device, r) -> None:
    print(f"  switch   conduction {r.switch.conduction:8.3f} W")
    print(f"           turn-on    {r.switch.turn_on:8.3f} W")
    print(f"           turn-off   {r.switch.turn_off:8.3f} W")
    if device.diode is None:
        print(f"           dead time  {r.switch.dead_time:8.3f} W")
        if device.switch.e_rr is not None:
            print(f"           recovery   {r.switch.recovery:8.3f} W")
    else:
        print(f"  diode    conduction {r.diode.conduction:8.3f} W")
        print(f"           recovery   {r.diode.recovery:8.3f} W")
    print(f"  power-stage loss    {r.p_inverter:8.2f} W")
    if r.efficiency is not None:
        print(f"  efficiency          {100 * r.efficiency:8.2f} %")
    assumed_note = " (assumed response)" if r.peak_basis.value == "assumed" else ""
    print(f"  Tj switch  average  {r.tj_switch:8.1f} °C   peak {r.tj_switch_peak:6.1f} °C{assumed_note}")
    if device.diode is not None:
        print(f"  Tj diode   average  {r.tj_diode:8.1f} °C   peak {r.tj_diode_peak:6.1f} °C{assumed_note}")
    print(f"  T case              {r.t_case:8.1f} °C")
    # The margin is to the top of the range, as every other answer counts it.
    top = max(r.tj_switch_peak, r.tj_diode_peak, *(r.tj_peak_range or ()))
    print(f"  margin to Tj max    {device.ratings.tj_max - top:8.1f} °C")
    if r.tj_peak_range is not None:
        low, high = r.tj_peak_range
        print(f"  hottest junction    {low:8.1f} to {high:.1f} °C across the thermal assumptions")
        for line in r.assumptions:
            print(f"    - {line}")
    print(f"  data support        {r.validity.value}")
    for note in r.notes:
        print(f"    - {note}")
    if len(r.roles) > 1:
        print("  by position (the figures above are for the hottest)")
        for role in r.roles:
            loss = role.switch.total + role.diode.total
            print(f"    - {role.count} x {role.name}: {loss:.3f} W each, peak {role.hottest:.1f} °C")
    print("  not modelled")
    for limit in r.limits:
        print(f"    - {limit}")
    if r.rating_warnings:
        print("  rating warnings")
        for warning in r.rating_warnings:
            print(f"    - {warning}")


def _figure(text: str) -> float:
    """A number given on the command line: a figure, not nan or inf."""
    import math

    value = float(text)
    if not math.isfinite(value):
        raise argparse.ArgumentTypeError(f"{text} is not a number")
    return value


def _above_zero(text: str) -> float:
    value = _figure(text)
    if value <= 0:
        raise argparse.ArgumentTypeError(f"has to be above zero, and {text} was given")
    return value


def _whole(text: str, low: int, high: int) -> int:
    value = int(text)
    if not low <= value <= high:
        raise argparse.ArgumentTypeError(f"has to be from {low} to {high}, and {text} was given")
    return value


def _repeats(text: str) -> int:
    return _whole(text, 1, 50)


def _count(text: str) -> int:
    return _whole(text, 1, 12)


def _port(text: str) -> int:
    return _whole(text, 1, 65535)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="motionsim",
        epilog="Exploratory tool: results are estimates and can be wrong. Verify by measurement "
        "before building anything. No warranty and no liability; see DISCLAIMER.md.",
    )
    parser.add_argument("--version", action="version", version=f"motionsim {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def conditions(p: argparse.ArgumentParser, *, many: bool = False, motor: bool = False) -> None:
        if many:
            p.add_argument("devices", nargs="+", help="device YAML files")
        else:
            p.add_argument("device", help="device YAML file")
        p.add_argument(
            "--pwm",
            choices=[m.value for m in Pwm],
            help="modulation scheme (default: sine, or the usual one for the motor type when a motor is given)",
        )
        p.add_argument("--vdc", type=_figure, required=True, help="DC-link voltage, V")
        if motor:
            p.add_argument("--motor", required=True, help="motor YAML file")
        else:
            p.add_argument("--m", type=_figure, required=True, help="modulation index, 0 to 1")
            p.add_argument("--pf", type=_figure, required=True, help="power factor")
            p.add_argument("--fout", type=_figure, default=50.0, help="output frequency, Hz (default 50)")
        p.add_argument("--fsw", type=_figure, required=True, help="switching frequency, Hz")
        p.add_argument("--tsink", type=_figure, help="heatsink temperature, °C, where it is known")
        p.add_argument("--tair", type=_figure, help="air temperature, °C, for cooling to air")
        p.add_argument(
            "--rth-heatsink",
            type=_figure,
            help="a heatsink in air: its thermal resistance, K/W, with every device on it",
        )
        p.add_argument(
            "--rth-case-sink",
            type=_figure,
            help="on a heatsink: one package's case-to-heatsink resistance as you mount it, K/W, where you know "
            "it. Left out, the device's own figure or one worked out for its package is used",
        )
        p.add_argument(
            "--interface",
            choices=["grease", "pad"],
            help="on a heatsink: the layer under the package (default: the device's, which is grease unless it says)",
        )
        p.add_argument(
            "--rth-ja",
            type=_figure,
            help="no heatsink: one package's junction-to-air resistance, K/W, from its datasheet",
        )
        p.add_argument(
            "--no-heatsink",
            action="store_true",
            help="no heatsink, at the usual junction-to-air figure for a TO-220, TO-247 or TO-263",
        )
        p.add_argument(
            "--board-area",
            type=_figure,
            help="no heatsink, soldered to one board: the board's area, cm². The packages then warm each other",
        )
        p.add_argument(
            "--copper", type=_figure, help="no heatsink, on a board: the copper each package has to itself, cm²"
        )
        p.add_argument(
            "--copper-ref",
            type=_figure,
            help="the copper area the datasheet's junction-to-air figure was taken on, cm² (default 6.45, one square inch)",
        )
        p.add_argument("--tdead", type=_figure, default=0.0, help="dead time, s (mosfets)")
        p.add_argument("--vdrive", type=_figure, help="gate drive voltage, V")
        p.add_argument("--rgon", type=_figure, help="total turn-on gate resistance, ohm")
        p.add_argument("--rgoff", type=_figure, help="total turn-off gate resistance, ohm")
        p.add_argument("--lloop", type=_figure, help="commutation-loop inductance, H")
        p.add_argument("--tmin", type=_figure, default=0.0, help="shortest pulse the gate drive passes, s")
        p.add_argument("--parallel", type=_count, default=1, help="devices side by side at each switch position")
        if motor:
            p.add_argument("--tmotor", type=_figure, help="winding temperature, °C (default: as the motor file gives)")

    sim = sub.add_parser("simulate", help="losses and temperatures at one operating point")
    conditions(sim)
    sim.add_argument("--irms", type=_figure, required=True, help="phase current, A rms")
    sim.set_defaults(func=_simulate)

    lim = sub.add_parser("max-current", help="phase current that reaches the junction limit")
    conditions(lim)
    lim.add_argument("--tj", type=_figure, help="junction temperature limit, °C (default: rating)")
    lim.add_argument("--average", action="store_true", help="limit the average junction temperature, not the peak")
    lim.set_defaults(func=_max_current)

    mot = sub.add_parser("motor", help="losses and temperatures at a motor speed and torque")
    conditions(mot, motor=True)
    mot.add_argument("--rpm", type=_figure, required=True, help="shaft speed, rpm")
    mot.add_argument("--torque", type=_figure, required=True, help="shaft torque, N·m")
    mot.set_defaults(func=_motor)

    mp = sub.add_parser("map", help="losses and temperatures over a speed-torque grid")
    conditions(mp, motor=True)
    mp.add_argument("--rpm", required=True, metavar="LOW:HIGH:N", help="speed range, rpm")
    mp.add_argument("--torque", required=True, metavar="LOW:HIGH:N", help="torque range, N·m")
    mp.add_argument("-o", "--output", help="CSV file for the full map")
    mp.set_defaults(func=_map)

    pro = sub.add_parser("propose", help="rank candidate devices for a motor and say why")
    conditions(pro, many=True, motor=True)
    pro.add_argument("--rpm", type=_figure, required=True, help="shaft speed at the design point, rpm")
    pro.add_argument("--torque", type=_figure, required=True, help="shaft torque at the design point, N·m")
    pro.set_defaults(func=_propose)

    trj = sub.add_parser("trajectory", help="losses and temperatures along currents and duty cycles from a file")
    trj.add_argument("device", help="device YAML file")
    trj.add_argument("trajectory", help="CSV: time_s, i_a, d_a, ... (see: motionsim template trajectory)")
    trj.add_argument("--vdc", type=_figure, required=True, help="DC-link voltage, V")
    trj.add_argument("--fsw", type=_figure, required=True, help="switching frequency, Hz")
    trj.add_argument("--tsink", type=_figure, required=True, help="heatsink temperature, °C")
    trj.add_argument("--tdead", type=_figure, default=0.0, help="dead time, s (mosfets)")
    trj.add_argument("--vdrive", type=_figure, help="gate drive voltage, V")
    trj.add_argument("--rgon", type=_figure, help="total turn-on gate resistance, ohm")
    trj.add_argument("--rgoff", type=_figure, help="total turn-off gate resistance, ohm")
    trj.add_argument("--lloop", type=_figure, help="commutation-loop inductance, H")
    trj.add_argument("-o", "--output", help="CSV file of temperature against time")
    trj.set_defaults(func=_trajectory)

    web = sub.add_parser("serve", help="open the local web page")
    web.add_argument("--port", type=_port, default=4310)
    web.add_argument("--devices", help="folder of device files (default: ~/.motionsim/devices)")
    web.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    web.add_argument(
        "--log-level",
        default="warning",
        choices=["debug", "info", "warning", "error"],
        help="what the terminal is told: faults with where they happened (default), or more",
    )
    web.set_defaults(func=lambda a: _serve(a))

    rec = sub.add_parser("recommend", help="starting values for gate resistors, dead time and heatsink")
    conditions(rec, motor=True)
    rec.add_argument("--rpm", type=_figure, required=True, help="shaft speed at the design point, rpm")
    rec.add_argument("--torque", type=_figure, required=True, help="shaft torque at the design point, N·m")
    rec.add_argument("--tambient", type=_figure, help="ambient temperature, °C, to size a heatsink")
    rec.add_argument(
        "--tsink-max",
        type=_figure,
        help="the most the heatsink may reach, °C (default 100: what is mounted on it gives out before a junction does)",
    )
    rec.add_argument("--dvdt", type=_above_zero, default=5.0, help="voltage slew-rate limit, V/ns (default 5)")
    rec.add_argument("--driver-peak", type=_figure, help="gate driver's peak output current, A")
    rec.add_argument(
        "--driver-mismatch",
        type=_figure,
        default=None,
        help="difference in propagation delay between gate-driver channels, s",
    )
    rec.set_defaults(func=_recommend)

    val = sub.add_parser("validate", help="compare the model with measurements or another simulator's results")
    val.add_argument("device", help="device YAML file")
    val.add_argument("reference", help="reference YAML file (see: motionsim template reference)")
    val.set_defaults(func=_validate)

    adv = sub.add_parser("advise", help="what kind of device to look for, from the motor and supply alone")
    adv.add_argument("--motor", required=True, help="motor YAML file")
    adv.add_argument("--vdc", type=_figure, required=True, help="DC-link voltage, V")
    adv.add_argument("--rpm", type=_figure, required=True, help="shaft speed at the design point, rpm")
    adv.add_argument("--torque", type=_figure, required=True, help="shaft torque at the design point, N·m")
    adv.add_argument("--fsw", type=_figure, required=True, help="switching frequency, Hz")
    adv.add_argument("--supply", choices=["one-way", "battery"], default="one-way")
    adv.set_defaults(func=_advise)

    cyc = sub.add_parser("cycle", help="a motor, its load and a motion, over the whole move")
    conditions(cyc, motor=True)
    cyc.add_argument("--load", required=True, help="load YAML file")
    cyc.add_argument("--profile", required=True, help="motion profile YAML file")
    cyc.add_argument("-o", "--output", help="CSV file of every instant")
    cyc.add_argument("--repeat", type=_repeats, default=1, help="run the motion this many times back to back")
    cyc.add_argument(
        "--rth-sink", type=_above_zero, help="heatsink to ambient, K/W (with --c-sink: the heatsink warms up)"
    )
    cyc.add_argument(
        "--c-sink", type=_above_zero, help="heatsink heat capacity, J/K (about 900 J/K per kg of aluminium)"
    )
    cyc.add_argument(
        "--tsink-max", type=_figure, help="the most the heatsink may reach when one is sized, °C (default 100)"
    )
    cyc.add_argument("--tambient", type=_figure, help="ambient temperature, °C (default: the starting --tsink)")
    cyc.add_argument("--clink", type=_above_zero, help="DC-link capacitance, F")
    cyc.add_argument(
        "--supply",
        choices=["one-way", "battery"],
        default="one-way",
        help="whether the supply can take braking energy back (default: one-way, it cannot)",
    )
    cyc.set_defaults(func=_cycle)

    pkg = sub.add_parser("package", help="thermal resistances computed for a generic package construction")
    pkg.add_argument("template", choices=["leadframe-module", "substrate-module", "TO-220", "TO-247", "TO-263"])
    pkg.add_argument("--irated", type=_above_zero, required=True, help="rated current of the switch, A")
    pkg.add_argument("--interface", default="grease", choices=["grease", "pad"])
    pkg.add_argument("--no-diode", action="store_true", help="discrete package with no diode chip")
    pkg.set_defaults(func=_package)

    tpl = sub.add_parser("template", help="write a parameter file to fill in")
    tpl.add_argument(
        "kind",
        choices=["device", "pmsm", "induction", "bldc", "dc", "stepper", "load", "profile", "reference", "trajectory"],
    )
    tpl.add_argument("-o", "--output", help="file to write (default: print)")
    tpl.set_defaults(func=_template)

    mea = sub.add_parser("measure", help="put double-pulse measurements into a device model")
    mea.add_argument("device", help="device YAML file")
    mea.add_argument("measurement", help="double-pulse JSON file")
    mea.add_argument("-o", "--output", required=True, help="device YAML to write")
    mea.set_defaults(func=_measure)

    cmp_ = sub.add_parser("compare", help="several devices at one operating point")
    conditions(cmp_, many=True)
    cmp_.add_argument("--irms", type=_figure, required=True, help="phase current, A rms")
    cmp_.add_argument("--sweep-fsw", metavar="LOW:HIGH", help="also sweep switching frequency, Hz, e.g. 2000:20000")
    cmp_.set_defaults(func=_compare)

    ext = sub.add_parser("extract", help="read tabulated values from a datasheet PDF")
    ext.add_argument("pdf")
    ext.add_argument("-o", "--output", required=True, help="observations YAML to write")
    ext.set_defaults(func=_extract)

    chk = sub.add_parser("check", help="re-run the checks on an observations file")
    chk.add_argument("observations")
    chk.add_argument("pdf")
    chk.set_defaults(func=_check)

    crv = sub.add_parser("curves", help="read a datasheet's figures again, keeping its table values")
    crv.add_argument("observations")
    crv.add_argument("pdf")
    crv.set_defaults(func=_curves)

    bld = sub.add_parser("build", help="build a device model from observations")
    bld.add_argument("observations")
    bld.add_argument("-o", "--output", required=True, help="device YAML to write")
    bld.add_argument("--allow-flagged", action="store_true", help="use flagged values too")
    bld.set_defaults(func=_build)

    dsn = sub.add_parser(
        "design", help="a whole design from one file, every step of the page: for a terminal or a coding agent"
    )
    actions = dsn.add_subparsers(dest="action", required=True)
    ini = actions.add_parser("init", help="write a design to start from, sized to a device")
    ini.add_argument(
        "--device",
        default="example-mosfet",
        help="a device file, a file of typed figures, or a made-up part: example-mosfet, example",
    )
    ini.add_argument(
        "--motor",
        help="kind of motor (default: the one usual with the device): pmsm, bldc, synrm, induction, dc, dc_series, stepper",
    )
    ini.add_argument("-o", "--output", help="file to write (default: print)")
    ini.add_argument("--workspace", help=argparse.SUPPRESS)
    ini.set_defaults(func=_design)
    go = actions.add_parser("run", help="run a design: fit, verdict, motion, what to build, what it can drive")
    go.add_argument("setup", help="the design file (YAML or JSON)")
    go.add_argument("--json", action="store_true", help="print everything as JSON, for a program or an agent to read")
    go.add_argument("--md", help="write the report in Markdown to this file")
    go.add_argument(
        "--csv",
        help="write the comparison as a table to this file: one row a device, and one a motor where several are compared",
    )
    go.add_argument(
        "--skip",
        action="append",
        choices=["fit", "motion", "build", "drive"],
        help="leave a step out (may be given more than once)",
    )
    go.add_argument("--traces", action="store_true", help="with --json: keep the motion's traces through time")
    go.add_argument("--workspace", help="a folder to keep the device files in (default: a temporary one)")
    go.add_argument(
        "-v", "--verbose", action="store_true", help="say on the terminal's error stream what each step took"
    )
    go.set_defaults(func=_design)

    agt = sub.add_parser("agent", help="print the guide for a coding agent that drives motionsim from the terminal")
    agt.set_defaults(func=_agent)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, ArithmeticError, RecursionError) as exc:
        # A file that is not there or is not what it is given as, a figure nothing can be
        # worked out from: said in a line, as the refusal it is.
        if isinstance(exc, OSError):
            said = f"{exc.strerror or exc}: {exc.filename}" if exc.filename else str(exc)
        else:
            from motionsim.page import reason_of

            said = reason_of(exc)
        print(f"cannot {args.command}: {said}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
