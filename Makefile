# Every target runs from committed files; none needs an account or the
# network. `make help` lists them.

.PHONY: help install setup test lint format format-check profile replay \
	evaluate results sweep cloud-sizing all

help: ## List the targets and what each writes
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-14s %s\n", $$1, $$2}'


install: ## Install pinned dependencies into the active venv
	python -m pip install --upgrade pip &&\
		python -m pip install -r requirements.txt

setup: install ## Same as install


test: ## Run the tests with coverage
	PYTHONPATH=src python -m pytest -vv --cov=telemetry tests/

lint: ## Pylint the package; docstrings everywhere, tests included
	PYTHONPATH=src python -m pylint --disable=R,C src/telemetry
	# Every module, class and function needs a docstring, tests included.
	PYTHONPATH=src python -m pylint --disable=all \
		--enable=missing-module-docstring,missing-class-docstring,missing-function-docstring \
		src scripts tests

format: ## Format with black
	black src/ tests/ scripts/

format-check: ## Check formatting without changing files
	black --check src/ tests/ scripts/


profile: ## Profile each study -> data/PROFILE.md
	PYTHONPATH=src python scripts/profile_studies.py

replay: ## Replay every study and scenario -> results/replay/
	PYTHONPATH=src python scripts/replay.py

evaluate: ## Score the replays -> results/evaluation/, results/figures/
	PYTHONPATH=src python scripts/evaluate.py

results: replay evaluate ## replay, then evaluate (about 5 min)

sweep: ## Threshold sweep on the vulture tuning set -> results/sweep/
	PYTHONPATH=src python scripts/sweep.py

cloud-sizing: ## Run the cloud slicing locally, check it -> results/cloud/
	PYTHONPATH=src python scripts/cloud_sizing.py


all: install format lint test ## install, format, lint, test
