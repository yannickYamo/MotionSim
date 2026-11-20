"""An answer of the service, printed for a person at a terminal. Only formatting: every
figure printed here was worked out by the service and is in its answer."""

from __future__ import annotations

import json

from motionsim.engine.notes import Code, code_of

WORD = {"ok": "ok", "caution": "CAUTION", "undecided": "UNDECIDED", "fail": "FAIL"}
ORDER = ("ok", "caution", "undecided", "fail")


def as_json(answer: dict) -> None:
    from motionsim.service.answers import finite

    print(json.dumps(finite(answer), indent=1, ensure_ascii=False, default=float))


def level(checks: list[dict]) -> str:
    return max((c["level"] for c in checks), key=ORDER.index, default="ok")


def checks(found: list[dict], indent: str = "  ") -> None:
    print(f"{indent}checks: {WORD[level(found)]}")
    for c in found:
        print(f"{indent}  [{WORD[c['level']]:>7}] {c['topic']}: {c['message']}")


def title(device: dict) -> str:
    return f"{device['name']} ({device['technology']})"


def _losses(device: dict, r: dict) -> None:
    h = r["hottest"]
    print(f"  switch   conduction {h['conduction']:8.3f} W")
    print(f"           turn-on    {h['turn_on']:8.3f} W")
    print(f"           turn-off   {h['turn_off']:8.3f} W")
    if device["kind"] == "mosfet":
        print(f"           dead time  {h['dead_time']:8.3f} W")
        if device["recovery"]:
            print(f"           recovery   {h['recovery']:8.3f} W")
    else:
        print(f"  diode    conduction {h['diode_conduction']:8.3f} W")
        print(f"           recovery   {h['diode_recovery']:8.3f} W")
    print(f"  power-stage loss    {r['loss']:8.2f} W")
    if r["efficiency"] is not None:
        print(f"  efficiency          {100 * r['efficiency']:8.2f} %")


def _temperatures(device: dict, r: dict) -> None:
    assumed = " (assumed response)" if r["peak_basis"] == "assumed" else ""
    print(f"  Tj switch  average  {r['tj_switch']:8.1f} °C   peak {r['tj_switch_peak']:6.1f} °C{assumed}")
    if device["kind"] != "mosfet":
        print(f"  Tj diode   average  {r['tj_diode']:8.1f} °C   peak {r['tj_diode_peak']:6.1f} °C{assumed}")
    print(f"  T case              {r['t_case']:8.1f} °C")
    # The margin is to the top of the range, as every other answer counts it.
    top = max(r["tj_switch_peak"], r["tj_diode_peak"], *(r["tj_range"] or ()))
    print(f"  margin to Tj max    {device['tj_max'] - top:8.1f} °C")
    if r["tj_range"] is not None:
        low, high = r["tj_range"]
        print(f"  hottest junction    {low:8.1f} to {high:.1f} °C across the thermal assumptions")
        for line in r["assumptions"]:
            print(f"    - {line}")


def result(device: dict, r: dict) -> None:
    """One result: the losses of the hottest position, the temperatures, and what the
    figures rest on."""
    _losses(device, r)
    _temperatures(device, r)
    print(f"  data support        {r['validity']}")
    for note in r["notes"]:
        print(f"    - {note}")
    if len(r["positions"]) > 1:
        print("  by position (the figures above are for the hottest)")
        for x in r["positions"]:
            print(f"    - {x['count']} x {x['name']}: {x['total']:.3f} W each, peak {x['tj']:.1f} °C")
    if r["limits"]:  # a heading with nothing under it says nothing
        print("  not modelled")
        for limit in r["limits"]:
            print(f"    - {limit}")
    if r["warnings"]:
        print("  rating warnings")
        for warning in r["warnings"]:
            print(f"    - {warning}")


def taken(lines: list[str]) -> None:
    """What was filled in for the user, said before the answer that rests on it."""
    for line in lines:
        code = code_of(line)
        if code is Code.junction_to_air_taken:
            print(line)
        elif code in (Code.dead_time_taken, Code.dead_time_estimated):
            print(f"{line} (--tdead)")


def recommendation(item: dict) -> None:
    print(item["topic"])
    for line in item["lines"]:
        print(f"  - {line}")


def table(title_: str, values, answer: dict, fmt: str, scale: float = 1.0) -> None:
    """One grid of a speed-torque map: '-' where the motor cannot be, '*' above the rating."""
    rpm, torque, limit = answer["rpm"], answer["torque"], answer["tj_max"]
    print(title_)
    corner = "N·m \\ rpm"
    print(f"{corner:>10}" + "".join(f"{n:9.0f}" for n in rpm))
    for a in reversed(range(len(torque))):
        cells = ""
        for b in range(len(rpm)):
            v = values[a][b]
            if v is None:
                cells += f"{'-':>9}"
            else:
                mark = "*" if (answer["tj"][a][b] or 0) > limit else " "
                cells += f"{format(scale * v, fmt):>8}{mark}"
        print(f"{torque[a]:10.2f}{cells}")
    print()
