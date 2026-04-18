"""Tests for ``s3.upload_stream`` and ``s3.presigned_url``."""

from __future__ import annotations

import os

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import io
import unittest
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlparse

import boto3
from botocore.stub import Stubber

from boto_lite import S3Client, s3
from boto_lite.exceptions import ValidationError

# Small part size used throughout these tests. AWS rejects anything
# under 5 MiB, so we override the module constant locally where needed.
PART = 5 * 1024 * 1024  # 5 MiB (AWS minimum)


def _stub_s3() -> tuple[object, Stubber]:
    client = boto3.client("s3", region_name="us-east-1")
    stubber = Stubber(client)
    stubber.activate()
    return client, stubber


class UploadStreamSinglePartTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw, self.stubber = _stub_s3()
        self.addCleanup(self.stubber.deactivate)
        session = MagicMock(spec=boto3.Session)
        session.client.return_value = self.raw
        self.client = S3Client(session=session)

    def test_small_data_uses_put_object_directly(self) -> None:
        body = b"tiny-payload"
        self.stubber.add_response(
            "put_object",
            {"ETag": '"abc123"'},
            {"Bucket": "b", "Key": "k", "Body": body},
        )
        etag = self.client.upload_stream("b", "k", iter([body]), part_size=PART)
        self.assertEqual(etag, '"abc123"')
        self.stubber.assert_no_pending_responses()

    def test_empty_stream_puts_empty_object(self) -> None:
        self.stubber.add_response(
            "put_object",
            {"ETag": '"empty"'},
            {"Bucket": "b", "Key": "k", "Body": b""},
        )
        etag = self.client.upload_stream("b", "k", iter([]), part_size=PART)
        self.assertEqual(etag, '"empty"')
        self.stubber.assert_no_pending_responses()

    def test_content_type_passed_on_single_part_path(self) -> None:
        self.stubber.add_response(
            "put_object",
            {"ETag": '"ct"'},
            {
                "Bucket": "b",
                "Key": "k",
                "Body": b"x",
                "ContentType": "application/json",
            },
        )
        self.client.upload_stream(
            "b", "k", iter([b"x"]), part_size=PART,
            content_type="application/json",
        )
        self.stubber.assert_no_pending_responses()

    def test_rejects_part_size_below_aws_minimum(self) -> None:
        with self.assertRaises(ValidationError):
            self.client.upload_stream(
                "b", "k", iter([b"x"]), part_size=PART - 1
            )


class UploadStreamMultipartTest(unittest.TestCase):
    def setUp(self) -> None:
        self.raw, self.stubber = _stub_s3()
        self.addCleanup(self.stubber.deactivate)
        session = MagicMock(spec=boto3.Session)
        session.client.return_value = self.raw
        self.client = S3Client(session=session)

    def _setup_multipart_success(self, parts_bodies: list[bytes]) -> None:
        self.stubber.add_response(
            "create_multipart_upload",
            {"UploadId": "uid-1"},
            {"Bucket": "b", "Key": "k"},
        )
        completed = []
        for i, body in enumerate(parts_bodies, start=1):
            self.stubber.add_response(
                "upload_part",
                {"ETag": f'"etag-{i}"'},
                {
                    "Bucket": "b",
                    "Key": "k",
                    "UploadId": "uid-1",
                    "PartNumber": i,
                    "Body": body,
                },
            )
            completed.append({"ETag": f'"etag-{i}"', "PartNumber": i})
        self.stubber.add_response(
            "complete_multipart_upload",
            {"ETag": '"final"'},
            {
                "Bucket": "b",
                "Key": "k",
                "UploadId": "uid-1",
                "MultipartUpload": {"Parts": completed},
            },
        )

    def test_multipart_flow_with_three_parts(self) -> None:
        p1, p2, p3 = b"A" * PART, b"B" * PART, b"C" * 1024
        self._setup_multipart_success([p1, p2, p3])
        etag = self.client.upload_stream(
            "b", "k", iter([p1, p2, p3]), part_size=PART
        )
        self.assertEqual(etag, '"final"')
        self.stubber.assert_no_pending_responses()

    def test_rechunks_irregular_iterable_into_part_sized_blocks(self) -> None:
        # Caller yields chunks that don't line up with PART; library
        # must re-chunk them into exactly PART-sized blocks (except last).
        total = PART * 2 + 1024
        stream = iter([b"x" * 1024 for _ in range(total // 1024)])
        self._setup_multipart_success(
            [b"x" * PART, b"x" * PART, b"x" * 1024]
        )
        self.client.upload_stream(
            "b", "k",
            (b"x" * 1024 for _ in range(total // 1024)),
            part_size=PART,
        )
        # Consume the iter we created for count-check; unused.
        list(stream)

    def test_file_like_object_is_read_directly(self) -> None:
        payload = b"Z" * (PART + 10)
        self._setup_multipart_success([b"Z" * PART, b"Z" * 10])
        self.client.upload_stream(
            "b", "k", io.BytesIO(payload), part_size=PART
        )
        self.stubber.assert_no_pending_responses()

    def test_exception_during_upload_part_aborts_multipart(self) -> None:
        self.stubber.add_response(
            "create_multipart_upload",
            {"UploadId": "uid-2"},
            {"Bucket": "b", "Key": "k"},
        )
        self.stubber.add_response(
            "upload_part",
            {"ETag": '"e1"'},
            {
                "Bucket": "b", "Key": "k", "UploadId": "uid-2",
                "PartNumber": 1, "Body": b"A" * PART,
            },
        )
        # Second upload_part: force AWS to reject, triggering abort path.
        self.stubber.add_client_error(
            "upload_part",
            service_error_code="InternalError",
            expected_params={
                "Bucket": "b", "Key": "k", "UploadId": "uid-2",
                "PartNumber": 2, "Body": b"B" * PART,
            },
        )
        self.stubber.add_response(
            "abort_multipart_upload",
            {},
            {"Bucket": "b", "Key": "k", "UploadId": "uid-2"},
        )
        with self.assertRaises(Exception):
            self.client.upload_stream(
                "b", "k",
                iter([b"A" * PART, b"B" * PART, b"C" * 10]),
                part_size=PART,
            )
        self.stubber.assert_no_pending_responses()


class PresignedUrlTest(unittest.TestCase):
    def setUp(self) -> None:
        # Use a real boto3 client (no stubber) — generate_presigned_url
        # is a local operation that signs with the client's credentials
        # and never hits the network.
        self.raw = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="AKIAfaketestkey",
            aws_secret_access_key="fakesecret",
        )
        session = MagicMock(spec=boto3.Session)
        session.client.return_value = self.raw
        self.client = S3Client(session=session)

    def test_get_url_is_signed_and_targets_the_object(self) -> None:
        url = self.client.presigned_url("b", "k", expires_in=600)
        parsed = urlparse(url)
        q = parse_qs(parsed.query)
        # Works for path-style (/b/k) and virtual-hosted (b.s3.amazonaws.com/k).
        self.assertTrue(
            parsed.path.rstrip("/").endswith("/b/k")
            or (parsed.netloc.startswith("b.") and parsed.path.rstrip("/").endswith("/k"))
        )
        # Accept either SigV4 (X-Amz-*) or SigV2 (Signature/Expires).
        self.assertTrue(
            "X-Amz-Signature" in q or "Signature" in q,
            f"No signature found in {q!r}",
        )
        self.assertTrue("X-Amz-Expires" in q or "Expires" in q)

    def test_put_url_selects_put_operation(self) -> None:
        url = self.client.presigned_url(
            "b", "k", operation="put_object", expires_in=60,
        )
        q = parse_qs(urlparse(url).query)
        self.assertTrue("X-Amz-Signature" in q or "Signature" in q)

    def test_extra_params_are_forwarded(self) -> None:
        url = self.client.presigned_url(
            "b", "k",
            extra_params={"ResponseContentDisposition": "attachment; filename=x.txt"},
        )
        q = parse_qs(urlparse(url).query)
        self.assertIn("response-content-disposition", q)

    def test_module_level_function_works_too(self) -> None:
        url = s3.presigned_url("b", "k", session=MagicMock(
            spec=boto3.Session, **{"client.return_value": self.raw}
        ))
        self.assertTrue(url.startswith("https://"))


if __name__ == "__main__":
    unittest.main()
