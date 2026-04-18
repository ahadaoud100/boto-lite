"""Tests for the in-process TTL cache on ``SecretsClient``."""

from __future__ import annotations

import os

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import unittest
from unittest.mock import MagicMock, patch

import boto3

from boto_lite import SecretsClient
from boto_lite.exceptions import ValidationError

_ARN = "arn:aws:secretsmanager:us-east-1:000000000000:secret:foo-AbCdEf"


def _make_client() -> tuple[SecretsClient, MagicMock]:
    raw = MagicMock()
    session = MagicMock(spec=boto3.Session)
    session.client.return_value = raw
    client = SecretsClient(session=session, ttl=300.0)
    return client, raw


class TtlCacheTest(unittest.TestCase):
    def test_rejects_non_positive_ttl(self) -> None:
        session = MagicMock(spec=boto3.Session)
        session.client.return_value = object()
        with self.assertRaises(ValidationError):
            SecretsClient(session=session, ttl=0)
        with self.assertRaises(ValidationError):
            SecretsClient(session=session, ttl=-1)

    def test_hit_within_ttl_does_not_call_aws(self) -> None:
        client, raw = _make_client()
        raw.get_secret_value.return_value = {
            "ARN": _ARN, "Name": "foo", "SecretString": "v1",
        }
        self.assertEqual(client.get("foo"), "v1")
        self.assertEqual(client.get("foo"), "v1")
        self.assertEqual(raw.get_secret_value.call_count, 1)

    def test_miss_after_expiry_refetches(self) -> None:
        client, raw = _make_client()
        raw.get_secret_value.side_effect = [
            {"ARN": _ARN, "Name": "foo", "SecretString": "v1"},
            {"ARN": _ARN, "Name": "foo", "SecretString": "v2"},
        ]
        with patch("boto_lite.secrets.time.monotonic") as now:
            now.return_value = 1_000.0
            self.assertEqual(client.get("foo"), "v1")
            now.return_value = 1_000.0 + 301.0  # past the 300s TTL
            self.assertEqual(client.get("foo"), "v2")
        self.assertEqual(raw.get_secret_value.call_count, 2)

    def test_cache_keyed_by_version(self) -> None:
        client, raw = _make_client()
        raw.get_secret_value.side_effect = [
            {"ARN": _ARN, "Name": "foo", "SecretString": "current"},
            {"ARN": _ARN, "Name": "foo", "SecretString": "previous"},
        ]
        self.assertEqual(client.get("foo"), "current")
        self.assertEqual(
            client.get("foo", version_stage="AWSPREVIOUS"), "previous"
        )
        self.assertEqual(raw.get_secret_value.call_count, 2)
        # Both entries are cached — repeat calls do not hit AWS.
        self.assertEqual(client.get("foo"), "current")
        self.assertEqual(
            client.get("foo", version_stage="AWSPREVIOUS"), "previous"
        )
        self.assertEqual(raw.get_secret_value.call_count, 2)

    def test_invalidate_by_name_drops_all_versions(self) -> None:
        client, raw = _make_client()
        raw.get_secret_value.side_effect = [
            {"ARN": _ARN, "Name": "foo", "SecretString": "cur"},
            {"ARN": _ARN, "Name": "foo", "SecretString": "prev"},
            {"ARN": _ARN, "Name": "foo", "SecretString": "cur2"},
            {"ARN": _ARN, "Name": "foo", "SecretString": "prev2"},
        ]
        client.get("foo")
        client.get("foo", version_stage="AWSPREVIOUS")
        client.invalidate("foo")
        client.get("foo")
        client.get("foo", version_stage="AWSPREVIOUS")
        self.assertEqual(raw.get_secret_value.call_count, 4)

    def test_invalidate_all_clears_everything(self) -> None:
        client, raw = _make_client()
        raw.get_secret_value.side_effect = [
            {"ARN": _ARN, "Name": "a", "SecretString": "A"},
            {"ARN": _ARN, "Name": "b", "SecretString": "B"},
            {"ARN": _ARN, "Name": "a", "SecretString": "A2"},
            {"ARN": _ARN, "Name": "b", "SecretString": "B2"},
        ]
        client.get("a")
        client.get("b")
        client.invalidate()
        client.get("a")
        client.get("b")
        self.assertEqual(raw.get_secret_value.call_count, 4)

    def test_jitter_validation_rejects_out_of_range(self) -> None:
        session = MagicMock(spec=boto3.Session)
        session.client.return_value = object()
        with self.assertRaises(ValidationError):
            SecretsClient(session=session, ttl=300, jitter=-0.01)
        with self.assertRaises(ValidationError):
            SecretsClient(session=session, ttl=300, jitter=1.0)

    def test_jitter_applied_to_stored_expiry(self) -> None:
        raw = MagicMock()
        session = MagicMock(spec=boto3.Session)
        session.client.return_value = raw
        client = SecretsClient(session=session, ttl=300.0, jitter=0.1)
        raw.get_secret_value.return_value = {
            "ARN": _ARN, "Name": "foo", "SecretString": "v",
        }
        with patch("boto_lite.secrets.random.uniform") as uniform, \
             patch("boto_lite.secrets.time.monotonic") as now:
            # First monotonic() call sites: cache lookup (miss) and
            # post-fetch expiry computation. Return 1000 for both.
            now.return_value = 1_000.0
            uniform.return_value = 0.8  # 20% early
            client.get("foo")
            uniform.assert_called_once_with(0.9, 1.0)
        # Expiry = 1000 + 300 * 0.8 = 1240
        _, expiry = client._cache[("foo", None, None)]
        self.assertEqual(expiry, 1_000.0 + 300.0 * 0.8)

    def test_jitter_zero_gives_exact_ttl(self) -> None:
        raw = MagicMock()
        session = MagicMock(spec=boto3.Session)
        session.client.return_value = raw
        client = SecretsClient(session=session, ttl=300.0, jitter=0.0)
        raw.get_secret_value.return_value = {
            "ARN": _ARN, "Name": "foo", "SecretString": "v",
        }
        with patch("boto_lite.secrets.time.monotonic") as now:
            now.return_value = 1_000.0
            client.get("foo")
        _, expiry = client._cache[("foo", None, None)]
        self.assertEqual(expiry, 1_300.0)

    def test_no_ttl_means_no_caching(self) -> None:
        raw = MagicMock()
        session = MagicMock(spec=boto3.Session)
        session.client.return_value = raw
        client = SecretsClient(session=session)  # no ttl
        raw.get_secret_value.return_value = {
            "ARN": _ARN, "Name": "foo", "SecretString": "v",
        }
        client.get("foo")
        client.get("foo")
        self.assertEqual(raw.get_secret_value.call_count, 2)
        # invalidate() is a no-op when caching is off — must not raise.
        client.invalidate("foo")
        client.invalidate()


if __name__ == "__main__":
    unittest.main()
