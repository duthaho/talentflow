terraform {
  required_version = ">= 1.8.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0, < 7.0"
    }
  }
}

variable "aws_region" {
  type        = string
  description = "Region for the state bucket. Keep state in the same approved jurisdiction as the environment."
}

variable "state_bucket_name" {
  type        = string
  description = "Globally unique S3 bucket name for encrypted OpenTofu state."
}

variable "tags" {
  type        = map(string)
  description = "Organization ownership and classification tags."
  default     = {}
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = merge(
      {
        Application = "TalentFlow"
        ManagedBy   = "OpenTofu"
        Repository  = "duthaho/talentflow"
        Purpose     = "infrastructure-state"
      },
      var.tags,
    )
  }
}

resource "aws_s3_bucket" "state" {
  bucket = var.state_bucket_name
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    id     = "retain-versioned-state"
    status = "Enabled"

    noncurrent_version_expiration {
      noncurrent_days = 365
    }
  }
}

output "state_bucket_name" {
  value = aws_s3_bucket.state.bucket
}
