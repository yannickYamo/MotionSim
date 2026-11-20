"""How an answer leaves the service: the answer itself, a refusal, or a fault.

Every way in (the page's own copy of the engine, the local server, the command line) hands
its work to `answer` and gets back a status and a body. One place decides what is the
asker's to put right and what is a fault of the tool, so the three can never disagree.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable

from motionsim.engine.notes import Code
from motionsim.engine.point import ThermalRunaway
from motionsim.errors import Refusal

# Faults and timings only: never a device file, a datasheet's content or a key.
log = logging.getLogger("motionsim")


def finite(value):
    """An answer as it can be written: a figure that is not a number goes as none at all,
    which every reader of JSON takes, where NaN is taken by none."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite(v) for v in value]
    return value


def reason_of(exc: Exception) -> str:
    """What a set of figures was refused for, in a line: the figure in words and what is
    wrong with it, never the validator's own wording or the address of a page about it."""
    return refused_figure(exc)[0]


def refused_figure(exc: Exception) -> tuple[str, str]:
    """The sentence and the name of the figure for the first thing wrong in a set of figures."""
    from motionsim.text import plain_error

    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            return plain_error(errors()[0])
        except (IndexError, TypeError, AttributeError):
            pass
    return (str(exc).splitlines()[0].strip() if str(exc).strip() else type(exc).__name__), ""


RUNAWAY = {
    "refused": "no stable temperature: the losses grow faster than the heat can leave",
    "fix": "lower the current or switching frequency, cool the heatsink, or pick a larger device",
    "field": "",
    # Not the asker's slip but the part's answer: it does not pass, as a comparison or a design
    # that meets the same temperatures says, and every command exits as one that fails.
    "level": "fail",
}


def _refusal(reason: str, fix: str = "", field: str = "") -> dict:
    return {"refused": reason, "fix": fix, "field": field}


GATE_FIX = "open Gate drive under Supply and point, and give the drive voltage and gate resistors"


def refusal_of(exc: BaseException) -> dict | None:
    """The refusal an exception stands for, in the three words every refusal comes in, or
    None where it is not one: a fault of the tool, which is not the asker's to put right.

    Only the types that are raised on purpose for an input that cannot work are named here.
    A ValueError or an arithmetic error from anywhere else is a slip in the code.
    """
    if isinstance(exc, Refusal):
        return _refusal(exc.reason, exc.fix, exc.field)
    if isinstance(exc, ThermalRunaway):
        # Temperatures that settle far above the data are not a runaway, and are not said as one.
        # Either way the junction does not stay under its rating: the part fails there.
        if exc.code is Code.thermal_runaway:
            return dict(RUNAWAY)
        return {**_refusal(str(exc), RUNAWAY["fix"]), "level": "fail"}
    from pydantic import ValidationError

    from motionsim.engine.mosfet import MissingGateDrive
    from motionsim.motor.stage import Unreachable
    from motionsim.trajectory import BadTrajectory

    if isinstance(exc, MissingGateDrive):
        return _refusal(str(exc), GATE_FIX, "v_drive")
    if isinstance(exc, Unreachable):
        from motionsim.service.verdict import FIXES

        return _refusal(f"this motor cannot do that: {exc}", FIXES.get(exc.code, FIXES[Code.reach_other]), "point")
    if isinstance(exc, BadTrajectory):
        return _refusal(f"the trajectory cannot be used: {exc}", "see `motionsim template trajectory`", "trajectory")
    if isinstance(exc, ValidationError):
        said, field = refused_figure(exc)
        return _refusal(
            f"these figures cannot be worked with: {said}",
            "look for a figure that is zero, far too large or small, or of the wrong kind",
            field,
        )
    return _refusal_of_a_fit(exc)


def _refusal_of_a_fit(exc: BaseException) -> dict | None:
    """The refusals of the code that builds a device from figures. Looked up only for an
    exception nothing else knew, so that an answer never waits on that code being loaded."""
    if not isinstance(exc, ValueError):
        return None
    from motionsim.fit.sparse import MissingData
    from motionsim.fit.typed import Mistyped

    if isinstance(exc, Mistyped):
        return _refusal(str(exc), "check the figure against the datasheet", exc.field or "")
    if isinstance(exc, MissingData):
        return _refusal(f"a device cannot be built: {exc}", "the datasheet lacks something the model needs")
    return None


# A path, on any system: said by its last part only, so that a fault's message never
# carries where the user keeps their files.
# A web address is not a path, and is kept whole: what follows a scheme's colon, or a
# slash, is not taken for one.
_PATH = re.compile(r"""(?<![\w.:/\\])(?:[A-Za-z]:)?(?:[\\/][^\\/\s:'"<>|]+)+""")


def without_paths(text: str) -> str:
    return _PATH.sub(lambda m: re.split(r"[\\/]", m.group())[-1], text)


def fault_of(exc: BaseException, where: str = "") -> dict:
    """A fault of the tool, for the asker: what kind, in a line, with no path in it. Where
    it happened goes to the log, with the whole trace."""
    log.error("fault answering %s", where or "a request", exc_info=(type(exc), exc, exc.__traceback__))
    said = without_paths(str(exc).splitlines()[0].strip()) if str(exc).strip() else ""
    return {"error": f"{type(exc).__name__}: {said}" if said else type(exc).__name__}


def answer(work: Callable[[], object], where: str = "", passing: type[BaseException] | tuple = ()) -> tuple[int, dict]:
    """Do the work and say how it went: 200 with the answer, 422 with a refusal, 500 with a
    fault. The statuses are HTTP's, read the same way by the page, the server and the
    command line."""
    try:
        return 200, finite(work())
    except passing:  # the caller's own to answer
        raise
    except Exception as exc:
        refusal = refusal_of(exc)
        if refusal is not None:
            log.info("refused %s: %r", where or "a request", exc)
            return 422, refusal
        return 500, fault_of(exc, where)
