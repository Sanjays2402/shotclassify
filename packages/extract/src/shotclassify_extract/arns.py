"""Cross-category AWS resource ARN extractor.

AWS resource identifiers follow a standard Amazon Resource Name (ARN)
shape that surfaces across error logs (IAM "user X is not authorized"
on a specific resource ARN), code snippets (AWS SDK calls), Terraform /
CloudFormation captures (resource declarations), document captures
(security audit reports), and chat captures (paste-the-ARN-when-asking-
for-help). Rather than teach each per-category extractor to find them,
we run :func:`extract_arns` once on the OCR text and stash unique
entries under ``ExtractedFields.raw["arns"]``.

Output shape: a list of ``{"service", "region", "account", "resource",
"arn"}`` dicts where:

* ``service``  -- AWS service tag (``s3``, ``iam``, ``lambda``,
                  ``ec2``, ``dynamodb``, ``sqs``, ``sns``,
                  ``cloudwatch``, ``logs``, ``rds``, etc.)
* ``region``   -- AWS region tag (``us-east-1``, ``eu-west-2``,
                  ``ap-southeast-2``, etc.) or ``""`` for global
                  services (S3, IAM).
* ``account``  -- 12-digit AWS account ID or ``""`` for
                  account-less ARNs (S3 bucket ARNs do NOT carry
                  an account segment).
* ``resource`` -- the trailing resource path (the full text after
                  the account segment, including ``type/name`` or
                  ``type:name`` substructure).
* ``arn``      -- the full original ARN string.

Output preserves first-seen order, de-dupes on the ``arn`` value,
capped at 50 entries.

ARN shape (per the AWS docs):

  arn:<partition>:<service>:<region>:<account-id>:<resource-id>
  arn:<partition>:<service>:<region>:<account-id>:<resource-type>/<resource-id>
  arn:<partition>:<service>:<region>:<account-id>:<resource-type>:<resource-id>

Recognised partitions: ``aws`` (commercial), ``aws-cn`` (China
regions), ``aws-us-gov`` (GovCloud). Any of the three is accepted.
"""
from __future__ import annotations

import re

# Generic ARN matcher. We accept the three known partitions
# (``aws`` / ``aws-cn`` / ``aws-us-gov``), a short lowercase service
# tag, an optional region (empty for global services like IAM and
# S3 bucket ARNs), an optional 12-digit account ID (empty for S3
# bucket ARNs), and the trailing resource segment which can contain
# colons, slashes, periods, dashes, alphanumerics, underscores, and
# the wildcard ``*``.
#
# We allow the resource segment to extend across multiple colons /
# slashes (an ARN like
# ``arn:aws:lambda:us-east-1:1234567:function:foo:1`` has TWO colons
# inside the resource part). Word-boundary on the left is the
# ``arn:`` prefix; on the right we use a negative-lookahead so a
# trailing word character does not extend the ARN into a longer
# blob. We DO allow trailing ``/`` characters inside the resource
# segment because S3 object ARNs include them.
_ARN_RE = re.compile(
    r"(?<![A-Za-z0-9])"
    r"arn:"
    r"(?P<partition>aws|aws-cn|aws-us-gov)"
    r":"
    r"(?P<service>[a-z][a-z0-9\-]{1,30})"
    r":"
    r"(?P<region>[a-z]{2}-[a-z]+-\d+|cn-[a-z]+-\d+|us-gov-[a-z]+-\d+)?"
    r":"
    # Account segment: 12-digit AWS account ID, the literal "aws"
    # (used on AWS-managed IAM policies like
    # ``arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess``), or empty
    # (used on S3 bucket ARNs).
    r"(?P<account>\d{12}|aws)?"
    r":"
    r"(?P<resource>[A-Za-z0-9_\-./:*][A-Za-z0-9_\-./:*]*)",
    re.IGNORECASE,
)


_MAX_ARNS = 50


def extract_arns(text: str) -> list[dict[str, str]]:
    """Return unique AWS ARN entries found in ``text``.

    Output is a list of ``{"service", "region", "account",
    "resource", "arn"}`` dicts. Preserves first-seen order across
    the OCR text and de-dupes on the ``arn`` value so the same ARN
    printed multiple times collapses to one entry. Caps the output
    at 50 entries.

    The matcher is anchored to the literal ``arn:`` prefix and the
    standard 6-segment colon-separated shape:

      arn:<partition>:<service>:<region>:<account>:<resource>

    Accepted partitions: ``aws`` (commercial), ``aws-cn`` (China
    regions), ``aws-us-gov`` (GovCloud). Region and account
    segments may both be empty for global services (S3 bucket ARNs
    are the canonical example: ``arn:aws:s3:::mybucket``).

    The resource segment is captured greedily across additional
    colons and slashes so the full Lambda / IAM-policy /
    CloudFormation-stack ARN forms are preserved (e.g.
    ``arn:aws:lambda:us-east-1:123:function:foo:1``). A trailing
    word boundary is NOT enforced on the right because Stack /
    Resource ARNs end with dynamic alphanumerics that we want to
    capture verbatim; the boundary is implicit when the next char
    is whitespace or a non-resource character.
    """
    if not text or not isinstance(text, str):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for m in _ARN_RE.finditer(text):
        # Pull the segments out (lowercased for service / region /
        # partition since those are case-insensitive in AWS docs;
        # account stays as captured).
        partition = m.group("partition").lower()
        service = m.group("service").lower()
        region = (m.group("region") or "").lower()
        account = m.group("account") or ""
        resource = m.group("resource")
        # Trim any trailing punctuation that the OCR may have
        # picked up (a period at the end of a sentence, a comma,
        # a closing paren / bracket / brace / quote).
        resource = resource.rstrip(".,;:)]}>'\"")
        # Rebuild the canonical ARN string from the trimmed parts
        # so duplicate ARNs that differed only by trailing
        # punctuation collapse to one entry.
        canonical = f"arn:{partition}:{service}:{region}:{account}:{resource}"
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(
            {
                "service": service,
                "region": region,
                "account": account,
                "resource": resource,
                "arn": canonical,
            }
        )
        if len(out) >= _MAX_ARNS:
            break
    return out


__all__ = ["extract_arns"]
