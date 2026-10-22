"""Clock Lambda: turn a scheduled time into one tick per deployment.

Live, a collar that stops sending sends no slices, so nothing would run
its clock and its gap alert would never be raised. EventBridge Scheduler
invokes this handler on a fixed rate (deployed disabled; see
``infra/terraform/clock.tf``) with the run to tick and the scheduled time.
It lists the run's deployments from the state table and sends each a tick
(``Message`` with no sequence number) in the deployment's own message
group, so the processor applies it in order with that collar's slices.

The schedule's time, not the wall clock, is the tick's ``until``, so a
retried invocation sends the same ticks; within SQS's five-minute window
the queue drops them as duplicates, and after it the processor finds the
clock already there.
"""

import json
import os
from datetime import datetime

import boto3

from telemetry.core.slices import Slice

from cloud.messages import Message, UploadSettings, fifo_dedup_id
from cloud.store import Tables

# SQS's limit on entries per SendMessageBatch call.
MAX_BATCH = 10


def handler(event: dict, context) -> dict:
    """Lambda entry point for the schedule.

    Args:
        event: ``run_id`` and ``until`` (the schedule's
            ``<aws.scheduler.scheduled-time>``, ISO 8601).
        context: The Lambda context; unused.

    Returns:
        dict: ``ticks``, the number sent.
    """
    del context
    sent = send_ticks(
        boto3.client("dynamodb"),
        boto3.client("sqs"),
        Tables.from_env(),
        os.environ["QUEUE_URL"],
        event["run_id"],
        datetime.fromisoformat(event["until"]),
    )
    return {"ticks": sent}


def ticks(client, tables: Tables, run_id: str, until: datetime) -> list[Message]:
    """A tick for each deployment the run has state for.

    A deployment with no state yet has sent nothing, so it has no clock
    to run.

    Args:
        client: A boto3 DynamoDB client.
        tables: Table names.
        run_id: The run to tick.
        until: Time to run each clock to.

    Returns:
        list[Message]: Ticks, by deployment ID.
    """
    found = []
    pages = client.get_paginator("scan").paginate(
        TableName=tables.state,
        FilterExpression="run_id = :run",
        ProjectionExpression="deployment_id, settings",
        ExpressionAttributeValues={":run": {"S": run_id}},
    )
    for page in pages:
        for item in page["Items"]:
            settings = json.loads(item["settings"]["S"])
            found.append(
                Message(
                    run_id,
                    None,
                    settings["taxon"],
                    UploadSettings.from_dict(settings["uploads"]),
                    settings["boundary"],
                    Slice(item["deployment_id"]["S"], (), until),
                )
            )
    return sorted(found, key=lambda message: message.deployment_id)


def send_ticks(
    dynamodb, sqs, tables: Tables, queue_url: str, run_id: str, until: datetime
) -> int:
    """Send every deployment of a run a tick to ``until``.

    Args:
        dynamodb: A boto3 DynamoDB client.
        sqs: A boto3 SQS client.
        tables: Table names.
        queue_url: The FIFO slices queue.
        run_id: The run to tick.
        until: Time to run each clock to.

    Returns:
        int: Ticks sent.

    Raises:
        RuntimeError: If SQS rejects any entry, so the scheduler retries
            the whole invocation (resent ticks are harmless).
    """
    messages = ticks(dynamodb, tables, run_id, until)
    for start in range(0, len(messages), MAX_BATCH):
        batch = messages[start : start + MAX_BATCH]
        response = sqs.send_message_batch(
            QueueUrl=queue_url,
            Entries=[
                {
                    "Id": str(index),
                    "MessageBody": message.to_json(),
                    "MessageGroupId": message.key,
                    "MessageDeduplicationId": fifo_dedup_id(message.dedup_id),
                }
                for index, message in enumerate(batch)
            ],
        )
        if response.get("Failed"):
            raise RuntimeError(f"SQS rejected ticks: {response['Failed']}")
    return len(messages)
