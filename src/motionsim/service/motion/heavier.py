"""How much heavier the load could be before the device, the motor or the link gives."""

from __future__ import annotations

from collections.abc import Generator
from typing import TYPE_CHECKING

from motionsim.engine import ThermalRunaway
from motionsim.engine.point import NO_STABLE
from motionsim.errors import Refusal
from motionsim.service.answers import reason_of
from motionsim.service.workspace import Workspace

if TYPE_CHECKING:
    pass
from motionsim.service.motion.follow import cycle

GROWS = ("inertia", "friction_coulomb", "friction_viscous", "constant_torque", "fan_coefficient")


def _scaled(data: dict, k: float) -> dict:
    """The same request with the load made k times as heavy: what it asks of the motor
    grows with it, the motion and the gearing stay."""
    load = dict(data.get("load") or {})
    for key in GROWS:
        if load.get(key):
            load[key] = load[key] * k
    if load.get("gravity"):
        load["gravity"] = {**load["gravity"], "mass": load["gravity"]["mass"] * k}
    for part, key in (("tumble", "mass"), ("pulsation", "torque"), ("breakaway", "torque")):
        if load.get(part):
            load[part] = {**load[part], key: load[part][key] * k}
    if load.get("vehicle"):
        load["vehicle"] = {
            **load["vehicle"],
            "mass": load["vehicle"]["mass"] * k,
            "drag_area": (load["vehicle"].get("drag_area") or 0.0) * k,
        }
    out = {**data, "load": load}
    if data.get("mission"):
        out["mission"] = {**data["mission"], "torque": [t * k for t in data["mission"]["torque"]]}
    return out


def _tried(data: dict, workspace: Workspace, k: float, coarse: bool = True) -> tuple[bool, str, dict | None]:
    """The motion with the load k times as heavy: whether every check passes, the first
    that fails, and the answer. The search steps through the motion in half as many
    instants (coarse); the answer it settles on is then worked out in full."""
    try:
        out = cycle({**_scaled(data, k), "coarse": coarse}, workspace)
    except Refusal as exc:
        # The load as it stands refused for a figure that is wrong, not for being too
        # much, is the asker's to put right: it is not an answer to how much more.
        if k == 1.0 and exc.field not in ("motion", ""):
            raise
        return False, exc.reason, None
    except ThermalRunaway:
        return False, NO_STABLE, None
    failing = [c["message"] for c in out["checks"] if c["level"] == "fail"]
    return (not failing), (failing[0] if failing else ""), out


def _probe(k: float, tried: tuple[bool, str, dict | None], low: float, high: float, full: bool = False) -> dict:
    """What one probe of the search says as it finishes: the scale tried, whether every check
    passed there, what failed, the hottest junction where the motion was followed, and the
    bounds the answer lies between once it is counted."""
    fine, why, out = tried
    summary = (out or {}).get("summary") or {}
    return {
        "scale": k,
        "passes": fine,
        "full": full,
        "why": why,
        "peak": summary.get("peak"),
        "tj_max": summary.get("tj_max"),
        "low": low,
        "high": high,
    }


def search(data: dict, workspace: Workspace) -> Generator[dict, None, dict]:
    """How much heavier the load could be before the device, the motor or the link gives:
    the load is scaled up until a check fails, and what failed is named. Each probe is
    handed out as it finishes, so that whoever waits can see the search close in, and can
    stop it between two probes; the answer is what the generator returns."""

    def tried(k: float, coarse: bool = True) -> tuple[bool, str, dict | None]:
        return _tried(data, workspace, k, coarse)

    try:
        _scaled(data, 1.0)
    except (TypeError, KeyError, ValueError, AttributeError) as exc:
        raise Refusal(
            f"the load or motion values do not fit: {reason_of(exc)}", "check the load and motion values", "load"
        ) from None
    fine, why, at = first = tried(1.0)
    if not fine:
        low, high = 0.0, 1.0
        yield _probe(1.0, first, low, high)
    else:
        low, high = 1.0, 2.0
        yield _probe(1.0, first, low, high)
        for _ in range(9):
            probe = fine, why_high, found = tried(high)
            if not fine:
                why = why_high
                yield _probe(high, probe, low, high)
                break
            low, at, high = high, found, 2 * high
            yield _probe(low, probe, low, high)
        else:
            return {
                "scale": low,
                "open": True,
                "why": "",
                "peak": (at or {})["summary"]["peak"],
                "tj_max": (at or {})["summary"]["tj_max"],
            }
    for _ in range(6):  # to a part in sixty of the last doubling: finer says nothing more
        middle = (low + high) / 2
        probe = fine, why_middle, found = tried(middle)
        if fine:
            low, at = middle, found
        else:
            high, why = middle, why_middle
        yield _probe(middle, probe, low, high)
    if low > 0:
        probe = fine, _, full = tried(low, coarse=False)
        at = full if fine else at
        yield _probe(low, probe, low, high, full=True)
    return {
        "scale": low,
        "open": False,
        "why": why,
        "peak": None if at is None else at["summary"]["peak"],
        "tj_max": None if at is None else at["summary"]["tj_max"],
    }


def largest(data: dict, workspace: Workspace) -> dict:
    """The answer of the search, its probes left unsaid."""
    found = search(data, workspace)
    while True:
        try:
            next(found)
        except StopIteration as done:
            return done.value
