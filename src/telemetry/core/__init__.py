"""Detection core: what the cloud handlers run.

Records, cleaning, detectors, the alert lifecycle, per-animal state and
the clock that drives them. Imports only the standard library, shapely and
other ``telemetry.core`` modules (enforced by ``tests/test_layout.py``), so
it deploys to Lambda as it is.
"""
