"""A board file made to cost the reader its time or its memory: each is refused in words, in
a process held to a gigabyte, within seconds. The files are made here, never kept: a few
kilobytes that unpack to gigabytes, text that makes a careless pattern walk it again and
again, brackets and names without end."""

from __future__ import annotations

import gzip
import io
import os
import re
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path

import pytest

from motionsim import board
from motionsim.board import formats, sexpr
from motionsim.errors import Refusal

pytestmark = pytest.mark.timeout(240)

BOARDS = Path(__file__).parent / "fixtures" / "boards"
M = 1 << 20
MEMORY = 1 << 30  # bytes of address space the reading process may have
SECONDS = 5.0  # of the processor's time for the read itself, from the bytes to the refusal

STEP_HEAD = "ISO-10303-21;\n#1=MANIFOLD_SOLID_BREP('',#2);\nSI_UNIT(.MILLI.,.METRE.)\n"


def half_bridge() -> str:
    return (BOARDS / "half_bridge.kicad_pcb").read_text(encoding="utf-8")


def half_bridge_xml() -> str:
    return (BOARDS / "half_bridge.xml").read_text(encoding="utf-8")


def segments(count: int) -> str:
    """The half bridge with this many more track segments on a signal net of their own."""
    more = "".join(
        f'  (segment (start {i % 200} {i // 200}) (end {i % 200 + 0.5} {i // 200}) (width 0.2) (layer "B.Cu") (net 4))\n'
        for i in range(count)
    )
    return half_bridge().rstrip()[:-1] + more + ")"


def zipped(members: dict[str, bytes], how: int = zipfile.ZIP_DEFLATED) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", how) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return out.getvalue()


def many_in_a_zip(count: int) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as archive:
        for n in range(count):
            archive.writestr(f"f{n}", "")
    return out.getvalue()


class Zeros(io.RawIOBase):
    """So many zero bytes, never held at once."""

    def __init__(self, count: int) -> None:
        self.left = count

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        n = min(len(buffer), self.left)
        buffer[:n] = b"\0" * n
        self.left -= n
        return n


def tar_of_one_huge_member(size: int) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz", compresslevel=9) as archive:
        info = tarfile.TarInfo("big")
        info.size = size
        archive.addfile(info, io.BufferedReader(Zeros(size)))
    return out.getvalue()


def tar_with_a_name_of(size: int) -> bytes:
    """A GNU "long name" member: the next member's name, given as this member's content, and
    here half a gigabyte of it in half a megabyte of file."""
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", compresslevel=9) as packed:
        info = tarfile.TarInfo("././@LongLink")
        info.type = tarfile.GNUTYPE_LONGNAME
        info.size = size
        packed.write(info.tobuf(format=tarfile.GNU_FORMAT))
        for _ in range(size // M):
            packed.write(b"a" * M)
        packed.write(b"\0" * ((512 - size % 512) % 512))
        packed.write(tarfile.TarInfo("x").tobuf(format=tarfile.GNU_FORMAT))
        packed.write(b"\0" * 1024)
    return out.getvalue()


def tar_of_many(count: int) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        for n in range(count):
            archive.addfile(tarfile.TarInfo(f"f{n}"))
    return out.getvalue()


def tar_of(name: str) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as archive:
        info = tarfile.TarInfo(name)
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))
    return out.getvalue()


def late_doctype(rest: str) -> str:
    """A document type declared a megabyte into the file, behind a comment."""
    return '<?xml version="1.0"?><!--' + "c" * (M + 10) + "-->" + rest


# Each: the file's name, what makes it, and words its refusal must hold.
HOSTILE = {
    # XML: entities that stand for more, addresses outside the file, and sheer size.
    "laughs.xml": (
        lambda: (
            '<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "ha"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
            '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]><IPC-2581>&c;</IPC-2581>'
        ),
        "a document type or an entity",
    ),
    "outside_entity.xml": (
        lambda: (
            '<?xml version="1.0"?><!DOCTYPE l [<!ENTITY x SYSTEM "file:///etc/passwd">]><IPC-2581 a="1">&x;</IPC-2581>'
        ),
        "a document type or an entity",
    ),
    "doctype_late.xml": (
        lambda: late_doctype(
            '<!DOCTYPE IPC-2581 SYSTEM "http://127.0.0.1:4589/evil.dtd"><IPC-2581>&undefined;</IPC-2581>'
        ),
        "a document type or an entity",
    ),
    "doctype_late_attlist.xml": (
        lambda: late_doctype(
            '<!DOCTYPE IPC-2581 [<!ATTLIST IPC-2581 units CDATA "MILS">]>'
            + half_bridge_xml()[half_bridge_xml().index("<IPC-2581") :]
        ),
        "a document type or an entity",
    ),
    "xinclude.xml": (
        lambda: (
            '<?xml version="1.0"?><IPC-2581 xmlns:xi="http://www.w3.org/2001/XInclude">'
            '<xi:include href="file:///etc/passwd" parse="text"/></IPC-2581>'
        ),
        "no half bridge was found",
    ),
    "utf16_entity.xml": (
        lambda: '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE l [<!ENTITY a "ha">]><IPC-2581>&a;</IPC-2581>'.encode(
            "utf-16"
        ),
        "a document type or an entity",
    ),
    "huge_attribute.xml": (lambda: '<IPC-2581 a="' + "A" * (28 * M) + '"></IPC-2581>', "no half bridge was found"),
    "deep.xml": (lambda: "<IPC-2581>" + "<a>" * 300_000 + "</a>" * 300_000 + "</IPC-2581>", "nested more than"),
    "deep_never_closed.xml": (lambda: "<IPC-2581>" + "<a>" * (9 * M), "nested more than"),
    "many_elements.xml": (
        lambda: "<IPC-2581>" + "<a/>" * (7 * M) + "</IPC-2581>",
        "holds more than 1 500 000 elements",
    ),
    "many_attributes.xml": (
        lambda: "<IPC-2581 " + " ".join(f'a{n}="1"' for n in range(1_500_000)) + "/>",
        "holds more than 256 attributes",
    ),
    "text.xml": (lambda: "<IPC-2581>" + "t" * (29 * M) + "</IPC-2581>", "no half bridge was found"),
    # KiCad's brackets: never closed, never ended, without end.
    "deep.kicad_pcb": (lambda: "(" * (5 * M), "deep"),
    "atom.kicad_pcb": (lambda: "(kicad_pcb " + "a" * (29 * M) + ")", "no half bridge was found"),
    "quote_never_closed.kicad_pcb": (lambda: '(kicad_pcb "' + "a" * (29 * M), "a quoted text is never closed"),
    "quote_closed.kicad_pcb": (lambda: '(kicad_pcb "' + "a" * (29 * M) + '")', "no half bridge was found"),
    "quote_of_escapes.kicad_pcb": (lambda: '(kicad_pcb "' + "\\a" * (14 * M), "a quoted text is never closed"),
    "quote_of_escaped_quotes.kicad_pcb": (lambda: '(kicad_pcb "' + '\\"' * (14 * M), "a quoted text is never closed"),
    "many_quotes.kicad_pcb": (lambda: "(kicad_pcb " + '"" ' * (9 * M) + ")", "brackets and values"),
    "cut_short.kicad_pcb": (lambda: half_bridge().rstrip()[:-1], "a bracket is never closed"),
    "one_bracket_more.kicad_pcb": (lambda: half_bridge() + ")", "a bracket closes that was never opened"),
    "blank.kicad_pcb": (lambda: " " * (29 * M) + "(kicad_pcb)", "no half bridge was found"),
    # Archives: more inside than outside, names that leave, names without end.
    "bomb.zip": (lambda: zipped({"big.bin": b"\0" * (1024 * M)}), "unpacks to more than any board is"),
    "many.zip": (lambda: many_in_a_zip(250_000), "holds more files than any board is made of"),
    "leaves.zip": (
        lambda: zipped({"../../../../tmp/evil.txt": b"x", "odb/matrix/matrix": b"x"}, zipfile.ZIP_STORED),
        "a path that leaves the archive",
    ),
    "odb.zip": (lambda: zipped({"job/matrix/matrix": b"x"}, zipfile.ZIP_STORED), "ODB++ is not read yet"),
    "odb.tgz": (lambda: tar_of("job/matrix/matrix"), "ODB++ is not read yet"),
    "huge_member.tgz": (lambda: tar_of_one_huge_member(3 * 1024 * M), "unpacks to more than any board is"),
    "long_name.tgz": (lambda: tar_with_a_name_of(500 * M), "a name longer than any file's"),
    "many.tgz": (lambda: tar_of_many(100_000), "holds more files than any board is made of"),
    "not_a.zip": (lambda: b"PK\x03\x04" + os.urandom(1000), "cannot be read as a .zip or a .tgz"),
    "garbage.gz": (lambda: b"\x1f\x8b" + os.urandom(1000), "cannot be read as a .zip or a .tgz"),
    # STEP: points without end, and digits a pattern could walk over and over.
    "many_points.step": (lambda: STEP_HEAD + "#9=CARTESIAN_POINT('',(1.0,2.0,3.0));\n" * 700_000, "is a STEP file"),
    "digits.step": (
        lambda: (
            STEP_HEAD
            + "CARTESIAN_POINT('',(1"
            + "1" * (2 * M)
            + "\n"
            + "CARTESIAN_POINT ( '"
            + "a" * 199
            + "x" * 100
            + "\n"
        ),
        "is a STEP file",
    ),
    "digits_many_times.step": (
        lambda: STEP_HEAD + ("CARTESIAN_POINT('',(1" + "1" * 3000 + " ") * 8000,
        "is a STEP file",
    ),
    "closed_format.PcbDoc": (lambda: b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100, "closed and not read"),
}

# Run with the file's path and its name: the read alone is timed, in a process that may not
# have more than MEMORY of address space. One line comes back: the seconds, then what happened.
# The seconds are the processor's time the read took, not those on the clock: with every
# test of the suite running at once there are some fifty processes ready for twelve threads,
# and a read of half a second took eight on the clock.
CHILD = f"""
import resource, sys, time
resource.setrlimit(resource.RLIMIT_AS, ({MEMORY}, {MEMORY}))
from motionsim import board
from motionsim.errors import Refusal
with open(sys.argv[1], "rb") as f:
    data = f.read()
start = time.process_time()
try:
    board.read(data, sys.argv[2])
    said = "read"
except Refusal as refusal:
    said = "refused: " + refusal.reason
except MemoryError:
    said = "out of memory"
print(f"{{time.process_time() - start:.3f}}|{{said}}")
"""


def read_held(path: Path, name: str) -> tuple[float, str]:
    """The processor's seconds a read took and how it ended, in a process held to MEMORY."""
    # One thread for the arithmetic: each thread of it would ask for address space of its own.
    env = {**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}
    done = subprocess.run(
        [sys.executable, "-c", CHILD, str(path), name], capture_output=True, text=True, timeout=120, env=env
    )
    assert done.returncode == 0, done.stderr[-2000:]
    seconds, _, said = done.stdout.strip().partition("|")
    return float(seconds), said


@pytest.mark.skipif(sys.platform == "win32", reason="a process's memory is held with resource, which Windows lacks")
@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_a_file_made_to_cost_time_or_memory_is_refused_in_words_at_once(name, tmp_path) -> None:
    make, words = HOSTILE[name]
    made = make()
    path = tmp_path / name
    path.write_bytes(made if isinstance(made, bytes) else made.encode("utf-8"))
    del made
    seconds, said = read_held(path, name)
    assert said.startswith("refused: ") and words in said, said
    assert seconds < SECONDS, f"{seconds} s: {said}"


def test_two_hundred_thousand_digits_in_a_step_file_are_answered_within_a_second() -> None:
    """A number's pattern that lets two of its parts share a run of digits tries every way of
    sharing them: a quarter of a megabyte then takes minutes, with every other request waiting."""
    text = STEP_HEAD + "CARTESIAN_POINT('',(1" + "1" * 200_000 + "\n"
    start = time.process_time()
    assert formats.step_size(text) is None
    with pytest.raises(Refusal, match="is a STEP file"):
        board.read(text.encode(), "part.step")
    assert time.process_time() - start < 1.0


def test_a_step_files_box_is_still_read_from_its_points() -> None:
    points = [(0, 0, 0), (10.5, 0, 0), (10.5, 4, 0), (0, 4, -2e0), (+1, 0.5, 1e-1)]
    text = STEP_HEAD + "".join(
        f"#{n}=CARTESIAN_POINT ( 'p{n}' , ( {x}, {y} ,{z} ) );\n" for n, (x, y, z) in enumerate(points)
    )
    assert formats.step_size(text) == pytest.approx((10.5, 4.0, 2.1))
    # In metres, the same box a thousand times the size; with two solids, none.
    assert formats.step_size(text.replace(".MILLI.", "$")) == pytest.approx((10500.0, 4000.0, 2100.0))
    assert formats.step_size(text + "#99=MANIFOLD_SOLID_BREP('',#2);\n") is None


def test_a_quoted_text_is_read_with_what_it_escapes() -> None:
    """Scanned without trying each character two ways: a quote behind a backslash is the
    text's own, a backslash behind a backslash is one backslash and ends nothing."""
    assert sexpr.parse(r'(a "b \"c\" d" "" "e\\" f "(g)" "h' + "\n" + 'i")') == [
        "a",
        'b "c" d',
        "",
        "e\\\\",
        "f",
        "(g)",
        "h\ni",
    ]
    for cut in ('(a "b', '(a "b\\"', '(a "b\\\\\\"'):
        with pytest.raises(Refusal, match="a quoted text is never closed"):
            sexpr.parse(cut)


def test_text_of_megabytes_between_two_brackets_is_read_as_it_is() -> None:
    long = "a" * (3 * M)
    assert sexpr.parse(f'(kicad_pcb "{long}" {long}\n' + " " * (2 * M) + f'(net 1 "{long}"))') == [
        "kicad_pcb",
        long,
        long,
        ["net", "1", long],
    ]


def board_patterns() -> list[tuple[str, re.Pattern]]:
    """Every pattern the board's readers keep, by where it is kept."""
    from motionsim.board import bridge, drive, ipc2581, values

    found = []
    for module in (formats, sexpr, ipc2581, values, bridge, drive):
        for key, value in vars(module).items():
            if isinstance(value, re.Pattern):
                found.append((f"{module.__name__}.{key}", value))
    found += [(f"values.PACKAGES[{n}]", re.compile(p, re.IGNORECASE)) for n, (p, *_) in enumerate(values.PACKAGES)]
    return found


# Runs a careless pattern walks again and again: one character, two in turn, a number and its
# separators, a quote and its escapes, an opening tag's attributes, a point's figures.
RUNS = [
    "1" * 200_000,
    " " * 200_000,
    "a" * 200_000,
    "1." * 100_000,
    '"' * 200_000,
    "\\" * 200_000,
    '\\"' * 100_000,
    "<a " + 'b="1" ' * 40_000,
    "CARTESIAN_POINT('',(" + "1," * 100_000,
    "SI_UNIT(" + " " * 200_000,
    "100n" * 50_000,
]


# Patterns only ever tried at one place, never searched for: a quoted text from its opening
# quote, a word from its first character, a value from its start.
ANCHORED = {"motionsim.board.sexpr._WHOLE", "motionsim.board.sexpr._WORD", "motionsim.board.values._OHMS"}


@pytest.mark.parametrize("label, pattern", board_patterns(), ids=lambda v: v if isinstance(v, str) else "")
def test_every_pattern_of_the_board_readers_walks_a_long_run_once(label, pattern) -> None:
    for run in RUNS:
        start = time.process_time()
        if label in ANCHORED:
            for at in range(8):
                pattern.match(run, at)
        else:
            pattern.search(run)
            pattern.findall(run[:50_000])
        assert time.process_time() - start < 0.5, f"{label} on {run[:12]!r}…"


class Walked:
    """A pattern that counts the characters it is asked to take apart."""

    def __init__(self, pattern: re.Pattern) -> None:
        self.pattern, self.walked = pattern, 0

    def findall(self, text: str, start: int, end: int) -> list:
        self.walked += end - start
        return self.pattern.findall(text, start, end)


@pytest.mark.parametrize(
    "text",
    [
        "(kicad_pcb " + "a" * (8 * M) + ")",
        '(kicad_pcb "' + "a" * (8 * M) + '")',
        '(kicad_pcb "' + '\\"' * (4 * M) + '" b)',
        "(kicad_pcb " + " " * (8 * M) + "b)",
    ],
    ids=["word", "quoted", "escapes", "spaces"],
)
def test_a_kicad_file_is_taken_apart_in_one_walk_however_long_its_words(text, monkeypatch) -> None:
    """A word longer than a stretch was read again with a stretch twice as long, and again,
    and the whole file twice over, once to count it: a word of 29 MB was walked some sixty
    times its length and took seconds."""
    walked = Walked(sexpr._TOKENS)
    monkeypatch.setattr(sexpr, "_TOKENS", walked)
    sexpr.parse(text)
    # A file that may hold more values than are taken is counted in a walk of its own first.
    walks = 2 if sexpr._most_values(text) > sexpr.MOST_VALUES else 1
    assert walked.walked <= walks * (len(text) + sexpr.STRETCH)
