"""Rank candidate devices for a motor and say why."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil

from motionsim import guard
from motionsim.device.schema import Device
from motionsim.drivers import MotorPoint, at_speed_and_torque
from motionsim.engine.limits import hottest
from motionsim.engine.solver import OperatingPoint, ThermalRunaway
from motionsim.motor.stage import Unreachable
from motionsim.text import written

LEVEL = 0.05  # two losses closer than this share of the lower one are not told apart


@dataclass(frozen=True)
class Footing:
    """What a device's switching loss rests on, so that two devices can be seen to be like
    for like or not."""

    kind: str  # "measured", "from charge" or "none"
    text: str  # one line: the test conditions, and how they were brought to these
    stretched: bool = False  # brought to a higher voltage than tested, in proportion


def _ohms(on: float | None, off: float | None) -> str:
    if on is None:
        return ""
    return f"{on:g} Ω" if off in (None, on) else f"{on:g} Ω on, {off:g} Ω off"


def switching_footing(device: Device, op: OperatingPoint) -> Footing:
    """One line on where this device's switching loss comes from at these conditions."""
    sw = device.switch
    if sw.e_on is None or sw.e_off is None:
        if sw.charge is None:
            return Footing("none", "no switching data")
        drive = "" if op.v_drive is None else f" at {op.v_drive:g} V drive"
        gate = _ohms(op.rg_on, op.rg_off)
        return Footing(
            "from charge",
            "estimated from gate and output charge" + (f", with {gate}{drive}" if gate else ""),
        )
    table = sw.e_on
    test = [f"{table.v_ref:g} V"]
    tested = _ohms(table.rg, sw.e_off.rg)
    if tested:
        test.append(tested)
    if table.gate_voltage is not None:
        test.append(f"{table.gate_voltage:g} V gate")
    text = "measured at " + ", ".join(test)
    stretched = False
    if abs(op.v_dc - table.v_ref) > 0.01 * table.v_ref:
        if table.v_values and table.v_values[0] <= op.v_dc <= table.v_values[-1]:
            text += f"; brought to {op.v_dc:g} V along the datasheet's figure"
        else:
            stretched = op.v_dc > table.v_ref
            text += f"; brought to {op.v_dc:g} V in proportion"
    if device.package.integrated_driver:
        return Footing("measured", text + "; gate drive built in", stretched)
    if op.rg_on is not None and table.rg is not None and abs(op.rg_on - table.rg) > 0.01 * table.rg:
        if table.rg_values and table.rg_factor:
            text += f"; brought to {_ohms(op.rg_on, op.rg_off)} along the datasheet's figure"
        else:
            text += "; your gate resistor is not applied, for want of a figure against it"
    return Footing("measured", text, stretched)


def _room(device: Device, point: MotorPoint | None) -> float | None:
    """K left to the junction limit, counted from the top of the range where there is one."""
    if point is None:
        return None
    r = point.result
    top = r.tj_peak_range[1] if r.tj_peak_range is not None else hottest(r)
    return device.ratings.tj_max - top


@dataclass(frozen=True)
class Candidate:
    device: Device
    design: MotorPoint | None
    stall: MotorPoint | None
    checks: list[guard.Check]  # design point and stall together
    problem: str | None  # why it could not be evaluated at all
    needs: list[str] = field(default_factory=list)  # what else the design must provide
    op: OperatingPoint | None = None  # the conditions it was run at, gate drive included
    footing: Footing | None = None

    @property
    def name(self) -> str:
        return f"{self.device.vendor} {self.device.part_number}"

    @property
    def margin(self) -> float | None:
        """K left to the junction limit at the design point."""
        return _room(self.device, self.design)

    @property
    def stall_margin(self) -> float | None:
        """K left to the junction limit holding the same torque at standstill."""
        return _room(self.device, self.stall)

    @property
    def level(self) -> guard.Level:
        return guard.Level.fail if self.problem else guard.verdict(self.checks)

    @property
    def loss(self) -> float:
        return self.design.result.p_inverter if self.design else float("inf")


def _point(device, motor, rpm, torque, base) -> tuple[MotorPoint | None, str | None]:
    try:
        return at_speed_and_torque(device, motor, rpm, torque, base), None
    except ThermalRunaway:
        return None, "no stable temperature: losses grow faster than the heat can leave"
    except Unreachable:
        raise
    except ValueError as exc:
        return None, str(exc)


def requirements(device: Device, positions: int, base: OperatingPoint) -> list[str]:
    """What a device asks of the rest of the design: how many packages, and its gate drive."""
    per_package = device.package.topology.positions
    side_by_side = max(int(base.parallel), 1)
    packages = ceil(positions / per_package) * side_by_side
    spare = packages * per_package - positions * side_by_side
    count = f"{packages} package{'s' if packages > 1 else ''} for the {positions} switches"
    if side_by_side > 1:
        count += f", {side_by_side} in parallel at each"
    if spare:
        count += f" ({spare} switch{'es' if spare > 1 else ''} left unused)"
    needs = [count]
    if device.package.integrated_driver:
        needs.append("gate drivers are inside the package")
        return needs
    needs.append(
        f"{positions} gate-driver channels, {positions // 2} of them for high-side switches "
        "that need a floating supply (bootstrap or isolated)"
    )
    charge = device.switch.charge
    if charge is not None and base.v_drive is not None:
        power = (charge.q_gs + charge.q_gd) * base.v_drive * base.f_sw
        line = f"each channel delivers at least {written(power * 1e3, 3)} mW of gate power"
        if base.rg_on:
            peak = base.v_drive / base.rg_on  # at the first instant the whole drive voltage is across it
            line += f" and about {written(peak, 2)} A at turn-on"
        needs.append(line)
    return needs


def propose(
    devices: list[Device],
    motor,
    rpm: float,
    torque: float,
    base: OperatingPoint,
    *,
    tune=None,
) -> list[Candidate]:
    """Candidates ranked: those that pass every check by loss, then the failures.

    Each device is checked at the design point and at standstill with the same
    torque. Standstill is where a robot joint or a loaded start sits, and where
    one switch carries the current without the relief of a rotating field.
    """
    shared = base
    out = []
    for device in devices:
        # tune completes the conditions for one device: its own gate drive, where the
        # user left that open.
        base = tune(device) if tune is not None else shared
        design, problem = _point(device, motor, rpm, torque, base)
        checks: list[guard.Check] = []
        stall = None
        if design is not None:
            checks += guard.check(device, base, design.result, design.stage.i_peak)
            checks += guard.ripple_checks(design, base)
            tripped = guard.trip_check(motor, rpm, base.v_dc, device.ratings.v_max)
            if tripped is not None:
                checks.append(tripped)
            try:
                stall, stall_problem = _point(device, motor, 0.0, torque, base)
            except Unreachable:
                stall, stall_problem = None, None
            if stall_problem:
                checks.append(guard.Check(guard.Level.fail, "standstill", f"at standstill: {stall_problem}"))
            elif stall is not None:
                for c in guard.check(device, base, stall.result, stall.stage.i_peak):
                    if c.topic == "temperature" and c.level is not guard.Level.ok:
                        checks.append(
                            guard.Check(c.level, "standstill", f"holding this torque at standstill: {c.message}")
                        )
        needs = [] if design is None else requirements(device, sum(r.count for r in design.stage.roles), base)
        out.append(Candidate(device, design, stall, checks, problem, needs, base, switching_footing(device, base)))
    # Those that pass first, then those the data cannot decide, then those that fail; by loss within each.
    return sorted(out, key=lambda c: (c.level is guard.Level.fail, c.level is guard.Level.undecided, c.loss))


def level_with_best(candidates: list[Candidate]) -> list[Candidate]:
    """The candidates that pass and lose so nearly what the best one loses that the model does
    not tell them apart. The best is among them; alone, when it leads clearly."""
    usable = [c for c in candidates if c.level is not guard.Level.fail]
    if not usable:
        return []
    least = min(c.loss for c in usable)
    return [c for c in usable if c.loss <= least * (1 + LEVEL)]


def _unlike(usable: list[Candidate]) -> list[str]:
    """Sentences on where the candidates' switching figures are not like for like."""
    lines = []
    kinds = {c.footing.kind for c in usable if c.footing is not None}
    if {"measured", "from charge"} <= kinds:
        measured = [c.name for c in usable if c.footing.kind == "measured"]
        charge = [c.name for c in usable if c.footing.kind == "from charge"]
        lines.append(
            f"The switching loss of {_and(measured)} is measured and that of {_and(charge)} is "
            "estimated from charge: the order between them rests on unlike data."
        )
    stretched = [c.name for c in usable if c.footing is not None and c.footing.stretched]
    if stretched and len(stretched) < len(usable):
        lines.append(
            f"The switching loss of {_and(stretched)} is brought in proportion to a higher voltage "
            "than it was measured at, and is likely stated low against the others."
        )
    return lines


def _span(low: float, high: float) -> str:
    return f"{low:.1f}" if f"{low:.1f}" == f"{high:.1f}" else f"{low:.1f} to {high:.1f}"


def _and(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def explain(candidates: list[Candidate]) -> list[str]:
    """Plain sentences on the ranking."""
    usable = [c for c in candidates if c.level is not guard.Level.fail]
    lines = []
    if not usable:
        lines.append("None of these devices passes every check at this operating point.")
    else:
        best = usable[0]
        name = best.name
        level = [c for c in level_with_best(candidates) if c is not best]
        if level:
            lines.append(
                f"{_and([name] + [c.name for c in level])} lose within {LEVEL:.0%} of each other "
                f"({_span(best.loss, max(c.loss for c in level))} W): on loss they are level, "
                "and something else has to decide."
            )
        else:
            lines.append(f"{name} has the lowest power-stage loss among the devices that pass: {best.loss:.1f} W.")
        if best.level is guard.Level.caution:
            lines.append(f"{name} passes with cautions, listed below; read them before relying on it.")
        if best.level is guard.Level.undecided:
            lines.append(
                f"{name} is not decided by this data: its temperature range crosses the rating. "
                "The check below says what would settle it."
            )
        if not best.device.package.integrated_driver:
            built_in = [c for c in usable[1:] if c.device.package.integrated_driver]
            if built_in:
                other = built_in[0]
                lines.append(
                    f"It needs separate gate drivers. {other.name} has them built in, for "
                    f"{other.loss - best.loss:.1f} W more loss."
                )
        for other in usable[1:]:
            if other in level:
                continue
            extra = other.loss - best.loss
            share = f" ({extra / best.loss:.0%})" if best.loss > 0 else ""
            lines.append(f"{other.name} loses {extra:.1f} W more{share}.")
        # Loss is not the only thing to choose on: the room left to the junction limit is
        # what a hot day, a blocked fan or a harder load is paid from.
        for what, room in (
            ("at the design point", lambda c: c.margin),
            ("holding the torque at standstill", lambda c: c.stall_margin),
        ):
            known = [c for c in usable if room(c) is not None]
            if len(known) < 2 or room(best) is None:
                continue
            roomiest = max(known, key=room)
            if roomiest is not best and room(roomiest) - room(best) >= 5:
                lines.append(
                    f"{roomiest.name} has {room(roomiest) - room(best):.0f} °C more margin to its junction "
                    f"limit {what} ({room(roomiest):.0f} °C against {room(best):.0f} °C)."
                )
        lines += _unlike(usable)
    for c in candidates:
        if c.level is guard.Level.fail:
            reason = c.problem or "; ".join(k.message for k in c.checks if k.level is guard.Level.fail)
            lines.append(f"{c.device.vendor} {c.device.part_number} is ruled out: {reason}.")
    return lines
