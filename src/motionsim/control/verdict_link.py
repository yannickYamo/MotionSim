"""What a run says of the DC link, where the drive is fed from the mains: whether it stayed
within the device's rating and above what the motor needs, how far it moved on the test's
event, and what the tie between the front end's control and the motor's did for it."""

from __future__ import annotations

from motionsim.text import said as _n

GOOD, IMPROVE, NOTE = "good", "improve", "note"
# The link "holds" within this share of its set point through a test.
HOLDS = 0.05
# A distortion of the mains current worth saying.
DISTORTED = 0.05
# A motor power that moves by this share of its mean within a period of the mains swings.
SWINGS = 0.2

SET_FRONT_END = {"kind": "design", "param": "front_end"}
SET_TIE = {"kind": "design", "param": "fe_link"}
SET_CAPACITOR = {"kind": "design", "param": "c_link"}


def _finding(ident: str, tag: str, severity: int, said: str, lever=None, expect=None, head=None) -> dict:
    return {
        "id": ident,
        "topic": "link",
        "tag": tag,
        "severity": severity,
        "said": said,
        "head": head,
        "lever": lever,
        "expect": expect,
        "change": None,
    }


def _capacitor(link: dict) -> str:
    c = link["c"]
    size = f"{_n(c * 1e6)} µF" if c < 1e-3 else f"{_n(c * 1e3)} mF"
    return f"{size}, sized here" if link.get("c_sized") else size


def _collapsed(link: dict) -> list[dict]:
    return [
        _finding(
            "link_lost",
            IMPROVE,
            5,
            f"the DC link was not held: with a link capacitor of {_capacitor(link)} it left the range the front "
            "end can hold it in, and the rest of the link's run says nothing",
            SET_CAPACITOR,
            "a capacitor that carries the drive through a period of the mains and a step of its load",
            head="the DC link is not held",
        )
    ]


def _over(link: dict) -> list[dict]:
    top, rating = link["v_max"], link.get("v_rating")
    # Braking that charged the link: energy came back, and the link rose past its own movement.
    rose = top > link["v_ref"] + max(link["ripple"], 0.02 * link["v_ref"])
    if rating is None or top <= 0.9 * rating or not (link.get("braked") and rose):
        return []
    past = top > rating
    how = (
        f"past the device's {_n(rating)} V rating" if past else f"within a tenth of the device's {_n(rating)} V rating"
    )
    if link["returns"]:
        lever, expect = SET_CAPACITOR, "a larger capacitor takes the same energy with less rise"
        why = "as the front end's loop gives it back to the mains"
    else:
        lever, expect = SET_FRONT_END, "a front end that gives energy back to the mains holds the link where it is"
        why = f"as {link['name'][0].lower()}{link['name'][1:]} gives nothing back to the mains"
    return [
        _finding(
            "link_over",
            IMPROVE,
            5 if past else 3,
            f"the motor's braking charged the DC link to {_n(top)} V, {how}, {why} (link capacitor {_capacitor(link)})",
            lever,
            expect,
            head=f"braking charges the DC link to {_n(top)} V",
        )
    ]


def _under(link: dict) -> list[dict]:
    low, need, ref = link["v_min"], link.get("need"), link["v_ref"]
    fell = ref - low
    if fell <= HOLDS * ref and (need is None or low >= need):
        return []
    short = need is not None and low < need
    if not link["shapes"] and not short:
        # A rectifier's link follows the crests: its troughs are its ripple, said as that.
        return []
    said = f"the DC link fell from {_n(ref)} V to {_n(low)} V on the test's event"
    # Under what the motor uses of it by more than it fell: the link is too low as it is held.
    head = f"the DC link sags {_n(fell)} V"
    if need is not None and short and fell <= HOLDS * ref:
        head = f"the DC link, {_n(low)} V, is under the {_n(need)} V the motor uses"
    if need is not None and short:
        said += (
            f", under the {_n(need)} V the motor needs at this point: there the current loop runs out of "
            "voltage, which this run of the motor's control, made on a steady link, does not show"
        )
    if link["shapes"] and not link["feed_forward"]:
        said += "; the front end answered only once the voltage had fallen, as nothing told it of the motor's power"
        return [
            _finding(
                "link_sag",
                IMPROVE,
                4 if short else 2,
                said,
                SET_TIE,
                "told what the motor's control is about to draw, the front end raises its power as the load comes on",
                head=head,
            )
        ]
    return [
        _finding(
            "link_sag",
            IMPROVE,
            4 if short else 2,
            said + f" (link capacitor {_capacitor(link)})",
            SET_CAPACITOR if link["shapes"] else SET_FRONT_END,
            "a larger capacitor falls less for the same step"
            if link["shapes"]
            else "a stage that holds the link does not let it follow the load",
            head=head,
        )
    ]


def _held(link: dict) -> list[dict]:
    ref = link["v_ref"]
    span = max(ref - link["v_min"], link["v_max"] - ref)
    if span > HOLDS * ref or not link["shapes"]:
        return []
    tie = (
        ", the front end told of the motor's power as its control asks for it"
        if link["feed_forward"]
        else ", though nothing tells the front end of the motor's power"
    )
    return [
        _finding(
            "link_held",
            GOOD,
            1,
            f"the DC link stayed within {_n(span)} V of its {_n(ref)} V through the test{tie} "
            f"({link['name']}, link capacitor {_capacitor(link)})",
            head=f"the DC link holds within {_n(span)} V",
        )
    ]


def _distorted(link: dict, thd: float) -> dict | None:
    swing, mean = link.get("p_swing") or 0.0, abs(link.get("p_mean") or 0.0)
    swings = swing > SWINGS * max(mean, 1.0)
    if swings and not link["feed_forward"]:
        # A power still moving as the run ends: the last period is a transient, not the current's shape.
        return None
    if swings:
        # Tied, the front end draws what the motor draws as it draws it: a load that swings is
        # passed to the mains, where the capacitor would otherwise have taken it.
        return _finding(
            "link_distortion",
            IMPROVE,
            2,
            f"the motor's power swings {_n(swing)} W through a period of the mains and, the two controls tied, "
            f"the front end draws it as it comes: the mains current is {_n(100 * thd, 2)} % off a sine",
            SET_TIE,
            "each on its own, the link's capacitor takes the swing: the mains current keeps its shape and the "
            "link moves more",
            head=f"the mains current follows the load's swing, {_n(100 * thd, 2)} % off a sine",
        )
    return _finding(
        "link_distortion",
        NOTE,
        1,
        f"the mains current is {_n(100 * thd, 2)} % off a sine with this control: what moves the power asked "
        "for within a period of the mains (the link's loop, the link's ripple, the mains voltage's own "
        "measure) reaches the current's shape",
    )


def _ripple(link: dict) -> list[dict]:
    out = []
    ripple = link["ripple"]
    if link["phases"] == 1 and ripple > 0.01 * link["v_ref"]:
        out.append(
            _finding(
                "link_ripple",
                NOTE,
                1,
                f"the DC link moves {_n(ripple)} V peak to peak at {_n(2 * link['f'])} Hz, twice the mains, "
                f"as one phase gives its power in pulses (link capacitor {_capacitor(link)})",
                SET_CAPACITOR,
                "twice the capacitance halves it",
            )
        )
    thd = link.get("thd")
    if thd is not None and thd > DISTORTED:
        said = _distorted(link, thd)
        out += [said] if said else []
    return out


def link_findings(q: dict) -> list[dict]:
    """The findings on the link of a run fed from the mains; none where it is not."""
    link = q.get("link")
    if not link:
        return []
    if link.get("collapsed"):
        return _collapsed(link)
    return _over(link) + _under(link) + _held(link) + _ripple(link)
