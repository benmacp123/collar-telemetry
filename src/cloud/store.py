"""DynamoDB access for the handlers: state items and incident items.

Two tables. The state table holds one item per deployment per run, keyed
``<run_id>#<deployment_id>``, with the deployment's ``AnimalState`` as
compact JSON and the sequence number of the last message applied. The
incidents table holds one item per incident, keyed by run and incident ID,
with the incident's newest form as JSON plus the fields the notifier and
the comparison filter on. Its stream feeds the notifier.

A processed message is saved in one ``TransactWriteItems``: the state put
is conditional on the stored sequence number being the one before the
message's, so the incidents can never be written without the state that
produced them, and a message that was already applied cannot be applied
twice. JSON is stored as strings rather than DynamoDB maps, since maps
would turn every float into a ``Decimal`` and back.
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime

from telemetry.core.alerts import Incident
from telemetry.core.stream import AnimalState

from cloud.messages import Message

# DynamoDB allows 100 actions per transaction; one is the state put.
MAX_INCIDENTS = 99


@dataclass(frozen=True)
class Tables:
    """The two table names, from the handler's environment.

    Attributes:
        state: The state table.
        incidents: The incidents table.
    """

    state: str
    incidents: str

    @classmethod
    def from_env(cls) -> "Tables":
        """Table names from the handler's environment.

        Returns:
            Tables: From ``STATE_TABLE`` and ``INCIDENTS_TABLE``.
        """
        return cls(os.environ["STATE_TABLE"], os.environ["INCIDENTS_TABLE"])


@dataclass(frozen=True)
class Saved:
    """A deployment's stored state.

    Attributes:
        seq: Sequence number of the last message applied.
        state: The deployment's state after it.
    """

    seq: int
    state: AnimalState


def load_state(client, tables: Tables, key: str) -> Saved | None:
    """Read a deployment's state, consistently.

    Args:
        client: A boto3 DynamoDB client.
        tables: Table names.
        key: The state key (``Message.key``).

    Returns:
        Saved | None: The stored state, or None before the first message.
    """
    item = client.get_item(
        TableName=tables.state, Key={"key": {"S": key}}, ConsistentRead=True
    ).get("Item")
    if item is None:
        return None
    return Saved(
        int(item["seq"]["N"]), AnimalState.from_dict(json.loads(item["state"]["S"]))
    )


def commit(
    client,
    tables: Tables,
    message: Message,
    state: AnimalState,
    incidents: list[Incident],
    processed_at: datetime,
    stored_at: datetime,
) -> None:
    """Save a message's new state and changed incidents in one transaction.

    Incident items are updated, not replaced, so the notifier's
    ``notified_at`` mark survives later changes to the incident, and the
    wall-clock times of the first write (``first_*``) are kept for latency.

    Args:
        client: A boto3 DynamoDB client.
        tables: Table names.
        message: The message applied.
        state: The deployment's state after it.
        incidents: The newest form of each incident it changed.
        processed_at: Wall-clock time the handler started on the message.
        stored_at: Wall-clock time of the write, as near as the handler
            can tell (DynamoDB does not report commit time).

    Raises:
        ValueError: If more incidents changed than one transaction holds.
        botocore.exceptions.ClientError: ``TransactionCanceledException``
            if the stored sequence number is not the one before the
            message's, i.e. another invocation got there first.
    """
    if len(incidents) > MAX_INCIDENTS:
        raise ValueError(
            f"{len(incidents)} incidents in one message for {message.key}; "
            f"at most {MAX_INCIDENTS} fit in a transaction"
        )
    state_put = {
        "TableName": tables.state,
        "Item": {
            "key": {"S": message.key},
            "seq": {"N": str(message.seq)},
            "run_id": {"S": message.run_id},
            "deployment_id": {"S": message.deployment_id},
            "state": {"S": json.dumps(state.to_dict(), separators=(",", ":"))},
            "stored_at": {"S": stored_at.isoformat()},
        },
    }
    if message.seq == 0:
        state_put["ConditionExpression"] = "attribute_not_exists(#key)"
        state_put["ExpressionAttributeNames"] = {"#key": "key"}
    else:
        state_put["ConditionExpression"] = "seq = :previous"
        state_put["ExpressionAttributeValues"] = {
            ":previous": {"N": str(message.seq - 1)}
        }
    actions = [{"Put": state_put}]
    actions += [
        {"Update": _incident_update(tables, message, incident, processed_at, stored_at)}
        for incident in incidents
    ]
    client.transact_write_items(TransactItems=actions)


def _incident_update(
    tables: Tables,
    message: Message,
    incident: Incident,
    processed_at: datetime,
    stored_at: datetime,
) -> dict:
    """The transaction action that writes one incident's newest form.

    Args:
        tables: Table names.
        message: The message that changed it.
        incident: Its newest form.
        processed_at: Wall-clock time the handler started on the message.
        stored_at: Wall-clock time of the write.

    Returns:
        dict: An ``Update`` action for ``TransactWriteItems``.
    """
    sent = message.sent_at.isoformat() if message.sent_at else ""
    return {
        "TableName": tables.incidents,
        "Key": {
            "run_id": {"S": message.run_id},
            "incident_id": {"S": incident.incident_id},
        },
        "UpdateExpression": (
            "SET deployment_id = :deployment, detector = :detector, "
            "#status = :status, incident = :incident, seq = :seq, "
            "first_seq = if_not_exists(first_seq, :seq), "
            "first_sent_at = if_not_exists(first_sent_at, :sent), "
            "first_processed_at = if_not_exists(first_processed_at, :processed), "
            "first_stored_at = if_not_exists(first_stored_at, :stored)"
        ),
        # "status" is a DynamoDB reserved word.
        "ExpressionAttributeNames": {"#status": "status"},
        "ExpressionAttributeValues": {
            ":deployment": {"S": incident.deployment_id},
            ":detector": {"S": incident.detector},
            ":status": {"S": incident.status},
            ":incident": {"S": json.dumps(incident.to_dict(), separators=(",", ":"))},
            ":seq": {"N": str(message.seq)},
            ":sent": {"S": sent},
            ":processed": {"S": processed_at.isoformat()},
            ":stored": {"S": stored_at.isoformat()},
        },
    }


def mark_notified(
    client, tables: Tables, run_id: str, incident_id: str, when: datetime
) -> bool:
    """Record that an incident's notification was sent, once.

    Args:
        client: A boto3 DynamoDB client.
        tables: Table names.
        run_id: The incident's run.
        incident_id: The incident.
        when: Wall-clock time the notification was published.

    Returns:
        bool: True if this call set the mark, False if it was already set.
    """
    try:
        client.update_item(
            TableName=tables.incidents,
            Key={"run_id": {"S": run_id}, "incident_id": {"S": incident_id}},
            UpdateExpression="SET notified_at = :when",
            ConditionExpression="attribute_not_exists(notified_at)",
            ExpressionAttributeValues={":when": {"S": when.isoformat()}},
        )
    except client.exceptions.ConditionalCheckFailedException:
        return False
    return True


def was_notified(client, tables: Tables, run_id: str, incident_id: str) -> bool:
    """Whether an incident's notification has been recorded, read
    consistently (a stream image can predate the mark).

    Args:
        client: A boto3 DynamoDB client.
        tables: Table names.
        run_id: The incident's run.
        incident_id: The incident.

    Returns:
        bool: True if ``notified_at`` is set.
    """
    item = client.get_item(
        TableName=tables.incidents,
        Key={"run_id": {"S": run_id}, "incident_id": {"S": incident_id}},
        ConsistentRead=True,
        ProjectionExpression="notified_at",
    ).get("Item", {})
    return "notified_at" in item


def run_incidents(client, tables: Tables, run_id: str) -> list[dict]:
    """Every incident item stored for a run, for comparison and reports.

    Args:
        client: A boto3 DynamoDB client.
        tables: Table names.
        run_id: The run.

    Returns:
        list[dict]: Raw DynamoDB items.
    """
    items = []
    pages = client.get_paginator("query").paginate(
        TableName=tables.incidents,
        KeyConditionExpression="run_id = :run",
        ExpressionAttributeValues={":run": {"S": run_id}},
        ConsistentRead=True,
    )
    for page in pages:
        items += page["Items"]
    return items
