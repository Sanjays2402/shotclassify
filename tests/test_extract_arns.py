"""Cross-category AWS ARN extractor tests.

A new cross-category extractor surfaces AWS resource ARNs found in
the OCR text under ``ExtractedFields.raw["arns"]``.

Output shape: list of ``{"service", "region", "account",
"resource", "arn"}`` dicts so downstream consumers can route on
service or region without re-parsing the ARN.

Shape rules:

* Anchored to the literal ``arn:`` prefix and standard 6-segment
  colon-separated form:
  ``arn:<partition>:<service>:<region>:<account>:<resource>``.
* Accepts the three AWS partitions: ``aws`` (commercial),
  ``aws-cn`` (China), ``aws-us-gov`` (GovCloud).
* Region and account segments may be empty for global services
  (S3 bucket ARNs are the canonical example:
  ``arn:aws:s3:::mybucket``).
* The resource segment is captured greedily so multi-colon
  forms like ``arn:aws:lambda:us-east-1:123:function:foo:1`` are
  preserved verbatim.
* Trailing punctuation (``.``, ``,``, ``)``) is trimmed.
* Output preserves first-seen order, de-dupes on ``arn`` value,
  capped at 50.
"""
from __future__ import annotations

from shotclassify_common import Category, ExtractedFields, OCRResult
from shotclassify_extract import enrich, extract_arns

# ---- S3 ARNs (account-less, region-less) -------------------------


def test_s3_bucket_arn():
    out = extract_arns("Stored in arn:aws:s3:::my-bucket")
    assert out == [
        {
            "service": "s3",
            "region": "",
            "account": "",
            "resource": "my-bucket",
            "arn": "arn:aws:s3:::my-bucket",
        }
    ]


def test_s3_object_arn():
    out = extract_arns("File arn:aws:s3:::my-bucket/path/to/file.txt")
    assert out == [
        {
            "service": "s3",
            "region": "",
            "account": "",
            "resource": "my-bucket/path/to/file.txt",
            "arn": "arn:aws:s3:::my-bucket/path/to/file.txt",
        }
    ]


def test_s3_wildcard_arn():
    out = extract_arns("Allow on arn:aws:s3:::my-bucket/*")
    assert len(out) == 1
    assert out[0]["resource"] == "my-bucket/*"


# ---- IAM ARNs (account, no region) -------------------------------


def test_iam_user_arn():
    out = extract_arns("Failed: arn:aws:iam::123456789012:user/JaneDoe")
    assert out == [
        {
            "service": "iam",
            "region": "",
            "account": "123456789012",
            "resource": "user/JaneDoe",
            "arn": "arn:aws:iam::123456789012:user/JaneDoe",
        }
    ]


def test_iam_role_arn():
    out = extract_arns(
        "AssumeRole arn:aws:iam::123456789012:role/lambda-execution"
    )
    assert len(out) == 1
    assert out[0]["service"] == "iam"
    assert out[0]["resource"] == "role/lambda-execution"


def test_iam_policy_arn():
    out = extract_arns(
        "Policy arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
    )
    # AWS-managed policies use the literal "aws" as their account
    # segment. We recognise this explicitly so the resource segment
    # parses cleanly.
    assert len(out) == 1
    assert out[0]["service"] == "iam"
    assert out[0]["account"] == "aws"
    assert out[0]["resource"] == "policy/AmazonS3ReadOnlyAccess"


# ---- Lambda ARNs (region + account + multi-colon resource) -----


def test_lambda_function_arn():
    out = extract_arns(
        "arn:aws:lambda:us-east-1:123456789012:function:my-function"
    )
    assert out == [
        {
            "service": "lambda",
            "region": "us-east-1",
            "account": "123456789012",
            "resource": "function:my-function",
            "arn": "arn:aws:lambda:us-east-1:123456789012:function:my-function",
        }
    ]


def test_lambda_function_with_version_arn():
    out = extract_arns(
        "arn:aws:lambda:us-east-1:123456789012:function:my-function:42"
    )
    assert len(out) == 1
    assert out[0]["resource"] == "function:my-function:42"


# ---- DynamoDB ARNs ---------------------------------------------


def test_dynamodb_table_arn():
    out = extract_arns(
        "Table arn:aws:dynamodb:us-west-2:123456789012:table/MyTable"
    )
    assert out == [
        {
            "service": "dynamodb",
            "region": "us-west-2",
            "account": "123456789012",
            "resource": "table/MyTable",
            "arn": "arn:aws:dynamodb:us-west-2:123456789012:table/MyTable",
        }
    ]


def test_dynamodb_index_arn():
    out = extract_arns(
        "Index arn:aws:dynamodb:us-west-2:123456789012:table/MyTable/index/MyIndex"
    )
    assert len(out) == 1
    assert "table/MyTable/index/MyIndex" in out[0]["resource"]


# ---- SQS / SNS / CloudWatch ------------------------------------


def test_sqs_queue_arn():
    out = extract_arns(
        "Queue arn:aws:sqs:eu-west-1:123456789012:my-queue"
    )
    assert out[0]["service"] == "sqs"
    assert out[0]["region"] == "eu-west-1"
    assert out[0]["resource"] == "my-queue"


def test_sns_topic_arn():
    out = extract_arns(
        "Topic arn:aws:sns:us-east-1:123456789012:MyTopic"
    )
    assert out[0]["service"] == "sns"


def test_cloudwatch_log_group_arn():
    out = extract_arns(
        "LogGroup arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/foo:*"
    )
    assert len(out) == 1
    assert out[0]["service"] == "logs"
    assert "log-group:/aws/lambda/foo:*" in out[0]["resource"]


# ---- EC2 ARNs --------------------------------------------------


def test_ec2_instance_arn():
    out = extract_arns(
        "Instance arn:aws:ec2:us-east-1:123456789012:instance/i-0abcd1234efgh5678"
    )
    assert out[0]["service"] == "ec2"
    assert out[0]["resource"] == "instance/i-0abcd1234efgh5678"


# ---- Partitions ------------------------------------------------


def test_china_partition():
    out = extract_arns(
        "arn:aws-cn:s3:::beijing-bucket"
    )
    assert len(out) == 1
    assert out[0]["arn"].startswith("arn:aws-cn:s3:")


def test_govcloud_partition():
    out = extract_arns(
        "arn:aws-us-gov:iam::123456789012:user/secure"
    )
    assert len(out) == 1
    assert out[0]["arn"].startswith("arn:aws-us-gov:")
    assert out[0]["account"] == "123456789012"


def test_govcloud_region():
    out = extract_arns(
        "arn:aws-us-gov:s3:us-gov-west-1:123456789012:my-bucket"
    )
    assert out[0]["region"] == "us-gov-west-1"


def test_china_region():
    out = extract_arns(
        "arn:aws-cn:s3:cn-north-1:123456789012:my-bucket"
    )
    assert out[0]["region"] == "cn-north-1"


# ---- Regional variants -----------------------------------------


def test_eu_west_region():
    out = extract_arns(
        "arn:aws:lambda:eu-west-2:123456789012:function:eu-fn"
    )
    assert out[0]["region"] == "eu-west-2"


def test_ap_southeast_region():
    out = extract_arns(
        "arn:aws:s3:ap-southeast-2:123456789012:bucket/path"
    )
    assert out[0]["region"] == "ap-southeast-2"


# ---- Trailing punctuation trim --------------------------------


def test_trailing_period_trimmed():
    out = extract_arns(
        "See arn:aws:iam::123456789012:user/Bob. The rest of the sentence."
    )
    assert len(out) == 1
    assert out[0]["resource"] == "user/Bob"
    assert not out[0]["arn"].endswith(".")


def test_trailing_comma_trimmed():
    out = extract_arns(
        "ARNs: arn:aws:s3:::a-bucket, arn:aws:s3:::b-bucket"
    )
    assert len(out) == 2
    assert out[0]["resource"] == "a-bucket"
    assert out[1]["resource"] == "b-bucket"


def test_trailing_paren_trimmed():
    out = extract_arns(
        "(arn:aws:s3:::my-bucket)"
    )
    assert len(out) == 1
    assert out[0]["resource"] == "my-bucket"


def test_trailing_quote_trimmed():
    out = extract_arns(
        '"arn:aws:s3:::my-bucket"'
    )
    assert len(out) == 1
    assert out[0]["resource"] == "my-bucket"


# ---- Case insensitivity --------------------------------------


def test_uppercase_arn_normalised():
    out = extract_arns("ARN:AWS:S3:::MY-BUCKET")
    assert len(out) == 1
    assert out[0]["service"] == "s3"
    assert out[0]["arn"] == "arn:aws:s3:::MY-BUCKET"


# ---- Multiple ARNs in one text ------------------------------


def test_preserves_first_seen_order():
    text = (
        "Source: arn:aws:s3:::bucket-a\n"
        "Target: arn:aws:s3:::bucket-b\n"
        "Log: arn:aws:logs:us-east-1:123456789012:log-group:/foo:*\n"
    )
    out = extract_arns(text)
    assert [x["resource"].split(":")[0].split("/")[0] for x in out] == [
        "bucket-a",
        "bucket-b",
        "log-group",
    ]


def test_dedupes_same_arn():
    text = (
        "Failed: arn:aws:iam::123456789012:user/JaneDoe\n"
        "Retry: arn:aws:iam::123456789012:user/JaneDoe\n"
    )
    out = extract_arns(text)
    assert len(out) == 1


def test_cap_at_50():
    # Build 60 distinct bucket ARNs; output must cap at 50.
    text = " ".join(
        f"arn:aws:s3:::bucket-{i:03d}" for i in range(60)
    )
    out = extract_arns(text)
    assert len(out) == 50


# ---- Rejection tests ---------------------------------------


def test_invalid_partition_rejected():
    # ``aws-eu`` is not a real partition.
    out = extract_arns("arn:aws-eu:s3:::my-bucket")
    assert out == []


def test_missing_arn_prefix():
    out = extract_arns("aws:s3:::my-bucket")
    assert out == []


def test_not_enough_segments():
    out = extract_arns("arn:aws:s3:my-bucket")
    assert out == []


def test_arn_inside_longer_word_rejected():
    # The literal ``arn:`` must not be preceded by an alphanumeric
    # word character. ``XYZarn:aws:s3:::b`` should not misfire.
    out = extract_arns("XYZarn:aws:s3:::my-bucket")
    assert out == []


def test_empty_text():
    assert extract_arns("") == []
    assert extract_arns(None) == []  # type: ignore[arg-type]


def test_no_arns():
    text = "Just an email user@example.com and a URL https://example.com"
    assert extract_arns(text) == []


# ---- Pipeline integration ---------------------------------


def test_pipeline_writes_raw_arns():
    text = "User arn:aws:iam::123456789012:user/JaneDoe is not authorized"
    ocr = OCRResult(text=text)
    out = enrich(Category.error_stacktrace, ExtractedFields(), ocr)
    assert out.raw is not None
    assert "arns" in out.raw
    assert out.raw["arns"][0]["resource"] == "user/JaneDoe"


def test_pipeline_no_raw_key_when_no_arns():
    ocr = OCRResult(text="Just an email user@example.com")
    out = enrich(Category.error_stacktrace, ExtractedFields(), ocr)
    if out.raw is not None:
        assert "arns" not in out.raw


def test_pipeline_writes_for_every_category():
    text = "Lambda arn:aws:lambda:us-east-1:123456789012:function:my-fn"
    ocr = OCRResult(text=text)
    for cat in Category:
        out = enrich(cat, ExtractedFields(), ocr)
        assert out.raw is not None
        assert "arns" in out.raw


# ---- Real-world contexts ---------------------------------


def test_terraform_resource_context():
    text = '''
resource "aws_iam_role_policy_attachment" "example" {
  role       = aws_iam_role.example.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"
}
'''
    out = extract_arns(text)
    assert len(out) == 1
    assert "AmazonS3ReadOnlyAccess" in out[0]["arn"]


def test_cli_error_context():
    text = (
        "An error occurred (AccessDenied) when calling the GetObject "
        "operation: User arn:aws:iam::123456789012:user/Bob is not "
        "authorized to perform: s3:GetObject on resource "
        "arn:aws:s3:::secret-bucket/key.txt"
    )
    out = extract_arns(text)
    assert len(out) == 2
    assert out[0]["service"] == "iam"
    assert out[1]["service"] == "s3"


def test_cloudformation_stack_context():
    text = (
        "arn:aws:cloudformation:us-east-1:123456789012:stack/"
        "my-stack/00abcd00-0000-1111-2222-abcdef000000"
    )
    out = extract_arns(text)
    assert len(out) == 1
    assert out[0]["service"] == "cloudformation"


def test_json_aws_sdk_response():
    text = '{"FunctionArn": "arn:aws:lambda:us-east-1:123456789012:function:my-fn"}'
    out = extract_arns(text)
    assert len(out) == 1
    assert out[0]["service"] == "lambda"
