"""Reading one datasheet from start to finish, as the command line and the page both do it.

The steps cost money and can fail late, so their order is fixed here: the plan is said
before any call is made; one ledger counts every call against one budget; and what has been
read is on disk before the figures are started, so a failure among the figures leaves the
tables that were paid for.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from motionsim.observe import provider, save_observations
from motionsim.observe.schema import ObservationSet


@dataclass
class Reading:
    """What reading a datasheet gave and what it cost."""

    observations: ObservationSet
    ledger: provider.Ledger
    saved: Path | None  # where the observations were written, if anywhere

    def summary(self) -> list[str]:
        """Lines for whoever shows the result: what was read, how firmly, and at what cost."""
        from motionsim.observe.verify import summary

        return [*summary(self.observations), self.ledger.summary()]


def ready() -> None:
    """Whether the libraries that read a PDF are installed: raises NoReader, with what to
    install, where one is not. Asked before anything else, so that a missing library is
    never reported as a missing file or a missing key."""
    for module, what in (
        ("pdfplumber", "reading a PDF"),
        ("pypdfium2", "drawing a page of a PDF"),
        ("PIL", "drawing a page of a PDF"),
    ):
        provider.needs(module, what)


def key_warning() -> str | None:
    """What to tell the user before reading where the key of the reader set up would cross
    a network unencrypted, or None. No reader set up is not this function's to say."""
    try:
        return provider.in_the_clear(provider.chosen())
    except provider.NoReader:
        return None


def read_datasheet(
    pdf: str | Path,
    output: str | Path | None = None,
    *,
    max_calls: int = provider.MAX_CALLS,
    max_pages: int | None = None,
    curves: bool = True,
    say: Callable[[str], None] | None = None,
    client=None,
) -> Reading:
    """Read a datasheet PDF: its tables, checked, and its figures, digitised.

    `max_calls` is the most model calls the whole reading may make (default 40) and
    `max_pages` the most pages the file may have (default 80); past either the reading is
    refused in words, before spending where that can be known beforehand. `say` is given
    the plan before the first call (the terminal's error stream when not given). With
    `output`, the observations are written there as soon as the tables are checked and
    again when the figures are done. Raises NoReader or ReaderFailed, each one plain line.
    """
    ready()
    from motionsim.observe import reader
    from motionsim.observe.digitise import digitise_curves
    from motionsim.observe.verify import check

    ledger = provider.Ledger(max_calls=max_calls)
    name = reader.reader_name()
    document, pages = reader.read_document(
        pdf,
        max_pages=reader.MAX_PAGES if max_pages is None else max_pages,
        ledger=ledger,
        say=reader._to_stderr if say is None else say,
        client=client,
    )
    obs = check(reader.read_tables(pages, client, ledger=ledger), document, pages, reader=name)
    saved = Path(output) if output is not None else None
    if saved is not None:
        save_observations(obs, saved)  # the tables are paid for: on disk before anything else can fail
    if curves:
        obs.curves = digitise_curves(str(pdf), obs, ledger=ledger, client=client)
        if saved is not None:
            save_observations(obs, saved)
    return Reading(obs, ledger, saved)
