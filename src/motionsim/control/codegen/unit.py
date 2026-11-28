"""One block of a scheme as C: its constants, its state, and the code of its reset, its warm
start and its step. An emitter (emitters.py) fills a `Unit` from the compiled Python block,
whose parameters and set-up figures are read off the block itself, so the constants are the
very numbers the simulation steps with."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from string import Template
from typing import Any

from motionsim.control.blocks import BlockSpec

KEYWORDS = frozenset(
    {
        "auto",
        "break",
        "case",
        "char",
        "const",
        "continue",
        "default",
        "do",
        "double",
        "else",
        "enum",
        "extern",
        "float",
        "for",
        "goto",
        "if",
        "inline",
        "int",
        "long",
        "register",
        "restrict",
        "return",
        "short",
        "signed",
        "sizeof",
        "static",
        "struct",
        "switch",
        "typedef",
        "union",
        "unsigned",
        "void",
        "volatile",
        "while",
        "bool",
        "class",
        "delete",
        "new",
        "this",
        "private",
        "public",
        "protected",
        "template",
        "typename",
        "namespace",
        "operator",
        "friend",
        "virtual",
        "true",
        "false",
        "try",
        "catch",
        "throw",
    }
)


def ident(name: str) -> str:
    """A name as a C identifier: letters, digits and underscores, never a keyword."""
    out = re.sub(r"[^0-9A-Za-z_]", "_", name)
    if not out or out[0].isdigit() or out in KEYWORDS or out.startswith("ms_"):
        out = f"b_{out}"
    return out


def said(text: str) -> str:
    """Words as a C comment holds them: on one line, with nothing that ends the comment."""
    return " ".join(str(text).replace("*/", "* /").replace("/*", "/ *").split())


def literal(value: float) -> str:
    """A number as C reads it back to the same double."""
    x = float(value)
    if math.isinf(x):
        return "HUGE_VAL" if x > 0 else "(-HUGE_VAL)"
    if math.isnan(x):
        raise ValueError("a constant that is not a number")
    text = repr(x)
    return text if any(c in text for c in ".en") else f"{text}.0"


@dataclass
class Constant:
    name: str
    value: Any  # a number, or a switch (int)
    unit: str
    source: str
    switch: bool = False

    def declared(self) -> str:
        if self.switch:
            body = f"static const int MS_MAYBE_UNUSED {self.name} = {int(bool(self.value))};"
        else:
            body = f"static const ms_real MS_MAYBE_UNUSED {self.name} = MS_C({literal(self.value)});"
        unit = f"[{self.unit}] " if self.unit else ""
        return f"{body} /* {said(unit + self.source)} */"


@dataclass
class Unit:
    """What an emitter makes of one block."""

    block: Any  # the compiled Block: its setup attributes (_kp, _reach ...) are read as they stand
    spec: BlockSpec
    name: str  # the C identifier of the block
    constants: list[Constant] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # fixed at generation: a choice and its value
    fields: list[str] = field(default_factory=list)  # declarations inside the block's state struct
    reset: list[str] = field(default_factory=list)
    warm: list[str] = field(default_factory=list)
    step: list[str] = field(default_factory=list)
    solver: bool = False  # whether it needs the current reference's solver
    helpers: list[str] = field(default_factory=list)  # functions of its own, before the step

    @property
    def p(self) -> dict:
        return self.block.p

    @property
    def ctx(self):
        return self.block.ctx

    def upper(self, what: str) -> str:
        return f"{self.name.upper()}_{ident(what).upper()}"

    def param(self, name: str) -> str:
        """A parameter of the block as a named constant, with its unit and where it came from."""
        described = next(p for p in type(self.block).params if p.name == name)
        source = self.spec.sources.get(name) or f"the block's default: {described.about}"
        value = self.p[name]
        self.constants.append(Constant(self.upper(name), value, described.unit, source, isinstance(value, bool)))
        return self.upper(name)

    def derived(self, name: str, value: float, unit: str, why: str) -> str:
        """A figure the block works out once from its parameters and the design."""
        self.constants.append(Constant(self.upper(name), value, unit, f"worked out from the block's figures: {why}"))
        return self.upper(name)

    def choice(self, name: str) -> str:
        """A parameter that is a choice: fixed when the code is generated, said in a comment."""
        source = self.spec.sources.get(name, "the block's default")
        self.notes.append(f"{name} = {self.p[name]} ({said(source)}): fixed at generation")
        return str(self.p[name])

    def code(self, where: list[str], text: str, **names: str) -> None:
        """C statements, `$name` filled in from `names`."""
        where.extend(Template(text).substitute(names).strip("\n").splitlines())
