# Every target runs from committed files; none needs an account or the
# network. `make help` lists them.

.PHONY: help install setup test lint format format-check profile replay \
	evaluate results sweep cloud-sizing cloud-moto lambda-image cloud-local \
	all

help: ## List the targets and what each writes
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-14s %s\n", $$1, $$2}'


install: ## Install pinned dependencies into the active venv
	python -m pip install --upgrade pip &&\
		python -m pip install -r requirements.txt

setup: install ## Same as install


test: ## Run the tests with coverage
	PYTHONPATH=src python -m pytest -vv --cov=telemetry --cov=cloud tests/

lint: ## Pylint the packages; docstrings everywhere, tests included
	PYTHONPATH=src python -m pylint --disable=R,C src/telemetry src/cloud
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

cloud-moto: ## Every study through the handlers on in-process moto (~20 min)
	PYTHONPATH=src python scripts/cloud_local.py --mode moto

COMPOSE = docker compose -f infra/local/compose.yaml

lambda-image: ## Build the handlers' Lambda image (needs Docker)
	docker build --network host -f infra/lambda/Dockerfile \
		-t collar-telemetry-lambda .

# Every jackal, and one vulture so the email path runs (jackals raise no
# likely_death incidents).
cloud-local: lambda-image ## Jackals + 1 vulture through the Lambda containers (Docker)
	$(COMPOSE) up -d --wait
	PYTHONPATH=src python scripts/cloud_local.py --mode docker \
		--study jackals --study vultures --only vultures=LTH_BLVU_68357; \
		status=$$?; $(COMPOSE) down; exit $$status


all: install format lint test ## install, format, lint, test
