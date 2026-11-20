"""How far the golden figures moved between two versions of tests/golden/figures.json.

    python tools/golden_diff.py old.json new.json

For each top-level group: the figures both hold that moved, with the median and the largest
relative change; the words that changed; and the keys only one side has. Lists are walked
by position. A figure that moved from or to zero counts as a change of 100%.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path


def leaves(value, path=""):
    """Every leaf under a value, as (path, leaf)."""
    if isinstance(value, dict):
        for key in sorted(value):
            yield from leaves(value[key], f"{path}/{key}")
    elif isinstance(value, list):
        for n, item in enumerate(value):
            yield from leaves(item, f"{path}[{n}]")
    else:
        yield path, value


def number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def compare(old, new) -> dict:
    a, b = dict(leaves(old)), dict(leaves(new))
    moved, words = [], []
    for path in a.keys() & b.keys():
        x, y = a[path], b[path]
        if x == y:
            continue
        if number(x) and number(y):
            scale = max(abs(x), abs(y))
            moved.append((abs(y - x) / scale if scale else 0.0, path, x, y))
        else:
            words.append((path, x, y))
    return {
        "shared": len(a.keys() & b.keys()),
        "moved": sorted(moved, reverse=True),
        "words": sorted(words, key=lambda w: w[0]),
        "added": sorted(b.keys() - a.keys()),
        "removed": sorted(a.keys() - b.keys()),
    }


def main(argv: list[str]) -> int:
    old, new = (json.loads(Path(p).read_text()) for p in argv[:2])
    detail = "--detail" in argv
    print(f"{'group':10}{'shared':>8}{'moved':>7}{'median':>10}{'largest':>10}{'words':>7}{'added':>7}{'removed':>9}")
    for group in sorted(old.keys() | new.keys()):
        d = compare(old.get(group, {}), new.get(group, {}))
        changes = [m[0] for m in d["moved"]]
        median = f"{statistics.median(changes):.3%}" if changes else "-"
        largest = f"{max(changes):.3%}" if changes else "-"
        print(
            f"{group:10}{d['shared']:8}{len(changes):7}{median:>10}{largest:>10}"
            f"{len(d['words']):7}{len(d['added']):7}{len(d['removed']):9}"
        )
        if detail:
            for change, path, x, y in d["moved"][:12]:
                print(f"    {change:8.3%}  {path}: {x!r} -> {y!r}")
            for path, x, y in d["words"][:8]:
                print(f"    words     {path}: {str(x)[:70]!r} -> {str(y)[:70]!r}")
            for path in d["added"][:8]:
                print(f"    added     {path}")
            for path in d["removed"][:8]:
                print(f"    removed   {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
