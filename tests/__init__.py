"""Test-time environment setup.

Sets dummy AWS credentials/region before any boto3 client is built so
Stubber-backed unit tests never try to resolve real creds or endpoints.
"""

import os

os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
