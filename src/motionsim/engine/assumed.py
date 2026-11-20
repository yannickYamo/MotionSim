"""Values used when a datasheet does not give what the thermal calculation needs.

Each comes as low, typical and high, so a result can show a range instead of
a single number it has no right to.

- Heating between chips, over the package's own face, and the layer between
  that face and the heatsink are computed from first principles for a
  generic package of the stated construction
  (`motionsim.package`): handbook material properties, standard outlines, and
  a chip size that follows from the current rating.
- The shape of the transient thermal response, used only when a datasheet
  gives a thermal resistance and no transient curve, is computed from the
  layers between the junction and the case: one-dimensional conduction under
  the die where heat goes straight down, the plate equation with its heat
  capacity where a leadframe spreads it first.
"""

from __future__ import annotations

from motionsim.package import templates
from motionsim.package.materials import current_density, die_of
from motionsim.package.templates import response_shape, summary

VARIANTS = ("low", "typical", "high")

_TEMPLATE = {"leadframe": "leadframe-module", "substrate": "substrate-module"}


def module_coupling(
    construction: str, i_rated: float, variant: str, interface: str = "grease", density: float | None = None
) -> float:
    """Junction rise per watt dissipated in each other chip of a multi-chip module, K/W,
    over the package's own face. It belongs to the package: what the package is mounted
    on does not move it. density is the rated current over a unit of chip area for the
    technology, A/m2; left out, a silicon IGBT's."""
    if construction in _TEMPLATE:
        return summary(_TEMPLATE[construction], i_rated, variant, interface, True, density).coupling
    # Construction not known: span both kinds, and take the more cautious one as typical.
    choice = {
        "low": ("substrate-module", "low"),
        "typical": ("leadframe-module", "typical"),
        "high": ("leadframe-module", "high"),
    }[variant]
    return summary(choice[0], i_rated, choice[1], interface, True, density).coupling


def module_interface(
    construction: str, i_rated: float, variant: str, interface: str = "grease", density: float | None = None
) -> float:
    """Resistance of the interface layer under a whole multi-chip module, K/W. Every watt
    the module loses crosses it, a chip's own as much as its neighbours'."""
    if construction in _TEMPLATE:
        return summary(_TEMPLATE[construction], i_rated, variant, interface, True, density).interface
    choice = {
        "low": ("substrate-module", "low"),
        "typical": ("leadframe-module", "typical"),
        "high": ("leadframe-module", "high"),
    }[variant]
    return summary(choice[0], i_rated, choice[1], interface, True, density).interface


def interface_resistance(outline: str, i_rated: float, variant: str, interface: str = "grease") -> float:
    """Case-to-heatsink resistance of a discrete package's tab through its interface layer, K/W."""
    return summary(outline, i_rated, variant, interface).interface


def shared_time(construction: str, outline: str | None, positions: int, i_rated: float, interface: str) -> float:
    """Seconds the copper under the chips takes to follow a change of loss: how fast the
    case and the heating between chips respond. Only the copper's heat capacity is
    counted, so the real package is slower and a result that uses this errs warm."""
    template, _ = template_for(construction, outline, positions)
    return templates.shared_time(template, i_rated, interface)


def tab_capacity(outline: str | None) -> float:
    """Heat capacity of a discrete package's copper tab, J/K. Whatever lies under the tab,
    the tab follows a change of loss in this times the resistance under it."""
    template, _ = template_for("unknown", outline, 1)
    width, height, thickness = templates.TABS[template]
    return templates.Stack.c_plate * width * height * thickness


def response(
    template: str,
    i_rated: float,
    variant: str,
    interface: str,
    chip: str,
    diode: bool = True,
    *,
    rth: float | None = None,
    technology: str = "",
    v_rated: float = 0.0,
) -> tuple[tuple[float, float], ...]:
    """Stages (share of the resistance, time constant in s) of a chip's thermal response,
    junction to case. diode says whether a diode chip shares the package with the switch.
    rth is the chip's own resistance from the datasheet: where heat goes straight down
    under the die, the die is sized from it."""
    density = current_density(technology, v_rated) if technology else None
    if rth is not None and templates.has_column(template):
        area = templates.chip_area(i_rated, "low", chip, density)
        shape = "low" if variant == "low" else "typical"
        return templates.column_response(template, rth, shape, die_of(technology), area)
    return response_shape(template, i_rated, variant, interface, chip, diode, density)


def response_template(construction: str, outline: str | None, positions: int, variant: str) -> tuple[str, bool]:
    """Package template a chip's transient response is drawn for, and whether it had to be
    guessed. A module whose construction is not known is taken as the kind that answers
    faster, a ceramic substrate, since the faster response swings more; the slower kind, a
    moulded leadframe, is the low end."""
    if positions > 1 and construction not in _TEMPLATE:
        return ("leadframe-module" if variant == "low" else "substrate-module"), True
    return template_for(construction, outline, positions)


def template_for(construction: str, outline: str | None, positions: int) -> tuple[str, bool]:
    """Package template for a device, and whether it had to be guessed."""
    if positions > 1:
        return _TEMPLATE.get(construction, "leadframe-module"), construction not in _TEMPLATE
    return (outline, False) if outline else ("TO-247", True)
