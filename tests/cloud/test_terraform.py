"""Tests that the Terraform, the deploy zip and the handlers agree on
names, settings and entry points, which `terraform validate` cannot
check."""

import importlib
import importlib.util
import re
from pathlib import Path

from cloud import cost, local, notifier

ROOT = Path(__file__).resolve().parents[2]
TERRAFORM = ROOT / "infra" / "terraform"


def _terraform() -> str:
    """All the Terraform, with the name prefix's default filled in.

    Returns:
        str: The concatenated ``*.tf`` files.
    """
    text = "\n".join(path.read_text() for path in sorted(TERRAFORM.glob("*.tf")))
    prefix = re.search(
        r'variable "name_prefix" \{.*?default\s*=\s*"([^"]+)"', text, re.S
    )
    return text.replace("${var.name_prefix}", prefix.group(1))


def _lambda_zip():
    """The deploy-zip build script, loaded as a module.

    Returns:
        module: ``scripts/lambda_zip.py``.
    """
    spec = importlib.util.spec_from_file_location(
        "lambda_zip", ROOT / "scripts" / "lambda_zip.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resource_names_match_the_local_run():
    """The deployed queue, tables and topic carry the names the local moto
    run uses, so the two setups cannot drift apart."""
    text = _terraform()
    for name in (local.QUEUE, local.TABLES.state, local.TABLES.incidents, local.TOPIC):
        assert f'name = "{name}"' in re.sub(r"\s+=\s+", " = ", text)


def test_runtime_matches_the_wheels_in_the_zip():
    """The Lambda runtime and architecture are the ones the zip's wheels
    were installed for."""
    text = _terraform()
    build = _lambda_zip()
    runtime = re.search(r'runtime\s*=\s*"([^"]+)"', text).group(1)
    architecture = re.search(r'architecture\s*=\s*"([^"]+)"', text).group(1)
    assert runtime == f"python{build.PYTHON_VERSION}"
    assert all(platform.endswith(architecture) for platform in build.PLATFORMS)


def test_handlers_exist():
    """Each handler setting names a function the zip's packages define."""
    for path in re.findall(r'handler\s*=\s*"([^"]+)"', _terraform()):
        module, function = path.rsplit(".", 1)
        assert callable(getattr(importlib.import_module(module), function))


def test_environment_matches_what_the_handlers_read():
    """The environment variables set are the ones the handlers read, and
    the boundaries directory is where the zip puts them."""
    text = _terraform()
    for name in (
        "STATE_TABLE",
        "INCIDENTS_TABLE",
        "TOPIC_ARN",
        "NOTIFY_ENABLED",
        "BOUNDARIES_DIR",
        "QUEUE_URL",
    ):
        assert re.search(rf"\b{name}\s*=", text)
    boundaries = re.search(r'BOUNDARIES_DIR\s*=\s*"([^"]+)"', text).group(1)
    assert boundaries == f"/var/task/{_lambda_zip().SOURCES['data/raw/boundaries']}"


def test_filters_pass_the_notified_detector():
    """The stream trigger and the email subscription both filter on the
    detector the notifier publishes."""
    text = _terraform()
    assert f'S = ["{notifier.NOTIFIED_DETECTOR}"]' in text
    assert f'detector = ["{notifier.NOTIFIED_DETECTOR}"]' in text


def test_cost_report_uses_the_deployed_memory_and_names():
    """The cost report prices Lambda time at each function's configured
    memory and reads metrics by the deployed function names."""
    text = _terraform()
    for role, function in cost.FUNCTIONS.items():
        block = re.search(
            rf'resource "aws_lambda_function" "{role}" \{{(.*?)\n\}}', text, re.S
        ).group(1)
        assert f'"{function}"' in block
        memory = int(re.search(r"memory_size\s*=\s*(\d+)", block).group(1))
        assert memory == cost.MEMORY_MB[role]


def test_clock_schedule_is_off_by_default_and_sends_its_scheduled_time():
    """The live clock deploys disabled, so replays see no extra ticks, and
    passes the scheduled time, so a retried invocation sends the same
    ticks."""
    text = _terraform()
    enabled = re.search(
        r'variable "clock_enabled" \{.*?default\s*=\s*(\w+)', text, re.S
    ).group(1)
    assert enabled == "false"
    assert 'state               = var.clock_enabled ? "ENABLED" : "DISABLED"' in text
    assert 'until  = "<aws.scheduler.scheduled-time>"' in text
