from __future__ import annotations

import os

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import unittest

from botocore.stub import Stubber

from boto_lite import secrets
from boto_lite._client import get_client
from boto_lite.exceptions import NotFoundError, ValidationError

_ARN = "arn:aws:secretsmanager:us-east-1:000000000000:secret:foo-AbCdEf"


class SecretsFacadeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = get_client("secretsmanager")
        self.stubber = Stubber(self.client)
        self.stubber.activate()
        self.addCleanup(self.stubber.deactivate)

    def test_get_returns_secret_string(self) -> None:
        self.stubber.add_response(
            "get_secret_value",
            {"ARN": _ARN, "Name": "foo", "SecretString": "s3cr3t"},
            {"SecretId": "foo"},
        )
        self.assertEqual(secrets.get("foo"), "s3cr3t")

    def test_get_returns_secret_binary(self) -> None:
        payload = b"\x30\x82\x01\x00"
        self.stubber.add_response(
            "get_secret_value",
            {"ARN": _ARN, "Name": "cert", "SecretBinary": payload},
            {"SecretId": "cert"},
        )
        self.assertEqual(secrets.get("cert"), payload)

    def test_get_with_version_stage(self) -> None:
        self.stubber.add_response(
            "get_secret_value",
            {"ARN": _ARN, "Name": "foo", "SecretString": "prev"},
            {"SecretId": "foo", "VersionStage": "AWSPREVIOUS"},
        )
        self.assertEqual(
            secrets.get("foo", version_stage="AWSPREVIOUS"), "prev"
        )

    def test_get_with_version_id(self) -> None:
        vid = "11111111-2222-3333-4444-555555555555"
        self.stubber.add_response(
            "get_secret_value",
            {"ARN": _ARN, "Name": "foo", "SecretString": "pinned"},
            {"SecretId": "foo", "VersionId": vid},
        )
        self.assertEqual(secrets.get("foo", version_id=vid), "pinned")

    def test_get_missing_raises_not_found(self) -> None:
        self.stubber.add_client_error(
            "get_secret_value",
            service_error_code="ResourceNotFoundException",
            expected_params={"SecretId": "nope"},
        )
        with self.assertRaises(NotFoundError):
            secrets.get("nope")

    def test_put_creates_when_absent(self) -> None:
        self.stubber.add_response(
            "create_secret",
            {"ARN": _ARN, "Name": "foo"},
            {"Name": "foo", "SecretString": "v"},
        )
        secrets.put("foo", "v")
        self.stubber.assert_no_pending_responses()

    def test_put_binary_creates(self) -> None:
        payload = b"binary-cert-bytes"
        self.stubber.add_response(
            "create_secret",
            {"ARN": _ARN, "Name": "cert"},
            {"Name": "cert", "SecretBinary": payload},
        )
        secrets.put("cert", payload)
        self.stubber.assert_no_pending_responses()

    def test_put_updates_when_exists(self) -> None:
        self.stubber.add_client_error(
            "create_secret",
            service_error_code="ResourceExistsException",
            expected_params={"Name": "foo", "SecretString": "v"},
        )
        self.stubber.add_response(
            "put_secret_value",
            {"ARN": _ARN, "Name": "foo"},
            {"SecretId": "foo", "SecretString": "v"},
        )
        secrets.put("foo", "v")
        self.stubber.assert_no_pending_responses()

    def test_delete_force_without_recovery(self) -> None:
        self.stubber.add_response(
            "delete_secret",
            {"ARN": _ARN, "Name": "foo"},
            {"SecretId": "foo", "ForceDeleteWithoutRecovery": True},
        )
        secrets.delete("foo", force_delete_without_recovery=True)
        self.stubber.assert_no_pending_responses()

    def test_delete_with_recovery_window(self) -> None:
        self.stubber.add_response(
            "delete_secret",
            {"ARN": _ARN, "Name": "foo"},
            {"SecretId": "foo", "RecoveryWindowInDays": 7},
        )
        secrets.delete("foo", recovery_window_in_days=7)
        self.stubber.assert_no_pending_responses()

    def test_delete_default_uses_aws_default_window(self) -> None:
        self.stubber.add_response(
            "delete_secret",
            {"ARN": _ARN, "Name": "foo"},
            {"SecretId": "foo"},
        )
        secrets.delete("foo")
        self.stubber.assert_no_pending_responses()

    def test_delete_rejects_conflicting_options(self) -> None:
        with self.assertRaises(ValidationError):
            secrets.delete(
                "foo",
                recovery_window_in_days=7,
                force_delete_without_recovery=True,
            )


if __name__ == "__main__":
    unittest.main()
