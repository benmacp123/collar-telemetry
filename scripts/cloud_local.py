"""Run the cloud handlers end to end against moto and check them against
the replay runner.

Two modes, each needing no AWS account:

- ``--mode moto`` (``make cloud-moto``): moto in-process, handlers called
  directly. Fast enough for every study.
- ``--mode docker`` (``make cloud-local``): the ``motoserver/moto``
  container plus the processor and notifier in Lambda base-image
  containers (``infra/local/compose.yaml``), called through the runtime
  interface emulator. This is the packaged code on the real Lambda
  runtime. ``make cloud-local`` runs every jackal and one vulture with
  ``likely_death`` incidents (jackals raise none), so the email path runs
  in the containers too.

For each study and scenario the publisher sends the run's slices,
resending some to test de-duplication (``feed``), the local poller feeds
them to the processor and the stream to the notifier, and the stored
incidents are compared with ``replay()`` (and with ``incidents.jsonl``
when ``make replay`` has written it). Notification is on, and the
notifications that reach the stand-in inbox are checked: one per
``likely_death`` incident.

Writes ``results/cloud/local-<mode>.json``; the script stops with an error
on any difference. Wall-clock latencies are printed, not written: locally
they measure the emulator, and the file should stay identical between runs.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

import boto3

from telemetry.data.studies import STUDIES
from telemetry.sim.arrival import SCENARIOS
from telemetry.sim.replay import DEFAULT_SEED, replay

from cloud import local, notifier, processor, publisher
from cloud.store import run_incidents

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "results" / "cloud"
CLOUD_SCENARIOS = ["satellite_daily", "gsm"]
RESEND_EVERY = 97
MOTO_URL = "http://localhost:5000"
PROCESSOR_URL = "http://localhost:9001"
NOTIFIER_URL = "http://localhost:9002"


def parse_args() -> argparse.Namespace:
    """Read the command line.

    Returns:
        argparse.Namespace: ``mode``, ``study``, ``scenario`` and ``only``.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mode", choices=["moto", "docker"], default="moto")
    parser.add_argument(
        "--study", action="append", choices=[study.slug for study in STUDIES]
    )
    parser.add_argument("--scenario", action="append", choices=list(SCENARIOS))
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="STUDY=DEPLOYMENT",
        help="limit a study to these deployments (repeatable)",
    )
    return parser.parse_args()


def clients() -> dict:
    """boto3 clients for every service the run touches.

    Returns:
        dict: Clients keyed by service name.
    """
    return {
        name: boto3.client(name)
        for name in ("sqs", "dynamodb", "dynamodbstreams", "sns")
    }


def invokers(mode: str, aws: dict, topic_arn: str) -> tuple:
    """How the poller calls the two handlers.

    Args:
        mode: ``moto`` (call in-process) or ``docker`` (call the
            emulators).
        aws: Clients from ``clients``.
        topic_arn: The alert topic, for in-process notification.

    Returns:
        tuple: The processor and notifier ``Invoke`` functions.
    """
    if mode == "docker":
        return local.http_invoker(PROCESSOR_URL), local.http_invoker(NOTIFIER_URL)
    return (
        lambda event: processor.process_records(
            event["Records"], aws["dynamodb"], local.TABLES
        ),
        lambda event: notifier.notify_records(
            event["Records"], aws["dynamodb"], aws["sns"], local.TABLES, topic_arn
        ),
    )


def run_one(mode, study, deployments, fixes, fence, scenario) -> dict:
    """Run one study and scenario through the handlers and check it.

    Args:
        mode: ``moto`` or ``docker``.
        study: The study.
        deployments: Its deployments.
        fixes: Its fixes.
        fence: Its geofence, or None.
        scenario: The arrival scenario.

    Returns:
        dict: Counts and the comparison with the replay.

    Raises:
        AssertionError: If the stored incidents or the notifications
            differ from what the replay implies.
    """
    started = time.perf_counter()
    aws = clients()
    resources = local.create_resources(aws["sqs"], aws["dynamodb"], aws["sns"])
    poller = local.Poller(
        aws["sqs"],
        aws["dynamodbstreams"],
        resources,
        *invokers(mode, aws, resources.topic_arn),
    )
    messages = publisher.messages_for(study, deployments, fixes, scenario)
    counts = local.feed(
        aws["sqs"], resources, poller, messages, resend_every=RESEND_EVERY
    )
    run = publisher.run_id(study, scenario)
    items = run_incidents(aws["dynamodb"], local.TABLES, run)
    expected = replay(deployments, fixes, scenario, DEFAULT_SEED, fence=fence)
    comparison = local.compare(items, expected.incidents)
    file_matches = _matches_file(study, scenario, deployments, items)
    notifications = local.read_notifications(aws["sqs"], resources)
    likely = sum(i.detector == "likely_death" for i in expected.incidents)
    notified = Counter(_incident_line(body) for body in notifications)
    result = {
        "study": study.slug,
        "scenario": scenario.name,
        "deployments": len(deployments),
        "messages": counts["published"],
        "resent_same_dedup_id": counts["resent_same_id"],
        "resent_new_dedup_id": counts["resent_new_id"],
        "received_by_processor": counts["received"],
        "processor_failures": counts["failed"],
        "stream_records": counts["stream_records"],
        **{key: comparison[key] for key in ("replay_incidents", "stored_incidents")},
        "matches_replay": not any(
            comparison[key] for key in ("missing", "extra", "different")
        ),
        "matches_incidents_jsonl": file_matches,
        "likely_death_incidents": likely,
        "notifications": len(notifications),
        "notified_incidents": len(notified),
    }
    print(
        f"{study.slug}/{scenario.name}: {json.dumps(result)}\n"
        f"  latency (emulator, not AWS): {local.latencies(items)}; "
        f"{time.perf_counter() - started:.0f} s"
    )
    assert result["matches_replay"], comparison
    assert file_matches is not False, f"{run} differs from incidents.jsonl"
    # The queue drops a resend with the same ID; one with a new ID reaches
    # the processor, which must skip it without changing anything.
    assert counts["received"] == counts["published"] + counts["resent_new_id"]
    assert len(notified) == likely and len(notifications) == likely, notified
    return result


def _matches_file(study, scenario, deployments, items) -> bool | None:
    """Whether the stored incidents equal ``make replay``'s file, for the
    deployments in the run.

    Args:
        study: The study.
        scenario: The scenario.
        deployments: The deployments run (``--only`` may narrow them).
        items: Stored incident items for the run.

    Returns:
        bool | None: The answer, or None if the file has not been written.
    """
    path = ROOT / "results" / "replay" / study.slug / scenario.name / "incidents.jsonl"
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    ids = {deployment.deployment_id for deployment in deployments}
    want = {
        row["incident_id"]: row
        for row in map(json.loads, lines)
        if row["deployment_id"] in ids
    }
    got = {
        item["incident_id"]["S"]: json.loads(item["incident"]["S"]) for item in items
    }
    return want == got


def _incident_line(body: str) -> str:
    """The incident ID in a notification's text.

    Args:
        body: A notification body (``notifier._body``).

    Returns:
        str: The ID.
    """
    return next(
        line.removeprefix("Incident: ")
        for line in body.splitlines()
        if line.startswith("Incident: ")
    )


def reset_moto(attempts: int = 30) -> None:
    """Empty the moto server, so each run starts from nothing, waiting for
    it to come up first.

    Args:
        attempts: Tries, a second apart.

    Raises:
        urllib.error.URLError: If the server never answers.
    """
    request = urllib.request.Request(f"{MOTO_URL}/moto-api/reset", method="POST")
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=30):
                return
        except urllib.error.URLError:
            if attempt == attempts - 1:
                raise
            time.sleep(1)


def main():
    """Run the chosen studies and scenarios and write the results."""
    args = parse_args()
    # moto accepts any credentials; these keep boto3 off real ones.
    os.environ.update(
        AWS_ACCESS_KEY_ID="testing",
        AWS_SECRET_ACCESS_KEY="testing",
        AWS_DEFAULT_REGION="eu-west-2",
    )
    os.environ.pop("AWS_PROFILE", None)
    # Print progress as it happens when output goes to a file.
    sys.stdout.reconfigure(line_buffering=True)
    studies = [s for s in STUDIES if not args.study or s.slug in args.study]
    scenarios = [SCENARIOS[name] for name in args.scenario or CLOUD_SCENARIOS]
    results = []
    only = {}
    for pair in args.only:
        slug, deployment_id = pair.split("=", 1)
        only.setdefault(slug, set()).add(deployment_id)
    for study in studies:
        deployments, fixes, _ = study.load(RAW)
        if study.slug in only:
            deployments = [
                d for d in deployments if d.deployment_id in only[study.slug]
            ]
            fixes = [f for f in fixes if f.deployment_id in only[study.slug]]
        fence = study.fence(RAW)
        for scenario in scenarios:
            if args.mode == "docker":
                os.environ["AWS_ENDPOINT_URL"] = MOTO_URL
                reset_moto()
                results.append(
                    run_one(args.mode, study, deployments, fixes, fence, scenario)
                )
            else:
                # Imported here so the Docker mode does not need moto.
                from moto import mock_aws  # pylint: disable=import-outside-toplevel

                with mock_aws():
                    results.append(
                        run_one(args.mode, study, deployments, fixes, fence, scenario)
                    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"local-{args.mode}.json").write_text(
        json.dumps(results, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
