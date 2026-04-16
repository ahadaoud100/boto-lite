# boto-lite

A minimal, zero-dependency (beyond `boto3`) Python facade over AWS **S3**, **SQS**, and **Secrets Manager**.

Flat public API. Strong types. Predictable errors. Nothing else.

## Install

```bash
pip install boto-lite
# or
uv add boto-lite
```

Requires Python 3.10+ and `boto3>=1.42.89`.

## Usage

```python
from boto_lite import s3, sqs, secrets, BotoLiteError
from boto_lite.exceptions import NotFoundError, AuthError

# S3
s3.put_object("my-bucket", "hello.txt", b"hello world")
body: bytes = s3.get_object("my-bucket", "hello.txt")
keys: list[str] = s3.list_keys("my-bucket", prefix="logs/")
s3.delete_object("my-bucket", "hello.txt")

# SQS
sqs.send("https://sqs.us-east-1.amazonaws.com/123/my-q", "payload")
for msg in sqs.receive("https://sqs.us-east-1.amazonaws.com/123/my-q"):
    print(msg.body)
    sqs.delete("https://sqs.us-east-1.amazonaws.com/123/my-q", msg.receipt_handle)

# Secrets Manager
secrets.put("db/password", "s3cr3t")
value: str = secrets.get("db/password")
secrets.delete("db/password", force=True)
```

All service calls translate boto3's `ClientError` / `NoCredentialsError` into three tidy exceptions:

- `NotFoundError` — missing bucket/key/queue/secret.
- `AuthError` — credentials, signing, or access-denied failures.
- `BotoLiteError` — base class; covers everything else.

## Why — token benchmark

A typical "upload a file to S3 and read it back" script, in raw `boto3` (with the error handling everyone eventually writes) vs. the `boto_lite` facade:

| Version | Tokens (cl100k_base) | Lines |
|---|---:|---:|
| Raw `boto3` | **186** | 19 |
| `boto_lite` facade | **65** | 9 |
| **Saved** | **121 (65.1%)** | 10 |

Reproduce locally:

```bash
uv sync --group dev
uv run python benchmark_tokens.py
```

Source: [`benchmark_tokens.py`](./benchmark_tokens.py).

## Scope

Intentionally small. Covered today:

- **S3**: `get_object`, `put_object`, `delete_object`, `list_keys` (paginated).
- **SQS**: `send`, `receive` (long-poll), `delete`, plus a frozen `Message` dataclass.
- **Secrets Manager**: `get` (strings only), `put` (create-or-update), `delete` (with `force`).

Not covered (by design — open an issue if you need one): presigned URLs, multipart, copy/head, batch SQS, FIFO params, binary secrets.

## License

MIT.
