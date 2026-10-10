"""Loss and temperature solver for a motor-drive power stage.

A power stage is described as a set of roles: kinds of switch position, each
with its current and conduction pattern over a period. Losses are averaged
over the period for each role. Junction temperatures feed back into the loss
tables, so the solver iterates until the assumed and computed temperatures
agree.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from motionsim.device.schema import Basis, Chip, ChipKind, Device, FosterNetwork, SwitchingEnergy
from motionsim.engine import assumed
from motionsim.engine import lookup
from motionsim.engine.modulation import Pwm, Role, phase_leg_roles, waveform
from motionsim.engine.thermal import periodic_rise, steady_state_rise

INVERTER_POSITIONS = 6
SLOWEST_OUTPUT = 0.1  # Hz; a stopped output is treated as turning this slowly


class PeakBasis(str, Enum):
    transient = "transient"  # from the device's own transient thermal data
    assumed = "assumed"  # no transient data: the response computed for a generic package is used


class Validity(str, Enum):
    interpolated = "interpolated"  # inside measured or digitised curves
    extrapolated = "extrapolated"  # beyond them, or scaled from other test conditions
    assumed = "assumed"  # rests on table points and a stated shape assumption


@dataclass(frozen=True)
class OperatingPoint:
    v_dc: float
    i_rms: float
    modulation_index: float
    power_factor: float
    f_sw: float
    t_sink: float
    f_out: float = 50.0
    pwm: Pwm = Pwm.sine
    t_dead: float = 0.0  # s, between one switch turning off and the other turning on
    v_drive: float | None = None  # gate drive voltage, V
    rg_on: float | None = None  # total turn-on gate resistance, ohm
    rg_off: float | None = None  # total turn-off gate resistance, ohm
    # Commutation-loop inductance, H: of one device's own loop. With devices in parallel
    # each has its loop and switches its share of the current.
    l_loop: float | None = None
    t_min_pulse: float = 0.0  # s, the shortest pulse the gate drive passes
    parallel: int = 1  # devices side by side at each switch position, sharing its current
    n_steps: int = 2048


@dataclass(frozen=True)
class SwitchLoss:
    conduction: float
    turn_on: float
    turn_off: float
    dead_time: float = 0.0  # mosfet: reverse conduction with both gates off
    recovery: float = 0.0  # mosfet: recovery of its own body diode

    @property
    def total(self) -> float:
        return self.conduction + self.turn_on + self.turn_off + self.dead_time + self.recovery


@dataclass(frozen=True)
class DiodeLoss:
    conduction: float
    recovery: float

    @property
    def total(self) -> float:
        return self.conduction + self.recovery


@dataclass(frozen=True)
class RoleResult:
    """One kind of switch position."""

    name: str
    count: int
    switch: SwitchLoss
    diode: DiodeLoss
    tj_switch: float
    tj_diode: float
    tj_switch_peak: float
    tj_diode_peak: float
    t_case: float
    # Loss of one switch and one diode against position in the period, W.
    p_switch: np.ndarray | None = field(default=None, compare=False, repr=False)
    p_diode: np.ndarray | None = field(default=None, compare=False, repr=False)

    @property
    def hottest(self) -> float:
        return max(self.tj_switch_peak, self.tj_diode_peak)


@dataclass(frozen=True)
class Result:
    """Outcome for the whole power stage. The loss and temperature fields
    describe the hottest role; roles lists every one."""

    switch: SwitchLoss
    diode: DiodeLoss
    tj_switch: float
    tj_diode: float
    tj_switch_peak: float
    tj_diode_peak: float
    peak_basis: PeakBasis
    t_case: float
    p_inverter: float
    p_out: float
    converged: bool
    iterations: int
    validity: Validity
    notes: list[str] = field(default_factory=list)
    limits: list[str] = field(default_factory=list)
    rating_warnings: list[str] = field(default_factory=list)
    roles: list[RoleResult] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)  # thermal values assumed, not given
    tj_peak_range: tuple[float, float] | None = None  # hottest junction across those assumptions

    @property
    def efficiency(self) -> float | None:
        if self.p_out <= 0:
            return None
        return self.p_out / (self.p_out + self.p_inverter)


class ThermalRunaway(RuntimeError):
    """Losses grow faster with temperature than the thermal path removes them."""


def gate_factor(table: SwitchingEnergy, rg: float | None) -> float:
    """Energy at a gate resistor as a multiple of the energy at the datasheet's own, from the
    datasheet's figure of energy against gate resistance. 1 where there is no such figure or
    no resistor is given. Outside the figure's range the nearest end is used: it is not
    extended."""
    if rg is None or not table.rg_values or not table.rg_factor:
        return 1.0
    return float(np.interp(rg, table.rg_values, table.rg_factor))


def voltage_factor(table: SwitchingEnergy, v_dc: float) -> float:
    """Energy at a supply voltage as a multiple of the energy at the datasheet's test voltage.

    From the datasheet's figure of energy against voltage where it has one, inside that
    figure's range. Otherwise in proportion to voltage, which is the least a real device
    does: above the test voltage most rise faster.
    """
    if table.v_values and table.v_factor and table.v_values[0] <= v_dc <= table.v_values[-1]:
        return float(np.interp(v_dc, table.v_values, table.v_factor))
    return v_dc / table.v_ref


def _energy(
    table: SwitchingEnergy, current: np.ndarray, tj: float, v_dc: float, rg: float | None = None
) -> np.ndarray:
    e = lookup.evaluate(table.curves, current, tj) * voltage_factor(table, v_dc) * gate_factor(table, rg)
    return np.maximum(e, 0.0)


def _voltage(chip: Chip, current: np.ndarray, tj: float) -> np.ndarray:
    return np.maximum(lookup.evaluate(chip.conduction.curves, current, tj), 0.0)


def _position_losses(
    device: Device, role: Role, op: OperatingPoint, tj_switch: float, tj_diode: float
) -> tuple[SwitchLoss, DiodeLoss, np.ndarray, np.ndarray]:
    """Losses of the switch and reverse path of one role.

    Returns the averages and the two loss waveforms over the period.
    """
    if device.switch.kind is ChipKind.mosfet:
        from motionsim.engine.mosfet import mosfet_losses

        return mosfet_losses(device.switch, role, op, tj_switch)
    i = role.current

    sw = device.switch
    p_cond_sw = role.d_switch * i * _voltage(sw, i, tj_switch)
    i_on = i if role.current_on is None else role.current_on
    i_off = i if role.current_off is None else role.current_off
    p_on = role.switch_events * _energy(sw.e_on, i_on, tj_switch, op.v_dc, op.rg_on) * op.f_sw
    p_off = role.switch_events * _energy(sw.e_off, i_off, tj_switch, op.v_dc, op.rg_off) * op.f_sw

    d = device.diode
    p_cond_d = role.d_reverse * i * _voltage(d, i, tj_diode)
    if d.e_rr is not None:
        # The diode recovers when the other switch of its leg turns on: at the bottom of the ripple.
        p_rr = role.reverse_events * _energy(d.e_rr, i_on, tj_diode, op.v_dc) * op.f_sw
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
    from dataclasses import replace

    k = int(np.argmax(role.current * role.d_switch))
    one, none = np.ones(1), np.zeros(1)
    share = max(int(op.parallel), 1)  # one device of those in parallel
    sample = replace(
        role, count=1, current=role.current[k : k + 1] / share, d_switch=one, d_reverse=none,
        switch_events=one, reverse_events=none,
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


def _mutual(device: Device, variant: str) -> float:
    """Coupling between chips: the user's value, or one computed for a generic package."""
    package = device.package
    if package.rth_mutual is not None:
        return package.rth_mutual
    if package.topology.positions == 1:
        return 0.0
    coupling = assumed.module_coupling(
        package.construction, device.ratings.i_nominal, variant, package.interface
    )
    # The computed coupling is measured from the heatsink, so it holds the interface layer
    # that every chip's heat crosses. That shared part is carried by the case-to-sink
    # resistance, given or computed, which applies to the whole package's loss.
    return max(coupling - _case_sink(device, variant), 0.0)


def _case_sink(device: Device, variant: str) -> float:
    """Case-to-heatsink resistance: the user's, or computed for a discrete package's outline."""
    package = device.package
    if package.rth_case_sink is not None:
        return package.rth_case_sink
    if package.outline is not None:
        return assumed.interface_resistance(
            package.outline, device.ratings.i_nominal, variant, package.interface
        )
    if package.topology.positions > 1:
        # A module's datasheet gives junction to case. The layer between case and heatsink
        # is still there, and a chip's own heat crosses it like its neighbours' does.
        return assumed.module_interface(
            package.construction, device.ratings.i_nominal, variant, package.interface
        )
    return 0.0


def _neighbour_rise(device: Device, own: float, package: float, variant: str) -> float:
    """Steady rise of one junction from the losses of every other chip in its package."""
    return _mutual(device, variant) * max(package - own, 0.0)


def thermal_network(
    device: Device, chip: Chip, variant: str = "typical"
) -> tuple[FosterNetwork, PeakBasis]:
    """A chip's junction-to-case network with time constants: the device's own, or its
    resistance spread over the response computed for a generic package."""
    network, basis = chip.thermal, PeakBasis.transient
    if network.tau is None:
        package = device.package
        template, _ = assumed.template_for(
            package.construction, package.outline, package.topology.positions
        )
        kind = "diode" if chip.kind is ChipKind.diode else "switch"
        stages = assumed.response(
            template, device.ratings.i_nominal, variant, package.interface, kind
        )
        network = FosterNetwork(
            r=[share * chip.thermal.rth for share, _ in stages],
            tau=[tau for _, tau in stages],
            source=chip.thermal.source,
        )
        basis = PeakBasis.assumed
    return network, basis


def _peak(
    device: Device, chip: Chip, power: np.ndarray, period: float, t_case: float, variant: str
) -> tuple[float, PeakBasis]:
    """Highest junction temperature within the period."""
    network, basis = thermal_network(device, chip, variant)
    return t_case + float(periodic_rise(network, power, period).max()), basis


def _assumptions(device: Device, peak_basis: PeakBasis) -> list[str]:
    out = []
    package = device.package
    if package.rth_mutual is None and package.topology.positions > 1:
        low, typical, high = (_mutual(device, v) for v in assumed.VARIANTS)
        kind = {
            "leadframe": "a generic moulded leadframe module",
            "substrate": "a generic ceramic-substrate module",
            "unknown": "a generic module, construction not given",
        }[package.construction]
        out.append(
            f"heating between chips computed for {kind}: {typical:.2f} K/W "
            f"({low:.2f} to {high:.2f}) per watt in each other chip"
        )
    if package.rth_case_sink is None and package.outline is None and package.topology.positions > 1:
        low, typical, high = (_case_sink(device, v) for v in assumed.VARIANTS)
        out.append(
            f"case-to-heatsink resistance computed for the interface layer under a generic module on "
            f"{package.interface}: {typical:.3f} K/W ({low:.3f} to {high:.3f})"
        )
    if package.rth_case_sink is None and package.outline is not None:
        low, typical, high = (_case_sink(device, v) for v in assumed.VARIANTS)
        out.append(
            f"case-to-heatsink resistance computed for a {package.outline} on {package.interface}: "
            f"{typical:.2f} K/W ({low:.2f} to {high:.2f})"
        )
    if peak_basis is PeakBasis.assumed:
        template, guessed = assumed.template_for(
            package.construction, package.outline, package.topology.positions
        )
        out.append(
            "no transient thermal data: the temperature swing within the period uses the "
            f"response computed for a generic {template}"
            + (" (package kind not given)" if guessed else "")
        )
    return out


def _envelope_notes(
    device: Device, op: OperatingPoint, i_pk: float, tj_switch: float, tj_diode: float
) -> list[str]:
    """Where the operating point leaves the characterised data."""
    notes: list[str] = []
    sw, d = device.switch, device.diode
    tables = [("switch conduction", sw.conduction, tj_switch, None)]
    if sw.e_on is not None and sw.e_off is not None:
        tables.append(("turn-on energy", sw.e_on, tj_switch, sw.e_on.v_ref))
        tables.append(("turn-off energy", sw.e_off, tj_switch, sw.e_off.v_ref))
    else:
        notes.append(
            "switching loss: estimated from gate and output charge, not from measured energy; "
            + (sw.charge.assumption or "")
        )
        if abs(op.v_dc - sw.charge.v_ref) > 0.01 * sw.charge.v_ref:
            scaling = sw.charge.q_oss_scaling
            if scaling == "table":
                if op.v_dc > sw.charge.oss_voltage[-1]:
                    notes.append(
                        f"output charge: {op.v_dc:.0f} V is beyond the capacitance curve "
                        f"({sw.charge.oss_voltage[-1]:.0f} V)"
                    )
            else:
                rule = "as the square root of voltage" if scaling == "sqrt" else "linearly"
                notes.append(
                    f"output charge: scaled {rule} from {sw.charge.v_ref:.0f} V to {op.v_dc:.0f} V"
                )
    if sw.reverse is not None and op.t_dead > 0:
        tables.append(("reverse conduction", sw.reverse, tj_switch, None))
    if d is None and sw.e_rr is not None:
        tables.append(("recovery energy", sw.e_rr, tj_switch, sw.e_rr.v_ref))
    if d is not None:
        tables.append(("diode conduction", d.conduction, tj_diode, None))
        if d.e_rr is not None:
            tables.append(("recovery energy", d.e_rr, tj_diode, d.e_rr.v_ref))
    for name, table, tj, v_ref in tables:
        curves = table.curves
        i_min, i_max = lookup.current_range(curves)
        if table.basis is Basis.curve and i_pk < i_min:
            notes.append(
                f"{name}: peak current {i_pk:.3g} A is below the lowest data point ({i_min:.3g} A)"
            )
        if table.basis is Basis.point:
            notes.append(f"{name}: built from table points up to {i_max:.3g} A; {table.assumption}")
            if i_pk > i_max:
                notes.append(f"{name}: peak current {i_pk:.3g} A is above the last table point")
        elif i_pk > i_max:
            notes.append(f"{name}: peak current {i_pk:.3g} A is above the data ({i_max:.3g} A)")
        t_min, t_max = lookup.temperature_range(curves)
        if len(curves) == 1:
            if abs(tj - t_min) > 1.0:
                notes.append(f"{name}: only characterised at {t_min:.0f} °C, used at {tj:.0f} °C")
        elif not t_min <= tj <= t_max:
            notes.append(
                f"{name}: {tj:.0f} °C is outside the data ({t_min:.0f} to {t_max:.0f} °C)"
            )
        if v_ref is not None and abs(op.v_dc - v_ref) > 0.01 * v_ref:
            followed = (
                table is not None and table.v_values and table.v_values[0] <= op.v_dc <= table.v_values[-1]
            )
            if followed:
                notes.append(
                    f"{name}: taken from {v_ref:.0f} V to {op.v_dc:.0f} V along the datasheet's own "
                    "figure of energy against voltage"
                )
            elif op.v_dc > v_ref:
                # In proportion is the least a real device does. Silicon IGBTs rise about as
                # the power 1.4 of the voltage: how much that could add is said, not applied.
                more = (op.v_dc / v_ref) ** 0.4 - 1
                notes.append(
                    f"{name}: scaled linearly from {v_ref:.0f} V test voltage to {op.v_dc:.0f} V; above "
                    f"the test voltage real devices rise faster, by up to {more:.0%} more here"
                )
            else:
                notes.append(
                    f"{name}: scaled linearly from {v_ref:.0f} V test voltage to {op.v_dc:.0f} V"
                )
    return notes


def _uses_point_tables(device: Device) -> bool:
    sw, d = device.switch, device.diode
    tables = [sw.conduction, sw.e_on, sw.e_off, sw.reverse]
    if d is None:
        tables.append(sw.e_rr)
    if d is not None:
        tables += [d.conduction, d.e_rr]
    measured = sw.e_on is not None and sw.e_off is not None
    return not measured or any(t is not None and t.basis is Basis.point for t in tables)


def _validity(device: Device, notes: list[str]) -> Validity:
    if _uses_point_tables(device):
        return Validity.assumed
    return Validity.extrapolated if notes else Validity.interpolated


HIGH_VOLTAGE_USE = 0.8  # share of the voltage rating above which little is left for overshoot


def _rating_warnings(device: Device, op: OperatingPoint, i_pk: float) -> list[str]:
    """Electrical limits the operating point reaches or cannot be checked against."""
    warnings: list[str] = []
    v_max = device.ratings.v_max
    sw = device.switch
    technology = device.technology.lower()
    if op.v_dc > v_max:
        warnings.append(f"DC voltage {op.v_dc:g} V is above the {v_max:g} V rating")
        return warnings

    overshoot = None
    if op.l_loop is not None and sw.charge is not None and op.rg_off is not None:
        # Current falls while the gate moves from plateau to threshold.
        t_fall = (sw.charge.q_gs - sw.charge.q_g_th) * op.rg_off / sw.charge.v_plateau
        if t_fall > 0:
            overshoot = op.l_loop * i_pk / t_fall
    if overshoot is None:
        if op.v_dc > HIGH_VOLTAGE_USE * v_max:
            warnings.append(
                f"DC voltage is {op.v_dc / v_max:.0%} of the rating and turn-off overshoot is not "
                "checked: give the loop inductance"
                + ("" if sw.charge is not None else " (and this device has no charge data)")
            )
        return warnings

    peak = op.v_dc + overshoot
    if peak > v_max:
        if "gan" in technology:
            consequence = "GaN transistors have no avalanche capability, so this is a violation"
        elif sw.kind is ChipKind.mosfet:
            consequence = (
                "the device would avalanche every switching cycle; check its repetitive "
                "avalanche rating or slow the turn-off"
            )
        else:
            consequence = "IGBTs are not avalanche rated, so this is a violation"
        warnings.append(
            f"turn-off overshoot of about {overshoot:.0f} V takes the device to {peak:.0f} V, "
            f"above its {v_max:g} V rating: {consequence}"
        )
    elif peak > HIGH_VOLTAGE_USE * v_max:
        warnings.append(
            f"turn-off overshoot of about {overshoot:.0f} V takes the device to {peak:.0f} V, "
            f"{peak / v_max:.0%} of its rating"
        )
    return warnings


def _model_limits(device: Device, peak_basis: PeakBasis) -> list[str]:
    """Physics this result leaves out."""
    limits = ["losses use each chip's average temperature over the output period"]
    package = device.package
    if package.rth_case_sink is None and package.outline is None and package.topology.positions == 1:
        limits.append(
            "case-to-heatsink resistance is not given and no package outline is set, so the "
            "sink temperature is used as the case temperature"
        )
    if device.switch.kind is ChipKind.mosfet and device.switch.reverse is None:
        limits.append("dead-time loss is left out: no reverse-conduction data for this device")
    sw = device.switch
    if sw.kind is ChipKind.mosfet and (sw.e_on is None or sw.e_off is None) and not sw.charge.q_oss:
        limits.append("output-capacitance loss is left out: the datasheet gives no output charge")
    if device.diode is not None and device.diode.e_rr is None:
        limits.append("diode recovery loss is left out: the datasheet gives no usable recovery energy")
    return limits


def _legs_together(stage_positions: int, package_positions: int) -> int:
    """Legs in the fullest package of the stage.

    A package holds whole legs. The stage's legs go into as few packages as will
    hold them, spread as evenly as whole legs allow: three legs on two-leg
    modules means one module carries two.
    """
    legs = math.ceil(stage_positions / 2)
    per_package = max(package_positions // 2, 1)
    packages = math.ceil(legs / per_package)
    return math.ceil(legs / packages)


def _package_share(stage_positions: int, package_positions: int) -> float:
    """Share of the stage's loss dissipated in its busiest package, when every leg loses alike."""
    return _legs_together(stage_positions, package_positions) * 2 / stage_positions


def _package_losses(roles: list[Role], each: list[float], together: int) -> list[float]:
    """Loss in the package each role sits in, W, from the loss of one position of each role.

    Legs that do different work lose differently: in an H-bridge the leg that chops runs
    hotter than the leg that holds. A role's package holds its own leg and, where a
    package holds several, the hottest of the others, which is the arrangement that
    heats it most.
    """
    named: dict[str, float] = {}
    plain = 0.0
    for role, loss in zip(roles, each):
        if role.leg is None:
            plain += role.count * loss
        else:
            named[role.leg] = named.get(role.leg, 0.0) + role.count * loss
    plain_legs = math.ceil(sum(r.count for r in roles if r.leg is None) / 2)
    legs = list(named.items()) + [(None, plain / max(plain_legs, 1))] * plain_legs
    out = []
    for role in roles:
        own = next(k for k, (name, _) in enumerate(legs) if name == role.leg)
        others = sorted((loss for k, (_, loss) in enumerate(legs) if k != own), reverse=True)
        out.append(legs[own][1] + sum(others[: together - 1]))
    return out


def hot_share(device: Device, parallel: int) -> float:
    """The share of a position's current carried by the hardest-worked of the devices in
    parallel there: equal shares, unless the datasheet says how far parts may differ."""
    n = max(int(parallel), 1)
    rho = device.switch.conduction.spread
    return rho / (rho + n - 1) if n > 1 and rho and rho > 1 else 1.0 / n


def _one(op: OperatingPoint) -> OperatingPoint:
    from dataclasses import replace

    return replace(op, parallel=1)


def solve_roles(
    device: Device,
    roles: list[Role],
    op: OperatingPoint,
    *,
    period: float,
    p_out: float,
    extra_notes: list[str] | None = None,
    tolerance: float = 0.01,
    max_iterations: int = 200,
    variant: str = "typical",
    stalled: bool = False,
    spread: bool = True,
) -> Result:
    """Losses and junction temperatures of a power stage described by its roles.

    op supplies the conditions every role shares: DC voltage, switching
    frequency, sink temperature, dead time and gate drive. period is the time
    the role waveforms span, in s. stalled says the output is not turning: the period then
    stands for the rotor positions the stage may be held at, not for time.
    """
    # Devices in parallel at a position share its current. Each is solved carrying its
    # share, as if sharing were equal; the stage's loss is that of all of them.
    n = max(int(op.parallel), 1)
    given = roles
    share = 1.0 / n
    if n > 1:
        from dataclasses import replace as _replace

        # Parts differ. The worst case for one device is to be the typical one among parts
        # at the datasheet's maximum: it has the lowest drop and takes the most current, in
        # proportion to how much lower. Without a maximum to go by, sharing is taken as equal.
        share = hot_share(device, n)

        def carrying(part: float) -> list[Role]:
            return [
                _replace(
                    r, current=r.current * part,
                    current_on=None if r.current_on is None else r.current_on * part,
                    current_off=None if r.current_off is None else r.current_off * part,
                )
                for r in given
            ]

        roles = carrying(share)
    stage_positions = sum(r.count for r in roles)
    together = _legs_together(stage_positions, device.package.topology.positions)
    alone = device.package.topology.positions == 1
    tj = [(op.t_sink, op.t_sink) for _ in roles]
    converged = False
    iterations = 0
    runaway_limit = device.ratings.tj_max + 500.0

    def evaluate(tj_now):
        losses = [_position_losses(device, r, op, *t) for r, t in zip(roles, tj_now)]
        total = sum(r.count * (sw.total + d.total) for r, (sw, d, _, _) in zip(roles, losses))
        # Loss dissipated in the package each role sits in. A switch in a package of its own
        # that is held at one rotor position heats its case with what it loses there, and
        # the worst position is the one to design for.
        if alone and stalled:
            packages = [float((p_sw + p_d).max()) for _, _, p_sw, p_d in losses]
        elif alone:
            packages = [sw.total + d.total for sw, d, _, _ in losses]
        else:
            packages = _package_losses(roles, [sw.total + d.total for sw, d, _, _ in losses], together)
        return losses, total, packages

    for iterations in range(1, max_iterations + 1):
        losses, total, packages = evaluate(tj)
        new = []
        for (sw, d, _, _), package in zip(losses, packages):
            t_case = op.t_sink + _case_sink(device, variant) * package
            t_sw = t_case + steady_state_rise(device.switch.thermal, sw.total)
            t_sw += _neighbour_rise(device, sw.total, package, variant)
            if device.diode is None:
                t_d = t_sw
            else:
                t_d = t_case + steady_state_rise(device.diode.thermal, d.total)
                t_d += _neighbour_rise(device, d.total, package, variant)
            new.append((t_sw, t_d))
        if max(max(t) for t in new) > runaway_limit:
            raise ThermalRunaway(
                f"junction temperature passed {runaway_limit:.0f} °C without settling"
            )
        step = max(abs(a - b) for n, o in zip(new, tj) for a, b in zip(n, o))
        tj = new
        if step < tolerance:
            converged = True
            break

    losses, total, packages = evaluate(tj)
    role_results = []
    bases = []
    for role, (sw, d, p_sw, p_d), package, (t_sw, t_d) in zip(roles, losses, packages, tj):
        t_case = op.t_sink + _case_sink(device, variant) * package
        peak_sw, basis = _peak(device, device.switch, p_sw, period, t_case, variant)
        peak_sw += _neighbour_rise(device, sw.total, package, variant)
        bases.append(basis)
        if device.diode is None:
            peak_d = peak_sw
        else:
            peak_d, basis_d = _peak(device, device.diode, p_d, period, t_case, variant)
            peak_d += _neighbour_rise(device, d.total, package, variant)
            bases.append(basis_d)
        role_results.append(
            RoleResult(
                name=role.name, count=role.count, switch=sw, diode=d, tj_switch=t_sw,
                tj_diode=t_d, tj_switch_peak=peak_sw, tj_diode_peak=peak_d, t_case=t_case,
                p_switch=p_sw, p_diode=p_d,
            )
        )
    peak_basis = PeakBasis.assumed if PeakBasis.assumed in bases else PeakBasis.transient
    worst = max(role_results, key=lambda r: r.hottest)
    assumptions = _assumptions(device, peak_basis)
    tj_range = None
    # The range across the thermal assumptions takes two more solves. A search that only
    # needs the typical value asks for it to be left out.
    if assumptions and variant == "typical" and spread:
        ends = []
        for other in ("low", "high"):
            try:
                alt = solve_roles(  # the roles here already carry one device's share
                    device, roles, _one(op), period=period, p_out=p_out, tolerance=tolerance,
                    max_iterations=max_iterations, variant=other, stalled=stalled,
                )
                ends.append(max(alt.tj_switch_peak, alt.tj_diode_peak))
            except ThermalRunaway:
                ends.append(float("inf"))
        tj_range = (min(ends + [worst.hottest]), max(ends + [worst.hottest]))
    i_pk = float(max(r.current.max() for r in roles))
    notes = list(extra_notes or []) + _envelope_notes(
        device, op, i_pk, worst.tj_switch, worst.tj_diode
    )
    if not converged:
        notes.append(f"temperature iteration did not settle in {max_iterations} steps")
    stage_loss = total * n
    if n > 1 and share > 1.0 / n + 1e-9:
        # The temperatures above are the hardest-worked device's. The others carry what is
        # left between them, and the stage loses the sum.
        rest = solve_roles(
            device, carrying((1 - share) / (n - 1)), _one(op), period=period, p_out=p_out,
            tolerance=tolerance, max_iterations=max_iterations, variant=variant, stalled=stalled, spread=False,
        )
        stage_loss = total + (n - 1) * rest.p_inverter
        notes.append(
            f"{n} devices in parallel at each position: the temperatures are those of the one that "
            f"carries most, {share:.0%} of the current, as the datasheet's spread between parts allows "
            f"(maximum {device.switch.conduction.spread:.2f} times typical)"
        )
    elif n > 1:
        notes.append(
            f"{n} devices in parallel at each position, taken to share the current equally: the "
            "datasheet gives no maximum to say how unevenly they might; leave margin"
        )
    return Result(
        switch=worst.switch,
        diode=worst.diode,
        tj_switch=worst.tj_switch,
        tj_diode=worst.tj_diode,
        tj_switch_peak=worst.tj_switch_peak,
        tj_diode_peak=worst.tj_diode_peak,
        peak_basis=peak_basis,
        t_case=worst.t_case,
        p_inverter=stage_loss,
        p_out=p_out,
        converged=converged,
        iterations=iterations,
        validity=_validity(device, notes),
        notes=notes,
        limits=_model_limits(device, peak_basis),
        rating_warnings=_rating_warnings(device, op, i_pk),
        roles=role_results,
        assumptions=assumptions,
        tj_peak_range=tj_range,
    )


def solve(device: Device, op: OperatingPoint, **kwargs) -> Result:
    """Losses and junction temperatures of a three-phase inverter at one operating point."""
    wave = waveform(op.i_rms, op.modulation_index, op.power_factor, op.n_steps, op.pwm)
    notes = []
    if op.modulation_index > op.pwm.max_modulation_index + 1e-9:
        notes.append(
            f"modulation index {op.modulation_index:g} is beyond the linear range of "
            f"{op.pwm.value} PWM ({op.pwm.max_modulation_index:.3g})"
        )
    # Beyond the linear range the stage cannot deliver more voltage, so the power stops there.
    reachable = min(op.modulation_index, op.pwm.max_modulation_index)
    v_phase_rms = reachable * op.v_dc / (2 * np.sqrt(2))
    return solve_roles(
        device,
        phase_leg_roles(wave, INVERTER_POSITIONS, op.pwm),
        op,
        period=1.0 / max(abs(op.f_out), SLOWEST_OUTPUT),
        p_out=float(3 * v_phase_rms * op.i_rms * np.clip(op.power_factor, -1.0, 1.0)),
        extra_notes=notes,
        stalled=abs(op.f_out) < SLOWEST_OUTPUT,
        **kwargs,
    )
