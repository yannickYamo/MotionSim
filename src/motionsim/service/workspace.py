"""The devices at hand: the user's folder of device files, the made-up parts that come with
the tool, and the ways a new one is brought in (a device file, figures typed from a
datasheet, a part's own measurements)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from motionsim.device import load_device
from motionsim.device.schema import Device
from motionsim.errors import Refusal
from motionsim.files import MOST_BYTES, parse_yaml, read_text
from motionsim.service.answers import reason_of

PACKAGE = Path(__file__).parent.parent
EXAMPLE = PACKAGE / "example_device.yaml"


# The made-up parts the page can be tried with: an IGBT for mains voltages, and a
# low-voltage transistor for batteries and robots.
EXAMPLES = {"example": EXAMPLE, "example-mosfet": PACKAGE / "example_mosfet.yaml"}


class Workspace:
    """Device files the page can use: the user's folder, plus the synthetic example."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        folder.mkdir(parents=True, exist_ok=True)

    def paths(self) -> dict[str, Path]:
        found = {key: path for key, path in EXAMPLES.items() if path.exists()}
        for path in sorted(self.folder.glob("*.device.yaml")):
            found[path.name.removesuffix(".device.yaml")] = path
        return found

    def device(self, key: str) -> Device:
        paths = self.paths()
        if key not in paths:
            raise Refusal(f"no device called {key}", "add its datasheet again")
        return load_device(paths[key])

    def summary(self, key: str, device: Device) -> dict:
        sw = device.switch
        tables = [sw.conduction, sw.e_on, sw.e_off, sw.reverse]
        if device.diode is not None:
            tables += [device.diode.conduction, device.diode.e_rr]
        point = any(t is not None and t.basis.value == "point" for t in tables)
        measured = sw.e_on is not None and sw.e_off is not None
        return {
            "id": key,
            # A copy carrying the user's own measurements is named as one, to be told from the part it came from.
            "name": f"{device.vendor} {device.part_number}" + (", measured" if key.endswith("-measured") else ""),
            "technology": device.technology,
            "v_max": device.ratings.v_max,
            "i_nominal": device.ratings.i_nominal,
            "tj_max": device.ratings.tj_max,
            "i_pulsed": device.ratings.i_pulsed,
            "t_sc": device.ratings.t_sc,
            "positions": device.package.topology.positions,
            "integrated_driver": device.package.integrated_driver,
            "example": key in EXAMPLES,
            "switching": "estimated from the datasheet's rise and fall times"
            if sw.e_on is not None and sw.e_off is not None and sw.e_on.footing == "times"
            else "measured energy from the datasheet"
            if measured
            else "estimated from gate and output charge",
            "support": "table points and assumed shapes" if point else "curves",
            "needs_gate_drive": not measured,
            # What kind of chip switches, and whether its own diode's recovery is counted.
            "kind": sw.kind.value,
            "recovery": (sw if device.diode is None else device.diode).e_rr is not None,
        }

    def listing(self) -> list[dict]:
        out = []
        for key, path in self.paths().items():
            try:
                out.append(self.summary(key, load_device(path)))
            except Refusal:  # a file that is not a device model is not the page's problem
                continue
        return out


NOT_A_DEVICE = "choose a .device.yaml file written by `motionsim build`"


def add_device(name: str, text: str, workspace: Workspace) -> dict:
    """Put a device file the user supplied into the workspace, after checking it loads."""
    import re

    from pydantic import ValidationError

    if not isinstance(name, str) or not isinstance(text, str):
        raise Refusal("a device file comes as a name and its text", "send the file's name and what it holds", "")

    key = re.sub(r"[^a-z0-9]+", "-", name.lower().removesuffix(".yaml").removesuffix(".device")).strip("-")
    key = key[:80].strip("-")
    if not key or key in EXAMPLES:
        key = "device"
    if len(text.encode("utf-8", "replace")) > MOST_BYTES:
        raise Refusal("that file is too large to be a device model", NOT_A_DEVICE)
    try:
        device = Device.model_validate(parse_yaml(text, name, "device file"))
    except Refusal as exc:
        raise Refusal(f"that file is not a device model: {exc.reason[:160]}", NOT_A_DEVICE) from None
    except ValidationError as exc:
        raise Refusal(f"that file is not a device model: {reason_of(exc)[:160]}", NOT_A_DEVICE) from None
    # The same file dropped again replaces what it held; another part under a name that
    # reads the same (a space for a dash) is another device and does not write over the first.
    base, n = key, 1
    while key in workspace.paths():
        try:
            held = workspace.device(key)
        except Refusal:
            break
        if (held.vendor, held.part_number) == (device.vendor, device.part_number):
            break
        n += 1
        key = f"{base}-{n}"
    (workspace.folder / f"{key}.device.yaml").write_text(text, encoding="utf-8")
    return {"device": workspace.summary(key, device)}


def add_typed(figures: dict | None, workspace: Workspace) -> dict:
    """A device from the figures the user typed in, built and kept like any other."""
    import re

    from motionsim.fit.typed import Mistyped, from_figures, typed_keys

    known = typed_keys((figures or {}).get("technology") if isinstance(figures, dict) else None)
    stray = sorted(str(k) for k in figures if k not in known) if isinstance(figures, dict) else []
    if stray:
        # A name that is not one of the figures is a figure mistyped: left out in silence,
        # the part would be built without it and nothing would say so.
        raise Refusal(
            f"the figures have names this tool does not know: {', '.join(stray)}",
            f"a typed part holds {', '.join(sorted(known))}",
            stray[0],
        )
    names = {d["name"] for d in workspace.listing()}
    try:
        device = from_figures(figures or {}, lambda name: name in names)
    except Mistyped as exc:
        raise Refusal(str(exc), "check the figure against the datasheet", exc.field or "") from None
    import hashlib

    name = f"{device.vendor} {device.part_number}"
    key = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    # A name that leaves nothing to tell it by, or that is one the page keeps for itself,
    # gets a key of its own, so that no two parts are written over each other.
    if not re.sub(r"[^a-z0-9]+", "", device.part_number.lower()) or key in EXAMPLES or key == "device":
        key = "typed-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    text = yaml.safe_dump(device.model_dump(mode="json", exclude_none=True), sort_keys=False, allow_unicode=True)
    (workspace.folder / f"{key}.device.yaml").write_text(text, encoding="utf-8")
    return {"device": workspace.summary(key, device), "name": f"{key}.device.yaml", "text": text}


def add_measurement(key: str, name: str, text: str, workspace: Workspace) -> dict:
    """Replace a device's datasheet switching energy with the user's own double-pulse data.

    The device as read from its datasheet is kept; the measured one is added beside it.
    """
    from pydantic import ValidationError

    from motionsim.device import save_device
    from motionsim.measured import DoublePulse, apply_double_pulse

    if not all(isinstance(x, str) for x in (key, name, text)):
        raise Refusal("measurements come as the device's name, the file's name and its text", "send all three", "")
    device = workspace.device(key)
    try:
        data = DoublePulse.model_validate(json.loads(text))
    except (ValidationError, json.JSONDecodeError, TypeError, RecursionError) as exc:
        # The figure at fault in words, never the validator's own text or its web address.
        said = reason_of(exc) if isinstance(exc, ValidationError) else "it is not JSON that can be read"
        raise Refusal(
            f"that file is not double-pulse data: {said[:160]}",
            "it needs v_dc and a list of points, each with tj, current, e_on and e_off",
        ) from None
    try:
        measured = apply_double_pulse(device, data, name)
    except ValueError as exc:
        raise Refusal(f"this measurement cannot be used: {exc}", "check the file's points") from None
    new_key = f"{key}-measured"
    save_device(measured, workspace.folder / f"{new_key}.device.yaml")
    return {"device": workspace.summary(new_key, measured)}


def curves(key: str, workspace: Workspace) -> dict:
    """The tables of a device model, for drawing what was read."""
    device = workspace.device(key)

    def table(model, unit: str) -> dict | None:
        if model is None:
            return None
        return {
            "unit": unit,
            "basis": model.basis.value,
            "assumption": model.assumption,
            "source": model.source.note,
            "page": model.source.page,
            "curves": [{"tj": c.tj, "x": c.current, "y": c.value} for c in model.curves],
        }

    sw, d = device.switch, device.diode
    out = {
        "summary": workspace.summary(key, device),
        "conduction": table(sw.conduction, "V"),
        "e_on": table(sw.e_on, "J"),
        "e_off": table(sw.e_off, "J"),
        "reverse": table(sw.reverse, "V"),
        "diode": None if d is None else table(d.conduction, "V"),
        "e_rr": table((d or sw).e_rr, "J"),
        "thermal": {"r": sw.thermal.r, "tau": sw.thermal.tau, "source": sw.thermal.source.note},
        "reading": _reading(key, workspace),
        # The device file itself, for a setup saved from the page to carry the part with it.
        "file": {"name": f"{key}.device.yaml", "text": workspace.paths()[key].read_text(encoding="utf-8")},
    }
    return out


def _reading(key: str, workspace: Workspace) -> dict | None:
    """What the reader took from the datasheet this device was built from, value by value,
    or None for a device that came as a file."""
    path = workspace.folder / f"{key}.observations.yaml"
    if not path.is_file():
        return None
    from motionsim.observe import load_observations

    obs = load_observations(path)

    def conditions(o) -> str:
        parts = []
        if o.current_a is not None:
            parts.append(f"{o.current_a:g} A")
        if o.voltage_v is not None:
            parts.append(f"{o.voltage_v:g} V")
        if o.tj_c is not None:
            parts.append(f"{o.tj_c:g} °C")
        return ", ".join(parts)

    def printed(o) -> str:
        parts = []
        if o.printed_typ is not None:
            parts.append(f"typ {o.printed_typ}")
        if o.printed_max is not None:
            parts.append(f"max {o.printed_max}")
        return (", ".join(parts) or "none") + f" {o.unit}"

    return {
        "document": obs.document.file,
        "pages": obs.document.pages,
        "from_images": len(obs.document.transcribed),
        "values": [
            {"what": o.quantity.value, "printed": printed(o), "at": conditions(o), "page": o.page, "flags": o.flags}
            for o in obs.observations
        ],
        "figures": [
            {
                "what": c.quantity.value,
                "label": c.label,
                "page": c.page,
                "tj": c.tj_c,
                "points": len(c.x),
                "flags": c.flags,
                "notes": c.notes,
                "within": c.anchor_error,
                "method": c.method,
            }
            for c in obs.curves
        ],
    }


def free_key(key: str, fallback: str = "device") -> str:
    """A name a device brought in may be kept under: never one of the made-up parts', which
    would put the user's part in the place of the example the page and the guide name."""
    return f"{key}-file" if key in EXAMPLES else key or fallback


def bring_device(entry: str, base: Path, workspace: Workspace) -> str:
    """A device named in a design or on the command line, brought into the workspace: one of
    the made-up parts by its name, a device file as it is, or a file of typed figures built
    first. Returns its name there."""
    from motionsim.fit.typed import Mistyped, from_figures

    if entry in workspace.paths():
        return entry
    file = Path(entry) if Path(entry).is_absolute() else base / entry
    try:
        there = file.is_file() or (file.exists() and not file.is_dir())
    except (OSError, ValueError):  # a name no file could have
        there = False
    if not there:
        raise Refusal(
            f"no device called {entry}, and no file of that name",
            "give a path to a device file, or example-mosfet or example",
            "devices",
        )
    try:
        data = parse_yaml(read_text(file, "device file", "devices"), file.name, "device file", "devices")
        device = from_figures(data) if isinstance(data, dict) and "switch" not in data else load_device(file)
    except Mistyped as exc:
        raise Refusal(f"{file.name}: {exc}", "check the figure against the datasheet", exc.field or "devices") from None
    except Refusal as exc:
        raise Refusal(f"{file.name} is not a device: {exc.reason[:200]}", exc.fix, "devices") from None
    name = file.name.removesuffix(".yaml").removesuffix(".yml").removesuffix(".device").lower().replace(" ", "-")
    key = free_key(name)
    # Two files of one name from two folders are two devices: the second is not written over the first.
    text = yaml.safe_dump(device.model_dump(mode="json", exclude_none=True), sort_keys=False)
    stem, n = key, 1
    while (kept := workspace.folder / f"{key}.device.yaml").exists() and kept.read_text(encoding="utf-8") != text:
        n += 1
        key = f"{stem}-{n}"
    (workspace.folder / f"{key}.device.yaml").write_text(text, encoding="utf-8")
    return key
