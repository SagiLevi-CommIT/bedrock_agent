variable "name_prefix" {
  type        = string
  description = "e.g. claude-aws-agent-staging-tool-api"
}

variable "region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "ecs_security_group_id" {
  type        = string
  description = "Reuse the agent ALB's ECS SG (already allows ALB -> container_port)."
}

variable "cluster_name" {
  type        = string
  description = "Existing ECS cluster to run in (reuse the agent cluster)."
}

variable "alb_listener_arn" {
  type        = string
  description = "Active ALB listener ARN to attach the /tool-api/* rule to."
}

variable "listener_rule_priority" {
  type    = number
  default = 100
}

variable "service_discovery_namespace" {
  type        = string
  default     = "cs-internal"
  description = "Cloud Map private DNS namespace for agent -> tool-api calls (DNS: tool-api.<namespace>)."
}

variable "image_tag" {
  type        = string
  description = "Short git SHA of the tool-api image (no :latest)."
}

variable "container_port" {
  type    = number
  default = 8000
}

variable "task_cpu" {
  type    = number
  default = 512
}

variable "task_memory" {
  type    = number
  default = 1024
}

variable "min_tasks" {
  type    = number
  default = 1
}

variable "max_tasks" {
  type    = number
  default = 2
}

variable "log_group_name" {
  type        = string
  description = "Shared CloudWatch log group (stream prefix tool-api)."
}

# Least-privilege task-role inputs (read-only data; write only to artifacts).
variable "data_bucket_arns" {
  type        = list(string)
  description = "Data buckets the task may READ (app-events, migrated--data, ...)."
}

variable "athena_results_bucket_arn" {
  type = string
}

variable "artifacts_bucket_arn" {
  type        = string
  description = "Output bucket; task may write ONLY under artifacts/*."
}

variable "reports_bucket_arn" {
  type        = string
  default     = ""
  description = "Patient-reports bucket ARN (read + Glacier RestoreObject for PDF reports). Empty disables the statement."
}

variable "patient_id_map_table_arn" {
  type        = string
  description = "Shared patient_id->UUID DynamoDB cache (RW)."
}

variable "token_secret_arn" {
  type        = string
  description = "Secrets Manager ARN for INTERNAL_TOKEN (patient resolver)."
}

variable "api_token_secret_name" {
  type        = string
  description = "Deterministic Secrets Manager name for the generated /tool-api bearer token (the agent references the same name without a module dependency)."
}

variable "source_bucket_name" {
  type        = string
  description = "Shared CodeBuild source bucket; the tool image builds from <bucket>/tool-api-source.zip."
}

variable "source_bucket_arn" {
  type = string
}

variable "extra_secret_arns" {
  type        = list(string)
  default     = []
  description = "Additional secret ARNs (e.g. tool-api bearer, cardiolyse) when provisioned."
}

variable "env" {
  type        = map(string)
  default     = {}
  description = "Non-secret container env (TOOL_API_CONFIG, TOOL_API_ARTIFACTS_BUCKET, ...)."
}
