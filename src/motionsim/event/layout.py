"""A layout file: the figures of the board a switching event runs in, which no datasheet has.

The same file is read by the local server, the command line and the page without a server,
with the same refusals. Every figure is optional; one left out is assumed and said so.
"""

from __future__ import annotations

from difflib import get_close_matches

from motionsim.errors import Refusal
from motionsim.event.parts import Detail
from motionsim.files import parse_yaml

# Each figure: the unit it is written in, its factor to SI, the range it is believed in, and
# what it is, for the template and for the refusals.
FIGURES: dict[str, tuple[str, float, float, float, str]] = {
    "l_loop_nh": ("nH", 1e-9, 0.1, 1000.0, "commutation loop: from the decoupling capacitor through both switches and back"),
    "l_cs_nh": ("nH", 1e-9, 0.0, 100.0, "common-source: shared by the gate loop and the power loop (0 with a Kelvin pin)"),
    "l_gate_nh": ("nH", 1e-9, 0.0, 1000.0, "gate loop: the driver's output, the gate and the return to the driver"),
    "r_loop_mohm": ("mΩ", 1e-3, 0.0, 10000.0, "resistance in series in the commutation loop"),
    "c_dc_uf": ("µF", 1e-6, 0.001, 100000.0, "decoupling capacitor at the switches"),
    "esl_nh": ("nH", 1e-9, 0.0, 100.0, "the decoupling capacitor's own inductance, added to the loop"),
}  # fmt: skip
FIELD = {"l_loop_nh": "l_loop", "l_cs_nh": "l_cs", "l_gate_nh": "l_g", "r_loop_mohm": "r_loop"}
FIELD |= {"c_dc_uf": "c_dc", "esl_nh": "esl"}

TEMPLATE = (
    "# The switching loop of your board, for the switching event (motionsim event, or the page's\n"
    "# event plot). Every figure is optional: one left out is assumed for the package and said so.\n"
    + "".join(f"{key}:    # {unit}: {what}\n" for key, (unit, _, _, _, what) in FIGURES.items())
)


def _figure(key: str, value) -> float:
    unit, _, low, high, what = FIGURES[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Refusal(f"{key} in the layout file is not a number: {value!r}", f"give the {what} in {unit}", key)
    if not low <= value <= high:
        raise Refusal(
            f"{key} in the layout file is {value:g} {unit}, outside {low:g} to {high:g} {unit}",
            f"give the {what} in {unit}",
            key,
        )
    return float(value)


def read_layout(text: str, name: str = "layout.yaml") -> Detail:
    """The figures a layout file gives, in SI; a file that cannot be read, a name it should not
    hold or a figure out of its range is refused in a line that names it."""
    data = parse_yaml(text, name, "layout file", "layout")
    if data is None:
        return Detail()
    if not isinstance(data, dict):
        raise Refusal(
            f"the layout file {name} does not hold names and values",
            "see `motionsim template layout` for what it holds",
            "layout",
        )
    found = {}
    for key, value in data.items():
        if key not in FIGURES:
            near = get_close_matches(str(key), FIGURES, n=1)
            hint = f"did you mean {near[0]}?" if near else f"the names it takes are {', '.join(FIGURES)}"
            raise Refusal(f"the layout file holds {key!r}, which it does not take", hint, "layout")
        if value is not None:
            found[FIELD[key]] = _figure(key, value) * FIGURES[key][1]
    return Detail(**found)
