"""The example files that come with the tool: where they are, and one found by its bare name.

Installed from a wheel they are inside the package, at motionsim/examples. Installed from a
clone in place, they are the clone's own examples folder. Either way a command takes
`motor_robot_joint_pmsm.yaml` as it is, from wherever it is run: someone who installed with
pip has no folder of the repository to point into.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

IN_PACKAGE = Path(__file__).parent / "examples"
IN_CLONE = Path(__file__).resolve().parents[2] / "examples"

# What each file is, by the start of its name.
KINDS = (
    ("synthetic_", "device"),
    ("motor_", "motor"),
    ("load_", "load"),
    ("profile_", "profile"),
    ("double_pulse_", "measurement"),
)


def folder() -> Path | None:
    """Where the example files are, or None in an install that has none."""
    for place in (IN_PACKAGE, IN_CLONE):
        if place.is_dir():
            return place
    return None


def _about(path: Path) -> str:
    """The file's own first line on itself: its leading comment, or a JSON file's note."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""
    if path.suffix == ".json":
        try:
            note = json.loads(text).get("note", "")
        except (ValueError, AttributeError):
            return ""
        return str(note)
    first = text.lstrip().splitlines()[0] if text.strip() else ""
    return first.removeprefix("#").strip() if first.startswith("#") else ""


def listed() -> list[dict]:
    """Each example file: its name, what it is, where it is and its first line on itself."""
    place = folder()
    if place is None:
        return []
    return [
        {
            "name": path.name,
            "kind": next((kind for start, kind in KINDS if path.name.startswith(start)), "file"),
            "path": str(path.resolve()),
            "about": _about(path),
        }
        for path in sorted(place.iterdir())
        if path.is_file()
    ]


def resolved(text: str) -> str:
    """The file a command was given: as given where there is such a file, or where it names a
    folder; otherwise the example of that bare name, where there is one. A user's own file of
    that name comes first."""
    if os.path.exists(text) or os.sep in text or (os.altsep and os.altsep in text):
        return text
    place = folder()
    if place is not None and (place / text).is_file():
        return str(place / text)
    return text
