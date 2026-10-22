"""Build the handlers' Lambda deployment zip and smoke-test it.

Run with ``make lambda-zip``, which runs this inside the pinned
``python:3.14-slim`` image (the Lambda ``python3.14`` runtime's Python) so
the build does not depend on the host's Python. The zip holds the
detection core, ``src/cloud`` and the bundled boundaries, plus the
``lambda`` dependency group installed as manylinux wheels for the Lambda
platform; it is the same content as the local image in
``infra/lambda/Dockerfile``, which stays for emulation only. The image has
no uv, so the Makefile first exports the group from ``uv.lock``, hashes
included, to ``build/requirements-lambda.txt``.

The zip is reproducible: every version and wheel hash comes from
``uv.lock``, and entries are sorted and carry a fixed timestamp, so the
same inputs give the same bytes and Terraform sees no change when nothing
changed. Pip installs wheels only (``--only-binary``) and checks every
hash, so nothing is compiled for the build machine by mistake and no
other file can stand in for a locked wheel.

After writing it, the script unpacks the zip and imports both handlers
from it in a fresh interpreter with site-packages switched off (``-S``),
so a missing file or wheel fails the build instead of the first deploy.

Writes ``build/lambda.zip`` (git-ignored).
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "build" / "lambda.zip"
DEFAULT_REQUIREMENTS = ROOT / "build" / "requirements-lambda.txt"

# The Lambda runtime and architecture the Terraform deploys
# (infra/terraform/lambda.tf); keep them in step. python3.14 runs on
# Amazon Linux 2023 (glibc 2.34), so any wheel up to manylinux_2_34
# loads; numpy has no manylinux2014 wheel for 3.14. pip does not widen a
# platform tag to older ones, so each is listed (uv's --python-platform
# would, but the build image has pip, not uv).
PYTHON_VERSION = "3.14"
PLATFORMS = [f"manylinux_2_{minor}_x86_64" for minor in (34, 28, 27, 26, 17)] + [
    "manylinux2014_x86_64"
]

# Source paths copied into the zip, relative to the repository root, and
# where each lands. Only what the handlers import (tests/test_layout.py).
SOURCES = {
    "src/telemetry/__init__.py": "telemetry/__init__.py",
    "src/telemetry/core": "telemetry/core",
    "src/cloud": "cloud",
    "data/raw/boundaries": "boundaries",
}

# 1980-01-01, the earliest time a zip entry can carry.
FIXED_TIME = (1980, 1, 1, 0, 0, 0)

SMOKE_TEST = """
from shapely.geometry import Point
import boto3
import cloud.notifier
import cloud.processor
fence = cloud.processor._fence("etosha")
assert fence is not None
print("imports ok; boto3", boto3.__version__)
"""


def main() -> None:
    """Build the zip, then smoke-test it."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--requirements",
        type=Path,
        default=DEFAULT_REQUIREMENTS,
        help="hashed export of the lambda group (make lambda-requirements)",
    )
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        package = Path(tmp) / "package"
        install(package, args.requirements)
        copy_sources(package)
        write_zip(package, args.out)
    smoke_test(args.out)
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.1f} MB)")


def install(package: Path, requirements: Path) -> None:
    """Install the Lambda requirements as wheels for the Lambda platform.

    Args:
        package: Directory to install into.
        requirements: Hashed requirements file exported from uv.lock.

    Raises:
        subprocess.CalledProcessError: If pip fails, for example when a
            requirement has no wheel for the platform or a hash does not
            match.
    """
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--quiet",
            "--no-cache-dir",
            "--disable-pip-version-check",
            "--require-hashes",
            "--requirement",
            str(requirements),
            "--target",
            str(package),
            "--python-version",
            PYTHON_VERSION,
            "--implementation",
            "cp",
            "--only-binary=:all:",
        ]
        + [flag for platform in PLATFORMS for flag in ("--platform", platform)],
        check=True,
    )


def copy_sources(package: Path) -> None:
    """Copy the handlers' code and the boundaries into the package.

    Args:
        package: The package directory.
    """
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for source, target in SOURCES.items():
        src, dst = ROOT / source, package / target
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=ignore)
        else:
            shutil.copy2(src, dst)


def write_zip(package: Path, out: Path) -> None:
    """Zip the package reproducibly.

    Bytecode caches are left out: Lambda's file system is read-only, and
    pip's caches hold build-machine paths and times.

    Args:
        package: The package directory.
        out: The zip to write.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(
        path
        for path in package.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    )
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            entry = zipfile.ZipInfo(path.relative_to(package).as_posix(), FIXED_TIME)
            entry.compress_type = zipfile.ZIP_DEFLATED
            # rw-r--r-- regular file; Lambda only needs to read them.
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, path.read_bytes())


def smoke_test(out: Path) -> None:
    """Import both handlers from the unpacked zip alone.

    Args:
        out: The zip to test.

    Raises:
        subprocess.CalledProcessError: If an import or the boundary load
            fails.
    """
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(out) as archive:
            archive.extractall(tmp)
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": tmp,
            "PYTHONDONTWRITEBYTECODE": "1",
            "BOUNDARIES_DIR": str(Path(tmp) / "boundaries"),
            "AWS_DEFAULT_REGION": "eu-west-2",
        }
        subprocess.run(
            [sys.executable, "-S", "-c", SMOKE_TEST], check=True, env=env, cwd=tmp
        )


if __name__ == "__main__":
    main()
