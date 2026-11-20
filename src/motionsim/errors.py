"""What is refused, as distinct from what goes wrong.

A refusal is an answer: the input cannot work, and the reason, what to change and the name
of the figure at issue are said. Everything the tool raises that is not a refusal is a
fault of the tool, and is reported as one. The line between the two is drawn here, by type,
so that a slip in the code is never handed to the user as a mistake of theirs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from motionsim.engine.notes import Code


class Refusal(Exception):
    """An input that cannot work. Carries the reason, what to change and the figure's name.

    Where the engine itself refuses, the kind of refusal rides along as a code (see
    engine/notes.py): whoever has to act on it reads that, and never the reason's words.
    """

    def __init__(self, reason: str, fix: str = "", field: str = "", code: Code | None = None) -> None:
        super().__init__(reason)
        self.reason, self.fix, self.field, self.code = reason, fix, field, code


class BadFigure(Refusal, ValueError):
    """A figure refused where it is used, deep in the engine. Also a ValueError, for the
    searches that try a figure and move on to the next when it cannot be."""


class Fault(RuntimeError):
    """A result the tool should never hand over, such as a loss that is not a number: its
    own failing, said as that and not passed on as an answer."""

    def __init__(self, reason: str, code: Code | None = None) -> None:
        super().__init__(reason)
        self.code = code


class FigureError(ValueError):
    """A figure a model's own check refuses, in words, with the name of the figure at fault.

    Raised inside a model's validator: pydantic carries it through as the cause of its own
    error, so the figure is known from here and never read back out of the words.
    """

    def __init__(self, reason: str, field: str = "") -> None:
        super().__init__(reason)
        self.field = field
