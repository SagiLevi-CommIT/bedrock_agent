terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

# Per-session conversation history. PK = session_id; sort = turn (timestamp).
resource "aws_dynamodb_table" "sessions" {
  name         = "${var.name_prefix}-sessions"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "session_id"
  range_key    = "turn"

  attribute {
    name = "session_id"
    type = "S"
  }

  attribute {
    name = "turn"
    type = "N"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = false # staging
  }
}

# Per-request cost rollup (Bedrock + Athena + tool counts).
resource "aws_dynamodb_table" "cost" {
  name         = "${var.name_prefix}-cost"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "request_id"

  attribute {
    name = "request_id"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}

# Cache for integer patient_id → pUuid resolution. Populated lazily by the
# resolve_patient_uuid tool after each successful Patients API call.
resource "aws_dynamodb_table" "patient_id_map" {
  name         = "${var.name_prefix}-patient-id-map"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "patient_id"

  attribute {
    name = "patient_id"
    type = "N"
  }
}

# Agent-owned bucket for downloads, exports, reports, charts.
resource "aws_s3_bucket" "output" {
  bucket = "${var.name_prefix}-output-${var.account_id}"
}

resource "aws_s3_bucket_versioning" "output" {
  bucket = aws_s3_bucket.output.id

  versioning_configuration {
    status = "Suspended"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "output" {
  bucket = aws_s3_bucket.output.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "output" {
  bucket = aws_s3_bucket.output.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "output" {
  bucket = aws_s3_bucket.output.id

  rule {
    id     = "expire-old-downloads"
    status = "Enabled"

    filter {
      prefix = ""
    }

    expiration {
      days = 30
    }
  }
}

# Athena query results bucket — separate from data so we keep IAM tight.
resource "aws_s3_bucket" "athena_results" {
  bucket = "${var.name_prefix}-athena-results-${var.account_id}"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id

  rule {
    id     = "expire-results"
    status = "Enabled"

    filter {
      prefix = ""
    }

    expiration {
      days = 7
    }
  }
}

# CodeBuild source bucket — zips of the app are uploaded here.
resource "aws_s3_bucket" "codebuild_source" {
  bucket = "${var.name_prefix}-codebuild-src-${var.account_id}"
}

resource "aws_s3_bucket_versioning" "codebuild_source" {
  bucket = aws_s3_bucket.codebuild_source.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "codebuild_source" {
  bucket = aws_s3_bucket.codebuild_source.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "codebuild_source" {
  bucket = aws_s3_bucket.codebuild_source.id

  rule {
    id     = "expire-old-versions"
    status = "Enabled"

    filter {
      prefix = ""
    }

    noncurrent_version_expiration {
      noncurrent_days = 7
    }
  }
}
