"""Every request the service answers, by its address, and the one way they are all answered.

The page's own copy of the engine, the local server and the command line come through
`dispatch`: the same checks on what a request must hold, the same function for each
address, and the same decision on what is a refusal and what is a fault.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Generator

from motionsim.service.answers import answer, finite
from motionsim.service.motion import largest
from motionsim.service.motion.heavier import search
from motionsim.service.presets import loads, setup, suggest
from motionsim.service.remembered import capability, cycle, motor_fit, proposal, recommendations
from motionsim.service.validate import asked
from motionsim.service.verdict import (
    compare,
    largest_current,
    motor_point,
    simulate,
    speed_torque,
    stage,
    trajectory,
)
from motionsim.service.verdict.sizing import cooling_offer
from motionsim.service.workspace import Workspace, add_device, add_measurement, add_typed, curves


def _report(data: dict, workspace: Workspace) -> dict:
    """The whole design as a report in Markdown, for saving from the page: the same
    document `motionsim design run` writes."""
    from motionsim import design

    return {"markdown": design.markdown(design.run(data, workspace, strict=False))}


def _event(data: dict, workspace: Workspace) -> dict:
    """The switching event, its code fetched only when one is first asked for."""
    from motionsim.service.verdict.event import event

    return event(data, workspace)


Route = Callable[[dict, Workspace], dict]

ROUTES: dict[str, Route] = {
    "/api/stage": lambda data, ws: stage(data),
    "/api/proposal": proposal,
    "/api/capability": capability,
    "/api/largest": largest,
    "/api/suggest": suggest,
    "/api/fit": motor_fit,
    "/api/report": _report,
    "/api/loads": lambda data, ws: loads(data),
    "/api/cycle": cycle,
    "/api/map": speed_torque,
    "/api/recommend": recommendations,
    "/api/simulate": simulate,
    "/api/compare": compare,
    "/api/max-current": largest_current,
    "/api/point": motor_point,
    "/api/trajectory": trajectory,
    "/api/cooling": cooling_offer,
    "/api/event": lambda data, ws: _event(data, ws),
}

# Requests that bring a device in: their figures are text and names, checked by what reads them.
ADDING: dict[str, Route] = {
    "/api/device": lambda data, ws: add_device(data.get("name", ""), data.get("text", ""), ws),
    "/api/typed": lambda data, ws: add_typed(data.get("figures"), ws),
    "/api/measure": lambda data, ws: add_measurement(
        data.get("device", ""), data.get("name", ""), data.get("text", ""), ws
    ),
}


def known(route: str) -> bool:
    """Whether a request can be posted to this address."""
    return route in ROUTES or route in ADDING


class NoSuchAddress(LookupError):
    """A request to an address nothing answers at."""


def run(route: str, data: dict, workspace: Workspace) -> dict:
    """The answer to one request, or the exception it ended in: a refusal, or a fault. For
    a caller that reports those its own way, as the command line does."""
    if route == "/api/setup":
        return setup(workspace)
    if route.startswith("/api/device/"):
        return curves(route.rsplit("/", 1)[1], workspace)
    handler = ROUTES.get(route) or ADDING.get(route)
    if handler is None:
        raise NoSuchAddress(route)
    asked(route, data)  # a request that lacks what its address needs is refused in words
    return handler(data, workspace)


def dispatch(route: str, data: dict, workspace: Workspace) -> tuple[int, dict]:
    """One request answered: a status read as HTTP's is, and the body that goes with it.
    200 with the answer, 422 with a refusal, 404 for no such address, 500 with a fault."""
    try:
        return answer(lambda: run(route, data, workspace), route, passing=NoSuchAddress)
    except NoSuchAddress:
        return 404, {"error": "no such address"}


def call(route: str, payload: str, workspace: Workspace) -> str:
    """One request as text in, text out: the form the browser's own copy of the engine uses."""
    try:
        data = json.loads(payload or "{}")
    except (ValueError, RecursionError):
        data = None
    if not isinstance(data, dict):
        return json.dumps({"status": 400, "body": {"error": "the request has to be a JSON object"}})
    status, body = dispatch(route, data, workspace)
    return json.dumps({"status": status, "body": body})


# Requests whose answer is a search that says each step as it finishes: the same answer as
# the address gives, with the steps before it.
Search = Callable[[dict, Workspace], Generator[dict, None, dict]]
STREAMS: dict[str, Search] = {"/api/largest": search}


def _raise(exc: BaseException) -> dict:
    raise exc


def stream(route: str, data: dict, workspace: Workspace) -> Generator[dict, None, None]:
    """One request to a search, answered step by step: a {"probe": ...} for each step as it
    finishes, then {"status": ..., "body": ...} as `dispatch` would have answered the whole.
    Whoever stops reading stops the search: nothing is worked out past the step it is at."""
    if route not in STREAMS:
        yield {"status": 404, "body": {"error": "no such address"}}
        return
    steps: Generator[dict, None, dict] | None = None
    try:
        asked(route, data)
        steps = STREAMS[route](data, workspace)
        while True:
            try:
                probe = next(steps)
            except StopIteration as done:
                final: tuple[int, dict] = (200, finite(done.value))
                break
            yield {"probe": finite(probe)}
    except Exception as exc:
        failed = exc
        final = answer(lambda: _raise(failed), route)
    finally:
        if steps is not None:
            steps.close()  # stopped between two steps: the search goes no further
    yield {"status": final[0], "body": final[1]}


def stream_call(route: str, payload: str, workspace: Workspace) -> Generator[str, None, None]:
    """The same, as lines of text: the form the browser's own copy of the engine reads, one
    line at a time, with a pause between two in which it can be told to stop."""
    try:
        data = json.loads(payload or "{}")
    except (ValueError, RecursionError):
        data = None
    if not isinstance(data, dict):
        yield json.dumps({"status": 400, "body": {"error": "the request has to be a JSON object"}})
        return
    for line in stream(route, data, workspace):
        yield json.dumps(line)
