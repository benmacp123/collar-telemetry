"""Tests for the local harness: the poller drives the handlers to the
replay's result, resends included, and the comparison catches
differences."""

import json

from telemetry.core.alerts import Incident

from cloud import local
from cloud.store import run_incidents
from cloud_helpers import RUN, expected, messages, poller


def test_feed_with_resends_matches_the_replay(aws):
    """End to end on moto: same-ID resends are dropped by the queue,
    new-ID resends skipped by the processor, and the stored incidents are
    the replay's."""
    batch = messages("gsm")
    counts = local.feed(
        aws["sqs"], aws["resources"], poller(aws), batch, window=4, resend_every=3
    )
    assert counts["published"] == len(batch)
    assert counts["resent_new_id"] == counts["resent_same_id"] > 0
    assert counts["received"] == len(batch) + counts["resent_new_id"]
    assert counts["failed"] == 0
    items = run_incidents(aws["dynamodb"], local.TABLES, RUN)
    stored = {i["incident_id"]["S"]: json.loads(i["incident"]["S"]) for i in items}
    assert stored == expected("gsm")


def test_compare_names_missing_extra_and_different():
    """A comparison that passes nothing through would hide a broken run."""
    want = list(expected().values())
    first, second = want[0], want[1]
    changed = {**second, "flaps": second["flaps"] + 1}
    items = [
        {"incident_id": {"S": row["incident_id"]}, "incident": {"S": json.dumps(row)}}
        for row in (changed, {**first, "incident_id": "extra"})
    ]
    result = local.compare(items, [Incident.from_dict(row) for row in want])
    assert result["missing"] == sorted(r["incident_id"] for r in want if r != second)
    assert result["extra"] == ["extra"]
    assert result["different"] == [second["incident_id"]]


def test_latencies_are_none_without_times():
    """Items without wall-clock fields give no latency, not an error."""
    assert local.latencies([{}]) == {
        "sent_to_stored_s": None,
        "stored_to_notified_s": None,
    }
