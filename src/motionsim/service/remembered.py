"""Answers already worked out, kept for a while: the report on a design reuses what the page
has just asked for the same design, instead of working it all out again.

What is kept is the engine's own answer to a request, never anything a page sends: the key is
the request itself, in one form however it was written, with the address it was sent to and
every device file the workspace holds, byte for byte. A device added, replaced or measured
again is another key, so nothing worked out for the part as it was is handed out for the part
as it is. Only answers are kept; a refusal or a fault is worked out again each time.

The store is small and in memory: a few dozen answers, the oldest used going first. A copy
goes in and a copy comes out, so that whoever changes an answer they were given changes
nothing for the next one to ask.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from collections import OrderedDict
from collections.abc import Callable

from motionsim.service.build import recommendations as _recommendations
from motionsim.service.motion import cycle as _cycle
from motionsim.service.verdict import capability as _capability
from motionsim.service.verdict import motor_fit as _motor_fit
from motionsim.service.verdict import proposal as _proposal
from motionsim.service.workspace import Workspace

MOST = 32  # answers kept: the design and its motion for a few devices, a few changes back

Route = Callable[[dict, Workspace], dict]

_kept: OrderedDict[str, dict] = OrderedDict()
_lock = threading.Lock()
counts = {"hits": 0, "misses": 0}


def _without_none(value):
    """A request with every name given as nothing left out: the service reads a name it is
    not given as one given as nothing, and the page sends some that a design leaves out."""
    if isinstance(value, dict):
        return {k: _without_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [_without_none(v) for v in value]
    return value


def _devices(workspace: Workspace) -> list[list[str]]:
    """Every device file the workspace holds, by name and by what is in it."""
    return [[key, hashlib.sha256(path.read_bytes()).hexdigest()] for key, path in sorted(workspace.paths().items())]


def key_of(route: str, data: dict, workspace: Workspace) -> str:
    """The mark of one request: its address, the request in one form whatever way it was
    written (as a design's mark is made), and the devices it could be answered from."""
    from motionsim.design.setup_file import _canon

    whole = [route, str(workspace.folder.resolve()), _devices(workspace), _canon(_without_none(data))]
    return hashlib.sha256(json.dumps(whole).encode()).hexdigest()


def forget() -> None:
    """Nothing is kept from here on, as when the engine has just started."""
    with _lock:
        _kept.clear()
        counts.update(hits=0, misses=0)


def held(route: str, data: dict, workspace: Workspace) -> dict | None:
    """The answer kept for this request, a copy of it, or None: for a search whose answer is
    kept as a whole once it has finished, whichever way it was asked for."""
    key = key_of(route, data, workspace)
    with _lock:
        found = _kept.get(key)
        if found is None:
            counts["misses"] += 1
            return None
        _kept.move_to_end(key)
        counts["hits"] += 1
        return copy.deepcopy(found)


def keep(route: str, data: dict, workspace: Workspace, answer: dict) -> None:
    """Keep a search's answer for this request, as `remembered` keeps one it worked out."""
    key = key_of(route, data, workspace)
    with _lock:
        _kept[key] = copy.deepcopy(answer)
        _kept.move_to_end(key)
        while len(_kept) > MOST:
            _kept.popitem(last=False)


def remembered(route: str, work: Route) -> Route:
    """The same work, its answers kept: a request asked again, with the same devices, is
    answered from what was worked out the first time."""

    def answered(data: dict, workspace: Workspace) -> dict:
        key = key_of(route, data, workspace)
        with _lock:
            held = _kept.get(key)
            if held is not None:
                _kept.move_to_end(key)
                counts["hits"] += 1
                return copy.deepcopy(held)
            counts["misses"] += 1
        found = work(data, workspace)
        kept = copy.deepcopy(found)
        with _lock:
            _kept[key] = kept
            _kept.move_to_end(key)
            while len(_kept) > MOST:
                _kept.popitem(last=False)
        return found

    answered.__doc__ = work.__doc__
    answered.__name__ = getattr(work, "__name__", route)
    return answered


# The requests a report on a design is made of, and the page asks for one by one.
proposal = remembered("/api/proposal", _proposal)
cycle = remembered("/api/cycle", _cycle)
capability = remembered("/api/capability", _capability)
recommendations = remembered("/api/recommend", _recommendations)
motor_fit = remembered("/api/fit", _motor_fit)
