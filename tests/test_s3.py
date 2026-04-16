from __future__ import annotations

import os

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import unittest
from io import BytesIO

from botocore.response import StreamingBody
from botocore.stub import Stubber

from boto_lite import s3
from boto_lite._client import get_client
from boto_lite.exceptions import NotFoundError


class S3FacadeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.client = get_client("s3")
        self.stubber = Stubber(self.client)
        self.stubber.activate()
        self.addCleanup(self.stubber.deactivate)

    def test_get_object_returns_bytes(self) -> None:
        payload = b"hello world"
        self.stubber.add_response(
            "get_object",
            {"Body": StreamingBody(BytesIO(payload), len(payload))},
            {"Bucket": "b", "Key": "k"},
        )
        self.assertEqual(s3.get_object("b", "k"), payload)
        self.stubber.assert_no_pending_responses()

    def test_get_object_missing_raises_not_found(self) -> None:
        self.stubber.add_client_error(
            "get_object",
            service_error_code="NoSuchKey",
            expected_params={"Bucket": "b", "Key": "missing"},
        )
        with self.assertRaises(NotFoundError):
            s3.get_object("b", "missing")

    def test_put_object(self) -> None:
        self.stubber.add_response(
            "put_object",
            {},
            {"Bucket": "b", "Key": "k", "Body": b"data"},
        )
        s3.put_object("b", "k", b"data")
        self.stubber.assert_no_pending_responses()

    def test_delete_object(self) -> None:
        self.stubber.add_response(
            "delete_object", {}, {"Bucket": "b", "Key": "k"}
        )
        s3.delete_object("b", "k")
        self.stubber.assert_no_pending_responses()

    def test_list_keys_paginates(self) -> None:
        self.stubber.add_response(
            "list_objects_v2",
            {
                "Contents": [{"Key": "a"}, {"Key": "b"}],
                "IsTruncated": True,
                "NextContinuationToken": "tok",
            },
            {"Bucket": "bkt", "Prefix": "p/"},
        )
        self.stubber.add_response(
            "list_objects_v2",
            {"Contents": [{"Key": "c"}], "IsTruncated": False},
            {"Bucket": "bkt", "Prefix": "p/", "ContinuationToken": "tok"},
        )
        self.assertEqual(s3.list_keys("bkt", "p/"), ["a", "b", "c"])
        self.stubber.assert_no_pending_responses()


if __name__ == "__main__":
    unittest.main()
