"""Flat, strongly-typed facade over a small subset of AWS SQS."""

from __future__ import annotations

from dataclasses import dataclass

from boto_lite._client import get_client, translate_errors


@dataclass(frozen=True)
class Message:
    id: str
    body: str
    receipt_handle: str


def send(queue_url: str, body: str) -> str:
    with translate_errors():
        resp = get_client("sqs").send_message(QueueUrl=queue_url, MessageBody=body)
        return resp["MessageId"]


def receive(
    queue_url: str, max_messages: int = 1, wait_seconds: int = 0
) -> list[Message]:
    with translate_errors():
        resp = get_client("sqs").receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_seconds,
        )
        return [
            Message(id=m["MessageId"], body=m["Body"], receipt_handle=m["ReceiptHandle"])
            for m in resp.get("Messages", [])
        ]


def delete(queue_url: str, receipt_handle: str) -> None:
    with translate_errors():
        get_client("sqs").delete_message(
            QueueUrl=queue_url, ReceiptHandle=receipt_handle
        )
