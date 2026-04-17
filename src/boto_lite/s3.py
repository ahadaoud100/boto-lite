"""Flat, strongly-typed facade over a small subset of AWS S3.

``get_object`` streams the response body a chunk at a time and
``list_keys`` yields keys from the paginator, so neither materializes
unbounded response data into memory.
"""

from __future__ import annotations

from typing import Iterator

import boto3
from botocore.config import Config as BotoConfig

from boto_lite._client import get_client, translate_errors


def get_object(
    bucket: str,
    key: str,
    *,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
) -> Iterator[bytes]:
    """Stream an object's body as an iterator of byte chunks.

    Returns a generator that yields chunks from
    ``StreamingBody.iter_chunks()``. Callers that genuinely want the
    full body in memory can do ``b"".join(s3.get_object(...))``; callers
    handling large objects can consume chunk-by-chunk (write to disk,
    pipe downstream, etc.) without ever materializing the whole body.
    """
    with translate_errors():
        client = get_client(
            "s3",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
        )
        resp = client.get_object(Bucket=bucket, Key=key)
        for chunk in resp["Body"].iter_chunks():
            yield chunk


def put_object(
    bucket: str,
    key: str,
    body: bytes,
    *,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
) -> None:
    with translate_errors():
        client = get_client(
            "s3",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
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
) -> None:
    with translate_errors():
        client = get_client(
            "s3",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
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
) -> Iterator[str]:
    """Yield every key under ``prefix`` via the ``list_objects_v2`` paginator.

    Returns a generator. Each page from AWS is drained lazily, so
    memory use is bounded by the page size (up to 1000 keys) regardless
    of how many keys match overall.
    """
    with translate_errors():
        client = get_client(
            "s3",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
        )
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                yield obj["Key"]
