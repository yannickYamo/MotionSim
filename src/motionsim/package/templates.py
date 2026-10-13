"""Generic package constructions, described well enough to compute how their chips heat each other.

Each template is a typical construction of its kind, not any vendor's
product: outline dimensions are from the public package standards, layer
thicknesses and conductivities are handbook values, and chip size follows
from the current rating through a current density. Every one of those is a
parameter with a low, typical and high value, because real packages differ
and none of this is on a datasheet.

What comes out is a thermal resistance matrix from each junction to the
heatsink surface, by the method in `plate.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from motionsim.package.plate import ChipSite, Plate, Stack, step_response, thermal_matrix

VARIANTS = ("low", "typical", "high")  # low: least heating, high: most

COPPER = 390.0  # W/(m·K)
LEADFRAME = 300.0  # copper alloy
ALUMINA = 24.0
SILICON = 100.0

# Thermal interface between package and heatsink: (conductivity, thickness).
INTERFACE = {
    "grease": {"low": (2.0, 40e-6), "typical": (1.0, 50e-6), "high": (0.8, 80e-6)},
    "pad": {"low": (3.0, 150e-6), "typical": (1.5, 200e-6), "high": (1.0, 250e-6)},
}

# Under a moulded module the layer is thicker than under a discrete package's tab: the
# body is held by a screw at each end and its face is not flat, and module makers'
# mounting guidance asks for about 100 µm of grease.
MOULDED_INTERFACE = {
    "grease": {"low": (2.0, 50e-6), "typical": (1.0, 100e-6), "high": (0.8, 150e-6)},
    "pad": INTERFACE["pad"],
}

# Rated current per unit of switch chip area, A/m2. A denser chip is smaller
# and heats more, so the "high" case has the highest density.
CURRENT_DENSITY = {"low": 1.2e6, "typical": 1.6e6, "high": 2.2e6}
DIODE_AREA_SHARE = 0.5  # antiparallel diode area over switch area


@dataclass(frozen=True)
class PackageModel:
    """A package ready for the plate calculation."""

    name: str
    plates: tuple[Plate, ...]
    stack: Stack
    footprint: float  # m2 of package face that carries heat to the heatsink
    interface_resistance: float  # K/W, interface layer alone under that face
    case: Stack | None = None  # the same stack down to the package's own face, no interface layer

    @property
    def chip_names(self) -> list[str]:
        return [c.name for p in self.plates for c in p.chips]

    def matrix(self, cell: float = 0.25e-3, *, to_case: bool = False) -> np.ndarray:
        """Junction-to-heatsink thermal resistance matrix, K/W, or junction to the
        package's own face held at one temperature. Chips on separate plates are taken
        not to heat each other through the package."""
        stack = self.case if to_case and self.case is not None else self.stack
        blocks = [thermal_matrix(p, stack, cell) for p in self.plates]
        n = sum(b.shape[0] for b in blocks)
        out = np.zeros((n, n))
        at = 0
        for b in blocks:
            out[at : at + b.shape[0], at : at + b.shape[0]] = b
            at += b.shape[0]
        return out


def _series(*layers: tuple[float, float]) -> tuple[float, float]:
    """One (conductivity, thickness) equivalent to layers stacked in series."""
    thickness = sum(t for _, t in layers)
    return thickness / sum(t / k for k, t in layers), thickness


def _sides(i_rated: float, variant: str) -> tuple[float, float]:
    switch = i_rated / CURRENT_DENSITY[variant]
    return float(np.sqrt(switch)), float(np.sqrt(DIODE_AREA_SHARE * switch))


def _row(names: list[str], sides: list[float], gap: float, margin: float):
    """Chips in a row with a fixed gap between them; returns the chips and the plate size."""
    chips, x = [], margin
    for name, side in zip(names, sides, strict=True):
        chips.append((name, x + side / 2, side))
        x += side + gap
    width = x - gap + margin
    height = max(sides) + 2 * margin
    return tuple(ChipSite(n, cx, height / 2, s, s) for n, cx, s in chips), width, height


def _six_pack(i_rated: float, variant: str, interface: str, *, substrate: bool) -> PackageModel:
    """Three-phase bridge in one moulded package.

    The three high-side switches and diodes share one copper area (the positive
    rail); each low-side switch and diode pair sits on its own phase area.
    """
    sw, d = _sides(i_rated, variant)
    gap = {"low": 2.5e-3, "typical": 2.0e-3, "high": 1.5e-3}[variant]
    margin = 1.0e-3
    rail, w, h = _row(
        ["HS switch U", "HS diode U", "HS switch V", "HS diode V", "HS switch W", "HS diode W"],
        [sw, d, sw, d, sw, d],
        gap,
        margin,
    )
    plates = [Plate(w, h, rail)]
    for phase in "UVW":
        chips, w2, h2 = _row([f"LS switch {phase}", f"LS diode {phase}"], [sw, d], gap, margin)
        plates.append(Plate(w2, h2, chips))
    copper = sum(p.width * p.height for p in plates)
    if substrate:
        # Copper on a ceramic, soldered or pressed to the package face. The copper under
        # the ceramic spreads the heat over a face wider than the copper the chips sit on.
        k_if, t_if = INTERFACE[interface][variant]
        inside = _series((ALUMINA, 0.38e-3), (COPPER, 0.3e-3))
        k_plate, t_plate = COPPER, 0.3e-3
        footprint = copper * 1.6
    else:
        # Leadframe with a layer of thermally conductive moulding compound beneath it.
        # Nothing spreads the heat below the leadframe, so it crosses the interface
        # under the copper and nowhere else.
        k_if, t_if = MOULDED_INTERFACE[interface][variant]
        inside = {"low": (2.5, 0.30e-3), "typical": (1.8, 0.35e-3), "high": (1.2, 0.45e-3)}[variant]
        k_plate, t_plate = LEADFRAME, 0.5e-3
        footprint = copper
    k_ins, t_ins = _series(inside, (k_if, t_if))
    return PackageModel(
        name="ceramic-substrate module" if substrate else "moulded leadframe module",
        plates=tuple(plates),
        stack=Stack(k_plate, t_plate, k_ins, t_ins, k_die=SILICON),
        footprint=footprint,
        interface_resistance=t_if / (k_if * footprint),
        case=Stack(k_plate, t_plate, *inside, k_die=SILICON),
    )


# Exposed copper tab of the standard discrete outlines: (width, height, thickness), m.
TABS = {
    "TO-220": (10.0e-3, 12.5e-3, 1.27e-3),
    "TO-247": (15.9e-3, 17.0e-3, 2.0e-3),
    "TO-263": (10.0e-3, 9.0e-3, 1.27e-3),
}


def _discrete(outline: str, i_rated: float, variant: str, interface: str, *, diode: bool) -> PackageModel:
    """One switch, with or without a diode beside it, on the package's copper tab."""
    width, height, thickness = TABS[outline]
    sw, d = _sides(i_rated, variant)
    # A chip is no larger than the tab it sits on, whatever its rating would ask for.
    sw, d = min(sw, width, height), min(d, width, height)
    if diode:
        chips = (
            ChipSite("switch", width / 2, height * 0.36, sw, sw),
            ChipSite("diode", width / 2, min(height * 0.36 + sw / 2 + 1.0e-3 + d / 2, height - d / 2), d, d),
        )
    else:
        chips = (ChipSite("switch", width / 2, height / 2, sw, sw),)
    k_if, t_if = INTERFACE[interface][variant]
    return PackageModel(
        name=outline,
        plates=(Plate(width, height, chips),),
        stack=Stack(COPPER, thickness, k_if, t_if, k_die=SILICON),
        footprint=width * height,
        interface_resistance=t_if / (k_if * width * height),
    )


TEMPLATES = ("leadframe-module", "substrate-module", "TO-220", "TO-247", "TO-263")


def build(
    template: str,
    i_rated: float,
    variant: str = "typical",
    interface: str = "grease",
    *,
    diode: bool = True,
) -> PackageModel:
    if template == "leadframe-module":
        return _six_pack(i_rated, variant, interface, substrate=False)
    if template == "substrate-module":
        return _six_pack(i_rated, variant, interface, substrate=True)
    if template in TABS:
        return _discrete(template, i_rated, variant, interface, diode=diode)
    raise ValueError(f"unknown package template {template!r}; choose from {', '.join(TEMPLATES)}")


@dataclass(frozen=True)
class Summary:
    """A package matrix reduced to a few numbers: what the loss engine uses, and each chip's own
    resistance for the `motionsim package` printout."""

    self_switch: float  # junction to heatsink, switch alone, K/W
    self_diode: float | None
    # Mean rise of a chip per watt in another chip, K/W, over the package's own face: what
    # the package does inside itself, whatever it is mounted on.
    coupling: float
    interface: float  # K/W, case to heatsink: the interface layer under the package


def summarise(model: PackageModel) -> Summary:
    m = model.matrix()
    inside = model.matrix(to_case=True)
    names = model.chip_names
    switches = [i for i, n in enumerate(names) if "switch" in n]
    diodes = [i for i, n in enumerate(names) if "diode" in n]
    n = len(names)
    off = (inside.sum() - np.trace(inside)) / (n * (n - 1)) if n > 1 else 0.0
    return Summary(
        self_switch=float(np.mean([m[i, i] for i in switches])),
        self_diode=float(np.mean([m[i, i] for i in diodes])) if diodes else None,
        coupling=float(off),
        interface=model.interface_resistance,
    )


def shared_time(template: str, i_rated: float, interface: str = "grease") -> float:
    """Seconds the copper under the chips takes to follow a change of loss: the plate
    equation's own time constant, the copper's heat capacity over a unit of area charged
    through the layers beneath it."""
    stack = build(template, i_rated, "typical", interface).stack
    return stack.c_plate * stack.t_plate * stack.t_insulation / stack.k_insulation


@lru_cache(maxsize=256)
def summary(
    template: str,
    i_rated: float,
    variant: str = "typical",
    interface: str = "grease",
    diode: bool = True,
) -> Summary:
    """Cached summarise(build(...)): the calculation takes a noticeable fraction of a second."""
    return summarise(build(template, i_rated, variant, interface, diode=diode))


@lru_cache(maxsize=256)
def response_shape(
    template: str,
    i_rated: float,
    variant: str = "typical",
    interface: str = "grease",
    chip: str = "switch",
    diode: bool = True,
) -> tuple[tuple[float, float], ...]:
    """Shape of a chip's thermal step response in a generic package of this kind.

    Returns stages as (share of the steady resistance, time constant in s),
    fitted to the response computed from the package's copper and die heat
    capacities. Applied to a datasheet's thermal resistance when it gives no
    transient curve.
    """
    from motionsim.fit.foster import fit_foster

    model = build(template, i_rated, variant, interface, diode=diode)
    plate = model.plates[0]
    index = next(k for k, c in enumerate(plate.chips) if chip in c.name)
    times = np.geomspace(2e-5, 20.0, 36)
    z = step_response(plate, model.stack, index, times)
    fit = fit_foster(times, z, max_order=3, target=0.05)
    total = sum(fit.r)
    return tuple((r / total, tau) for r, tau in zip(fit.r, fit.tau, strict=True))
