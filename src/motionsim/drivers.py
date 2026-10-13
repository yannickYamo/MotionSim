"""Ways of calling the engine: from a motor's speed and torque, and over a speed-torque grid."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from motionsim.device.schema import Device
from motionsim.engine.limits import hottest
from motionsim.engine.link import capacitor_ripple, phase_ripple, states_capacitor, states_ripple
from motionsim.engine.solver import OperatingPoint, Result, ThermalRunaway, solve_roles
from motionsim.motor.stage import Stage, Unreachable
from motionsim.text import written


@dataclass(frozen=True)
class MotorPoint:
    stage: Stage
    result: Result
    # At the switching frequency: the largest peak-to-peak ripple on a phase current, A, or
    # None where the motor's inductance is not known; and the rms current the DC-link
    # capacitor carries, A, or None for a stage it is not worked out for.
    ripple_pp: float | None = None
    capacitor_rms: float | None = None

    @property
    def system_efficiency(self) -> float | None:
        """Shaft power over DC input power: motor winding loss and power-stage loss included."""
        if self.stage.p_shaft <= 0:
            return None
        return self.stage.p_shaft / (self.stage.p_shaft + self.stage.p_motor_loss + self.result.p_inverter)


def _raised(motor, stage, rpm: float, torque: float, base: OperatingPoint, least: float):
    """The stage carrying at least `least` amps peak, as a drive running open loop makes it.

    The drive holds a fixed current whatever the torque; what the torque does not use
    magnetises the motor. At the low speeds where this happens the voltage is small and
    the duty cycles hardly move, so the stage is the one the torque asks for with its
    currents scaled up, and the winding loss with their square.
    """
    from dataclasses import replace

    if stage.i_peak >= least:
        return stage
    if stage.i_peak <= 0:  # no torque asked for: take the waveforms of a vanishing one
        stage = motor.stage(rpm, 1e-6 if torque >= 0 else -1e-6, base.v_dc, base.pwm)
    k = least / stage.i_peak
    loss = stage.p_motor_loss * k**2
    return replace(
        stage,
        roles=[replace(r, current=r.current * k) for r in stage.roles],
        states=stage.states and [(share, drawn * k, volts) for share, drawn, volts in stage.states],
        p_motor_loss=loss,
        p_electrical=stage.p_shaft + loss,
        notes=stage.notes
        + [f"open-loop start: the drive holds {written(least / 2**0.5, 3)} A rms here, whatever the torque"],
    )


def _usable(device: Device, base: OperatingPoint, i_peak: float) -> float:
    """Share of the ideal output voltage the stage can really give.

    Three things take from it. Dead time cuts a slice off every pulse. The gate drive
    cannot make a pulse shorter than its shortest, so the duty cycle cannot come closer
    to either rail than that. And the switch and the diode each drop a volt or two of what
    is left, which matters on a low supply.
    """
    from motionsim.engine.losses import voltage

    timing = 2.0 * (base.t_dead + base.t_min_pulse) * base.f_sw
    if timing >= 0.5:
        # Not a design to be given a figure for: half of every period or more is spent with
        # both switches off. Said, and not hidden under the floor below.
        raise Unreachable(
            f"the dead time and the shortest pulse take {timing:.0%} of each switching period at "
            f"{written(base.f_sw / 1000, 3)} kHz: the stage cannot make its voltage. Lower the switching frequency, "
            "or give a shorter dead time"
        )
    drop = 0.0
    if i_peak > 0:
        chips = [device.switch] + ([device.diode] if device.diode is not None else [])
        drop = max(float(voltage(c, np.array([i_peak / max(int(base.parallel), 1)]), base.t_sink)[0]) for c in chips)
    return float(np.clip(1.0 - timing - drop / (base.v_dc / 2), 0.5, 1.0))


def at_speed_and_torque(
    device: Device,
    motor,
    rpm: float,
    torque: float,
    base: OperatingPoint,
    *,
    least_current: float | None = None,
    ripple: bool = True,
    spread: bool = True,
) -> MotorPoint:
    """Solve the power stage at a motor speed and torque.

    base supplies what the motor does not decide: DC voltage, switching
    frequency, PWM scheme, sink temperature, dead time and gate drive.
    least_current, in amps peak, is the current a drive running open loop holds.
    ripple=False gives the engine's own answer for the fundamental alone: no current ripple
    at the switching frequency and no voltage lost in the stage.
    spread=False leaves out the range across the thermal assumptions, for a search that
    only needs the typical value.
    """
    from dataclasses import replace

    # Iron loss in the motor is torque the shaft never sees: the windings have to supply it.
    w = abs(rpm) * np.pi / 30
    iron = motor.iron_loss(rpm) if w > 0 else 0.0
    asked = torque + (np.sign(rpm) * iron / w if iron else 0.0)
    notes: list[str] = []
    stage = motor.stage(rpm, asked, base.v_dc, base.pwm)
    if ripple:
        # What the stage can give depends on the current, which depends on what it can give:
        # once round is enough, since the drop moves the current little.
        usable = _usable(device, base, stage.i_peak)
        if usable < 1.0:
            motor = motor.model_copy(update={"usable_voltage": usable})
            stage = motor.stage(rpm, asked, base.v_dc, base.pwm)
            notes.append(
                f"the stage gives {usable:.1%} of the ideal output voltage (dead time, shortest pulse and "
                "the devices' own drop); the motor's reach is worked out with that"
            )
    if least_current:
        stage = _raised(motor, stage, rpm, torque, base, least_current)
    if iron:
        notes.append(f"iron loss in the motor: {written(iron, 3)} W at this speed, supplied through the windings")
        stage = replace(
            stage, p_shaft=torque * w * np.sign(rpm) if rpm else 0.0, p_motor_loss=stage.p_motor_loss + iron
        )
    if motor.temperature_note:
        notes.append(motor.temperature_note)
    if notes:
        stage = replace(stage, notes=stage.notes + notes)
    capacitor = states_capacitor(stage.states) if stage.states else capacitor_ripple(stage.roles)
    # The stage handed back is the motor's own, at the fundamental. What is solved carries
    # the ripple as well.
    solved, ripple_pp = _with_ripple(stage, base) if ripple else (stage, None)
    result = solve_roles(
        device,
        solved.roles,
        base,
        period=stage.period,
        p_out=stage.p_electrical,
        extra_notes=stage.notes,
        stalled=stage.stalled,
        spread=spread,
    )
    return MotorPoint(
        stage=stage,
        result=result,
        ripple_pp=ripple_pp,
        capacitor_rms=None if capacitor is None else capacitor[0],
    )


def _with_ripple(stage: Stage, base: OperatingPoint) -> tuple[Stage, float | None]:
    """The stage with the current ripple at the switching frequency taken into what its
    switches conduct, and the largest ripple, peak to peak.

    The ripple adds to the rms current, a twelfth of its square, and so to conduction loss.
    It also moves the current at the switching instants: turn-on happens at the bottom of
    the ripple and turn-off at the top.
    """
    from dataclasses import replace

    if not stage.l_phase:
        return stage, None
    if stage.states:
        if base.f_sw <= 0:
            return stage, None
        swing = states_ripple(stage.states, base.v_dc, base.f_sw, 2 * stage.l_phase)
        pp = np.full_like(stage.roles[0].current, swing)
    else:
        pp = phase_ripple(stage.roles, base.v_dc, base.f_sw, stage.l_phase)
    if pp is None:
        return stage, None
    named = any(r.leg is not None for r in stage.roles)
    # Legs alike see the same ripple a third of a turn apart, and the roles are written
    # from the first leg; legs that differ carry one current, with one ripple.
    extra = pp if not named else np.full_like(pp, float(pp.max()))
    # The mean square rises by a twelfth of the ripple squared. A switch turns on at the
    # bottom of the ripple and off at the top; where the ripple is larger than twice the
    # current the bottom is zero, and that turn-on is free.
    roles = [
        replace(
            r,
            current=np.where(r.current > 0, np.sqrt(r.current**2 + extra**2 / 12), 0.0),
            current_on=np.where(r.current > 0, np.maximum(r.current - extra / 2, 0.0), 0.0),
            current_off=np.where(r.current > 0, r.current + extra / 2, 0.0),
        )
        for r in stage.roles
    ]
    return replace(stage, roles=roles), float(pp.max())


@dataclass(frozen=True)
class Map:
    """Results over a grid of speeds (columns) and torques (rows); nan where unreachable."""

    rpm: np.ndarray
    torque: np.ndarray
    p_inverter: np.ndarray
    tj_peak: np.ndarray
    efficiency: np.ndarray  # shaft power over DC input power
    i_peak: np.ndarray
    reason: list[list[str]]  # why a cell is empty, else ""


def speed_torque_map(device: Device, motor, rpm: np.ndarray, torque: np.ndarray, base: OperatingPoint) -> Map:
    shape = (len(torque), len(rpm))
    p, tj, eff, cur = (np.full(shape, np.nan) for _ in range(4))
    reason = [["" for _ in rpm] for _ in torque]
    for a, t in enumerate(torque):
        for b, n in enumerate(rpm):
            try:
                point = at_speed_and_torque(device, motor, float(n), float(t), base)
            except Unreachable:
                reason[a][b] = "motor"
                continue
            except ThermalRunaway:
                reason[a][b] = "thermal runaway"
                continue
            p[a, b] = point.result.p_inverter
            tj[a, b] = hottest(point.result)
            cur[a, b] = point.stage.i_peak
            if point.system_efficiency is not None:
                eff[a, b] = point.system_efficiency
    return Map(
        rpm=np.asarray(rpm),
        torque=np.asarray(torque),
        p_inverter=p,
        tj_peak=tj,
        efficiency=eff,
        i_peak=cur,
        reason=reason,
    )
