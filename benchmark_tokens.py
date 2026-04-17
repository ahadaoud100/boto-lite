"""Source-length comparison: raw ``boto3`` vs. the ``boto_lite`` facade.

This is NOT a runtime benchmark. It counts ``cl100k_base`` tokens and
lines for three semantically-equivalent snippets — one each for S3,
SQS, and Secrets Manager. Each pair performs the same work with the
same error behavior, so the only thing being compared is how much
source the reader has to absorb.

To keep the comparison honest, the facade snippets materialize
``s3.get_object`` generators with ``b"".join(...)`` so both snippets
return the same ``bytes`` value.

Run:
    uv run --group dev python benchmark_tokens.py
"""

from __future__ import annotations

import tiktoken


S3_RAW = '''\
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

S3_FACADE = '''\
from boto_lite import s3
from boto_lite.exceptions import NotFoundError, AuthError


def upload_and_fetch(bucket: str, key: str, body: bytes) -> bytes:
    try:
        s3.put_object(bucket, key, body)
        return b"".join(s3.get_object(bucket, key))
    except NotFoundError as exc:
        raise FileNotFoundError(f"{bucket}/{key}") from exc
    except AuthError as exc:
        raise PermissionError(str(exc)) from exc
'''


SQS_RAW = '''\
import boto3
from botocore.exceptions import ClientError, NoCredentialsError


def send_and_drain(queue_url: str, payload: str) -> list[str]:
    try:
        client = boto3.client("sqs")
        client.send_message(QueueUrl=queue_url, MessageBody=payload)
        resp = client.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=5,
        )
        out: list[str] = []
        for m in resp.get("Messages", []):
            out.append(m["Body"])
            client.delete_message(
                QueueUrl=queue_url, ReceiptHandle=m["ReceiptHandle"],
            )
        return out
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "AWS.SimpleQueueService.NonExistentQueue":
            raise FileNotFoundError(queue_url) from exc
        raise
    except NoCredentialsError as exc:
        raise PermissionError("no credentials") from exc
'''

SQS_FACADE = '''\
from boto_lite import sqs
from boto_lite.exceptions import NotFoundError, AuthError


def send_and_drain(queue_url: str, payload: str) -> list[str]:
    try:
        sqs.send(queue_url, payload)
        msgs = sqs.receive(queue_url, max_messages=10, wait_seconds=5)
        for m in msgs:
            sqs.delete(queue_url, m.receipt_handle)
        return [m.body for m in msgs]
    except NotFoundError as exc:
        raise FileNotFoundError(queue_url) from exc
    except AuthError as exc:
        raise PermissionError(str(exc)) from exc
'''


SECRETS_RAW = '''\
import boto3
from botocore.exceptions import ClientError, NoCredentialsError


def get_or_create(name: str, value: str) -> str:
    try:
        client = boto3.client("secretsmanager")
        try:
            resp = client.get_secret_value(SecretId=name)
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ResourceNotFoundException":
                raise
            client.create_secret(Name=name, SecretString=value)
            return value
        if "SecretString" in resp:
            return resp["SecretString"]
        return resp["SecretBinary"].decode()
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("AccessDeniedException", "UnrecognizedClientException"):
            raise PermissionError(code) from exc
        raise
    except NoCredentialsError as exc:
        raise PermissionError("no credentials") from exc
'''

SECRETS_FACADE = '''\
from boto_lite import secrets
from boto_lite.exceptions import NotFoundError, AuthError


def get_or_create(name: str, value: str) -> str:
    try:
        v = secrets.get(name)
        return v if isinstance(v, str) else v.decode()
    except NotFoundError:
        secrets.put(name, value)
        return value
    except AuthError as exc:
        raise PermissionError(str(exc)) from exc
'''


TASKS = [
    ("S3 upload+fetch",    S3_RAW,      S3_FACADE),
    ("SQS send+drain",     SQS_RAW,     SQS_FACADE),
    ("Secrets get-or-create", SECRETS_RAW, SECRETS_FACADE),
]


def _count(enc, text: str) -> int:
    return len(enc.encode(text))


def main() -> None:
    enc = tiktoken.get_encoding("cl100k_base")

    header = f"{'Task':<26}{'raw tok':>8}{'lib tok':>8}{'saved':>8}{'raw L':>8}{'lib L':>8}"
    print(header)
    print("-" * len(header))

    total_raw = total_lib = total_raw_lines = total_lib_lines = 0
    for name, raw, lib in TASKS:
        rt, lt = _count(enc, raw), _count(enc, lib)
        rl, ll = raw.count("\n"), lib.count("\n")
        total_raw += rt
        total_lib += lt
        total_raw_lines += rl
        total_lib_lines += ll
        saved = rt - lt
        print(f"{name:<26}{rt:>8}{lt:>8}{saved:>+8}{rl:>8}{ll:>8}")

    print("-" * len(header))
    saved = total_raw - total_lib
    pct = (saved / total_raw) * 100 if total_raw else 0.0
    print(
        f"{'TOTAL':<26}{total_raw:>8}{total_lib:>8}{saved:>+8}"
        f"{total_raw_lines:>8}{total_lib_lines:>8}"
    )
    print(f"\nSource-length delta: {saved} tokens ({pct:.1f}%) shorter with boto_lite.")
    print("Note: this measures source length, not runtime. See benchmark_runtime.py.")


if __name__ == "__main__":
    main()
