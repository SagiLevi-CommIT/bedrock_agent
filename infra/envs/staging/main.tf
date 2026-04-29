provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile

  allowed_account_ids = [var.expected_account_id]

  default_tags {
    tags = {
      Project     = var.project
      Environment = var.environment
      Owner       = var.owner
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  name_prefix = "${var.project}-${var.environment}"

  # Bedrock ARNs scoped to the EU geo inference profile and EU foundation models.
  bedrock_model_arns = [
    "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.*",
    "arn:aws:bedrock:${var.aws_region}:${var.expected_account_id}:inference-profile/eu.anthropic.*",
  ]

  task_env = {
    AWS_REGION              = var.aws_region
    BEDROCK_MODEL_ID        = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
    ATHENA_WORKGROUP        = "primary"
    ATHENA_DEFAULT_DATABASE = "migrated_data"
    LOG_LEVEL               = "INFO"
    ALLOW_WRITES            = "false"
  }
}

module "vpc" {
  source      = "../../modules/vpc"
  name_prefix = local.name_prefix
  vpc_cidr    = var.vpc_cidr
  region      = var.aws_region
}

module "ecr" {
  source      = "../../modules/ecr"
  name_prefix = local.name_prefix
}

module "observability" {
  source             = "../../modules/observability"
  name_prefix        = local.name_prefix
  project            = var.project
  log_retention_days = var.log_retention_days
  alarm_email        = var.alarm_email
  monthly_budget_usd = var.monthly_budget_usd
}

module "iam" {
  source              = "../../modules/iam"
  name_prefix         = local.name_prefix
  bedrock_model_arns  = local.bedrock_model_arns
  log_group_arn       = module.observability.log_group_arn
  data_bucket_arns    = []
  athena_results_bucket_arn = ""
  output_bucket_arn   = ""
  dynamodb_table_arns = []
  secret_arns         = []
}

module "alb" {
  source            = "../../modules/alb"
  name_prefix       = local.name_prefix
  vpc_id            = module.vpc.vpc_id
  public_subnet_ids = module.vpc.public_subnet_ids
  container_port    = 8000
  certificate_arn   = "" # phase-8 swap to ACM cert ARN
}

module "waf" {
  source              = "../../modules/waf"
  name_prefix         = local.name_prefix
  alb_arn             = module.alb.alb_arn
  office_cidrs        = var.office_cidrs
  rate_limit_per_5min = 1000
}

module "ecs" {
  source                = "../../modules/ecs"
  name_prefix           = local.name_prefix
  region                = var.aws_region
  private_subnet_ids    = module.vpc.private_subnet_ids
  ecs_security_group_id = module.alb.ecs_security_group_id
  target_group_arn      = module.alb.target_group_arn
  image_repository_url  = module.ecr.repository_url
  image_tag             = var.image_tag
  container_port        = 8000
  task_cpu              = var.task_cpu
  task_memory           = var.task_memory
  min_tasks             = var.service_min_tasks
  max_tasks             = var.service_max_tasks
  exec_role_arn         = module.iam.exec_role_arn
  task_role_arn         = module.iam.task_role_arn
  log_group_name        = module.observability.log_group_name
  env                   = local.task_env
}

# Subsequent phases append:
# module "data"           { ... }   # DDB sessions + cost-rollup, S3 output bucket
# module "secrets"        { ... }   # Secrets Manager + SSM
# module "route53"        { ... }   # public DNS record + ACM cert
# module "bedrock_access" { ... }   # IAM grants for additional model ARNs as needed
