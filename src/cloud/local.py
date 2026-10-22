"""Local stand-ins for what AWS does around the handlers.

moto emulates SQS, DynamoDB (with Streams) and SNS, but does not run the
event-source mappings that feed Lambda. This module does that part: it
creates the resources, polls the FIFO queue and hands batches to the
processor as SQS events, reads the incidents table's stream and hands
records to the notifier, deletes what succeeded and retries what failed.
The trigger settings themselves (batch size, retries, dead-lettering) are
only proven by a real deploy.

Handlers are called through an ``Invoke`` function, so the same poller
drives them in-process (tests, the moto run) or through the Lambda
runtime interface emulator in Docker.
"""

import json
import time
import urllib.request
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from telemetry.core.alerts import Incident

from cloud.messages import Message
from cloud.publisher import publish
from cloud.store import Tables

Invoke = Callable[[dict], dict]

QUEUE = "collar-slices.fifo"
NOTIFICATIONS = "collar-notifications"
TOPIC = "collar-alerts"
TABLES = Tables("collar-state", "collar-incidents")
# Receives before the poller gives up on a message, as a redrive policy
# would send it to a dead-letter queue.
MAX_RECEIVES = 5


@dataclass(frozen=True)
class Resources:
    """What ``create_resources`` made.

    Attributes:
        queue_url: The FIFO slice queue.
        stream_arn: The incidents table's stream.
        topic_arn: The alert topic.
        notifications_url: A standard queue subscribed to the topic, which
            stands in for the email inbox.
    """

    queue_url: str
    stream_arn: str
    topic_arn: str
    notifications_url: str


def create_resources(sqs, dynamodb, sns, visibility_seconds: int = 5) -> Resources:
    """Create the queue, tables, stream and topic the handlers use.

    Mirrors the Terraform: a FIFO queue without content-based
    deduplication (the publisher sets IDs), on-demand tables, a
    ``NEW_AND_OLD_IMAGES`` stream on the incidents table, and a topic with
    a ``potential_death`` filter on its subscription.

    Args:
        sqs: A boto3 SQS client.
        dynamodb: A boto3 DynamoDB client.
        sns: A boto3 SNS client.
        visibility_seconds: Queue visibility timeout; short locally, so a
            failed message is retried soon.

    Returns:
        Resources: Their URLs and ARNs.
    """
    queue_url = sqs.create_queue(
        QueueName=QUEUE,
        Attributes={
            "FifoQueue": "true",
            "ContentBasedDeduplication": "false",
            "VisibilityTimeout": str(visibility_seconds),
        },
    )["QueueUrl"]
    dynamodb.create_table(
        TableName=TABLES.state,
        KeySchema=[{"AttributeName": "key", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "key", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    stream_arn = dynamodb.create_table(
        TableName=TABLES.incidents,
        KeySchema=[
            {"AttributeName": "run_id", "KeyType": "HASH"},
            {"AttributeName": "incident_id", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "run_id", "AttributeType": "S"},
            {"AttributeName": "incident_id", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
        StreamSpecification={
            "StreamEnabled": True,
            "StreamViewType": "NEW_AND_OLD_IMAGES",
        },
    )["TableDescription"]["LatestStreamArn"]
    topic_arn = sns.create_topic(Name=TOPIC)["TopicArn"]
    notifications_url = sqs.create_queue(QueueName=NOTIFICATIONS)["QueueUrl"]
    notifications_arn = sqs.get_queue_attributes(
        QueueUrl=notifications_url, AttributeNames=["QueueArn"]
    )["Attributes"]["QueueArn"]
    sns.subscribe(
        TopicArn=topic_arn,
        Protocol="sqs",
        Endpoint=notifications_arn,
        Attributes={
            "RawMessageDelivery": "true",
            "FilterPolicy": json.dumps({"detector": ["potential_death"]}),
        },
    )
    return Resources(queue_url, stream_arn, topic_arn, notifications_url)


def http_invoker(url: str) -> Invoke:
    """Call a handler through the Lambda runtime interface emulator.

    Args:
        url: Base URL of the container, e.g. ``http://localhost:9001``.

    Returns:
        Invoke: Posts an event and returns the handler's response.
    """
    endpoint = f"{url}/2015-03-31/functions/function/invocations"

    def invoke(event: dict) -> dict:
        """Post one event to the emulator.

        Args:
            event: The Lambda event.

        Returns:
            dict: The handler's return value.

        Raises:
            RuntimeError: If the handler raised instead of returning.
        """
        # Stream records carry datetimes from boto3; Lambda would send text.
        body = json.dumps(event, default=str).encode()
        request = urllib.request.Request(endpoint, data=body, method="POST")
        with urllib.request.urlopen(request, timeout=300) as response:
            result = json.loads(response.read())
        if not isinstance(result, dict) or "batchItemFailures" not in result:
            raise RuntimeError(f"handler error: {result}")
        return result

    return invoke


class StreamReader:
    """Reads new records from every shard of a DynamoDB stream."""

    def __init__(self, streams, stream_arn: str):
        """Start reading from the beginning of the stream.

        Args:
            streams: A boto3 DynamoDB Streams client.
            stream_arn: The stream.
        """
        self.streams = streams
        self.stream_arn = stream_arn
        self.iterators: dict[str, str | None] = {}

    def read(self) -> list[dict]:
        """Every record added since the last read, shard by shard.

        Returns:
            list[dict]: Stream records in shard order.
        """
        shards = self.streams.describe_stream(StreamArn=self.stream_arn)[
            "StreamDescription"
        ]["Shards"]
        for shard in shards:
            if shard["ShardId"] not in self.iterators:
                self.iterators[shard["ShardId"]] = self.streams.get_shard_iterator(
                    StreamArn=self.stream_arn,
                    ShardId=shard["ShardId"],
                    ShardIteratorType="TRIM_HORIZON",
                )["ShardIterator"]
        records = []
        for shard_id, iterator in self.iterators.items():
            while iterator:
                page = self.streams.get_records(ShardIterator=iterator, Limit=1000)
                records += page["Records"]
                iterator = page.get("NextShardIterator")
                if not page["Records"]:
                    break
            self.iterators[shard_id] = iterator
        return records


class Poller:
    """Feeds the queue to the processor and the stream to the notifier,
    as Lambda's event-source mappings would."""

    def __init__(
        self,
        sqs,
        streams,
        resources: Resources,
        processor: Invoke,
        notifier: Invoke,
        batch_size: int = 10,
    ):
        """Set up a poller.

        Args:
            sqs: A boto3 SQS client.
            streams: A boto3 DynamoDB Streams client.
            resources: The queue and stream to poll.
            processor: Invokes the processor handler.
            notifier: Invokes the notifier handler.
            batch_size: Most messages per processor invocation (SQS allows
                up to 10 per receive).
        """
        self.sqs = sqs
        self.resources = resources
        self.processor = processor
        self.notifier = notifier
        self.batch_size = batch_size
        self.stream = StreamReader(streams, resources.stream_arn)
        self.pending: list[dict] = []
        self.counts = Counter()

    def drain(self, idle_seconds: float = 0.2) -> Counter:
        """Run until the queue is empty and every stream record is handled.

        Args:
            idle_seconds: Pause when nothing is visible but messages are
                still in flight (waiting out a visibility timeout).

        Returns:
            Counter: ``received``, ``failed``, ``invocations``,
            ``stream_records`` and ``notifier_failures`` so far.

        Raises:
            RuntimeError: If a message has been received ``MAX_RECEIVES``
                times, which a deployed queue would dead-letter.
        """
        while True:
            messages = self.sqs.receive_message(
                QueueUrl=self.resources.queue_url,
                MaxNumberOfMessages=self.batch_size,
                AttributeNames=["All"],
            ).get("Messages", [])
            if messages:
                self._process(messages)
            self._notify()
            if not messages:
                if self._queue_empty() and not self.pending:
                    return self.counts
                time.sleep(idle_seconds)

    def _process(self, messages: list[dict]) -> None:
        """Invoke the processor on one batch and settle each message.

        Args:
            messages: Messages from ``receive_message``.

        Raises:
            RuntimeError: If a message has been received too often.
        """
        self.counts["received"] += len(messages)
        self.counts["invocations"] += 1
        event = {
            "Records": [
                {
                    "messageId": message["MessageId"],
                    "receiptHandle": message["ReceiptHandle"],
                    "body": message["Body"],
                    "attributes": message.get("Attributes", {}),
                    "eventSource": "aws:sqs",
                }
                for message in messages
            ]
        }
        failed = {
            failure["itemIdentifier"]
            for failure in self.processor(event)["batchItemFailures"]
        }
        done = [m for m in messages if m["MessageId"] not in failed]
        if done:
            self.sqs.delete_message_batch(
                QueueUrl=self.resources.queue_url,
                Entries=[
                    {"Id": str(i), "ReceiptHandle": m["ReceiptHandle"]}
                    for i, m in enumerate(done)
                ],
            )
        for message in messages:
            if message["MessageId"] not in failed:
                continue
            self.counts["failed"] += 1
            if int(message["Attributes"]["ApproximateReceiveCount"]) >= MAX_RECEIVES:
                raise RuntimeError(
                    f"message {message['MessageId']} failed {MAX_RECEIVES} times"
                )

    def _notify(self) -> None:
        """Hand new stream records to the notifier, keeping any it failed
        on (and those after) for the next call."""
        new = self.stream.read()
        self.counts["stream_records"] += len(new)
        self.pending += new
        if not self.pending:
            return
        failures = self.notifier({"Records": self.pending})["batchItemFailures"]
        if not failures:
            self.pending = []
            return
        self.counts["notifier_failures"] += 1
        first = failures[0]["itemIdentifier"]
        index = next(
            i
            for i, record in enumerate(self.pending)
            if record["dynamodb"]["SequenceNumber"] == first
        )
        self.pending = self.pending[index:]

    def _queue_empty(self) -> bool:
        """Whether the queue has nothing visible and nothing in flight.

        Returns:
            bool: True when drained.
        """
        attributes = self.sqs.get_queue_attributes(
            QueueUrl=self.resources.queue_url,
            AttributeNames=[
                "ApproximateNumberOfMessages",
                "ApproximateNumberOfMessagesNotVisible",
            ],
        )["Attributes"]
        return all(int(value) == 0 for value in attributes.values())


def feed(
    sqs,
    resources: Resources,
    poller: Poller,
    messages: Iterable[Message],
    window: int = 50,
    resend_every: int | None = None,
) -> Counter:
    """Publish messages a window at a time, draining the queue after each.

    Interleaving is how a live feed behaves, and it keeps the emulated
    queue short: moto rescans every queued message on each call, so
    publishing a whole run before draining it is quadratic.

    Resends test both layers of de-duplication. Every ``resend_every``-th
    message is sent twice more at the end of its window: once with the
    same deduplication ID, which the FIFO queue should drop, and once with
    a fresh one (as a publisher retry after the 5-minute dedup window
    would be), which reaches the processor and must be skipped by its
    sequence check.

    Args:
        sqs: A boto3 SQS client.
        resources: Where the queue is.
        poller: The poller to drain with.
        messages: Messages in order.
        window: Messages per publish-then-drain round.
        resend_every: Resend every n-th message, or None for no resends.

    Returns:
        Counter: ``published`` (first sends), ``resent_same_id`` and
        ``resent_new_id``, plus the poller's counts.
    """
    counts = Counter()
    batch = []

    def flush():
        """Publish the window and any resends, then drain."""
        counts["published"] += publish(sqs, resources.queue_url, batch)
        resends = [
            m
            for i, m in enumerate(batch, counts["published"] - len(batch))
            if resend_every and i % resend_every == 0
        ]
        if resends:
            counts["resent_same_id"] += publish(sqs, resources.queue_url, resends)
            counts["resent_new_id"] += publish(
                sqs, resources.queue_url, resends, suffix="#resend"
            )
        poller.drain()
        batch.clear()

    for message in messages:
        batch.append(message)
        if len(batch) == window:
            flush()
    if batch:
        flush()
    return counts + poller.counts


def read_notifications(sqs, resources: Resources) -> list[str]:
    """Drain the stand-in inbox.

    Args:
        sqs: A boto3 SQS client.
        resources: Where the notifications queue is.

    Returns:
        list[str]: Notification bodies received.
    """
    bodies = []
    while True:
        messages = sqs.receive_message(
            QueueUrl=resources.notifications_url, MaxNumberOfMessages=10
        ).get("Messages", [])
        if not messages:
            return bodies
        bodies += [message["Body"] for message in messages]
        sqs.delete_message_batch(
            QueueUrl=resources.notifications_url,
            Entries=[
                {"Id": str(i), "ReceiptHandle": m["ReceiptHandle"]}
                for i, m in enumerate(messages)
            ],
        )


def compare(items: list[dict], expected: list[Incident]) -> dict:
    """Compare stored incident items with the replay runner's incidents.

    Args:
        items: Incident items for one run (``store.run_incidents``).
        expected: The replay's incidents for the same study and scenario.

    Returns:
        dict: Counts, and the IDs missing, extra or different (empty when
        the cloud matches the replay exactly).
    """
    got = {
        item["incident_id"]["S"]: json.loads(item["incident"]["S"]) for item in items
    }
    want = {incident.incident_id: incident.to_dict() for incident in expected}
    return {
        "replay_incidents": len(want),
        "stored_incidents": len(got),
        "missing": sorted(want.keys() - got.keys()),
        "extra": sorted(got.keys() - want.keys()),
        "different": sorted(k for k in want.keys() & got.keys() if got[k] != want[k]),
    }


def latencies(items: list[dict]) -> dict:
    """Wall-clock latency of incidents' first writes, in seconds.

    Locally these measure the emulator and poller, not AWS; they show the
    fields are recorded, nothing more.

    Args:
        items: Incident items for one run.

    Returns:
        dict: Median and 95th percentile of sent-to-stored, and of
        stored-to-notified for notified incidents; None where empty.
    """

    def gap(item: dict, start: str, end: str) -> float | None:
        """Seconds between two recorded times on an item.

        Args:
            item: An incident item.
            start: Name of the earlier time.
            end: Name of the later time.

        Returns:
            float | None: Seconds, or None if either is missing.
        """
        if not item.get(start, {}).get("S") or not item.get(end, {}).get("S"):
            return None
        return (
            datetime.fromisoformat(item[end]["S"])
            - datetime.fromisoformat(item[start]["S"])
        ).total_seconds()

    def spread(values: list[float | None]) -> dict | None:
        """Median and p95 of the values present.

        Args:
            values: Seconds, with None for missing.

        Returns:
            dict | None: ``median`` and ``p95``, or None if none present.
        """
        present = sorted(v for v in values if v is not None)
        if not present:
            return None
        return {
            "median": round(present[len(present) // 2], 3),
            "p95": round(present[min(len(present) - 1, int(0.95 * len(present)))], 3),
        }

    return {
        "sent_to_stored_s": spread(
            [gap(i, "first_sent_at", "first_stored_at") for i in items]
        ),
        "stored_to_notified_s": spread(
            [gap(i, "first_stored_at", "notified_at") for i in items]
        ),
    }
