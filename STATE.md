# STATE

_Last updated: 2026-04-17_

## Status
**Build phase complete. Package renamed to `boto-lite`.**
Facade, tests, docs, token benchmark, PyPI metadata, and CI/release workflows
are all in place. Awaiting the literal user message `RELEASE` before anything
is published to GitHub or PyPI.

## What works
- Distribution name: **`boto-lite`** (PEP 503-normalized; installable as
  `pip install boto-lite`). Import name: **`boto_lite`** (folder at
  `src/boto_lite/`).
- Runtime still ships with `boto3>=1.42.89` as the sole runtime dependency.
- `tiktoken>=0.7.0` in `[dependency-groups].dev` **only** — not a runtime dep.
  (CLAUDE.md's "ZERO dependencies other than boto3" rule was explicitly relaxed
  by the user for the dev group on 2026-04-17 so the token benchmark could run.)
- Package layout under `src/boto_lite/`:
  - `__init__.py` — flat public API re-exports (`s3`, `sqs`, `secrets`, `SSAError`).
  - `_client.py` — cached `boto3.client` helper + `translate_errors` mapping
    `ClientError`/`NoCredentialsError` to `NotFoundError`, `AuthError`, or `SSAError`.
  - `s3.py` — `get_object`, `put_object`, `delete_object`, `list_keys` (paginated).
  - `sqs.py` — `send`, `receive` (long-poll), `delete`, frozen `Message` dataclass.
  - `secrets.py` — `get` (string-only), `put` (create-or-update), `delete` (with `force`).
  - `exceptions.py` — `SSAError`, `NotFoundError`, `AuthError`.
- **Public exception class is still `SSAError`.** The rename refactor scoped
  only the module path, not the class name. If we want `BotoLiteError` (or
  an alias), that's a separate, explicit API decision.
- Tests: 15/15 pass via `uv run python -m unittest discover -s tests` after the
  rename. All test imports now read `from boto_lite...`.
- `benchmark_tokens.py` still prints: raw boto3 **186** tokens → `boto_lite`
  **61** tokens (−125 / −67.2%). Token count is identical to the pre-rename
  run because the facade script in the benchmark changed from
  `from ssa import s3, SSAError` to `from boto_lite import s3, SSAError` —
  same token count under cl100k_base.
- `pyproject.toml` finalized: `name = "boto-lite"`, description, MIT license,
  authors/maintainers, keywords, PyPI classifiers (Python 3.10–3.13, Beta,
  Typed, OSS tags), project URLs (Homepage/Repository/Issues pointing at
  `github.com/ahadaoud100/boto-lite`).
- `README.md` rewritten around the `boto-lite` / `boto_lite` names; install
  snippet, usage per service, error model, scope, benchmark table.
- CI: `.github/workflows/test.yml` — unittest matrix on
  {ubuntu, windows, macos} × Python {3.10, 3.11, 3.12, 3.13}.
- Release: `.github/workflows/release.yml` — builds sdist+wheel on `v*` tag
  push, publishes to PyPI via **Trusted Publishing** (OIDC, `id-token: write`,
  GitHub `pypi` environment, `url: https://pypi.org/p/boto-lite`).

## What is broken / not yet done
- No integration tests against a real or LocalStack backend.
- Binary secrets (`SecretBinary`) intentionally unsupported.
- S3 facade does not yet cover: presigned URLs, multipart upload, copy, head.
- SQS facade does not yet cover: batch send/delete, visibility timeout changes,
  FIFO-specific params (group id, dedup id).
- PyPI project `boto-lite` must be pre-registered with Trusted Publishing
  configured against this repo + the `pypi` environment before `release.yml`
  can succeed.
- Repo has **not** been pushed to GitHub — release is blocked on the literal
  user message `RELEASE`.
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
12. **Release** — blocked on the exact user message `RELEASE`.
13. Extended surface (if needed) — presigned URLs, batch SQS, binary secrets.
14. Consider renaming `SSAError` → `BotoLiteError` or adding an alias (deferred).

## Exact next step
Stop and wait for the user. Do **not** push to GitHub, tag, or publish until
the user types the literal message `RELEASE`.
