"""boto_lite: a minimal, strongly-typed facade over AWS S3, SQS, and Secrets Manager."""

from boto_lite import s3, secrets, sqs
from boto_lite.exceptions import (
    AuthError,
    BotoLiteError,
    NotFoundError,
    ValidationError,
)
from boto_lite.s3 import S3Client
from boto_lite.secrets import SecretsClient
from boto_lite.sqs import (
    BatchFailure,
    DeleteBatchResult,
    Message,
    SendBatchResult,
    SQSClient,
)

__all__ = [
    "s3",
    "secrets",
    "sqs",
    "S3Client",
    "SQSClient",
    "SecretsClient",
    "Message",
    "BatchFailure",
    "SendBatchResult",
    "DeleteBatchResult",
    "BotoLiteError",
    "NotFoundError",
    "AuthError",
    "ValidationError",
]
