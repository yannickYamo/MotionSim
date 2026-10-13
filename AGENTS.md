# For coding agents

MotionSim can be driven entirely from the terminal. Install it (`pip install .`), then run

```
motionsim agent
```

for the guide: the loop, the design file, what comes back and what the exit status means.
In short: `motionsim design init -o design.yaml`, edit it, `motionsim design run design.yaml --json`.

Working on this repository itself:

- `pip install -e ".[dev]"`, then `pre-commit install` once: commits are formatted and linted with ruff.
- Tests are `pytest`. `tests/test_golden.py` holds the product's figures to the last digit: a change that
  moves one is either a mistake or meant, and if meant, `pytest tests/test_golden.py --update-golden` and
  say in the commit which figures moved and why.
- The page is built with `cd web && npm run build`; the built files under `src/motionsim/webui` are
  committed, and CI fails when they are not what the sources build.
