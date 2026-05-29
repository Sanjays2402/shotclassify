terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  type    = string
  default = "us-west-2"
}

variable "name" {
  type    = string
  default = "shotclassify"
}

variable "tags" {
  type = map(string)
  default = {
    Project = "shotclassify"
    Owner   = "sanjay"
  }
}

resource "aws_s3_bucket" "uploads" {
  bucket = "${var.name}-uploads"
  tags   = var.tags
}

resource "aws_s3_bucket_versioning" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket                  = aws_s3_bucket.uploads.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_iam_user" "app" {
  name = "${var.name}-app"
  tags = var.tags
}

resource "aws_iam_user_policy" "app_s3" {
  name = "${var.name}-s3"
  user = aws_iam_user.app.name
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect = "Allow",
      Action = ["s3:PutObject", "s3:GetObject", "s3:ListBucket", "s3:DeleteObject"],
      Resource = [aws_s3_bucket.uploads.arn, "${aws_s3_bucket.uploads.arn}/*"]
    }]
  })
}

output "bucket_name" { value = aws_s3_bucket.uploads.bucket }
output "iam_user"    { value = aws_iam_user.app.name }
