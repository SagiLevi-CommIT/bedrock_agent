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
  account_id  = data.aws_caller_identity.current.account_id

  bedrock_model_arns = [
    "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.*",
    "arn:aws:bedrock:${var.aws_region}:${var.expected_account_id}:inference-profile/eu.anthropic.*",
  ]

  cardiacsense_data_bucket_arns = [
    "arn:aws:s3:::735555370207-app-events",
    "arn:aws:s3:::735555370207-migrated--data",
    "arn:aws:s3:::735555370207-datasets-versioning",
  ]

  ecr_registry = "${local.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"
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

module "data" {
  source      = "../../modules/data"
  name_prefix = local.name_prefix
  account_id  = local.account_id
}

module "iam" {
  source                    = "../../modules/iam"
  name_prefix               = local.name_prefix
  bedrock_model_arns        = local.bedrock_model_arns
  log_group_arn             = module.observability.log_group_arn
  data_bucket_arns          = local.cardiacsense_data_bucket_arns
  athena_results_bucket_arn = module.data.athena_results_bucket_arn
  output_bucket_arn         = module.data.output_bucket_arn
  dynamodb_table_arns = [
    module.data.sessions_table_arn,
    module.data.cost_table_arn,
  ]
  secret_arns = []
}

module "alb" {
  source            = "../../modules/alb"
  name_prefix       = local.name_prefix
  vpc_id            = module.vpc.vpc_id
  public_subnet_ids = module.vpc.public_subnet_ids
  container_port    = 8000
  certificate_arn   = "" # phase-9 swap to ACM cert ARN
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
  env = {
    AWS_REGION              = var.aws_region
    BEDROCK_MODEL_ID        = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
    BEDROCK_FAST_MODEL_ID   = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
    ATHENA_WORKGROUP        = "primary"
    ATHENA_DEFAULT_DATABASE = "migrated_data"
    ATHENA_RESULTS_BUCKET   = module.data.athena_results_bucket_name
    SESSIONS_TABLE          = module.data.sessions_table_name
    COST_TABLE              = module.data.cost_table_name
    OUTPUT_BUCKET           = module.data.output_bucket_name
    LOG_LEVEL               = "INFO"
    ALLOW_WRITES            = "false"
  }
}

module "codebuild" {
  source             = "../../modules/codebuild"
  name_prefix        = local.name_prefix
  aws_region         = var.aws_region
  ecr_repository_arn = module.ecr.repository_arn
  ecr_repository_url = module.ecr.repository_url
  ecr_registry       = local.ecr_registry
  source_bucket_name = module.data.codebuild_source_bucket_name
  source_bucket_arn  = module.data.codebuild_source_bucket_arn
  passrole_arns = [
    module.iam.exec_role_arn,
    module.iam.task_role_arn,
  ]
}
