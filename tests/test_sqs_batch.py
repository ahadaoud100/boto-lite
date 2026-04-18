"""Tests for ``sqs.send_batch`` / ``sqs.delete_batch`` / ``sqs.consume``.

Exercises AWS 10-entry chunking, partial-failure surfacing, and the
consumer loop's delete-on-success / keep-on-exception semantics.
"""

from __future__ import annotations

import os

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import threading
import unittest
from unittest.mock import MagicMock

import boto3
from botocore.stub import Stubber

from boto_lite import sqs
from boto_lite.sqs import SQSClient

QUEUE = "https://sqs.us-east-1.amazonaws.com/123456789012/q"


def _stub_sqs() -> tuple[object, Stubber]:
    client = boto3.client("sqs", region_name="us-east-1")
    stubber = Stubber(client)
    stubber.activate()
    return client, stubber


class SendBatchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw, self.stubber = _stub_sqs()
        self.addCleanup(self.stubber.deactivate)
        session = MagicMock(spec=boto3.Session)
        session.client.return_value = self.raw
        self.client = SQSClient(session=session)

    def test_single_chunk_returns_ids_in_input_order(self) -> None:
        bodies = [f"m{i}" for i in range(3)]
        self.stubber.add_response(
            "send_message_batch",
            {
                "Successful": [
                    {"Id": "0", "MessageId": "mid-0", "MD5OfMessageBody": "x"},
                    {"Id": "1", "MessageId": "mid-1", "MD5OfMessageBody": "x"},
                    {"Id": "2", "MessageId": "mid-2", "MD5OfMessageBody": "x"},
                ],
                "Failed": [],
            },
            {
                "QueueUrl": QUEUE,
                "Entries": [
                    {"Id": "0", "MessageBody": "m0"},
                    {"Id": "1", "MessageBody": "m1"},
                    {"Id": "2", "MessageBody": "m2"},
                ],
            },
        )
        result = self.client.send_batch(QUEUE, bodies)
        self.assertEqual(result.message_ids, ["mid-0", "mid-1", "mid-2"])
        self.assertTrue(result.all_succeeded)

    def test_chunks_above_ten_entries(self) -> None:
        bodies = [f"m{i}" for i in range(25)]
        # Chunk 1: 10 entries, Ids 0..9
        self.stubber.add_response(
            "send_message_batch",
            {
                "Successful": [
                    {"Id": str(i), "MessageId": f"id-{i}", "MD5OfMessageBody": "x"}
                    for i in range(10)
                ],
                "Failed": [],
            },
            {
                "QueueUrl": QUEUE,
                "Entries": [
                    {"Id": str(i), "MessageBody": f"m{i}"} for i in range(10)
                ],
            },
        )
        # Chunk 2: 10 entries, local Ids 0..9 but correspond to global 10..19
        self.stubber.add_response(
            "send_message_batch",
            {
                "Successful": [
                    {"Id": str(i), "MessageId": f"id-{10+i}", "MD5OfMessageBody": "x"}
                    for i in range(10)
                ],
                "Failed": [],
            },
            {
                "QueueUrl": QUEUE,
                "Entries": [
                    {"Id": str(i), "MessageBody": f"m{10+i}"} for i in range(10)
                ],
            },
        )
        # Chunk 3: 5 entries, local Ids 0..4 -> global 20..24
        self.stubber.add_response(
            "send_message_batch",
            {
                "Successful": [
                    {"Id": str(i), "MessageId": f"id-{20+i}", "MD5OfMessageBody": "x"}
                    for i in range(5)
                ],
                "Failed": [],
            },
            {
                "QueueUrl": QUEUE,
                "Entries": [
                    {"Id": str(i), "MessageBody": f"m{20+i}"} for i in range(5)
                ],
            },
        )
        result = self.client.send_batch(QUEUE, bodies)
        self.assertEqual(
            result.message_ids, [f"id-{i}" for i in range(25)]
        )
        self.assertTrue(result.all_succeeded)

    def test_partial_failures_keyed_to_global_index(self) -> None:
        bodies = [f"m{i}" for i in range(12)]
        # Chunk 1: entries 0..9, one failure at local Id 3.
        self.stubber.add_response(
            "send_message_batch",
            {
                "Successful": [
                    {"Id": str(i), "MessageId": f"id-{i}", "MD5OfMessageBody": "x"}
                    for i in range(10)
                    if i != 3
                ],
                "Failed": [
                    {
                        "Id": "3",
                        "Code": "InternalError",
                        "Message": "transient",
                        "SenderFault": False,
                    }
                ],
            },
            {
                "QueueUrl": QUEUE,
                "Entries": [
                    {"Id": str(i), "MessageBody": f"m{i}"} for i in range(10)
                ],
            },
        )
        # Chunk 2: entries 10..11, one failure at local Id 1 (global index 11).
        self.stubber.add_response(
            "send_message_batch",
            {
                "Successful": [
                    {"Id": "0", "MessageId": "id-10", "MD5OfMessageBody": "x"},
                ],
                "Failed": [
                    {
                        "Id": "1",
                        "Code": "MessageTooLong",
                        "Message": "oops",
                        "SenderFault": True,
                    }
                ],
            },
            {
                "QueueUrl": QUEUE,
                "Entries": [
                    {"Id": "0", "MessageBody": "m10"},
                    {"Id": "1", "MessageBody": "m11"},
                ],
            },
        )
        result = self.client.send_batch(QUEUE, bodies)
        self.assertFalse(result.all_succeeded)
        self.assertIsNone(result.message_ids[3])
        self.assertIsNone(result.message_ids[11])
        self.assertEqual(result.message_ids[0], "id-0")
        self.assertEqual(result.message_ids[10], "id-10")
        failed_indices = {f.index for f in result.failures}
        self.assertEqual(failed_indices, {3, 11})
        fail_11 = next(f for f in result.failures if f.index == 11)
        self.assertEqual(fail_11.code, "MessageTooLong")
        self.assertTrue(fail_11.sender_fault)


class DeleteBatchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw, self.stubber = _stub_sqs()
        self.addCleanup(self.stubber.deactivate)
        session = MagicMock(spec=boto3.Session)
        session.client.return_value = self.raw
        self.client = SQSClient(session=session)

    def test_all_succeed(self) -> None:
        handles = [f"rh-{i}" for i in range(3)]
        self.stubber.add_response(
            "delete_message_batch",
            {
                "Successful": [{"Id": str(i)} for i in range(3)],
                "Failed": [],
            },
            {
                "QueueUrl": QUEUE,
                "Entries": [
                    {"Id": str(i), "ReceiptHandle": h}
                    for i, h in enumerate(handles)
                ],
            },
        )
        result = self.client.delete_batch(QUEUE, handles)
        self.assertTrue(result.all_succeeded)
        self.assertEqual(result.failures, [])

    def test_reports_failure_index(self) -> None:
        handles = ["a", "b", "c"]
        self.stubber.add_response(
            "delete_message_batch",
            {
                "Successful": [{"Id": "0"}, {"Id": "2"}],
                "Failed": [
                    {
                        "Id": "1",
                        "Code": "ReceiptHandleIsInvalid",
                        "Message": "bad",
                        "SenderFault": True,
                    }
                ],
            },
            {
                "QueueUrl": QUEUE,
                "Entries": [
                    {"Id": "0", "ReceiptHandle": "a"},
                    {"Id": "1", "ReceiptHandle": "b"},
                    {"Id": "2", "ReceiptHandle": "c"},
                ],
            },
        )
        result = self.client.delete_batch(QUEUE, handles)
        self.assertFalse(result.all_succeeded)
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].index, 1)
        self.assertEqual(result.failures[0].code, "ReceiptHandleIsInvalid")


class ConsumeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw, self.stubber = _stub_sqs()
        self.addCleanup(self.stubber.deactivate)
        session = MagicMock(spec=boto3.Session)
        session.client.return_value = self.raw
        self.client = SQSClient(session=session)

    def test_delete_on_success(self) -> None:
        stop = threading.Event()
        self.stubber.add_response(
            "receive_message",
            {
                "Messages": [
                    {"MessageId": "m1", "Body": "b1", "ReceiptHandle": "rh1"}
                ]
            },
            {"QueueUrl": QUEUE, "MaxNumberOfMessages": 10, "WaitTimeSeconds": 20},
        )
        self.stubber.add_response(
            "delete_message", {}, {"QueueUrl": QUEUE, "ReceiptHandle": "rh1"}
        )

        handled: list[str] = []

        def handler(msg: sqs.Message) -> None:
            handled.append(msg.body)
            stop.set()  # exit after first message

        self.client.consume(QUEUE, handler, stop=stop)
        self.assertEqual(handled, ["b1"])
        self.stubber.assert_no_pending_responses()

    def test_handler_exception_skips_delete_and_fires_on_error(self) -> None:
        stop = threading.Event()
        self.stubber.add_response(
            "receive_message",
            {
                "Messages": [
                    {"MessageId": "m1", "Body": "poison", "ReceiptHandle": "rh1"}
                ]
            },
            {"QueueUrl": QUEUE, "MaxNumberOfMessages": 10, "WaitTimeSeconds": 20},
        )
        # Deliberately no delete_message stub: if consume() tried to delete,
        # the stubber would raise StubResponseError.

        errors: list[tuple[str, str]] = []

        def handler(msg: sqs.Message) -> None:
            raise RuntimeError("boom")

        def on_error(msg: sqs.Message, exc: BaseException) -> None:
            errors.append((msg.body, str(exc)))
            stop.set()

        self.client.consume(QUEUE, handler, stop=stop, on_error=on_error)
        self.assertEqual(errors, [("poison", "boom")])
        self.stubber.assert_no_pending_responses()

    def test_stop_preset_short_circuits_loop(self) -> None:
        stop = threading.Event()
        stop.set()  # loop should exit before the first receive

        def handler(msg: sqs.Message) -> None:  # pragma: no cover
            self.fail("handler should not be called")

        self.client.consume(QUEUE, handler, stop=stop)
        self.stubber.assert_no_pending_responses()

    def test_empty_receive_then_exit_on_stop(self) -> None:
        stop = threading.Event()
        call_count = {"n": 0}

        def receive_side_effect(**kwargs: object) -> dict[str, object]:
            call_count["n"] += 1
            stop.set()  # signal shutdown after the first (empty) receive
            return {}

        fake_client = MagicMock()
        fake_client.receive_message.side_effect = receive_side_effect

        def handler(msg: sqs.Message) -> None:  # pragma: no cover
            self.fail("handler should not be called on empty receive")

        from boto_lite.sqs import _consume_on

        _consume_on(
            fake_client,
            QUEUE,
            handler,
            stop=stop,
            max_messages=10,
            wait_seconds=20,
            visibility_timeout=None,
            on_error=None,
        )
        self.assertEqual(call_count["n"], 1)
        fake_client.delete_message.assert_not_called()


if __name__ == "__main__":
    unittest.main()
