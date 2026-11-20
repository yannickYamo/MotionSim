"""The ways heat leaves a chip: through its own junction-to-case network, into the other
chips of its package, and through the layer under the package to the heatsink. Each is the
device's own figure where it gives one, and one computed for a generic package where not."""

from __future__ import annotations

from motionsim.device.schema import Chip, ChipKind, Device, FosterNetwork
from motionsim.engine import assumed
from motionsim.engine.point import OperatingPoint, PeakBasis
from motionsim.package.materials import current_density


def _mutual(device: Device, variant: str) -> float:
    """Coupling between chips: the user's value, or one computed for a generic package."""
    package = device.package
    if package.rth_mutual is not None:
        return package.rth_mutual
    if package.topology.positions == 1:
        return 0.0
    # Over the package's own face. The layer between that face and the heatsink, which
    # every chip's heat crosses, is the case-to-sink resistance and is kept apart: it
    # belongs to how the package is mounted, and changing it leaves this where it is.
    return assumed.module_coupling(package.construction, device.ratings.i_nominal, variant, density=_density(device))


def _density(device: Device) -> float:
    """Rated current over a unit of chip area usual for this technology, A/m2."""
    return current_density(device.technology, device.ratings.v_max)


def case_sink(device: Device, variant: str, op: OperatingPoint | None = None) -> float:
    """Case-to-heatsink resistance of one package: the figure given for this build, else
    the device's own, else computed for the layer under its package."""
    package = device.package
    if op is not None and op.rth_case_sink is not None:
        return op.rth_case_sink
    layer = (op.interface if op is not None else None) or package.interface
    # A device's own figure is for the layer its datasheet had in mind. Named another for
    # this build, the layer is computed.
    if package.rth_case_sink is not None and layer == package.interface:
        return package.rth_case_sink
    if package.outline is not None:
        return assumed.interface_resistance(package.outline, device.ratings.i_nominal, variant, layer)
    if package.topology.positions > 1:
        # A module's datasheet gives junction to case. The layer between case and heatsink
        # is still there, and a chip's own heat crosses it like its neighbours' does.
        return assumed.module_interface(
            package.construction, device.ratings.i_nominal, variant, layer, density=_density(device)
        )
    return package.rth_case_sink or 0.0


def shared_time(device: Device, op: OperatingPoint, variant: str = "typical") -> float:
    """Seconds in which what a chip shares with its package follows the package's loss.

    A package of its own: the heat capacity of its copper tab, charged through whatever
    lies under it, which is the layer to the heatsink or the path to the air. A module:
    the copper under its chips, charged through the layers beneath. Only the copper's heat
    capacity is counted; the body around it slows a real package further.
    """
    package = device.package
    if package.topology.positions > 1:
        return assumed.shared_time(
            package.construction,
            package.outline,
            package.topology.positions,
            device.ratings.i_nominal,
            op.interface or package.interface,
        )
    under = op.rth_free if op.rth_free is not None else case_sink(device, variant, op)
    return assumed.tab_capacity(package.outline) * under


def thermal_network(device: Device, chip: Chip, variant: str = "typical") -> tuple[FosterNetwork, PeakBasis]:
    """A chip's junction-to-case network with time constants: the device's own, or its
    resistance spread over the response computed for a generic package."""
    network, basis = chip.thermal, PeakBasis.transient
    if network.tau is None:
        package = device.package
        template, _ = assumed.response_template(
            package.construction, package.outline, package.topology.positions, variant
        )
        kind = "diode" if chip.kind is ChipKind.diode else "switch"
        stages = assumed.response(
            template,
            device.ratings.i_nominal,
            variant,
            package.interface,
            kind,
            device.diode is not None,
            rth=chip.thermal.rth,
            technology=device.technology,
            v_rated=device.ratings.v_max,
        )
        network = FosterNetwork(
            r=[share * chip.thermal.rth for share, _ in stages],
            tau=[tau for _, tau in stages],
            source=chip.thermal.source,
        )
        basis = PeakBasis.assumed
    return network, basis
