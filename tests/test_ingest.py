"""Opening a PDF that may be anything: not a PDF, a damaged one, or one built to exhaust
the machine that opens it. Each file is made here, in a temporary folder."""

from __future__ import annotations

import io
import subprocess
import sys
import time
import zlib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.reader import pdf
from motionsim.observe import ingest, provider

LINE = "Collector-emitter saturation voltage VCE(sat) IC = 50 A, Tj = 25 °C 1.55 2.00 V"


def datasheet(pages: int = 1, **size) -> bytes:
    made = []
    for n in range(pages):
        page = pdf.Page(**size)
        page.text(50, 50, f"{LINE} (page {n + 1})")
        made.append(page)
    return pdf.write(made)


def file_with_stream(packed: bytes, dictionary: str = "", box: str = "0 0 595 842") -> bytes:
    """A one-page PDF around a stream that is already compressed, so that one which
    unpacks to hundreds of megabytes can be written without ever holding them."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [{box}] /Contents 4 0 R >>".encode(),
        f"<< /Filter /FlateDecode {dictionary} /Length {len(packed)} >>\nstream\n".encode() + packed + b"\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def packed_zeros(megabytes: int) -> bytes:
    packer = zlib.compressobj(9)
    megabyte = bytes(1 << 20)
    return b"".join(packer.compress(megabyte) for _ in range(megabytes)) + packer.flush()


def test_a_datasheet_is_read_page_by_page_and_named_by_its_bytes(tmp_path) -> None:
    import hashlib

    data = datasheet(pages=3)
    path = tmp_path / "part.pdf"
    path.write_bytes(data)
    document, pages = ingest.read_pages(path)
    assert (document.file, document.pages, document.sha256) == ("part.pdf", 3, hashlib.sha256(data).hexdigest())
    assert pages[1] == f"{LINE} (page 2)" and not ingest.unreadable(pages[1])


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"just some text, not a PDF at all",
        b"\x89PNG\r\n\x1a\n" + bytes(200),
        b"PK\x03\x04" + bytes(200),
    ],
)
def test_a_file_that_is_not_a_pdf_is_refused_in_the_words_the_page_uses(tmp_path, content) -> None:
    path = tmp_path / "thing.pdf"
    path.write_bytes(content)
    with pytest.raises(provider.ReaderFailed) as refused:
        ingest.read_pages(path)
    assert str(refused.value) == "that file is not a PDF"


@pytest.mark.parametrize("keep", [20, 200, 0.5, 0.9])
def test_a_damaged_pdf_is_refused_in_words(tmp_path, keep) -> None:
    whole = datasheet(pages=2)
    cut = whole[: keep if isinstance(keep, int) else int(len(whole) * keep)]
    path = tmp_path / "cut.pdf"
    path.write_bytes(cut)
    try:
        _, pages = ingest.read_pages(path)
    except provider.ReaderFailed as refused:
        assert "not a PDF" in str(refused) and "\n" not in str(refused)
    else:  # a PDF library may yet mend a file cut near its end: then it is simply read
        assert len(pages) == 2


def test_a_file_that_is_not_there_is_said_as_that(tmp_path) -> None:
    with pytest.raises(provider.ReaderFailed, match=r"missing\.pdf cannot be opened"):
        ingest.read_pages(tmp_path / "missing.pdf")


def test_a_small_file_that_unpacks_to_hundreds_of_megabytes_is_refused_unopened(tmp_path) -> None:
    bomb = file_with_stream(packed_zeros(300))
    assert len(bomb) < 400_000  # about 300 kB on disk, 300 MB once unpacked
    path = tmp_path / "bomb.pdf"
    path.write_bytes(bomb)
    started = time.perf_counter()
    with pytest.raises(provider.ReaderFailed, match="unpacks to more than 32 MB"):
        ingest.read_pages(path)
    assert time.perf_counter() - started < 5.0


@pytest.mark.skipif(sys.platform != "linux", reason="the peak memory of a process is read the Linux way")
def test_refusing_the_bomb_does_not_unpack_it(tmp_path) -> None:
    """In a process of its own, so that its peak memory is this file's doing and nothing else's.
    The peak is the process's own high-water mark (VmHWM). The peak getrusage gives is not: on
    Linux it carries over the peak of the process it was started from, a test worker that may
    have held a few hundred megabytes for an earlier test. The PDF library is loaded first, so
    that what the read itself takes is the rise from there."""
    path = tmp_path / "bomb.pdf"
    path.write_bytes(file_with_stream(packed_zeros(300)))
    code = (
        "import sys\n"
        "def peak():\n"
        "    return int(next(x for x in open('/proc/self/status') if x.startswith('VmHWM:')).split()[1])\n"
        "import pdfplumber\n"
        "from motionsim.observe import ingest, provider\n"
        "before = peak()\n"
        "try:\n    ingest.read_pages(sys.argv[1])\nexcept provider.ReaderFailed as refused:\n    print(refused)\n"
        "print(before, peak())\n"
    )
    ran = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True, timeout=120)
    said, figures = ran.stdout.strip().splitlines()
    before_kb, peak_kb = map(int, figures.split())
    assert "unpacks to more than" in said
    # The 300 MB were never held: opened unchecked, the read rose by over 600 MB.
    assert peak_kb - before_kb < 100_000 and peak_kb < 250_000


def test_many_streams_that_are_each_allowed_are_refused_together(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ingest, "MAX_STREAM", 3_000_000)
    monkeypatch.setattr(ingest, "MAX_UNPACKED", 5_000_000)
    two = packed_zeros(2)
    ingest.check_streams(file_with_stream(two) + file_with_stream(two))  # 4 MB in all: allowed
    with pytest.raises(provider.ReaderFailed, match="unpacks to more than"):
        ingest.check_streams(file_with_stream(two) * 3)


def test_a_picture_may_unpack_to_more_than_text_may(monkeypatch) -> None:
    monkeypatch.setattr(ingest, "MAX_STREAM", 1_000_000)
    monkeypatch.setattr(ingest, "MAX_IMAGE_STREAM", 4_000_000)
    scan = "/Type /XObject /Subtype /Image /Width 1448 /Height 1448 /ColorSpace /DeviceGray /BitsPerComponent 8"
    ingest.check_streams(file_with_stream(packed_zeros(2), scan))
    with pytest.raises(provider.ReaderFailed):
        ingest.check_streams(file_with_stream(packed_zeros(2)))  # the same bytes as page content
    with pytest.raises(provider.ReaderFailed):
        ingest.check_streams(file_with_stream(packed_zeros(5), scan))


def test_a_page_the_size_of_a_building_is_drawn_smaller_not_at_full_size(tmp_path) -> None:
    from PIL import Image

    huge = file_with_stream(zlib.compress(b""), box="0 0 14400 14400")
    assert len(huge) < 700
    path = tmp_path / "huge.pdf"
    path.write_bytes(huge)
    started = time.perf_counter()
    picture = Image.open(io.BytesIO(ingest.render_page(path, 1)))
    assert time.perf_counter() - started < 10.0
    across, down = picture.size
    assert across == down and 0.9 * ingest.MAX_PIXELS < across * down <= ingest.MAX_PIXELS
    # A page of ordinary size is drawn at the scale asked for, as before.
    path.write_bytes(datasheet())
    assert Image.open(io.BytesIO(ingest.render_page(path, 1))).size == (1190, 1684)


def test_the_scale_that_fits() -> None:
    assert ingest.fitting_scale(595, 842, 2.0) == 2.0
    scale = ingest.fitting_scale(14400, 14400, 2.0)
    assert 0.99 * ingest.MAX_PIXELS < (14400 * scale) ** 2 <= ingest.MAX_PIXELS
    assert ingest.fitting_scale(0, 0, 2.0) == 2.0


def test_a_page_that_does_not_exist_is_not_drawn(tmp_path) -> None:
    path = tmp_path / "one.pdf"
    path.write_bytes(datasheet())
    for number in (0, 2, 99, -1):
        with pytest.raises(provider.ReaderFailed, match=f"page {number} does not exist: the file has 1 pages"):
            ingest.render_page(path, number)


def test_more_pages_than_are_read_is_refused_unless_allowed(tmp_path) -> None:
    path = tmp_path / "long.pdf"
    path.write_bytes(datasheet(pages=ingest.MAX_PAGES + 1))
    with pytest.raises(
        provider.ReaderFailed, match=f"has {ingest.MAX_PAGES + 1} pages, more than the {ingest.MAX_PAGES}"
    ):
        ingest.read_pages(path)
    assert len(ingest.read_pages(path, max_pages=200)[1]) == ingest.MAX_PAGES + 1


def test_a_file_that_takes_too_long_is_given_up_on(tmp_path) -> None:
    path = tmp_path / "slow.pdf"
    path.write_bytes(datasheet(pages=3))
    with pytest.raises(provider.ReaderFailed, match="took more than 0 s"):
        ingest.read_pages(path, seconds=0.0)


def test_a_file_too_large_to_be_a_datasheet_is_not_loaded(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ingest, "MAX_FILE", 100)
    path = tmp_path / "big.pdf"
    path.write_bytes(datasheet())
    with pytest.raises(provider.ReaderFailed, match="is not read"):
        ingest.read_pages(path)


@pytest.mark.parametrize(
    ("module", "call"), [("pdfplumber", "read_pages"), ("pypdfium2", "render_page"), ("PIL", "render_page")]
)
def test_without_a_pdf_library_what_to_install_is_said(tmp_path, monkeypatch, module, call) -> None:
    path = tmp_path / "part.pdf"
    path.write_bytes(datasheet())
    monkeypatch.setitem(sys.modules, module, None)  # as if it had never been installed
    with pytest.raises(
        provider.NoReader,
        match=rf'{module} library.*pip install "motionsim\[reader\] @ git\+https://github.com/yannickYamo/MotionSim"',
    ):
        getattr(ingest, call)(path, 1) if call == "render_page" else ingest.read_pages(path)


def test_a_scanned_page_is_known_by_its_lack_of_text() -> None:
    assert ingest.unreadable("") and ingest.unreadable("   page 3  ")
    assert ingest.unreadable("(cid:12)(cid:7)(cid:99)(cid:3)(cid:41)(cid:8)(cid:15) 12")
    assert not ingest.unreadable(LINE)
