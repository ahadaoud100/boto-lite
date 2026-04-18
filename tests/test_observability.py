"""Tests that bound clients register botocore event handlers passed via ``events``."""

from __future__ import annotations

import os

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import unittest
from unittest.mock import MagicMock

import boto3

from boto_lite import S3Client, SQSClient, SecretsClient


class _Spy:
    """A minimal stand-in for a boto3 client whose only job is to record
    calls to ``.meta.events.register``. We're verifying the plumbing —
    that the bound-client constructor forwards ``events`` entries into
    boto3's event system — not that boto3 itself emits events (boto3's
    own tests cover that)."""

    def __init__(self) -> None:
        self.registered: list[tuple[str, object]] = []
        self.meta = MagicMock()
        self.meta.events = MagicMock()
        self.meta.events.register = self._register

    def _register(self, event_name: str, handler: object) -> None:
        self.registered.append((event_name, handler))


def _session_returning(spy: _Spy) -> MagicMock:
    session = MagicMock(spec=boto3.Session)
    session.client.return_value = spy
    return session


class EventsPassthroughTest(unittest.TestCase):
    def test_s3_client_forwards_events_to_event_system(self) -> None:
        spy = _Spy()
        handler = lambda **_: None  # noqa: E731
        S3Client(session=_session_returning(spy),
                 events={"before-call.s3.PutObject": handler})
        self.assertEqual(spy.registered, [("before-call.s3.PutObject", handler)])

    def test_sqs_client_forwards_events_to_event_system(self) -> None:
        spy = _Spy()
        h1 = lambda **_: None  # noqa: E731
        h2 = lambda **_: None  # noqa: E731
        SQSClient(session=_session_returning(spy),
                  events={"before-call.sqs.SendMessage": h1,
                          "after-call.sqs.SendMessage": h2})
        self.assertEqual(
            sorted(spy.registered),
            sorted([("before-call.sqs.SendMessage", h1),
                    ("after-call.sqs.SendMessage", h2)]),
        )

    def test_secrets_client_forwards_events_to_event_system(self) -> None:
        spy = _Spy()
        handler = lambda **_: None  # noqa: E731
        SecretsClient(
            session=_session_returning(spy),
            events={"before-call.secrets-manager.GetSecretValue": handler},
        )
        self.assertEqual(
            spy.registered,
            [("before-call.secrets-manager.GetSecretValue", handler)],
        )

    def test_no_events_kwarg_registers_nothing(self) -> None:
        for cls in (S3Client, SQSClient, SecretsClient):
            spy = _Spy()
            cls(session=_session_returning(spy))
            self.assertEqual(
                spy.registered, [],
                f"{cls.__name__} registered something when events was omitted",
            )

    def test_empty_events_mapping_registers_nothing(self) -> None:
        spy = _Spy()
        S3Client(session=_session_returning(spy), events={})
        self.assertEqual(spy.registered, [])


if __name__ == "__main__":
    unittest.main()
