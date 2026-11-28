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
from motionsim.engine.losses import conducted, energy, voltage
from motionsim.engine.modulation import Role
from motionsim.engine.notes import Code, Note
from motionsim.engine.point import DiodeLoss, OperatingPoint, SwitchLoss
from motionsim.package.materials import body_drop, family


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


def miller_charge(c, v_dc: float) -> float:
    """Gate-drain charge at the DC voltage, C.

    It is tabulated at v_ref. The gate-drain capacitance falls with the voltage across it
    about as an abrupt junction's, so on a lower supply the charge is smaller by the square
    root of the ratio. Above v_ref it is kept as tabulated: the capacitance there is small,
    and the tabulated figure is the safe one for a loss."""
    return c.q_gd * min(v_dc / c.v_ref, 1.0) ** 0.5


# Recovery charge away from the current it was tabulated at follows the square root of the
# current, above and below: the charge a junction stores rises with the current, and the
# faster commutation of a larger current leaves less of it time to recombine. Datasheets
# that draw recovery charge against current show a power between a half and nearly one.
# Above the test current the square root is the low end of the growth; below it, it is the
# high end of what is left, and the safe one for a loss.
RECOVERY_GROWTH = 0.5
# With temperature the carriers of a silicon junction live longer and more of them are
# still there to be swept out: datasheets that give the charge hot show 1.5 to 2.5 times
# the 25 °C figure at 125 to 150 °C. A rise of 0.7% a kelvin from 25 °C is 1.7 times at
# 125 °C. A silicon-carbide body diode stores almost nothing and what is tabulated is
# mostly its capacitance, which does not move; a GaN transistor has no junction to recover.
RECOVERY_RISE = 0.007  # per K, silicon
RECOVERY_REFERENCE = 25.0  # °C, where a recovery charge is tabulated


def recovery_rises(technology: str) -> bool:
    """Whether the reverse path of this kind of transistor is a silicon junction, whose
    recovery charge grows with temperature."""
    return bool(technology) and family(technology) == "si"


def recovery_charge(c, current: np.ndarray, tj=None, technology: str = "") -> np.ndarray:
    """Recovery charge of the reverse path at each current, C.

    It follows the square root of the current, from the current it was measured at, and is
    nothing at no current. tj and technology bring it to the junction
    temperature for a silicon junction; left out, the tabulated figure is used as it is.
    """
    current = np.asarray(current, dtype=float)
    if c.q_rr_current:
        q_rr = c.q_rr * (np.maximum(current, 0.0) / c.q_rr_current) ** RECOVERY_GROWTH
    else:
        q_rr = c.q_rr * (current > 0)
    if tj is not None and recovery_rises(technology):
        q_rr = q_rr * np.maximum(1.0 + RECOVERY_RISE * (np.asarray(tj, dtype=float) - RECOVERY_REFERENCE), 0.0)
    return q_rr


def recovery_note(chip: Chip, technology: str, i_peak: float, tj: float) -> Note | None:
    """What a result should say about a recovery charge used away from where it was
    tabulated, or None where it is used as tabulated or there is none."""
    c = chip.charge
    if c is None or not c.q_rr or (chip.e_on is not None and chip.e_off is not None):
        return None
    said = []
    if c.q_rr_current and abs(i_peak - c.q_rr_current) > 0.01 * c.q_rr_current:
        said.append(
            f"away from the {c.q_rr_current:g} A it was measured at it is taken to follow the square root of the "
            "current"
        )
    if recovery_rises(technology) and abs(tj - RECOVERY_REFERENCE) > 1.0:
        factor = max(1.0 + RECOVERY_RISE * (tj - RECOVERY_REFERENCE), 0.0)
        said.append(
            f"it is taken as tabulated at {RECOVERY_REFERENCE:g} °C and {factor:.2f} times that at {tj:.0f} °C, "
            "the usual rise of a silicon junction; a datasheet's own hot figure is not read"
        )
    if not said:
        return None
    return Note(Code.recovery_charge_assumed, "recovery energy", "recovery charge: " + "; ".join(said))


def charge_energies(
    chip: Chip, current: np.ndarray, op: OperatingPoint, tj=None, technology: str = ""
) -> tuple[np.ndarray, np.ndarray]:
    """Hard-switching turn-on and turn-off energy from gate and output charge.

    Turn-on and turn-off each have a current-voltage overlap lasting as long as
    the gate current takes to move the charge between threshold and the end of
    the plateau. Turn-on also dissipates the output charge of both devices in
    the leg and any recovery charge, each taken through the full DC voltage.
    tj and technology are for the recovery charge alone: see recovery_charge.
    """
    c = chip.charge
    assert c is not None  # a transistor with no measured energy has a charge model: the device model sees to it
    # A drive voltage that was given and cannot switch the part is said first: no gate resistor
    # is chosen for it, and saying the resistors are missing would send the user the wrong way.
    if op.v_drive is not None and op.v_drive <= c.v_plateau:
        raise MissingGateDrive(f"gate drive voltage {op.v_drive:g} V does not exceed the plateau ({c.v_plateau:g} V)")
    if op.v_drive is None or op.rg_on is None or op.rg_off is None:
        raise MissingGateDrive(
            "this device has no measured switching energy; give the gate drive voltage and the "
            "turn-on and turn-off gate resistances to estimate it from charge"
        )
    moved = c.q_gs - c.q_g_th + miller_charge(c, op.v_dc)
    t_on = moved * op.rg_on / (op.v_drive - c.v_plateau)
    # At turn-off the gate is pulled from its plateau to the driver's low level, nought or below.
    t_off = moved * op.rg_off / (c.v_plateau - (op.v_drive_off or 0.0))
    q_oss = output_charge(c, op.v_dc)
    q_rr = recovery_charge(c, current, tj, technology)
    e_on = 0.5 * op.v_dc * current * t_on + (q_oss + q_rr) * op.v_dc
    e_off = 0.5 * op.v_dc * current * t_off
    return e_on, e_off


def mosfet_losses(
    chip: Chip, role: Role, op: OperatingPoint, tj: float | np.ndarray, technology: str = ""
) -> tuple[SwitchLoss, DiodeLoss, np.ndarray, np.ndarray]:
    """technology names the kind of transistor, for what its recovery charge does with
    temperature; left out, the charge is used as tabulated."""
    mag = role.current

    # Reverse current loses two dead times of channel conduction per switching period.
    dead = role.reverse_events * np.minimum(2 * op.t_dead * op.f_sw, role.d_reverse)
    p_cond = (role.d_switch + role.d_reverse - dead) * conducted(lambda i: voltage(chip, i, tj), role)
    if chip.reverse is not None:
        v_reverse = np.maximum(lookup.evaluate(chip.reverse.curves, mag, tj), 0.0)
    else:
        # With both gates off the channel carries nothing, and the current goes through the
        # body diode, or for GaN the channel in reverse: never less than the channel would
        # have dropped, which is all that taking the dead time out of conduction removed.
        # Its drop is the technology's usual one, said in the result (D157).
        v_reverse = np.maximum(body_drop(technology)[0], voltage(chip, mag, tj))
    p_dead = dead * mag * v_reverse

    mag_on = mag if role.current_on is None else role.current_on
    mag_off = mag if role.current_off is None else role.current_off
    if chip.e_on is not None and chip.e_off is not None:
        e_on = energy(chip.e_on, mag_on, tj, op.v_dc, op.rg_on)
        e_off = energy(chip.e_off, mag_off, tj, op.v_dc, op.rg_off)
    else:
        e_on = charge_energies(chip, mag_on, op, tj, technology)[0]
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
