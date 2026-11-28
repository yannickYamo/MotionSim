# Contributing

Thank you for looking. The most useful thing anyone can bring is a figure that is wrong: see "A figure you think is wrong" below. Code is welcome too, and this page says how the repository is worked on.

Everyone taking part is asked to follow the [code of conduct](CODE_OF_CONDUCT.md). A security fault goes through [SECURITY.md](SECURITY.md), not a public issue.

## Two rules before anything else

- **No maker and no part number.** No semiconductor maker and no real part number is named anywhere in the repository: not in code, tests, documents, commit messages, issues or pull requests. A part is described by kind and rating ("a 100 V, 2 mΩ silicon MOSFET"). Example parts are made up.
- **No datasheets and no device data.** Datasheets are their makers' property. None is committed, attached to an issue or quoted at length, and no device model read from one is committed either.

## Setup

You need Python 3.11 or later, and Node 22 for the page. Docker is needed only to try the container.

```
git clone https://github.com/yannickYamo/MotionSim.git
cd MotionSim
make setup
```

`make setup` makes a virtual environment in `.venv`, installs the package with every tool (`pip install -e ".[dev]"`), installs the commit hooks (`pre-commit install`) and the page's build tools (`cd web && npm ci`). On Windows, where `make` is not at hand, run those three commands yourself.

`make help` lists every target. The one to remember is

```
make check
```

which runs the main checks of CI: format and lint, the type check, the tests with the coverage floor, the package build, the audits, and the page's own checks. CI adds the oldest libraries allowed, the installed wheel on three systems, the datasheet reader's check, and the page's races and walks.

## Tests

```
make test         # the whole suite, in parallel, with coverage
make test-fast    # without coverage, stopping at the first failure
```

- A test's expected value is worked out apart from the code it tests: a closed form, a figure from a published source, or a second path through the engine. A test that asks the code for its answer and then checks the code gives that answer holds nothing.
- A warning raised in a test is a failure, and a test that runs for five minutes is stopped. Both are set in `pyproject.toml`.
- Tests that need real datasheets (`tests/test_real_datasheets.py`) run only where a `datasheets/` folder holds them, and skip everywhere else.
- Coverage has a floor in `pyproject.toml`. It is raised as tests land and never lowered to let a change through.

## The golden-figure rule

`tests/test_golden.py` holds the figures the product exists for (a loss, a junction temperature, a comparison, a whole design) to a relative 1e-9 of the values recorded in `tests/golden/`. It does not say a figure is right; it says the figure has not moved.

When that test fails, the change moved a result. Either that is a mistake, and the change is fixed, or it is meant. If it is meant:

1. Rewrite the recorded figures: `pytest tests/test_golden.py --update-golden`.
2. Say in the commit message and in the pull request which figures moved, from what to what, and why the new value is right.
3. Add a line under "Unreleased" in `CHANGELOG.md`, since someone using the tool will see a different number.

A pull request that rewrites the golden figures without saying why is not merged.

## The page

The page's sources are in `web/`; what users get is the built page in `src/motionsim/webui/`, which is committed so that `pip install` needs no Node.

```
make page          # cd web && npm run build
```

Commit the built files with the change that caused them. The build also packs the engine for the hosted page, so a change to anything under `src/motionsim/` needs a rebuild too: CI fails when the committed page is not what the sources build.

## The control lab

The engine's side is `src/motionsim/control/` (the motor, the blocks, the schemes, the kernel, the hand-off to the loss engine, the linear analysis) and `src/motionsim/service/control/` (the five addresses; the docstring of its `__init__.py` is the API's reference, so a change to a shape is a change to that docstring). `docs/CONTROL.md` describes the model.

```
.venv/bin/pytest -q tests/test_control_*.py      # the lab's tests
.venv/bin/motionsim control presets design.yaml  # the same engine from a terminal
```

- A new kind of block is a class against `motionsim.control.Block`, registered with `register`. It says what it is in words and in mathematics, gives every parameter a unit and bounds, and a test holds it to what can be worked out by hand.
- A scheme sets no figure without the rule it came from (`sources`). Where the rule is this tool's own choice and not a published one, its text says so.
- A field-oriented drive held at a steady point has to end where the settled engine is: `tests/test_control_engine.py` holds that on the six made-up parts. A change that moves it is a change to the loss hand-off, and is said.
- A new exploration has its headline in `tests/test_control_explore.py`, written from the physics and not read from the library, and runs inside the test's budget.
- No loss formula is written in the lab. Losses come from the engine.

The lab's page is the one part of the page written in React (`web/src/control/`, TSX, with React Flow for the diagram and KaTeX for the mathematics). The five steps are not, and stay so.

```
motionsim serve --no-browser     # the engine, on 127.0.0.1:4310
cd web && npm run dev            # the page on 127.0.0.1:4311, asking that engine
cd web && npm test               # the page's tests, the lab's among them
cd web && npm run lint && npx tsc --noEmit
```

`MOTIONSIM_ENGINE` names another engine for `npm run dev`. The lab is fetched when it is first opened: `web/tests/control.build.test.ts` builds the page and fails if React, the diagram or the mathematics come with the first load. The page has no model of its own, here as elsewhere: every figure the lab shows is the engine's.

## The local app and the board reader

`src/motionsim/app/` serves the page with FastAPI on uvicorn where the `app` extra is installed (`make setup` installs it). It works nothing out: every address goes through the service's one dispatch, as on the standard library's server, and `tests/test_app_http.py` holds the two to the same statuses, bodies and headers. An address added to the service is answered by both with no change there. The reader's key is never put in an answer, a log, the store or the words of a refusal.

`src/motionsim/board/` reads a board's design file; `docs/BOARD.md` describes the method. A board in the tests or the examples is made up, and says so in the file. Every figure it gives carries a band and what it rests on. A file that cannot be read is refused in a line: never a fault, never a hang.

```
.venv/bin/pytest -q tests/test_app_*.py tests/test_board_*.py
docker compose up                # the container, as a user starts it
```

## Style

- Python is formatted and linted by ruff (`make format` rewrites, `make lint` only checks), and type-checked by mypy (`make typecheck`). The rules, with the reason for each one left out, are in `pyproject.toml`.
- A function stays within a complexity of 13, 12 branches, 8 returns and 45 statements, and within about 60 lines with its docstring; a module within about 500 lines, unless it is a table. Split by what the code does, not to satisfy the count.
- Words for the user are plain sentences that say what happened and what to do. A refusal names the figure at issue and its unit.
- Comments say why, in plain sentences.
- Every result says what it rests on. A new model term comes with what it leaves out, in `docs/LIMITS.md`.

## A figure you think is wrong

Open an issue with the "A figure is wrong" form. It asks for:

- the figure, the operating point and what MotionSim gives;
- what it should be and where that comes from: a datasheet table or figure (by its title, not the part's name), a measurement and how it was taken, another tool, or the calculation written out;
- the design file or the command, and the version (`motionsim --version`).

A measured loss or junction temperature on real hardware is worth more than anything else here: `docs/VALIDATION.md` says how little of that the tool has been held against.

## Pull requests

- One change to a pull request, with a test.
- `make check` passes.
- The pull request form has the list: tests, golden figures, the page rebuilt, the changelog.
- Commit messages say what changed for someone using the tool, in a plain sentence.

## Releasing

For the maintainer.

1. In `CHANGELOG.md`, rename "Unreleased" to `## [X.Y.Z] - YYYY-MM-DD`, start a new empty "Unreleased" above it, and update the links at the foot.
2. Set the same version in `src/motionsim/__init__.py` (the one place the package reads it from) and in `CITATION.cff`, with the date.
3. `make check`, commit, and merge to main. Wait for CI to pass there; that run also deploys the page.
4. Tag that commit and push the tag:

   ```
   git tag -a vX.Y.Z -m "MotionSim X.Y.Z"
   git push origin vX.Y.Z
   ```

The tag starts the release workflow (`.github/workflows/release.yml`). It stops unless the tag, the package and `CITATION.cff` name the same version and the changelog has that version's entry. Then it runs the tests, builds the source distribution and the wheel, checks them, creates the GitHub release with both attached and the changelog entry as its notes, and publishes to PyPI.

### One-time setup for PyPI

Publishing uses PyPI's trusted publishing: PyPI accepts an upload because it comes from this repository's release workflow, and no password or token is stored anywhere. Until the steps below are done the workflow skips the PyPI job and does everything else.

1. On PyPI, under "Publishing" in the account settings, add a pending publisher: project name `motionsim`, owner `yannickYamo`, repository `MotionSim`, workflow `release.yml`, environment `pypi`.
2. On GitHub, under Settings, Environments, create an environment named `pypi`. Restricting it to tags matching `v*` and adding yourself as a required reviewer puts a confirmation before every upload.
3. On GitHub, under Settings, Secrets and variables, Actions, Variables, add a repository variable `PYPI_PUBLISH` with the value `true`.

A version on PyPI cannot be replaced. If a release is wrong, fix it in a new version.
