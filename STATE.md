# STATE

_Last updated: 2026-04-17_

Slim maintainer status page. User-facing docs live in `README.md`,
`CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`.

## Version

- Published: **v0.2.0** on PyPI (2026-04-18).
- Working tree: unreleased changes pending on `main`. See
  `CHANGELOG.md` → `## Unreleased` for the candidate notes for the
  next minor (v0.3.0).

## Tests

- `uv run pytest` → 56 passed, 2 skipped (LocalStack integration,
  skipped when LocalStack is not reachable).
- CI: `.github/workflows/test.yml` runs the unit matrix on
  {ubuntu, windows, macos} × Python {3.10, 3.11, 3.12, 3.13} and a
  dedicated LocalStack integration job on ubuntu.

## Release

- `.github/workflows/release.yml` runs `pytest` and a packaging
  sanity check (`twine check` + smoke-import from the built wheel)
  before publishing to PyPI via Trusted Publishing (OIDC, `pypi`
  environment).
- Cutting a release: bump `pyproject.toml` version, promote the
  `## Unreleased` heading in `CHANGELOG.md`, commit, tag `vX.Y.Z`,
  push the tag. CI does the rest.

## Outstanding

- Presigned URLs, multipart upload, copy/head, batch SQS operations,
  visibility timeout changes — intentionally not wrapped. Users reach
  through `S3Client.raw` / `SQSClient.raw`.
- Runtime benchmarks (`benchmark_runtime.py`) skip gracefully when
  LocalStack is not running. Numbers are captured locally and live in
  the PR description, not in the repo.
