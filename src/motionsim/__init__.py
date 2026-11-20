"""Datasheets as executable models for motor-drive inverters.

The public interface is small: `load_device`, `OperatingPoint`, `simulate`, `run_design`
and `Refusal` (see motionsim.api). They are loaded when first asked for, so that importing
the package, or asking the command line for its version, loads no engine.
"""

from typing import TYPE_CHECKING, Any

__version__ = "0.6.0"

__all__ = [
    "Device",
    "OperatingPoint",
    "Refusal",
    "Result",
    "__version__",
    "load_device",
    "run_design",
    "simulate",
]

if TYPE_CHECKING:
    from motionsim.api import Device, OperatingPoint, Refusal, Result, load_device, run_design, simulate


def __getattr__(name: str) -> Any:
    if name in __all__:
        from motionsim import api

        return getattr(api, name)
    raise AttributeError(f"module 'motionsim' has no attribute {name!r}")


def __dir__() -> list[str]:
    # What the package offers, though it is loaded only when first asked for.
    return sorted(__all__)
