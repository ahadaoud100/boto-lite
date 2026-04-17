"""Flat, strongly-typed facade over a small subset of AWS SQS."""

from __future__ import annotations

from dataclasses import dataclass

import boto3
from botocore.config import Config as BotoConfig

from boto_lite._client import get_client, translate_errors


@dataclass(frozen=True)
class Message:
    id: str
    body: str
    receipt_handle: str


def send(
    queue_url: str,
    body: str,
    *,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
) -> str:
    with translate_errors():
        client = get_client(
            "sqs",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
        )
        resp = client.send_message(QueueUrl=queue_url, MessageBody=body)
        return resp["MessageId"]


def receive(
    queue_url: str,
    max_messages: int = 1,
    wait_seconds: int = 0,
    *,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
) -> list[Message]:
    """Receive up to ``max_messages`` messages from ``queue_url``.

    ``wait_seconds`` maps directly to SQS ``WaitTimeSeconds``:

    - ``wait_seconds=0`` (the default) performs a **short poll** — the
      call returns immediately with whatever messages happen to be on
      the sampled subset of SQS hosts, and may return an empty list
      even when messages exist on the queue.
    - ``wait_seconds`` in the range ``1..20`` performs a **long poll**
      — the call blocks on the server for up to that many seconds,
      returning as soon as any message arrives. Long polling is the
      recommended setting for most workloads.

    Values outside ``0..20`` are rejected by SQS with a parameter
    validation error.
    """
    with translate_errors():
        client = get_client(
            "sqs",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
        )
        resp = client.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=max_messages,
            WaitTimeSeconds=wait_seconds,
        )
        return [
            Message(
                id=m["MessageId"],
                body=m["Body"],
                receipt_handle=m["ReceiptHandle"],
            )
            for m in resp.get("Messages", [])
        ]


def delete(
    queue_url: str,
    receipt_handle: str,
    *,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
) -> None:
    with translate_errors():
        client = get_client(
            "sqs",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
        )
        client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
