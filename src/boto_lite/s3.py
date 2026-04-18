"""Flat, strongly-typed facade over a small subset of AWS S3.

``get_object`` streams the response body a chunk at a time and
``list_keys`` yields keys from the paginator, so neither materializes
unbounded response data into memory.
"""

from __future__ import annotations

import itertools
from typing import Any, BinaryIO, Callable, Iterable, Iterator, Literal, Mapping

import boto3
from botocore.config import Config as BotoConfig

from boto_lite._client import get_client, register_events, translate_errors
from boto_lite.exceptions import ValidationError

_MIN_PART_SIZE = 5 * 1024 * 1024  # AWS S3 multipart minimum (except last part)
_DEFAULT_PART_SIZE = 8 * 1024 * 1024


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


def _iter_parts(
    data: Iterable[bytes] | BinaryIO, part_size: int
) -> Iterator[bytes]:
    """Yield chunks of exactly ``part_size`` bytes (last chunk may be smaller).

    Accepts either an iterable of ``bytes`` (re-chunked) or a file-like
    object with a ``.read(n)`` method (read directly).
    """
    if hasattr(data, "read"):
        reader: BinaryIO = data  # type: ignore[assignment]
        while True:
            buf = reader.read(part_size)
            if not buf:
                return
            yield buf
        return

    buffer = bytearray()
    for piece in data:  # type: ignore[union-attr]
        buffer.extend(piece)
        while len(buffer) >= part_size:
            yield bytes(buffer[:part_size])
            del buffer[:part_size]
    if buffer:
        yield bytes(buffer)


def _upload_stream_on(
    client: Any,
    bucket: str,
    key: str,
    data: Iterable[bytes] | BinaryIO,
    *,
    part_size: int,
    content_type: str | None,
) -> str:
    if part_size < _MIN_PART_SIZE:
        raise ValidationError(
            f"part_size must be at least {_MIN_PART_SIZE} bytes (AWS S3 minimum)"
        )

    parts = _iter_parts(data, part_size)
    try:
        first = next(parts)
    except StopIteration:
        first = b""
    try:
        second = next(parts)
    except StopIteration:
        # Fits in one part: use simple PutObject, skip the multipart machinery.
        put_kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key, "Body": first}
        if content_type is not None:
            put_kwargs["ContentType"] = content_type
        with translate_errors():
            resp = client.put_object(**put_kwargs)
        return resp.get("ETag", "")

    create_kwargs: dict[str, Any] = {"Bucket": bucket, "Key": key}
    if content_type is not None:
        create_kwargs["ContentType"] = content_type
    with translate_errors():
        create = client.create_multipart_upload(**create_kwargs)
    upload_id = create["UploadId"]

    completed: list[dict[str, Any]] = []
    try:
        for part_number, chunk in enumerate(
            itertools.chain([first, second], parts), start=1
        ):
            with translate_errors():
                resp = client.upload_part(
                    Bucket=bucket,
                    Key=key,
                    UploadId=upload_id,
                    PartNumber=part_number,
                    Body=chunk,
                )
            completed.append({"ETag": resp["ETag"], "PartNumber": part_number})

        with translate_errors():
            result = client.complete_multipart_upload(
                Bucket=bucket,
                Key=key,
                UploadId=upload_id,
                MultipartUpload={"Parts": completed},
            )
        return result.get("ETag", "")
    except BaseException:
        try:
            client.abort_multipart_upload(
                Bucket=bucket, Key=key, UploadId=upload_id
            )
        except Exception:
            pass
        raise


def _presigned_url_on(
    client: Any,
    bucket: str,
    key: str,
    *,
    operation: str,
    expires_in: int,
    extra_params: Mapping[str, Any] | None,
) -> str:
    params: dict[str, Any] = {"Bucket": bucket, "Key": key}
    if extra_params:
        params.update(extra_params)
    with translate_errors():
        return client.generate_presigned_url(
            ClientMethod=operation,
            Params=params,
            ExpiresIn=expires_in,
        )


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


def upload_stream(
    bucket: str,
    key: str,
    data: Iterable[bytes] | BinaryIO,
    *,
    part_size: int = _DEFAULT_PART_SIZE,
    content_type: str | None = None,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
    endpoint_url: str | None = None,
) -> str:
    """Upload an iterator or file-like object to S3 using multipart.

    ``data`` may be either an iterable yielding ``bytes`` (re-chunked
    into parts of ``part_size`` bytes) or any file-like object with a
    ``.read(n)`` method. ``part_size`` must be at least 5 MiB — the AWS
    minimum — and defaults to 8 MiB. Content that fits in a single
    part uses ``PutObject`` directly; otherwise a multipart upload is
    started, each part uploaded, and the upload completed. On any
    exception during the part loop the multipart upload is aborted on
    a best-effort basis so you are not billed for orphaned parts.

    Returns the final object's ``ETag``.
    """
    client = get_client(
        "s3",
        region_name=region_name,
        profile_name=profile_name,
        config=config,
        session=session,
        endpoint_url=endpoint_url,
    )
    return _upload_stream_on(
        client, bucket, key, data, part_size=part_size, content_type=content_type
    )


def presigned_url(
    bucket: str,
    key: str,
    *,
    operation: Literal["get_object", "put_object"] = "get_object",
    expires_in: int = 3600,
    extra_params: Mapping[str, Any] | None = None,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
    endpoint_url: str | None = None,
) -> str:
    """Return a presigned URL for a single S3 operation on ``bucket/key``.

    ``operation`` selects the S3 method being presigned — ``get_object``
    (default) for downloads, ``put_object`` for browser-side uploads.
    ``expires_in`` is in seconds (default 1 hour). ``extra_params``
    merges additional client parameters such as
    ``ResponseContentDisposition`` for GETs or ``ContentType`` for PUTs.
    URL signing is local to the client — no network call is made.
    """
    client = get_client(
        "s3",
        region_name=region_name,
        profile_name=profile_name,
        config=config,
        session=session,
        endpoint_url=endpoint_url,
    )
    return _presigned_url_on(
        client,
        bucket,
        key,
        operation=operation,
        expires_in=expires_in,
        extra_params=extra_params,
    )


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
        events: Mapping[str, Callable[..., Any]] | None = None,
    ) -> None:
        self._client = get_client(
            "s3",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
            endpoint_url=endpoint_url,
        )
        register_events(self._client, events)

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

    def upload_stream(
        self,
        bucket: str,
        key: str,
        data: Iterable[bytes] | BinaryIO,
        *,
        part_size: int = _DEFAULT_PART_SIZE,
        content_type: str | None = None,
    ) -> str:
        return _upload_stream_on(
            self._client,
            bucket,
            key,
            data,
            part_size=part_size,
            content_type=content_type,
        )

    def presigned_url(
        self,
        bucket: str,
        key: str,
        *,
        operation: Literal["get_object", "put_object"] = "get_object",
        expires_in: int = 3600,
        extra_params: Mapping[str, Any] | None = None,
    ) -> str:
        return _presigned_url_on(
            self._client,
            bucket,
            key,
            operation=operation,
            expires_in=expires_in,
            extra_params=extra_params,
        )

    def delete_object(self, bucket: str, key: str) -> None:
        with translate_errors():
            self._client.delete_object(Bucket=bucket, Key=key)

    def list_keys(self, bucket: str, prefix: str = "") -> Iterator[str]:
        with translate_errors():
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    yield obj["Key"]
