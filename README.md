# boto-lite

A minimal, zero-dependency (beyond `boto3`) Python facade over AWS **S3**, **SQS**, and **Secrets Manager**.

Flat public API. Strong types. Predictable errors. Streaming-by-default where it matters. Full dependency injection for sessions and configuration.

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
from boto_lite.exceptions import NotFoundError, AuthError, ValidationError

# ---- S3 ----------------------------------------------------------------
s3.put_object("my-bucket", "hello.txt", b"hello world")

# s3.get_object returns a STREAMING GENERATOR of bytes chunks.
# Stream to disk/socket/etc. without materializing the full body:
with open("out.bin", "wb") as fh:
    for chunk in s3.get_object("my-bucket", "hello.txt"):
        fh.write(chunk)
# Or join for the full body when it's actually small:
body: bytes = b"".join(s3.get_object("my-bucket", "hello.txt"))

# s3.list_keys is a GENERATOR that drives the list_objects_v2 paginator
# lazily — memory use is bounded by one page (≤1000 keys) regardless of
# how many keys match.
for key in s3.list_keys("my-bucket", prefix="logs/"):
    print(key)

s3.delete_object("my-bucket", "hello.txt")

# ---- SQS ---------------------------------------------------------------
sqs.send("https://sqs.us-east-1.amazonaws.com/123/my-q", "payload")
for msg in sqs.receive("https://sqs.us-east-1.amazonaws.com/123/my-q",
                       max_messages=10, wait_seconds=20):  # long poll
    print(msg.body)
    sqs.delete("https://sqs.us-east-1.amazonaws.com/123/my-q",
               msg.receipt_handle)

# ---- Secrets Manager ---------------------------------------------------
secrets.put("db/password", "s3cr3t")            # SecretString
secrets.put("db/cert", b"\x30\x82...")          # SecretBinary
value: str | bytes = secrets.get("db/password")
secrets.delete("db/password", force_delete_without_recovery=True)
# or: secrets.delete("db/password", recovery_window_in_days=7)
```

## Streaming & pagination

- **`s3.get_object(bucket, key, ...) -> Iterator[bytes]`** — returns a
  generator over `StreamingBody.iter_chunks()`. The object body is never
  fully materialized by the facade; you iterate it chunk by chunk.
- **`s3.list_keys(bucket, prefix, ...) -> Iterator[str]`** — returns a
  generator that drives `list_objects_v2`'s paginator and `yield`s each
  key. Pages are fetched on demand, so a listing of millions of keys
  uses constant memory.

Both are lazy: exceptions (including translated `NotFoundError`,
`AuthError`, `ValidationError`, and base `BotoLiteError`) surface on the
first `next()`, not at the `get_object(...)` / `list_keys(...)` call
site.

## Dependency injection

Every public function in `s3`, `sqs`, and `secrets` accepts the same set
of keyword-only dependency-injection arguments:

| Argument | Type | Behavior |
|---|---|---|
| `region_name` | `str \| None` | AWS region override. |
| `profile_name` | `str \| None` | Named profile from `~/.aws/credentials`. |
| `config` | `botocore.config.Config \| None` | Full retry / timeout / addressing-style override. **Bypasses the internal client cache.** |
| `session` | `boto3.Session \| None` | Use this pre-built session directly. **Bypasses the internal client cache entirely**; `boto3.Session(...)` is never called. |

Examples:

```python
import boto3
from botocore.config import Config

# Named profile + specific region:
s3.put_object("my-bucket", "k", b"v",
              profile_name="prod", region_name="eu-west-1")

# Custom retry / timeout behavior:
tight = Config(connect_timeout=2, read_timeout=5,
               retries={"max_attempts": 2, "mode": "standard"})
body = b"".join(s3.get_object("my-bucket", "k", config=tight))

# Full session injection — e.g., an assumed-role session from STS,
# or a session pointed at LocalStack / a custom endpoint:
session = boto3.Session(region_name="us-east-1")
for key in s3.list_keys("my-bucket", session=session):
    ...
```

When none of `config` / `session` are passed, clients are cached
internally per `(service, region_name, profile_name)` behind a
`threading.Lock` — concurrent callers share a single client without
racing on first touch.

## Error model

All service calls translate botocore errors into a small typed hierarchy:

- `NotFoundError` — missing bucket/key/queue/secret.
- `AuthError` — credentials, signing, or access-denied failures
  (including `NoCredentialsError`).
- `ValidationError` — local parameter validation failures
  (`ParamValidationError`).
- `BotoLiteError` — base class; also catches `EndpointConnectionError`,
  `ReadTimeoutError`, and any otherwise-unmapped `ClientError`.

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

## Tests

```bash
uv run pytest
```

The unit tests use `botocore.stub.Stubber` and run fully offline. The
integration suite (`tests/test_integration.py`) talks to a real
**LocalStack** instance over the wire, exercising real S3 round-trips
(put/list/stream-get/delete) and real SQS long-polling. It is skipped
automatically when LocalStack isn't reachable:

```bash
docker compose up -d localstack
uv run pytest tests/test_integration.py
```

## Scope

Covered today:

- **S3**: `get_object` (streaming), `put_object`, `delete_object`,
  `list_keys` (generator over pagination).
- **SQS**: `send`, `receive` (short or long poll), `delete`, plus a
  frozen `Message` dataclass.
- **Secrets Manager**: `get` (string or binary), `put` (create-or-update,
  string or binary), `delete` (with `recovery_window_in_days` or
  `force_delete_without_recovery`).
- **Cross-cutting**: per-call `region_name` / `profile_name` / `config` /
  `session` injection on every function.

Not yet wrapped (open an issue if you need one): presigned URLs,
multipart upload, copy/head, batch SQS operations, SQS visibility timeout
adjustments, FIFO-specific params.

## License

MIT.
