"""What the lab says of itself: the formulas of every block are written so that the page's
typesetter reads them, every wire has a unit the page knows, and the service's own note
names every scheme it offers."""

from __future__ import annotations

import cmath
import math
import re

import pytest

import motionsim.service.control as service
from motionsim.control.blocks import BLOCKS, Context, describe
from motionsim.control.presets import BUILDERS

# The commands the formulas use, each one KaTeX typesets (checked against the page's own
# copy of it in strict mode). A command outside this list is a slip of the hand or needs
# adding here once it is known to typeset.
COMMANDS = {
    "frac", "tfrac", "sqrt", "left", "right", "text", "mathrm", "int", "sum", "min", "max", "arg",
    "cos", "sin", "arctan", "hat", "bar", "dot", "overline", "big", "begin", "end", "quad", "qquad",
    "alpha", "beta", "delta", "Delta", "epsilon", "varepsilon", "lambda", "omega", "psi", "rho", "tau",
    "theta", "vartheta", "xi", "pi", "ell", "imath", "angle", "circ", "le", "ge", "ne", "in", "to", "pm",
    "mp", "lessgtr", "lfloor", "rfloor", "gamma", "zeta", "tilde", "mathrel", "tan", "leftarrow",
    "{", "}", ",", "!", " ", "\\", "|",
}  # fmt: skip
UNITS = {
    "", "A", "V", "W", "Hz", "s", "H", "Wb", "K", "°C", "rad", "rad/s", "rad/s2", "rad/s3", "N·m", "N·m/s",
    "N·m/s2", "N·m·s/rad", "N·m/rad", "kg·m²", "V/A", "V/(A·s)", "bit", "1/turn", "samples", "steps", "rad/A",
}  # fmt: skip


def formulas() -> list[tuple[str, str]]:
    return [(kind, line) for kind, cls in sorted(BLOCKS.items()) for line in cls.math]


def test_every_block_has_its_formulas() -> None:
    assert len(BLOCKS) >= 23
    assert all(cls.math and cls.definition for cls in BLOCKS.values())


@pytest.mark.parametrize(("kind", "line"), formulas())
def test_a_formula_is_written_as_the_page_s_typesetter_reads_it(kind: str, line: str) -> None:
    used = set(re.findall(r"\\([A-Za-z]+|.)", line))
    assert used <= COMMANDS, f"{kind}: {sorted(used - COMMANDS)}"
    depth = 0
    for char in re.sub(r"\\[{}]", "", line):
        depth += (char == "{") - (char == "}")
        assert depth >= 0, f"{kind}: a brace closes that was not opened"
    assert depth == 0, f"{kind}: a brace is left open"
    assert len(re.findall(r"\\left\b", line)) == len(re.findall(r"\\right\b", line)), kind
    assert line.count(r"\begin{") == line.count(r"\end{"), kind
    assert "$" not in line and "\n" not in line, kind


def test_every_wire_and_setting_has_a_unit_the_page_knows() -> None:
    for kind, cls in BLOCKS.items():
        for port in (*cls.inputs, *cls.outputs, *cls.params):
            assert port.unit in UNITS, f"{kind}.{port.name}: {port.unit!r}"


def test_the_service_s_own_note_names_every_scheme_it_offers() -> None:
    for scheme_id in BUILDERS:
        assert f'"{scheme_id}"' in service.__doc__, scheme_id


@pytest.mark.parametrize("way", (1.0, -1.0))
def test_the_back_emf_observer_s_error_is_the_formula_s_in_both_directions(way: float) -> None:
    # A back-EMF of 10 V a quarter turn ahead of the rotor's d axis going forwards, behind it
    # going backwards; the loop's own angle 0.1 rad ahead of the rotor. The formula gives
    # sgn(ω)·(−e_α cos θ̂ − e_β sin θ̂)/|e| = sin(θ − θ̂) = −0.0998 either way, and the loop's
    # speed moves by ρ²·Ts times that in one step.
    ts, theta = 5e-5, 0.7
    ctx = Context(ts=ts, f_carrier=1.0 / ts, v_dc=48.0, rs=0.03, ld=8e-5, lq=8e-5, psi=0.01, pole_pairs=4)
    block = BLOCKS["observer_emf_pll"]("observer", {"pll_bandwidth": 50.0}, ctx)
    block.reset()
    emf = way * 10.0 * 1j * cmath.exp(1j * theta)
    block._theta, block._omega = theta + 0.1, way * 1000.0
    written = way * (-emf.real * math.cos(theta + 0.1) - emf.imag * math.sin(theta + 0.1)) / abs(emf)
    assert written == pytest.approx(-math.sin(0.1))
    block._lock(block._along_d(emf), 0.0, theta, abs(emf))
    assert block._omega - way * 1000.0 == pytest.approx(block._ki * ts * written, rel=1e-9)
    assert block._ki == pytest.approx((2.0 * math.pi * 50.0) ** 2, rel=0.5)  # ρ² of a loop of some 50 Hz


def test_every_block_says_what_it_does_in_a_few_lines():
    """The inspector opens on the summary: a few lines, at most a quarter of a long definition."""
    for kind, cls in BLOCKS.items():
        said = describe(cls)["summary"]
        assert said and len(said.split()) <= 45, kind
        if len(cls.definition.split()) > 60:
            assert len(said.split()) <= 0.3 * len(cls.definition.split()), kind


def test_every_exploration_has_its_problem_worded_on_the_page() -> None:
    # A card the page has no pitch for falls back to the engine's question: long, and unlike
    # every card beside it. Each exploration the engine offers is worded on the page.
    import pathlib
    import re

    from motionsim.service.control.library import EXPLORATIONS

    page = (pathlib.Path(__file__).parents[1] / "web/src/control/explorewords.ts").read_text()
    worded = set(re.findall(r"^  (\w+): \{$", page, flags=re.M))
    missing = sorted(x.id for x in EXPLORATIONS if x.id not in worded)
    assert not missing, missing
