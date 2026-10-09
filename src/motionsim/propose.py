"""Rank candidate devices for a motor and say why."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil

from motionsim import guard
from motionsim.device.schema import Device
from motionsim.drivers import MotorPoint, at_speed_and_torque
from motionsim.engine.solver import OperatingPoint, ThermalRunaway
from motionsim.motor.stage import Unreachable


@dataclass(frozen=True)
class Candidate:
    device: Device
    design: MotorPoint | None
    stall: MotorPoint | None
    checks: list[guard.Check]  # design point and stall together
    problem: str | None  # why it could not be evaluated at all
    needs: list[str] = field(default_factory=list)  # what else the design must provide

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
        line = f"each channel delivers at least {power * 1e3:.3g} mW of gate power"
        if base.rg_on:
            peak = base.v_drive / base.rg_on  # at the first instant the whole drive voltage is across it
            line += f" and about {peak:.2g} A at turn-on"
        needs.append(line)
    return needs


def propose(
    devices: list[Device], motor, rpm: float, torque: float, base: OperatingPoint,
    *, tune=None,
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
            try:
                stall, stall_problem = _point(device, motor, 0.0, torque, base)
            except Unreachable:
                stall, stall_problem = None, None
            if stall_problem:
                checks.append(guard.Check(guard.Level.fail, "standstill", f"at standstill: {stall_problem}"))
            elif stall is not None:
                for c in guard.check(device, base, stall.result, stall.stage.i_peak):
                    if c.topic == "temperature" and c.level is not guard.Level.ok:
                        checks.append(guard.Check(c.level, "standstill", f"holding this torque at standstill: {c.message}"))
        needs = [] if design is None else requirements(
            device, sum(r.count for r in design.stage.roles), base
        )
        out.append(Candidate(device, design, stall, checks, problem, needs))
    return sorted(out, key=lambda c: (c.level is guard.Level.fail, c.loss))


def explain(candidates: list[Candidate]) -> list[str]:
    """Plain sentences on the ranking."""
    usable = [c for c in candidates if c.level is not guard.Level.fail]
    lines = []
    if not usable:
        lines.append("None of these devices passes every check at this operating point.")
    else:
        best = usable[0]
        name = f"{best.device.vendor} {best.device.part_number}"
        lines.append(
            f"{name} has the lowest power-stage loss among the devices that pass: "
            f"{best.loss:.1f} W."
        )
        if best.level is guard.Level.caution:
            lines.append("It passes with cautions, listed below; read them before relying on it.")
        if not best.device.package.integrated_driver:
            built_in = [c for c in usable[1:] if c.device.package.integrated_driver]
            if built_in:
                other = built_in[0]
                lines.append(
                    f"It needs separate gate drivers. {other.device.vendor} "
                    f"{other.device.part_number} has them built in, for "
                    f"{other.loss - best.loss:.1f} W more loss."
                )
        for other in usable[1:]:
            extra = other.loss - best.loss
            share = f" ({extra / best.loss:.0%})" if best.loss > 0 else ""
            lines.append(
                f"{other.device.vendor} {other.device.part_number} loses {extra:.1f} W more{share}."
            )
    for c in candidates:
        if c.level is guard.Level.fail:
            reason = c.problem or "; ".join(k.message for k in c.checks if k.level is guard.Level.fail)
            lines.append(f"{c.device.vendor} {c.device.part_number} is ruled out: {reason}.")
    return lines
