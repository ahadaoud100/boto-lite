# Changelog

All notable changes to `boto-lite` are documented here. This project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

## [0.4.0] — 2026-04-18

### Added
- `s3.upload_stream(bucket, key, data, *, part_size=8*1024*1024,
  content_type=None)` and `S3Client.upload_stream` — upload an
  iterable of `bytes` or a file-like object to S3 using multipart
  under the hood. Content that fits in a single part falls back to
  `PutObject`; multipart uploads abort on the way out if any part
  fails, so orphaned parts are not left billable. Re-chunks
  irregular input into exactly `part_size` parts (5 MiB minimum).
- `s3.presigned_url(bucket, key, *, operation="get_object",
  expires_in=3600, extra_params=None)` and
  `S3Client.presigned_url` — first-class presigned URL helper for
  `get_object` and `put_object` (no more `.raw.generate_presigned_url`
  ceremony).
- `sqs.send_batch(queue_url, bodies)` and
  `SQSClient.send_batch` — arbitrary-length sends, automatically
  chunked into the SQS 10-entry batch limit. Returns a
  `SendBatchResult` with per-input `message_ids` (or `None` on
  failure) and a `failures` list of `BatchFailure(index, code,
  message, sender_fault)`.
- `sqs.delete_batch(queue_url, receipt_handles)` and
  `SQSClient.delete_batch` with the same chunking and failure
  surfacing via `DeleteBatchResult`.
- `sqs.consume(queue_url, handler, *, stop, ...)` and
  `SQSClient.consume` — long-poll consumer loop with
  delete-on-success, keep-on-exception (re-delivered after the
  visibility timeout), optional `on_error(msg, exc)` callback, and
  `threading.Event`-based graceful shutdown.
- `SecretsClient(ttl=...)` — in-process TTL cache for `get` calls,
  keyed on `(name, version_id, version_stage)`. Thread-safe
  (`threading.Lock`). `.invalidate(name=None)` clears specific or all
  entries.
- New public exports: `Message`, `BatchFailure`, `SendBatchResult`,
  `DeleteBatchResult`.

### Fixed
- CI `LocalStack integration` job: pin `docker-compose.yml` to
  `localstack/localstack:3` (community stable). The floating
  `latest` tag had started resolving to a Pro dev build that
  required license activation and exited with code 55.

## [0.3.1] — 2026-04-18

### Fixed
- `release.yml`: run `twine check` via `uvx` instead of
  `uv pip install --system twine`. The previous approach failed on the
  GitHub runner's PEP 668 externally-managed system Python, which
  blocked the 0.3.0 tag from publishing. No library changes — 0.3.1
  is 0.3.0's code with a fixed release pipeline.

## [0.3.0] — 2026-04-18

### Added
- `S3Client`, `SQSClient`, `SecretsClient` bound service classes that
  construct their underlying `boto3.client` once per instance and
  reuse it for every method.
- `.raw` property on every bound client, exposing the underlying
  `boto3.client` as a deliberate escape hatch.
- First-class `endpoint_url` keyword argument on `get_client`, all
  module-level facade functions, and all bound-client constructors.
  Participates in the client-cache key.
- `sqs.send` / `SQSClient.send` now accept `message_attributes`,
  `message_group_id`, `message_deduplication_id`, and `delay_seconds`.
- `secrets.get` / `SecretsClient.get` accept `version_id` and
  `version_stage`.
- `S3StreamCleanupTest` covering `StreamingBody` cleanup on full
  consumption, early `break`, and consumer exceptions.
- New `tests/test_bound_clients.py` suite.
- LocalStack integration job in the `test` GitHub Actions workflow.
- `release` workflow now runs `pytest` and a packaging sanity check
  before building and publishing.
- `CONTRIBUTING.md`, `SECURITY.md`, and this `CHANGELOG.md`.

### Changed
- `s3.get_object` / `S3Client.get_object` now deterministically close
  the underlying `StreamingBody` via a generator `try/finally` —
  avoids leaked urllib3 connections on early exit or exception.
- `secrets.delete` raises `ValidationError` (not stdlib `ValueError`)
  when `recovery_window_in_days` and `force_delete_without_recovery`
  are passed together. Normalises library-side validation into the
  published error hierarchy.
- README rewritten around real-user personas, scope/non-goals, bound
  clients, and the `.raw` escape hatch. Runtime-performance framing is
  now honest (thin wrapper; no measurable difference from a
  well-written raw-boto3 client). Token savings are documented as a
  source-readability comparison, not a runtime claim.
- `STATE.md` slimmed to a maintainer-focused status page.

## [0.2.0] — 2026-04-18

### Added
- Keyword-only `region_name`, `profile_name`, `config`, `session`
  dependency-injection arguments on every public facade function.
- `boto_lite.exceptions.ValidationError` mapping for
  `ParamValidationError`.
- `s3.get_object` is now a generator over
  `StreamingBody.iter_chunks()`.
- `s3.list_keys` is now a generator that drives the
  `list_objects_v2` paginator lazily.
- `secrets.get` handles `SecretBinary` (returns `bytes`).
- `secrets.put` accepts `str` or `bytes`.
- `secrets.delete` replaces `force: bool` with explicit
  `recovery_window_in_days` / `force_delete_without_recovery`.
- LocalStack integration tests via
  `docker-compose.yml` + `tests/test_integration.py`.
- `translate_errors` covers `EndpointConnectionError`,
  `ReadTimeoutError`, and `ParamValidationError`.

### Changed
- Replaced `@lru_cache` on `get_client` with a
  `threading.Lock`-guarded dict cache keyed by
  `(service, region_name, profile_name)`. Eliminates first-touch race
  and forced global default session.
- `sqs.receive` docstring now correctly documents `wait_seconds=0`
  (short poll) vs `1..20` (long poll).

## [0.1.0] — 2026-04-17

### Added
- Initial release: flat `s3` / `sqs` / `secrets` module API, typed
  `BotoLiteError` hierarchy (`NotFoundError`, `AuthError`),
  `botocore.stub.Stubber`-backed unit tests, and GitHub Actions for
  test matrix + Trusted Publishing to PyPI.
