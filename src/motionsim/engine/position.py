"""The losses of one switch position over the output period: its switch and its reverse
path, at the junction temperatures given."""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from motionsim.device.schema import ChipKind, Device
from motionsim.engine.losses import conducted, energy, voltage
from motionsim.engine.modulation import Role
from motionsim.engine.mosfet import mosfet_losses
from motionsim.engine.point import DiodeLoss, OperatingPoint, SwitchLoss


def _position_losses(
    device: Device, role: Role, op: OperatingPoint, tj_switch: float | np.ndarray, tj_diode: float | np.ndarray
) -> tuple[SwitchLoss, DiodeLoss, np.ndarray, np.ndarray]:
    """Losses of the switch and reverse path of one role, at the junction temperatures
    given: one for the period, or one at each of its instants.

    Returns the averages and the two loss waveforms over the period.
    """
    if device.switch.kind is ChipKind.mosfet:
        return mosfet_losses(device.switch, role, op, tj_switch, device.technology)
    i = role.current

    sw, d = device.switch, device.diode
    # The device model sees to it that an IGBT has its energies and its diode.
    assert sw.e_on is not None and sw.e_off is not None and d is not None
    p_cond_sw = role.d_switch * conducted(lambda at: voltage(sw, at, tj_switch), role)
    i_on = i if role.current_on is None else role.current_on
    i_off = i if role.current_off is None else role.current_off
    p_on = role.switch_events * energy(sw.e_on, i_on, tj_switch, op.v_dc, op.rg_on) * op.f_sw
    p_off = role.switch_events * energy(sw.e_off, i_off, tj_switch, op.v_dc, op.rg_off) * op.f_sw

    p_cond_d = role.d_reverse * conducted(lambda at: voltage(d, at, tj_diode), role)
    if d.e_rr is not None:
        # The diode recovers when the other switch of its leg turns on: at the bottom of the ripple.
        p_rr = role.reverse_events * energy(d.e_rr, i_on, tj_diode, op.v_dc) * op.f_sw
    else:
        p_rr = np.zeros_like(i)

    return (
        SwitchLoss(float(p_cond_sw.mean()), float(p_on.mean()), float(p_off.mean())),
        DiodeLoss(float(p_cond_d.mean()), float(p_rr.mean())),
        p_cond_sw + p_on + p_off,
        p_cond_d + p_rr,
    )


def switching_period(
    device: Device, role: Role, op: OperatingPoint, tj_switch: float, tj_diode: float
) -> dict[str, float]:
    """One PWM period of a role's switch, at the instant of the output period where it
    works hardest: the current it carries, how long it is on, what it loses while on, and
    the energy of each turn-on and turn-off.

    Found by asking the loss model about a switch that is on for the whole of one sample
    and switches in it, so nothing here is worked out a second way.
    """
    k = int(np.argmax(role.current * role.d_switch))
    one, none = np.ones(1), np.zeros(1)
    share = max(int(op.parallel), 1)  # one device of those in parallel
    sample = replace(
        role,
        count=1,
        current=role.current[k : k + 1] / share,
        d_switch=one,
        d_reverse=none,
        switch_events=one,
        reverse_events=none,
    )
    sw, _, _, _ = _position_losses(device, sample, op, tj_switch, tj_diode)
    switches = bool(role.switch_events[k] > 0)
    return {
        "current": float(role.current[k]) / share,
        "duty": float(role.d_switch[k]),
        "p_on": sw.conduction,
        "e_on": sw.turn_on / op.f_sw if switches else 0.0,
        "e_off": sw.turn_off / op.f_sw if switches else 0.0,
        "f_sw": op.f_sw,
    }
