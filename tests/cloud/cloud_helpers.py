"""Helpers for the cloud tests: a short timeline cut into messages, the
incidents it should produce, and an in-process poller.

The timeline is the slicing tests' track (five days walking 300 m an
hour, three still, then silent), which opens mortality, gap and
``likely_death`` incidents within 16 daily slices, so every path the
handlers have is exercised.
"""

from datetime import datetime, timedelta, timezone

from telemetry.core.fixes import Fix
from telemetry.core.geo import offset
from telemetry.core.pipeline import stream_for
from telemetry.core.slices import slice_timeline
from telemetry.sim.arrival import SCENARIOS, simulate_arrival
from telemetry.sim.replay import SILENT_HORIZON

from cloud import local, notifier, processor
from cloud.messages import Message, UploadSettings

RUN = "test-run"
JACKAL = "Canis mesomelas"
START = datetime(2009, 3, 1, 0, 20, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


def track() -> list[Fix]:
    """Five days walking, then three days still, one fix an hour.

    Returns:
        list[Fix]: Fixes for deployment ``A``, in time order.
    """
    fixes = []
    lat, lon = -19.0, 15.5
    for i in range(24 * 8):
        if i < 24 * 5:
            lat, lon = offset(lat, lon, 0.0, 300.0)
        fixes.append(Fix("A", START + i * HOUR, lat, lon))
    return fixes


def timeline(scenario_name: str = "satellite_daily"):
    """The test track's arrivals and end of watch under a scenario.

    Args:
        scenario_name: An arrival scenario.

    Returns:
        tuple: Arrivals and end of watch.
    """
    arrivals = simulate_arrival(track(), SCENARIOS[scenario_name], seed=3)
    return arrivals, arrivals[-1].time + SILENT_HORIZON


def messages(scenario_name: str = "satellite_daily", **kwargs) -> list[Message]:
    """The test track as cloud messages.

    Args:
        scenario_name: An arrival scenario.
        **kwargs: Passed to ``slice_timeline``.

    Returns:
        list[Message]: One per slice, numbered from 0.
    """
    scenario = SCENARIOS[scenario_name]
    arrivals, until = timeline(scenario_name)
    uploads = UploadSettings(scenario.upload_every, scenario.max_lateness)
    return [
        Message(RUN, seq, JACKAL, uploads, None, part)
        for seq, part in enumerate(slice_timeline("A", arrivals, until, **kwargs))
    ]


def expected(scenario_name: str = "satellite_daily") -> dict:
    """The newest form of each incident from one pass over the track.

    Args:
        scenario_name: An arrival scenario.

    Returns:
        dict: Incident dicts by incident ID.
    """
    arrivals, until = timeline(scenario_name)
    stream = stream_for(JACKAL, SCENARIOS[scenario_name])
    return {
        incident.incident_id: incident.to_dict()
        for incident in stream.advance("A", arrivals, until)
    }


def sqs_records(batch: list[Message]) -> list[dict]:
    """Messages as the records of an SQS Lambda event.

    Args:
        batch: Messages.

    Returns:
        list[dict]: Records with ``messageId`` and ``body``.
    """
    return [
        {"messageId": f"m{message.seq}", "body": message.to_json()} for message in batch
    ]


def poller(aws, notify=None) -> local.Poller:
    """A poller calling the handlers in-process.

    Args:
        aws: The ``aws`` fixture.
        notify: Replacement notifier ``Invoke``, or None for the real one.

    Returns:
        local.Poller: Ready to drain.
    """
    resources = aws["resources"]
    return local.Poller(
        aws["sqs"],
        aws["dynamodbstreams"],
        resources,
        lambda event: processor.process_records(
            event["Records"], aws["dynamodb"], local.TABLES
        ),
        notify
        or (
            lambda event: notifier.notify_records(
                event["Records"],
                aws["dynamodb"],
                aws["sns"],
                local.TABLES,
                resources.topic_arn,
            )
        ),
    )
