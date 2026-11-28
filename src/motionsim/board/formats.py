"""Telling what kind of file was handed over, and refusing in words the kinds that cannot
give a board's loop: an archive, a solid model, a closed format.

Nothing is ever unpacked to disk. An archive is only listed, to say what it is, with its
members and their sizes counted and a path that leaves the archive refused.
"""

from __future__ import annotations

import gzip
import io
import math
import re
import tarfile
import zipfile
import zlib
from typing import Any

from motionsim.board.model import FIX, MOST_BYTES, MOST_MEMBERS
from motionsim.errors import Refusal

ODB_NOT_YET = "ODB++ is not read yet: export IPC-2581 or give the KiCad file"
MOST_POINTS = 400_000
MOST_STEP = 8 * 1024 * 1024  # characters of a STEP file looked through for its solid's corner points
MOST_NAME = 4096  # bytes of one member's name in an archive: no file system takes a longer one
UNPACKS = 20  # times the largest board file: what an archive may unpack to while it is listed
BLOCK = 512  # a tar archive is written in blocks of this size


class _TooMuch(Exception):
    """An archive that holds more than is listed, said with what it holds too much of."""


def _suffix(name: str) -> str:
    return name.lower().rsplit(".", 1)[-1] if "." in name else ""


class _Limited(io.RawIOBase):
    """A stream that stops at a size: a few kilobytes can be packed to unpack without end."""

    def __init__(self, inner, most: int) -> None:
        self.inner, self.left = inner, most

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        chunk = self.inner.read(len(buffer))
        self.left -= len(chunk)
        if self.left < 0:
            raise _TooMuch("unpacks to more than any board is")
        buffer[: len(chunk)] = chunk
        return len(chunk)


def _zip_members(data: bytes) -> list[str]:
    """The names in a zip archive. Its closing record says how many files it lists and how
    long that list is: both are held to a board's before the list itself is read."""
    end = data.rfind(b"PK\x05\x06", max(len(data) - 65_600, 0))
    if end < 0 or len(data) - end < 22:
        raise zipfile.BadZipFile
    count, listed = (
        int.from_bytes(data[end + 10 : end + 12], "little"),
        int.from_bytes(data[end + 12 : end + 16], "little"),
    )
    # A count or a length of all ones says the true figure is elsewhere: more than is taken.
    if count > MOST_MEMBERS or listed > MOST_MEMBERS * (46 + MOST_NAME // 8):
        raise _TooMuch("holds more files than any board is made of")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) > MOST_MEMBERS:
            raise _TooMuch("holds more files than any board is made of")
        if sum(info.file_size for info in infos) > UNPACKS * MOST_BYTES:
            raise _TooMuch("unpacks to more than any board is")
        if any(len(info.filename) > MOST_NAME for info in infos):
            raise _TooMuch("holds a name longer than any file's")
        return [info.filename for info in infos]


def _field(block: bytes, start: int, length: int) -> str:
    return block[start : start + length].split(b"\0", 1)[0].decode("utf-8", "replace")


def _number(block: bytes, start: int, length: int) -> int:
    """A tar header's number: octal digits, or, with its first bit set, the bytes themselves."""
    raw = block[start : start + length]
    if raw[:1] >= b"\x80":
        return int.from_bytes(raw[1:], "big")
    digits = raw.strip(b" \0")
    return int(digits, 8) if digits else 0


def _skip(stream, count: int) -> None:
    while count > 0:
        got = stream.read(min(count, 1 << 20))
        if not got:
            raise EOFError
        count -= len(got)


def _tar_members(data: bytes) -> list[str]:
    """The names in a tar archive, from its headers alone. No member is read: what a member
    holds is passed over, and a name given as a member of its own (GNU's long name, a pax
    header) is read only while it is as short as a name is."""
    inner: Any = io.BytesIO(data)
    if data[:2] == b"\x1f\x8b":
        inner = gzip.GzipFile(fileobj=inner)
    stream = io.BufferedReader(_Limited(inner, UNPACKS * MOST_BYTES), 1 << 20)
    names: list[str] = []
    named = ""  # the next member's name, where a member before it gave one
    while True:
        block = stream.read(BLOCK)
        if len(block) < BLOCK or not block.strip(b"\0"):
            break  # the end of the archive: a block of zeros, or no block more
        # Every header carries the sum of its own bytes: what does not is no tar archive.
        if sum(block[:148]) + 8 * 32 + sum(block[156:]) != _number(block, 148, 8):
            raise tarfile.ReadError
        size, kind = _number(block, 124, 12), block[156:157]
        held = -(-size // BLOCK) * BLOCK
        if kind in (b"L", b"x"):  # a name too long for a header, given as a member's own content
            if size > MOST_NAME:
                raise _TooMuch("holds a name longer than any file's")
            given = stream.read(held)[:size]
            if kind == b"L":
                named = given.split(b"\0", 1)[0].decode("utf-8", "replace")
            else:  # pax: lines of "length path=name"
                found = [line.partition(b"path=")[2] for line in given.split(b"\n") if b" path=" in line[:24]]
                named = found[-1].decode("utf-8", "replace") if found else named
            continue
        if kind in (b"K", b"g"):  # a long link's target, or settings for the whole archive: not a name
            if size > MOST_NAME:
                raise _TooMuch("holds a name longer than any file's")
            _skip(stream, held)
            continue
        prefix = _field(block, 345, 155) if block[257:262] == b"ustar" else ""
        own = _field(block, 0, 100)
        names.append(named or (f"{prefix}/{own}" if prefix else own))
        named = ""
        if len(names) > MOST_MEMBERS:
            raise _TooMuch("holds more files than any board is made of")
        _skip(stream, held)
    if not names:
        raise tarfile.ReadError
    return names


def _leaves(member: str) -> bool:
    """Whether a member's path points out of its archive."""
    steps = member.replace("\\", "/").split("/")
    return member[:1] in ("/", "\\") or ".." in steps or (len(member) > 1 and member[1] == ":" and member[0].isalpha())


def archive(data: bytes, name: str) -> Refusal:
    """What an archive is refused with: ODB++ by its matrix file, anything else as an
    archive; one that cannot be listed, is too large or holds a path that leaves it, as that."""
    try:
        members = _zip_members(data) if data[:2] == b"PK" else _tar_members(data)
    except _TooMuch as much:
        return Refusal(f"the archive {name} {much}", FIX, "board")
    except (
        zipfile.BadZipFile,
        tarfile.TarError,
        OSError,
        EOFError,
        ValueError,
        RuntimeError,
        NotImplementedError,
        zlib.error,
    ):
        return Refusal(f"the archive {name} cannot be read as a .zip or a .tgz", FIX, "board")
    if any(_leaves(m) for m in members):
        return Refusal(f"the archive {name} holds a path that leaves the archive: it is not unpacked", FIX, "board")
    if any(m == "matrix/matrix" or m.endswith("/matrix/matrix") for m in members):
        return Refusal(ODB_NOT_YET, "in the layout tool, export IPC-2581 (revision B or C) and give that file", "board")
    return Refusal(f"{name} is an archive of {len(members)} files, not a board file", FIX, "board")


# Every pattern here is tried from a fixed word and takes each character at most once more:
# no part of one can give a run of characters to the part after it and take it back, which is
# what makes a pattern walk a long run again and again. Where spaces or text may come between
# two marks, how many is bounded.
_SOLID = re.compile(r"=\s{0,64}(?:MANIFOLD_SOLID_BREP|BREP_WITH_VOIDS)\s{0,64}\(")
_MILLIMETRES = re.compile(r"SI_UNIT\s{0,64}\(\s{0,64}\.MILLI\.\s{0,64},\s{0,64}\.METRE\.\s{0,64}\)")
_METRES = re.compile(r"SI_UNIT\s{0,64}\(\s{0,64}\$\s{0,64},\s{0,64}\.METRE\.\s{0,64}\)")
# A point's three figures are taken as the text between its inner brackets, at most 200
# characters of it, and turned into numbers by float, not by a pattern.
_POINT = re.compile(r"CARTESIAN_POINT\s{0,64}\(\s{0,64}'[^']{0,200}'\s{0,64},\s{0,64}\(([^()]{0,200})\)")


def _point(inner: str) -> tuple[float, float, float] | None:
    parts = inner.split(",")
    if len(parts) != 3:
        return None
    try:
        x, y, z = (float(part) for part in parts)
    except ValueError:
        return None
    return (x, y, z) if all(math.isfinite(v) for v in (x, y, z)) else None


def step_size(text: str) -> tuple[float, float, float] | None:
    """The box round a STEP file's one solid, mm, longest side first: only where the file
    holds one solid, no assembly and lengths in millimetres or metres, so that its points
    are all the solid's own. A round shape's box is understated: its points are on its axis.
    None too for a file longer than is looked through: a box from some of its points only
    would be a wrong one."""
    if len(text) > MOST_STEP:
        return None
    solids = len(_SOLID.findall(text))
    if solids != 1 or "NEXT_ASSEMBLY_USAGE_OCCURRENCE" in text or "ITEM_DEFINED_TRANSFORMATION" in text:
        return None
    if _MILLIMETRES.search(text):
        scale = 1.0
    elif _METRES.search(text):
        scale = 1000.0
    else:
        return None
    low, high, count = [float("inf")] * 3, [float("-inf")] * 3, 0
    for match in _POINT.finditer(text):
        point = _point(match.group(1))
        if point is None:
            continue
        count += 1
        if count > MOST_POINTS:
            return None
        for k in range(3):
            low[k], high[k] = min(low[k], point[k]), max(high[k], point[k])
    if count < 4:
        return None
    sides = sorted(((h - l) * scale for l, h in zip(low, high, strict=True)), reverse=True)
    return (sides[0], sides[1], sides[2]) if all(0 <= s < 1e5 for s in sides) and sides[0] > 0 else None


def _step(text: str, name: str) -> Refusal:
    size = step_size(text)
    about = ""
    if size:
        about = (
            f" (its one solid is about {size[0]:.3g} × {size[1]:.3g} × {size[2]:.3g} mm by its corner points: "
            "geometry only, of use for a heatsink's or a busbar's size)"
        )
    return Refusal(
        f"{name} is a STEP file: it holds shapes and no nets, so no loop inductance can honestly be read from it{about}",
        FIX,
        "board",
    )


def _text(data: bytes, name: str) -> str:
    try:
        if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
            return data.decode("utf-16")
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise Refusal(
            f"the board file {name} is not text in UTF-8, and is no kind of board file known here", FIX, "board"
        ) from None


def recognise(data: bytes, name: str) -> tuple[str, str]:
    """The kind of board file ("kicad" or "ipc2581") and its text, or the refusal its kind is given."""
    if len(data) > MOST_BYTES:
        raise Refusal(
            f"the board file {name} is larger than {MOST_BYTES // (1024 * 1024)} MB, which is more than is read",
            "give the board of the power stage alone",
            "board",
        )
    if not data.strip():
        raise Refusal(f"the board file {name} is empty", FIX, "board")
    suffix = _suffix(name)
    if data[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" or suffix in ("pcbdoc", "schdoc", "prjpcb"):
        raise Refusal(
            f"{name} is Altium's own format, which is closed and not read",
            "in Altium, export IPC-2581 (File > Fabrication Outputs) or ODB++, and give the IPC-2581 file",
            "board",
        )
    if data[:2] in (b"PK", b"\x1f\x8b") or data[257:262] == b"ustar" or suffix in ("zip", "tgz", "tar", "gz"):
        raise archive(data, name)
    text = _text(data, name)
    start = text[:4096].lstrip()
    if start.startswith("ISO-10303-21") or suffix in ("step", "stp"):
        raise _step(text, name)
    if start.startswith("(") or suffix == "kicad_pcb":
        return "kicad", text
    if start.startswith("<"):
        return "ipc2581", text
    raise Refusal(f"{name} is not a board file of a kind read here", FIX, "board")
