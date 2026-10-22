"""Cost per animal-month of the deployed stack, from metered usage.

``fetch`` (needs AWS credentials, ``AWS_PROFILE``) reads per-minute
CloudWatch metrics for the stack's resources over the session's day and
writes ``results/cloud/usage-aws.json``. AWS keeps them after ``terraform
destroy``, but one-minute points only for 15 days. The file holds resource
names and counts, no account details.

``compute`` needs no account: it totals the full run's minutes from that
file, counts the run's messages and SQS requests by publishing them to a
counter instead of a queue, prices it all with the committed snapshot
(``data/prices/aws-eu-west-2.json``), and projects live mode. It checks
that the metered sends equal the messages the run published, then writes
``results/cloud/cost.json`` and ``results/cloud/COST.md``.
"""

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3

from telemetry.data.studies import STUDIES
from telemetry.sim.arrival import SCENARIOS
from telemetry.sim.replay import DEFAULT_SEED, timelines

from cloud import cost, publisher

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "results" / "cloud"
USAGE = OUT / "usage-aws.json"
PRICES = ROOT / "data" / "prices" / "aws-eu-west-2.json"
CLOUD_SCENARIOS = ["satellite_daily", "gsm"]
# Any fixed send time of the same length as a real one gives the same
# body sizes; publish stamps microseconds, so this does too.
SENT_AT = datetime(2026, 10, 22, 11, 11, 27, 500000, tzinfo=timezone.utc)


def parse_args() -> argparse.Namespace:
    """Read the command line.

    Returns:
        argparse.Namespace: ``command`` and its options.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("fetch", help="read CloudWatch (needs AWS)")
    fetch.add_argument("--region", default="eu-west-2")
    fetch.add_argument(
        "--day", default=None, help="UTC date to read (default: the full run's)"
    )
    compute = commands.add_parser("compute", help="price the usage (offline)")
    compute.add_argument("--label", default="full", help="the run to price")
    return parser.parse_args()


def run_file(label: str) -> dict:
    """A deployed run's results, as written by ``cloud_aws.py run``.

    Args:
        label: The run's label.

    Returns:
        dict: The results file.
    """
    return json.loads((OUT / f"aws-{label}.json").read_text(encoding="utf-8"))


def fetch(args):
    """Read the day's metrics and write the usage file.

    Args:
        args: The parsed command line.
    """
    day = args.day or run_file("full")["started_at"][:10]
    start = datetime.fromisoformat(day).replace(tzinfo=timezone.utc)
    end = min(start + timedelta(days=1), datetime.now(timezone.utc))
    cloudwatch = boto3.client("cloudwatch", region_name=args.region)
    usage = cost.fetch_usage(cloudwatch, start, end)
    usage["region"] = args.region
    USAGE.write_text(json.dumps(usage, indent=2) + "\n", encoding="utf-8")
    for key, entry in usage["metrics"].items():
        print(
            f"{key}: {len(entry['points'])} minutes, {sum(entry['points'].values()):,.0f}"
        )


def offline_counts() -> tuple[dict, list[dict]]:
    """Publish every study and scenario of the full run to a counter.

    Returns:
        tuple[dict, list[dict]]: SQS counts for the whole run, published
        study by study as ``cloud_aws.py`` did; and per study and
        scenario, the slices, animal-months and slices per animal-month.
    """
    counter = cost.SendCounter()
    runs = []
    for study in STUDIES:
        deployments, fixes, _ = study.load(RAW)
        for name in CLOUD_SCENARIOS:
            scenario = SCENARIOS[name]
            days = sum(
                cost.watched_days(timeline)
                for timeline in timelines(deployments, fixes, scenario, DEFAULT_SEED)
            )
            before = counter.messages
            publisher.publish(
                counter,
                "counted",
                publisher.messages_for(study, deployments, fixes, scenario),
                clock=lambda: SENT_AT,
            )
            slices = counter.messages - before
            months = days / cost.DAYS_PER_MONTH
            runs.append(
                {
                    "study": study.slug,
                    "scenario": name,
                    "deployments": len(deployments),
                    "slices": slices,
                    "animal_months": months,
                    "slices_per_animal_month": slices / months,
                }
            )
    return counter.counts(), runs


def compute(args):
    """Price the run, project live mode and write the reports.

    Args:
        args: The parsed command line.

    Raises:
        SystemExit: If the metered sends differ from the messages the run
            published.
    """
    usage = json.loads(USAGE.read_text(encoding="utf-8"))
    prices = cost.load_prices(PRICES)
    run = run_file(args.label)
    span = cost.window(run["started_at"], run["drained_at"])
    used = cost.metered(usage, span)
    sent, runs = offline_counts()
    published = sum(entry["messages"] for entry in run["runs"])
    months = sum(entry["animal_months"] for entry in runs)
    bill = cost.run_bill(used, sent, prices)
    projection = cost.live_projection(used, sent, prices, months)
    busy = [
        cost.window(other["started_at"], other["drained_at"])
        for other in (run_file(label) for label in ("smoke", "full"))
    ]
    quiet = cost.idle(usage, busy)
    if quiet["empty_receives_per_minute"] is not None:
        quiet["usd_per_month"] = (
            quiet["requests_per_month"] * prices["prices"]["sqs_fifo_request"]["usd"]
        )
    report = {
        "label": args.label,
        "window": span,
        "prices": {
            "file": str(PRICES.relative_to(ROOT)),
            "retrieved": prices["retrieved"],
        },
        "checks": {
            "published": published,
            "counted": sent["messages"],
            "metered_sent": used["messages_sent"],
            "metered_received": used["messages_received"],
            "processor_errors": used["processor_errors"],
        },
        "metered": used,
        "sqs_counted": sent,
        "runs": runs,
        "animal_months": months,
        "run_bill": bill,
        "run_usd_per_animal_month": bill["total_usd"] / months,
        "live_projection": projection,
        "idle": quiet,
        "free_tier": cost.free_tier_animals(
            projection, prices, quiet.get("requests_per_month", 0)
        ),
    }
    (OUT / "cost.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "COST.md").write_text(markdown(report), encoding="utf-8")
    print(markdown(report))
    if not published == sent["messages"] == used["messages_sent"]:
        raise SystemExit(
            f"messages differ: published {published}, counted {sent['messages']}, "
            f"metered {used['messages_sent']:.0f}"
        )


def markdown(report: dict) -> str:
    """The report as a short Markdown page.

    Args:
        report: As written to ``cost.json``.

    Returns:
        str: The page.
    """
    bill = report["run_bill"]
    live = report["live_projection"]
    months = report["animal_months"]
    lines = [
        "# Cost of the deployed run",
        "",
        "Generated by `make cloud-cost` from `usage-aws.json` (CloudWatch,",
        f"the `{report['label']}` run's minutes {report['window'][0]} to",
        f"{report['window'][1]}) and the list prices in `{report['prices']['file']}`",
        f"(retrieved {report['prices']['retrieved']}, eu-west-2, USD, before free tier).",
        "",
        f"The run covered {months:,.0f} animal-months ({len({r['study'] for r in report['runs']})} studies",
        f"under {len({r['scenario'] for r in report['runs']})} scenarios) in {report['checks']['published']:,} slices.",
        "",
        "## The run as billed",
        "",
        "| Line | Quantity | USD | Basis |",
        "| --- | ---: | ---: | --- |",
    ]
    for name, line in bill["lines"].items():
        lines.append(
            f"| {name} | {line['quantity']:,.2f} | {line['usd']:.4f} | {line['basis']} |"
        )
    lines += [
        f"| **total** | | **{bill['total_usd']:.4f}** | |",
        "",
        f"Per animal-month as run: **${report['run_usd_per_animal_month']:.6f}**",
        f"(${report['run_usd_per_animal_month'] * 1000:.3f} per 1,000 animal-months).",
        "",
        "## Live mode (projection, provisional)",
        "",
        "Live, each daily slice gets its own invocation. Low spreads the run's",
        "processor time and logs over slices; high charges each slice a whole",
        "invocation's worth.",
        f"Slices per animal-month: {live['slices_per_animal_month']:.1f}.",
        "",
        "| Line | Low USD / animal-month | High USD / animal-month |",
        "| --- | ---: | ---: |",
    ]
    for name in live["low"]["usd"]:
        lines.append(
            f"| {name} | {live['low']['usd'][name]:.6f} | {live['high']['usd'][name]:.6f} |"
        )
    lines += [
        f"| **total** | **{live['low']['total_usd']:.6f}** | "
        f"**{live['high']['total_usd']:.6f}** |",
        "",
    ]
    quiet = report["idle"]
    if quiet["empty_receives_per_minute"] is None:
        lines.append("Idle: no quiet minutes found in the usage file.")
    else:
        lines += [
            "## Idle",
            "",
            f"Over {quiet['quiet_minutes']} quiet minutes the queue trigger made a median",
            f"{quiet['empty_receives_per_minute']:.1f} empty receives a minute:",
            f"{quiet['requests_per_month']:,.0f} requests and "
            f"${quiet['usd_per_month']:.2f} a month",
            "with nothing to do, before the SQS free tier.",
        ]
    free = report["free_tier"]
    lines += [
        "",
        "## Free tier",
        "",
        "On the high projection, the always-free allowances cover the Lambda,",
        f"SQS and log usage of about {free['limit']:,.0f} animals a month, after",
        "idle polling has taken its share of the SQS allowance. DynamoDB",
        "on-demand request units have no free tier.",
        "",
    ]
    return "\n".join(lines)


def main():
    """Run the chosen command."""
    args = parse_args()
    if args.command == "fetch":
        fetch(args)
    else:
        compute(args)


if __name__ == "__main__":
    main()
