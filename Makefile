# Every target runs from committed files; only the tf-plan, tf-apply,
# tf-destroy, cloud-aws and cloud-leftovers targets need an AWS account.
# `make help` lists them.

.PHONY: help install setup test lint format format-check profile replay \
	evaluate results sweep cloud-sizing cloud-moto lambda-image cloud-local \
	lambda-zip tf-check tf-fmt tf-plan tf-apply tf-output tf-destroy \
	cloud-aws cloud-leftovers all

help: ## List the targets and what each writes
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  %-16s %s\n", $$1, $$2}'


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

# Deploy package and Terraform, both run in pinned images so nothing needs
# installing on the host. --network host: the bridge network has no DNS.
PYTHON_IMAGE = python:3.14-slim@sha256:fbecd461fc72d21b2143c6eaba25143738079154a6d0ea3da3aec724f50eed4a
TF_IMAGE = hashicorp/terraform:1.16.6@sha256:bfffc1ded5fbf0a17beaaf22eb4793980abdb19d0761ff6a3a0efb2ab4d9b316
DOCKER_RUN = docker run --rm --network host --user $$(id -u):$$(id -g) \
	-e HOME=/tmp -v $(CURDIR):/repo -w /repo
TF = $(DOCKER_RUN) -w /repo/infra/terraform $(TF_IMAGE)

lambda-zip: ## Build the deploy zip -> build/lambda.zip (needs Docker)
	$(DOCKER_RUN) $(PYTHON_IMAGE) python scripts/lambda_zip.py

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


all: install format lint test ## install, format, lint, test
