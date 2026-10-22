"""Workstation helpers for a run against the deployed stack.

``make cloud-aws`` publishes to the real queue and lets AWS's own triggers
run the handlers, so unlike ``local`` there is no poller: these helpers
read Terraform's outputs, wait for the queue to empty, wait for the
notifier, and after ``terraform destroy`` look for anything left behind.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from botocore.exceptions import ClientError

from cloud.store import Tables, run_incidents

# What a queue holds, counting messages a Lambda is working on (not
# visible) and any waiting out a delay.
DEPTH_ATTRIBUTES = [
    "ApproximateNumberOfMessages",
    "ApproximateNumberOfMessagesNotVisible",
    "ApproximateNumberOfMessagesDelayed",
]


@dataclass(frozen=True)
class Stack:
    """What the run needs from ``terraform output -json``.

    Attributes:
        queue_url: The FIFO slice queue.
        dead_letter_queue_url: Slices that failed five times.
        notify_failures_url: Stream batches the notifier gave up on.
        tables: The state and incident tables.
    """

    queue_url: str
    dead_letter_queue_url: str
    notify_failures_url: str
    tables: Tables

    @property
    def region(self) -> str:
        """The region, read from the queue URL (``sqs.<region>.amazonaws.com``).

        Returns:
            str: The region name.
        """
        return urlparse(self.queue_url).hostname.split(".")[1]


def load_stack(path: Path) -> Stack:
    """Read the stack from a saved ``terraform output -json``.

    Args:
        path: The saved outputs (``make tf-output``).

    Returns:
        Stack: The queue URLs and table names.

    Raises:
        FileNotFoundError: If the outputs have not been saved.
        KeyError: If an output is missing (an older Terraform state).
    """
    outputs = {
        name: entry["value"]
        for name, entry in json.loads(path.read_text(encoding="utf-8")).items()
    }
    return Stack(
        outputs["queue_url"],
        outputs["dead_letter_queue_url"],
        outputs["notify_failures_url"],
        Tables(outputs["state_table"], outputs["incidents_table"]),
    )


def queue_depth(sqs, queue_url: str) -> int:
    """Messages in a queue, waiting, in flight or delayed.

    Args:
        sqs: A boto3 SQS client.
        queue_url: The queue.

    Returns:
        int: The approximate total.
    """
    attributes = sqs.get_queue_attributes(
        QueueUrl=queue_url, AttributeNames=DEPTH_ATTRIBUTES
    )["Attributes"]
    return sum(int(attributes.get(name, 0)) for name in DEPTH_ATTRIBUTES)


def wait_for_drain(
    sqs,
    queue_url: str,
    poll_seconds: float = 20,
    quiet_polls: int = 3,
    timeout_seconds: float = 6 * 3600,
    sleep: Callable[[float], None] = time.sleep,
    report: Callable[[int], None] = lambda depth: None,
) -> int:
    """Wait until the queue is empty and stays empty.

    SQS's counts are approximate and can lag by about a minute, so one
    zero reading is not enough: the queue must read empty ``quiet_polls``
    times in a row. A message is deleted only after the processor
    returns, so an empty queue means every slice has been applied or
    dead-lettered.

    Args:
        sqs: A boto3 SQS client.
        queue_url: The slice queue.
        poll_seconds: Time between readings.
        quiet_polls: Empty readings in a row needed.
        timeout_seconds: Give up after this long.
        sleep: Waits between readings, for tests.
        report: Called with each reading, for progress.

    Returns:
        int: Readings taken.

    Raises:
        TimeoutError: If the queue has not drained in time.
    """
    readings, quiet, waited = 0, 0, 0.0
    while quiet < quiet_polls:
        if waited > timeout_seconds:
            raise TimeoutError(f"{queue_url} still busy after {waited:.0f} s")
        depth = queue_depth(sqs, queue_url)
        readings += 1
        report(depth)
        quiet = quiet + 1 if depth == 0 else 0
        if quiet < quiet_polls:
            sleep(poll_seconds)
            waited += poll_seconds
    return readings


def wait_for_notified(
    dynamodb,
    tables: Tables,
    run_id: str,
    incident_ids: set[str],
    poll_seconds: float = 15,
    timeout_seconds: float = 600,
    sleep: Callable[[float], None] = time.sleep,
) -> set[str]:
    """Wait until the notifier has marked every given incident.

    The notifier runs from the table's stream after the processor has
    written, so it can finish after the queue has drained.

    Args:
        dynamodb: A boto3 DynamoDB client.
        tables: Table names.
        run_id: The run.
        incident_ids: Incidents that should be notified.
        poll_seconds: Time between readings.
        timeout_seconds: Stop waiting after this long.
        sleep: Waits between readings, for tests.

    Returns:
        set[str]: The given incidents still not notified (empty on success).
    """
    waited = 0.0
    while True:
        notified = {
            item["incident_id"]["S"]
            for item in run_incidents(dynamodb, tables, run_id)
            if "notified_at" in item
        }
        missing = incident_ids - notified
        if not missing or waited >= timeout_seconds:
            return missing
        sleep(poll_seconds)
        waited += poll_seconds


def leftovers(clients: dict, project: str, prefix: str) -> list[str]:
    """Anything of the project's still in the account after ``destroy``.

    The tagging API finds tagged resources, but a Lambda still running
    when ``destroy`` deletes its log group writes a new, untagged one, and
    IAM roles and budgets are global and schedules take no tags, so those
    are looked up by name too.
    The tagging API can list a just-deleted resource for a while: check
    again before treating a hit as left behind.

    Args:
        clients: boto3 clients keyed ``resourcegroupstaggingapi``, ``logs``,
            ``iam``, ``budgets``, ``sts`` and ``scheduler``.
        project: The ``Project`` tag value.
        prefix: The resource name prefix (Terraform's ``name_prefix``).

    Returns:
        list[str]: ARNs or names found; empty when the account is clean.
    """
    found = []
    pages = clients["resourcegroupstaggingapi"].get_paginator("get_resources")
    for page in pages.paginate(TagFilters=[{"Key": "Project", "Values": [project]}]):
        found += [r["ResourceARN"] for r in page["ResourceTagMappingList"]]
    groups = clients["logs"].get_paginator("describe_log_groups")
    for page in groups.paginate(logGroupNamePrefix=f"/aws/lambda/{prefix}-"):
        found += [g["logGroupName"] for g in page["logGroups"]]
    for role in ("processor", "notifier", "clock", "scheduler"):
        role = f"{prefix}-{role}"
        try:
            clients["iam"].get_role(RoleName=role)
            found.append(f"iam role {role}")
        except ClientError as error:
            if error.response["Error"]["Code"] != "NoSuchEntity":
                raise
    schedule = f"{prefix}-clock"
    try:
        clients["scheduler"].get_schedule(Name=schedule)
        found.append(f"schedule {schedule}")
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    account = clients["sts"].get_caller_identity()["Account"]
    budget = f"{prefix}-monthly"
    try:
        clients["budgets"].describe_budget(AccountId=account, BudgetName=budget)
        found.append(f"budget {budget}")
    except ClientError as error:
        if error.response["Error"]["Code"] != "NotFoundException":
            raise
    return sorted(set(found))
