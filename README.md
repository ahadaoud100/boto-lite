# boto-lite

A tiny, typed facade over AWS **S3**, **SQS**, and **Secrets Manager**.
One dependency (`boto3`). Flat functions for the common cases, bound
client classes for repeated work, and a `raw` escape hatch when you
need the underlying `boto3.client` directly.

```python
from boto_lite import s3, sqs, secrets

s3.put_object("my-bucket", "hello.txt", b"hello world")
body = b"".join(s3.get_object("my-bucket", "hello.txt"))

sqs.send("https://sqs.../my-q", "payload")

api_key = secrets.get("third-party/api-key")
```

## Install

```bash
pip install boto-lite        # or: uv add boto-lite
```

Python 3.10+. Sole runtime dependency: `boto3>=1.42.89`.

## Who this is for

- **One-off scripts** that need to move a few objects in or out of S3
  without the full boto3 ceremony.
- **AWS Lambda handlers** where you want readable control flow and
  typed errors without pulling in a framework.
- **Small services** that touch S3/SQS/Secrets from a handful of call
  sites and benefit from a cached client per process.
- **Local development** against **LocalStack** via `endpoint_url` or a
  pre-built `boto3.Session`.

If you need niche S3 features (object-level ACLs, replication,
inventory, lifecycle rules, …) reach for raw `boto3` or use
`boto_lite`'s `raw` escape hatch (below). The library covers the
everyday operations including streaming multipart upload and
presigned URLs; it doesn't try to wrap every parameter AWS ships.

## Two ways to call it

### 1. Module functions — simplest

Every operation is available as a function on `s3`, `sqs`, or
`secrets`. Each call builds (or reuses) a cached `boto3.client`.

```python
from boto_lite import s3, sqs, secrets

s3.put_object("bucket", "k", b"data")
for key in s3.list_keys("bucket", prefix="logs/"):     # generator
    ...

sqs.send(queue_url, "payload", delay_seconds=5)
for msg in sqs.receive(queue_url, max_messages=10, wait_seconds=20):
    sqs.delete(queue_url, msg.receipt_handle)

secrets.put("db/password", "s3cr3t")
value = secrets.get("db/password")                     # str | bytes
```

### 2. Bound clients — when you make many calls

`S3Client`, `SQSClient`, and `SecretsClient` build the underlying
`boto3.client` exactly once in their constructor and reuse it for every
method. Use them when the same handler calls `put_object` ten times,
or when you want a single object to pass around.

```python
from boto_lite import S3Client, SQSClient, SecretsClient

s3c = S3Client(region_name="eu-west-1")
for k in s3c.list_keys("bkt", prefix="2026/"):
    s3c.delete_object("bkt", k)

# Multipart upload from an iterator or file-like object.
with open("dump.bin", "rb") as fh:
    etag = s3c.upload_stream("bkt", "dump.bin", fh)  # 8 MiB parts

# Presigned download URL, expires in an hour.
url = s3c.presigned_url("bkt", "report.pdf", expires_in=3600)

sqsc = SQSClient(endpoint_url="http://localhost:4566")    # LocalStack
msg_id = sqsc.send(queue_url, "hi",
                   message_group_id="g1",
                   message_deduplication_id="d1")        # FIFO

# Arbitrary-length batch send; library chunks to SQS's 10-entry limit.
result = sqsc.send_batch(queue_url, [f"msg-{i}" for i in range(37)])
if not result.all_succeeded:
    retry = [queue_url for f in result.failures]  # reach out via f.index

# Long-poll consumer loop with graceful shutdown:
stop = threading.Event()

def handle(msg):
    process(msg.body)  # raise to leave the message for redelivery

sqsc.consume(queue_url, handle, stop=stop, wait_seconds=20)

sec = SecretsClient(profile_name="prod", ttl=300)  # 5-minute cache
current = sec.get("api/key")           # fetches
again = sec.get("api/key")             # cached
previous = sec.get("api/key", version_stage="AWSPREVIOUS")
sec.invalidate("api/key")              # drop before next read
```

Each class exposes the same DI keyword arguments as the module
functions: `region_name`, `profile_name`, `config`, `endpoint_url`,
`session`.

### Escape hatch: `.raw`

Every bound client exposes the underlying `boto3.client` via `.raw`.
Reach through it whenever you need a feature this library doesn't
wrap — you keep the cached client, the credentials, the endpoint, and
the config.

```python
s3c = S3Client()
presigned = s3c.raw.generate_presigned_url(
    "get_object", Params={"Bucket": "b", "Key": "k"}, ExpiresIn=3600,
)
```

## Streaming and pagination

`s3.get_object` and `s3.list_keys` are generators. Bodies are streamed
in chunks; listings are paginated lazily.

```python
# Stream a large object straight to disk — never loaded fully into RAM.
with open("out.bin", "wb") as fh:
    for chunk in s3.get_object("b", "huge.bin"):
        fh.write(chunk)

# Walk millions of keys with bounded memory (one page at a time).
for key in s3.list_keys("b", prefix="logs/"):
    ...
```

The streaming generator closes the underlying `StreamingBody` on
normal completion, early `break`, and exceptions raised by the
consumer — no leaked urllib3 connections.

If you want a full `bytes` value:

```python
body = b"".join(s3.get_object("b", "small.json"))
```

## Dependency injection

All public functions and bound-client constructors accept the same
keyword-only arguments:

| Argument        | Type                          | Notes                                                             |
|-----------------|-------------------------------|-------------------------------------------------------------------|
| `region_name`   | `str \| None`                 | AWS region.                                                       |
| `profile_name`  | `str \| None`                 | Named profile from `~/.aws/credentials`.                          |
| `endpoint_url`  | `str \| None`                 | Custom endpoint (LocalStack, MinIO, VPC endpoints…). First-class. |
| `config`        | `botocore.config.Config`      | Timeouts/retries/etc. Bypasses the internal cache.                |
| `session`       | `boto3.Session`               | Pre-built session — used directly; bypasses the internal cache.   |

```python
import boto3
from botocore.config import Config

# LocalStack
s3.put_object("b", "k", b"v", endpoint_url="http://localhost:4566")

# Assumed-role session from STS, reused across calls
session = boto3.Session(...)
for k in s3.list_keys("b", session=session):
    ...

# Custom retry / timeout policy
tight = Config(connect_timeout=2, read_timeout=5,
               retries={"max_attempts": 2, "mode": "standard"})
body = b"".join(s3.get_object("b", "k", config=tight))
```

With none of `config` / `session`, clients are cached per
`(service, region_name, profile_name, endpoint_url)` behind a
`threading.Lock` — threads share a single client safely.

## Error model

Botocore errors are translated into a small typed hierarchy:

- `NotFoundError` — missing bucket / key / queue / secret.
- `AuthError` — credentials, signing, access-denied, `NoCredentialsError`.
- `ValidationError` — local parameter validation failures, including
  library-side checks (e.g. mutually exclusive delete options).
- `BotoLiteError` — base class; also catches `EndpointConnectionError`,
  `ReadTimeoutError`, and unmapped `ClientError`s.

```python
from boto_lite.exceptions import NotFoundError, AuthError, BotoLiteError

try:
    value = secrets.get("missing")
except NotFoundError:
    value = None
```

Streaming and listing errors surface on first iteration, not at the
`get_object(...)` / `list_keys(...)` call site — that's the cost of
lazy evaluation. Wrap the iterator, not the call.

## Scope and non-goals

**Covered today:**

- **S3**: `get_object` (streaming), `put_object`, `delete_object`,
  `list_keys` (paginated generator), `upload_stream` (multipart
  from an iterator or file-like object — single-part fast path when
  the data fits, multipart abort on failure), `presigned_url`
  (first-class helper for GET/PUT URLs).
- **SQS**: `send` (attrs, delay, FIFO group/dedup ids), `send_batch`
  (auto-chunks past the 10-entry limit, partial failures surfaced),
  `receive` (short or long poll), `delete`, `delete_batch`,
  `consume(queue_url, handler, stop=event)` — long-poll loop with
  delete-on-success, keep-on-exception, optional `on_error` callback,
  and graceful shutdown via `threading.Event`. Frozen `Message`
  dataclass.
- **Secrets Manager**: `get` (string or binary, with `version_id` /
  `version_stage`), `put` (create-or-update, string or binary),
  `delete` (`recovery_window_in_days` or
  `force_delete_without_recovery`). `SecretsClient(ttl=...)` offers
  an in-process TTL cache with `.invalidate(name=None)`.
- Cross-cutting: thread-safe cached clients, session/endpoint/profile
  injection, typed error translation.

**Explicit non-goals:**

- Wrapping every AWS API surface. If a feature isn't here, use `.raw`
  or raw `boto3`.
- Async. `boto-lite` is sync-only; use `aioboto3` if you need asyncio.
- Multi-cloud abstraction. This is an AWS facade.
- Retry policy innovation. We defer entirely to botocore's retry
  handling — override it via `config`.

## Performance

This library is a thin wrapper over `boto3`. On the critical path the
extra work is a dict lookup in the client cache and a translate-errors
context manager around the AWS call. You should not see measurable
throughput or latency differences versus a well-written raw-boto3
client that reuses its `boto3.client` instance.

What you should **not** do: construct `boto3.client(...)` on every
call. That rebuilds a session and walks botocore's loader — it's the
expensive thing, and it's exactly what `boto-lite`'s cache and
bound-client classes avoid.

Runtime micro-benchmarks against LocalStack live in
[`benchmark_runtime.py`](./benchmark_runtime.py). A separate
[`benchmark_tokens.py`](./benchmark_tokens.py) compares source length
between raw-boto3 and the facade (not a runtime metric; just for
readability comparisons).

## Testing

Unit tests run fully offline via `botocore.stub.Stubber`:

```bash
uv sync --group dev
uv run pytest
```

Integration tests hit a real **LocalStack** instance and exercise wire
traffic end-to-end. They're skipped cleanly when LocalStack isn't
reachable.

```bash
docker compose up -d localstack
uv run pytest tests/test_integration.py
```

CI runs the unit matrix on {ubuntu, windows, macos} × Python
{3.10, 3.11, 3.12, 3.13} and the LocalStack integration job on ubuntu.
See [`.github/workflows/test.yml`](./.github/workflows/test.yml).

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md).

## Security

See [SECURITY.md](./SECURITY.md) for how to report vulnerabilities.

## License

MIT.
