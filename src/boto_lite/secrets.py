"""Flat, strongly-typed facade over a small subset of AWS Secrets Manager."""

from __future__ import annotations

from typing import Any

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from boto_lite._client import get_client, translate_errors
from boto_lite.exceptions import BotoLiteError


def get(
    name: str,
    *,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
) -> str | bytes:
    """Fetch a secret value.

    Returns ``str`` for a ``SecretString`` secret and ``bytes`` for a
    ``SecretBinary`` secret. Raises :class:`BotoLiteError` if the
    response unexpectedly contains neither field.
    """
    with translate_errors():
        client = get_client(
            "secretsmanager",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
        )
        resp = client.get_secret_value(SecretId=name)
        if "SecretString" in resp:
            return resp["SecretString"]
        if "SecretBinary" in resp:
            return resp["SecretBinary"]
        raise BotoLiteError(
            f"Secret {name!r} returned neither SecretString nor SecretBinary"
        )


def put(
    name: str,
    value: str | bytes,
    *,
    region_name: str | None = None,
    profile_name: str | None = None,
    config: BotoConfig | None = None,
    session: boto3.Session | None = None,
) -> None:
    """Create a secret or update its value.

    ``str`` values are written as ``SecretString``; ``bytes`` values as
    ``SecretBinary``.
    """
    payload: dict[str, Any]
    if isinstance(value, (bytes, bytearray)):
        payload = {"SecretBinary": bytes(value)}
    else:
        payload = {"SecretString": value}

    with translate_errors():
        client = get_client(
            "secretsmanager",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
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
) -> None:
    """Delete a secret.

    Pass ``recovery_window_in_days`` (7–30, per AWS) to schedule
    deletion with a recovery window, or ``force_delete_without_recovery=True``
    to delete immediately and irrevocably. The two options are mutually
    exclusive; if neither is provided, AWS applies its default 30-day
    recovery window.
    """
    if recovery_window_in_days is not None and force_delete_without_recovery:
        raise ValueError(
            "recovery_window_in_days and force_delete_without_recovery "
            "are mutually exclusive"
        )

    kwargs: dict[str, Any] = {"SecretId": name}
    if force_delete_without_recovery:
        kwargs["ForceDeleteWithoutRecovery"] = True
    elif recovery_window_in_days is not None:
        kwargs["RecoveryWindowInDays"] = recovery_window_in_days

    with translate_errors():
        client = get_client(
            "secretsmanager",
            region_name=region_name,
            profile_name=profile_name,
            config=config,
            session=session,
        )
        client.delete_secret(**kwargs)
