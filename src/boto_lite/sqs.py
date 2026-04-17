"""Flat, strongly-typed facade over a small subset of AWS SQS."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

import boto3
from botocore.config import Config as BotoConfig

from boto_lite._client import get_client, translate_errors


@dataclass(frozen=True)
class Message:
    id: str
    body: str
    receipt_handle: str


def _send_kwargs(
    queue_url: str,
    body: str,
    *,
    message_attributes: Mapping[str, Any] | None,
    message_group_id: str | None,
    message_deduplication_id: str | None,
    delay_seconds: int | None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"QueueUrl": queue_url, "MessageBody": body}
    if message_attributes:
        kwargs["MessageAttributes"] = dict(message_attributes)
    if message_group_id is not None:
        kwargs["MessageGroupId"] = message_group_id
    if message_deduplication_id is not None:
        kwargs["MessageDeduplicationId"] = message_deduplication_id
    if delay_seconds is not None:
        kwargs["DelaySeconds"] = delay_seconds
    return kwargs


def send(
    queue_url: str,
    body: str,
    *,
    message_attributes: Mapping[str, Any] | None = None,
    message_group_id: str | None = None,
    message_deduplication_id: str | None = None,
    delay_seconds: int | None = None,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
    endpoint_url: str | None = None,
) -> str:
    """Send a single message and return its ``MessageId``.

    ``message_attributes`` accepts an already-shaped SQS attribute map
    (``{"name": {"DataType": "String", "StringValue": "v"}}``).
    ``message_group_id`` / ``message_deduplication_id`` are required for
    FIFO queues. ``delay_seconds`` delays per-message delivery (0–900).
    """
    with translate_errors():
        client = get_client(
            "sqs",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
            endpoint_url=endpoint_url,
        )
        resp = client.send_message(
            **_send_kwargs(
                queue_url,
                body,
                message_attributes=message_attributes,
                message_group_id=message_group_id,
                message_deduplication_id=message_deduplication_id,
                delay_seconds=delay_seconds,
            )
        )
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
    endpoint_url: str | None = None,
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
            endpoint_url=endpoint_url,
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
    endpoint_url: str | None = None,
) -> None:
    with translate_errors():
        client = get_client(
            "sqs",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
            endpoint_url=endpoint_url,
        )
        client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)


class SQSClient:
    """Reusable SQS facade bound to a single underlying boto3 client.

    Use this when you make repeated calls with non-default configuration
    and want to avoid the per-call client-construction cost of the
    module-level ``sqs.*`` functions.
    """

    __slots__ = ("_client",)

    def __init__(
        self,
        *,
        region_name: str | None = None,
        profile_name: str | None = None,
        config: BotoConfig | None = None,
        session: boto3.Session | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        self._client = get_client(
            "sqs",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
            endpoint_url=endpoint_url,
        )

    @property
    def raw(self) -> Any:
        return self._client

    def send(
        self,
        queue_url: str,
        body: str,
        *,
        message_attributes: Mapping[str, Any] | None = None,
        message_group_id: str | None = None,
        message_deduplication_id: str | None = None,
        delay_seconds: int | None = None,
    ) -> str:
        with translate_errors():
            resp = self._client.send_message(
                **_send_kwargs(
                    queue_url,
                    body,
                    message_attributes=message_attributes,
                    message_group_id=message_group_id,
                    message_deduplication_id=message_deduplication_id,
                    delay_seconds=delay_seconds,
                )
            )
            return resp["MessageId"]

    def receive(
        self,
        queue_url: str,
        max_messages: int = 1,
        wait_seconds: int = 0,
    ) -> list[Message]:
        with translate_errors():
            resp = self._client.receive_message(
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

    def delete(self, queue_url: str, receipt_handle: str) -> None:
        with translate_errors():
            self._client.delete_message(
                QueueUrl=queue_url, ReceiptHandle=receipt_handle
            )
