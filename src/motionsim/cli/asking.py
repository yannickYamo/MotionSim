"""Arguments turned into the request the service takes: the same names and values the page
sends. Only what is particular to a command line is checked here (two flags that say
opposite things); every figure is checked by the service, as it is for everyone."""

from __future__ import annotations

import argparse
import contextlib
import tempfile
from collections.abc import Iterator
from pathlib import Path

from motionsim.errors import Refusal
from motionsim.files import read_record
from motionsim.service.workspace import Workspace, bring_device

EXIT_OF_LEVEL = {"ok": 0, "caution": 0, "fail": 3, "undecided": 4}


@contextlib.contextmanager
def workspace(folder: str | None = None) -> Iterator[Workspace]:
    """A place for the devices a command names, gone when the command is done unless a
    folder was asked for."""
    if folder:
        yield Workspace(Path(folder))
        return
    with tempfile.TemporaryDirectory() as temporary:
        yield Workspace(Path(temporary))


def device(entry: str, ws: Workspace) -> str:
    """A device as named on the command line, by the name it has in the workspace: a file,
    or one of the made-up parts."""
    return bring_device(entry, Path.cwd(), ws)


def _no_heatsink(args: argparse.Namespace) -> bool:
    return any(getattr(args, name, None) not in (None, False) for name in ("rth_ja", "no_heatsink", "board_area"))


def _layer(args: argparse.Namespace, free: bool) -> dict:
    """What lies under a package on a heatsink, where it was said."""
    under = {key: getattr(args, key) for key in ("rth_case_sink", "interface") if getattr(args, key, None) is not None}
    if under and free:
        raise Refusal(
            "--rth-case-sink and --interface say what lies under a package on a heatsink, and --rth-ja, "
            "--no-heatsink or --board-area says there is none",
            "give one or the other",
            "interface",
        )
    return under


def cooling(args: argparse.Namespace) -> dict:
    """The cooling asked for: a heatsink held at --tsink, or cooling to air at --tair
    through a heatsink (--rth-heatsink), with none (--rth-ja, --no-heatsink) or on a board
    (--board-area)."""
    get = lambda name: getattr(args, name, None)  # noqa: E731
    free = _no_heatsink(args)
    if get("rth_heatsink") is not None and free:
        raise Refusal(
            "--rth-heatsink says the devices sit on a heatsink, and --rth-ja, --no-heatsink or --board-area that they do not",
            "give one or the other",
            "cooling",
        )
    if get("copper") is not None and get("board_area") is None:
        raise Refusal("--copper needs --board-area: the packages then share a board", "give --board-area", "copper")
    under = _layer(args, free)
    if get("rth_heatsink") is None and not free:
        if get("tair") is not None:
            raise Refusal(
                "--tair needs the way to the air",
                "give --rth-heatsink (a heatsink's K/W), --rth-ja or --no-heatsink (no heatsink), or --board-area "
                "(parts soldered to one board)",
                "cooling",
            )
        if get("tsink") is None:
            raise Refusal(
                "no cooling is given",
                "give --tsink for a heatsink at a known temperature, or --tair with --rth-heatsink (a heatsink in "
                "air) or --rth-ja (no heatsink)",
                "t_sink",
            )
        return {"cooling": "held", "t_sink": args.tsink, **under}
    if get("tsink") is not None:
        raise Refusal(
            "--tsink is a heatsink at a known temperature, and the other cooling given is to air",
            "give one cooling: --tsink, or --tair with the way to the air",
            "cooling",
        )
    if get("tair") is None:
        raise Refusal("cooling to air needs the air's temperature", "give --tair", "t_ambient")
    if not free:
        return {"cooling": "heatsink", "rth_sink": args.rth_heatsink, "t_ambient": args.tair, **under}
    board = get("board_area") is not None
    return {
        "cooling": "board" if board else "none",
        "t_ambient": args.tair,
        "rth_ja": get("rth_ja"),
        "board_area": get("board_area"),
        "copper": get("copper"),
        "copper_ref": get("copper_ref"),
    }


def conditions(args: argparse.Namespace) -> dict:
    """The supply, switching, gate drive and cooling, by the names the service takes."""
    get = lambda name: getattr(args, name, None)  # noqa: E731
    given = {
        "v_dc": args.vdc,
        "f_sw": args.fsw,
        "pwm": get("pwm"),
        "t_dead": get("tdead"),
        "t_min_pulse": get("tmin"),
        "v_drive": get("vdrive"),
        "rg_on": get("rgon"),
        "rg_off": get("rgoff"),
        "l_loop": get("lloop"),
        "edge_limit": get("edge_limit"),
        "parallel": get("parallel") or 1,
        **cooling(args),
    }
    for name, key in (("m", "m"), ("pf", "pf"), ("fout", "f_out"), ("irms", "i_rms")):
        if get(name) is not None:
            given[key] = get(name)
    for key in ("rpm", "torque"):
        if isinstance(get(key), (int, float)):
            given[key] = get(key)
    return given


def motor(args: argparse.Namespace) -> dict:
    """The motor file's figures, with the winding temperature asked for where one is given."""
    figures = read_record(args.motor, "motor file", "motor")
    hot = getattr(args, "tmotor", None)
    return figures if hot is None else {**figures, "t_motor": hot}


def grid(text: str, name: str) -> list[float]:
    """A range written low:high:count, as the values it stands for."""
    try:
        low, high, count = text.split(":")
        first, last, n = float(low), float(high), int(count)
    except ValueError:
        raise Refusal(
            f"a range is written low:high:count, and {text} was given", "for example 500:3000:6", name
        ) from None
    if not 1 <= n <= 200:
        raise Refusal(f"a range takes 1 to 200 points, and {n} were asked for", "ask for fewer points", name)
    if n == 1:
        return [first]
    return [first + (last - first) * k / (n - 1) for k in range(n)]
