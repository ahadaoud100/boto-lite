"""Typed exceptions raised by the boto_lite facade."""


class BotoLiteError(Exception):
    """Base class for all boto_lite errors."""


class NotFoundError(BotoLiteError):
    """Raised when a requested resource does not exist."""


class AuthError(BotoLiteError):
    """Raised when AWS credentials are missing or insufficient."""


class ValidationError(BotoLiteError):
    """Raised when call parameters fail botocore's local validation."""
