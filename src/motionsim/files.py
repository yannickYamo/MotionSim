"""Files the user hands over, read with care.

A file named on the command line or in a design may be anything: missing, a folder, a
device that never ends, text in another encoding, YAML that does not parse, or a few lines
that stand for millions of figures. Each of those is the user's to put right and is said
in a line, as a refusal. None of them is a traceback, and none is read without end.
"""

from __future__ import annotations

from pathlib import Path

from motionsim.errors import Refusal

# The largest file read as a device, a motor, a load, a design or a measurement. A device
# model with every curve digitised is some tens of kilobytes.
MOST_BYTES = 5 * 1024 * 1024
MOST_FIGURES = 200_000  # names and values a file may stand for, however it is written


def read_bytes(path: str | Path, what: str = "file", field: str = "") -> bytes:
    """What a file holds, where it is a file of a size such a file could be."""
    path = Path(path)
    try:
        with open(path, "rb") as f:
            # One byte more than the most allowed is enough to know it is too large, and is
            # all that is read of a file that has no end.
            data = f.read(MOST_BYTES + 1)
    except OSError as exc:
        raise Refusal(f"cannot read the {what} {path.name}: {exc.strerror or type(exc).__name__}", "", field) from None
    if len(data) > MOST_BYTES:
        raise Refusal(
            f"the {what} {path.name} is larger than {MOST_BYTES // (1024 * 1024)} MB, which no {what} is",
            "check that the right file is named",
            field,
        )
    return data


def read_text(path: str | Path, what: str = "file", field: str = "") -> str:
    try:
        return read_bytes(path, what, field).decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Refusal(f"the {what} {Path(path).name} is not text in UTF-8", "save it as UTF-8 text", field) from None


def plain(data, room: list[int] | None = None):
    """What a file held, once it is known to be of a size a device or a design could be. A
    few lines of YAML can name one list inside another until it stands for millions of
    figures; that is refused before anything tries to read them."""
    room = [MOST_FIGURES] if room is None else room
    room[0] -= 1
    if room[0] < 0:
        raise Refusal("the file stands for far more figures than a device or a design holds")
    for inner in data.values() if isinstance(data, dict) else data if isinstance(data, list) else ():
        plain(inner, room)
    return data


def parse_yaml(text: str, name: str = "the file", what: str = "file", field: str = ""):
    """YAML as plain names and values, or a refusal that says in a line why it is not. JSON
    is read as JSON: YAML 1.1 takes the 2e-05 a program writes for a JSON number as text."""
    import json

    import yaml

    if text.lstrip()[:1] in ("{", "["):
        try:
            return plain(json.loads(text))
        except ValueError:
            pass  # not JSON after all: YAML's flow style, read as YAML below
        except RecursionError:
            raise Refusal(f"the {what} {name} is nested deeper than any {what} is", "", field) from None
    try:
        return plain(yaml.safe_load(text))
    except yaml.YAMLError as exc:
        said = " ".join(str(exc).split())[:160]
        raise Refusal(f"the {what} {name} is not YAML that can be read: {said}", "", field) from None
    except RecursionError:
        raise Refusal(f"the {what} {name} is nested deeper than any {what} is", "", field) from None


def read_yaml(path: str | Path, what: str = "file", field: str = ""):
    return parse_yaml(read_text(path, what, field), Path(path).name, what, field)


def read_record(path: str | Path, what: str = "file", field: str = "") -> dict:
    """A YAML file that has to hold names and values: an empty file, a list or a single
    word is refused as not being one."""
    data = read_yaml(path, what, field)
    if not isinstance(data, dict):
        raise Refusal(
            f"the {what} {Path(path).name} does not hold names and values",
            f"see `motionsim template` for what a {what} holds",
            field,
        )
    return data


def write_text(path: str | Path, text: str, what: str = "file") -> None:
    """Write where the user asked, or say in a line why that cannot be done."""
    try:
        Path(path).write_text(text, encoding="utf-8", newline="")
    except OSError as exc:
        raise Refusal(f"cannot write the {what} {Path(path).name}: {exc.strerror or type(exc).__name__}") from None
