"""Motor types and the power stage each one needs.

Every machine answers one question: at this speed and torque, from this DC
voltage, what current does each switch position carry, and for how long? All
models are steady state.

- Permanent-magnet synchronous and induction motors: three-phase inverter,
  sinusoidal currents.
- Brushless DC with block commutation: three-phase inverter, each phase
  carrying the current for 120 degrees in each direction.
- Brushed DC: H-bridge, one leg chopping.
- Stepper: two H-bridges, sinusoidal (microstepped) currents at a set amplitude.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, ClassVar, Literal

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator
from scipy.optimize import brentq

from motionsim.engine.modulation import Pwm, Role, phase_leg_roles, waveform
from motionsim.motor import pmsm
from motionsim.motor.stage import Stage, Unreachable
from motionsim.text import written

N = 1440  # samples per period; a multiple of 360 so 120-degree windows fall on samples
SLOW = 0.1  # Hz; a stopped or creeping motor is treated as turning this slowly


class _Machine(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    name: str = "motor"
    # Share of the ideal output voltage the stage can really give: dead time takes some.
    # Set by the solver from the conditions; a motor file does not carry it.
    usable_voltage: float = Field(default=1.0, gt=0, le=1, exclude=True)
    # Said in every result when the motor's figures were moved to a working temperature.
    temperature_note: str = Field(default="", exclude=True)
    # Iron loss, as a catalogue or a no-load test gives it: so many watts at such a speed.
    p_iron: float | None = Field(default=None, ge=0, description="iron loss at n_iron, W; optional")
    n_iron: float | None = Field(default=None, gt=0, description="speed that iron loss was measured at, rpm")

    def iron_loss(self, rpm: float) -> float:
        """Loss in the motor's iron at a speed, W. Half of it is taken to rise with speed
        (hysteresis) and half with speed squared (eddy currents), which is the usual split
        when nothing better is known. Taken at full flux: in field weakening it is less."""
        if not self.p_iron or not self.n_iron:
            return 0.0
        x = abs(rpm) / self.n_iron
        return self.p_iron * (0.5 * x + 0.5 * x * x)

    # The modulation used when the user names none, and what it is called for this motor.
    default_pwm: ClassVar[Pwm] = Pwm.sine
    fixed_scheme: ClassVar[str | None] = None  # set where the motor type decides the scheme

    def scheme(self, pwm: Pwm) -> str:
        """The modulation in words, for the result."""
        return self.fixed_scheme or f"{pwm.value} PWM"


COPPER = 0.00393  # per kelvin: how copper's resistance rises with temperature
MAGNET = -0.0011  # per kelvin: how a neodymium magnet's flux falls; ferrite falls about twice as fast
CATALOGUE = 25.0  # °C the motor's figures are taken to be given at


def at_temperature(machine, t_c: float):
    """The same motor at a working temperature: its windings resist more and its magnets
    give less, so the same torque takes more current and more copper loss."""
    dt = t_c - CATALOGUE
    changed = {}
    for key in ("rs", "rr", "r"):
        if getattr(machine, key, None) is not None:
            changed[key] = getattr(machine, key) * (1 + COPPER * dt)
    magnets = [k for k in ("flux_linkage", "kt") if getattr(machine, k, None) is not None]
    if machine.type in ("pmsm", "bldc", "dc"):
        for key in magnets:
            changed[key] = getattr(machine, key) * (1 + MAGNET * dt)
    changed["temperature_note"] = (
        f"motor taken at {t_c:g} °C: winding resistance {1 + COPPER * dt:.2f} times its {CATALOGUE:g} °C value"
        + (
            f", magnet flux {1 + MAGNET * dt:.2f} times (neodymium; ferrite loses about twice as much)"
            if machine.type in ("pmsm", "bldc", "dc") and magnets
            else ""
        )
    )
    return machine.model_copy(update=changed)


def replace_notes(stage: Stage, old: str, new: str) -> Stage:
    """The stage with one of its notes reworded."""
    from dataclasses import replace

    return replace(stage, notes=[new if n.startswith(old) else n for n in stage.notes])


def _rad_s(rpm: float) -> float:
    return 2 * np.pi * rpm / 60


def _sinusoidal_stage(
    *,
    i_rms: float,
    v_peak: float,
    power_factor: float,
    f_out: float,
    v_dc: float,
    pwm: Pwm,
    legs: int,
    p_shaft: float,
    p_loss: float,
    summary: list,
    notes: list[str],
    leg_voltage: float,
    l_phase: float | None = None,
) -> Stage:
    """Stage for sinusoidal currents. leg_voltage is the DC voltage one leg's swing spans:
    half the link for a three-phase inverter, the full link for an H-bridge."""
    m = v_peak / leg_voltage
    wave = waveform(i_rms, m, power_factor, N, pwm)
    phases = legs // 2 if leg_voltage > v_dc / 2 else legs
    summary = summary + [
        ("phase current", i_rms, "A rms"),
        ("phase voltage", v_peak / np.sqrt(2), "V rms"),
        ("modulation index", m, ""),
        ("power factor", power_factor, ""),
        ("output frequency", f_out, "Hz"),
    ]
    return Stage(
        roles=phase_leg_roles(wave, 2 * legs, pwm),
        period=1.0 / max(abs(f_out), SLOW),
        stalled=abs(f_out) < SLOW,
        l_phase=l_phase,
        p_electrical=phases * (v_peak / np.sqrt(2)) * i_rms * power_factor,
        p_shaft=p_shaft,
        p_motor_loss=p_loss,
        summary=summary,
        notes=notes,
    )


class Pmsm(_Machine):
    """Permanent-magnet synchronous motor under field-oriented control."""

    type: Literal["pmsm"] = "pmsm"
    # Field-oriented drives use space-vector modulation: 15% more voltage from the same
    # DC link than plain sine, for the same losses.
    default_pwm: ClassVar[Pwm] = Pwm.space_vector
    magnets: Literal["surface", "inset", "interior"] = "surface"
    pole_pairs: int = Field(gt=0)
    flux_linkage: float = Field(gt=0, description="Wb peak")
    ld: float = Field(gt=0, description="H")
    lq: float = Field(gt=0, description="H")
    rs: float = Field(ge=0, description="ohm per phase")
    i_max: float | None = Field(default=None, gt=0, description="A rms")
    i_sat: float | None = Field(
        default=None,
        gt=0,
        description="current at which an inductance has fallen to 71% of its value, A peak; optional",
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_catalogue_values(cls, data):
        """Accept the figures motor catalogues give in place of flux linkage and dq inductances.

        - l: one phase inductance, for a surface-magnet motor (Ld = Lq)
        - kv: speed constant, rpm per volt of peak line-to-line back-EMF
        - ke: back-EMF constant, peak line-to-line volts per 1000 rpm
        """
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if "l" in data:
            if "ld" in data or "lq" in data:
                raise ValueError("give either l, or ld and lq")
            data["ld"] = data["lq"] = data.pop("l")
        given = [k for k in ("flux_linkage", "kv", "ke") if k in data]
        if len(given) != 1:
            raise ValueError("give exactly one of flux_linkage, kv or ke")
        pairs = data.get("pole_pairs")
        # Bad values are left for the field checks, which name the field; nothing is
        # computed from them here.
        key = given[0]
        usable = all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in (pairs, data[key]))
        if key != "flux_linkage" and not usable:
            if not (isinstance(pairs, (int, float)) and not isinstance(pairs, bool) and pairs > 0):
                raise ValueError("pole_pairs must be a whole number above zero")
            raise ValueError(f"{key} must be a number above zero")
        if "kv" in data:
            data["flux_linkage"] = 60 / (np.sqrt(3) * 2 * np.pi * pairs * data.pop("kv"))
        elif "ke" in data:
            data["flux_linkage"] = data.pop("ke") * 60 / (1000 * np.sqrt(3) * 2 * np.pi * pairs)
        return data

    @model_validator(mode="after")
    def _check_saliency(self) -> Pmsm:
        if self.magnets == "surface" and self.ld != self.lq:
            raise ValueError("a surface-magnet motor has Ld equal to Lq; use magnets: inset or interior")
        if self.magnets != "surface" and self.lq < self.ld:
            raise ValueError("with inset or interior magnets Lq is at least as large as Ld")
        return self

    def stage(self, rpm: float, torque: float, v_dc: float, pwm: Pwm) -> Stage:
        motor = pmsm.Motor(
            **self.model_dump(exclude={"type", "magnets", "usable_voltage", "p_iron", "n_iron", "temperature_note"})
        )
        s = pmsm.operating_state(motor, rpm, torque, self.usable_voltage * pwm.max_modulation_index * v_dc / 2)
        return _sinusoidal_stage(
            i_rms=s.i_rms,
            v_peak=s.v_peak,
            power_factor=s.power_factor,
            f_out=s.f_out,
            v_dc=v_dc,
            pwm=pwm,
            legs=3,
            p_shaft=s.p_shaft,
            p_loss=s.p_copper,
            summary=[("field weakening", float(s.field_weakening), "yes/no")],
            notes=[],
            leg_voltage=v_dc / 2,
            l_phase=(self.ld + self.lq) / 2,
        )


class SynRm(_Machine):
    """Synchronous reluctance motor: a shaped steel rotor with no magnets and no winding.

    Torque comes only from the rotor being easier to magnetise along one axis
    than the other. The d axis is the easy one, so Ld is the larger inductance:

        torque = 1.5 * p * (Ld - Lq) * id * iq
        vd = Rs * id - w * Lq * iq
        vq = Rs * iq + w * Ld * id

    The least current for a torque has id equal to iq. When that needs more
    voltage than the link gives, id is lowered and iq raised, down to the
    least-voltage point where Ld * id equals Lq * iq. Inductances are taken as
    constant; in a real motor they fall as the steel saturates.
    """

    type: Literal["synrm"]
    default_pwm: ClassVar[Pwm] = Pwm.space_vector
    pole_pairs: int = Field(gt=0)
    ld: float = Field(gt=0, description="d-axis (easy axis) inductance, H")
    lq: float = Field(gt=0, description="q-axis inductance, H")
    rs: float = Field(ge=0, description="ohm per phase")
    i_max: float | None = Field(default=None, gt=0, description="A rms")
    i_sat: float | None = Field(
        default=None,
        gt=0,
        description="current at which an inductance has fallen to 71% of its value, A peak; optional",
    )

    @model_validator(mode="after")
    def _check_saliency(self) -> SynRm:
        if self.ld <= self.lq:
            raise ValueError("ld must be larger than lq: a reluctance motor's torque comes from the difference")
        return self

    def stage(self, rpm: float, torque: float, v_dc: float, pwm: Pwm) -> Stage:
        """With a saturation current given, the inductances follow the current: each axis by
        its own, L = L0 / sqrt(1 + (i / i_sat)^2). The easy axis carries the magnetising
        current and saturates first, which is what limits a reluctance motor's torque."""
        if not self.i_sat:
            return self._solve(rpm, torque, v_dc, pwm)[0]
        motor = self
        for _ in range(12):
            _, i_d, i_q = motor._solve(rpm, torque, v_dc, pwm)
            ld = self.ld / float(np.sqrt(1 + (i_d / self.i_sat) ** 2))
            lq = self.lq / float(np.sqrt(1 + (i_q / self.i_sat) ** 2))
            motor = self.model_copy(update={"ld": max(ld, 1.02 * lq), "lq": lq})
        stage, _, _ = motor._solve(rpm, torque, v_dc, pwm)
        return replace_notes(
            stage,
            "reluctance motor: inductances taken as constant",
            f"reluctance motor: inductances follow the current, saturating about {self.i_sat:g} A",
        )

    def _solve(self, rpm: float, torque: float, v_dc: float, pwm: Pwm) -> tuple[Stage, float, float]:
        v_max = self.usable_voltage * pwm.max_modulation_index * v_dc / 2
        w = self.pole_pairs * _rad_s(rpm)
        k = 1.5 * self.pole_pairs * (self.ld - self.lq)
        product = abs(torque) / k  # id * |iq|
        sign = 1.0 if torque >= 0 else -1.0

        def voltages(i_d: float) -> tuple[float, float, float]:
            i_q = sign * product / i_d if i_d > 0 else 0.0
            return i_q, self.rs * i_d - w * self.lq * i_q, self.rs * i_q + w * self.ld * i_d

        i_d = float(np.sqrt(product))
        i_q, v_d, v_q = voltages(i_d)
        weakening = False
        if np.hypot(v_d, v_q) > v_max:
            weakening = True
            least = float(np.sqrt(product * self.lq / self.ld))  # where Ld*id = Lq*iq

            def excess(x: float) -> float:
                _, a, b = voltages(x)
                return float(np.hypot(a, b) - v_max)

            if excess(least) > 0:
                raise Unreachable(
                    f"{written(torque, 3)} N·m at {written(rpm, 4)} rpm needs more voltage than {written(v_max, 4)} V peak "
                    "at any current angle"
                )
            i_d = float(brentq(excess, least, i_d))
            i_q, v_d, v_q = voltages(i_d)
        i_pk = float(np.hypot(i_d, i_q))
        if self.i_max is not None and i_pk / np.sqrt(2) > self.i_max:
            raise Unreachable(
                f"{written(torque, 3)} N·m at {written(rpm, 4)} rpm needs {written(i_pk / np.sqrt(2), 3)} A rms, above the "
                f"motor's {self.i_max:g} A limit"
            )
        v_pk = float(np.hypot(v_d, v_q))
        power = 1.5 * (v_d * i_d + v_q * i_q)
        return (
            _sinusoidal_stage(
                i_rms=i_pk / np.sqrt(2),
                v_peak=v_pk,
                power_factor=float(power / (1.5 * v_pk * i_pk)) if v_pk * i_pk > 0 else 1.0,
                f_out=float(w / (2 * np.pi)),
                v_dc=v_dc,
                pwm=pwm,
                legs=3,
                p_shaft=torque * _rad_s(rpm),
                p_loss=1.5 * self.rs * i_pk**2,
                summary=[("field weakening", float(weakening), "yes/no")],
                notes=["reluctance motor: inductances taken as constant, so saturation is not modelled"],
                leg_voltage=v_dc / 2,
                l_phase=(self.ld + self.lq) / 2,
            ),
            i_d,
            abs(i_q),
        )


class Induction(_Machine):
    """Induction motor under rotor-flux-oriented control.

    Flux is held at its rated value until the voltage limit, then reduced.
        torque = 1.5 * p * (Lm / Lr) * psi_r * iq,   psi_r = Lm * id
        slip   = (Rr / Lr) * iq / id
    """

    type: Literal["induction"]
    default_pwm: ClassVar[Pwm] = Pwm.space_vector
    pole_pairs: int = Field(gt=0)
    rs: float = Field(ge=0, description="stator resistance, ohm")
    rr: float = Field(gt=0, description="rotor resistance referred to the stator, ohm")
    lm: float = Field(gt=0, description="magnetising inductance, H")
    lls: float = Field(ge=0, description="stator leakage inductance, H")
    llr: float = Field(ge=0, description="rotor leakage inductance, H")
    i_magnetising: float = Field(gt=0, description="rated magnetising current, A peak")
    i_max: float | None = Field(default=None, gt=0, description="A rms")

    def _state(self, rpm: float, torque: float, i_d: float):
        ls, lr = self.lm + self.lls, self.lm + self.llr
        i_q = torque / (1.5 * self.pole_pairs * self.lm**2 / lr * i_d)
        w = self.pole_pairs * _rad_s(rpm) + self.rr / lr * i_q / i_d
        sigma_ls = ls - self.lm**2 / lr
        v_d = self.rs * i_d - w * sigma_ls * i_q
        v_q = self.rs * i_q + w * ls * i_d
        return i_q, w, v_d, v_q

    def stage(self, rpm: float, torque: float, v_dc: float, pwm: Pwm) -> Stage:
        v_max = self.usable_voltage * pwm.max_modulation_index * v_dc / 2
        i_d = self.i_magnetising
        weakening = False

        def excess(x: float) -> float:
            _, _, v_d, v_q = self._state(rpm, torque, x)
            return float(np.hypot(v_d, v_q) - v_max)

        if excess(i_d) > 0:
            weakening = True
            # Less flux lowers the voltage until the extra torque current outweighs it.
            grid = np.geomspace(i_d, i_d / 200, 400)
            below = [x for x in grid if excess(x) <= 0]
            if not below:
                raise Unreachable(
                    f"{written(torque, 3)} N·m at {written(rpm, 4)} rpm needs more voltage than {written(v_max, 4)} V peak "
                    "at any flux level"
                )
            i_d = float(brentq(excess, below[0], grid[list(grid).index(below[0]) - 1]))
        i_q, w, v_d, v_q = self._state(rpm, torque, i_d)
        lr = self.lm + self.llr
        i_pk, v_pk = np.hypot(i_d, i_q), np.hypot(v_d, v_q)
        if self.i_max is not None and i_pk / np.sqrt(2) > self.i_max:
            raise Unreachable(
                f"{written(torque, 3)} N·m at {written(rpm, 4)} rpm needs {written(i_pk / np.sqrt(2), 3)} A rms, above the "
                f"{self.i_max:g} A limit"
            )
        power = 1.5 * (v_d * i_d + v_q * i_q)
        stator = 1.5 * self.rs * i_pk**2
        rotor = 1.5 * self.rr * (self.lm / lr * i_q) ** 2
        return _sinusoidal_stage(
            i_rms=float(i_pk / np.sqrt(2)),
            v_peak=float(v_pk),
            power_factor=float(power / (1.5 * v_pk * i_pk)) if v_pk * i_pk > 0 else 1.0,
            f_out=float(w / (2 * np.pi)),
            v_dc=v_dc,
            pwm=pwm,
            legs=3,
            p_shaft=torque * _rad_s(rpm),
            p_loss=stator + rotor,
            summary=[
                ("field weakening", float(weakening), "yes/no"),
                ("slip frequency", float((w - self.pole_pairs * _rad_s(rpm)) / (2 * np.pi)), "Hz"),
            ],
            notes=[],
            leg_voltage=v_dc / 2,
            # What the switching sees is the leakage: the magnetising branch is far slower.
            l_phase=self.lls + self.lm * self.llr / (self.lm + self.llr),
        )


def _window(start_deg: float, width_deg: float) -> np.ndarray:
    angle = (np.arange(N) + 0.5) * 360.0 / N
    return (((angle - start_deg) % 360.0) < width_deg).astype(float)


RETURNING = "braking: the motor returns energy to the DC link"
PLUGGING = (
    "braking at this speed takes power from the supply: the winding resistance uses more than the motor generates"
)


def _stage_gives(usable: float, v_dc: float) -> str:
    """What a voltage is said to be more than: the link, or what the stage makes of it."""
    if usable >= 1:
        return "the DC link"
    return f"the DC link gives through this stage ({written(usable * v_dc, 4)} V of {v_dc:g} V)"


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
    kt: float = Field(gt=0, description="torque constant, N·m per A of DC-link current")
    l: float | None = Field(default=None, gt=0, description="phase-to-phase inductance, H; optional")
    r: float = Field(ge=0, description="phase-to-phase resistance, ohm")
    i_max: float | None = Field(default=None, gt=0, description="A")

    def stage(self, rpm: float, torque: float, v_dc: float, pwm: Pwm) -> Stage:
        current = abs(torque) / self.kt
        if self.i_max is not None and current > self.i_max:
            raise Unreachable(f"{torque:g} N·m needs {written(current, 3)} A, above the {self.i_max:g} A limit")
        motoring = torque * rpm >= 0
        back_emf = self.kt * _rad_s(abs(rpm))  # in SI units the torque and voltage constants are equal
        # Voltage the bridge applies along the current. Negative: the motor pushes current into the link.
        drive = back_emf + self.r * current if motoring else self.r * current - back_emf
        duty = abs(drive) / v_dc
        if duty > self.usable_voltage:
            raise Unreachable(
                f"{written(torque, 3)} N·m at {written(rpm, 4)} rpm needs {written(abs(drive), 4)} V, more than "
                + _stage_gives(self.usable_voltage, v_dc)
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
            period=1.0 / max(f_out, SLOW),
            stalled=f_out < SLOW,
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
            notes=["block commutation: diode conduction during each commutation is not modelled"]
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
            raise Unreachable(f"{torque:g} N·m needs {written(abs(current), 3)} A, above the {self.i_max:g} A limit")
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
            + _stage_gives(usable, v_dc)
        )
    first, second = ("A", "B") if current >= 0 else ("B", "A")
    along = voltage if current >= 0 else -voltage  # along the current
    duty = abs(along) / v_dc
    n = 8
    amps, one, zero = np.full(n, abs(current)), np.ones(n), np.zeros(n)
    chopping = float(0 < duty < 1) * one
    idle = (zero, zero, zero, zero, zero)
    states = None
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
                "the supply; give a positive speed and torque"
            )
        current = float(np.sqrt(torque / self.k))
        if self.i_max is not None and current > self.i_max:
            raise Unreachable(f"{torque:g} N·m needs {written(current, 3)} A, above the {self.i_max:g} A limit")
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
                "series-wound: torque taken as proportional to current squared, so "
                "saturation of the field is not modelled"
            ],
        )


class Stepper(_Machine):
    """Bipolar stepper on two H-bridges with sinusoidal (microstepped) currents.

    A stepper driver holds the phase current at a set amplitude whatever the
    load, so the current comes from the motor file and the torque asked for
    only has to be within what the motor can hold.
    """

    type: Literal["stepper"]
    fixed_scheme: ClassVar[str | None] = "sine PWM on two H-bridges (microstepping)"
    steps_per_rev: int = Field(default=200, gt=0)
    i_phase: float = Field(gt=0, description="set phase current, A peak")
    r: float = Field(ge=0, description="phase resistance, ohm")
    l: float = Field(gt=0, description="phase inductance, H")
    holding_torque: float = Field(gt=0, description="N·m at i_phase")

    def stage(self, rpm: float, torque: float, v_dc: float, pwm: Pwm) -> Stage:
        if abs(torque) > self.holding_torque:
            raise Unreachable(f"{torque:g} N·m is above the holding torque of {self.holding_torque:g} N·m")
        pole_pairs = self.steps_per_rev / 4
        w = pole_pairs * abs(_rad_s(rpm))
        # Back-EMF amplitude per phase from the holding torque: T = 2 * (pole pairs) * psi * I / 2.
        back_emf = self.holding_torque / (pole_pairs * self.i_phase) * w
        # The rotor lags the current by the angle whose sine is torque over holding torque.
        # Only that share of the back-EMF is in phase with the current and does work, with
        # the sign of torque times speed; the rest adds to the inductive voltage.
        working = torque / self.holding_torque * (1.0 if rpm >= 0 else -1.0)
        resistive = self.r * self.i_phase + back_emf * working
        reactive = w * self.l * self.i_phase + back_emf * float(np.sqrt(max(1 - working**2, 0.0)))
        v_peak = float(np.hypot(resistive, reactive))
        if v_peak > self.usable_voltage * v_dc:
            raise Unreachable(
                f"holding {self.i_phase:g} A at {rpm:g} rpm needs {written(v_peak, 4)} V, more than "
                f"{_stage_gives(self.usable_voltage, v_dc)}: at this speed the current, and the torque, fall"
            )
        return _sinusoidal_stage(
            i_rms=self.i_phase / np.sqrt(2),
            v_peak=v_peak,
            power_factor=float(resistive / v_peak) if v_peak else 1.0,
            f_out=float(w / (2 * np.pi)),
            v_dc=v_dc,
            pwm=Pwm.sine,
            legs=4,
            p_shaft=torque * _rad_s(rpm),
            p_loss=self.r * self.i_phase**2,
            summary=[("set phase current", self.i_phase, "A peak")],
            notes=[
                "stepper: current is the driver's set value, not derived from the torque",
                "stepper: the back-EMF that does no work is added to the inductive voltage, the highest-voltage case",
            ],
            leg_voltage=v_dc,
        )


Machine = Annotated[Pmsm | SynRm | Induction | Bldc | BrushedDc | SeriesDc | Stepper, Field(discriminator="type")]
ADAPTER = TypeAdapter(Machine)


def load_machine(path: str | Path):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    data.setdefault("type", "pmsm")
    return ADAPTER.validate_python(data)


TEMPLATES = {
    "pmsm": """\
# Permanent-magnet synchronous motor (also a brushless motor run with sinusoidal
# currents and field-oriented control). The values below describe a made-up 48 V
# robot-joint motor. Replace them with your motor's.
type: pmsm
name: my motor
magnets: surface      # surface: magnets on the rotor surface (Ld = Lq). Inner or outer rotor alike
                      # inset: magnets set into the surface (Lq a little above Ld)
                      # interior: magnets buried in the rotor (Lq > Ld, adds reluctance torque)
pole_pairs: 7         # number of magnet poles divided by 2

# Back-EMF: give exactly one of the three.
kv: 100               # speed constant, rpm per volt (peak line-to-line)
# ke: 10.0            # back-EMF constant, peak line-to-line volts per 1000 rpm
# flux_linkage: 0.0079  # permanent-magnet flux linkage, Wb peak

# Inductance: one value for a surface-magnet motor, two for interior magnets.
l: 0.00012            # phase inductance, H (line-to-line inductance divided by 2)
# ld: 0.00010         # d-axis inductance, H
# lq: 0.00018         # q-axis inductance, H

rs: 0.045             # phase resistance, ohm (line-to-line resistance divided by 2)
i_max: 40             # optional: winding current limit, A rms
""",
    "synrm": """\
# Synchronous reluctance motor: a shaped steel rotor, no magnets. A made-up 400 V
# class motor of about 1.5 kW.
type: synrm
name: my motor
pole_pairs: 2
ld: 0.22              # inductance along the rotor's easy axis, H
lq: 0.045             # inductance across it, H (must be smaller than ld)
rs: 2.2               # phase resistance, ohm
i_max: 6              # optional: winding current limit, A rms
""",
    "induction": """\
# Induction motor. Per-phase equivalent-circuit values, rotor referred to the
# stator. A made-up 400 V class motor of about 1.5 kW.
type: induction
name: my motor
pole_pairs: 2         # 2 pole pairs: about 1500 rpm at 50 Hz
rs: 4.0               # stator resistance, ohm
rr: 3.5               # rotor resistance, ohm
lm: 0.32              # magnetising inductance, H
lls: 0.015            # stator leakage inductance, H
llr: 0.015            # rotor leakage inductance, H
i_magnetising: 2.4    # magnetising current at rated flux, A peak (about the no-load current)
i_max: 3.6            # optional: winding current limit, A rms
""",
    "bldc": """\
# Brushless DC motor driven with block (six-step, trapezoidal) commutation.
# A made-up 48 V robot-joint motor.
type: bldc
name: my motor
pole_pairs: 7
kt: 0.09              # torque constant, N·m per A  (= 9.55 / Kv in rpm per volt)
r: 0.08               # phase-to-phase resistance, ohm
l: 0.00012            # optional: phase-to-phase inductance, H. Sets the current ripple
i_max: 40             # optional: winding current limit, A
""",
    "dc": """\
# Brushed DC motor on an H-bridge. A made-up 24 V gearmotor (values at the motor shaft).
type: dc
name: my motor
kt: 0.05              # torque constant, N·m per A
r: 0.4                # armature resistance, ohm
l: 0.0006             # optional: armature inductance, H. Sets the current ripple
i_max: 20             # optional: current limit, A
# drive: unipolar     # unipolar (default): one leg chops, lower loss
                      # bipolar: both legs switch every period
""",
    "dc_series": """\
# Brushed DC motor with a series field (power tools, starters, universal motors).
# A made-up 24 V motor.
type: dc_series
name: my motor
k: 0.004              # torque per current squared, N·m per A^2
r: 0.25               # armature plus field resistance, ohm
i_max: 30             # optional: current limit, A
""",
    "stepper": """\
# Bipolar stepper on two H-bridges with microstepping. A made-up NEMA 23 size motor.
type: stepper
name: my motor
steps_per_rev: 200    # 200 for a 1.8 degree motor
i_phase: 2.8          # phase current the driver is set to, A peak
r: 0.9                # phase resistance, ohm
l: 0.0025             # phase inductance, H
holding_torque: 1.2   # N·m at i_phase
""",
}
