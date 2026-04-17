# Security policy

## Supported versions

`boto-lite` is pre-1.0. Only the latest published minor version
receives security fixes. Pin to a known-good version in production.

## Reporting a vulnerability

If you believe you've found a security issue, **do not open a public
GitHub issue**. Instead, email the maintainer directly:

- Maintainer: Ahmed Hashim
- Email: ahadaoud100@gmail.com
- Subject prefix: `[boto-lite security]`

Please include:

- A description of the issue and the affected version(s).
- Reproduction steps or a proof of concept, if possible.
- Any suggested mitigation.

You should expect an acknowledgement within 5 business days. Once the
issue is understood, we will coordinate a fix, a release, and a public
disclosure date with you.

## Scope

This library is a thin wrapper over `boto3`. Vulnerabilities in boto3
or botocore themselves should be reported upstream to AWS:
<https://aws.amazon.com/security/vulnerability-reporting/>.

Issues specifically in `boto-lite`'s code — for example in our
exception translation, client caching, streaming, or parameter
validation — are in scope for this policy.

## Credentials

`boto-lite` never logs or transmits AWS credentials. It delegates
credential resolution entirely to `boto3.Session`, which reads from
the standard AWS credential chain. Do not pass credentials as
function arguments — use a profile, environment variables, instance
role, or a pre-built `boto3.Session`.
