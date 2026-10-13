"""Losses of one field-effect transistor position.

A mosfet has no separate diode. When the phase current is negative the
high-side device carries it in reverse: through its channel while its gate is
on, and through the body diode (or, for GaN, the reverse-biased channel) during
the dead time when both gates are off.
"""

from __future__ import annotations

import numpy as np

from motionsim.device.schema import Chip
from motionsim.engine import lookup
from motionsim.engine.losses import energy, voltage
from motionsim.engine.modulation import Role
from motionsim.engine.point import DiodeLoss, OperatingPoint, SwitchLoss


class MissingGateDrive(ValueError):
    """Switching loss from charge needs the gate drive voltage and resistances."""


def output_charge(c, v_dc: float) -> float:
    """Output charge of one device at the DC voltage, C."""
    if c.q_oss_scaling == "table":
        top = c.oss_voltage[-1]
        if v_dc <= top:
            return float(np.interp(v_dc, c.oss_voltage, c.oss_charge))
        # Beyond the curve the capacitance is small and falling; the charge of an abrupt
        # junction carries it on.
        return float(c.oss_charge[-1] * (v_dc / top) ** 0.5)
    return c.q_oss * (v_dc / c.v_ref) ** (0.5 if c.q_oss_scaling == "sqrt" else 1.0)


def charge_energies(chip: Chip, current: np.ndarray, op: OperatingPoint) -> tuple[np.ndarray, np.ndarray]:
    """Hard-switching turn-on and turn-off energy from gate and output charge.

    Turn-on and turn-off each have a current-voltage overlap lasting as long as
    the gate current takes to move the charge between threshold and the end of
    the plateau. Turn-on also dissipates the output charge of both devices in
    the leg and any recovery charge, each taken through the full DC voltage.
    """
    if op.v_drive is None or op.rg_on is None or op.rg_off is None:
        raise MissingGateDrive(
            "this device has no measured switching energy; give the gate drive voltage and the "
            "turn-on and turn-off gate resistances to estimate it from charge"
        )
    c = chip.charge
    if op.v_drive <= c.v_plateau:
        raise MissingGateDrive(f"gate drive voltage {op.v_drive:g} V does not exceed the plateau ({c.v_plateau:g} V)")
    moved = c.q_gs - c.q_g_th + c.q_gd
    t_on = moved * op.rg_on / (op.v_drive - c.v_plateau)
    t_off = moved * op.rg_off / c.v_plateau
    q_oss = output_charge(c, op.v_dc)
    # Recovery charge falls with the current the diode carried, and is nothing at no current.
    if c.q_rr_current:
        q_rr = c.q_rr * np.minimum(current / c.q_rr_current, 1.0)
    else:
        q_rr = c.q_rr * (current > 0)
    e_on = 0.5 * op.v_dc * current * t_on + (q_oss + q_rr) * op.v_dc
    e_off = 0.5 * op.v_dc * current * t_off
    return e_on, e_off


def mosfet_losses(
    chip: Chip, role: Role, op: OperatingPoint, tj: float
) -> tuple[SwitchLoss, DiodeLoss, np.ndarray, np.ndarray]:
    mag = role.current

    # Reverse current loses two dead times of channel conduction per switching period.
    dead = role.reverse_events * np.minimum(2 * op.t_dead * op.f_sw, role.d_reverse)
    v_on = voltage(chip, mag, tj)
    p_cond = (role.d_switch + role.d_reverse - dead) * mag * v_on
    if chip.reverse is not None:
        v_reverse = np.maximum(lookup.evaluate(chip.reverse.curves, mag, tj), 0.0)
        p_dead = dead * mag * v_reverse
    else:
        p_dead = np.zeros_like(mag)

    mag_on = mag if role.current_on is None else role.current_on
    mag_off = mag if role.current_off is None else role.current_off
    if chip.e_on is not None and chip.e_off is not None:
        e_on = energy(chip.e_on, mag_on, tj, op.v_dc, op.rg_on)
        e_off = energy(chip.e_off, mag_off, tj, op.v_dc, op.rg_off)
    else:
        e_on = charge_energies(chip, mag_on, op)[0]
        e_off = charge_energies(chip, mag_off, op)[1]
    p_on = role.switch_events * e_on * op.f_sw
    p_off = role.switch_events * e_off * op.f_sw
    # A tabulated recovery energy is lost in the body diode of the device that was conducting
    # in reverse. With charge-based switching the recovery charge is already in turn-on.
    if chip.e_rr is not None and chip.e_on is not None:
        p_rr = role.reverse_events * energy(chip.e_rr, mag, tj, op.v_dc) * op.f_sw
    else:
        p_rr = np.zeros_like(mag)

    loss = SwitchLoss(
        conduction=float(p_cond.mean()),
        turn_on=float(p_on.mean()),
        turn_off=float(p_off.mean()),
        dead_time=float(p_dead.mean()),
        recovery=float(p_rr.mean()),
    )
    waveform = p_cond + p_on + p_off + p_dead + p_rr
    return loss, DiodeLoss(0.0, 0.0), waveform, np.zeros_like(mag)
