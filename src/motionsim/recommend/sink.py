"""The heatsink: the largest thermal resistance to the air that keeps the hottest junction
under its rating with a margin, and the heatsink itself under its own limit."""

from __future__ import annotations

from collections.abc import Callable

from motionsim.cooling import HEATSINK_LIMIT
from motionsim.device.schema import Device
from motionsim.engine.solver import ThermalRunaway
from motionsim.recommend.base import Recommendation
from motionsim.text import written


def _warmest_sink(junction: Callable[[float], float], limit: float, low: float, high: float) -> tuple[float, bool]:
    """The warmest heatsink between low and high that keeps the junction within its limit,
    and whether that is the top of the span itself."""
    if junction(high) <= limit:
        return high, True
    for _ in range(30):
        middle = (low + high) / 2
        if junction(middle) <= limit:
            low = middle
        else:
            high = middle
        if high - low < 0.1:
            break
    return low, False


def _sink_cap(t_ambient: float, sink_limit: float | None) -> tuple[float, str, Recommendation | None]:
    """The limit on the heatsink's own temperature, what is said where the air is already
    past the usual one, and the refusal where the air is past a limit the user gave."""
    cap = HEATSINK_LIMIT if sink_limit is None else sink_limit
    if cap > t_ambient:
        return cap, "", None
    if sink_limit is not None:
        # A limit the user gave is held to, or said to be out of reach: never dropped.
        return (
            cap,
            "",
            Recommendation(
                "heatsink",
                lines=[
                    f"no heatsink stays at {written(cap, 3)} °C in air at {written(t_ambient, 3)} °C: the air is already "
                    "that warm. Raise the limit on the heatsink, or cool the air"
                ],
            ),
        )
    set_aside = (
        f"the air is already at {written(t_ambient, 3)} °C, so the usual limit of {written(cap, 3)} °C on the "
        "heatsink is set aside: the junction alone decides. What is mounted on the heatsink has to stand it"
    )
    return cap, set_aside, None


def _sink_advice(
    device: Device,
    t_ambient: float,
    margin: float,
    low: float,
    hottest: float,
    loss: float,
    cap: float | None,
    set_aside: str,
) -> Recommendation:
    """The heatsink found, as a recommendation: held by its own limit (cap) or by the junction."""
    topic = "heatsink"
    limit = device.ratings.tj_max - margin
    rth = (low - t_ambient) / loss
    if cap is not None:
        return Recommendation(
            topic,
            {"rth_sink": rth, "t_sink": low, "loss": loss, "sink_limit": cap},
            [
                f"the heatsink is kept at or below {written(cap, 3)} °C, a design target and not a rating, for what is usually mounted on it: the board, the capacitors, "
                f"the connectors. The hottest junction is then at {hottest:.0f} °C, {device.ratings.tj_max - hottest:.0f} K "
                f"under its {written(device.ratings.tj_max, 3)} °C rating",
                f"it then carries {written(loss, 3)} W into {written(t_ambient, 3)} °C air: {written(rth, 2)} K/W or lower, heatsink to ambient",
            ],
        )
    return Recommendation(
        topic,
        {"rth_sink": rth, "t_sink": low, "loss": loss},
        ([set_aside] if set_aside else [])
        + [
            f"the heatsink may reach {low:.0f} °C before the hottest junction passes {limit:g} °C "
            f"({margin:g} K under its {device.ratings.tj_max:g} °C rating)",
            f"it then carries {written(loss, 3)} W into {t_ambient:g} °C air: {written(rth, 2)} K/W or lower, "
            "heatsink to ambient",
        ],
    )


def heatsink(
    device: Device,
    t_ambient: float,
    evaluate: Callable[[float], tuple[float, float]],
    *,
    margin: float = 25.0,
    sink_limit: float | None = None,
) -> Recommendation:
    """Largest heatsink-to-ambient thermal resistance that keeps the hottest junction
    `margin` below its rating, and the heatsink itself no hotter than `sink_limit`
    (cooling.HEATSINK_LIMIT where none is given): what is mounted on a heatsink gives
    out long before a junction does.

    evaluate(t_sink) returns the hottest junction temperature and the loss
    flowing into the heatsink, with the heatsink at t_sink. The hottest
    junction should be the upper end of its range where thermal values are
    assumed.
    """
    topic = "heatsink"
    limit = device.ratings.tj_max - margin

    def junction(t_sink: float) -> float:
        try:
            return evaluate(t_sink)[0]
        except ThermalRunaway:
            return float("inf")

    if junction(t_ambient) > limit:
        return Recommendation(
            topic,
            lines=[
                f"even with the heatsink held at the {t_ambient:g} °C ambient the hottest junction "
                f"is above {limit:g} °C ({margin:g} K under the rating): no heatsink is enough",
            ],
        )
    cap, set_aside, refused = _sink_cap(t_ambient, sink_limit)
    if refused is not None:
        return refused
    capped = cap > t_ambient and cap < device.ratings.tj_max
    low, at_top = _warmest_sink(junction, limit, t_ambient, cap if capped else device.ratings.tj_max)
    hottest, loss = evaluate(low)
    if loss <= 0:
        return Recommendation(topic, lines=["no loss flows into the heatsink at this point"])
    held = cap if at_top and capped else None
    return _sink_advice(device, t_ambient, margin, low, hottest, loss, held, set_aside)
