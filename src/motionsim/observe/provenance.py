"""What a device model says of where its figures came from, as far as the reading knows.

A table built from a page that is a scan rests on the reader's own transcription of that
page: the digits were checked against text the model wrote, not against print. The device
file says so beside each such table, so that a result can tell what was read from what
was taken on trust.
"""

from __future__ import annotations

from pydantic import BaseModel

from motionsim.device.schema import Device, Source
from motionsim.observe.schema import ObservationSet

TRANSCRIBED = "read from the model's own transcription of a scanned page, not from printed text"


def _marked(value, pages: set[int]):
    """`value` with every source that cites one of `pages` noted as transcribed."""
    if isinstance(value, Source):
        if value.page in pages and TRANSCRIBED not in (value.note or ""):
            return value.model_copy(update={"note": f"{value.note}; {TRANSCRIBED}" if value.note else TRANSCRIBED})
        return value
    if isinstance(value, BaseModel):
        changed = {name: _marked(getattr(value, name), pages) for name in type(value).model_fields}
        changed = {name: new for name, new in changed.items() if new is not getattr(value, name)}
        return value.model_copy(update=changed) if changed else value
    if isinstance(value, list):
        new = [_marked(item, pages) for item in value]
        return new if any(a is not b for a, b in zip(new, value, strict=True)) else value
    return value


def mark_transcribed(device: Device, obs: ObservationSet) -> Device:
    """The device with each table that came off a transcribed page saying so in its source."""
    pages = set(obs.document.transcribed)
    return _marked(device, pages) if pages else device
