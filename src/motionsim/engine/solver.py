"""Loss and temperature solver for a motor-drive power stage.

A power stage is described as a set of roles: kinds of switch position, each
with its current and conduction pattern over a period. Losses are averaged
over the period for each role. Junction temperatures feed back into the loss
tables, so the solver iterates until the assumed and computed temperatures
agree.

The work is shared out: position.py has the losses of one switch position, paths.py the
ways heat leaves a chip, settle.py the search for the temperatures, envelope.py and
doubt.py where the point leaves the data and what that could do, caveats.py what else a
result says of itself. Here they are put together into a result.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from motionsim.device.schema import Device
from motionsim.engine.caveats import _assumptions, _model_limits, _range_lead, _rating_warnings, collect_notes
from motionsim.engine.doubt import _doubt, _outside, _validity
from motionsim.engine.envelope import _envelope_notes
from motionsim.engine.modulation import Role, phase_leg_roles, waveform
from motionsim.engine.notes import Code, Note
from motionsim.engine.paths import case_sink, shared_time, thermal_network
from motionsim.engine.point import (
    BeyondData,
    DiodeLoss,
    OperatingPoint,
    PeakBasis,
    Result,
    RoleResult,
    SwitchLoss,
    ThermalRunaway,
    Validity,
)
from motionsim.engine.position import switching_period
from motionsim.engine.settle import RUNAWAY_MARGIN, _Mounting, package_waves, role_results_at, settle_temperatures

__all__ = [
    "BeyondData",
    "DiodeLoss",
    "OperatingPoint",
    "PeakBasis",
    "Result",
    "RoleResult",
    "SwitchLoss",
    "ThermalRunaway",
    "Validity",
    "case_sink",
    "hot_share",
    "package_waves",
    "share_between_parallel",
    "shared_time",
    "solve",
    "solve_roles",
    "switching_period",
    "thermal_network",
]

INVERTER_POSITIONS = 6


def hot_share(device: Device, parallel: int) -> float:
    """The share of a position's current carried by the hardest-worked of the devices in
    parallel there: equal shares, unless the datasheet says how far parts may differ."""
    n = max(int(parallel), 1)
    rho = device.switch.conduction.spread
    return rho / (rho + n - 1) if n > 1 and rho and rho > 1 else 1.0 / n


def _one(op: OperatingPoint, t_sink: float | None = None) -> OperatingPoint:
    """The conditions for one device of those in parallel. Its heatsink is shared with the
    others, so it is held at the temperature the whole stage's loss brings it to."""
    if t_sink is None or (op.rth_sink is None and op.rth_board is None):
        return replace(op, parallel=1)
    return replace(op, parallel=1, rth_sink=None, rth_board=None, t_sink=t_sink)


def _carrying(roles: list[Role], part: float) -> list[Role]:
    """The roles with every current brought to one device's part of it."""
    return [
        replace(
            r,
            current=r.current * part,
            current_on=None if r.current_on is None else r.current_on * part,
            current_off=None if r.current_off is None else r.current_off * part,
        )
        for r in roles
    ]


def share_between_parallel(device: Device, roles: list[Role], n: int) -> tuple[list[Role], float]:
    """The roles as the hardest-worked of n devices in parallel carries them, and its share.

    Parts differ. The worst case for one device is to be the typical one among parts at the
    datasheet's maximum: it has the lowest drop and takes the most current, in proportion
    to how much lower. Without a maximum to go by, sharing is taken as equal.
    """
    if n <= 1:
        return roles, 1.0
    share = hot_share(device, n)
    return _carrying(roles, share), share


def _mounted(
    device: Device, roles: list[Role], op: OperatingPoint, period: float, variant: str, stalled: bool
) -> _Mounting:
    """The stage as one device of those in parallel at each position sees it. Devices in
    parallel at a position share its current: each is solved carrying its share, and the
    stage's loss is that of all of them. Under the case is the user's own figure to the air
    where there is no heatsink, else the layer between the case and the heatsink."""
    n = max(int(op.parallel), 1)
    carried, _ = share_between_parallel(device, roles, n)
    under = op.rth_free if op.rth_free is not None else case_sink(device, variant, op)
    return _Mounting(device, carried, op, period, variant, stalled, n, under)


def assumption_range(
    stage: _Mounting,
    held: float,
    worst: RoleResult,
    package: float,
    peak_basis: PeakBasis,
    assumptions: list[str],
    spread: bool,
    **solving,
) -> tuple[tuple[float, float] | None, str | None, list[str]]:
    """The hottest junction across the thermal assumptions, which takes two more solves; which
    assumption lifts the top most; and the assumptions, with a line added where one end
    does not settle. None where nothing is assumed, and where a search that only needs the
    typical value asks for the range to be left out (spread false)."""
    if not (assumptions and stage.variant == "typical" and spread):
        return None, None, assumptions
    device = stage.device
    runaway_limit = device.ratings.tj_max + RUNAWAY_MARGIN
    ends = []
    ran_away = False
    for other in ("low", "high"):
        try:
            alt = solve_roles(  # the roles here already carry one device's share
                device, stage.roles, _one(stage.op, held), variant=other, stalled=stage.stalled, **solving
            )
            ends.append(max(alt.tj_switch_peak, alt.tj_diode_peak))
        except ThermalRunaway:
            # No temperature to report at this end: the range is closed where the search
            # gave up, far above any rating, and the result says why.
            ends.append(runaway_limit)
            ran_away = True
    tj_range = (min(ends + [worst.hottest]), max(ends + [worst.hottest]))
    if ran_away:
        assumptions = assumptions + [
            Note(
                Code.range_runs_away,
                "tj_peak_range",
                "at one end of these assumptions the junction temperature does not settle (thermal "
                f"runaway): the range is closed at {runaway_limit:.0f} °C, where the search stopped",
            )
        ]
    lead = None
    if tj_range[1] > worst.hottest:
        top = float("inf") if ran_away else tj_range[1]
        lead = _range_lead(device, stage.op, worst, package, top, peak_basis)
    return tj_range, lead, assumptions


def rest_of_parallel(
    stage: _Mounting, given: list[Role], held: float, total: float, **solving
) -> tuple[float, Note | None]:
    """The stage's loss with n devices in parallel at each position, and the note that says
    how they were taken to share. The temperatures are the hardest-worked device's; the
    others carry what is left between them, and the stage loses the sum."""
    n, device = stage.n, stage.device
    share = hot_share(device, n)
    if n > 1 and share > 1.0 / n + 1e-9:
        rest = solve_roles(
            device,
            _carrying(given, (1 - share) / (n - 1)),
            _one(stage.op, held),
            variant=stage.variant,
            stalled=stage.stalled,
            spread=False,
            **solving,
        )
        return total + (n - 1) * rest.p_inverter, Note(
            Code.parallel_uneven,
            "parallel",
            f"{n} devices in parallel at each position: the temperatures are those of the one that "
            f"carries most, {share:.0%} of the current, as the datasheet's spread between parts allows "
            f"(maximum {device.switch.conduction.spread:.2f} times typical)",
        )
    if n > 1:
        return total * n, Note(
            Code.parallel_equal,
            "parallel",
            f"{n} devices in parallel at each position, taken to share the current equally: the "
            "datasheet gives no maximum to say how unevenly they might; leave margin",
        )
    return total * n, None


def _hottest_place(worst: RoleResult, stalled: bool) -> dict:
    """The figures a result leads with: those of its hardest-worked role. Held still, the
    rotor stands at one place and each junction holds that place's temperature: a mean over
    places it does not stand at would sit below the case it is reported beside. The result
    gives the hottest place's; each role keeps its mean over the period, which following a
    motion through time builds on."""
    return {
        "switch": worst.switch,
        "diode": worst.diode,
        "tj_switch": worst.tj_switch_peak if stalled else worst.tj_switch,
        "tj_diode": worst.tj_diode_peak if stalled else worst.tj_diode,
        "tj_switch_peak": worst.tj_switch_peak,
        "tj_diode_peak": worst.tj_diode_peak,
        "t_case": worst.t_case,
    }


def solve_roles(
    device: Device,
    roles: list[Role],
    op: OperatingPoint,
    *,
    period: float,
    p_out: float,
    extra_notes: list[str] | None = None,
    extra_outside: list[str] | None = None,  # notes that put the point outside what is characterised
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
    stands for the rotor positions the stage may be held at, not for time, and every
    temperature is the one that position settles at.
    """
    stage = _mounted(device, roles, op, period, variant, stalled)
    solving = {"period": period, "p_out": p_out, "tolerance": tolerance, "max_iterations": max_iterations}
    tj, converged, iterations = settle_temperatures(stage, tolerance, max_iterations)
    role_results, sink, total, packages = role_results_at(stage, tj)
    peak_basis = stage.paths.basis
    worst = max(role_results, key=lambda r: r.hottest)
    held = stage.held(sink, total, packages)
    assumptions = _assumptions(device, peak_basis, in_air=op.rth_free is not None, op=op)
    tj_range, lead, assumptions = assumption_range(
        stage, held, worst, packages[role_results.index(worst)], peak_basis, assumptions, spread, **solving
    )
    i_pk = float(max(r.current.max() for r in stage.roles))
    envelope = _envelope_notes(device, op, i_pk, worst.tj_switch, worst.tj_diode)
    outside = list(extra_outside or []) + _outside(envelope, role_results)
    stage_loss, parallel = rest_of_parallel(stage, roles, held, total, **solving)
    unsettled = None if converged else max_iterations
    return Result(
        **_hottest_place(worst, stalled),
        peak_basis=peak_basis,
        p_inverter=stage_loss,
        p_out=p_out,
        converged=converged,
        iterations=iterations,
        validity=_validity(device, outside),
        notes=collect_notes(device, op, envelope, extra_notes, extra_outside, unsettled, parallel),
        outside=outside,
        limits=_model_limits(device, peak_basis, op),
        rating_warnings=_rating_warnings(device, op, i_pk),
        roles=role_results,
        assumptions=assumptions,
        tj_peak_range=tj_range,
        range_lead=lead,
        t_sink=sink,
        doubt=_doubt(envelope, role_results, op.t_sink),
    )


def solve(device: Device, op: OperatingPoint, **kwargs) -> Result:
    """Losses and junction temperatures of a three-phase inverter at one operating point."""
    wave = waveform(op.i_rms, op.modulation_index, op.power_factor, op.n_steps, op.pwm)
    # The point holds its modulation index inside the scheme's linear range (OperatingPoint).
    v_phase_rms = op.modulation_index * op.v_dc / (2 * np.sqrt(2))
    return solve_roles(
        device,
        phase_leg_roles(wave, INVERTER_POSITIONS, op.pwm),
        op,
        period=1.0 / abs(op.f_out) if op.f_out else float("inf"),
        p_out=float(3 * v_phase_rms * op.i_rms * np.clip(op.power_factor, -1.0, 1.0)),
        stalled=op.f_out == 0,
        **kwargs,
    )
