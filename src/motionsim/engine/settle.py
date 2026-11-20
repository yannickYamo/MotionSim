"""The temperatures of one device of the stage, settled: its losses gathered into the
packages they heat, what each path does to a loss that repeats every period, and the search
that goes round until the losses and the temperatures they give agree."""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cached_property

import numpy as np

from motionsim.device.schema import Device
from motionsim.engine.modulation import Role
from motionsim.engine.paths import _mutual, case_sink, shared_time, thermal_network
from motionsim.engine.point import BeyondData, OperatingPoint, PeakBasis, Result, RoleResult, ThermalRunaway
from motionsim.engine.position import _position_losses
from motionsim.engine.thermal import harmonics, through

RUNAWAY_MARGIN = 500.0  # K above the rating at which the search for a settled temperature gives up


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


def _package_losses(roles: list[Role], each: list[float], together: int) -> list[float]:
    """Loss in the package each role sits in, W, from the loss of one position of each role.

    Legs that do different work lose differently: in an H-bridge the leg that chops runs
    hotter than the leg that holds. A role's package holds its own leg and, where a
    package holds several, the hottest of the others, which is the arrangement that
    heats it most.
    """
    named: dict[str, float] = {}
    plain = 0.0
    for role, loss in zip(roles, each, strict=True):
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


def package_waves(device: Device, roles: list[Role], result: Result, op: OperatingPoint) -> list[dict]:
    """For each role's switch and diode: against position in the period, the rise over the
    heatsink that the rest of its package would settle it at, K. It is the loss of the
    whole package through the layer under it, and of the other chips through the package."""
    own = [_loss_waves(r) for r in result.roles]
    waves = [p_sw + p_d for p_sw, p_d in own]
    if any(role.leg is None for role in roles):
        raise ValueError("the legs of this stage are not told apart, so its packages cannot be followed through time")
    if device.package.topology.positions == 1:
        packages = waves
    else:
        together = _legs_together(sum(r.count for r in roles), device.package.topology.positions)
        legs: dict[str | None, np.ndarray] = {}
        for role, wave in zip(roles, waves, strict=True):
            legs[role.leg] = legs.get(role.leg, 0.0) + role.count * wave
        packages = []
        for role in roles:
            others = sorted((w for leg, w in legs.items() if leg != role.leg), key=lambda w: -float(w.mean()))
            packages.append(legs[role.leg] + sum(others[: together - 1]))
    # With no heatsink the way from the case to the air is slow, and stays at its mean.
    under = 0.0 if op.rth_free is not None else case_sink(device, "typical", op)
    mutual = _mutual(device, "typical")
    out = []
    for (p_sw, p_d), package in zip(own, packages, strict=True):
        chips = {"switch": p_sw, "diode": p_d}
        out.append({name: under * package + mutual * np.maximum(package - p, 0.0) for name, p in chips.items()})
    return out


def _loss_waves(role: RoleResult) -> tuple[np.ndarray, np.ndarray]:
    """The loss of a solved position's switch and diode through the period, W."""
    if role.p_switch is None or role.p_diode is None:
        raise ValueError("this position was not solved through the period")
    return role.p_switch, role.p_diode


@dataclass(frozen=True)
class _Paths:
    """Thermal impedance at each harmonic of the period (see thermal.harmonics): each chip's
    junction to case, and what a chip shares with its package, per K/W of it."""

    switch: np.ndarray
    diode: np.ndarray | None
    shared: np.ndarray
    basis: PeakBasis  # what the junction-to-case paths rest on


@dataclass(frozen=True)
class _Temperatures:
    """One role through the period, °C at every instant."""

    case: np.ndarray
    switch: np.ndarray
    diode: np.ndarray
    # Where the rest of its package would settle each chip, K over what the package sits on.
    shared_switch: np.ndarray | None
    shared_diode: np.ndarray | None


@dataclass(frozen=True)
class _Mounting:
    """What one device of the stage sits on, and how its losses are gathered into packages."""

    device: Device
    roles: list[Role]  # as one device carries them
    op: OperatingPoint
    period: float
    variant: str
    stalled: bool
    n: int  # devices in parallel at each position
    under: float  # K/W under the case: to the air where there is no heatsink, else the layer to the heatsink

    @property
    def alone(self) -> bool:
        return self.device.package.topology.positions == 1

    def losses(self, tj: list[tuple]) -> tuple[list, float, list[float]]:
        """Each role's losses at the temperatures given, the loss of one device at every
        position, and the mean loss dissipated in the package each role sits in."""
        device, roles = self.device, self.roles
        losses = [_position_losses(device, r, self.op, *t) for r, t in zip(roles, tj, strict=True)]
        total = sum(r.count * (sw.total + d.total) for r, (sw, d, _, _) in zip(roles, losses, strict=True))
        if self.alone:
            packages = [sw.total + d.total for sw, d, _, _ in losses]
        else:
            together = _legs_together(sum(r.count for r in roles), device.package.topology.positions)
            packages = _package_losses(roles, [sw.total + d.total for sw, d, _, _ in losses], together)
        return losses, total, packages

    @cached_property
    def paths(self) -> _Paths:
        """What each path the heat takes does to a loss that repeats every period. Held
        still, the period has no end: every path is at its steady value at each position."""
        device = self.device
        samples = self.roles[0].current.size
        period = float("inf") if self.stalled else self.period
        chips = {"switch": device.switch} | ({"diode": device.diode} if device.diode is not None else {})
        own, bases = {}, []
        for name, chip in chips.items():
            network, basis = thermal_network(device, chip, self.variant)
            bases.append(basis)
            if basis is PeakBasis.assumed and self.variant == "high":
                # The most any response can give: the junction follows its loss at once.
                own[name] = harmonics([network.rth], [0.0], samples, float("inf"))
            else:
                own[name] = harmonics(network.r, network.tau, samples, period)
        tau = shared_time(device, self.op, self.variant) if self.alone else 0.0
        return _Paths(
            own["switch"],
            own.get("diode"),
            harmonics([1.0], [tau], samples, period),
            PeakBasis.assumed if PeakBasis.assumed in bases else PeakBasis.transient,
        )

    def temperatures(self, loss: tuple, package: float, sink: float, total: float) -> _Temperatures:
        """A role's case and junction temperatures at every instant of the period, from its
        loss waveforms.

        The junction-to-case path of each chip answers its own loss. A package of its own
        also heats and cools as a whole: its case, through the layer under it, follows the
        package's loss with the time constant of the tab, so that a slow turn of the motor
        takes the case to the loss of each position in turn and a fast one leaves it at the
        mean. A module holds the whole stage, whose loss is even through the period.
        """
        device, paths = self.device, self.paths
        sw, d, p_sw, p_d = loss
        mutual = _mutual(device, self.variant)
        mean_case = self.case_at(sink, package, total)
        shared: dict[str, np.ndarray | None] = {"switch": None, "diode": None}
        if self.alone:
            whole = p_sw + p_d
            # What lies under the case beyond its own layer (a heatsink in air, a board) is
            # slow, and stays where the mean loss puts it.
            base = mean_case - self.under * package
            case = base + through(paths.shared, self.under * whole)
            waves = {name: self.under * whole + mutual * (whole - p) for name, p in (("switch", p_sw), ("diode", p_d))}
            rest = {name: base + through(paths.shared, wave) for name, wave in waves.items()}
            shared = dict(waves)
        else:
            case = np.full_like(p_sw, mean_case)
            rest = {name: case + mutual * max(package - own.total, 0.0) for name, own in (("switch", sw), ("diode", d))}
        t_sw = rest["switch"] + through(paths.switch, p_sw)
        t_d = t_sw if paths.diode is None else rest["diode"] + through(paths.diode, p_d)
        return _Temperatures(case, t_sw, t_d, shared["switch"], None if paths.diode is None else shared["diode"])

    def sink_at(self, total: float) -> float:
        """A heatsink in air warms with all the stage loses. The devices in parallel are
        counted as losing what the hardest-worked one does, which errs on the warm side."""
        op = self.op
        return op.t_sink + (op.rth_sink * total * self.n if op.rth_sink is not None else 0.0)

    def case_at(self, sink: float, package: float, total: float) -> float:
        op = self.op
        if op.rth_board is None:
            return sink + self.under * package
        # On a shared board: its own loss through its own path, plus what the others put
        # into the board; and never cooler than the board as a whole.
        everything = total * self.n
        return sink + max(
            self.under * package + op.rth_board * max(everything - package, 0.0), op.rth_board * everything
        )

    def held(self, sink: float, total: float, packages: list[float]) -> float:
        """For a solve of one device alone: what it sits on is already settled, by all the
        stage loses. On a shared board that is the air plus the neighbours' share, and
        never cooler in all than the board as a whole."""
        op = self.op
        if op.rth_board is None:
            return sink
        everything, own = total * self.n, max(packages)
        return sink + max(op.rth_board * max(everything - own, 0.0), op.rth_board * everything - self.under * own)


def settle_temperatures(stage: _Mounting, tolerance: float, max_iterations: int) -> tuple[list[tuple], bool, int]:
    """Each role's switch and diode temperature at every instant of the period, found by
    going round until the losses and the temperatures they give agree: a chip's loss at an
    instant is read at its own temperature at that instant. Returns them, whether they
    settled, and the rounds taken.

    A search that passes the rating by RUNAWAY_MARGIN is not stopped there: it is followed
    to see whether the temperatures settle after all (BeyondData) or keep climbing
    (ThermalRunaway). Neither has a figure worth reporting.
    """
    device = stage.device
    start = stage.op.t_sink
    tj: list[tuple] = [(start, start) for _ in stage.roles]
    runaway_limit = device.ratings.tj_max + RUNAWAY_MARGIN
    iterations = 0
    for iterations in range(1, max_iterations + 1):
        losses, total, packages = stage.losses(tj)
        sink = stage.sink_at(total)
        new = []
        for loss, package in zip(losses, packages, strict=True):
            t = stage.temperatures(loss, package, sink, total)
            new.append((t.switch, t.diode))
        hottest = max(float(np.max(t)) for pair in new for t in pair)
        if hottest > runaway_limit + 10 * RUNAWAY_MARGIN or not np.isfinite(hottest):
            raise ThermalRunaway(f"junction temperature passed {runaway_limit:.0f} °C without settling")
        step = max(
            float(np.max(np.abs(a - b))) for n, o in zip(new, tj, strict=True) for a, b in zip(n, o, strict=True)
        )
        tj = new
        if step < tolerance:
            if hottest > runaway_limit:
                raise BeyondData(
                    f"the junction would settle near {hottest:.0f} °C, above {runaway_limit:.0f} °C and far "
                    "beyond anything the device's data describes"
                )
            return tj, True, iterations
    if max(float(np.max(t)) for pair in tj for t in pair) > runaway_limit:
        raise ThermalRunaway(f"junction temperature passed {runaway_limit:.0f} °C without settling")
    return tj, False, iterations


def role_results_at(stage: _Mounting, tj: list[tuple]) -> tuple[list[RoleResult], float, float, list[float]]:
    """Every role's losses and temperatures at the settled temperatures: the mean over the
    period and the highest within it. Also the temperature of what the packages sit on, the
    loss of one device at every position, and the loss that heats each role's package most."""
    losses, total, packages = stage.losses(tj)
    sink = stage.sink_at(total)
    role_results = []
    hardest = []
    for role, loss, package in zip(stage.roles, losses, packages, strict=True):
        sw, d, p_sw, p_d = loss
        t = stage.temperatures(loss, package, sink, total)
        role_results.append(
            RoleResult(
                name=role.name,
                count=role.count,
                switch=sw,
                diode=d,
                tj_switch=float(t.switch.mean()),
                tj_diode=float(t.diode.mean()),
                tj_switch_peak=float(t.switch.max()),
                tj_diode_peak=float(t.diode.max()),
                # The highest the case reaches: turning fast that is its mean, held still it
                # is the case at the position that loads it most.
                t_case=float(t.case.max()),
                p_switch=p_sw,
                p_diode=p_d,
                shared_switch=t.shared_switch,
                shared_diode=t.shared_diode,
            )
        )
        # The loss the layer under the package carries when the case is at its highest.
        swing = float(t.case.max() - t.case.mean())
        hardest.append(package + (swing / stage.under if stage.under > 0 else 0.0))
    return role_results, sink, total, hardest
