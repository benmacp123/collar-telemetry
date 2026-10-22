# Every target runs from committed files; only the tf-plan, tf-apply,
# tf-destroy, cloud-aws and cloud-leftovers targets need an AWS account.
# `make help` lists them.

.PHONY: help install setup test lint format format-check profile replay \
	evaluate results sweep cloud-sizing cloud-moto lambda-requirements \
	lambda-image cloud-local lambda-zip lock tf-check tf-fmt tf-plan \
	tf-apply tf-output tf-destroy cloud-aws cloud-leftovers prices cloud-usage cloud-cost all

help: ## List the targets and what each writes
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-16s %s\n", $$1, $$2}'


# uv manages the venv at venv/ (the portfolio's convention) rather than
# .venv; activate it before the other targets.
export UV_PROJECT_ENVIRONMENT = venv

install: ## Sync venv/ to uv.lock exactly (all groups)
	uv sync --frozen

lock: ## Re-resolve uv.lock after editing pyproject.toml
	uv lock

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

carcass: ## Measure collars on vulture carcasses -> results/carcass/
	PYTHONPATH=src python scripts/carcass_profile.py

cloud-sizing: ## Run the cloud slicing locally, check it -> results/cloud/
	PYTHONPATH=src python scripts/cloud_sizing.py

cloud-moto: ## Every study through the handlers on in-process moto (~20 min)
	PYTHONPATH=src python scripts/cloud_local.py --mode moto

COMPOSE = docker compose -f infra/local/compose.yaml

# The lambda group exported from uv.lock, with hashes, for the zip build,
# which runs pip in a container without uv. Exported, not committed, so
# pyproject.toml stays the one place each version is pinned.
LAMBDA_REQUIREMENTS = build/requirements-lambda.txt

lambda-requirements: ## Export the lambda group -> build/requirements-lambda.txt
	mkdir -p build
	uv export --frozen --only-group lambda --no-emit-project --no-header \
		--output-file $(LAMBDA_REQUIREMENTS) > /dev/null

# The emulation image's base is Python 3.13 and uv.lock only records 3.14
# wheels, so the image gets the same versions without hashes and pip picks
# its cp313 wheels.
lambda-image: ## Build the handlers' Lambda image (needs Docker)
	mkdir -p build
	uv export --frozen --only-group lambda --no-emit-project --no-header \
		--no-hashes --output-file build/requirements-lambda-image.txt > /dev/null
	docker build --network host -f infra/lambda/Dockerfile \
		-t collar-telemetry-lambda .

# Every jackal, and one vulture so the email path runs (jackals raise no
# likely_death incidents).
cloud-local: lambda-image ## Jackals + 1 vulture through the Lambda containers (Docker)
	$(COMPOSE) up -d --wait
	PYTHONPATH=src python scripts/cloud_local.py --mode docker \
		--study jackals --study vultures --only vultures=LTH_BLVU_68357; \
		status=$$?; $(COMPOSE) down; exit $$status

# Deploy package and Terraform, both run in pinned images so nothing needs
# installing on the host. --network host: the bridge network has no DNS.
PYTHON_IMAGE = python:3.14-slim@sha256:fbecd461fc72d21b2143c6eaba25143738079154a6d0ea3da3aec724f50eed4a
TF_IMAGE = hashicorp/terraform:1.16.6@sha256:bfffc1ded5fbf0a17beaaf22eb4793980abdb19d0761ff6a3a0efb2ab4d9b316
DOCKER_RUN = docker run --rm --network host --user $$(id -u):$$(id -g) \
	-e HOME=/tmp -v $(CURDIR):/repo -w /repo
TF = $(DOCKER_RUN) -w /repo/infra/terraform $(TF_IMAGE)

lambda-zip: lambda-requirements ## Build the deploy zip -> build/lambda.zip (needs Docker)
	$(DOCKER_RUN) $(PYTHON_IMAGE) python scripts/lambda_zip.py \
		--requirements $(LAMBDA_REQUIREMENTS)

tf-fmt: ## Format the Terraform (needs Docker)
	$(TF) fmt -recursive

tf-check: ## terraform fmt -check and validate, as CI runs them (needs Docker)
	$(TF) fmt -check -recursive -diff
	$(TF) init -backend=false -input=false
	$(TF) validate

# These read or change your AWS account, so run them yourself: they need
# credentials in ~/.aws and infra/terraform/terraform.tfvars. apply and
# destroy run interactively (-it) so Terraform asks before changing
# anything.
TF_AWS = $(DOCKER_RUN) -v $(HOME)/.aws:/tmp/.aws:ro -e AWS_PROFILE \
	-w /repo/infra/terraform
NOTIFY ?= false

tf-plan: lambda-zip ## terraform plan against your AWS account (needs Docker, credentials)
	$(TF) init -input=false
	$(TF_AWS) $(TF_IMAGE) plan -out=tfplan

tf-apply: lambda-zip ## Deploy; NOTIFY=true sends likely_death emails (needs Docker, credentials)
	$(TF) init -input=false
	$(TF_AWS) -it $(TF_IMAGE) apply -var notify_enabled=$(NOTIFY)
	$(MAKE) tf-output

# The outputs include the account ID: build/ is git-ignored.
tf-output: ## Save terraform output -json -> build/terraform-outputs.json
	mkdir -p build
	$(TF) output -json > build/terraform-outputs.json

tf-destroy: ## Remove everything deployed (needs Docker, credentials)
	$(TF_AWS) -it $(TF_IMAGE) destroy

# ARGS go to scripts/cloud_aws.py run, e.g. ARGS="--label smoke --study jackals".
cloud-aws: ## Publish to the deployed stack, compare -> results/cloud/aws-<label>.json
	PYTHONPATH=src python scripts/cloud_aws.py run $(ARGS)

cloud-leftovers: ## After tf-destroy: list anything of the project still in AWS
	PYTHONPATH=src python scripts/cloud_aws.py leftovers

# Optional: the snapshot is committed. Public price files, no account needed.
prices: ## Fetch AWS list prices -> data/prices/aws-eu-west-2.json
	python scripts/fetch_prices.py

cloud-usage: ## After a deployed run: CloudWatch usage -> results/cloud/usage-aws.json (credentials)
	PYTHONPATH=src python scripts/cloud_cost.py fetch

cloud-cost: ## Price the usage, project live mode -> results/cloud/cost.json, COST.md
	PYTHONPATH=src python scripts/cloud_cost.py compute

all: install format lint test ## install, format, lint, test
