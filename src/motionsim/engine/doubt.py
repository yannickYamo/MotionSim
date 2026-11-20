"""How far the data supports a result: which of the notes that put the point outside the
data could move the stage's loss enough to matter, and how much higher the hottest junction
could then be."""

from __future__ import annotations

from motionsim.device.schema import Basis, Device
from motionsim.engine.envelope import _Notes
from motionsim.engine.point import RoleResult, Validity

MINOR_SHARE = 0.05  # a share of the stage's loss below which nothing changes a verdict


def _uses_point_tables(device: Device) -> bool:
    sw, d = device.switch, device.diode
    tables = [sw.conduction, sw.e_on, sw.e_off, sw.reverse]
    if d is None:
        tables.append(sw.e_rr)
    if d is not None:
        tables += [d.conduction, d.e_rr]
    measured = sw.e_on is not None and sw.e_off is not None
    return not measured or any(t is not None and t.basis is Basis.point for t in tables)


def _shares(roles: list[RoleResult]) -> dict[str, float]:
    """Each loss term's share of the stage's loss, under the names the data notes use."""
    terms = {
        "switch conduction": lambda r: r.switch.conduction,
        "turn-on energy": lambda r: r.switch.turn_on,
        "turn-off energy": lambda r: r.switch.turn_off,
        "reverse conduction": lambda r: r.switch.dead_time,
        "recovery energy": lambda r: r.switch.recovery + r.diode.recovery,
        "diode conduction": lambda r: r.diode.conduction,
    }
    total = sum(r.count * (r.switch.total + r.diode.total) for r in roles)
    if total <= 0:
        return dict.fromkeys(terms, 0.0)
    return {name: sum(r.count * pick(r) for r in roles) / total for name, pick in terms.items()}


def _doubt(marks: _Notes, roles: list[RoleResult], coolest: float) -> float:
    """How much higher the hottest junction's rise would be, as a share of it, were the loss
    that rests on data the datasheet does not hold as far off as it can be. A junction rises
    mostly with its own chip's loss, so a term in doubt counts for its share of that chip's
    loss, and never for less than its share of the stage's, which every chip is warmed by.
    Each chip is carried to where it would then stand, and the hottest of those is set
    against the hottest as drawn: a cool chip much in doubt does not speak for a hot one."""
    share = _shares(roles)
    off = marks.off.get
    stage = sum(share.get(term, 1.0) * far for term, far in marks.off.items())
    hottest = max(r.hottest for r in roles)
    if hottest <= coolest:
        return 0.0
    would = hottest
    for r in roles:
        sw, d = r.switch, r.diode
        chips = []
        if sw.total > 0:
            in_doubt = (
                sw.conduction * off("switch conduction", 0.0)
                + sw.turn_on * off("turn-on energy", 0.0)
                + sw.turn_off * off("turn-off energy", 0.0)
                + sw.dead_time * off("reverse conduction", 0.0)
                + sw.recovery * off("recovery energy", 0.0)
            )
            chips.append((r.tj_switch_peak, in_doubt / sw.total))
        if d.total > 0:
            in_doubt = d.conduction * off("diode conduction", 0.0) + d.recovery * off("recovery energy", 0.0)
            chips.append((r.tj_diode_peak, in_doubt / d.total))
        for peak, own in chips:
            would = max(would, peak + min(max(own, stage), 1.0) * (peak - coolest))
    # Reckoned whether or not the stage as a whole is outside its data: a term that is a
    # twentieth of the stage's loss can be most of the hottest chip's.
    worst = (would - hottest) / (hottest - coolest)
    return min(worst, 1.0) if worst >= MINOR_SHARE else 0.0


def _outside(marks: _Notes, roles: list[RoleResult]) -> list[str]:
    """The notes that say the point is outside the data, where together they could move the
    stage's loss by enough to matter. Each counts for its term's share of the loss, times how
    much of the term is in doubt. A table measured at one temperature and used a little way
    from it, or a term that carries next to none of the loss, is still noted and decides
    nothing. The one that could move the loss most comes first."""
    share = _shares(roles)
    weighed = [(share.get(term, 1.0) * doubt, text) for term, text, doubt in marks.outside]
    by_term: dict[str, float] = {}
    for term, _, doubt in marks.outside:
        by_term[term] = max(by_term.get(term, 0.0), share.get(term, 1.0) * doubt)
    if sum(by_term.values()) < MINOR_SHARE:
        return []
    kept = [text for weight, text in weighed if weight >= MINOR_SHARE / 10]
    # Which notes count is settled above. The one read first is the one that could move the
    # loss most: a table used a hair beyond its test voltage does not lead.
    term_of: dict[str, str] = {text: term for term, text, _ in marks.outside}
    return sorted(kept, key=lambda text: -share.get(term_of[text], 1.0) * marks.reach.get(text, 1.0))


def _validity(device: Device, outside: list[str]) -> Validity:
    """How far the data supports the result. What the motor or the stage notes about its own
    model says nothing on that, so only the device's data counts."""
    if outside:
        return Validity.extrapolated
    return Validity.assumed if _uses_point_tables(device) else Validity.interpolated
