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

  # IAM allow-list for Bedrock invocations.
  #
  # Anthropic models are listed but currently **blocked at the org SCP**
  # (verified 2026-04-29 — `arn:aws:organizations::071204572266:policy/...
  # /service_control_policy/p-lwuwinuh` denies any anthropic.* foundation-
  # model invocation). The IAM grant is kept so that the moment the SCP is
  # updated, no code change is needed.
  #
  # Non-Anthropic providers (Mistral, GLM, Qwen, Amazon, OpenAI-OSS) are not
  # blocked by the SCP. We grant them too so the agent can fall back to a
  # working chat model.
  bedrock_model_arns = [
    "arn:aws:bedrock:*::foundation-model/anthropic.*",
    "arn:aws:bedrock:*::foundation-model/mistral.*",
    "arn:aws:bedrock:*::foundation-model/amazon.*",
    "arn:aws:bedrock:*::foundation-model/cohere.*",
    "arn:aws:bedrock:*::foundation-model/openai.*",
    "arn:aws:bedrock:*::foundation-model/qwen.*",
    "arn:aws:bedrock:*::foundation-model/zai.*",
    "arn:aws:bedrock:${var.aws_region}:${var.expected_account_id}:inference-profile/eu.anthropic.*",
    "arn:aws:bedrock:${var.aws_region}:${var.expected_account_id}:inference-profile/global.anthropic.*",
  ]

  cardiacsense_data_bucket_arns = [
    "arn:aws:s3:::735555370207-app-events",
    "arn:aws:s3:::735555370207-migrated--data",
    "arn:aws:s3:::735555370207-datasets-versioning",
  ]

  ecr_registry = "${local.account_id}.dkr.ecr.${var.aws_region}.amazonaws.com"

  # Private Cloud Map DNS for agent -> tool-api calls (no ALB/WAF in the path --
  # the WAF default-blocks non-office IPs, so the public ALB route is unusable
  # for service-to-service traffic). Must match the tool_api module's
  # service_discovery_namespace default. Empty URL when the tool-api is disabled
  # (the agent's data-tool wrappers then return a clean "not configured" error).
  tool_api_namespace    = "cs-internal"
  tool_api_internal_url = var.enable_tool_api ? "http://tool-api.${local.tool_api_namespace}:8000" : ""

  # Bearer token for agent -> tool-api auth. The secret is CREATED inside the
  # count-gated tool_api module under this deterministic name; the agent's env
  # and IAM reference the name/ARN-pattern directly (not module outputs) because
  # tool_api consumes the ecs cluster -- a module-output reference here would be
  # a dependency cycle. Empty name when disabled -> the agent sends no token.
  tool_api_token_secret_name = "${local.name_prefix}-tool-api-token"
  tool_api_token_secret_arn_pattern = (
    "arn:aws:secretsmanager:${var.aws_region}:${var.expected_account_id}:secret:${local.name_prefix}-tool-api-token-*"
  )
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

module "indexing" {
  source                = "../../modules/indexing"
  name_prefix           = local.name_prefix
  app_events_bucket     = "735555370207-app-events"
  rollup_bucket         = module.data.output_bucket_name
  athena_results_bucket = module.data.athena_results_bucket_name
  athena_workgroup      = "primary"
  agent_glue_database   = "bedrock_agent"
}

data "aws_secretsmanager_secret" "internal_token" {
  name = var.patient_resolver_token_secret_name
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
    module.data.patient_id_map_table_arn,
  ]
  secret_arns = []
  task_secret_arns = concat(
    [data.aws_secretsmanager_secret.internal_token.arn],
    # ARN pattern (not a module output) -- see the locals note on the cycle.
    var.enable_tool_api ? [local.tool_api_token_secret_arn_pattern] : [],
  )
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
    AWS_REGION = var.aws_region
    # NOTE: An org-level SCP currently denies bedrock:InvokeModel for ALL
    # `anthropic.*` models in this account, regardless of region/profile
    # (verified 2026-04-29 against eu, global, and direct profiles for
    # claude-sonnet-4-5, haiku-4-5, sonnet-4 — every attempt fails with
    # `explicit deny in a service control policy
    # arn:aws:organizations::071204572266:policy/o-ld9q2iv86w/service_control_policy/p-lwuwinuh`).
    # Until the SCP is updated to allow Anthropic in eu-central-1, we use
    # Mistral devstral-2 as a placeholder so the chat path can be exercised
    # end-to-end. Restoring Claude is a one-line change here.
    BEDROCK_MODEL_ID                   = "mistral.devstral-2-123b"
    BEDROCK_FAST_MODEL_ID              = "mistral.devstral-2-123b"
    ATHENA_WORKGROUP                   = "primary"
    ATHENA_DEFAULT_DATABASE            = "migrated_data"
    ATHENA_RESULTS_BUCKET              = module.data.athena_results_bucket_name
    SESSIONS_TABLE                     = module.data.sessions_table_name
    COST_TABLE                         = module.data.cost_table_name
    OUTPUT_BUCKET                      = module.data.output_bucket_name
    LOG_LEVEL                          = "INFO"
    ALLOW_WRITES                       = "false"
    GET_PATIENT_URL                    = var.patient_resolver_url
    PATIENT_RESOLVER_URL               = var.patient_resolver_url
    INTERNAL_TOKEN_SECRET_NAME         = var.patient_resolver_token_secret_name
    PATIENT_RESOLVER_TOKEN_SECRET_NAME = var.patient_resolver_token_secret_name
    PATIENT_ID_MAP_TABLE               = module.data.patient_id_map_table_name
    PATIENT_ID_UUID_MAP_TABLE          = module.data.patient_id_map_table_name
    EVENTS_BUCKET                      = "735555370207-app-events"
    EVENT_SESSIONS_TABLE               = var.event_sessions_table
    ATHENA_MAX_SCAN_GB_DEFAULT         = tostring(var.athena_max_scan_gb_default)
    # Deterministic data tool (empty until enable_tool_api=true -> the 11
    # data-tool wrappers fail cleanly and the prompt routes to native tools).
    TOOL_API_BASE_URL          = local.tool_api_internal_url
    TOOL_API_TOKEN_SECRET_NAME = var.enable_tool_api ? local.tool_api_token_secret_name : ""
  }
}

# Deterministic Tool API (the S3 data/visualization tool) -- a second service in
# the SAME cluster behind the SAME ALB (path /tool-api/*), reusing VPC/SG/logs/
# buckets so we don't pay twice. DISABLED by default (count=0): the live plan is
# unchanged until `enable_tool_api=true` + `tool_api_image_tag` are set. See the
# module README + docs/E2E_VALIDATION_AND_INTELLIGENCE.md for the validated
# config requirements (resolver, discovery.mode=auto, large-artifact handling).
module "tool_api" {
  count  = var.enable_tool_api ? 1 : 0
  source = "../../modules/tool_api"

  name_prefix            = "${local.name_prefix}-tool-api"
  region                 = var.aws_region
  vpc_id                 = module.vpc.vpc_id
  private_subnet_ids     = module.vpc.private_subnet_ids
  ecs_security_group_id  = module.alb.ecs_security_group_id
  cluster_name           = module.ecs.cluster_name
  alb_listener_arn       = module.alb.active_listener_arn
  listener_rule_priority = 100
  image_tag              = var.tool_api_image_tag
  log_group_name         = module.observability.log_group_name

  data_bucket_arns          = local.cardiacsense_data_bucket_arns
  athena_results_bucket_arn = module.data.athena_results_bucket_arn
  artifacts_bucket_arn      = module.data.output_bucket_arn
  patient_id_map_table_arn  = module.data.patient_id_map_table_arn
  token_secret_arn          = data.aws_secretsmanager_secret.internal_token.arn
  api_token_secret_name     = local.tool_api_token_secret_name

  env = {
    AWS_REGION                = var.aws_region
    TOOL_API_ARTIFACTS_BUCKET = module.data.output_bucket_name
    # The tool image bakes config.staging.json (empty keys -> task role,
    # account_id=735555370207, patient_resolver.get_patient_url set,
    # discovery.mode=auto). Validated: this enables the migrated fast-path.
    TOOL_API_CONFIG      = "/app/config.staging.json"
    TOOL_API_JOBS_INLINE = "false"
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
