# One command for everything CI runs: `make check`. `make help` lists the rest.
# For Linux and macOS; on Windows, run the commands of a target by hand (CONTRIBUTING.md).

PYTHON ?= python3
VENV ?= .venv
BIN := $(abspath $(VENV))/bin

.DEFAULT_GOAL := help
.PHONY: help setup format lint typecheck test test-fast package audit page page-check check clean

help: ## what each target does
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F ':.*## ' '{printf "  %-11s %s\n", $$1, $$2}'

setup: ## a virtual environment with the package, every tool, the commit hooks and the page's build tools
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -e ".[dev]"
	$(BIN)/pre-commit install
	cd web && npm ci

format: ## rewrite the code in the project's format and apply the safe lint fixes
	$(BIN)/ruff format src tests web/scripts
	$(BIN)/ruff check --fix src tests web/scripts

lint: ## format and lint, changing nothing
	$(BIN)/ruff format --check src tests web/scripts
	$(BIN)/ruff check src tests web/scripts

typecheck: ## mypy on the package
	$(BIN)/mypy src/motionsim

test: ## the whole suite, in parallel, with the coverage floor
	$(BIN)/pytest -q -n auto --cov=motionsim --cov-report=term-missing:skip-covered

test-fast: ## the suite without coverage, stopping at the first failure
	$(BIN)/pytest -q -n auto -x

package: ## build the source distribution and the wheel into dist/, and check both
	$(BIN)/validate-pyproject pyproject.toml
	$(BIN)/python -c "import shutil; shutil.rmtree('dist', ignore_errors=True)"
	$(BIN)/python -m build
	$(BIN)/twine check --strict dist/*
	$(BIN)/check-wheel-contents dist/*.whl

audit: ## known advisories against the installed Python libraries and the packages the page ships
	$(BIN)/pip-audit --local --skip-editable
	cd web && npm audit --omit=dev

page: ## rebuild the page into src/motionsim/webui (commit the result)
	cd web && PATH="$(BIN):$$PATH" npm run build

page-check: ## the page's lint, types, tests and build; the built page is the committed one; the browser checks
	cd web && npm run lint
	cd web && npm run format:check
	cd web && npx tsc --noEmit
	cd web && npm test
	$(MAKE) page
	@test -z "$$(git status --porcelain -- src/motionsim/webui)" || (git status --short -- src/motionsim/webui; echo "the built page is not what the sources build: commit it"; exit 1)
	cd web && PYTHON="$(BIN)/python" npm run engine-check
	cd web && npx playwright install chromium
	cd web && npm run journey

check: lint typecheck test package audit page-check ## everything CI runs

clean: ## remove the caches the targets above leave behind
	$(BIN)/python -c "import shutil; [shutil.rmtree(d, ignore_errors=True) for d in ('dist', 'build', 'htmlcov', '.pytest_cache', '.mypy_cache', '.ruff_cache')]"
