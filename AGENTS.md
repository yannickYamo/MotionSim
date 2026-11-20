# For coding agents

MotionSim can be driven entirely from the terminal. Install it (`pip install .` in a clone, or `uvx --from git+https://github.com/yannickYamo/MotionSim motionsim agent` with nothing to clone), then run

```
motionsim agent
```

for the guide: the loop, the design file, what comes back and what the exit status means.
In short: `motionsim design init -o design.yaml`, edit it, `motionsim design run design.yaml --json`.

Working on this repository itself ([CONTRIBUTING.md](CONTRIBUTING.md) has the whole of it):

- `make setup` once (or `pip install -e ".[dev]"`, `pre-commit install` and `cd web && npm ci`): commits are
  formatted and linted with ruff. `make check` runs everything CI runs.
- Tests are `pytest`. `tests/test_golden.py` holds the product's figures to a relative 1e-9: a change that
  moves one is either a mistake or meant, and if meant, `pytest tests/test_golden.py --update-golden` and
  say in the commit and the pull request which figures moved and why.
- The page is built with `make page` (`cd web && npm run build`); the built files under
  `src/motionsim/webui` are committed, and CI fails when they are not what the sources build.
- A warning in a test is a failure, and so is a test that runs five minutes.
- No semiconductor maker and no real part number is named anywhere: parts are described by kind and rating.
