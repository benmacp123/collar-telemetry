"""GPS-collar telemetry alerts.

Subpackages, each depending only on those above it:

- ``core``: detection logic the cloud handlers run (no AWS imports).
- ``sim``: the local replay harness.
- ``data``: loading the committed studies.
- ``analysis``: scoring and reporting.
"""
