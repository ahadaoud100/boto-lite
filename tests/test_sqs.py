from __future__ import annotations

import os

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import unittest

from botocore.stub import Stubber

from boto_lite import sqs
from boto_lite._client import get_client
from boto_lite.exceptions import NotFoundError

QUEUE = "https://sqs.us-east-1.amazonaws.com/123456789012/q"


class SqsFacadeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = get_client("sqs")
        self.stubber = Stubber(self.client)
        self.stubber.activate()
        self.addCleanup(self.stubber.deactivate)

    def test_send_returns_message_id(self) -> None:
        self.stubber.add_response(
            "send_message",
            {"MessageId": "mid-1", "MD5OfMessageBody": "x"},
            {"QueueUrl": QUEUE, "MessageBody": "hi"},
        )
        self.assertEqual(sqs.send(QUEUE, "hi"), "mid-1")

    def test_receive_parses_messages(self) -> None:
        self.stubber.add_response(
            "receive_message",
            {
                "Messages": [
                    {"MessageId": "m1", "Body": "hello", "ReceiptHandle": "rh1"},
                    {"MessageId": "m2", "Body": "world", "ReceiptHandle": "rh2"},
                ]
            },
            {"QueueUrl": QUEUE, "MaxNumberOfMessages": 2, "WaitTimeSeconds": 5},
        )
        msgs = sqs.receive(QUEUE, max_messages=2, wait_seconds=5)
        self.assertEqual([m.id for m in msgs], ["m1", "m2"])
        self.assertEqual(msgs[0].body, "hello")
        self.assertEqual(msgs[1].receipt_handle, "rh2")

    def test_receive_empty(self) -> None:
        self.stubber.add_response(
            "receive_message",
            {},
            {"QueueUrl": QUEUE, "MaxNumberOfMessages": 1, "WaitTimeSeconds": 0},
        )
        self.assertEqual(sqs.receive(QUEUE), [])

    def test_delete(self) -> None:
        self.stubber.add_response(
            "delete_message", {}, {"QueueUrl": QUEUE, "ReceiptHandle": "rh"}
        )
        sqs.delete(QUEUE, "rh")
        self.stubber.assert_no_pending_responses()

    def test_missing_queue_raises_not_found(self) -> None:
        self.stubber.add_client_error(
            "send_message",
            service_error_code="AWS.SimpleQueueService.NonExistentQueue",
        )
        with self.assertRaises(NotFoundError):
            sqs.send(QUEUE, "hi")


if __name__ == "__main__":
    unittest.main()
