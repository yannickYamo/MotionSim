from motionsim.fit.sparse import MissingData
from motionsim.fit.sparse import build_device as _build_device
from motionsim.observe.schema import ObservationSet

__all__ = ["MissingData", "build_device"]


def build_device(obs: ObservationSet, *, allow_flagged: bool = False):
    """Device model from a reading. Flagged observations are left out unless allowed.

    A table that came off a scanned page says so in its source: the reading knows which
    pages were transcribed by the model, and the device file has to carry that on.
    """
    from motionsim.observe.provenance import mark_transcribed

    return mark_transcribed(_build_device(obs, allow_flagged=allow_flagged), obs)
