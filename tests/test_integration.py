"""LocalStack integration tests.

These exercise real AWS API wire traffic against a running LocalStack
instance at ``LOCALSTACK_URL`` (default ``http://localhost:4566``). Bring
it up with ``docker compose up -d localstack`` before running pytest.

When LocalStack is not reachable, the whole module is skipped — CI and
local runs without Docker still pass the rest of the suite cleanly.
"""

from __future__ import annotations

import os
import socket
import unittest
import uuid
from urllib.parse import urlparse

os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

import boto3

from boto_lite import s3, sqs
from boto_lite import _client as client_mod

LOCALSTACK_URL = os.environ.get("LOCALSTACK_URL", "http://localhost:4566")


def _localstack_reachable(url: str, timeout: float = 0.5) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


@unittest.skipUnless(
    _localstack_reachable(LOCALSTACK_URL),
    f"LocalStack not reachable at {LOCALSTACK_URL}; "
    "run `docker compose up -d localstack` to enable integration tests.",
)
class LocalStackIntegrationTest(unittest.TestCase):
    """Real wire traffic against LocalStack via injected boto3.Session.

    Each test uses a freshly constructed ``boto3.Session`` with its
    ``endpoint_url`` pointed at LocalStack and passes it through the
    facade via the new ``session=`` argument, exercising both the
    session-injection code path and real network/botocore behavior.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.session = boto3.Session(region_name="us-east-1")
        # Admin clients, used only to prep/cleanup LocalStack state.
        cls.admin_s3 = cls.session.client("s3", endpoint_url=LOCALSTACK_URL)
        cls.admin_sqs = cls.session.client("sqs", endpoint_url=LOCALSTACK_URL)
        # The session we hand to the facade: every client it builds will
        # automatically be aimed at LocalStack via AWS_ENDPOINT_URL.
        os.environ["AWS_ENDPOINT_URL"] = LOCALSTACK_URL
        # Wipe the facade's cache so our env change is picked up.
        client_mod._client_cache.clear()

    @classmethod
    def tearDownClass(cls) -> None:
        os.environ.pop("AWS_ENDPOINT_URL", None)
        client_mod._client_cache.clear()

    def test_s3_roundtrip_with_streaming_get_and_generator_list(self) -> None:
        bucket = f"boto-lite-it-{uuid.uuid4().hex[:12]}"
        self.admin_s3.create_bucket(Bucket=bucket)
        try:
            payload = b"integration-payload-" + os.urandom(32)
            s3.put_object(bucket, "obj/1.bin", payload, session=self.session)
            s3.put_object(bucket, "obj/2.bin", b"second", session=self.session)

            # list_keys is a generator — consume lazily.
            keys_gen = s3.list_keys(bucket, prefix="obj/", session=self.session)
            keys = sorted(keys_gen)
            self.assertEqual(keys, ["obj/1.bin", "obj/2.bin"])

            # get_object yields chunks; join to reconstruct.
            chunks = list(s3.get_object(bucket, "obj/1.bin", session=self.session))
            self.assertGreaterEqual(len(chunks), 1)
            self.assertEqual(b"".join(chunks), payload)

            s3.delete_object(bucket, "obj/1.bin", session=self.session)
            s3.delete_object(bucket, "obj/2.bin", session=self.session)
        finally:
            # Best-effort cleanup.
            try:
                for obj in self.admin_s3.list_objects_v2(Bucket=bucket).get(
                    "Contents", []
                ):
                    self.admin_s3.delete_object(Bucket=bucket, Key=obj["Key"])
                self.admin_s3.delete_bucket(Bucket=bucket)
            except Exception:
                pass

    def test_sqs_send_receive_delete_long_poll(self) -> None:
        queue_name = f"boto-lite-it-{uuid.uuid4().hex[:12]}"
        created = self.admin_sqs.create_queue(QueueName=queue_name)
        queue_url = created["QueueUrl"]
        try:
            message_id = sqs.send(queue_url, "integration-body", session=self.session)
            self.assertTrue(message_id)

            # Long-poll so we reliably pick up the message even if the
            # first SQS host sample comes back empty.
            msgs = sqs.receive(
                queue_url,
                max_messages=1,
                wait_seconds=5,
                session=self.session,
            )
            self.assertEqual(len(msgs), 1)
            self.assertEqual(msgs[0].body, "integration-body")
            self.assertEqual(msgs[0].id, message_id)

            sqs.delete(queue_url, msgs[0].receipt_handle, session=self.session)
        finally:
            try:
                self.admin_sqs.delete_queue(QueueUrl=queue_url)
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
