"""Pack the engine for the browser.

Writes two files into web/public/engine/:
- motionsim.zip: the Python package, as the page loads it into its own copy of Python;
- setup.json: what the first screen needs, so the forms can be drawn before the engine is up.

Run by `npm run build` and `npm run dev`. Needs the project's Python environment.
"""

from __future__ import annotations

import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "motionsim"
OUT = ROOT / "web" / "public" / "engine"
SKIP = {"webui", "__pycache__"}

sys.path.insert(0, str(ROOT / "src"))
from motionsim import page  # noqa: E402


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    files = sorted(
        p for p in PACKAGE.rglob("*")
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
    print(f"engine packed: {len(files)} files, {(OUT / 'motionsim.zip').stat().st_size // 1024} kB")


if __name__ == "__main__":
    main()
