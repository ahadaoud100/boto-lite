"""boto_lite: a minimal, strongly-typed facade over AWS S3, SQS, and Secrets Manager."""

from boto_lite import s3, secrets, sqs
from boto_lite.exceptions import (
    AuthError,
    BotoLiteError,
    NotFoundError,
    ValidationError,
)

__all__ = [
    "s3",
    "secrets",
    "sqs",
    "BotoLiteError",
    "NotFoundError",
    "AuthError",
    "ValidationError",
]
