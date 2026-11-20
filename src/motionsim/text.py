"""How a number is written in a sentence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def written(value: float, digits: int = 3) -> str:
    """A number to a few significant figures, written out: 20000, not 2e+04.

    The same rounding as the `g` format, without its habit of turning to powers of ten
    as soon as a number has more digits than it was asked for. Very large and very small
    numbers, where the power of ten is the plainer way, keep it.
    """
    x = float(f"{float(value):.{digits}g}")
    if abs(x) >= 1e6:
        return f"{x:.{digits}g}"  # as many figures as were asked for, whatever the size
    # Ten figures hold anything already rounded to fewer; below a ten-thousandth the format
    # turns to a power of ten by itself.
    return f"{x:.10g}"


def rounded(value: float, digits: int = 3) -> float:
    """A number to a few significant figures, kept a number: what `written` writes, read back."""
    return float(written(value, digits))


def capital(text: str) -> str:
    """A sentence with its first letter raised, unless its first word is a name that mixes
    its cases on purpose (eGaN, xFET), which is left as it is written."""
    first = text.split(" ", 1)[0]
    if any(c.isupper() for c in first[1:]):
        return text
    return text[:1].upper() + text[1:]


# The names a figure is known by in words, where its key is not plain enough to say. Keys
# not here are said with their underscores as spaces. The page's own labels for a motor's
# figures (service/catalogue.py) are passed in by whoever has them.
NAMES = {
    "v_dc": "the supply voltage",
    "f_sw": "the switching frequency",
    "t_sink": "the heatsink temperature",
    "t_ambient": "the air temperature",
    "i_rms": "the current",
    "pf": "the power factor",
    "m": "the modulation index",
    "f_out": "the output frequency",
    "t_dead": "the dead time",
    "t_min_pulse": "the shortest pulse",
    "v_drive": "the gate drive voltage",
    "rg_on": "the turn-on gate resistance",
    "rg_off": "the turn-off gate resistance",
    "l_loop": "the loop inductance",
    "rth_sink": "the heatsink's thermal resistance",
    "rth_case_sink": "the case-to-heatsink thermal resistance",
    "rth_ja": "the junction-to-air thermal resistance",
    "board_area": "the board's area",
    "parallel": "the number of devices in parallel",
    "v_max": "the voltage rating",
    "i_nominal": "the current rating",
    "i_pulsed": "the pulsed current rating",
    "tj_max": "the highest junction temperature",
    "t_sc": "the short-circuit time",
    "tj": "the junction temperature of a curve",
    "v_ref": "the test voltage",
    "r": "a thermal resistance",
    "tau": "a time constant",
    "q_gs": "the gate-source charge",
    "q_gd": "the gate-drain charge",
    "q_g": "the total gate charge",
    "q_g_drive": "the gate voltage of the total gate charge",
    "q_g_th": "the gate charge at threshold",
    "v_plateau": "the plateau voltage",
    "q_oss": "the output charge",
    "q_rr": "the recovery charge",
    "rg_internal": "the internal gate resistance",
    "outline": "the package outline",
    "topology": "the package's arrangement",
    "construction": "the module's construction",
    "interface": "the layer under the package",
    "gear_ratio": "the gear ratio",
    "gear_efficiency": "the gear efficiency",
    "motor_inertia": "the rotor inertia",
    "inertia": "the load inertia",
    "friction_coulomb": "the friction",
    "friction_viscous": "the friction growing with speed",
    "fan_coefficient": "the fan constant",
    "mass": "the weight",
    "arm": "the arm length",
    "wheel_radius": "the wheel radius",
    "rolling_resistance": "the rolling resistance",
    "drag_area": "the drag area",
    "duration": "the duration",
    "speed_start": "the speed at the start",
    "speed_end": "the speed at the end",
    "segments": "the stretches of the motion",
    "points": "the measured points",
    "e_on": "the turn-on energy",
    "e_off": "the turn-off energy",
    "e_rr": "the recovery energy",
    "current": "a current",
    "value": "a value",
}


def _figure(x) -> str:
    return written(x, 6) if isinstance(x, (int, float)) and not isinstance(x, bool) else str(x)


def plain_error(error: Mapping[str, Any], names: dict[str, str] | None = None) -> tuple[str, str]:
    """One of pydantic's errors as a sentence a person reads, and the figure it is about.

    No words of the validator's own pass through: its kinds of error are each said here.
    Where a model's own check raised a FigureError, its words and its figure are taken.
    """
    names = {**NAMES, **(names or {})}
    loc = [str(x) for x in error.get("loc", ())]
    keys = [p for p in loc if not p.isdigit()]
    field = keys[-1] if keys else ""
    what = names.get(field) or (field.replace("_", " ") if field else "a figure")
    # Where in a list it sits: a motion's second stretch, a table's third point.
    for k, part in enumerate(loc):
        if part.isdigit() and k and loc[k - 1] == "segments":
            what = f"{what} of stretch {int(part) + 1}"
    kind, ctx = error.get("type", ""), error.get("ctx") or {}
    cause = ctx.get("error")
    if kind == "value_error" and cause is not None:
        return str(cause), getattr(cause, "field", "") or field
    expected = str(ctx.get("expected", "")).replace("'", "")
    said = {
        "missing": f"{what} is needed",
        "literal_error": f"{what} is one of {expected}",
        "enum": f"{what} is one of {expected}",
        "greater_than": f"{what} has to be above {_figure(ctx.get('gt'))}",
        "greater_than_equal": f"{what} cannot be below {_figure(ctx.get('ge'))}",
        "less_than": f"{what} has to be below {_figure(ctx.get('lt'))}",
        "less_than_equal": f"{what} cannot be above {_figure(ctx.get('le'))}",
        "finite_number": f"{what} is not a number",
        "float_parsing": f"{what} is not a number",
        "float_type": f"{what} is not a number",
        "int_parsing": f"{what} is not a whole number",
        "int_type": f"{what} is not a whole number",
        "int_from_float": f"{what} has to be a whole number",
        "bool_parsing": f"{what} is yes or no",
        "bool_type": f"{what} is yes or no",
        "string_type": f"{what} has to be words",
        "list_type": f"{what} has to be a list",
        "dict_type": f"{what} has to be a set of names and values",
        "model_type": f"{what} has to be a set of names and values",
        "model_attributes_type": f"{what} has to be a set of names and values",
        "too_short": f"{what} needs at least {ctx.get('min_length')}",
        "too_long": f"{what} holds at most {ctx.get('max_length')}",
        "extra_forbidden": f"there is no figure called {field} here",
        "union_tag_invalid": f"there is no kind called {ctx.get('tag')}: it is one of "
        + str(ctx.get("expected_tags", "")).replace("'", ""),
        "union_tag_not_found": "the kind is needed",
    }.get(kind, f"{what} is not a figure that can be used here")
    return said, field
