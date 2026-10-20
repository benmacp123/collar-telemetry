"""Shared fixture for the cloud tests: moto in-process, with the queue,
tables and topic the handlers use."""

import boto3
import pytest
from moto import mock_aws

from cloud import local


@pytest.fixture(name="aws")
def fixture_aws(monkeypatch):
    """moto clients with the handlers' queue, tables and topic created.

    Yields:
        dict: Clients by service name, plus ``resources``.
    """
    for name, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_DEFAULT_REGION": "eu-west-2",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.delenv("AWS_ENDPOINT_URL", raising=False)
    with mock_aws():
        clients = {
            name: boto3.client(name)
            for name in ("sqs", "dynamodb", "dynamodbstreams", "sns")
        }
        clients["resources"] = local.create_resources(
            clients["sqs"], clients["dynamodb"], clients["sns"]
        )
        yield clients
