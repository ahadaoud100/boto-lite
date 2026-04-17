"""Runtime micro-benchmark against LocalStack.

Compares three call styles for each of three representative tasks:

1. ``facade``        — module-level functions (warm cached client).
2. ``bound``         — ``S3Client`` / ``SQSClient`` / ``SecretsClient``
                       (one client built in the constructor, reused).
3. ``raw_reused``    — a single ``boto3.client(...)`` built once and
                       reused across every iteration. This is what a
                       well-written raw-boto3 program looks like, and
                       is the relevant baseline.

Skips gracefully when LocalStack isn't reachable.

Run:
    docker compose up -d localstack
    uv run --group dev python benchmark_runtime.py

Reports median and p95 per operation in milliseconds. This is a
micro-benchmark — LocalStack latency dominates, so numbers here
illustrate the overhead of the facade relative to raw boto3, not
absolute production latency.
"""

from __future__ import annotations

import os
import socket
import statistics
import sys
import time
import uuid
from contextlib import contextmanager
from typing import Callable, Iterator
from urllib.parse import urlparse

os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import boto3

from boto_lite import (
    S3Client,
    SQSClient,
    SecretsClient,
    s3,
    secrets,
    sqs,
)
from boto_lite import _client as client_mod

LOCALSTACK_URL = os.environ.get("LOCALSTACK_URL", "http://localhost:4566")
ITERS = int(os.environ.get("BENCH_ITERS", "30"))
WARMUP = 3


def _reachable(url: str, timeout: float = 0.5) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _time(fn: Callable[[], None], iters: int) -> tuple[float, float]:
    for _ in range(WARMUP):
        fn()
    samples: list[float] = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    samples.sort()
    median = statistics.median(samples)
    # Nearest-rank p95.
    p95 = samples[min(len(samples) - 1, int(round(0.95 * len(samples))) - 1)]
    return median, p95


@contextmanager
def _localstack_env() -> Iterator[None]:
    prev = os.environ.get("AWS_ENDPOINT_URL")
    os.environ["AWS_ENDPOINT_URL"] = LOCALSTACK_URL
    client_mod._client_cache.clear()
    try:
        yield
    finally:
        client_mod._client_cache.clear()
        if prev is None:
            os.environ.pop("AWS_ENDPOINT_URL", None)
        else:
            os.environ["AWS_ENDPOINT_URL"] = prev


def bench_s3(admin_s3, session) -> list[tuple[str, str, float, float]]:
    bucket = f"bench-{uuid.uuid4().hex[:10]}"
    admin_s3.create_bucket(Bucket=bucket)
    payload = b"x" * 1024

    try:
        s3_bound = S3Client(session=session, endpoint_url=LOCALSTACK_URL)
        raw = boto3.client("s3", endpoint_url=LOCALSTACK_URL)

        def facade_put() -> None:
            s3.put_object(bucket, "k", payload)

        def bound_put() -> None:
            s3_bound.put_object(bucket, "k", payload)

        def raw_put() -> None:
            raw.put_object(Bucket=bucket, Key="k", Body=payload)

        def facade_get() -> None:
            b"".join(s3.get_object(bucket, "k"))

        def bound_get() -> None:
            b"".join(s3_bound.get_object(bucket, "k"))

        def raw_get() -> None:
            raw.get_object(Bucket=bucket, Key="k")["Body"].read()

        results: list[tuple[str, str, float, float]] = []
        for op, variants in [
            ("s3.put_object", [("facade", facade_put), ("bound", bound_put), ("raw_reused", raw_put)]),
            ("s3.get_object", [("facade", facade_get), ("bound", bound_get), ("raw_reused", raw_get)]),
        ]:
            for style, fn in variants:
                med, p95 = _time(fn, ITERS)
                results.append((op, style, med, p95))
        return results
    finally:
        try:
            for obj in admin_s3.list_objects_v2(Bucket=bucket).get("Contents", []):
                admin_s3.delete_object(Bucket=bucket, Key=obj["Key"])
            admin_s3.delete_bucket(Bucket=bucket)
        except Exception:
            pass


def bench_sqs(admin_sqs, session) -> list[tuple[str, str, float, float]]:
    qname = f"bench-{uuid.uuid4().hex[:10]}"
    qurl = admin_sqs.create_queue(QueueName=qname)["QueueUrl"]

    try:
        sqs_bound = SQSClient(session=session, endpoint_url=LOCALSTACK_URL)
        raw = boto3.client("sqs", endpoint_url=LOCALSTACK_URL)

        def facade_send() -> None:
            sqs.send(qurl, "payload")

        def bound_send() -> None:
            sqs_bound.send(qurl, "payload")

        def raw_send() -> None:
            raw.send_message(QueueUrl=qurl, MessageBody="payload")

        results: list[tuple[str, str, float, float]] = []
        for style, fn in [("facade", facade_send), ("bound", bound_send), ("raw_reused", raw_send)]:
            med, p95 = _time(fn, ITERS)
            results.append(("sqs.send", style, med, p95))
        return results
    finally:
        try:
            admin_sqs.delete_queue(QueueUrl=qurl)
        except Exception:
            pass


def bench_secrets(admin_sec, session) -> list[tuple[str, str, float, float]]:
    name = f"bench-{uuid.uuid4().hex[:10]}"
    admin_sec.create_secret(Name=name, SecretString="v")

    try:
        sec_bound = SecretsClient(session=session, endpoint_url=LOCALSTACK_URL)
        raw = boto3.client("secretsmanager", endpoint_url=LOCALSTACK_URL)

        def facade_get() -> None:
            secrets.get(name)

        def bound_get() -> None:
            sec_bound.get(name)

        def raw_get() -> None:
            raw.get_secret_value(SecretId=name)

        results: list[tuple[str, str, float, float]] = []
        for style, fn in [("facade", facade_get), ("bound", bound_get), ("raw_reused", raw_get)]:
            med, p95 = _time(fn, ITERS)
            results.append(("secrets.get", style, med, p95))
        return results
    finally:
        try:
            admin_sec.delete_secret(SecretId=name, ForceDeleteWithoutRecovery=True)
        except Exception:
            pass


def main() -> int:
    if not _reachable(LOCALSTACK_URL):
        print(
            f"LocalStack not reachable at {LOCALSTACK_URL}. "
            "Run `docker compose up -d localstack` first.",
            file=sys.stderr,
        )
        return 0  # exit 0 so the benchmark skips gracefully

    session = boto3.Session(region_name="us-east-1")
    admin_s3 = session.client("s3", endpoint_url=LOCALSTACK_URL)
    admin_sqs = session.client("sqs", endpoint_url=LOCALSTACK_URL)
    admin_sec = session.client("secretsmanager", endpoint_url=LOCALSTACK_URL)

    with _localstack_env():
        rows: list[tuple[str, str, float, float]] = []
        rows.extend(bench_s3(admin_s3, session))
        rows.extend(bench_sqs(admin_sqs, session))
        rows.extend(bench_secrets(admin_sec, session))

    print(f"\nRuntime micro-benchmark vs LocalStack ({LOCALSTACK_URL})")
    print(f"iterations per variant: {ITERS} (+ {WARMUP} warmup)\n")
    header = f"{'operation':<16}{'style':<14}{'median_ms':>12}{'p95_ms':>12}"
    print(header)
    print("-" * len(header))
    for op, style, med, p95 in rows:
        print(f"{op:<16}{style:<14}{med:>12.2f}{p95:>12.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
