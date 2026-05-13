terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

# ECS task execution role: pull image from ECR, write logs.
resource "aws_iam_role" "exec" {
  name = "${var.name_prefix}-exec-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "exec_managed" {
  role       = aws_iam_role.exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Optional: read secrets at task start (for env injection from Secrets Manager).
resource "aws_iam_role_policy" "exec_secrets_read" {
  count = length(var.secret_arns) > 0 ? 1 : 0
  name  = "${var.name_prefix}-exec-secrets"
  role  = aws_iam_role.exec.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue"]
      Resource = var.secret_arns
    }]
  })
}

# Application task role: read-only data, Bedrock Converse, scoped writes.
resource "aws_iam_role" "task" {
  name = "${var.name_prefix}-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "task_secrets_read" {
  count = length(var.task_secret_arns) > 0 ? 1 : 0
  name  = "${var.name_prefix}-task-secrets-read"
  role  = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
      Resource = var.task_secret_arns
    }]
  })
}

resource "aws_iam_role_policy" "task_bedrock" {
  name = "${var.name_prefix}-task-bedrock"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "InvokeAndConverse"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:Converse", "bedrock:ConverseStream"]
        Resource = var.bedrock_model_arns
      }
    ]
  })
}

resource "aws_iam_role_policy" "task_athena" {
  name = "${var.name_prefix}-task-athena"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "athena:StartQueryExecution",
          "athena:StopQueryExecution",
          "athena:GetQueryExecution",
          "athena:GetQueryResults",
          "athena:GetQueryResultsStream",
          "athena:GetWorkGroup",
          "athena:ListQueryExecutions",
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "task_glue_readonly" {
  name = "${var.name_prefix}-task-glue-ro"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "glue:GetDatabase",
        "glue:GetDatabases",
        "glue:GetTable",
        "glue:GetTables",
        "glue:GetPartition",
        "glue:GetPartitions",
        "glue:GetPartitionStatistics",
        "glue:BatchGetPartition",
        "glue:SearchTables",
      ]
      Resource = "*"
    }]
  })
}

resource "aws_iam_role_policy" "task_s3_data_readonly" {
  count = length(var.data_bucket_arns) > 0 ? 1 : 0
  name  = "${var.name_prefix}-task-s3-data-ro"
  role  = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ListBuckets"
        Effect   = "Allow"
        Action   = ["s3:ListBucket", "s3:GetBucketLocation"]
        Resource = var.data_bucket_arns
      },
      {
        Sid      = "GetObjects"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = [for arn in var.data_bucket_arns : "${arn}/*"]
      }
    ]
  })
}

resource "aws_iam_role_policy" "task_s3_athena_results" {
  name = "${var.name_prefix}-task-s3-athena-results"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation"]
      Resource = [
        var.athena_results_bucket_arn,
        "${var.athena_results_bucket_arn}/*",
      ]
    }]
  })
}

resource "aws_iam_role_policy" "task_s3_output_rw" {
  name = "${var.name_prefix}-task-s3-output-rw"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
      Resource = [
        var.output_bucket_arn,
        "${var.output_bucket_arn}/*",
      ]
    }]
  })
}

resource "aws_iam_role_policy" "task_logs" {
  name = "${var.name_prefix}-task-logs"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "logs:CreateLogStream",
        "logs:PutLogEvents",
      ]
      Resource = "${var.log_group_arn}:*"
    }]
  })
}

resource "aws_iam_role_policy" "task_sts" {
  name = "${var.name_prefix}-task-sts"
  role = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sts:GetCallerIdentity"]
      Resource = "*"
    }]
  })
}

# DynamoDB read-write on agent's own tables only (sessions + cost rollup).
resource "aws_iam_role_policy" "task_ddb" {
  count = length(var.dynamodb_table_arns) > 0 ? 1 : 0
  name  = "${var.name_prefix}-task-ddb"
  role  = aws_iam_role.task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:Query",
        "dynamodb:BatchGetItem",
        "dynamodb:BatchWriteItem",
      ]
      Resource = var.dynamodb_table_arns
    }]
  })
}
