"""Internal boto3 session/client helpers and error translation."""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from boto_lite.exceptions import AuthError, NotFoundError, BotoLiteError

_NOT_FOUND_CODES = frozenset(
    {
        "NoSuchKey",
        "NoSuchBucket",
        "ResourceNotFoundException",
        "QueueDoesNotExist",
        "AWS.SimpleQueueService.NonExistentQueue",
    }
)
_AUTH_CODES = frozenset(
    {
        "AccessDenied",
        "AccessDeniedException",
        "UnauthorizedOperation",
        "InvalidAccessKeyId",
        "SignatureDoesNotMatch",
        "ExpiredToken",
        "ExpiredTokenException",
    }
)


@lru_cache(maxsize=None)
def get_client(service: str, region: str | None = None) -> Any:
    """Return a cached boto3 client for the given AWS service."""
    return boto3.client(service, region_name=region)


@contextmanager
def translate_errors() -> Iterator[None]:
    """Map botocore errors to typed boto_lite exceptions."""
    try:
        yield
    except NoCredentialsError as e:
        raise AuthError(str(e)) from e
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in _NOT_FOUND_CODES:
            raise NotFoundError(str(e)) from e
        if code in _AUTH_CODES:
            raise AuthError(str(e)) from e
        raise BotoLiteError(str(e)) from e
