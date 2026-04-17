# Contributing to boto-lite

Thanks for wanting to help. This is a small library with a
deliberately narrow scope — please read this file before opening a PR.

## Ground rules

- **Python 3.10+** only.
- **Zero runtime dependencies** beyond `boto3`. Dev-only dependencies
  (pytest, tiktoken, etc.) go in `[dependency-groups].dev` in
  `pyproject.toml`, never in `[project].dependencies`.
- **Flat, typed public API.** If a new surface doesn't fit on one line
  of a module, reconsider the shape.
- **No async.** Use raw `aioboto3` if you need that.

## Development setup

```bash
uv sync --group dev
uv run pytest
```

LocalStack integration tests (skipped by default):

```bash
docker compose up -d localstack
uv run pytest tests/test_integration.py
docker compose down -v
```

## What belongs in this library

- Everyday S3 / SQS / Secrets Manager operations used from scripts,
  Lambdas, and small services.
- Improvements to error translation, streaming, pagination, or the
  DI surface (`region_name`, `profile_name`, `config`, `endpoint_url`,
  `session`).
- Bug fixes and documentation.

## What does not belong

- New AWS services. Keep the scope to S3, SQS, and Secrets Manager.
- Wrapping the full surface of any one service. The `raw` escape
  hatch on the bound clients is the correct answer for
  seldom-used parameters.
- Dependencies beyond `boto3`.
- Framework coupling (CLIs, web frameworks, logging setups).

## Pull request checklist

- [ ] `uv run pytest` passes (56+ tests, integration tests skipped).
- [ ] New functions are typed and documented with a short docstring.
- [ ] Errors are translated through `translate_errors` or raise
      exceptions from `boto_lite.exceptions`.
- [ ] Changes to the public API appear in `CHANGELOG.md` under
      `## Unreleased`.
- [ ] New operations or parameters have a unit test using
      `botocore.stub.Stubber` and, when wire behavior matters, a
      LocalStack integration test.

## Commit and PR style

- Small, focused commits. Keep diffs minimal.
- PR title: imperative mood, under ~70 characters
  (e.g., "Add `S3Client.head_object`").
- PR description: what changed, why, any tradeoffs or open questions.

## Releases

Releases are cut by the maintainer. Do not open PRs that bump the
version or edit `CHANGELOG.md`'s `## Unreleased` heading into a
versioned one.
