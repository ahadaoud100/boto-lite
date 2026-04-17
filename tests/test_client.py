from __future__ import annotations

import os

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import unittest
from unittest.mock import MagicMock, patch

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import (
    EndpointConnectionError,
    ParamValidationError,
    ReadTimeoutError,
)
from botocore.stub import Stubber

from boto_lite import _client as client_mod
from boto_lite import s3
from boto_lite._client import get_client, translate_errors
from boto_lite.exceptions import BotoLiteError, ValidationError


class GetClientInjectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_cache = dict(client_mod._client_cache)
        client_mod._client_cache.clear()

    def tearDown(self) -> None:
        client_mod._client_cache.clear()
        client_mod._client_cache.update(self._saved_cache)

    def test_default_call_caches_per_service_region_profile(self) -> None:
        a = get_client("s3")
        b = get_client("s3")
        self.assertIs(a, b)

    def test_distinct_region_produces_distinct_client(self) -> None:
        a = get_client("s3", region_name="us-east-1")
        b = get_client("s3", region_name="eu-west-1")
        self.assertIsNot(a, b)

    def test_custom_config_bypasses_cache(self) -> None:
        cfg = BotoConfig(connect_timeout=1, read_timeout=1, retries={"max_attempts": 1})
        fake_session = MagicMock()
        with patch.object(client_mod.boto3, "Session", return_value=fake_session):
            get_client("s3", config=cfg)
            get_client("s3", config=cfg)
        self.assertEqual(fake_session.client.call_count, 2)
        _, kwargs = fake_session.client.call_args
        self.assertIs(kwargs["config"], cfg)

    def test_profile_and_region_passed_to_session(self) -> None:
        fake_session = MagicMock()
        with patch.object(client_mod.boto3, "Session", return_value=fake_session) as mk:
            get_client("s3", region_name="ap-south-1", profile_name="prod")
        mk.assert_called_once_with(profile_name="prod", region_name="ap-south-1")
        fake_session.client.assert_called_once_with("s3")


class SessionInjectionTest(unittest.TestCase):
    """Verifies that an injected boto3.Session is used directly and bypasses
    both the module-level cache and the default Session constructor."""

    def setUp(self) -> None:
        self._saved_cache = dict(client_mod._client_cache)
        client_mod._client_cache.clear()

    def tearDown(self) -> None:
        client_mod._client_cache.clear()
        client_mod._client_cache.update(self._saved_cache)

    def test_injected_session_is_used_directly(self) -> None:
        fake_session = MagicMock(spec=boto3.Session)
        sentinel_client = object()
        fake_session.client.return_value = sentinel_client

        result = get_client("s3", session=fake_session)

        self.assertIs(result, sentinel_client)
        fake_session.client.assert_called_once_with("s3")

    def test_injected_session_bypasses_cache(self) -> None:
        fake_session = MagicMock(spec=boto3.Session)
        fake_session.client.return_value = object()

        get_client("s3", session=fake_session)
        get_client("s3", session=fake_session)

        # Two calls → two client() invocations, and nothing cached.
        self.assertEqual(fake_session.client.call_count, 2)
        self.assertEqual(client_mod._client_cache, {})

    def test_injected_session_does_not_invoke_default_session(self) -> None:
        fake_session = MagicMock(spec=boto3.Session)
        fake_session.client.return_value = object()

        with patch.object(client_mod.boto3, "Session") as default_session_ctor:
            get_client("s3", session=fake_session)

        default_session_ctor.assert_not_called()

    def test_injected_session_forwards_region_and_config(self) -> None:
        fake_session = MagicMock(spec=boto3.Session)
        fake_session.client.return_value = object()
        cfg = BotoConfig(retries={"max_attempts": 1})

        get_client("s3", session=fake_session, region_name="eu-west-2", config=cfg)

        fake_session.client.assert_called_once_with(
            "s3", region_name="eu-west-2", config=cfg
        )

    def test_facade_session_injection_end_to_end(self) -> None:
        """s3.put_object with an injected session should call through to
        that session's client, not the module cache."""
        real_client = boto3.client("s3", region_name="us-east-1")
        stubber = Stubber(real_client)
        stubber.add_response("put_object", {}, {"Bucket": "b", "Key": "k", "Body": b"x"})
        stubber.activate()
        self.addCleanup(stubber.deactivate)

        fake_session = MagicMock(spec=boto3.Session)
        fake_session.client.return_value = real_client

        s3.put_object("b", "k", b"x", session=fake_session)

        fake_session.client.assert_called_once_with("s3")
        stubber.assert_no_pending_responses()


class TranslateErrorsTest(unittest.TestCase):
    def test_endpoint_connection_error_wrapped(self) -> None:
        with self.assertRaises(BotoLiteError):
            with translate_errors():
                raise EndpointConnectionError(endpoint_url="https://example.invalid")

    def test_read_timeout_error_wrapped(self) -> None:
        with self.assertRaises(BotoLiteError):
            with translate_errors():
                raise ReadTimeoutError(endpoint_url="https://example.invalid")

    def test_param_validation_error_wrapped(self) -> None:
        with self.assertRaises(ValidationError):
            with translate_errors():
                raise ParamValidationError(report="missing required Bucket")


if __name__ == "__main__":
    unittest.main()
