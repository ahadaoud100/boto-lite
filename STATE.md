# STATE

_Last updated: 2026-04-17_

## Status
**Published to PyPI as `boto-lite` v0.1.0. Repo is public on GitHub.**
Red Team architectural audit is **APPROVED and fully landed** across two
fix passes plus a documentation / commit wrap-up pass. `uv run pytest` →
32 passed, 2 skipped (the 2 are the LocalStack integration tests, which
skip cleanly when Docker/LocalStack is not running). No version bump /
re-release yet — next release still requires the literal user message
`RELEASE`.

## What works
- Distribution name: **`boto-lite`** (PEP 503-normalized; installable as
  `pip install boto-lite`). Import name: **`boto_lite`** (folder at
  `src/boto_lite/`). Published to PyPI at v0.1.0.
- Public GitHub repo at `github.com/ahadaoud100/boto-lite`.
- Runtime still ships with `boto3>=1.42.89` as the sole runtime
  dependency.
- `tiktoken>=0.7.0` and `pytest>=8.0` in `[dependency-groups].dev` **only**
  — not runtime deps. (CLAUDE.md's "ZERO dependencies other than boto3"
  rule was relaxed by the user for the dev group on 2026-04-17 so the
  token benchmark and a venv-local pytest could run.)
- Package layout under `src/boto_lite/`:
  - `__init__.py` — flat public API re-exports (`s3`, `sqs`, `secrets`,
    `BotoLiteError`, `NotFoundError`, `AuthError`, `ValidationError`).
  - `_client.py` — `get_client` factory with lock-guarded
    `(service, region_name, profile_name)` cache; custom `config` or an
    injected `session` bypass the cache. `translate_errors` maps
    `ClientError` / `NoCredentialsError` / `EndpointConnectionError` /
    `ReadTimeoutError` / `ParamValidationError` onto the typed hierarchy.
  - `s3.py` — `get_object` (streaming generator over
    `StreamingBody.iter_chunks()`), `put_object`, `delete_object`,
    `list_keys` (generator over the `list_objects_v2` paginator).
  - `sqs.py` — `send`, `receive` (short or long poll, correctly
    documented), `delete`, frozen `Message` dataclass.
  - `secrets.py` — `get` (returns `str` or `bytes` per
    `SecretString`/`SecretBinary`), `put` (accepts `str` or `bytes`),
    `delete` (explicit `recovery_window_in_days` vs
    `force_delete_without_recovery`, mutually exclusive).
  - `exceptions.py` — `BotoLiteError`, `NotFoundError`, `AuthError`,
    `ValidationError`.
- **Every public function** in `s3`, `sqs`, `secrets` accepts keyword-only
  `region_name`, `profile_name`, `config` (`botocore.config.Config`),
  and `session` (`boto3.Session`) DI arguments.
- Tests:
  - `tests/test_s3.py`, `tests/test_sqs.py`, `tests/test_secrets.py`,
    `tests/test_client.py` — offline unit tests via `botocore.stub.Stubber`
    and `unittest.mock.patch`.
  - `tests/test_integration.py` — real LocalStack wire traffic via
    injected `boto3.Session` + `AWS_ENDPOINT_URL`. Skips cleanly when
    LocalStack isn't reachable.
  - Full run: 32 passed, 2 skipped.
- `docker-compose.yml` at project root defines a `localstack/localstack`
  service on port 4566 with `s3,sqs,secretsmanager` + healthcheck.
- `benchmark_tokens.py` prints the facade-vs-raw-boto3 token delta.
- `pyproject.toml` finalized: `name = "boto-lite"`, MIT license,
  classifiers, project URLs, `[tool.pytest.ini_options]`
  `testpaths = ["tests"]`.
- `README.md` rewritten around streaming generators, DI capabilities,
  error model, and integration testing flow.
- CI: `.github/workflows/test.yml` — unittest/pytest matrix on
  {ubuntu, windows, macos} × Python {3.10, 3.11, 3.12, 3.13}.
- Release: `.github/workflows/release.yml` — builds sdist+wheel on `v*`
  tag push, publishes to PyPI via Trusted Publishing (OIDC,
  `id-token: write`, GitHub `pypi` environment,
  `url: https://pypi.org/p/boto-lite`). Used successfully for v0.1.0.

## Architectural hardening summary

### Audit fix pass 1 (`audit_fix.txt`)
- Removed `@lru_cache` on `get_client`; replaced with a
  `threading.Lock`-guarded dict cache keyed by
  `(service, region_name, profile_name)` — eliminates the first-touch
  race and the forced global default session.
- Threaded keyword-only `region_name`, `profile_name`, `config` through
  every public facade function.
- Expanded the `translate_errors` net to cover
  `EndpointConnectionError`, `ReadTimeoutError` (→ `BotoLiteError`) and
  `ParamValidationError` (→ new `ValidationError`).
- `secrets.get` handles `SecretBinary` (returns `bytes`) as well as
  `SecretString`; `secrets.put` accepts either; `secrets.delete` replaces
  the vague `force: bool` with explicit, AWS-named
  `recovery_window_in_days` and `force_delete_without_recovery`.
- `sqs.receive` docstring now correctly documents `wait_seconds=0` as
  short polling vs `1..20` as long polling.
- Added `pytest>=8.0` to `[dependency-groups].dev` with a
  `[tool.pytest.ini_options]` stanza so `uv run pytest` resolves to the
  venv's pytest rather than a global shadow.

### Audit fix pass 2 (`audit_fix_2.txt`)
- **S3 streaming (real code, not docstring warnings):** `s3.get_object`
  is now a generator yielding chunks from `StreamingBody.iter_chunks()`.
  `s3.list_keys` is a generator that `yield`s keys from the
  `list_objects_v2` paginator. Neither materializes unbounded response
  data. Lazy error surfacing: botocore exceptions translated through
  `translate_errors` emerge on the first `next()`.
- **Session injection:** `get_client` and every facade function accept
  `session: boto3.Session | None`. When provided, the session is used
  directly and the module cache is bypassed entirely;
  `boto3.Session(...)` is never invoked. `region_name` and `config` still
  forward to `session.client()`; `profile_name` is ignored because the
  session carries its own profile.
- **LocalStack integration (real wire traffic, no mocks):**
  `docker-compose.yml` at project root, `tests/test_integration.py`
  driving real S3 put/list/stream-get/delete and real SQS
  send/long-poll-receive/delete through the facade via an injected
  session and `AWS_ENDPOINT_URL=http://localhost:4566`.

### Wrap-up pass (`audit_fix.txt`, approval revision)
- `README.md` rewritten: removed the "narrow" / "lacking configuration"
  framing, added a dedicated **Streaming & pagination** section, a
  **Dependency injection** table + examples (`region_name`,
  `profile_name`, `config`, `session`), and a **Tests** section covering
  the LocalStack flow.
- `STATE.md` brought in sync with the landed architecture.
- Single comprehensive git commit recording concurrency, S3 streaming,
  session injection, LocalStack integration, and the doc refresh.

## What is broken / not yet done
- S3 facade does not yet cover: presigned URLs, multipart upload, copy,
  head.
- SQS facade does not yet cover: batch send/delete, visibility timeout
  changes, FIFO-specific params (group id, dedup id).
- CI (`.github/workflows/test.yml`) does not currently spin up LocalStack,
  so integration tests only run when the user brings the compose service
  up locally. Wiring LocalStack into the GH Actions matrix is a
  follow-up.
- Repo folder is still `E:/projects/SSA` on disk (cosmetic; not touched).

## Roadmap
1. ~~Dependencies & tooling~~ ✅
2. ~~Client layer with error translation~~ ✅
3. ~~Secrets Manager facade~~ ✅
4. ~~S3 facade~~ ✅
5. ~~SQS facade~~ ✅
6. ~~Unit tests via Stubber~~ ✅
7. ~~README~~ ✅
8. ~~Token benchmark (`benchmark_tokens.py` + README table)~~ ✅
9. ~~PyPI metadata finalized~~ ✅
10. ~~GitHub Actions: `test.yml` + `release.yml` (Trusted Publishing)~~ ✅
11. ~~Rename package `ssa` → `boto-lite` (dist) / `boto_lite` (import)~~ ✅
12. ~~Rename exception `SSAError` → `BotoLiteError`~~ ✅
13. ~~Initial release to PyPI (v0.1.0) + public GitHub~~ ✅
14. ~~Red Team audit fix pass 1 (`audit_fix.txt` Phases 1–5)~~ ✅
15. ~~Red Team audit fix pass 2 (`audit_fix_2.txt`: S3 streaming,
    session injection, LocalStack integration)~~ ✅
16. ~~Doc + commit wrap-up (approval revision of `audit_fix.txt`)~~ ✅
17. Next release — blocked on the literal user message `RELEASE`.
18. Extended surface (if needed) — presigned URLs, batch SQS, etc.
19. Wire LocalStack into CI so integration tests run on every PR
    (deferred).

## Exact next step
Stop. The refactor is committed locally. Do **not** bump the version,
tag, or publish until the user types the literal message `RELEASE`.
