"""Tests for the package layout: each subpackage imports only what its
layer allows, so the detection core can be deployed on its own.

Imports are read from the source with ``ast``, not by importing, so a
forbidden import is caught even in a branch no other test runs.
"""

import ast
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "telemetry"

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


def imports(path):
    """Top-level names imported by a module, with ``telemetry.<sub>`` kept
    to two parts."""
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
            names.add(".".join(parts[:2]) if parts[0] == "telemetry" else parts[0])
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
