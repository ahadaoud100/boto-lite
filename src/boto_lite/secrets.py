"""Flat, strongly-typed facade over a small subset of AWS Secrets Manager."""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from boto_lite._client import get_client, translate_errors
from boto_lite.exceptions import BotoLiteError


def get(name: str) -> str:
    with translate_errors():
        resp = get_client("secretsmanager").get_secret_value(SecretId=name)
        if "SecretString" not in resp:
            raise BotoLiteError(f"Secret {name!r} is binary; only string secrets supported")
        return resp["SecretString"]


def put(name: str, value: str) -> None:
    with translate_errors():
        client = get_client("secretsmanager")
        try:
            client.create_secret(Name=name, SecretString=value)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ResourceExistsException":
                client.put_secret_value(SecretId=name, SecretString=value)
            else:
                raise


def delete(name: str, force: bool = False) -> None:
    with translate_errors():
        kwargs: dict[str, Any] = {"SecretId": name}
        if force:
            kwargs["ForceDeleteWithoutRecovery"] = True
        get_client("secretsmanager").delete_secret(**kwargs)
