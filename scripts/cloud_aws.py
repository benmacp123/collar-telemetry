"""Run studies through the deployed stack and check it against the replay
runner, or check that ``terraform destroy`` left nothing behind.

Needs AWS credentials (``AWS_PROFILE``) and, for ``run``, the stack's
outputs saved by ``make tf-output``. Unlike ``cloud_local.py`` there is no
poller: the publisher sends every slice to the real queue, and AWS's own
triggers run the processor and, from the table's stream, the notifier.

``run`` publishes every chosen study and scenario first, so collars run in
parallel, then waits for the queue to drain and compares each run's stored
incidents with ``replay()`` (and ``incidents.jsonl`` when written). With
``--resend-every N`` every Nth slice is sent twice more: once with its own
deduplication ID, which the queue should drop, and once with a new one,
which the processor should skip. ``--expect-notify`` (the deliberate email
test, with ``notify_enabled`` applied) waits for the notifier to mark every
``likely_death`` incident.

Writes ``results/cloud/aws-<label>.json``, with wall-clock latencies:
sent-to-stored includes time queued behind the rest of the run, since
everything is published up front. The file holds no account details. The
script exits non-zero on any difference, dead letter or missing
notification, after writing the file.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3

from telemetry.data.studies import STUDIES
from telemetry.sim.arrival import SCENARIOS
from telemetry.sim.replay import DEFAULT_SEED, replay

from cloud import deployed, local, publisher
from cloud.store import run_incidents

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "results" / "cloud"
OUTPUTS = ROOT / "build" / "terraform-outputs.json"
CLOUD_SCENARIOS = ["satellite_daily", "gsm"]
RESEND_SUFFIX = "#resend"


def parse_args() -> argparse.Namespace:
    """Read the command line.

    Returns:
        argparse.Namespace: ``command`` and its options.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="publish, drain and compare")
    run.add_argument("--label", required=True, help="names the results file")
    run.add_argument(
        "--study", action="append", choices=[study.slug for study in STUDIES]
    )
    run.add_argument("--scenario", action="append", choices=list(SCENARIOS))
    run.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="STUDY=DEPLOYMENT",
        help="limit a study to these deployments (repeatable)",
    )
    run.add_argument("--resend-every", type=int, default=0)
    run.add_argument("--expect-notify", action="store_true")
    left = commands.add_parser("leftovers", help="look for anything not destroyed")
    left.add_argument("--region", default="eu-west-2")
    left.add_argument("--project", default="collar-telemetry")
    left.add_argument("--prefix", default="collar")
    return parser.parse_args()


def selected(args) -> list[tuple]:
    """The studies to run, each narrowed by ``--only``.

    Args:
        args: The parsed command line.

    Returns:
        list[tuple]: ``(study, deployments, fixes, fence)`` per study.
    """
    only = {}
    for pair in args.only:
        slug, deployment_id = pair.split("=", 1)
        only.setdefault(slug, set()).add(deployment_id)
    chosen = []
    for study in STUDIES:
        if args.study and study.slug not in args.study:
            continue
        deployments, fixes, _ = study.load(RAW)
        if study.slug in only:
            keep = only[study.slug]
            deployments = [d for d in deployments if d.deployment_id in keep]
            fixes = [f for f in fixes if f.deployment_id in keep]
        chosen.append((study, deployments, fixes, study.fence(RAW)))
    return chosen


def publish_run(sqs, stack, study, deployments, fixes, scenario, resend_every):
    """Send one study and scenario's slices, then the resends.

    Resends go after every original, so the new-ID copy reaches the
    processor after its collar's later slices and must be skipped as
    already applied.

    Args:
        sqs: A boto3 SQS client.
        stack: The deployed stack.
        study: The study.
        deployments: Its deployments.
        fixes: Its fixes.
        scenario: The arrival scenario.
        resend_every: Resend every Nth slice; 0 for none.

    Returns:
        dict: Messages published and resent.
    """
    messages = list(publisher.messages_for(study, deployments, fixes, scenario))
    sent = publisher.publish(sqs, stack.queue_url, messages)
    again = messages[resend_every - 1 :: resend_every] if resend_every else []
    publisher.publish(sqs, stack.queue_url, again)
    publisher.publish(sqs, stack.queue_url, again, suffix=RESEND_SUFFIX)
    return {"messages": sent, "resent_each_way": len(again)}


def check_run(aws, stack, study, deployments, fixes, fence, scenario, args) -> dict:
    """Compare one run's stored incidents with the replay.

    Args:
        aws: boto3 clients by service name.
        stack: The deployed stack.
        study: The study.
        deployments: Its deployments.
        fixes: Its fixes.
        fence: Its geofence, or None.
        scenario: The arrival scenario.
        args: The parsed command line.

    Returns:
        dict: Counts, the comparison and latencies.
    """
    run = publisher.run_id(study, scenario)
    expected = replay(deployments, fixes, scenario, DEFAULT_SEED, fence=fence)
    likely = {i.incident_id for i in expected.incidents if i.detector == "likely_death"}
    unnotified = set()
    if args.expect_notify:
        unnotified = deployed.wait_for_notified(
            aws["dynamodb"], stack.tables, run, likely
        )
    ids = {d.deployment_id for d in deployments}
    items = [
        item
        for item in run_incidents(aws["dynamodb"], stack.tables, run)
        if json.loads(item["incident"]["S"])["deployment_id"] in ids
    ]
    comparison = local.compare(items, expected.incidents)
    return {
        "study": study.slug,
        "scenario": scenario.name,
        "deployments": len(deployments),
        **{key: comparison[key] for key in ("replay_incidents", "stored_incidents")},
        "matches_replay": not any(
            comparison[key] for key in ("missing", "extra", "different")
        ),
        "differences": {
            key: comparison[key][:20] for key in ("missing", "extra", "different")
        },
        "matches_incidents_jsonl": _matches_file(study, scenario, ids, items),
        "likely_death_incidents": len(likely),
        "notified_incidents": sum("notified_at" in item for item in items),
        "not_notified": sorted(unnotified),
        "latency_s": local.latencies(items),
    }


def _matches_file(study, scenario, ids, items) -> bool | None:
    """Whether the stored incidents equal ``make replay``'s file, for the
    deployments in the run.

    Args:
        study: The study.
        scenario: The scenario.
        ids: The deployment IDs run.
        items: Stored incident items for those deployments.

    Returns:
        bool | None: The answer, or None if the file has not been written.
    """
    path = ROOT / "results" / "replay" / study.slug / scenario.name / "incidents.jsonl"
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    want = {
        row["incident_id"]: row
        for row in map(json.loads, lines)
        if row["deployment_id"] in ids
    }
    got = {
        item["incident_id"]["S"]: json.loads(item["incident"]["S"]) for item in items
    }
    return want == got


def run(args) -> int:
    """Publish, drain, compare and write the results.

    Args:
        args: The parsed command line.

    Returns:
        int: The exit status: 0 if everything matched.
    """
    stack = deployed.load_stack(OUTPUTS)
    aws = {
        name: boto3.client(name, region_name=stack.region)
        for name in ("sqs", "dynamodb")
    }
    studies = selected(args)
    scenarios = [SCENARIOS[name] for name in args.scenario or CLOUD_SCENARIOS]
    # Wall-clock bounds of the run, so its usage can be read back from
    # CloudWatch for the cost estimate.
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    published = {}
    for study, deployments, fixes, _ in studies:
        for scenario in scenarios:
            published[study.slug, scenario.name] = publish_run(
                aws["sqs"],
                stack,
                study,
                deployments,
                fixes,
                scenario,
                args.resend_every,
            )
            print(
                f"published {study.slug}/{scenario.name}: {published[study.slug, scenario.name]}"
            )
    publish_seconds = time.perf_counter() - started
    deployed.wait_for_drain(
        aws["sqs"],
        stack.queue_url,
        report=lambda depth: print(
            f"{time.perf_counter() - started:7.0f} s: {depth} in the queue"
        ),
    )
    drain_seconds = time.perf_counter() - started
    drained_at = datetime.now(timezone.utc)
    runs = []
    for study, deployments, fixes, fence in studies:
        for scenario in scenarios:
            result = check_run(
                aws, stack, study, deployments, fixes, fence, scenario, args
            )
            runs.append(published[study.slug, scenario.name] | result)
            print(f"{study.slug}/{scenario.name}: {json.dumps(runs[-1])}")
    summary = {
        "label": args.label,
        "started_at": started_at.isoformat(timespec="seconds"),
        "drained_at": drained_at.isoformat(timespec="seconds"),
        "region": stack.region,
        "publish_s": round(publish_seconds),
        "publish_to_drained_s": round(drain_seconds),
        "dead_letters": deployed.queue_depth(aws["sqs"], stack.dead_letter_queue_url),
        "notify_failures": deployed.queue_depth(aws["sqs"], stack.notify_failures_url),
        "runs": runs,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"aws-{args.label}.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    problems = [
        f"{r['study']}/{r['scenario']}: {name}"
        for r in runs
        for name, bad in (
            ("differs from the replay", not r["matches_replay"]),
            ("differs from incidents.jsonl", r["matches_incidents_jsonl"] is False),
            ("notifications missing", bool(r["not_notified"])),
        )
        if bad
    ]
    problems += [
        f"{summary[key]} in {key}"
        for key in ("dead_letters", "notify_failures")
        if summary[key]
    ]
    for problem in problems:
        print(f"PROBLEM: {problem}", file=sys.stderr)
    return 1 if problems else 0


def check_leftovers(args) -> int:
    """Print anything of the project's still in the account.

    Args:
        args: The parsed command line.

    Returns:
        int: The exit status: 0 if nothing was found.
    """
    clients = {
        name: boto3.client(name, region_name=args.region)
        for name in ("resourcegroupstaggingapi", "logs", "iam", "budgets", "sts")
    }
    found = deployed.leftovers(clients, args.project, args.prefix)
    for name in found:
        print(f"left behind: {name}")
    if not found:
        print("nothing left behind")
    return 1 if found else 0


def main():
    """Run the chosen command."""
    args = parse_args()
    # Print progress as it happens when output goes to a file.
    sys.stdout.reconfigure(line_buffering=True)
    sys.exit(run(args) if args.command == "run" else check_leftovers(args))


if __name__ == "__main__":
    main()
