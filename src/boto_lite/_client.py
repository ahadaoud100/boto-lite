"""Internal boto3 session/client helpers and error translation."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Mapping

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
    ParamValidationError,
    ReadTimeoutError,
)

from boto_lite.exceptions import (
    AuthError,
    BotoLiteError,
    NotFoundError,
    ValidationError,
)

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


# Cache key: (service, region_name, profile_name, endpoint_url). Custom
# ``config`` and injected ``session`` bypass this cache entirely.
_ClientCacheKey = tuple[str, str | None, str | None, str | None]
_client_cache: dict[_ClientCacheKey, Any] = {}
_client_lock = threading.Lock()


def get_client(
    service: str,
    *,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
    endpoint_url: str | None = None,
) -> Any:
    """Return a boto3 client for the given AWS service.

    - If ``session`` is provided, it is used directly and the internal
      cache is bypassed. ``region_name``, ``config``, and ``endpoint_url``
      are still forwarded to ``session.client()`` when supplied;
      ``profile_name`` is ignored because the session already carries
      its own profile.
    - If ``config`` is provided without a ``session``, a fresh
      ``boto3.Session`` is built from ``region_name`` / ``profile_name``
      and a new client is returned uncached.
    - Otherwise, clients are cached per
      ``(service, region_name, profile_name, endpoint_url)`` behind a
      lock so concurrent callers share a single instance without racing
      on first touch.
    """
    if session is not None:
        kwargs: dict[str, Any] = {}
        if region_name is not None:
            kwargs["region_name"] = region_name
        if config is not None:
            kwargs["config"] = config
        if endpoint_url is not None:
            kwargs["endpoint_url"] = endpoint_url
        return session.client(service, **kwargs)

    if config is not None:
        new_session = boto3.Session(
            profile_name=profile_name, region_name=region_name
        )
        client_kwargs: dict[str, Any] = {"config": config}
        if endpoint_url is not None:
            client_kwargs["endpoint_url"] = endpoint_url
        return new_session.client(service, **client_kwargs)

    key: _ClientCacheKey = (service, region_name, profile_name, endpoint_url)
    with _client_lock:
        client = _client_cache.get(key)
        if client is None:
            new_session = boto3.Session(
                profile_name=profile_name, region_name=region_name
            )
            if endpoint_url is not None:
                client = new_session.client(service, endpoint_url=endpoint_url)
            else:
                client = new_session.client(service)
            _client_cache[key] = client
    return client


def register_events(
    client: Any, events: Mapping[str, Callable[..., Any]] | None
) -> None:
    """Register ``(event_name, handler)`` pairs on a boto3 client's
    event system. No-op when ``events`` is ``None`` or empty. Handlers
    receive the standard botocore event kwargs (``event_name``,
    ``**kwargs`` — contents vary by event); see the botocore events
    reference for the schema of each hook.
    """
    if not events:
        return
    for event_name, handler in events.items():
        client.meta.events.register(event_name, handler)


@contextmanager
def translate_errors() -> Iterator[None]:
    """Map botocore errors to typed boto_lite exceptions."""
    try:
        yield
    except NoCredentialsError as e:
        raise AuthError(str(e)) from e
    except EndpointConnectionError as e:
        raise BotoLiteError(str(e)) from e
    except ReadTimeoutError as e:
        raise BotoLiteError(str(e)) from e
    except ParamValidationError as e:
        raise ValidationError(str(e)) from e
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in _NOT_FOUND_CODES:
            raise NotFoundError(str(e)) from e
        if code in _AUTH_CODES:
            raise AuthError(str(e)) from e
        raise BotoLiteError(str(e)) from e
