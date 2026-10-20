"""The cloud runner: Lambda handlers, the publisher and a local harness.

This is the only package that imports boto3. The handlers (``processor``,
``notifier``) and the modules they use (``messages``, ``store``) import
only ``telemetry.core`` from the detection package, so the Lambda image
carries the core and nothing above it; ``tests/test_layout.py`` enforces
this. The publisher and the local harness run on a workstation and may
also read the studies and simulate arrival.
"""
