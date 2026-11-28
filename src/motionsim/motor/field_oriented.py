"""Motors under field-oriented control, on a three-phase inverter with sinusoidal currents:
permanent-magnet synchronous, synchronous reluctance and induction."""

from __future__ import annotations

from typing import ClassVar, Literal

import numpy as np
from pydantic import Field, model_validator

from motionsim.engine.modulation import Pwm
from motionsim.engine.notes import Code, Note
from motionsim.errors import FigureError
from motionsim.motor import pmsm
from motionsim.motor.base import _Machine, _rad_s, _sinusoidal_stage, brentq, replace_notes
from motionsim.motor.stage import Stage, Unreachable
from motionsim.text import written


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
    # A d-axis current to hold in place of the one that needs least current, A peak. Set by
    # the advice that looks for the value losing least; a motor file does not carry it.
    i_d_held: float | None = Field(default=None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _accept_catalogue_values(cls, data):
        """Accept the figures motor catalogues give in place of flux linkage and dq inductances.

        - l: one phase inductance, for a surface-magnet motor (Ld = Lq)
        - kv: speed constant, rpm per volt of peak line-to-line back-EMF
        - ke: back-EMF constant, peak line-to-line volts per 1000 rpm
        - kt: torque constant, N·m per A rms of phase current, of the magnet's torque alone
        """
        if not isinstance(data, dict):
            return data
        data = dict(data)
        if "l" in data:
            if "ld" in data or "lq" in data:
                raise FigureError("give one phase inductance, or the two axis inductances, not both", "l")
            data["ld"] = data["lq"] = data.pop("l")
        given = [k for k in ("flux_linkage", "kv", "ke", "kt") if k in data]
        if len(given) != 1:
            raise FigureError("give one of the speed constant, the back-EMF constant or the flux linkage", "kv")
        pairs = data.get("pole_pairs")
        # Bad values are left for the field checks, which name the field; nothing is
        # computed from them here.
        key = given[0]
        usable = all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 for v in (pairs, data[key]))
        if key != "flux_linkage" and not usable:
            if not (isinstance(pairs, (int, float)) and not isinstance(pairs, bool) and pairs > 0):
                raise FigureError("the pole pairs have to be a whole number above zero", "pole_pairs")
            said = {"kv": "the speed constant", "ke": "the back-EMF constant", "kt": "the torque constant"}[key]
            raise FigureError(f"{said} has to be a number above zero", key)
        if "kv" in data:
            data["flux_linkage"] = 60 / (np.sqrt(3) * 2 * np.pi * pairs * data.pop("kv"))
        elif "ke" in data:
            data["flux_linkage"] = data.pop("ke") * 60 / (1000 * np.sqrt(3) * 2 * np.pi * pairs)
        elif "kt" in data:
            # Per A rms of phase current: T = 3/2 · p · ψ · √2 · I_rms.
            data["flux_linkage"] = data.pop("kt") / (1.5 * np.sqrt(2) * pairs)
        return data

    @model_validator(mode="after")
    def _check_saliency(self) -> Pmsm:
        if self.magnets == "surface" and self.ld != self.lq:
            raise FigureError(
                "a surface-magnet motor has the same inductance on both axes; for two, take inset or interior magnets",
                "magnets",
            )
        if self.magnets != "surface" and self.lq < self.ld:
            raise FigureError("with inset or interior magnets the cross-axis inductance is at least the other", "lq")
        return self

    def state(self, rpm: float, torque: float, v_dc: float, pwm: Pwm) -> pmsm.DriveState:
        """The d- and q-axis currents and voltages the control settles to at a speed and torque."""
        motor = pmsm.Motor(
            **self.model_dump(exclude={"type", "magnets", "usable_voltage", "p_iron", "n_iron", "temperature_note"})
        )
        v_max = self.usable_voltage * pwm.max_modulation_index * v_dc / 2
        # A d-axis current held by the user is held up to the full voltage; left to the
        # control, the field is weakened from the share a drive keeps to.
        kept = v_max if self.i_d_held is not None else pmsm.WEAKENING_HEADROOM * v_max
        return pmsm.operating_state(motor, rpm, torque, kept, self.i_d_held)

    def flux_share(self, state: pmsm.DriveState) -> float:
        """The stator's flux linkage at a point, as a share of the magnet's own. Each
        inductance is the one the point was solved with: lower where the iron saturates."""
        ld, lq = self.ld, self.lq
        if self.i_sat:
            fallen = pmsm.saturated(self.i_sat, state.i_d, state.i_q)
            ld, lq = ld / fallen, lq / fallen
        return float(np.hypot(self.flux_linkage + ld * state.i_d, lq * state.i_q) / self.flux_linkage)

    def stage(self, rpm: float, torque: float, v_dc: float, pwm: Pwm) -> Stage:
        s = self.state(rpm, torque, v_dc, pwm)
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
            raise FigureError(
                "the easy-axis inductance has to be larger than the cross-axis one: a reluctance motor's torque "
                "comes from the difference",
                "ld",
            )
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
            Code.inductances_constant,
            Note(
                Code.inductances_saturate,
                "i_sat",
                f"reluctance motor: inductances follow the current, saturating about {self.i_sat:g} A",
            ),
        )

    def _solve(self, rpm: float, torque: float, v_dc: float, pwm: Pwm) -> tuple[Stage, float, float]:
        v_max = pmsm.WEAKENING_HEADROOM * self.usable_voltage * pwm.max_modulation_index * v_dc / 2
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
                    "at any current angle",
                    Code.reach_voltage,
                )
            i_d = float(brentq(excess, least, i_d))
            i_q, v_d, v_q = voltages(i_d)
        i_pk = float(np.hypot(i_d, i_q))
        if self.i_max is not None and i_pk / np.sqrt(2) > self.i_max:
            raise Unreachable(
                f"{written(torque, 3)} N·m at {written(rpm, 4)} rpm needs {written(i_pk / np.sqrt(2), 3)} A rms, above the "
                f"motor's {self.i_max:g} A limit",
                Code.reach_current,
            )
        stage = self._stage_at(rpm, torque, v_dc, pwm, (i_d, i_q, v_d, v_q), weakening)
        return stage, i_d, abs(i_q)

    def _stage_at(
        self, rpm: float, torque: float, v_dc: float, pwm: Pwm, dq: tuple[float, float, float, float], weakening: bool
    ) -> Stage:
        """The stage for currents and voltages on the two axes, as solved."""
        i_d, i_q, v_d, v_q = dq
        i_pk = float(np.hypot(i_d, i_q))
        v_pk = float(np.hypot(v_d, v_q))
        power = 1.5 * (v_d * i_d + v_q * i_q)
        return _sinusoidal_stage(
            i_rms=i_pk / np.sqrt(2),
            v_peak=v_pk,
            power_factor=float(power / (1.5 * v_pk * i_pk)) if v_pk * i_pk > 0 else 1.0,
            f_out=float(self.pole_pairs * _rad_s(rpm) / (2 * np.pi)),
            v_dc=v_dc,
            pwm=pwm,
            legs=3,
            p_shaft=torque * _rad_s(rpm),
            p_loss=1.5 * self.rs * i_pk**2,
            summary=[("field weakening", float(weakening), "yes/no")],
            notes=[
                Note(
                    Code.inductances_constant,
                    "i_sat",
                    "reluctance motor: inductances taken as constant, so saturation is not modelled",
                )
            ],
            leg_voltage=v_dc / 2,
            l_phase=(self.ld + self.lq) / 2,
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
        v_max = pmsm.WEAKENING_HEADROOM * self.usable_voltage * pwm.max_modulation_index * v_dc / 2
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
                    "at any flux level",
                    Code.reach_voltage,
                )
            i_d = float(brentq(excess, below[0], grid[list(grid).index(below[0]) - 1]))
        i_q, w, v_d, v_q = self._state(rpm, torque, i_d)
        lr = self.lm + self.llr
        i_pk, v_pk = np.hypot(i_d, i_q), np.hypot(v_d, v_q)
        if self.i_max is not None and i_pk / np.sqrt(2) > self.i_max:
            raise Unreachable(
                f"{written(torque, 3)} N·m at {written(rpm, 4)} rpm needs {written(i_pk / np.sqrt(2), 3)} A rms, above the "
                f"{self.i_max:g} A limit",
                Code.reach_current,
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
