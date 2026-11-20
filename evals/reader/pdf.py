"""A PDF written by hand, so that a made-up datasheet needs no library to make and comes
out the same bytes every time.

Only what a datasheet page is made of: lines of text in a plain font, straight strokes and
many-point curves in a colour and a weight, and a grey picture placed on the page. Lengths
are in points and measured from the top-left corner, as a reader of the page thinks of them.
"""

from __future__ import annotations

import zlib
from dataclasses import dataclass, field

A4 = (595.0, 842.0)
# Letters the plain font does not have, and the letter of the Symbol font that draws each.
SYMBOL = {"Ω": "W", "θ": "q", "μ": "m", "≤": "\xa3", "≥": "\xb3"}


def _escaped(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


@dataclass
class Page:
    width: float = A4[0]
    height: float = A4[1]
    ops: list[str] = field(default_factory=list)
    images: list[tuple[str, int, int, bytes]] = field(default_factory=list)

    def text(self, x: float, top: float, words: str, size: float = 9.0) -> None:
        """One line of text with its baseline `size` below `top`."""
        runs: list[tuple[str, str]] = []
        for letter in words:
            font, glyph = ("F2", SYMBOL[letter]) if letter in SYMBOL else ("F1", letter)
            if runs and runs[-1][0] == font:
                runs[-1] = (font, runs[-1][1] + glyph)
            else:
                runs.append((font, glyph))
        shown = " ".join(f"/{font} {size:g} Tf ({_escaped(run)}) Tj" for font, run in runs)
        self.ops.append(f"BT {x:.2f} {self.height - top - size:.2f} Td {shown} ET")

    def stroke(self, points, width: float = 0.5, colour: tuple[float, float, float] = (0, 0, 0)) -> None:
        """A stroke through `points`, each (x, top): a line for two, a curve for more."""
        (x, top), rest = points[0], points[1:]
        path = f"{x:.2f} {self.height - top:.2f} m " + " ".join(f"{x:.2f} {self.height - t:.2f} l" for x, t in rest)
        r, g, b = colour
        self.ops.append(f"{r:g} {g:g} {b:g} RG {width:g} w {path} S")

    def picture(self, x: float, top: float, width: float, height: float, grey: bytes, across: int, down: int) -> None:
        """A grey picture of `across` by `down` pixels, one byte a pixel, placed on the page."""
        name = f"Im{len(self.images) + 1}"
        self.images.append((name, across, down, grey))
        self.ops.append(f"q {width:.2f} 0 0 {height:.2f} {x:.2f} {self.height - top - height:.2f} cm /{name} Do Q")


def write(pages: list[Page], compress: bool = True) -> bytes:
    """The pages as one PDF file."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    def stream(dictionary: str, data: bytes) -> bytes:
        if compress:
            data, dictionary = zlib.compress(data, 9), dictionary + " /Filter /FlateDecode"
        return f"<< {dictionary} /Length {len(data)} >>\nstream\n".encode("latin-1") + data + b"\nendstream"

    catalog, tree = add(b""), add(b"")
    plain = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    # The Symbol font's letters are told to be the Greek ones they draw, as a real datasheet's
    # fonts tell it: without this a reader of the text gets "mW" for a milliohm.
    pairs = "\n".join(f"<{ord(glyph):02X}> <{ord(letter):04X}>" for letter, glyph in SYMBOL.items())
    cmap = (
        "/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CMapName /Greek def /CMapType 2 def\n"
        "1 begincodespacerange <00> <FF> endcodespacerange\n"
        f"{len(SYMBOL)} beginbfchar\n{pairs}\nendbfchar\nendcmap CMapName currentdict /CMap defineresource pop end end"
    )
    greek = add(stream("", cmap.encode()))
    symbol = add(f"<< /Type /Font /Subtype /Type1 /BaseFont /Symbol /ToUnicode {greek} 0 R >>".encode())
    kids = []
    for page in pages:
        pictures = []
        for name, across, down, grey in page.images:
            described = f"/Type /XObject /Subtype /Image /Width {across} /Height {down} /ColorSpace /DeviceGray /BitsPerComponent 8"
            pictures.append(f"/{name} {add(stream(described, grey))} 0 R")
        content = add(stream("", "\n".join(page.ops).encode("cp1252")))
        resources = f"<< /Font << /F1 {plain} 0 R /F2 {symbol} 0 R >> /XObject << {' '.join(pictures)} >> >>"
        kids.append(
            add(
                f"<< /Type /Page /Parent {tree} 0 R /MediaBox [0 0 {page.width:g} {page.height:g}] "
                f"/Resources {resources} /Contents {content} 0 R >>".encode("latin-1")
            )
        )
    objects[catalog - 1] = f"<< /Type /Catalog /Pages {tree} 0 R >>".encode()
    objects[tree - 1] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>".encode()
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
