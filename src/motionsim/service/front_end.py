"""The front end of a drive fed from the mains, for the page and the command line: which
stage suits the design, what each of them loses there, and the checks on the one chosen."""

from __future__ import annotations

from dataclasses import replace

from motionsim import front_end as fe
from motionsim import guard
from motionsim.drivers import at_speed_and_torque
from motionsim.engine.limits import hottest
from motionsim.engine.point import ThermalRunaway
from motionsim.errors import Refusal
from motionsim.motor import Unreachable
from motionsim.package.materials import family
from motionsim.service.shapes import _checks, level_of
from motionsim.service.validate import _conditions, _motor, _number, point
from motionsim.service.verdict.common import _gate, _sound, _switched, _unreachable
from motionsim.service.workspace import Workspace
from motionsim.text import written

# Under this power drawn from the mains, the limits on its harmonics ask nothing of most
# equipment (IEC 61000-3-2: 75 W), and a rectifier alone is the stage to have.
NO_SHAPING_UNDER = 75.0
# A stage is "as good" within this share of the least loss: the simpler one is then taken.
AS_GOOD = 0.10
# The link is held this far over what the motor needs, so the current loop keeps its room.
ROOM = 1.05
ORDER = ("rectifier", "boost", "interleaved", "totem_pole", "six_pulse", "vienna", "active")


def mains(data: dict) -> fe.Mains:
    """The mains as the page or a file gives it: its voltage, its frequency, its phases."""
    given = data.get("mains") or {}
    phases = given.get("phases") or 1
    if str(phases) not in ("1", "3"):
        raise Refusal(f"a mains has one phase or three, and {phases} was given", field="mains.phases")
    return fe.Mains(
        _number(given.get("v"), "mains voltage", low=20, high=1000, field="mains.v"),
        _number(given.get("f") or 50, "mains frequency", low=15, high=1000, field="mains.f"),
        int(phases),
    )


def returns(data: dict) -> bool:
    """Whether the front end a request names gives braking energy back to the mains."""
    kind = fe.TOPOLOGIES.get((data.get("front_end") or {}).get("topology") or "")
    return kind is not None and kind.returns


def _settings(data: dict) -> dict:
    given = data.get("front_end") or {}

    def number(key: str, name: str, low: float, high: float) -> float | None:
        value = given.get(key)
        return None if value in (None, "") else _number(value, name, low=low, high=high, field=f"front_end.{key}")

    c_link = data.get("c_link")
    return {
        "topology": given.get("topology") or None,
        "f_sw": number("f_sw", "front end's switching frequency", 1e3, 1e7),
        "v_dc": number("v_dc", "DC-link voltage", 1, 2000),
        "device": given.get("device") or None,
        "capacitance": _number(c_link, "DC-link capacitance", low=1e-9, field="c_link") if c_link else None,
    }


class _Design:
    """The inverter's side of a request: what it draws from the link at a link voltage."""

    def __init__(self, data: dict, workspace: Workspace) -> None:
        self.motor = _motor(data["motor"])
        self.base = _conditions(data["conditions"] | {"v_dc": data["conditions"].get("v_dc") or 100}, self.motor)
        self.rpm, self.torque = point(data["conditions"])
        self.conditions = data["conditions"]
        self.device = workspace.device(data["device"])
        self._found: dict[float, tuple] = {}

    def at(self, v_dc: float):
        """The motor's point on a link of v_dc: the inverter's conditions there, what the
        stage and the motor draw from the link (W), and the point itself."""
        if v_dc not in self._found:
            op = replace(self.base, v_dc=v_dc)
            _switched(self.motor, op, self.conditions)
            op = _gate(self.device, op, self.motor, self.conditions).op
            try:
                found = at_speed_and_torque(self.device, self.motor, self.rpm, self.torque, op)
            except Unreachable as exc:
                raise _unreachable(exc, op) from None
            _sound(found.result)
            drawn = found.stage.p_shaft + found.stage.p_motor_loss + found.result.p_inverter
            self._found[v_dc] = (op, max(drawn, 0.0), found)
        return self._found[v_dc]

    def need(self, v_dc: float, room: float = ROOM) -> float | None:
        """The least link voltage the motor's point can be made from, V, from how far the
        stage is modulated at v_dc, with `room` over it; None where the stage does not say."""
        op, _, found = self.at(v_dc)
        index = next((value for label, value, _ in found.stage.summary if label == "modulation index"), None)
        if not index:
            return None
        return float(v_dc * index / op.pwm.max_modulation_index * room)

    def _used(self, v_dc: float) -> float | None:
        """What the stage uses of a link of v_dc to make the point, V."""
        op, _, found = self.at(v_dc)
        index = next((value for label, value, _ in found.stage.summary if label == "modulation index"), None)
        return float(v_dc * index / op.pwm.max_modulation_index) if index else None

    def least(self, v_dc: float) -> float | None:
        """The link voltage under which this point is no longer made as it is at v_dc, V: what
        the stage uses of the link, with no room. None where the point is held by weakening
        the field (on a link twice as high it would use more than this link gives): a link a
        little lower weakens the field a little more, and nothing is lost that this figure
        could say."""
        try:
            used, ample = self._used(v_dc), self._used(2.0 * v_dc)
        except (Refusal, ThermalRunaway):
            return None
        if used is None or ample is None or ample > v_dc:
            return None
        return used


# The most a mains of one phase is usually asked for, A a line: over it a drive is fed from three.
ONE_PHASE_MOST = 32.0


def _one(design: _Design, line: fe.Mains, kind: fe.Topology, device, settings: dict) -> dict:
    """One stage on this design, solved, with its checks: or the reason it cannot be."""
    out = {"id": kind.id, "name": kind.name, "about": kind.about, "shapes": kind.shapes, "returns": kind.returns}
    try:
        v_dc = fe.link_voltage(line, kind.id) if not kind.shapes or settings["v_dc"] is None else settings["v_dc"]
        op, drawn, found = design.at(v_dc)
        solved = fe.solve(
            device if kind.shapes else None, line, kind.id, drawn, replace(op, t_sink=found.result.t_sink or op.t_sink),
            v_dc=v_dc if kind.shapes else None, f_sw=settings["f_sw"], capacitance=settings["capacitance"],
        )  # fmt: skip
    except (Refusal, ThermalRunaway) as exc:
        return out | {"refused": str(exc), "level": "fail"}
    checks = _checked(solved, device, line)
    return out | {
        "v_dc": v_dc,
        "loss": solved.p_loss,
        "efficiency": solved.efficiency,
        "power_factor": solved.power_factor,
        "within_limit": solved.within_limit,
        "level": level_of(checks),
        "_solved": solved,
        "_checks": checks,
        "_inverter": found,
    }


def _harmonics_check(solved: fe.FrontEnd) -> guard.Check | None:
    if solved.within_limit is None:
        return guard.Check(
            guard.Level.ok if solved.thd < 0.05 else guard.Level.caution,
            "mains current",
            f"{written(solved.i_line, 3)} A a line is over the 16 A that IEC 61000-3-2 covers: the limit on "
            f"harmonics then depends on how strong the mains is at the place (IEC 61000-3-12); "
            f"the current's distortion is {solved.thd:.0%}",
        )
    if solved.within_limit:
        shaped = "shaped to a sine" if not solved.harmonics else f"distortion {solved.thd:.0%}"
        return guard.Check(guard.Level.ok, "mains current", f"within the harmonic limits of IEC 61000-3-2 ({shaped})")
    # The lowest harmonic over its limit: the one a real mains softens least.
    worst = next(h for h in solved.harmonics if h.limit and h.current > h.limit)
    return guard.Check(
        guard.Level.caution,
        "mains current",
        f"harmonic {worst.order} is {written(worst.current, 3)} A against the {worst.limit:.2f} A that "
        f"IEC 61000-3-2 (class A) allows, at a power factor of {solved.power_factor:.2f}: "
        "a stage that shapes the current brings it within",
    )


def _checked(solved: fe.FrontEnd, device, line: fe.Mains) -> list[dict]:
    checks: list[guard.Check] = []
    if solved.stage is not None and solved.op is not None:
        half = solved.op.v_dc < solved.v_dc - 1
        for check in guard.voltage_checks(device, solved.op, solved.stage, 0.8):
            # The engine's words are an inverter's: here the voltage is the link's, or half of it.
            said = str(check.message).replace("supply", "half the link" if half else "the link", 1)
            checks.append(replace(check, message=said))
        checks.append(guard.temperature_check(device, solved.op, solved.stage, 25.0))
        checks.append(guard.data_check(solved.stage))
    harmonics = _harmonics_check(solved)
    if harmonics is not None:
        checks.append(harmonics)
    if line.phases == 1 and solved.i_line > ONE_PHASE_MOST:
        checks.append(
            guard.Check(
                guard.Level.caution,
                "mains",
                f"{written(solved.i_line, 3)} A is drawn from one phase, where a mains of one phase gives up to "
                f"about {ONE_PHASE_MOST:g} A: a drive of this power is fed from three phases",
            )
        )
    return _checks(checks)


def _recommend(choices: list[dict], drawn: float, braking: bool, device) -> tuple[str, str]:
    """The stage for this design and the reason, in a sentence. Among the stages that shape
    the current and pass their checks: the one that gives braking energy back where the
    motion brakes, else the least loss, the simpler one where two are as good."""
    by_id = {c["id"]: c for c in choices}
    plain = next(c for c in choices if not c["shapes"])
    if "refused" not in plain and not braking:
        if drawn < NO_SHAPING_UNDER:
            return plain["id"], (
                f"Under {NO_SHAPING_UNDER:g} W drawn from the mains, nothing has to shape the current: "
                "a rectifier is enough."
            )
        if plain["within_limit"]:
            return plain["id"], (
                "A rectifier alone stays within the harmonic limits at this power, with the least loss "
                "and the fewest parts: nothing has to shape the current."
            )
    fit = [c for c in choices if c["shapes"] and c["level"] != "fail"]
    if not fit:
        shaping = [c for c in choices if c["shapes"] and "refused" not in c] or [plain]
        best = min(shaping, key=lambda c: c.get("loss", float("inf")))
        return best["id"], "No stage passes its checks with this part: this one comes nearest."
    if braking and any(c["returns"] for c in fit):
        best = min((c for c in fit if c["returns"]), key=lambda c: c["loss"])
        return best["id"], "The motion brakes, and this stage gives that energy back to the mains."
    least = min(c["loss"] for c in fit)
    best = next(c for c in sorted(fit, key=lambda c: ORDER.index(c["id"])) if c["loss"] <= least * (1 + AS_GOOD))
    others = [c for c in fit if c is not best]
    if not others:
        return best["id"], "The one stage that shapes the current and passes its checks with this part."
    rival = min(others, key=lambda c: c["loss"])
    lead = f"{written(best['loss'], 3)} W lost against {written(rival['loss'], 3)} W for {_lower(rival['name'])}"
    if best["loss"] > least * (1 + 1e-9):
        return best["id"], f"As good as the least loss, with fewer parts: {lead}."
    reason = f"The least loss of the stages that shape the current: {lead}."
    recovery = by_id.get("totem_pole")
    if best["id"] == "totem_pole" and family(device.technology) in ("sic", "gan"):
        reason += " This part's reverse recovery is small enough for it."
    elif best["id"] == "boost" and recovery is not None and recovery.get("loss", 0) > best["loss"]:
        reason += " This part's reverse recovery costs a totem-pole stage more than a bridge does."
    return best["id"], reason


def _lower(name: str) -> str:
    """A stage's name inside a sentence: "a boost PFC", "an active front end"."""
    words = name[0].lower() + name[1:]
    return ("an " if words[0] in "aeiou" else "a ") + words


def _detail(choice: dict, device, tj_max: float) -> dict:
    solved: fe.FrontEnd = choice["_solved"]
    stage = solved.stage
    inductor = solved.inductor
    return {
        "topology": solved.topology,
        "name": choice["name"],
        "v_dc": solved.v_dc,
        "f_sw": solved.f_sw,
        "p_link": solved.p_link,
        "p_in": solved.p_in,
        "loss": solved.p_loss,
        "loss_switches": solved.p_switches,
        "loss_diodes": solved.p_diodes,
        "efficiency": solved.efficiency,
        "i_line": solved.i_line,
        "power_factor": solved.power_factor,
        "thd": solved.thd,
        "within_limit": solved.within_limit,
        "harmonics": [{"order": h.order, "current": h.current, "limit": h.limit} for h in solved.harmonics[:8]],
        "tj_peak": None if stage is None else hottest(stage),
        "tj_max": tj_max,
        "positions": 0 if stage is None else sum(r.count for r in stage.roles),
        "roles": []
        if stage is None
        else [
            {
                "name": r.name,
                "count": r.count,
                "conduction": r.switch.conduction + r.switch.dead_time + r.diode.conduction,
                "switching": r.switch.turn_on + r.switch.turn_off + r.switch.recovery + r.diode.recovery,
                "tj_peak": max(r.tj_switch_peak, r.tj_diode_peak),
            }
            for r in stage.roles
        ],
        "inductor": None
        if inductor is None
        else {
            "henry": inductor.henry,
            "count": inductor.count,
            "i_peak": inductor.i_peak,
            "i_rms": inductor.i_rms,
            "ripple": inductor.ripple,
        },
        "capacitor": {
            "rms": solved.cap_rms,
            "slow": solved.cap_slow,
            "capacitance": solved.capacitance,
            "sized": solved.capacitance_sized,
            "v_ripple": solved.v_ripple,
        },
        "notes": solved.notes,
        "checks": choice["_checks"],
        "level": choice["level"],
        "device": device.part_number,
    }


def _lever(design: _Design, line: fe.Mains, chosen: dict, device, settings: dict) -> dict | None:
    """What holding the link only as high as the motor needs would save in both stages, where
    the chosen stage sets its link and the motor needs less than it holds."""
    kind = fe.TOPOLOGIES[chosen["id"]]
    if not kind.shapes or "refused" in chosen:
        return None
    try:
        need = design.need(chosen["v_dc"])
        if need is None:
            return None
        lower = fe.link_voltage(line, kind.id, need=need)
        if lower > chosen["v_dc"] - 5:
            return None
        again = _one(design, line, kind, device, settings | {"v_dc": lower})
    except (Refusal, ThermalRunaway):
        return None
    if "refused" in again or again["level"] == "fail":
        return None
    now = chosen["loss"] + chosen["_inverter"].result.p_inverter
    then = again["loss"] + again["_inverter"].result.p_inverter
    if now - then < 0.01 * now:
        return None
    return {"v_dc": lower, "need": need, "saves": now - then, "loss": then, "from": chosen["v_dc"]}


def front_end(data: dict, workspace: Workspace) -> dict:
    """The stages that can feed this design from its mains, each solved at the design point;
    the one recommended and why; and the one chosen (front_end.topology, else the one
    recommended) in full, with its checks.

    data is a design point's request with `mains` {v, f, phases} and, where given,
    `front_end` {topology, f_sw, v_dc, device}, `c_link` and `brakes` (the motion gives
    energy back).
    """
    line = mains(data)
    settings = _settings(data)
    design = _Design(data, workspace)
    device = workspace.device(settings["device"]) if settings["device"] else design.device
    kinds = [fe.TOPOLOGIES[i] for i in ORDER if fe.TOPOLOGIES[i].phases == line.phases]
    if settings["topology"] is not None and settings["topology"] not in {k.id for k in kinds}:
        many = "three phases" if line.phases == 3 else "one phase"
        raise Refusal(
            f"there is no front end called {settings['topology']} for a mains of {many}",
            "one of " + ", ".join(k.id for k in kinds),
            "front_end.topology",
        )
    choices = [_one(design, line, kind, device, settings) for kind in kinds]
    solved = [c for c in choices if "refused" not in c]
    if not solved:
        raise Refusal(choices[-1]["refused"], field="mains.v")
    drawn = max(c["_solved"].p_link for c in solved)
    recommended, why = _recommend(choices, drawn, bool(data.get("brakes")), device)
    chosen = next(c for c in choices if c["id"] == (settings["topology"] or recommended))
    if "refused" in chosen:
        raise Refusal(chosen["refused"], "another front end, or another part for it", "front_end.topology")
    lever = _lever(design, line, chosen, device, settings)
    return {
        "mains": {"v": line.v_rms, "f": line.f, "phases": line.phases},
        "recommended": recommended,
        "why": why,
        "chosen": chosen["id"],
        "v_dc": chosen["v_dc"],
        "v_dc_given": settings["v_dc"] is not None and fe.TOPOLOGIES[chosen["id"]].shapes,
        "choices": [{k: v for k, v in c.items() if not k.startswith("_")} for c in choices],
        "result": _detail(chosen, device, device.ratings.tj_max),
        "lever": lever,
    }
