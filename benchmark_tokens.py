"""Compare token counts of a standard S3 upload-and-fetch script written in
raw boto3 versus the equivalent written against the `boto_lite` facade.

Run:
    uv run --group dev python benchmark_tokens.py

Uses OpenAI's `tiktoken` (cl100k_base) as a widely-cited token proxy.
"""

from __future__ import annotations

import tiktoken

RAW_BOTO3 = '''\
import boto3
from botocore.exceptions import ClientError, NoCredentialsError


def upload_and_fetch(bucket: str, key: str, body: bytes) -> bytes:
    try:
        client = boto3.client("s3")
        client.put_object(Bucket=bucket, Key=key, Body=body)
        resp = client.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read()
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "NoSuchBucket", "404"):
            raise FileNotFoundError(f"{bucket}/{key}") from exc
        if code in ("AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch"):
            raise PermissionError(code) from exc
        raise
    except NoCredentialsError as exc:
        raise PermissionError("no credentials") from exc
'''

BOTO_LITE_FACADE = '''\
from boto_lite import s3, BotoLiteError


def upload_and_fetch(bucket: str, key: str, body: bytes) -> bytes:
    try:
        s3.put_object(bucket, key, body)
        return s3.get_object(bucket, key)
    except BotoLiteError:
        raise
'''


def count(text: str) -> int:
    enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def main() -> None:
    raw_tokens = count(RAW_BOTO3)
    facade_tokens = count(BOTO_LITE_FACADE)
    raw_lines = RAW_BOTO3.count("\n")
    facade_lines = BOTO_LITE_FACADE.count("\n")
    saved = raw_tokens - facade_tokens
    pct = (saved / raw_tokens) * 100 if raw_tokens else 0.0

    print(f"raw boto3       : {raw_tokens:>4} tokens, {raw_lines:>2} lines")
    print(f"boto_lite facade: {facade_tokens:>4} tokens, {facade_lines:>2} lines")
    print(f"saved           : {saved:>4} tokens ({pct:.1f}%)")


if __name__ == "__main__":
    main()
