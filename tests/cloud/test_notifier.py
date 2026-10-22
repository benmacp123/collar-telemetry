"""Tests for the notifier: every ``potential_death`` incident is emailed at
least once, other incidents never, and a crash at any point cannot lose a
notification."""

from cloud import local, notifier
from cloud.store import run_incidents
from cloud_helpers import RUN, expected, messages, poller


def run_all(aws, notify=None) -> list[str]:
    """Publish the test track, drain it and read the stand-in inbox.

    Args:
        aws: The ``aws`` fixture.
        notify: Replacement notifier ``Invoke``, or None.

    Returns:
        list[str]: Notification bodies.
    """
    local.feed(aws["sqs"], aws["resources"], poller(aws, notify), messages())
    return local.read_notifications(aws["sqs"], aws["resources"])


def potential_ids() -> set[str]:
    """IDs of the ``potential_death`` incidents the track should raise.

    Returns:
        set[str]: Incident IDs.
    """
    return {
        key
        for key, incident in expected().items()
        if incident["detector"] == notifier.NOTIFIED_DETECTOR
    }


def notified_ids(bodies: list[str]) -> list[str]:
    """Incident IDs named in notification bodies, with repeats.

    Args:
        bodies: Notification bodies.

    Returns:
        list[str]: One ID per body.
    """
    return [
        line.removeprefix("Incident: ")
        for body in bodies
        for line in body.splitlines()
        if line.startswith("Incident: ")
    ]


def real_notifier(aws):
    """The notifier as an ``Invoke``, for wrapping.

    Args:
        aws: The ``aws`` fixture.

    Returns:
        Callable: Takes a stream event, returns the handler's response.
    """
    return lambda event: notifier.notify_records(
        event["Records"],
        aws["dynamodb"],
        aws["sns"],
        local.TABLES,
        aws["resources"].topic_arn,
    )


def test_track_raises_a_potential_death():
    """The fixture track exercises the notified path at all."""
    assert len(potential_ids()) == 1


def test_each_potential_death_is_emailed_once(aws):
    """One email per ``potential_death`` incident; mortality and gap
    incidents send none."""
    bodies = run_all(aws)
    assert sorted(notified_ids(bodies)) == sorted(potential_ids())
    items = run_incidents(aws["dynamodb"], local.TABLES, RUN)
    marked = {i["incident_id"]["S"] for i in items if "notified_at" in i}
    assert marked == potential_ids()


def test_email_carries_the_incident(aws):
    """The email names the deployment and says what was seen."""
    (body,) = run_all(aws)
    assert "Deployment: A" in body
    assert body.splitlines()[0]


def test_crash_before_publish_still_notifies_on_retry(aws):
    """A notifier that fails before sending (a crash between the store
    write and the notify) leaves the stream record to be retried."""
    calls = {"n": 0}

    class FailingOnce:
        """SNS client whose first publish raises."""

        def publish(self, **kwargs):
            """Raise once, then publish for real.

            Args:
                **kwargs: ``publish`` arguments.

            Returns:
                dict: SNS's response.

            Raises:
                ConnectionError: On the first call.
            """
            calls["n"] += 1
            if calls["n"] == 1:
                raise ConnectionError("simulated crash")
            return aws["sns"].publish(**kwargs)

    def notify(event):
        """Notifier with the failing SNS client."""
        return notifier.notify_records(
            event["Records"],
            aws["dynamodb"],
            FailingOnce(),
            local.TABLES,
            aws["resources"].topic_arn,
        )

    bodies = run_all(aws, notify)
    assert calls["n"] == 2
    assert sorted(notified_ids(bodies)) == sorted(potential_ids())


def test_crash_after_publish_duplicates_rather_than_loses(aws, monkeypatch):
    """A crash between sending and marking sends the email again on retry:
    at least once, never zero."""
    real_mark = notifier.mark_notified
    calls = {"n": 0}

    def crash_once(*args):
        """Fail the first mark, as if the Lambda died after publishing.

        Args:
            *args: ``mark_notified`` arguments.

        Returns:
            bool: As ``mark_notified``.

        Raises:
            ConnectionError: On the first call.
        """
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionError("simulated crash")
        return real_mark(*args)

    monkeypatch.setattr(notifier, "mark_notified", crash_once)
    bodies = run_all(aws)
    (potential,) = potential_ids()
    assert notified_ids(bodies) == [potential, potential]


def test_marked_incident_is_not_sent_again(aws):
    """Replaying the whole stream after success sends nothing new."""
    run_all(aws)
    reader = local.StreamReader(aws["dynamodbstreams"], aws["resources"].stream_arn)
    records = reader.read()
    assert records
    assert real_notifier(aws)({"Records": records}) == {"batchItemFailures": []}
    assert not local.read_notifications(aws["sqs"], aws["resources"])


def test_handler_sends_nothing_when_disabled(monkeypatch):
    """Bulk replays run with notification off."""
    monkeypatch.delenv("NOTIFY_ENABLED", raising=False)
    record = {"dynamodb": {"NewImage": {"detector": {"S": "potential_death"}}}}
    assert notifier.handler({"Records": [record]}, None) == {"batchItemFailures": []}


def test_failure_reports_the_failed_record(aws):
    """A failing record is named by sequence number, so Lambda retries
    from it."""

    class Broken:
        """SNS client that always fails."""

        def publish(self, **kwargs):
            """Always raise.

            Args:
                **kwargs: Ignored.

            Raises:
                ConnectionError: Always.
            """
            raise ConnectionError(kwargs)

    image = {
        "detector": {"S": "potential_death"},
        "run_id": {"S": RUN},
        "incident_id": {"S": "A:potential_death:x"},
        "deployment_id": {"S": "A"},
        "incident": {"S": "{}"},
    }
    records = [{"eventID": "1", "dynamodb": {"SequenceNumber": "7", "NewImage": image}}]
    response = notifier.notify_records(
        records, aws["dynamodb"], Broken(), local.TABLES, "arn"
    )
    assert response == {"batchItemFailures": [{"itemIdentifier": "7"}]}
