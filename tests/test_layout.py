"""Tests for the package layout: each subpackage imports only what its
layer allows, so the detection core can be deployed on its own, and only
the cloud package touches AWS.

Imports are read from the source with ``ast``, not by importing, so a
forbidden import is caught even in a branch no other test runs.
"""

import ast
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "telemetry"
CLOUD = PACKAGE.parent / "cloud"
AWS_LIBRARIES = {"boto3", "botocore", "aiobotocore", "moto", "awslambdaric"}

# What each layer may import beyond the standard library: third-party
# top-level names, and the telemetry subpackages below it.
ALLOWED = {
    "core": ({"shapely"}, {"core"}),
    "sim": (set(), {"core", "sim"}),
    "data": (set(), {"core", "data"}),
    "analysis": (
        {"matplotlib", "numpy", "shapely"},
        {"core", "sim", "data", "analysis"},
    ),
}


# What the Lambda image runs: these may import only the core, AWS's SDK and
# each other. The publisher and local harness run on a workstation.
HANDLER_MODULES = {"messages", "store", "processor", "notifier"}
HANDLER_ALLOWED = {"boto3", "botocore", "telemetry.core"} | {
    f"cloud.{name}" for name in HANDLER_MODULES
}
WORKSTATION_ALLOWED = (
    {"boto3", "botocore", "moto"}
    | {f"telemetry.{sub}" for sub in ("core", "sim", "data")}
    | {f"cloud.{p.stem}" for p in CLOUD.glob("*.py")}
)


def imports(path):
    """Top-level names imported by a module, with ``telemetry.<sub>`` and
    ``cloud.<module>`` kept to two parts."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            modules = [node.module]
        else:
            continue
        for module in modules:
            parts = module.split(".")
            keep = 2 if parts[0] in ("telemetry", "cloud") else 1
            names.add(".".join(parts[:keep]))
    return names


@pytest.mark.parametrize("layer", sorted(ALLOWED))
def test_layer_imports_only_what_it_may(layer):
    """No module imports a layer above its own or an unexpected library."""
    third_party, internal = ALLOWED[layer]
    allowed = third_party | {f"telemetry.{sub}" for sub in internal}
    modules = sorted((PACKAGE / layer).rglob("*.py"))
    assert modules
    for module in modules:
        extra = {
            name
            for name in imports(module) - allowed
            if name not in sys.stdlib_module_names
        }
        assert not extra, f"{module.relative_to(PACKAGE)} imports {sorted(extra)}"


def test_every_module_belongs_to_a_layer():
    """A new module dropped at the top of the package would escape the
    layer checks."""
    loose = [p.name for p in PACKAGE.glob("*.py") if p.name != "__init__.py"]
    assert not loose
    assert {
        p.name for p in PACKAGE.iterdir() if p.is_dir() and p.name != "__pycache__"
    } == set(ALLOWED)


def test_detection_package_imports_no_aws_library():
    """The core and every layer above it run without AWS, so results
    reproduce without an account."""
    for module in sorted(PACKAGE.rglob("*.py")):
        found = {name.split(".")[0] for name in imports(module)} & AWS_LIBRARIES
        assert not found, f"{module.relative_to(PACKAGE)} imports {sorted(found)}"


@pytest.mark.parametrize("module", sorted(p.stem for p in CLOUD.glob("*.py")))
def test_cloud_modules_import_only_what_they_may(module):
    """Handler modules carry only the core into the Lambda image; the
    workstation modules may also read studies and simulate arrival."""
    allowed = HANDLER_ALLOWED if module in HANDLER_MODULES else WORKSTATION_ALLOWED
    extra = {
        name
        for name in imports(CLOUD / f"{module}.py") - allowed
        if name.split(".")[0] not in sys.stdlib_module_names
    }
    assert not extra, f"cloud/{module}.py imports {sorted(extra)}"
