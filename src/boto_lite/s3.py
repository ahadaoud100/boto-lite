"""Flat, strongly-typed facade over a small subset of AWS S3."""

from __future__ import annotations

from boto_lite._client import get_client, translate_errors


def get_object(bucket: str, key: str) -> bytes:
    with translate_errors():
        resp = get_client("s3").get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()


def put_object(bucket: str, key: str, body: bytes) -> None:
    with translate_errors():
        get_client("s3").put_object(Bucket=bucket, Key=key, Body=body)


def delete_object(bucket: str, key: str) -> None:
    with translate_errors():
        get_client("s3").delete_object(Bucket=bucket, Key=key)


def list_keys(bucket: str, prefix: str = "") -> list[str]:
    with translate_errors():
        paginator = get_client("s3").get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys
