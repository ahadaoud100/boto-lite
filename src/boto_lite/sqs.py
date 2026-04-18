"""Flat, strongly-typed facade over a small subset of AWS SQS."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

import boto3
from botocore.config import Config as BotoConfig

from boto_lite._client import get_client, translate_errors

_BATCH_LIMIT = 10  # AWS SQS: max entries per SendMessageBatch / DeleteMessageBatch.


@dataclass(frozen=True)
class Message:
    id: str
    body: str
    receipt_handle: str


@dataclass(frozen=True)
class BatchFailure:
    """One failed entry in a batch call, keyed back to the input index."""

    index: int
    code: str
    message: str
    sender_fault: bool


@dataclass(frozen=True)
class SendBatchResult:
    """Outcome of :func:`send_batch` / :meth:`SQSClient.send_batch`.

    ``message_ids[i]`` is the AWS ``MessageId`` for input ``bodies[i]``,
    or ``None`` if that send failed. ``failures`` lists every failed
    entry with the AWS error code and message.
    """

    message_ids: list[str | None]
    failures: list[BatchFailure]

    @property
    def all_succeeded(self) -> bool:
        return not self.failures


@dataclass(frozen=True)
class DeleteBatchResult:
    """Outcome of :func:`delete_batch` / :meth:`SQSClient.delete_batch`.

    Every input receipt handle is considered deleted unless its index
    appears in ``failures``.
    """

    failures: list[BatchFailure]

    @property
    def all_succeeded(self) -> bool:
        return not self.failures


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


def _chunks(seq: Sequence[Any], size: int) -> list[Sequence[Any]]:
    return [seq[i : i + size] for i in range(0, len(seq), size)]


def _send_batch_on(
    client: Any, queue_url: str, bodies: Sequence[str]
) -> SendBatchResult:
    message_ids: list[str | None] = [None] * len(bodies)
    failures: list[BatchFailure] = []
    for chunk_offset, chunk in enumerate(_chunks(list(bodies), _BATCH_LIMIT)):
        base = chunk_offset * _BATCH_LIMIT
        entries = [
            {"Id": str(local_idx), "MessageBody": body}
            for local_idx, body in enumerate(chunk)
        ]
        with translate_errors():
            resp = client.send_message_batch(QueueUrl=queue_url, Entries=entries)
        for s in resp.get("Successful", []):
            message_ids[base + int(s["Id"])] = s["MessageId"]
        for f in resp.get("Failed", []):
            failures.append(
                BatchFailure(
                    index=base + int(f["Id"]),
                    code=f.get("Code", ""),
                    message=f.get("Message", ""),
                    sender_fault=bool(f.get("SenderFault", False)),
                )
            )
    return SendBatchResult(message_ids=message_ids, failures=failures)


def _delete_batch_on(
    client: Any, queue_url: str, receipt_handles: Sequence[str]
) -> DeleteBatchResult:
    failures: list[BatchFailure] = []
    for chunk_offset, chunk in enumerate(
        _chunks(list(receipt_handles), _BATCH_LIMIT)
    ):
        base = chunk_offset * _BATCH_LIMIT
        entries = [
            {"Id": str(local_idx), "ReceiptHandle": rh}
            for local_idx, rh in enumerate(chunk)
        ]
        with translate_errors():
            resp = client.delete_message_batch(
                QueueUrl=queue_url, Entries=entries
            )
        for f in resp.get("Failed", []):
            failures.append(
                BatchFailure(
                    index=base + int(f["Id"]),
                    code=f.get("Code", ""),
                    message=f.get("Message", ""),
                    sender_fault=bool(f.get("SenderFault", False)),
                )
            )
    return DeleteBatchResult(failures=failures)


def _consume_on(
    client: Any,
    queue_url: str,
    handler: Callable[[Message], None],
    *,
    stop: threading.Event | None,
    max_messages: int,
    wait_seconds: int,
    visibility_timeout: int | None,
    on_error: Callable[[Message, BaseException], None] | None,
) -> None:
    receive_kwargs: dict[str, Any] = {
        "QueueUrl": queue_url,
        "MaxNumberOfMessages": max_messages,
        "WaitTimeSeconds": wait_seconds,
    }
    if visibility_timeout is not None:
        receive_kwargs["VisibilityTimeout"] = visibility_timeout

    while not (stop is not None and stop.is_set()):
        with translate_errors():
            resp = client.receive_message(**receive_kwargs)
        for m in resp.get("Messages", []):
            msg = Message(
                id=m["MessageId"],
                body=m["Body"],
                receipt_handle=m["ReceiptHandle"],
            )
            try:
                handler(msg)
            except Exception as exc:  # handler-side failure: do not delete
                if on_error is not None:
                    on_error(msg, exc)
                continue
            with translate_errors():
                client.delete_message(
                    QueueUrl=queue_url, ReceiptHandle=msg.receipt_handle
                )


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


def send_batch(
    queue_url: str,
    bodies: Sequence[str],
    *,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
    endpoint_url: str | None = None,
) -> SendBatchResult:
    """Send an arbitrary number of messages in batches of ten.

    Returns a :class:`SendBatchResult` where ``message_ids[i]`` is the
    AWS ``MessageId`` for ``bodies[i]`` (or ``None`` if that entry
    failed), and ``failures`` is the punch list of failed indices with
    the AWS error code and message. A batch API error — credentials,
    missing queue, network — raises through the normal
    :mod:`boto_lite.exceptions` hierarchy and aborts the call.
    """
    client = get_client(
        "sqs",
        region_name=region_name,
        profile_name=profile_name,
        config=config,
        session=session,
        endpoint_url=endpoint_url,
    )
    return _send_batch_on(client, queue_url, bodies)


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


def delete_batch(
    queue_url: str,
    receipt_handles: Sequence[str],
    *,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
    endpoint_url: str | None = None,
) -> DeleteBatchResult:
    """Delete an arbitrary number of messages in batches of ten.

    Every input is considered deleted unless its index appears in the
    returned :class:`DeleteBatchResult`'s ``failures`` list.
    """
    client = get_client(
        "sqs",
        region_name=region_name,
        profile_name=profile_name,
        config=config,
        session=session,
        endpoint_url=endpoint_url,
    )
    return _delete_batch_on(client, queue_url, receipt_handles)


def consume(
    queue_url: str,
    handler: Callable[[Message], None],
    *,
    stop: threading.Event | None = None,
    max_messages: int = 10,
    wait_seconds: int = 20,
    visibility_timeout: int | None = None,
    on_error: Callable[[Message, BaseException], None] | None = None,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
    endpoint_url: str | None = None,
) -> None:
    """Long-poll consumer loop with delete-on-success, requeue-on-error.

    For each received message, ``handler(msg)`` is invoked. If the
    handler returns normally, the message is deleted. If it raises,
    the message is **not** deleted — SQS will re-deliver it after the
    visibility timeout expires, giving you natural retry semantics —
    and ``on_error(msg, exc)`` is called if supplied.

    The loop exits when ``stop`` (a :class:`threading.Event`) is set.
    Pass ``wait_seconds=20`` (the default) for long polling so an idle
    loop does not hammer SQS. Transport-level errors (``BotoLiteError``
    subclasses) propagate to the caller.
    """
    client = get_client(
        "sqs",
        region_name=region_name,
        profile_name=profile_name,
        config=config,
        session=session,
        endpoint_url=endpoint_url,
    )
    _consume_on(
        client,
        queue_url,
        handler,
        stop=stop,
        max_messages=max_messages,
        wait_seconds=wait_seconds,
        visibility_timeout=visibility_timeout,
        on_error=on_error,
    )


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

    def send_batch(
        self, queue_url: str, bodies: Sequence[str]
    ) -> SendBatchResult:
        return _send_batch_on(self._client, queue_url, bodies)

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

    def delete_batch(
        self, queue_url: str, receipt_handles: Sequence[str]
    ) -> DeleteBatchResult:
        return _delete_batch_on(self._client, queue_url, receipt_handles)

    def consume(
        self,
        queue_url: str,
        handler: Callable[[Message], None],
        *,
        stop: threading.Event | None = None,
        max_messages: int = 10,
        wait_seconds: int = 20,
        visibility_timeout: int | None = None,
        on_error: Callable[[Message, BaseException], None] | None = None,
    ) -> None:
        _consume_on(
            self._client,
            queue_url,
            handler,
            stop=stop,
            max_messages=max_messages,
            wait_seconds=wait_seconds,
            visibility_timeout=visibility_timeout,
            on_error=on_error,
        )
