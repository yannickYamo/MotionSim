"""Where MotionSim keeps what it keeps on this machine: one folder, the user's own.

MOTIONSIM_HOME names it where that is set, as it is in a container, where the folder is a
mounted volume. Otherwise it is `.motionsim` in the user's home folder, which is where the
device files have always been kept.
"""

from __future__ import annotations

import os
from pathlib import Path

HOME = "MOTIONSIM_HOME"


def home() -> Path:
    """The folder, read from the environment each time it is asked for. Not made here:
    whoever writes into it makes it."""
    given = os.environ.get(HOME, "").strip()
    return Path(given).expanduser() if given else Path.home() / ".motionsim"


def devices() -> Path:
    """The folder of device files, where none is named on the command line."""
    return home() / "devices"


def made(folder: Path) -> Path:
    """The folder, made if it is not there, and the user's alone where it is made here: it
    holds a key."""
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder
