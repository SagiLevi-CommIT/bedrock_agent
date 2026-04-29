terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

resource "aws_iam_role" "codebuild" {
  name = "${var.name_prefix}-codebuild-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codebuild.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_cloudwatch_log_group" "codebuild" {
  name              = "/aws/codebuild/${var.name_prefix}-image-build"
  retention_in_days = 14
}

resource "aws_iam_role_policy" "codebuild" {
  name = "${var.name_prefix}-codebuild-policy"
  role = aws_iam_role.codebuild.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Logs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "${aws_cloudwatch_log_group.codebuild.arn}:*"
      },
      {
        Sid      = "EcrAuth"
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Sid    = "EcrPushPull"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:CompleteLayerUpload",
          "ecr:GetDownloadUrlForLayer",
          "ecr:InitiateLayerUpload",
          "ecr:PutImage",
          "ecr:UploadLayerPart",
          "ecr:BatchGetImage",
          "ecr:DescribeImages",
          "ecr:DescribeRepositories",
        ]
        Resource = var.ecr_repository_arn
      },
      {
        Sid    = "S3Source"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:GetObjectVersion",
          "s3:ListBucket",
        ]
        Resource = [
          var.source_bucket_arn,
          "${var.source_bucket_arn}/*",
        ]
      },
      {
        Sid    = "EcsUpdate"
        Effect = "Allow"
        Action = [
          "ecs:DescribeServices",
          "ecs:UpdateService",
          "ecs:RegisterTaskDefinition",
          "ecs:DescribeTaskDefinition",
        ]
        Resource = "*"
      },
      {
        Sid      = "PassRole"
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = var.passrole_arns
      }
    ]
  })
}

locals {
  buildspec = <<-EOT
    version: 0.2
    phases:
      pre_build:
        commands:
          - echo "Logging in to ECR ${var.aws_region}..."
          - aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${var.ecr_registry}
          - export IMAGE_TAG=$${IMAGE_TAG:-$(echo $CODEBUILD_RESOLVED_SOURCE_VERSION | cut -c1-8)}
          - echo "Image tag will be $IMAGE_TAG"
      build:
        commands:
          - cd $CODEBUILD_SRC_DIR
          - docker build -f app/Dockerfile -t ${var.ecr_repository_url}:$IMAGE_TAG .
      post_build:
        commands:
          - docker push ${var.ecr_repository_url}:$IMAGE_TAG
          - printf '{"imageTag":"%s"}' "$IMAGE_TAG" > image_tag.json
    artifacts:
      files:
        - image_tag.json
  EOT
}

resource "aws_codebuild_project" "image" {
  name          = "${var.name_prefix}-image-build"
  description   = "Builds the agent container image and pushes to ECR. Triggered manually."
  service_role  = aws_iam_role.codebuild.arn
  build_timeout = 20

  artifacts {
    type = "NO_ARTIFACTS"
  }

  environment {
    type            = "LINUX_CONTAINER"
    compute_type    = "BUILD_GENERAL1_SMALL"
    image           = "aws/codebuild/standard:7.0"
    privileged_mode = true # required for docker
  }

  source {
    type      = "S3"
    location  = "${var.source_bucket_name}/source.zip"
    buildspec = local.buildspec
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.codebuild.name
    }
  }
}
