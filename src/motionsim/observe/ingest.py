"""A PDF, opened: the text of its pages and pictures of them.

A datasheet comes from anywhere, so the file is not trusted. A file that is not a PDF, or
is a damaged one, is refused in words. A file built to exhaust the machine that opens it (a
small compressed stream that unpacks to gigabytes, a page the size of a building) is held to
limits set here: refused where that is the only safe answer, drawn smaller where that will do.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
import zlib
from pathlib import Path

from motionsim.observe import provider
from motionsim.observe.schema import Document

MAX_FILE = 100_000_000  # bytes; a long datasheet with photographs is ten or twenty megabytes
MAX_PAGES = 80  # a long module datasheet has forty
MAX_STREAM = 32_000_000  # bytes one compressed stream of text or drawing may unpack to; a full page is under one
MAX_IMAGE_STREAM = 256_000_000  # the same for a picture: a colour scan of a page at 600 dpi is about 100 MB
MAX_UNPACKED = 512_000_000  # bytes all the compressed streams of a file may unpack to together
MAX_PIXELS = 12_000_000  # of a rendered page; an A4 page at the usual scale of 2 is two million
MAX_SECONDS = 120.0  # to get the text out of every page; a real datasheet takes a few seconds

NOT_A_PDF = "that file is not a PDF"


def _refused(why: str) -> provider.ReaderFailed:
    return provider.ReaderFailed(why, "check that the file is the datasheet's own PDF, as its maker publishes it")


_STREAM = re.compile(rb"stream\r?\n")
_IMAGE = re.compile(rb"/Subtype\s*/Image")


def _unpacked(packed: bytes, limit: int) -> int:
    """Bytes a deflated stream unpacks to, counted a piece at a time and no further than
    just past `limit`, so that measuring a bomb does not set it off. 0 for what is not
    deflate at all."""
    unpacker = zlib.decompressobj()
    size, rest = 0, packed
    try:
        while size <= limit and not unpacker.eof:
            piece = unpacker.decompress(rest, 1 << 20)
            if not piece and len(unpacker.unconsumed_tail) == len(rest):
                break  # nothing came out and nothing went in: the stream stops short
            size, rest = size + len(piece), unpacker.unconsumed_tail
    except zlib.error:
        pass  # not deflate, or damaged part-way: what came out before is what it unpacks to
    return size


def check_streams(data: bytes) -> None:
    """Refuse a file whose compressed streams unpack to more than a datasheet's could.

    Every stream of a PDF stands in the file itself, never inside another, so each can be
    found and measured before any PDF library is let near it.
    """
    total = 0
    for found in _STREAM.finditer(data):
        end = data.find(b"endstream", found.end())
        if end < 0:
            break
        before = data[max(0, found.start() - 2048) : found.start()]
        dictionary = before[before.rfind(b"obj") + 3 :]
        if b"FlateDecode" not in dictionary:
            continue
        limit = MAX_IMAGE_STREAM if _IMAGE.search(dictionary) else MAX_STREAM
        size = _unpacked(data[found.end() : end], min(limit, MAX_UNPACKED - total))
        total += size
        if size > limit or total > MAX_UNPACKED:
            raise _refused(
                f"that PDF holds compressed data that unpacks to more than {min(limit, MAX_UNPACKED) // 1_000_000} MB, "
                "which no datasheet needs: it is not opened"
            )


def _loaded(path: Path) -> bytes:
    try:
        size = path.stat().st_size
        if size > MAX_FILE:
            raise _refused(
                f"that file is {size // 1_000_000} MB; a datasheet of more than {MAX_FILE // 1_000_000} MB is not read"
            )
        data = path.read_bytes()
    except OSError as failed:
        raise _refused(f"{path.name} cannot be opened: {failed.strerror or failed}") from None
    if b"%PDF" not in data[:1024]:
        raise _refused(NOT_A_PDF)
    return data


def read_pages(
    path: str | Path, *, max_pages: int = MAX_PAGES, seconds: float = MAX_SECONDS
) -> tuple[Document, list[str]]:
    """Text of every page, plus the identity of the file it came from.

    Raises ReaderFailed, in one plain line, for a file that is not a PDF, is damaged past
    opening, has more than `max_pages` pages, unpacks to more than a datasheet could, or
    takes longer than `seconds` to give up its text.
    """
    path = Path(path)
    data = _loaded(path)
    check_streams(data)
    pdfplumber = provider.needs("pdfplumber", "reading a PDF")
    started = time.monotonic()
    pages: list[str] = []
    try:
        with pdfplumber.open(path) as pdf:
            count = len(pdf.pages)
            if count == 0:
                raise _refused(f"{NOT_A_PDF} with any pages in it")
            if count > max_pages:
                raise _refused(
                    f"that PDF has {count} pages, more than the {max_pages} that are read: allow more pages, "
                    "or cut it down to the pages of the one part"
                )
            for page in pdf.pages:
                if time.monotonic() - started > seconds:
                    raise _refused(
                        f"that PDF took more than {seconds:g} s to give up the text of its first {len(pages)} pages: "
                        "it is not read further"
                    )
                pages.append(_text(page))
    except provider.ReaderFailed:
        raise
    except Exception:  # the PDF library fails in many ways on a damaged file, and they all mean this
        raise _refused(f"{NOT_A_PDF} that can be opened: it is damaged or cut short") from None
    return Document(file=path.name, sha256=hashlib.sha256(data).hexdigest(), pages=len(pages)), pages


def _text(page) -> str:
    """One page's text. A page whose own text cannot be got out is treated as having none,
    which sends it to be read from its picture like a scan."""
    try:
        return page.extract_text() or ""
    except RecursionError:
        raise
    except Exception:
        return ""


def unreadable(text: str) -> bool:
    """Whether a page's text is no use: next to nothing, or glyph codes that did not decode."""
    stripped = text.strip()
    if len(stripped) < 40:
        return True
    return stripped.count("(cid:") * 6 > len(stripped) // 2


def with_transcripts(document: Document, pages: list[str]) -> list[str]:
    """Page texts, with each transcribed page's saved transcript in place of its own."""
    return [document.transcribed.get(n, text) for n, text in enumerate(pages, start=1)]


def fitting_scale(width: float, height: float, scale: float, max_pixels: int = MAX_PIXELS) -> float:
    """The scale to draw a page at: the one asked for, or the largest that keeps the
    picture within `max_pixels`. A page far larger than paper is drawn smaller, not refused."""
    pixels = width * height * scale * scale
    if pixels <= max_pixels or pixels <= 0:
        return scale
    fitted = scale * math.sqrt(max_pixels / pixels)
    while math.ceil(width * fitted) * math.ceil(height * fitted) > max_pixels:
        fitted *= 0.999  # a picture is a whole number of pixels each way, rounded up
    return fitted


def render_page(path: str | Path, number: int, scale: float = 2.0, *, max_pixels: int = MAX_PIXELS) -> bytes:
    """One page (numbered from 1) as PNG bytes, of at most `max_pixels` pixels."""
    import io

    pypdfium2 = provider.needs("pypdfium2", "drawing a page of a PDF")
    provider.needs("PIL", "drawing a page of a PDF")
    try:
        document = pypdfium2.PdfDocument(str(path))
    except Exception:
        raise _refused(f"{NOT_A_PDF} that can be opened: it is damaged or cut short") from None
    try:
        if not 1 <= number <= len(document):
            raise _refused(f"page {number} does not exist: the file has {len(document)} pages")
        page = document[number - 1]
        width, height = page.get_size()
        image = page.render(scale=fitting_scale(width, height, scale, max_pixels)).to_pil()
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
    finally:
        document.close()
