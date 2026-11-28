"""The load the chosen part can carry: the application's own load, made as heavy as it can be
while every check of the motion passes with the junction a margin under its rating.

The load's shape is the application's (presets.load_presets, sized to the design point):
its inertia, friction, steady torque and masses grow together, its motion stays. The search
starts where the device's envelope (/api/capability: the most torque it holds at each speed)
says the load's hardest instant would reach its limit, then closes in on the real answer by
following the motion itself, as /api/largest does, with the same checks the results show.
What stops it is named: the junction, the part's current, the motor's current limit or its
reach on the supply, the voltage at turn-off, or another check that fails.

Where the scheme recommended for the application starts the motor open loop (the sensorless
families of control/presets.PRACTICE), the start is part of the proposal: a load is carried
only where the start lifts it from rest, by the very rule presets.chosen picks the scheme by
(sensorless.starting_torque at the drive's current limit against sensorless.rest_load). Past
that, "the open-loop start" is what stops it.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Generator

from motionsim.engine import ThermalRunaway
from motionsim.engine.point import NO_STABLE
from motionsim.errors import Refusal
from motionsim.service.motion.follow import cycle
from motionsim.service.motion.heavier import _scaled
from motionsim.service.workspace import Workspace
from motionsim.text import rounded, written

ROUTE = "/api/load-proposal"
# The figures of the request that are the load and its motion: the proposal puts its own.
LOAD_KEYS = ("load", "profile", "mission", "coarse", "size_heatsink")
MARGIN = 25.0  # K under the junction's rating: guard.check's own, below which its check is a caution
LIGHT = 0.1  # of the usual load: what the design says of itself with almost nothing to drive
LEAST = 0.02  # of the usual load: lighter than this, no load of the kind passes
MOST = 16.0  # of the usual load: heavier than this, something other than this drive limits it
CLOSE = 1.02  # the search stops once the bounds are two parts in a hundred apart
FULL_CLOSE = 1.02  # and in full alike
# The checks that tighten as the load grows: a caution among them that a light load does not
# have is a limit reached. A fail or an undecided of any check is a limit whatever it is.
GROWING = ("temperature", "current", "voltage", "ripple")

WORDS = {
    "junction": "the junction temperature",
    "current": "the part's current rating",
    "motor current": "the motor's current limit",
    "motor voltage": "the motor's reach on this supply (at full field weakening)",
    "motor": "the motor's reach",
    "voltage": "the voltage at turn-off, against the part's rating",
    "ripple": "the current ripple",
    "start": "the open-loop start",
    "none": "nothing within sixteen times the usual load",
}


def design_of(data: dict) -> dict:
    """The design the proposal is for: everything but the load and its motion."""
    return {k: v for k, v in data.items() if k not in LOAD_KEYS}


def _preset(data: dict) -> dict:
    """The application's load, sized to the design point as step 4 sizes it."""
    from motionsim.service.presets import load_presets
    from motionsim.service.validate import point

    motor = data["motor"] if isinstance(data.get("motor"), dict) else {}
    kind = str(motor.get("type") or "pmsm")
    conditions = data["conditions"] if isinstance(data.get("conditions"), dict) else {}
    rpm, torque = point(conditions)
    v_dc = conditions.get("v_dc")
    given = {k: v for k, v in motor.items() if k not in ("type", "t_motor") and v not in ("", None)}
    offered = load_presets(kind, rpm, torque, None if v_dc in ("", None) else float(v_dc), given)
    asked = data.get("application")
    found = next((p for p in offered if p["id"] == asked), None) if asked else offered[0]
    if found is None:
        raise Refusal(
            f"there is no load called {asked} for this motor",
            f"one of {', '.join(p['id'] for p in offered)}",
            "application",
        )
    return found


def _round(value):
    """A load's figures to four significant figures, as a user would type them."""
    if isinstance(value, dict):
        return {k: _round(v) for k, v in value.items()}
    if isinstance(value, float) and math.isfinite(value) and value != 0:
        return rounded(value, 4)
    return value


def scaled_preset(preset: dict, k: float) -> dict:
    """The application's load made k times as heavy, its motion the same."""
    return {**preset, "load": _round(_scaled({"load": preset["load"]}, k)["load"])}


def _request(design: dict, preset: dict) -> dict:
    return {**design, "load": preset["load"], "profile": preset["profile"], "mission": None}


def _motor_limit(request: dict, ws: Workspace) -> str:
    """Which of the motor's limits the motion ran into: its current, or the voltage it can
    reach. Asked of the motor itself at each instant of the motion, in time, as the motion
    asks it: with the voltage the stage really gives and the current a sensorless start holds."""
    from motionsim.drivers import _motor_stage
    from motionsim.load import sample
    from motionsim.motor import Unreachable
    from motionsim.service.motion.inputs import motion_inputs

    try:
        m = motion_inputs(request, ws)
        if m.samples:
            instants = m.samples
        elif m.load is None or m.profile is None:
            raise ValueError("no motion to sample")
        else:
            instants = sample(m.load, m.profile, m.per_segment)
    except (Refusal, ValueError):
        return "motor"
    for x in instants:
        least = None if m.start is None else m.start.floor(x.motor_rpm, x.resting)
        try:
            _motor_stage(m.device, m.motor, x.motor_rpm, x.motor_torque, m.op, least, True)
        except Unreachable as exc:
            code = getattr(exc.code, "value", "")
            return {"reach-current": "motor current", "reach-voltage": "motor voltage"}.get(code, "motor")
        except ValueError:
            return "motor"
    return "motor"


class _Start:
    """The open-loop start of the scheme recommended for the application, as presets.chosen
    reckons it: the torque the drive's current limit makes with the angle imposed, against
    what the load asks of a shaft leaving rest. The first is the drive's and stays as the
    load grows; the second is the load's, worked out for each load tried."""

    def __init__(self, design) -> None:
        from motionsim.control.sensorless import starting_torque

        self.design = design
        self.gives = starting_torque(design, design.limit)

    def asks(self, preset: dict) -> float:
        """N·m a load asks of the shaft leaving rest, as the control lab's design reads it."""
        from dataclasses import replace

        from motionsim.control.sensorless import rest_load
        from motionsim.load import Load
        from motionsim.service.control.design import _standstill

        load = Load.model_validate(preset["load"])
        return rest_load(
            replace(self.design, load_standstill=_standstill(load), load_rest_mean=_standstill(load, True))
        )

    def stop(self, preset: dict) -> dict | None:
        """The check a load fails where the start cannot lift it, as the proposal names it."""
        asks = self.asks(preset)
        if self.gives > asks:  # presets.chosen's own rule: no open-loop start follows at gives <= asks
            return None
        return {
            "level": "fail",
            "topic": "start",
            "message": (
                f"the open-loop start makes at most {written(self.gives, 3)} N·m at the drive's current limit, and "
                f"the load asks {written(asks, 3)} N·m of a shaft leaving rest"
            ),
        }


def _start_of(design: dict, preset: dict, ws: Workspace) -> _Start | None:
    """The start the proposal has to include: where the scheme recommended for the
    application's usual load (presets.chosen) starts the motor open loop. None where it does
    not, or where the control lab has no design of this motor (it takes permanent-magnet
    motors only)."""
    from motionsim.control.presets import BUILDERS, chosen
    from motionsim.service.control.design import _designed

    try:
        built, _ = _designed(_request(design, preset), ws)
    except (Refusal, ValueError):
        return None
    scheme = BUILDERS[chosen(built)[0]](built)
    if not any(b.kind == "if_startup" for b in scheme.blocks):
        return None
    return _Start(built)


def _limit_of(check: dict, request: dict, ws: Workspace) -> str:
    """What a check that stops the load is a limit of, in one word the page reads."""
    topic = check.get("topic", "")
    if topic == "temperature":
        return "junction"
    if topic == "motion":
        return _motor_limit(request, ws)
    return topic or "motor"


class _Tried:
    """One load tried: whether it holds, the check that stops it, and the answer."""

    def __init__(self, k: float, holds: bool, stop: dict | None, out: dict | None, limit: str) -> None:
        self.k, self.holds, self.stop, self.out, self.limit = k, holds, stop, out, limit


def _judged(k: float, out: dict, light: Counter | None, request: dict, ws: Workspace) -> _Tried:
    """A motion's checks read as the proposal reads them: every one passes, the junction is
    the margin under its rating, and no check that tightens with the load has a caution a
    light load does not have."""
    checks = out["checks"]
    stop = next((c for c in checks if c["level"] in ("fail", "undecided")), None)
    if stop is None:
        stop = next((c for c in checks if c["topic"] == "temperature" and c["level"] != "ok"), None)
    if stop is None and light is not None:
        now = Counter(c["topic"] for c in checks if c["level"] == "caution" and c["topic"] in GROWING)
        grew = next((t for t, n in now.items() if n > light.get(t, 0)), None)
        if grew is not None:
            stop = [c for c in checks if c["topic"] == grew and c["level"] == "caution"][-1]
    if stop is None:
        return _Tried(k, True, None, out, "")
    return _Tried(k, False, stop, out, _limit_of(stop, request, ws))


def _try(
    design: dict,
    preset: dict,
    k: float,
    light: Counter | None,
    ws: Workspace,
    coarse: bool = True,
    start: _Start | None = None,
) -> _Tried:
    """The application's load k times as heavy, its motion followed and judged, and lifted
    from rest by the open-loop start where the scheme starts open loop. A load the start
    cannot lift is not followed, but for the usual one, whose figures are shown."""
    scaled = scaled_preset(preset, k)
    request = _request(design, scaled)
    unlifted = None if start is None else start.stop(scaled)
    if unlifted is not None and k != 1.0:
        return _Tried(k, False, unlifted, None, "start")
    tried = _followed(request, k, light, ws, coarse)
    if unlifted is not None and tried.holds:
        return _Tried(k, False, unlifted, tried.out, "start")
    return tried


def _followed(request: dict, k: float, light: Counter | None, ws: Workspace, coarse: bool) -> _Tried:
    """A load's motion followed and judged."""
    try:
        out = cycle({**request, "coarse": coarse}, ws)
    except Refusal as exc:
        if exc.field not in ("motion", ""):
            raise
        return _Tried(k, False, {"level": "fail", "topic": "motion", "message": exc.reason}, None, "motor")
    except ThermalRunaway:
        return _Tried(k, False, {"level": "fail", "topic": "temperature", "message": NO_STABLE}, None, "junction")
    return _judged(k, out, light, request, ws)


def _guess(design: dict, preset: dict, usual: _Tried, workspace: Workspace) -> float | None:
    """Where the device's envelope says the load's hardest instant would reach the most it
    holds: the torque at each instant of the usual load scales with the load, the most the
    device holds at that speed does not."""
    from motionsim.service.remembered import capability

    if usual.out is None:
        return None
    try:
        cap = capability(_request(design, preset), workspace)
    except (Refusal, ValueError, ThermalRunaway):
        return None
    speeds = cap["rpm"]
    edge = [row["torque"] for row in cap["edge"]]
    worst = math.inf
    for rpm, torque in zip(usual.out["rpm"], usual.out["torque"], strict=False):
        if not torque or rpm is None or abs(rpm) > speeds[-1]:
            continue
        held = _between(speeds, edge, abs(rpm))
        if held is not None and held > 0:
            worst = min(worst, held / abs(torque))
    return None if not math.isfinite(worst) else worst


def _between(xs: list[float], ys: list, x: float) -> float | None:
    for (x0, y0), (x1, y1) in zip(zip(xs, ys, strict=False), zip(xs[1:], ys[1:], strict=False), strict=False):
        if x0 <= x <= x1 and y0 is not None and y1 is not None:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return None


def _probe(t: _Tried, low: float, high: float, full: bool = False) -> dict:
    summary = (t.out or {}).get("summary") or {}
    return {
        "scale": t.k,
        "passes": t.holds,
        "full": full,
        "why": "" if t.stop is None else t.stop["message"],
        "limit": t.limit,
        "peak": summary.get("peak"),
        "tj_max": summary.get("tj_max"),
        "low": low,
        "high": high,
    }


def _down(k: float) -> float:
    """A scale cut down to three significant figures: the proposal is a figure to read."""
    if k <= 0:
        return k
    step = 10 ** (math.floor(math.log10(k)) - 2)
    return math.floor(k / step + 1e-9) * step


def _figures(out: dict) -> dict:
    """What a proposed load asks of the motor, read from its motion."""
    rpm, torque, current = out["rpm"], out["torque"], out["i_peak"]
    k_torque = max(range(len(torque)), key=lambda k: abs(torque[k]))
    k_speed = max(range(len(rpm)), key=lambda k: abs(rpm[k]))
    k_power = max(range(len(rpm)), key=lambda k: abs(rpm[k] * torque[k]))
    s = out["summary"]
    points = [
        {"name": name, "rpm": rpm[k], "torque": torque[k]}
        for name, k in (("most torque", k_torque), ("top speed", k_speed), ("most power", k_power))
    ]
    return {
        "peak_torque": abs(torque[k_torque]),
        "rms_torque": s["rms_torque"],
        "top_rpm": abs(rpm[k_speed]),
        "i_peak": max((abs(i) for i in current if i is not None), default=None),
        "tj_peak": s["peak"],
        "tj_top": s["peak_top"],
        "tj_max": s["tj_max"],
        "points": points,
    }


def _refused(t: _Tried) -> Refusal:
    said = "" if t.stop is None else f": {t.stop['message']}"
    return Refusal(
        f"no load of this kind passes on this design, even at {written(t.k, 2)} times the usual one{said}",
        "lower the supply or the design point, take a larger part, or cool it better",
        "",
    )


def search(data: dict, workspace: Workspace) -> Generator[dict, None, dict]:
    """The proposal worked out, each probe handed out as it finishes; the answer is what
    the generator returns. Asked again for the same design, the answer kept is handed back."""
    from motionsim.service import remembered

    design = design_of(data)
    held = remembered.held(ROUTE, design, workspace)
    if held is not None:
        return held
    found = yield from _search(design, workspace)
    remembered.keep(ROUTE, design, workspace, found)
    return found


def _cautions(t: _Tried) -> Counter:
    """The cautions of the checks that tighten with the load, by topic."""
    checks = (t.out or {}).get("checks", [])
    return Counter(c["topic"] for c in checks if c["level"] == "caution" and c["topic"] in GROWING)


class _Bounds:
    """The search as it closes in: the heaviest load found to hold and the lightest found
    not to, with the probe that says so as each finishes."""

    def __init__(self, design: dict, preset: dict, ws: Workspace, start: _Start | None) -> None:
        self.design, self.preset, self.ws, self.start = design, preset, ws, start
        self.light: Counter = Counter()
        self.best: _Tried | None = None
        self.above: _Tried | None = None

    @property
    def low(self) -> float:
        return 0.0 if self.best is None else self.best.k

    @property
    def high(self) -> float:
        return math.inf if self.above is None else self.above.k

    def tried(self, k: float, coarse: bool = True) -> _Tried:
        return _try(self.design, self.preset, k, self.light, self.ws, coarse, self.start)

    def count(self, t: _Tried, full: bool = False) -> dict:
        if t.holds and t.k >= self.low:
            self.best = t
        elif not t.holds and t.k <= self.high:
            self.above = t
        return _probe(t, self.low, self.high if math.isfinite(self.high) else 0.0, full)


def _search(design: dict, workspace: Workspace) -> Generator[dict, None, dict]:
    """The search itself: the usual load, the envelope's guess, out until a load fails and
    in until a load holds, then halving between the two, and the answer worked out in full."""
    preset = _preset(design)
    s = _Bounds(design, preset, workspace, _start_of(design, preset, workspace))
    usual = s.tried(1.0)
    if _cautions(usual) or not usual.holds:
        # What the design says of itself with almost nothing to drive: a caution it has then
        # is the design's, not a limit the load reached.
        light = s.tried(LIGHT)
        s.light = _cautions(light) if light.out else Counter()
        yield s.count(light)
        usual = s.tried(1.0)
    yield s.count(usual)
    guess = _guess(design, preset, usual, workspace)
    if guess is not None:
        k = min(max(guess, LEAST), MOST)
        if (s.best is None or k > s.low * CLOSE) and k < s.high / CLOSE:
            yield s.count(s.tried(k))
    while s.best is None:
        k = (s.high if math.isfinite(s.high) else 1.0) * 0.6
        if k < LEAST:
            raise _refused(s.above or usual)
        yield s.count(s.tried(k))
    grow = 1.1
    while not math.isfinite(s.high):
        k = s.low * grow
        grow = 1.5
        if k > MOST:
            full = _try(design, preset, s.low, None, workspace, coarse=False, start=s.start)
            return _answer(preset, full if full.holds else s.best, None, usual, open_=True, start=s.start)
        yield s.count(s.tried(k))
    while s.high / s.low > CLOSE:
        yield s.count(s.tried(math.sqrt(s.low * s.high)))
    return (yield from _in_full(s, usual))


def _in_full(s: _Bounds, usual: _Tried) -> Generator[dict, None, dict]:
    """The answer worked out in full, as the results will be. The coarse search steps through
    fewer instants and can miss the hardest: where the full motion does not pass at its
    answer, the search goes on in full, down from there."""
    first = s.tried(_down(s.low), coarse=False)
    yield _probe(first, s.low, s.high, full=True)
    if first.holds:
        return _answer(s.preset, first, s.above, usual, start=s.start)
    fails, holds = first, None
    step = 0.97  # the full motion is seldom far from the coarse: close below first, then further
    while holds is None:
        k = _down(fails.k * step)
        step = 0.85
        if k < LEAST:
            raise _refused(fails)
        t = s.tried(k, coarse=False)
        yield _probe(t, k if t.holds else 0.0, fails.k, full=True)
        holds, fails = (t, fails) if t.holds else (None, t)
    while fails.k / holds.k > FULL_CLOSE:
        middle = _down(math.sqrt(holds.k * fails.k))
        if middle <= holds.k:
            break
        t = s.tried(middle, coarse=False)
        yield _probe(t, holds.k, fails.k, full=True)
        holds, fails = (t, fails) if t.holds else (holds, t)
    return _answer(s.preset, holds, fails, usual, start=s.start)


def _answer(
    preset: dict, at: _Tried, above: _Tried | None, usual: _Tried, open_: bool = False, start: _Start | None = None
) -> dict:
    """The proposal as the page reads it: the load, what stops it, the margin, the figures."""
    out = at.out or {}
    figures = _figures(out)
    limit = "none" if open_ or above is None else above.limit
    binding = {
        "limit": limit,
        "words": WORDS.get(limit, f"the {limit} check"),
        "check": "" if above is None or above.stop is None else above.stop["message"],
        "level": "" if above is None or above.stop is None else above.stop["level"],
        "scale": None if above is None else above.k,
    }
    margin = figures["tj_max"] - figures["tj_top"]
    k = at.k
    said = (
        f"The {preset['label'].lower()} load made {written(k, 3)} times as heavy as the usual one: the heaviest at "
        f"which every check of the motion passes with the junction at least {MARGIN:g} K under its rating"
        + (", and the open-loop start of the scheme recommended for it lifts it from rest." if start else ".")
    )
    if open_:
        said += f" It still passes at {written(MOST, 2)} times: something other than this drive limits it first."
    elif binding["check"]:
        said += f" Heavier, {binding['words']} is reached first: {binding['check']}."
    return {
        "application": preset["id"],
        "label": preset["label"],
        "scale": k,
        "open": open_,
        "preset": scaled_preset(preset, k),
        "binding": binding,
        "margin": {"wanted": MARGIN, "junction": margin},
        "figures": figures,
        "usual": _figures(usual.out) if usual.out else None,  # as the coarse search followed it
        "checks": out.get("checks", []),
        "why": said,
    }


def load_proposal(data: dict, workspace: Workspace) -> dict:
    """The answer of the search, its probes left unsaid."""
    found = search(data, workspace)
    while True:
        try:
            next(found)
        except StopIteration as done:
            return done.value
