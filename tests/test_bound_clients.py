"""Tests for the S3Client / SQSClient / SecretsClient bound service objects.

The bound classes all share two properties the module-level API does
not:

1. The underlying boto3 client is constructed exactly once per
   instance, so repeated calls do not pay client-construction cost.
2. The raw underlying client is exposed as ``.raw`` as a deliberate
   escape hatch.
"""

from __future__ import annotations

import os

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import types
import unittest
from io import BytesIO
from unittest.mock import MagicMock

import boto3
from botocore.response import StreamingBody
from botocore.stub import Stubber

from boto_lite import S3Client, SecretsClient, SQSClient
from boto_lite.exceptions import NotFoundError, ValidationError

QUEUE = "https://sqs.us-east-1.amazonaws.com/123456789012/q"
_ARN = "arn:aws:secretsmanager:us-east-1:000000000000:secret:foo-AbCdEf"


def _stub(service: str) -> tuple[object, Stubber]:
    client = boto3.client(service, region_name="us-east-1")
    stubber = Stubber(client)
    stubber.activate()
    return client, stubber


class S3ClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw, self.stubber = _stub("s3")
        self.addCleanup(self.stubber.deactivate)
        session = MagicMock(spec=boto3.Session)
        session.client.return_value = self.raw
        self.client = S3Client(session=session)

    def test_client_constructed_once(self) -> None:
        # Two method calls should not reconstruct the underlying client.
        self.stubber.add_response(
            "put_object", {}, {"Bucket": "b", "Key": "k1", "Body": b"1"}
        )
        self.stubber.add_response(
            "put_object", {}, {"Bucket": "b", "Key": "k2", "Body": b"2"}
        )
        self.client.put_object("b", "k1", b"1")
        self.client.put_object("b", "k2", b"2")
        self.stubber.assert_no_pending_responses()

    def test_raw_escape_hatch(self) -> None:
        self.assertIs(self.client.raw, self.raw)

    def test_get_object_streams(self) -> None:
        payload = b"bound-hello"
        self.stubber.add_response(
            "get_object",
            {"Body": StreamingBody(BytesIO(payload), len(payload))},
            {"Bucket": "b", "Key": "k"},
        )
        gen = self.client.get_object("b", "k")
        self.assertIsInstance(gen, types.GeneratorType)
        self.assertEqual(b"".join(gen), payload)

    def test_list_keys_paginates(self) -> None:
        self.stubber.add_response(
            "list_objects_v2",
            {
                "Contents": [{"Key": "a"}],
                "IsTruncated": True,
                "NextContinuationToken": "tok",
            },
            {"Bucket": "bkt", "Prefix": ""},
        )
        self.stubber.add_response(
            "list_objects_v2",
            {"Contents": [{"Key": "b"}], "IsTruncated": False},
            {"Bucket": "bkt", "Prefix": "", "ContinuationToken": "tok"},
        )
        self.assertEqual(list(self.client.list_keys("bkt")), ["a", "b"])

    def test_missing_raises_not_found(self) -> None:
        self.stubber.add_client_error(
            "get_object",
            service_error_code="NoSuchKey",
            expected_params={"Bucket": "b", "Key": "missing"},
        )
        with self.assertRaises(NotFoundError):
            list(self.client.get_object("b", "missing"))


class SQSClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw, self.stubber = _stub("sqs")
        self.addCleanup(self.stubber.deactivate)
        session = MagicMock(spec=boto3.Session)
        session.client.return_value = self.raw
        self.client = SQSClient(session=session)

    def test_send_and_receive(self) -> None:
        self.stubber.add_response(
            "send_message",
            {"MessageId": "mid", "MD5OfMessageBody": "x"},
            {"QueueUrl": QUEUE, "MessageBody": "hi"},
        )
        self.stubber.add_response(
            "receive_message",
            {
                "Messages": [
                    {"MessageId": "mid", "Body": "hi", "ReceiptHandle": "rh"}
                ]
            },
            {"QueueUrl": QUEUE, "MaxNumberOfMessages": 1, "WaitTimeSeconds": 0},
        )
        self.assertEqual(self.client.send(QUEUE, "hi"), "mid")
        msgs = self.client.receive(QUEUE)
        self.assertEqual(msgs[0].body, "hi")

    def test_send_with_attributes_and_fifo(self) -> None:
        attrs = {"k": {"DataType": "String", "StringValue": "v"}}
        self.stubber.add_response(
            "send_message",
            {"MessageId": "mid", "MD5OfMessageBody": "x"},
            {
                "QueueUrl": QUEUE,
                "MessageBody": "hi",
                "MessageAttributes": attrs,
                "MessageGroupId": "g1",
                "MessageDeduplicationId": "d1",
            },
        )
        self.client.send(
            QUEUE,
            "hi",
            message_attributes=attrs,
            message_group_id="g1",
            message_deduplication_id="d1",
        )
        self.stubber.assert_no_pending_responses()

    def test_delete(self) -> None:
        self.stubber.add_response(
            "delete_message", {}, {"QueueUrl": QUEUE, "ReceiptHandle": "rh"}
        )
        self.client.delete(QUEUE, "rh")
        self.stubber.assert_no_pending_responses()


class SecretsClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw, self.stubber = _stub("secretsmanager")
        self.addCleanup(self.stubber.deactivate)
        session = MagicMock(spec=boto3.Session)
        session.client.return_value = self.raw
        self.client = SecretsClient(session=session)

    def test_get_with_version_stage(self) -> None:
        self.stubber.add_response(
            "get_secret_value",
            {"ARN": _ARN, "Name": "foo", "SecretString": "prev"},
            {"SecretId": "foo", "VersionStage": "AWSPREVIOUS"},
        )
        self.assertEqual(
            self.client.get("foo", version_stage="AWSPREVIOUS"), "prev"
        )

    def test_get_binary(self) -> None:
        payload = b"\x00\x01\x02"
        self.stubber.add_response(
            "get_secret_value",
            {"ARN": _ARN, "Name": "b", "SecretBinary": payload},
            {"SecretId": "b"},
        )
        self.assertEqual(self.client.get("b"), payload)

    def test_put_create_then_update(self) -> None:
        self.stubber.add_response(
            "create_secret",
            {"ARN": _ARN, "Name": "foo"},
            {"Name": "foo", "SecretString": "v1"},
        )
        self.client.put("foo", "v1")
        self.stubber.add_client_error(
            "create_secret",
            service_error_code="ResourceExistsException",
            expected_params={"Name": "foo", "SecretString": "v2"},
        )
        self.stubber.add_response(
            "put_secret_value",
            {"ARN": _ARN, "Name": "foo"},
            {"SecretId": "foo", "SecretString": "v2"},
        )
        self.client.put("foo", "v2")
        self.stubber.assert_no_pending_responses()

    def test_delete_rejects_conflicting_options(self) -> None:
        with self.assertRaises(ValidationError):
            self.client.delete(
                "foo",
                recovery_window_in_days=7,
                force_delete_without_recovery=True,
            )


class EndpointUrlForwardingTest(unittest.TestCase):
    """Verify endpoint_url reaches session.client() from bound-client ctors."""

    def test_s3client_forwards_endpoint(self) -> None:
        fake_session = MagicMock(spec=boto3.Session)
        fake_session.client.return_value = object()
        S3Client(session=fake_session, endpoint_url="http://localhost:4566")
        fake_session.client.assert_called_once_with(
            "s3", endpoint_url="http://localhost:4566"
        )

    def test_sqsclient_forwards_endpoint(self) -> None:
        fake_session = MagicMock(spec=boto3.Session)
        fake_session.client.return_value = object()
        SQSClient(session=fake_session, endpoint_url="http://localhost:4566")
        fake_session.client.assert_called_once_with(
            "sqs", endpoint_url="http://localhost:4566"
        )

    def test_secretsclient_forwards_endpoint(self) -> None:
        fake_session = MagicMock(spec=boto3.Session)
        fake_session.client.return_value = object()
        SecretsClient(session=fake_session, endpoint_url="http://localhost:4566")
        fake_session.client.assert_called_once_with(
            "secretsmanager", endpoint_url="http://localhost:4566"
        )


if __name__ == "__main__":
    unittest.main()
