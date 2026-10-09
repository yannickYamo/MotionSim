from __future__ import annotations

import hashlib
from pathlib import Path

import pdfplumber

from motionsim.observe.schema import Document


def read_pages(path: str | Path) -> tuple[Document, list[str]]:
    """Text of every page, plus the identity of the file it came from."""
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with pdfplumber.open(path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return Document(file=path.name, sha256=digest, pages=len(pages)), pages


def unreadable(text: str) -> bool:
    """Whether a page's text is no use: next to nothing, or glyph codes that did not decode."""
    stripped = text.strip()
    if len(stripped) < 40:
        return True
    return stripped.count("(cid:") * 6 > len(stripped) // 2


def with_transcripts(document: Document, pages: list[str]) -> list[str]:
    """Page texts, with each transcribed page's saved transcript in place of its own."""
    return [document.transcribed.get(n, text) for n, text in enumerate(pages, start=1)]


def render_page(path: str | Path, number: int, scale: float = 2.0) -> bytes:
    """One page (numbered from 1) as PNG bytes."""
    import io

    import pypdfium2

    document = pypdfium2.PdfDocument(str(path))
    image = document[number - 1].render(scale=scale).to_pil()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
