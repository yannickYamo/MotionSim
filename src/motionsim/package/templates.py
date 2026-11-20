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

from motionsim.package.column import Column, Layer, sized, trimmed
from motionsim.package.kept import kept
from motionsim.package.materials import IGBT_DENSITY, Die
from motionsim.package.materials import SILICON as SILICON_DIE
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

# Rated current per unit of switch chip area: the technology's usual figure (see
# materials.current_density; that of a silicon IGBT where none is given) times these. A
# denser chip is smaller and heats more, so the "high" case has the highest density.
DENSITY_SPREAD = {"low": 0.75, "typical": 1.0, "high": 1.375}
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


def _sides(i_rated: float, variant: str, density: float | None = None) -> tuple[float, float]:
    switch = i_rated / ((density or IGBT_DENSITY) * DENSITY_SPREAD[variant])
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


def _six_pack(
    i_rated: float, variant: str, interface: str, *, substrate: bool, density: float | None = None
) -> PackageModel:
    """Three-phase bridge in one moulded package.

    The three high-side switches and diodes share one copper area (the positive
    rail); each low-side switch and diode pair sits on its own phase area.
    """
    sw, d = _sides(i_rated, variant, density)
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
    # Surface-mount outlines cooled through their pad. The pad is taken from the published
    # outline drawings, rounded: a maker's own drawing differs by a few tenths of a millimetre.
    "TO-252": (5.2e-3, 5.5e-3, 0.5e-3),
    "TOLL": (9.7e-3, 8.0e-3, 0.5e-3),
}


def _discrete(
    outline: str, i_rated: float, variant: str, interface: str, *, diode: bool, density: float | None = None
) -> PackageModel:
    """One switch, with or without a diode beside it, on the package's copper tab."""
    width, height, thickness = TABS[outline]
    sw, d = _sides(i_rated, variant, density)
    # A chip is no larger than the tab it sits on, whatever its rating would ask for.
    sw, d = min(sw, width, height), min(d, width, height)
    if diode:
        # One above the other along the tab, a millimetre apart. Where the two with their
        # gap are longer than the tab, both are made smaller by the same share until they fit.
        gap = 1.0e-3
        fit = min(1.0, (height - gap) / (sw + d))
        sw, d = sw * fit, d * fit
        low = max((height - (sw + gap + d)) / 2, 0.0)
        chips: tuple[ChipSite, ...] = (
            ChipSite("switch", width / 2, low + sw / 2, sw, sw),
            ChipSite("diode", width / 2, low + sw + gap + d / 2, d, d),
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


TEMPLATES = ("leadframe-module", "substrate-module", *TABS)


def build(
    template: str,
    i_rated: float,
    variant: str = "typical",
    interface: str = "grease",
    *,
    diode: bool = True,
    density: float | None = None,
) -> PackageModel:
    """density is the rated current over a unit of chip area usual for the technology, A/m2;
    left out, a silicon IGBT's."""
    if template == "leadframe-module":
        return _six_pack(i_rated, variant, interface, substrate=False, density=density)
    if template == "substrate-module":
        return _six_pack(i_rated, variant, interface, substrate=True, density=density)
    if template in TABS:
        return _discrete(template, i_rated, variant, interface, diode=diode, density=density)
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


def _summary_back(v: list) -> Summary:
    switch, diode, coupling, interface = v
    return Summary(float(switch), None if diode is None else float(diode), float(coupling), float(interface))


def _stages_plain(stages: tuple[tuple[float, float], ...]) -> list:
    return [[float(r), float(tau)] for r, tau in stages]


def _stages_back(v: list) -> tuple[tuple[float, float], ...]:
    return tuple((float(r), float(tau)) for r, tau in v)


@lru_cache(maxsize=256)
@kept(
    "summary",
    lambda s: [s.self_switch, s.self_diode, s.coupling, s.interface],
    _summary_back,
)
def summary(
    template: str,
    i_rated: float,
    variant: str = "typical",
    interface: str = "grease",
    diode: bool = True,
    density: float | None = None,
) -> Summary:
    """Cached summarise(build(...)): the calculation takes a noticeable fraction of a second."""
    return summarise(build(template, i_rated, variant, interface, diode=diode, density=density))


ATTACH = Layer(50.0, 1.7e6, 50e-6, slices=3)  # solder under the die
CERAMIC = Layer(ALUMINA, 3.0e6, 0.38e-3, spreads=True, slices=6)
SPREADING_ANGLE = 45.0  # degrees: the usual figure for heat widening in copper under a die


def _column_layers(template: str, die: Die) -> tuple[tuple[Layer, ...], float, float]:
    """The layers under a die where heat goes straight down to the case: a discrete package's
    tab, or a ceramic substrate with its copper. With them, how wide the copper is, and how
    long heat takes to cross it sideways, s."""
    top = (Layer(die.k, die.c, die.thickness, slices=12), ATTACH)
    if template in TABS:
        width, height, thickness = TABS[template]
        across = max(width, height)
        copper = Layer(COPPER, Stack.c_plate, thickness, spreads=True, slices=10)
        return (*top, copper), min(width, height), _crossing(across / 2, COPPER, Stack.c_plate)
    copper = Layer(COPPER, Stack.c_plate, 0.3e-3, spreads=True, slices=6)
    reach = float(np.sqrt(COPPER * 0.3e-3 * 0.38e-3 / ALUMINA))  # how far heat spreads on the substrate
    return (*top, copper, CERAMIC, copper), float("inf"), _crossing(reach, COPPER, Stack.c_plate)


def _crossing(length: float, k: float, c: float) -> float:
    """The slowest time constant of heat crossing a length with one end held: 4·L²/(π²·α)."""
    return 4 * length**2 * c / (np.pi**2 * k)


def has_column(template: str) -> bool:
    """Whether heat in this package goes straight down under the die. In a moulded leadframe
    module it does not: the leadframe spreads it sideways, far beyond its own thickness,
    before it crosses the moulding compound, and the plate equation describes that."""
    return template in TABS or template == "substrate-module"


@lru_cache(maxsize=512)
@kept("column", _stages_plain, _stages_back)
def column_response(
    template: str,
    rth: float,
    variant: str = "typical",
    die: Die = SILICON_DIE,
    area: float | None = None,
) -> tuple[tuple[float, float], ...]:
    """Shape of a chip's junction-to-case step response from one-dimensional conduction
    through the die, the die attach and the copper under it (see column.py), for a chip
    whose datasheet gives the resistance rth and no curve.

    Returns stages as (share of rth, time constant in s). The die is sized so that the
    column's own resistance is rth: the stages then add up to the datasheet's figure
    exactly, and their time constants follow from the geometry.

    That is the fast end of what a real package does. A published curve of a discrete part
    is slower between 0.1 and 100 ms, because part of a datasheet's figure is heat spreading
    along the tab to a case that is not at one temperature. The "low" variant stands for
    that: the die is as large as its current rating allows (area, m2), and what the column
    under it does not explain of rth is one more stage with the time heat takes to cross
    the copper sideways. Where the column under that die already explains rth, low is the
    typical shape.
    """
    layers, widest, crossing = _column_layers(template, die)
    if variant == "low" and area is not None:
        large = Column(min(float(np.sqrt(area)), widest), layers, SPREADING_ANGLE, widest)
        if large.resistance < rth:
            r, tau = large.stages()
            left = rth - large.resistance
            return trimmed(np.append(r, left), np.append(tau, crossing))
    return trimmed(*sized(rth, layers, SPREADING_ANGLE, widest).stages())


@lru_cache(maxsize=256)
@kept("response", _stages_plain, _stages_back)
def response_shape(
    template: str,
    i_rated: float,
    variant: str = "typical",
    interface: str = "grease",
    chip: str = "switch",
    diode: bool = True,
    density: float | None = None,
) -> tuple[tuple[float, float], ...]:
    """Shape of a chip's thermal step response in a generic moulded leadframe module,
    junction to the package's own face.

    Returns stages as (share of the steady resistance, time constant in s),
    fitted to the response computed from the package's copper and die heat
    capacities. Applied to a datasheet's thermal resistance when it gives no
    transient curve. For a package where heat goes straight down under the die
    see column_response.
    """
    from motionsim.fit.foster import fit_foster

    model = build(template, i_rated, variant, interface, diode=diode, density=density)
    plate = model.plates[0]
    index = next(k for k, c in enumerate(plate.chips) if chip in c.name)
    times = np.geomspace(2e-5, 20.0, 36)
    # Junction to the package's own face: the layer under the package belongs to the
    # mounting and has its own place in the result.
    z = step_response(plate, model.case or model.stack, index, times)
    fit = fit_foster(times, z, max_order=3, target=0.05)
    total = sum(fit.r)
    return tuple((r / total, tau) for r, tau in zip(fit.r, fit.tau, strict=True))


def chip_area(i_rated: float, variant: str, chip: str = "switch", density: float | None = None) -> float:
    """Area of a chip rated for this current, m2."""
    switch, diode_side = _sides(i_rated, variant, density)
    return diode_side**2 if chip == "diode" else switch**2
