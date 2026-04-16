from __future__ import annotations

import os

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import unittest

from botocore.stub import Stubber

from boto_lite import secrets
from boto_lite._client import get_client
from boto_lite.exceptions import NotFoundError


class SecretsFacadeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = get_client("secretsmanager")
        self.stubber = Stubber(self.client)
        self.stubber.activate()
        self.addCleanup(self.stubber.deactivate)

    def test_get_returns_secret_string(self) -> None:
        self.stubber.add_response(
            "get_secret_value",
            {"ARN": "arn:aws:secretsmanager:us-east-1:000000000000:secret:foo-AbCdEf", "Name": "foo", "SecretString": "s3cr3t"},
            {"SecretId": "foo"},
        )
        self.assertEqual(secrets.get("foo"), "s3cr3t")

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
            {"ARN": "arn:aws:secretsmanager:us-east-1:000000000000:secret:foo-AbCdEf", "Name": "foo"},
            {"Name": "foo", "SecretString": "v"},
        )
        secrets.put("foo", "v")
        self.stubber.assert_no_pending_responses()

    def test_put_updates_when_exists(self) -> None:
        self.stubber.add_client_error(
            "create_secret",
            service_error_code="ResourceExistsException",
            expected_params={"Name": "foo", "SecretString": "v"},
        )
        self.stubber.add_response(
            "put_secret_value",
            {"ARN": "arn:aws:secretsmanager:us-east-1:000000000000:secret:foo-AbCdEf", "Name": "foo"},
            {"SecretId": "foo", "SecretString": "v"},
        )
        secrets.put("foo", "v")
        self.stubber.assert_no_pending_responses()

    def test_delete_force(self) -> None:
        self.stubber.add_response(
            "delete_secret",
            {"ARN": "arn:aws:secretsmanager:us-east-1:000000000000:secret:foo-AbCdEf", "Name": "foo"},
            {"SecretId": "foo", "ForceDeleteWithoutRecovery": True},
        )
        secrets.delete("foo", force=True)
        self.stubber.assert_no_pending_responses()


if __name__ == "__main__":
    unittest.main()
