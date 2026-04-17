"""Flat, strongly-typed facade over a small subset of AWS Secrets Manager."""

from __future__ import annotations

from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from boto_lite._client import get_client, translate_errors
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
            "secretsmanager",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
            endpoint_url=endpoint_url,
        )

    @property
    def raw(self) -> Any:
        return self._client

    def get(
        self,
        name: str,
        *,
        version_id: str | None = None,
        version_stage: str | None = None,
    ) -> str | bytes:
        with translate_errors():
            resp = self._client.get_secret_value(
                **_get_kwargs(name, version_id, version_stage)
            )
            return _unwrap_secret(name, resp)

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
