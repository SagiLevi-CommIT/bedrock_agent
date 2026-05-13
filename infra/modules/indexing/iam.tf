# IAM for the daily-refresh Lambda. Separate from the agent runtime task
# role per CLAUDE.md ("the task role has no glue:Create*"). This role is
# only assumed by the Lambda; the runtime cannot use it.

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "rollup_lambda" {
  name               = "${var.name_prefix}-rollup-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = var.tags
}

# Standard CloudWatch Logs permissions
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.rollup_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Athena + Glue access — read-only on source data + write to results bucket.
data "aws_iam_policy_document" "rollup_lambda" {
  statement {
    sid = "AthenaQuery"
    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:GetWorkGroup",
      "athena:StopQueryExecution",
    ]
    resources = ["*"]
  }

  statement {
    sid = "GlueRead"
    actions = [
      "glue:GetDatabase",
      "glue:GetDatabases",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartition",
      "glue:GetPartitions",
      "glue:BatchGetPartition",
      "glue:CreatePartition",
      "glue:UpdatePartition",
      "glue:BatchCreatePartition",
    ]
    resources = ["*"]
  }

  statement {
    sid = "S3ReadDataBuckets"
    actions = [
      "s3:GetObject",
      "s3:ListBucket",
    ]
    resources = [
      "arn:aws:s3:::${var.app_events_bucket}",
      "arn:aws:s3:::${var.app_events_bucket}/*",
      "arn:aws:s3:::735555370207-migrated--data",
      "arn:aws:s3:::735555370207-migrated--data/*",
    ]
  }

  statement {
    sid = "S3WriteRollupAndResults"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:ListBucket",
      "s3:GetBucketLocation",
    ]
    resources = [
      "arn:aws:s3:::${var.rollup_bucket}",
      "arn:aws:s3:::${var.rollup_bucket}/*",
      "arn:aws:s3:::${var.athena_results_bucket}",
      "arn:aws:s3:::${var.athena_results_bucket}/*",
    ]
  }
}

resource "aws_iam_role_policy" "rollup_lambda" {
  name   = "${var.name_prefix}-rollup-lambda-policy"
  role   = aws_iam_role.rollup_lambda.id
  policy = data.aws_iam_policy_document.rollup_lambda.json
}
