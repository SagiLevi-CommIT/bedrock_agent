terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

# --- Container registry (its own repo; SHA-tagged images, no :latest) --------
resource "aws_ecr_repository" "this" {
  name                 = "${var.name_prefix}-backend"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# --- Execution role (ECR pull + logs) ----------------------------------------
data "aws_iam_policy_document" "assume_ecs_tasks" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "exec" {
  name               = "${var.name_prefix}-exec"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs_tasks.json
}

resource "aws_iam_role_policy_attachment" "exec_managed" {
  role       = aws_iam_role.exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# --- Task role (LEAST-PRIVILEGE: read-only data; write only to artifacts/*) --
resource "aws_iam_role" "task" {
  name               = "${var.name_prefix}-task"
  assume_role_policy = data.aws_iam_policy_document.assume_ecs_tasks.json
}

data "aws_iam_policy_document" "task" {
  # Read-only on data buckets (objects + listing).
  statement {
    sid       = "DataReadObjects"
    actions   = ["s3:GetObject"]
    resources = [for b in var.data_bucket_arns : "${b}/*"]
  }
  statement {
    sid       = "DataListBuckets"
    actions   = ["s3:ListBucket"]
    resources = var.data_bucket_arns
  }

  # Athena query results bucket (read + write — Athena writes results here).
  statement {
    sid       = "AthenaResults"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation"]
    resources = [var.athena_results_bucket_arn, "${var.athena_results_bucket_arn}/*"]
  }

  # Artifacts: WRITE only under artifacts/* (plus read for presign/serve).
  statement {
    sid       = "ArtifactsWrite"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${var.artifacts_bucket_arn}/artifacts/*"]
  }

  # Athena + Glue catalog (read-only).
  statement {
    sid = "Athena"
    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:StopQueryExecution",
      "athena:GetWorkGroup",
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
    ]
    resources = ["*"]
  }

  # Shared patient_id->UUID cache (RW) for the resolver path.
  statement {
    sid       = "PatientIdMap"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"]
    resources = [var.patient_id_map_table_arn]
  }

  # Patient-resolver token (+ any future secrets, e.g. cardiolyse).
  statement {
    sid       = "Secrets"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = concat([var.token_secret_arn], var.extra_secret_arns)
  }
}

resource "aws_iam_role_policy" "task" {
  name   = "${var.name_prefix}-task-policy"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

# --- API bearer token (agent -> tool-api auth) --------------------------------
# Generated here, stored in Secrets Manager under a DETERMINISTIC name (passed
# in as a variable so the agent's env/IAM can reference it without a module
# dependency cycle: tool_api consumes the ecs cluster, so ecs/iam must not
# consume tool_api outputs). Injected into the container as TOOL_API_TOKEN
# (the app enforces bearer auth on /v1/* when it is set); the agent task reads
# the same secret at runtime via TOOL_API_TOKEN_SECRET_NAME.
resource "random_password" "api_token" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "api_token" {
  name        = var.api_token_secret_name
  description = "Bearer token for the Tool API (TOOL_API_TOKEN). Read by the tool-api container (injected) and the agent task (runtime)."
  # Staging: allow immediate re-create on disable/enable (no 7-day name lock).
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "api_token" {
  secret_id     = aws_secretsmanager_secret.api_token.id
  secret_string = random_password.api_token.result
}

# Container `secrets` injection is done by the EXECUTION role.
data "aws_iam_policy_document" "exec_secrets" {
  statement {
    sid       = "ApiTokenInject"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.api_token.arn]
  }
}

resource "aws_iam_role_policy" "exec_secrets" {
  name   = "${var.name_prefix}-exec-secrets"
  role   = aws_iam_role.exec.id
  policy = data.aws_iam_policy_document.exec_secrets.json
}

# --- CodeBuild: builds the tool image (no local Docker on operator machines) --
# Mirrors modules/codebuild but for the TOOL repo's Dockerfile.api: the operator
# zips the tool repo source to <source_bucket>/tool-api-source.zip and starts a
# build with IMAGE_TAG=<tool-repo-short-sha> (see DEPLOY.md).
resource "aws_cloudwatch_log_group" "codebuild" {
  name              = "/aws/codebuild/${var.name_prefix}-image-build"
  retention_in_days = 14
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

resource "aws_iam_role_policy" "codebuild" {
  name = "${var.name_prefix}-codebuild-policy"
  role = aws_iam_role.codebuild.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
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
        Resource = aws_ecr_repository.this.arn
      },
      {
        Sid      = "S3Source"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion", "s3:ListBucket"]
        Resource = [var.source_bucket_arn, "${var.source_bucket_arn}/*"]
      },
    ]
  })
}

resource "aws_codebuild_project" "image" {
  name          = "${var.name_prefix}-image-build"
  description   = "Builds the tool-api container image (Dockerfile.api from the tool repo) and pushes to ECR. Triggered manually with IMAGE_TAG."
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
    type     = "S3"
    location = "${var.source_bucket_name}/tool-api-source.zip"
    # S3 source has no git SHA -> IMAGE_TAG must be passed via
    # --environment-variables-override at start-build time.
    buildspec = <<-EOT
      version: 0.2
      phases:
        pre_build:
          commands:
            - test -n "$IMAGE_TAG" || { echo "IMAGE_TAG env var is required"; exit 1; }
            - aws ecr get-login-password --region ${var.region} | docker login --username AWS --password-stdin ${split("/", aws_ecr_repository.this.repository_url)[0]}
        build:
          commands:
            - cd $CODEBUILD_SRC_DIR
            - docker build -f Dockerfile.api -t ${aws_ecr_repository.this.repository_url}:$IMAGE_TAG .
        post_build:
          commands:
            - docker push ${aws_ecr_repository.this.repository_url}:$IMAGE_TAG
    EOT
  }

  logs_config {
    cloudwatch_logs {
      group_name = aws_cloudwatch_log_group.codebuild.name
    }
  }
}

# --- Private service discovery (agent -> tool-api) ---------------------------
# The agent task CANNOT reach the public ALB (WAF default-blocks non-office IPs,
# and the NAT egress IP is not an office CIDR), so agent->tool-api goes over the
# private network via Cloud Map DNS: http://tool-api.<namespace>:<port>.
resource "aws_service_discovery_private_dns_namespace" "this" {
  name = var.service_discovery_namespace
  vpc  = var.vpc_id
}

resource "aws_service_discovery_service" "this" {
  name = "tool-api"

  dns_config {
    namespace_id   = aws_service_discovery_private_dns_namespace.this.id
    routing_policy = "MULTIVALUE"

    dns_records {
      type = "A"
      ttl  = 10
    }
  }

  health_check_custom_config {
    failure_threshold = 1
  }
}

# NOTE: the task-to-task ingress rule (agent -> tool-api, same ECS SG) lives
# INLINE in modules/alb's aws_security_group.ecs. It was originally a
# standalone aws_security_group_rule here, but that SG manages rules inline,
# so the next update of the SG resource silently wiped the standalone rule
# (live regression, 2026-06-11). Do not re-add it here.

# --- ALB target group + path-routed listener rule (/tool-api/*) --------------
resource "aws_lb_target_group" "this" {
  name        = substr("${var.name_prefix}-tg", 0, 32)
  port        = var.container_port
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = var.vpc_id

  health_check {
    enabled             = true
    healthy_threshold   = 2
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 15
    path                = "/health"
    matcher             = "200"
  }

  deregistration_delay = 30
}

resource "aws_lb_listener_rule" "tool_api" {
  listener_arn = var.alb_listener_arn
  priority     = var.listener_rule_priority

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }

  condition {
    path_pattern {
      values = ["/tool-api", "/tool-api/*"]
    }
  }
}

# --- Task definition + service (in the existing cluster) ---------------------
resource "aws_ecs_task_definition" "this" {
  family                   = "${var.name_prefix}-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.exec.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name      = "tool-api"
      image     = "${aws_ecr_repository.this.repository_url}:${var.image_tag}"
      essential = true

      # Routing: the app serves /health + /v1/* at root for INTERNAL calls
      # (agent via Cloud Map DNS, no prefix), and TOOL_API_ROOT_PATH makes the
      # app ALSO accept /tool-api/* for BROWSER calls via the ALB rule (ALBs
      # cannot strip path prefixes; the app's middleware strips it instead).
      portMappings = [
        { containerPort = var.container_port, hostPort = var.container_port, protocol = "tcp" }
      ]

      environment = [
        for k, v in merge({ TOOL_API_ROOT_PATH = "/tool-api" }, var.env) :
        { name = k, value = v }
      ]

      secrets = [
        { name = "TOOL_API_TOKEN", valueFrom = aws_secretsmanager_secret.api_token.arn }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = var.log_group_name
          awslogs-region        = var.region
          awslogs-stream-prefix = "tool-api"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "python -c 'import urllib.request; urllib.request.urlopen(\"http://localhost:${var.container_port}/health\").read()' || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 20
      }
    }
  ])
}

resource "aws_ecs_service" "this" {
  name                               = "${var.name_prefix}-svc"
  cluster                            = var.cluster_name
  task_definition                    = aws_ecs_task_definition.this.arn
  desired_count                      = var.min_tasks
  launch_type                        = "FARGATE"
  platform_version                   = "LATEST"
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [var.ecs_security_group_id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.this.arn
    container_name   = "tool-api"
    container_port   = var.container_port
  }

  service_registries {
    registry_arn = aws_service_discovery_service.this.arn
  }

  lifecycle {
    ignore_changes = [desired_count]
  }
}

resource "aws_appautoscaling_target" "this" {
  max_capacity       = var.max_tasks
  min_capacity       = var.min_tasks
  resource_id        = "service/${var.cluster_name}/${aws_ecs_service.this.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "cpu" {
  name               = "${var.name_prefix}-cpu-target"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.this.resource_id
  scalable_dimension = aws_appautoscaling_target.this.scalable_dimension
  service_namespace  = aws_appautoscaling_target.this.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value = 60.0
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    scale_in_cooldown  = 120
    scale_out_cooldown = 60
  }
}
