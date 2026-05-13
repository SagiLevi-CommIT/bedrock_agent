# Daily refresh Lambda + EventBridge rule.
#
# Lambda packages the Python source under lambda_src/ and runs every day at
# 02:00 UTC. It:
#   1. Computes yesterday's `patient_daily` partition by querying
#      migrated_data.pc_results_part + migrated_data.pc_timeseries.
#   2. Lists rearrangement S3 prefixes for sleep_flow + rt_flow + others to
#      capture file counts (Athena queries don't see these for sleep_flow).
#   3. Writes a parquet partition to s3://${rollup_bucket}/rollup/patient_daily/dt=YYYY-MM-DD/.
#   4. Calls glue:CreatePartition to register the new partition.
#
# The Python module is intentionally simple — pure boto3 + python (no pandas
# in the Lambda layer; we use pyarrow which is a smaller dep, packed via a
# Layer). For now the Lambda is provisioned but DEPLOYED with a placeholder
# code zip; first real deployment will need a container image or proper
# layer with pyarrow. This is documented in the module README.

data "archive_file" "rollup_lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/lambda_src"
  output_path = "${path.module}/build/refresh_daily_rollup.zip"
}

resource "aws_lambda_function" "rollup" {
  function_name = "${var.name_prefix}-refresh-daily-rollup"
  description   = "Daily patient_daily rollup refresh: queries Athena + lists S3, writes parquet partition."
  role          = aws_iam_role.rollup_lambda.arn
  runtime       = "python3.12"
  handler       = "refresh_daily_rollup.handler"
  timeout       = 600
  memory_size   = 2048

  filename         = data.archive_file.rollup_lambda_zip.output_path
  source_code_hash = data.archive_file.rollup_lambda_zip.output_base64sha256

  # AWS SDK for Pandas Lambda layer — provides pandas, pyarrow, boto3, etc.
  # Required for writing Parquet output to s3 with df.to_parquet(...).
  # The official AWS-published account is 336392948345; pin a specific version.
  layers = [
    "arn:aws:lambda:${data.aws_region.current.name}:336392948345:layer:AWSSDKPandas-Python312:24",
  ]

  environment {
    variables = {
      APP_EVENTS_BUCKET     = var.app_events_bucket
      ROLLUP_BUCKET         = var.rollup_bucket
      ATHENA_RESULTS_BUCKET = var.athena_results_bucket
      ATHENA_WORKGROUP      = var.athena_workgroup
      AGENT_GLUE_DATABASE   = var.agent_glue_database
    }
  }

  tags = var.tags
}

data "aws_region" "current" {}

resource "aws_cloudwatch_event_rule" "rollup_daily" {
  name                = "${var.name_prefix}-rollup-daily"
  description         = "Trigger refresh_daily_rollup Lambda once per day."
  schedule_expression = var.schedule_expression
  tags                = var.tags
}

resource "aws_cloudwatch_event_target" "rollup_daily" {
  rule      = aws_cloudwatch_event_rule.rollup_daily.name
  target_id = "rollup-lambda"
  arn       = aws_lambda_function.rollup.arn
}

resource "aws_lambda_permission" "rollup_daily_invoke" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.rollup.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.rollup_daily.arn
}
