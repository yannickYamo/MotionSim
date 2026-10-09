from __future__ import annotations

import argparse
import sys

import numpy as np

from motionsim.device import load_device, save_device
from motionsim.engine import OperatingPoint, Pwm, ThermalRunaway, solve
from motionsim.engine.limits import max_current


def _pwm(args: argparse.Namespace) -> Pwm:
    """The scheme asked for; without one, the usual scheme for the motor, or sine."""
    if args.pwm is not None:
        return Pwm(args.pwm)
    if getattr(args, "motor", None):
        from motionsim.motor import load_machine

        return load_machine(args.motor).default_pwm
    return Pwm.sine


def _operating_point(args: argparse.Namespace, i_rms: float) -> OperatingPoint:
    return OperatingPoint(
        v_dc=args.vdc,
        i_rms=i_rms,
        modulation_index=getattr(args, "m", 0.0),
        power_factor=getattr(args, "pf", 1.0),
        f_sw=args.fsw,
        t_sink=args.tsink,
        f_out=getattr(args, "fout", 50.0),
        pwm=_pwm(args),
        t_dead=args.tdead,
        v_drive=args.vdrive,
        rg_on=args.rgon,
        rg_off=args.rgoff,
        l_loop=args.lloop,
    )


def _simulate(args: argparse.Namespace) -> int:
    device = load_device(args.device)
    try:
        r = solve(device, _operating_point(args, args.irms))
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
    i_max, r = max_current(
        device, _operating_point(args, 0.0), tj_limit=args.tj, peak=not args.average
    )
    print(f"{device.vendor} {device.part_number} ({device.technology})")
    print(f"  maximum current     {i_max:8.2f} A rms")
    if r is not None:
        _print_result(device, r)
    return 0


def _motor(args: argparse.Namespace) -> int:
    from motionsim.drivers import at_speed_and_torque
    from motionsim.motor import Unreachable, load_machine

    device, motor = load_device(args.device), load_machine(args.motor)
    try:
        point = at_speed_and_torque(
            device, motor, args.rpm, args.torque, _operating_point(args, 0.0)
        )
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

    _print_checks(guard.check(device, _operating_point(args, 0.0), point.result, st.i_peak))
    return 0


def _print_checks(checks, indent: str = "  ") -> None:
    from motionsim import guard

    word = {guard.Level.ok: "ok", guard.Level.caution: "CAUTION", guard.Level.fail: "FAIL"}
    print(f"{indent}checks: {word[guard.verdict(checks)]}")
    for c in checks:
        print(f"{indent}  [{word[c.level]:>7}] {c.topic}: {c.message}")


def _propose(args: argparse.Namespace) -> int:
    from motionsim import guard
    from motionsim.motor import Unreachable, load_machine
    from motionsim.propose import explain, propose

    devices = [load_device(path) for path in args.devices]
    motor = load_machine(args.motor)
    try:
        candidates = propose(devices, motor, args.rpm, args.torque, _operating_point(args, 0.0))
    except Unreachable as exc:
        print(f"the motor cannot run at this point: {exc}", file=sys.stderr)
        return 1
    word = {guard.Level.ok: "ok", guard.Level.caution: "caution", guard.Level.fail: "FAIL"}
    print(f"{motor.name} ({motor.type}): {args.torque:g} N·m at {args.rpm:g} rpm from {args.vdc:g} V")
    print()
    print(f"{'device':<28}{'loss W':>9}{'Tj peak':>9}{'at stall':>10}  verdict")
    for c in candidates:
        name = f"{c.device.vendor} {c.device.part_number}"[:27]
        if c.design is None:
            print(f"{name:<28}{'-':>9}{'-':>9}{'-':>10}  FAIL")
            continue
        peak = max(c.design.result.tj_switch_peak, c.design.result.tj_diode_peak)
        stall = "-" if c.stall is None else f"{max(c.stall.result.tj_switch_peak, c.stall.result.tj_diode_peak):.0f}"
        print(f"{name:<28}{c.loss:9.1f}{peak:9.0f}{stall:>10}  {word[c.level]}")
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
        v_dc=args.vdc, i_rms=0.0, modulation_index=0.0, power_factor=1.0, f_sw=args.fsw,
        t_sink=args.tsink, t_dead=args.tdead, v_drive=args.vdrive, rg_on=args.rgon,
        rg_off=args.rgoff, l_loop=args.lloop,
    )
    try:
        outcome = run(device, trajectory, op)
    except (ThermalRunaway, ValueError) as exc:
        print(f"cannot simulate: {exc}", file=sys.stderr)
        return 1
    r = outcome.result
    i_peak = max(float(np.abs(i).max()) for i in trajectory.current.values())
    print(f"{device.vendor} {device.part_number} ({device.technology}) along {args.trajectory}")
    print(f"  duration            {trajectory.duration:8.4g} s, {len(trajectory.legs)} legs, "
          f"peak current {i_peak:.3g} A")
    print("  taking the trajectory to repeat without end")
    _print_result(device, r)
    print(f"  run once from a heatsink-temperature start, the hottest junction reaches "
          f"{outcome.peak_from_start:.1f} °C")
    _print_checks(guard.check(device, op, r, i_peak))
    if args.output:
        import csv

        with open(args.output, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["time_s", "tj_hottest_from_start_c"])
            w.writerows(zip(outcome.time, outcome.tj_from_start))
        print(f"  temperature against time written to {args.output}")
    return 0


def _serve(args: argparse.Namespace) -> int:
    from motionsim.server import serve

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
    from motionsim.motor import Unreachable, load_machine

    device, motor = load_device(args.device), load_machine(args.motor)
    base = _operating_point(args, 0.0)
    try:
        stage = motor.stage(args.rpm, args.torque, base.v_dc, base.pwm)
    except Unreachable as exc:
        print(f"the motor cannot run at this point: {exc}", file=sys.stderr)
        return 1
    print(f"{device.vendor} {device.part_number} driving {motor.name}: "
          f"{args.torque:g} N·m at {args.rpm:g} rpm from {args.vdc:g} V")
    print("Starting values for a first prototype. Settle them on the bench.")
    print()
    _print_recommendation(recommend.gate_resistors(
        device, base, stage.i_peak, dvdt_max=args.dvdt * 1e9, driver_peak=args.driver_peak,
    ))
    _print_recommendation(recommend.dead_time(device, base, driver_mismatch=args.driver_mismatch))

    def evaluate(t_sink: float) -> tuple[float, float]:
        worst, loss = float("-inf"), 0.0
        for rpm in (args.rpm, 0.0):  # the design point, and holding the same torque at standstill
            try:
                point = at_speed_and_torque(device, motor, rpm, args.torque, replace(base, t_sink=t_sink))
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
                point = at_speed_and_torque(
                    device, motor, args.rpm, args.torque, replace(base, pwm=scheme)
                )
                losses[scheme.value] = point.result.p_inverter
            except (Unreachable, ThermalRunaway, ValueError):
                continue
    _print_recommendation(recommend.modulation(losses, motor.default_pwm.value))

    if args.tambient is None:
        print("heatsink")
        print("  - give the ambient temperature (--tambient) to size a heatsink")
    else:
        _print_recommendation(recommend.heatsink(device, args.tambient, evaluate))
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
    print(f"{'point':>5} {'quantity':<10}{'model':>10}{'reference':>11}{'difference':>12}")
    numbers = {id(p): k for k, p in enumerate(reference.points, start=1)}
    for row in rows:
        unit = "W" if row.quantity.startswith("p_") else "°C"
        shown = f"{row.relative:+.1%}" if unit == "W" else f"{row.difference:+.1f} K"
        print(
            f"{numbers[id(row.point)]:>5} {row.quantity:<10}{row.model:>9.2f} {unit:<2}"
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
    from motionsim.motor import Unreachable, load_machine

    motor = load_machine(args.motor)
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

    low, high, count = text.split(":")
    return np.linspace(float(low), float(high), int(count))


def _map(args: argparse.Namespace) -> int:
    import numpy as np

    from motionsim.drivers import speed_torque_map
    from motionsim.motor import load_machine

    device, motor = load_device(args.device), load_machine(args.motor)
    try:
        m = speed_torque_map(
            device, motor, _grid(args.rpm), _grid(args.torque), _operating_point(args, 0.0)
        )
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
                    w.writerow([n, t, m.i_peak[a, b], m.p_inverter[a, b], m.tj_peak[a, b],
                                m.efficiency[a, b], m.reason[a][b]])
        print(f"full map written to {args.output}")
    return 0


def _package(args: argparse.Namespace) -> int:
    import numpy as np

    from motionsim.package import build, summarise

    print(f"{args.template}, {args.irated:g} A switch, on {args.interface}")
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
        for name, row in zip(names, np.round(model.matrix(), 3)):
            print(f"  {name:<10}" + "".join(f"{v:9.3f}" for v in row))
    return 0


def _template(args: argparse.Namespace) -> int:
    from motionsim.load import LOAD_TEMPLATE, PROFILE_TEMPLATE
    from motionsim.motor import TEMPLATES
    from motionsim.reference import TEMPLATE as REFERENCE_TEMPLATE
    from motionsim.trajectory import example

    text = {
        **TEMPLATES, "load": LOAD_TEMPLATE, "profile": PROFILE_TEMPLATE,
        "reference": REFERENCE_TEMPLATE, "trajectory": example(),
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
    from motionsim.motor import load_machine
    from motionsim.transient import Heatsink, follow

    device, motor = load_device(args.device), load_machine(args.motor)
    load, profile = load_load(args.load), load_profile(args.profile)
    base = _operating_point(args, 0.0)
    heatsink = None
    if args.rth_sink is not None or args.c_sink is not None:
        if args.rth_sink is None or args.c_sink is None:
            print("a heatsink needs both --rth-sink and --c-sink", file=sys.stderr)
            return 1
        ambient = args.tsink if args.tambient is None else args.tambient
        heatsink = Heatsink(rth=args.rth_sink, capacity=args.c_sink, t_ambient=ambient)
    try:
        cycle, trace = follow(
            device, motor, load, profile, base, heatsink=heatsink, repeats=args.repeat
        )
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
                device, motor, load, profile, replace(base, t_sink=t_sink), repeats=args.repeat
            )
            return temperatures.peak + spread, moved.mean_loss

        needed = recommend.heatsink(device, args.tambient, evaluate)
        print("  heatsink for this motion repeated without pause")
        for line in needed.lines:
            print(f"    - {line}")
    if args.output:
        import csv

        with open(args.output, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["time_s", "motor_rpm", "motor_torque_nm", "p_stage_w", "p_dc_w",
                        "tj_c", "tj_if_held_forever_c", "t_sink_c", "problem"])
            start = len(trace.time) - count
            for k, s in enumerate(cycle.steps):
                row = [f"{trace.time[start + k]:.6g}", s.sample.motor_rpm, s.sample.motor_torque]
                if s.point is None:
                    row += ["", ""]
                else:
                    row += [s.point.result.p_inverter,
                            s.point.stage.p_electrical + s.point.result.p_inverter]
                row += [trace.tj[start + k], trace.steady[start + k], trace.t_sink[start + k],
                        s.problem or ""]
                w.writerow(row)
        print(f"  every instant written to {args.output}")
    return 0


def _measure(args: argparse.Namespace) -> int:
    from pathlib import Path

    from motionsim.measured import apply_double_pulse, load_double_pulse

    try:
        device = apply_double_pulse(
            load_device(args.device), load_double_pulse(args.measurement),
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
        print(
            f"{name:<28}{r.p_inverter:9.1f}{eff}{bound:>3}{peak:6.1f}{row.margin:8.1f}  "
            f"{r.validity.value}"
        )
    for row in rows:
        if row.result is not None and row.margin < 0:
            print(f"  {row.device.part_number}: over its junction temperature rating")

    if args.sweep_fsw:
        low, high = (float(v) for v in args.sweep_fsw.split(":"))
        frequencies = np.linspace(low, high, 10)
        table = sweep_switching_frequency(devices, op, frequencies)
        print()
        print(f"{'fsw kHz':<10}" + "".join(f"{d.part_number[:14]:>16}" for d in devices))
        for j, f in enumerate(frequencies):
            cells = "".join(
                f"{'-':>16}" if np.isnan(v) else f"{v:16.1f}" for v in table[:, j]
            )
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
    obs.curves = _digitise_curves(args.pdf, obs)
    save_observations(obs, args.output)
    flagged = [o for o in obs.observations if o.flags]
    print(f"{obs.vendor} {obs.part_number} ({obs.technology}, {obs.topology.value})")
    if document.transcribed:
        print(f"  {len(document.transcribed)} of {document.pages} pages had no usable text and were read from their image")
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
    obs.curves = _digitise_curves(args.pdf, obs)
    save_observations(obs, args.observations)
    _print_curves(obs)
    return 0


def _digitise_curves(pdf_path: str, obs) -> list:
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
        digitise_normalised_resistance,
        digitise_gate_resistance,
        is_family,
        is_gate_resistance,
        is_normalised_resistance,
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
                f for f in listed
                if is_thermal(f) or is_family(f) or is_normalised_resistance(f) or is_gate_resistance(f)
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
                    f for f in frames
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
    from motionsim.fit import MissingData, build_device
    from motionsim.observe import load_observations

    try:
        device = build_device(load_observations(args.observations), allow_flagged=args.allow_flagged)
    except MissingData as exc:
        print(f"cannot build a device: {exc}", file=sys.stderr)
        return 1
    save_device(device, args.output)
    print(f"{device.vendor} {device.part_number}: device model written to {args.output}")
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
    margin = device.ratings.tj_max - max(r.tj_switch_peak, r.tj_diode_peak)
    print(f"  margin to Tj max    {margin:8.1f} °C")
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
            print(
                f"    - {role.count} x {role.name}: {loss:.3f} W each, "
                f"peak {role.hottest:.1f} °C"
            )
    print("  not modelled")
    for limit in r.limits:
        print(f"    - {limit}")
    if r.rating_warnings:
        print("  rating warnings")
        for warning in r.rating_warnings:
            print(f"    - {warning}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="motionsim",
        epilog="Exploratory tool: results are estimates and can be wrong. Verify by measurement "
        "before building anything. No warranty and no liability; see DISCLAIMER.md.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def conditions(p: argparse.ArgumentParser, *, many: bool = False, motor: bool = False) -> None:
        if many:
            p.add_argument("devices", nargs="+", help="device YAML files")
        else:
            p.add_argument("device", help="device YAML file")
        p.add_argument(
            "--pwm", choices=[m.value for m in Pwm],
            help="modulation scheme (default: sine, or the usual one for the motor type "
            "when a motor is given)"
        )
        p.add_argument("--vdc", type=float, required=True, help="DC-link voltage, V")
        if motor:
            p.add_argument("--motor", required=True, help="motor YAML file")
        else:
            p.add_argument("--m", type=float, required=True, help="modulation index, 0 to 1")
            p.add_argument("--pf", type=float, required=True, help="power factor")
            p.add_argument(
                "--fout", type=float, default=50.0, help="output frequency, Hz (default 50)"
            )
        p.add_argument("--fsw", type=float, required=True, help="switching frequency, Hz")
        p.add_argument("--tsink", type=float, required=True, help="heatsink temperature, °C")
        p.add_argument("--tdead", type=float, default=0.0, help="dead time, s (mosfets)")
        p.add_argument("--vdrive", type=float, help="gate drive voltage, V")
        p.add_argument("--rgon", type=float, help="total turn-on gate resistance, ohm")
        p.add_argument("--rgoff", type=float, help="total turn-off gate resistance, ohm")
        p.add_argument("--lloop", type=float, help="commutation-loop inductance, H")

    sim = sub.add_parser("simulate", help="losses and temperatures at one operating point")
    conditions(sim)
    sim.add_argument("--irms", type=float, required=True, help="phase current, A rms")
    sim.set_defaults(func=_simulate)

    lim = sub.add_parser("max-current", help="phase current that reaches the junction limit")
    conditions(lim)
    lim.add_argument("--tj", type=float, help="junction temperature limit, °C (default: rating)")
    lim.add_argument(
        "--average", action="store_true", help="limit the average junction temperature, not the peak"
    )
    lim.set_defaults(func=_max_current)

    mot = sub.add_parser("motor", help="losses and temperatures at a motor speed and torque")
    conditions(mot, motor=True)
    mot.add_argument("--rpm", type=float, required=True, help="shaft speed, rpm")
    mot.add_argument("--torque", type=float, required=True, help="shaft torque, N·m")
    mot.set_defaults(func=_motor)

    mp = sub.add_parser("map", help="losses and temperatures over a speed-torque grid")
    conditions(mp, motor=True)
    mp.add_argument("--rpm", required=True, metavar="LOW:HIGH:N", help="speed range, rpm")
    mp.add_argument("--torque", required=True, metavar="LOW:HIGH:N", help="torque range, N·m")
    mp.add_argument("-o", "--output", help="CSV file for the full map")
    mp.set_defaults(func=_map)

    pro = sub.add_parser("propose", help="rank candidate devices for a motor and say why")
    conditions(pro, many=True, motor=True)
    pro.add_argument("--rpm", type=float, required=True, help="shaft speed at the design point, rpm")
    pro.add_argument("--torque", type=float, required=True, help="shaft torque at the design point, N·m")
    pro.set_defaults(func=_propose)

    trj = sub.add_parser(
        "trajectory", help="losses and temperatures along currents and duty cycles from a file"
    )
    trj.add_argument("device", help="device YAML file")
    trj.add_argument("trajectory", help="CSV: time_s, i_a, d_a, ... (see: motionsim template trajectory)")
    trj.add_argument("--vdc", type=float, required=True, help="DC-link voltage, V")
    trj.add_argument("--fsw", type=float, required=True, help="switching frequency, Hz")
    trj.add_argument("--tsink", type=float, required=True, help="heatsink temperature, °C")
    trj.add_argument("--tdead", type=float, default=0.0, help="dead time, s (mosfets)")
    trj.add_argument("--vdrive", type=float, help="gate drive voltage, V")
    trj.add_argument("--rgon", type=float, help="total turn-on gate resistance, ohm")
    trj.add_argument("--rgoff", type=float, help="total turn-off gate resistance, ohm")
    trj.add_argument("--lloop", type=float, help="commutation-loop inductance, H")
    trj.add_argument("-o", "--output", help="CSV file of temperature against time")
    trj.set_defaults(func=_trajectory)

    web = sub.add_parser("serve", help="open the local web page")
    web.add_argument("--port", type=int, default=4310)
    web.add_argument("--devices", help="folder of device files (default: ~/.motionsim/devices)")
    web.add_argument("--no-browser", action="store_true", help="do not open a browser window")
    web.set_defaults(func=lambda a: _serve(a))

    rec = sub.add_parser(
        "recommend", help="starting values for gate resistors, dead time and heatsink"
    )
    conditions(rec, motor=True)
    rec.add_argument("--rpm", type=float, required=True, help="shaft speed at the design point, rpm")
    rec.add_argument("--torque", type=float, required=True, help="shaft torque at the design point, N·m")
    rec.add_argument("--tambient", type=float, help="ambient temperature, °C, to size a heatsink")
    rec.add_argument("--dvdt", type=float, default=5.0, help="voltage slew-rate limit, V/ns (default 5)")
    rec.add_argument("--driver-peak", type=float, help="gate driver's peak output current, A")
    rec.add_argument("--driver-mismatch", type=float, default=0.0,
                     help="difference in propagation delay between gate-driver channels, s")
    rec.set_defaults(func=_recommend)

    val = sub.add_parser(
        "validate", help="compare the model with measurements or another simulator's results"
    )
    val.add_argument("device", help="device YAML file")
    val.add_argument("reference", help="reference YAML file (see: motionsim template reference)")
    val.set_defaults(func=_validate)

    adv = sub.add_parser(
        "advise", help="what kind of device to look for, from the motor and supply alone"
    )
    adv.add_argument("--motor", required=True, help="motor YAML file")
    adv.add_argument("--vdc", type=float, required=True, help="DC-link voltage, V")
    adv.add_argument("--rpm", type=float, required=True, help="shaft speed at the design point, rpm")
    adv.add_argument("--torque", type=float, required=True, help="shaft torque at the design point, N·m")
    adv.add_argument("--fsw", type=float, required=True, help="switching frequency, Hz")
    adv.add_argument("--supply", choices=["one-way", "battery"], default="one-way")
    adv.set_defaults(func=_advise)

    cyc = sub.add_parser("cycle", help="a motor, its load and a motion, over the whole move")
    conditions(cyc, motor=True)
    cyc.add_argument("--load", required=True, help="load YAML file")
    cyc.add_argument("--profile", required=True, help="motion profile YAML file")
    cyc.add_argument("-o", "--output", help="CSV file of every instant")
    cyc.add_argument("--repeat", type=int, default=1, help="run the motion this many times back to back")
    cyc.add_argument("--rth-sink", type=float, help="heatsink to ambient, K/W (with --c-sink: the heatsink warms up)")
    cyc.add_argument("--c-sink", type=float, help="heatsink heat capacity, J/K (about 900 J/K per kg of aluminium)")
    cyc.add_argument("--tambient", type=float, help="ambient temperature, °C (default: the starting --tsink)")
    cyc.add_argument("--clink", type=float, help="DC-link capacitance, F")
    cyc.add_argument(
        "--supply", choices=["one-way", "battery"], default="one-way",
        help="whether the supply can take braking energy back (default: one-way, it cannot)",
    )
    cyc.set_defaults(func=_cycle)

    pkg = sub.add_parser(
        "package", help="thermal resistances computed for a generic package construction"
    )
    pkg.add_argument("template", choices=["leadframe-module", "substrate-module", "TO-220", "TO-247", "TO-263"])
    pkg.add_argument("--irated", type=float, required=True, help="rated current of the switch, A")
    pkg.add_argument("--interface", default="grease", choices=["grease", "pad"])
    pkg.add_argument("--no-diode", action="store_true", help="discrete package with no diode chip")
    pkg.set_defaults(func=_package)

    tpl = sub.add_parser("template", help="write a parameter file to fill in")
    tpl.add_argument(
        "kind",
        choices=["pmsm", "induction", "bldc", "dc", "stepper", "load", "profile", "reference",
                 "trajectory"],
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
    cmp_.add_argument("--irms", type=float, required=True, help="phase current, A rms")
    cmp_.add_argument(
        "--sweep-fsw", metavar="LOW:HIGH", help="also sweep switching frequency, Hz, e.g. 2000:20000"
    )
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

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
