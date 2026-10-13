"""Values used when a datasheet does not give what the thermal calculation needs.

Each comes as low, typical and high, so a result can show a range instead of
a single number it has no right to.

- Heating between chips and the package-to-heatsink interface are computed
  from first principles for a generic package of the stated construction
  (`motionsim.package`): handbook material properties, standard outlines, and
  a chip size that follows from the current rating.
- The shape of the transient thermal response, used only when a datasheet
  gives a thermal resistance and no transient curve, is computed the same
  way, from the heat capacity of the copper and the die.
"""

from __future__ import annotations

from motionsim.package.templates import response_shape, summary

VARIANTS = ("low", "typical", "high")

_TEMPLATE = {"leadframe": "leadframe-module", "substrate": "substrate-module"}


def module_coupling(construction: str, i_rated: float, variant: str, interface: str = "grease") -> float:
    """Junction rise per watt dissipated in each other chip of a multi-chip module, K/W,
    measured from the heatsink surface, so the interface layer is included."""
    if construction in _TEMPLATE:
        return summary(_TEMPLATE[construction], i_rated, variant, interface).coupling
    # Construction not known: span both kinds, and take the more cautious one as typical.
    choice = {
        "low": ("substrate-module", "low"),
        "typical": ("leadframe-module", "typical"),
        "high": ("leadframe-module", "high"),
    }[variant]
    return summary(choice[0], i_rated, choice[1], interface).coupling


def module_interface(construction: str, i_rated: float, variant: str, interface: str = "grease") -> float:
    """Resistance of the interface layer under a whole multi-chip module, K/W. Every watt
    the module loses crosses it, a chip's own as much as its neighbours'."""
    if construction in _TEMPLATE:
        return summary(_TEMPLATE[construction], i_rated, variant, interface).interface
    choice = {
        "low": ("substrate-module", "low"),
        "typical": ("leadframe-module", "typical"),
        "high": ("leadframe-module", "high"),
    }[variant]
    return summary(choice[0], i_rated, choice[1], interface).interface


def interface_resistance(outline: str, i_rated: float, variant: str, interface: str = "grease") -> float:
    """Case-to-heatsink resistance of a discrete package's tab through its interface layer, K/W."""
    return summary(outline, i_rated, variant, interface).interface


def response(template: str, i_rated: float, variant: str, interface: str, chip: str) -> tuple[tuple[float, float], ...]:
    """Stages (share of the resistance, time constant in s) of a chip's thermal response."""
    return response_shape(template, i_rated, variant, interface, chip)


def template_for(construction: str, outline: str | None, positions: int) -> tuple[str, bool]:
    """Package template for a device, and whether it had to be guessed."""
    if positions > 1:
        return _TEMPLATE.get(construction, "leadframe-module"), construction not in _TEMPLATE
    return (outline, False) if outline else ("TO-247", True)
