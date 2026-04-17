"""Flat, strongly-typed facade over a small subset of AWS S3.

``get_object`` streams the response body a chunk at a time and
``list_keys`` yields keys from the paginator, so neither materializes
unbounded response data into memory.
"""

from __future__ import annotations

from typing import Any, Iterator

import boto3
from botocore.config import Config as BotoConfig

from boto_lite._client import get_client, translate_errors


def _stream_body(resp: dict[str, Any]) -> Iterator[bytes]:
    body = resp["Body"]
    try:
        for chunk in body.iter_chunks():
            yield chunk
    finally:
        close = getattr(body, "close", None)
        if callable(close):
            try:
                close()
            except Exception:
                pass


def get_object(
    bucket: str,
    key: str,
    *,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
    endpoint_url: str | None = None,
) -> Iterator[bytes]:
    """Stream an object's body as an iterator of byte chunks.

    Returns a generator that yields chunks from
    ``StreamingBody.iter_chunks()``. The underlying streaming body is
    closed on exhaustion, early exit (e.g. ``break``), or exception —
    the caller does not need to manage cleanup. Callers that want the
    full body in memory can do ``b"".join(s3.get_object(...))``.
    """
    with translate_errors():
        client = get_client(
            "s3",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
            endpoint_url=endpoint_url,
        )
        resp = client.get_object(Bucket=bucket, Key=key)
        yield from _stream_body(resp)


def put_object(
    bucket: str,
    key: str,
    body: bytes,
    *,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
    endpoint_url: str | None = None,
) -> None:
    with translate_errors():
        client = get_client(
            "s3",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
            endpoint_url=endpoint_url,
        )
        client.put_object(Bucket=bucket, Key=key, Body=body)


def delete_object(
    bucket: str,
    key: str,
    *,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
    endpoint_url: str | None = None,
) -> None:
    with translate_errors():
        client = get_client(
            "s3",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
            endpoint_url=endpoint_url,
        )
        client.delete_object(Bucket=bucket, Key=key)


def list_keys(
    bucket: str,
    prefix: str = "",
    *,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
    endpoint_url: str | None = None,
) -> Iterator[str]:
    """Yield every key under ``prefix`` via the ``list_objects_v2`` paginator.

    Returns a generator; pages are fetched lazily so memory use is
    bounded by one page (up to 1000 keys) regardless of match count.
    """
    with translate_errors():
        client = get_client(
            "s3",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
            endpoint_url=endpoint_url,
        )
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                yield obj["Key"]


class S3Client:
    """Reusable S3 facade bound to a single underlying boto3 client.

    Use this when you make repeated calls with non-default configuration
    (custom region/profile/endpoint/retry-timeouts/session) and want to
    avoid the per-call client-construction cost of the module-level
    ``s3.*`` functions. The module-level functions remain the simpler
    default for scripts and Lambda handlers.
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
            "s3",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
            endpoint_url=endpoint_url,
        )

    @property
    def raw(self) -> Any:
        """Escape hatch: the underlying boto3 S3 client."""
        return self._client

    def get_object(self, bucket: str, key: str) -> Iterator[bytes]:
        with translate_errors():
            resp = self._client.get_object(Bucket=bucket, Key=key)
            yield from _stream_body(resp)

    def put_object(self, bucket: str, key: str, body: bytes) -> None:
        with translate_errors():
            self._client.put_object(Bucket=bucket, Key=key, Body=body)

    def delete_object(self, bucket: str, key: str) -> None:
        with translate_errors():
            self._client.delete_object(Bucket=bucket, Key=key)

    def list_keys(self, bucket: str, prefix: str = "") -> Iterator[str]:
        with translate_errors():
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    yield obj["Key"]
