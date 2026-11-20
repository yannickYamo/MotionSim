"""Pack the engine for the browser.

Writes into web/public/engine/:
- motionsim.zip: the Python package, as the page loads it into its own copy of Python;
- setup.json: what the first screen needs, so the forms can be drawn before the engine is up;
- pyodide/: the Python runtime itself, copied from the pinned npm package, so that the code
  the page runs is served with the page and from nowhere else. The numerical libraries stay
  on the public file server; the lock file written here names each by its full address and
  carries its hash, which the runtime checks before it loads one.

Run by `npm run build` and `npm run dev`. Needs the project's Python environment.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "motionsim"
OUT = ROOT / "web" / "public" / "engine"
SKIP = {"webui", "__pycache__"}
RUNTIME = ROOT / "web" / "node_modules" / "pyodide"
CORE = ("pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip")

sys.path.insert(0, str(ROOT / "src"))
from motionsim import page  # noqa: E402


def runtime() -> str:
    """Copy the Python runtime beside the engine. Returns its version."""
    version = json.loads((RUNTIME / "package.json").read_text(encoding="utf-8"))["version"]
    out = OUT / "pyodide"
    out.mkdir(parents=True, exist_ok=True)
    for name in CORE:
        shutil.copyfile(RUNTIME / name, out / name)
    lock = json.loads((RUNTIME / "pyodide-lock.json").read_text(encoding="utf-8"))
    base = f"https://cdn.jsdelivr.net/pyodide/v{version}/full/"
    for package in lock["packages"].values():
        package["file_name"] = base + package["file_name"]
    (out / "pyodide-lock.json").write_text(json.dumps(lock, sort_keys=True), encoding="utf-8")
    return version


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    version = runtime()
    files = sorted(
        p
        for p in PACKAGE.rglob("*")
        if p.is_file() and not SKIP.intersection(p.relative_to(PACKAGE).parts) and p.suffix in {".py", ".yaml"}
    )
    with zipfile.ZipFile(OUT / "motionsim.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for path in files:
            # A fixed date keeps the archive the same from one build to the next.
            info = zipfile.ZipInfo(str(Path("motionsim") / path.relative_to(PACKAGE)), (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, path.read_bytes())
    with tempfile.TemporaryDirectory() as folder:
        setup = page.setup(page.Workspace(Path(folder)))
    setup["can_read"] = False
    (OUT / "setup.json").write_text(json.dumps(setup), encoding="utf-8")
    # Served as it is, the page has no engine behind it; `motionsim serve` answers this
    # address itself and says so.
    (OUT / "mode.json").write_text(json.dumps({"server": False}), encoding="utf-8")
    size = (OUT / "motionsim.zip").stat().st_size // 1024
    print(f"engine packed: {len(files)} files, {size} kB; Python runtime {version} beside it")


if __name__ == "__main__":
    main()
