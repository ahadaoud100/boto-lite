from __future__ import annotations

import os

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import types
import unittest
from io import BytesIO
from unittest.mock import MagicMock

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

    def test_get_object_streams_chunks(self) -> None:
        payload = b"hello world"
        self.stubber.add_response(
            "get_object",
            {"Body": StreamingBody(BytesIO(payload), len(payload))},
            {"Bucket": "b", "Key": "k"},
        )
        result = s3.get_object("b", "k")
        self.assertIsInstance(result, types.GeneratorType)
        chunks = list(result)
        self.assertGreaterEqual(len(chunks), 1)
        self.assertEqual(b"".join(chunks), payload)
        self.stubber.assert_no_pending_responses()

    def test_get_object_missing_raises_not_found(self) -> None:
        self.stubber.add_client_error(
            "get_object",
            service_error_code="NoSuchKey",
            expected_params={"Bucket": "b", "Key": "missing"},
        )
        with self.assertRaises(NotFoundError):
            list(s3.get_object("b", "missing"))

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

    def test_list_keys_yields_across_pages(self) -> None:
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
        result = s3.list_keys("bkt", "p/")
        self.assertIsInstance(result, types.GeneratorType)
        self.assertEqual(list(result), ["a", "b", "c"])
        self.stubber.assert_no_pending_responses()


class S3StreamCleanupTest(unittest.TestCase):
    """_stream_body must call Body.close() on early exit, exhaustion, and
    exceptions — otherwise we leak urllib3 connections on the happy path
    that matters most (HTTP keep-alive reuse after partial reads)."""

    def _make_body(self, chunks: list[bytes]) -> MagicMock:
        body = MagicMock()
        body.iter_chunks.return_value = iter(chunks)
        return body

    def test_closes_body_on_full_consumption(self) -> None:
        from boto_lite.s3 import _stream_body

        body = self._make_body([b"a", b"b"])
        gen = _stream_body({"Body": body})
        list(gen)
        body.close.assert_called_once()

    def test_closes_body_on_early_break(self) -> None:
        from boto_lite.s3 import _stream_body

        body = self._make_body([b"a", b"b", b"c"])
        gen = _stream_body({"Body": body})
        for _ in gen:
            break
        gen.close()
        body.close.assert_called_once()

    def test_closes_body_on_exception_in_consumer(self) -> None:
        from boto_lite.s3 import _stream_body

        body = self._make_body([b"a", b"b"])
        gen = _stream_body({"Body": body})
        try:
            with self.assertRaises(RuntimeError):
                for _ in gen:
                    raise RuntimeError("consumer blew up")
        finally:
            gen.close()
        body.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
