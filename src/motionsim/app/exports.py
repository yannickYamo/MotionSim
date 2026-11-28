"""Files an agent exports: the design's report as a PDF or Markdown, and a control scheme drawn
as SVG or PDF. Written into MotionSim's folder, under exports/, and served to the page.

The PDF here is plain: the report's text set in a fixed-width face, page after page; and the
scheme as boxes and wires. The page's own Print and Export make the drawn ones; these are for
an agent with no browser. Nothing here needs a library beyond Python's own.
"""

from __future__ import annotations

import re
import textwrap
import time
import zlib
from pathlib import Path
from typing import Any

from motionsim.app.home import made
from motionsim.app.shared import exports

PAGE_W, PAGE_H = 595.0, 842.0  # A4, in points
MARGIN = 48.0
FONT_SIZE = 8.5
LEADING = 11.0
COLUMNS = 104  # characters of Courier at 8.5 pt across the page


def _ascii(text: str) -> str:
    """Text as the PDF's standard face can show it: the few signs the report uses spelled out."""
    swaps = {
        "·": ".",
        "°": " deg",
        "µ": "u",
        "Ω": "Ohm",
        "²": "2",
        "³": "3",
        "→": "->",
        "–": "-",
        "—": "-",
        "≤": "<=",
        "≥": ">=",
        "±": "+/-",
        "×": "x",
        "’": "'",
        "“": '"',
        "”": '"',
        "…": "...",
    }
    for a, b in swaps.items():
        text = text.replace(a, b)
    return text.encode("latin-1", "replace").decode("latin-1")


def _escaped(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


class Pdf:
    """A PDF of pages, each a content stream of drawing operators."""

    def __init__(self) -> None:
        self.pages: list[str] = []

    def add(self, stream: str) -> None:
        self.pages.append(stream)

    def bytes(self) -> bytes:
        objects: list[bytes] = []
        n = len(self.pages)
        # 1 catalog, 2 pages, 3 font regular, 4 font bold, then a page and its content each.
        kids = " ".join(f"{5 + 2 * k} 0 R" for k in range(n))
        objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
        objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier /Encoding /WinAnsiEncoding >>")
        objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        for k, stream in enumerate(self.pages):
            content = zlib.compress(stream.encode("latin-1"))
            objects.append(
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W:g} {PAGE_H:g}] "
                f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> /Contents {6 + 2 * k} 0 R >>".encode()
            )
            objects.append(
                f"<< /Length {len(content)} /Filter /FlateDecode >>\nstream\n".encode() + content + b"\nendstream"
            )
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for k, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{k} 0 obj\n".encode() + body + b"\nendobj\n"
        xref = len(out)
        out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
        for o in offsets:
            out += f"{o:010d} 00000 n \n".encode()
        out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        return bytes(out)


def text_pdf(markdown: str, title: str) -> bytes:
    """The report as plain text pages."""
    lines: list[str] = []
    for raw in markdown.splitlines():
        line = _ascii(re.sub(r"\*\*(.+?)\*\*", r"\1", raw.rstrip()))
        lines.extend(textwrap.wrap(line, COLUMNS, subsequent_indent="  ", break_long_words=True) or [""])
    per_page = int((PAGE_H - 2 * MARGIN - 2 * LEADING) // LEADING)
    pdf = Pdf()
    chunks = [lines[k : k + per_page] for k in range(0, len(lines), per_page)] or [[]]
    for number, chunk in enumerate(chunks, start=1):
        ops = [
            f"BT /F2 9 Tf {MARGIN:g} {PAGE_H - MARGIN + 14:g} Td ({_escaped(_ascii(title))} - page {number} of {len(chunks)}) Tj ET"
        ]
        ops.append(f"BT /F1 {FONT_SIZE:g} Tf {LEADING:g} TL {MARGIN:g} {PAGE_H - MARGIN:g} Td")
        ops += [f"({_escaped(line)}) '" for line in chunk]
        ops.append("ET")
        pdf.add("\n".join(ops))
    return pdf.bytes()


# -- a scheme drawn ---------------------------------------------------------------------------

ROLES = (
    "reference",
    "outer_regulator",
    "reference_generator",
    "inner_regulator",
    "transform_forward",
    "actuation",
    "sensing",
    "transform_feedback",
    "estimation",
    "supervisor",
)
BOX_W, BOX_H, GAP_X, GAP_Y = 150.0, 46.0, 40.0, 22.0


def _layout(scheme: dict, kinds: dict) -> tuple[list[dict], float, float]:
    """Each block placed in a column by its role, in the order the roles flow."""
    columns: dict[int, list[dict]] = {}
    for b in scheme.get("blocks", []):
        role = (kinds.get(b.get("kind"), {}) or {}).get("role", "")
        col = ROLES.index(role) if role in ROLES else len(ROLES)
        columns.setdefault(col, []).append(b)
    placed: list[dict[str, Any]] = []
    for x, col in enumerate(sorted(columns)):
        for y, b in enumerate(columns[col]):
            placed.append({"block": b, "x": 30 + x * (BOX_W + GAP_X), "y": 60 + y * (BOX_H + GAP_Y)})
    width = 60 + max((float(p["x"]) for p in placed), default=0.0) + BOX_W
    height = 90 + max((float(p["y"]) for p in placed), default=0.0) + BOX_H
    return placed, width, height


def _wires(placed: list[dict]) -> list[tuple[dict, dict, str]]:
    at = {p["block"]["name"]: p for p in placed}
    out = []
    for p in placed:
        for port, wire in (p["block"].get("inputs") or {}).items():
            source = str(wire).split(".")[0]
            if source in at and source != p["block"]["name"]:
                out.append((at[source], p, port))
    return out


def _xml(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def scheme_svg(scheme: dict, kinds: dict) -> bytes:
    placed, w, h = _layout(scheme, kinds)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:g}" height="{h:g}" viewBox="0 0 {w:g} {h:g}" '
        'font-family="Helvetica, Arial, sans-serif">',
        f'<rect width="{w:g}" height="{h:g}" fill="#ffffff"/>',
        f'<text x="30" y="30" font-size="15" font-weight="600" fill="#1b1f24">{_xml(scheme.get("label") or scheme.get("id", "scheme"))}</text>',
        '<defs><marker id="a" viewBox="0 0 10 10" refX="10" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
        '<path d="M0 0L10 5L0 10z" fill="#57606a"/></marker></defs>',
    ]
    for a, b, _ in _wires(placed):
        x1, y1 = a["x"] + BOX_W, a["y"] + BOX_H / 2
        x2, y2 = b["x"], b["y"] + BOX_H / 2
        if x2 <= x1:  # a feedback wire: drawn under the boxes, back to the left
            low = max(a["y"], b["y"]) + BOX_H + 10
            parts.append(
                f'<path d="M{x1:g} {y1:g}H{x1 + 12:g}V{low:g}H{x2 - 12:g}V{y2:g}H{x2:g}" fill="none" '
                'stroke="#8c959f" stroke-dasharray="4 3" marker-end="url(#a)"/>'
            )
        else:
            mid = (x1 + x2) / 2
            parts.append(
                f'<path d="M{x1:g} {y1:g}H{mid:g}V{y2:g}H{x2:g}" fill="none" stroke="#57606a" marker-end="url(#a)"/>'
            )
    for p in placed:
        b = p["block"]
        title = (kinds.get(b.get("kind"), {}) or {}).get("title") or b.get("kind", "")
        parts.append(
            f'<rect x="{p["x"]:g}" y="{p["y"]:g}" width="{BOX_W:g}" height="{BOX_H:g}" rx="6" fill="#f6f8fa" stroke="#1b1f24"/>'
            f'<text x="{p["x"] + 10:g}" y="{p["y"] + 19:g}" font-size="12" font-weight="600" fill="#1b1f24">{_xml(b["name"])}</text>'
            f'<text x="{p["x"] + 10:g}" y="{p["y"] + 35:g}" font-size="10" fill="#57606a">{_xml(str(title)[:26])}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts).encode()


def scheme_pdf(scheme: dict, kinds: dict) -> bytes:
    placed, w, h = _layout(scheme, kinds)
    scale = min(1.0, (PAGE_H - 2 * MARGIN) / w, (PAGE_W - 2 * MARGIN) / h)
    # Landscape on A4: the page turned, the drawing laid along its length.
    ops = [f"q 0 1 -1 0 {PAGE_W:g} 0 cm {MARGIN:g} {MARGIN:g} cm {scale:.4f} 0 0 {scale:.4f} 0 0 cm"]

    def y(v: float) -> float:
        return h - v

    ops.append(
        f"BT /F2 15 Tf 30 {y(30):g} Td ({_escaped(_ascii(scheme.get('label') or scheme.get('id', 'scheme')))}) Tj ET"
    )
    ops.append("0.34 0.38 0.42 RG 0.8 w")
    for a, b, _ in _wires(placed):
        x1, y1 = a["x"] + BOX_W, a["y"] + BOX_H / 2
        x2, y2 = b["x"], b["y"] + BOX_H / 2
        if x2 <= x1:
            low = max(a["y"], b["y"]) + BOX_H + 10
            pts = [(x1, y1), (x1 + 12, y1), (x1 + 12, low), (x2 - 12, low), (x2 - 12, y2), (x2, y2)]
            ops.append("[4 3] 0 d")
        else:
            mid = (x1 + x2) / 2
            pts = [(x1, y1), (mid, y1), (mid, y2), (x2, y2)]
            ops.append("[] 0 d")
        ops.append(" ".join(f"{px:g} {y(py):g} {'m' if k == 0 else 'l'}" for k, (px, py) in enumerate(pts)) + " S")
        ops.append(f"[] 0 d {x2 - 6:g} {y(y2) + 3:g} m {x2:g} {y(y2):g} l {x2 - 6:g} {y(y2) - 3:g} l f")
    ops.append("[] 0 d 0.11 0.12 0.14 RG 1 w")
    for p in placed:
        b = p["block"]
        title = (kinds.get(b.get("kind"), {}) or {}).get("title") or b.get("kind", "")
        ops.append(f"0.965 0.973 0.98 rg {p['x']:g} {y(p['y'] + BOX_H):g} {BOX_W:g} {BOX_H:g} re B")
        ops.append(
            f"0.11 0.12 0.14 rg BT /F2 12 Tf {p['x'] + 10:g} {y(p['y'] + 19):g} Td ({_escaped(_ascii(b['name']))}) Tj ET"
        )
        ops.append(
            f"0.34 0.38 0.42 rg BT /F2 10 Tf {p['x'] + 10:g} {y(p['y'] + 35):g} Td ({_escaped(_ascii(str(title)[:26]))}) Tj ET"
        )
    ops.append("Q")
    pdf = Pdf()
    pdf.add("\n".join(ops))
    return pdf.bytes()


def written(stem: str, suffix: str, body: bytes) -> Path:
    """The file, written under exports/ with the time in its name so that none is written over."""
    folder = made(exports())
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip("-")[:60] or "export"
    name = f"{clean}-{time.strftime('%Y%m%d-%H%M%S')}{suffix}"
    target = folder / name
    k = 1
    while target.exists():
        target = folder / f"{clean}-{time.strftime('%Y%m%d-%H%M%S')}-{k}{suffix}"
        k += 1
    target.write_bytes(body)
    return target
