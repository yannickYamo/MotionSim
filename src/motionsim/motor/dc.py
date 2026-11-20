"""Motors driven like direct current: brushless DC with block commutation on a three-phase
inverter, and brushed DC with a magnet or a series field on an H-bridge."""

from __future__ import annotations

from typing import ClassVar, Literal

import numpy as np
from pydantic import Field, model_validator

from motionsim.engine.modulation import Pwm, Role
from motionsim.engine.notes import Code, Note
from motionsim.errors import FigureError
from motionsim.motor.base import N, _Machine, _rad_s, _stage_gives
from motionsim.motor.stage import Stage, Unreachable
from motionsim.text import written


def _window(start_deg: float, width_deg: float) -> np.ndarray:
    angle = (np.arange(N) + 0.5) * 360.0 / N
    return (((angle - start_deg) % 360.0) < width_deg).astype(float)


def _from_speed_constant(data):
    """A torque constant given as the speed constant a catalogue prints, rpm per volt of
    back-EMF: in SI units the torque and voltage constants are equal, Kt = 60 / (2π · Kv)."""
    if not isinstance(data, dict) or "kv" not in data:
        return data
    data = dict(data)
    if "kt" in data:
        raise FigureError("give the torque constant or the speed constant, not both", "kt")
    kv = data.pop("kv")
    if isinstance(kv, bool) or not isinstance(kv, (int, float)) or not kv > 0:
        raise FigureError("the speed constant has to be a number above zero", "kv")
    data["kt"] = 60 / (2 * np.pi * kv)
    return data


RETURNING = Note(Code.braking_returns, "torque", "braking: the motor returns energy to the DC link")
PLUGGING = Note(
    Code.braking_from_supply,
    "torque",
    "braking at this speed takes power from the supply: the winding resistance uses more than the motor generates",
)


def _braking_notes(motoring: bool, drive: float) -> list[str]:
    if motoring:
        return []
    return [RETURNING if drive < 0 else PLUGGING]


class Bldc(_Machine):
    """Brushless DC motor with block (six-step) commutation, motoring and braking.

    Two phases conduct at a time. Motoring, the high-side switch of the
    positive phase chops and the low-side switch of the negative phase stays
    on. Braking hard enough to return energy, the current runs against the
    back-EMF: the low side of one phase carries it in reverse all the time,
    and the other phase chops between its low-side switch and the reverse
    path of its high side, which is where the energy goes back to the link.
    """

    type: Literal["bldc"]
    fixed_scheme: ClassVar[str | None] = "block (trapezoidal) commutation, high side chopping"
    pole_pairs: int = Field(gt=0)
    kt: float = Field(
        gt=0,
        description="torque constant, N·m per A of winding current: the current in the two phases that "
        "conduct, which the DC link carries only for the part of each period the chopping switch is on",
    )
    l: float | None = Field(default=None, gt=0, description="phase-to-phase inductance, H; optional")
    r: float = Field(ge=0, description="phase-to-phase resistance, ohm")
    i_max: float | None = Field(default=None, gt=0, description="A")

    @model_validator(mode="before")
    @classmethod
    def _accept_speed_constant(cls, data):
        return _from_speed_constant(data)

    def stage(self, rpm: float, torque: float, v_dc: float, pwm: Pwm) -> Stage:
        current = abs(torque) / self.kt
        if self.i_max is not None and current > self.i_max:
            raise Unreachable(
                f"{torque:g} N·m needs {written(current, 3)} A, above the {self.i_max:g} A limit",
                Code.reach_current,
            )
        motoring = torque * rpm >= 0
        back_emf = self.kt * _rad_s(abs(rpm))  # in SI units the torque and voltage constants are equal
        # Voltage the bridge applies along the current. Negative: the motor pushes current into the link.
        drive = back_emf + self.r * current if motoring else self.r * current - back_emf
        duty = abs(drive) / v_dc
        if duty > self.usable_voltage:
            raise Unreachable(
                f"{written(torque, 3)} N·m at {written(rpm, 4)} rpm needs {written(abs(drive), 4)} V, more than "
                + _stage_gives(self.usable_voltage, v_dc),
                Code.reach_voltage,
            )
        positive, negative = _window(30, 120), _window(210, 120)
        chopping = float(0 < duty < 1)
        zero = np.zeros(N)
        amps = np.full(N, current)
        if drive >= 0:
            roles = [
                Role("high-side position", 3, amps, duty * positive, zero, chopping * positive, zero),
                Role("low-side position", 3, amps, negative, (1 - duty) * positive, zero, chopping * positive),
            ]
        else:
            roles = [
                Role("high-side position", 3, amps, zero, duty * negative, zero, chopping * negative),
                Role("low-side position", 3, amps, (1 - duty) * negative, positive, chopping * negative, zero),
            ]
        f_out = self.pole_pairs * abs(rpm) / 60
        sign = 1.0 if drive >= 0 else -1.0
        return Stage(
            roles=roles,
            period=1.0 / f_out if f_out else float("inf"),
            stalled=f_out == 0,
            l_phase=None if self.l is None else self.l / 2,
            # Two phases in series across the link while the chopping switch is on, shorted
            # through the other side of that leg while it is off; the third phase carries nothing.
            states=[(duty, sign * current, sign), (1 - duty, 0.0, 0.0)],
            p_electrical=drive * current,
            p_shaft=torque * _rad_s(rpm),
            p_motor_loss=self.r * current**2,
            summary=[
                ("winding current", current, "A"),
                ("duty cycle", duty, ""),
                ("commutation frequency", f_out, "Hz"),
            ],
            notes=[
                Note(
                    Code.commutation_not_modelled,
                    "commutation",
                    "block commutation: diode conduction during each commutation is not modelled",
                )
            ]
            + _braking_notes(motoring, drive),
        )


class BrushedDc(_Machine):
    """Brushed DC motor on an H-bridge, in all four quadrants.

    The current runs from one leg to the other. When the bridge feeds the
    motor, the first leg chops and the low side of the second stays on. When
    the motor feeds the bridge, the low side of the first leg carries the
    current in reverse, and the second leg chops between its low-side switch
    and the reverse path of its high side, which returns energy to the link.
    Positions are listed leg by leg, so each keeps its place when the motor
    changes from driving to braking.
    """

    type: Literal["dc"]
    kt: float = Field(gt=0, description="torque constant, N·m/A")
    r: float = Field(ge=0, description="armature resistance, ohm")

    @model_validator(mode="before")
    @classmethod
    def _accept_speed_constant(cls, data):
        return _from_speed_constant(data)

    l: float | None = Field(default=None, gt=0, description="armature inductance, H; optional")
    i_max: float | None = Field(default=None, gt=0, description="A")
    drive: Literal["unipolar", "bipolar"] = Field(
        default="unipolar",
        description="unipolar: one leg chops while the other holds, the usual choice and the "
        "lower loss. bipolar: both legs switch every period, diagonal pairs in turn; simpler "
        "to control through zero, at about twice the switching loss",
    )

    def scheme(self, pwm: Pwm) -> str:
        return f"{self.drive} PWM on an H-bridge"

    def stage(self, rpm: float, torque: float, v_dc: float, pwm: Pwm) -> Stage:
        current = torque / self.kt  # positive from leg A to leg B
        if self.i_max is not None and abs(current) > self.i_max:
            raise Unreachable(
                f"{torque:g} N·m needs {written(abs(current), 3)} A, above the {self.i_max:g} A limit",
                Code.reach_current,
            )
        voltage = self.kt * _rad_s(rpm) + self.r * current  # leg A minus leg B
        return _h_bridge_stage(
            current,
            voltage,
            v_dc,
            self.drive,
            torque=torque,
            rpm=rpm,
            loss=self.r * current**2,
            inductance=self.l,
            usable=self.usable_voltage,
        )


# What one position of an H-bridge does, as a Role takes it after its name and count: the
# current and the four duty patterns. By leg and side.
_Parts = dict[tuple[str, str], tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]]
_States = list[tuple[float, float, float]] | None


def _h_bridge_stage(
    current: float,
    voltage: float,
    v_dc: float,
    drive: str,
    *,
    torque: float,
    rpm: float,
    loss: float,
    notes: list[str] | None = None,
    inductance: float | None = None,
    usable: float = 1.0,
) -> Stage:
    """What each of an H-bridge's four positions does for a signed current and voltage.

    current is positive from leg A to leg B; voltage is leg A minus leg B.
    """
    if abs(voltage) > usable * v_dc:
        raise Unreachable(
            f"{written(torque, 3)} N·m at {written(rpm, 4)} rpm needs {written(abs(voltage), 4)} V, more than "
            + _stage_gives(usable, v_dc),
            Code.reach_voltage,
        )
    along = voltage if current >= 0 else -voltage  # along the current
    duty = abs(along) / v_dc
    parts, states = _h_bridge_parts(current, along, duty, v_dc, drive)
    roles = [
        Role(f"leg {leg} {side} side", 1, *parts[(leg, side)], leg=leg)
        for leg in ("A", "B")
        for side in ("high", "low")
    ]
    return Stage(
        roles=roles,
        period=1.0,
        l_phase=None if inductance is None else inductance / 2,
        states=states,
        p_electrical=voltage * current,
        p_shaft=torque * _rad_s(rpm),
        p_motor_loss=loss,
        summary=[("armature current", current, "A"), ("duty cycle", duty, "")],
        notes=(notes or []) + _braking_notes(torque * rpm >= 0, along),
    )


def _h_bridge_parts(current: float, along: float, duty: float, v_dc: float, drive: str) -> tuple[_Parts, _States]:
    """What each of an H-bridge's four positions carries, by leg and side, and the states the
    winding sees where the bridge switches both legs. along is the voltage along the current."""
    first, second = ("A", "B") if current >= 0 else ("B", "A")
    n = 8
    amps, one, zero = np.full(n, abs(current)), np.ones(n), np.zeros(n)
    chopping = float(0 < duty < 1) * one
    idle = (zero, zero, zero, zero, zero)
    states: _States = None
    if drive == "bipolar":
        # The diagonal pair that feeds the motor is on for part of each period; for the
        # rest the current runs back through the reverse paths of the other diagonal.
        share = (1 + along / v_dc) / 2
        every = float(0 < share < 1) * one
        # One diagonal, then the other: the link gives the current, then takes it back, and
        # the winding sees the whole DC voltage one way, then the other.
        states = [(share, abs(current), 1.0), (1 - share, -abs(current), -1.0)]
        parts = {
            (first, "high"): (amps, share * one, zero, every, zero),
            (second, "low"): (amps, share * one, zero, every, zero),
            (first, "low"): (amps, zero, (1 - share) * one, zero, every),
            (second, "high"): (amps, zero, (1 - share) * one, zero, every),
        }
    elif along >= 0:
        parts = {
            (first, "high"): (amps, duty * one, zero, chopping, zero),
            (first, "low"): (amps, zero, (1 - duty) * one, zero, chopping),
            (second, "high"): idle,
            (second, "low"): (amps, one, zero, zero, zero),
        }
    else:
        parts = {
            (first, "high"): idle,
            (first, "low"): (amps, zero, one, zero, zero),
            (second, "high"): (amps, zero, duty * one, zero, chopping),
            (second, "low"): (amps, (1 - duty) * one, zero, chopping, zero),
        }
    return parts, states


class SeriesDc(_Machine):
    """Brushed DC motor with its field winding in series with the armature.

    The field is made by the armature's own current, so torque goes with the
    square of the current and the back-EMF with current times speed:

        torque = k * I^2        back-EMF = k * I * speed

    Power tools, starters and universal motors are built this way. Reversing
    the current reverses field and armature together, so the torque keeps its
    direction: the motor turns one way for a given wiring and cannot return
    energy to the supply without being rewired.
    """

    type: Literal["dc_series"]
    k: float = Field(gt=0, description="torque per current squared, N·m/A^2")
    r: float = Field(ge=0, description="armature plus field resistance, ohm")
    l: float | None = Field(default=None, gt=0, description="armature plus field inductance, H; optional")
    i_max: float | None = Field(default=None, gt=0, description="A")
    drive: Literal["unipolar", "bipolar"] = "unipolar"

    def scheme(self, pwm: Pwm) -> str:
        return f"{self.drive} PWM on an H-bridge"

    def stage(self, rpm: float, torque: float, v_dc: float, pwm: Pwm) -> Stage:
        if torque < 0 or rpm < 0:
            raise Unreachable(
                "a series-wound motor turns one way for a given wiring and cannot brake into "
                "the supply; give a positive speed and torque",
                Code.reach_other,
            )
        current = float(np.sqrt(torque / self.k))
        if self.i_max is not None and current > self.i_max:
            raise Unreachable(
                f"{torque:g} N·m needs {written(current, 3)} A, above the {self.i_max:g} A limit",
                Code.reach_current,
            )
        voltage = self.k * current * _rad_s(rpm) + self.r * current
        return _h_bridge_stage(
            current,
            voltage,
            v_dc,
            self.drive,
            torque=torque,
            rpm=rpm,
            loss=self.r * current**2,
            inductance=self.l,
            usable=self.usable_voltage,
            notes=[
                Note(
                    Code.field_not_saturating,
                    "kt",
                    "series-wound: torque taken as proportional to current squared, so "
                    "saturation of the field is not modelled",
                )
            ],
        )
