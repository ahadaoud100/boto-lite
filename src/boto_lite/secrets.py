"""Flat, strongly-typed facade over a small subset of AWS Secrets Manager."""

from __future__ import annotations

import random
import threading
import time
from typing import Any, Callable, Mapping

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from boto_lite._client import get_client, register_events, translate_errors
from boto_lite.exceptions import BotoLiteError, ValidationError


def _get_kwargs(
    name: str,
    version_id: str | None,
    version_stage: str | None,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"SecretId": name}
    if version_id is not None:
        kwargs["VersionId"] = version_id
    if version_stage is not None:
        kwargs["VersionStage"] = version_stage
    return kwargs


def _unwrap_secret(name: str, resp: dict[str, Any]) -> str | bytes:
    if "SecretString" in resp:
        return resp["SecretString"]
    if "SecretBinary" in resp:
        return resp["SecretBinary"]
    raise BotoLiteError(
        f"Secret {name!r} returned neither SecretString nor SecretBinary"
    )


def _put_payload(value: str | bytes) -> dict[str, Any]:
    if isinstance(value, (bytes, bytearray)):
        return {"SecretBinary": bytes(value)}
    return {"SecretString": value}


def _validate_delete_options(
    recovery_window_in_days: int | None,
    force_delete_without_recovery: bool,
) -> None:
    if recovery_window_in_days is not None and force_delete_without_recovery:
        raise ValidationError(
            "recovery_window_in_days and force_delete_without_recovery "
            "are mutually exclusive"
        )


def _delete_kwargs(
    name: str,
    recovery_window_in_days: int | None,
    force_delete_without_recovery: bool,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"SecretId": name}
    if force_delete_without_recovery:
        kwargs["ForceDeleteWithoutRecovery"] = True
    elif recovery_window_in_days is not None:
        kwargs["RecoveryWindowInDays"] = recovery_window_in_days
    return kwargs


def get(
    name: str,
    *,
    version_id: str | None = None,
    version_stage: str | None = None,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
    endpoint_url: str | None = None,
) -> str | bytes:
    """Fetch a secret value.

    Returns ``str`` for a ``SecretString`` secret and ``bytes`` for a
    ``SecretBinary`` secret. ``version_id`` / ``version_stage`` follow
    AWS semantics (default ``AWSCURRENT``; pass ``AWSPREVIOUS`` or a
    specific version id during rotation).
    """
    with translate_errors():
        client = get_client(
            "secretsmanager",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
            endpoint_url=endpoint_url,
        )
        resp = client.get_secret_value(
            **_get_kwargs(name, version_id, version_stage)
        )
        return _unwrap_secret(name, resp)


def put(
    name: str,
    value: str | bytes,
    *,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
    endpoint_url: str | None = None,
) -> None:
    """Create a secret or update its value.

    ``str`` values are written as ``SecretString``; ``bytes`` values as
    ``SecretBinary``.
    """
    payload = _put_payload(value)
    with translate_errors():
        client = get_client(
            "secretsmanager",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
            endpoint_url=endpoint_url,
        )
        try:
            client.create_secret(Name=name, **payload)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceExistsException":
                client.put_secret_value(SecretId=name, **payload)
            else:
                raise


def delete(
    name: str,
    *,
    recovery_window_in_days: int | None = None,
    force_delete_without_recovery: bool = False,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
    endpoint_url: str | None = None,
) -> None:
    """Delete a secret.

    Pass ``recovery_window_in_days`` (7–30, per AWS) to schedule
    deletion with a recovery window, or ``force_delete_without_recovery=True``
    to delete immediately and irrevocably. The two options are mutually
    exclusive (``ValidationError`` if both are supplied); if neither is
    provided, AWS applies its default 30-day recovery window.
    """
    _validate_delete_options(recovery_window_in_days, force_delete_without_recovery)
    with translate_errors():
        client = get_client(
            "secretsmanager",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
            endpoint_url=endpoint_url,
        )
        client.delete_secret(
            **_delete_kwargs(
                name, recovery_window_in_days, force_delete_without_recovery
            )
        )


class SecretsClient:
    """Reusable Secrets Manager facade bound to a single underlying client.

    Use this when you make repeated calls with non-default configuration
    and want to avoid the per-call client-construction cost of the
    module-level ``secrets.*`` functions.

    Pass ``ttl`` (in seconds) to enable an in-process cache for
    :meth:`get`. Subsequent reads of the same ``(name, version_id,
    version_stage)`` tuple within the TTL window return the cached
    value without calling Secrets Manager. The cache is per-instance
    and thread-safe. Invalidate entries with :meth:`invalidate`.

    ``jitter`` spreads per-entry expiry downward by a random fraction
    of ``ttl`` so a fleet of instances that cached the same secret at
    the same moment do not all expire together and stampede Secrets
    Manager. Each entry's effective TTL is ``ttl * uniform(1-jitter,
    1)``; the cache never exceeds ``ttl``. Default 0.1 (10%). Pass
    ``0.0`` to disable.
    """

    __slots__ = ("_client", "_ttl", "_jitter", "_cache", "_cache_lock")

    def __init__(
        self,
        *,
        ttl: float | None = None,
        jitter: float = 0.1,
        region_name: str | None = None,
        profile_name: str | None = None,
        config: BotoConfig | None = None,
        session: boto3.Session | None = None,
        endpoint_url: str | None = None,
        events: Mapping[str, Callable[..., Any]] | None = None,
    ) -> None:
        if ttl is not None and ttl <= 0:
            raise ValidationError("ttl must be positive")
        if not 0.0 <= jitter < 1.0:
            raise ValidationError("jitter must satisfy 0 <= jitter < 1")
        self._client = get_client(
            "secretsmanager",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
            endpoint_url=endpoint_url,
        )
        register_events(self._client, events)
        self._ttl: float | None = ttl
        self._jitter = jitter
        self._cache: dict[tuple[str, str | None, str | None], tuple[str | bytes, float]] = {}
        self._cache_lock = threading.Lock()

    @property
    def raw(self) -> Any:
        return self._client

    def _fetch(
        self, name: str, version_id: str | None, version_stage: str | None
    ) -> str | bytes:
        with translate_errors():
            resp = self._client.get_secret_value(
                **_get_kwargs(name, version_id, version_stage)
            )
            return _unwrap_secret(name, resp)

    def get(
        self,
        name: str,
        *,
        version_id: str | None = None,
        version_stage: str | None = None,
    ) -> str | bytes:
        if self._ttl is None:
            return self._fetch(name, version_id, version_stage)
        key = (name, version_id, version_stage)
        now = time.monotonic()
        with self._cache_lock:
            hit = self._cache.get(key)
            if hit is not None and now < hit[1]:
                return hit[0]
        # Fetch outside the lock; tolerate duplicate in-flight fetches.
        value = self._fetch(name, version_id, version_stage)
        effective_ttl = self._ttl * random.uniform(1.0 - self._jitter, 1.0)
        with self._cache_lock:
            self._cache[key] = (value, time.monotonic() + effective_ttl)
        return value

    def invalidate(self, name: str | None = None) -> None:
        """Drop cache entries. Pass ``name`` to invalidate only that
        secret's entries (across all version ids/stages), or omit it
        to clear the entire cache. No-op when the cache is disabled.
        """
        if self._ttl is None:
            return
        with self._cache_lock:
            if name is None:
                self._cache.clear()
            else:
                for key in [k for k in self._cache if k[0] == name]:
                    del self._cache[key]

    def put(self, name: str, value: str | bytes) -> None:
        payload = _put_payload(value)
        with translate_errors():
            try:
                self._client.create_secret(Name=name, **payload)
            except ClientError as e:
                if e.response.get("Error", {}).get("Code") == "ResourceExistsException":
                    self._client.put_secret_value(SecretId=name, **payload)
                else:
                    raise

    def delete(
        self,
        name: str,
        *,
        recovery_window_in_days: int | None = None,
        force_delete_without_recovery: bool = False,
    ) -> None:
        _validate_delete_options(
            recovery_window_in_days, force_delete_without_recovery
        )
        with translate_errors():
            self._client.delete_secret(
                **_delete_kwargs(
                    name,
                    recovery_window_in_days,
                    force_delete_without_recovery,
                )
            )
