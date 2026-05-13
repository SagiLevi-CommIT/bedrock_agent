variable "aws_region" {
  type    = string
  default = "eu-central-1"
}

variable "aws_profile" {
  type        = string
  description = "Local AWS profile name. Leave null in CI (OIDC role assumed by GitHub Actions)."
  default     = null
}

variable "expected_account_id" {
  type        = string
  description = "Guardrail: terraform fails if the active credentials are NOT this account."
}

variable "project" {
  type    = string
  default = "claude-aws-agent"
}

variable "environment" {
  type    = string
  default = "staging"
}

variable "owner" {
  type    = string
  default = "data-platform"
}

variable "alarm_email" {
  type        = string
  description = "Email for SNS alarms and AWS Budget alerts."
}

variable "office_cidrs" {
  type        = list(string)
  description = "CIDRs allowed to reach the ALB. Provided by IT."
  default     = []
}

variable "image_tag" {
  type        = string
  description = "ECR image tag to deploy. Set by CI to the short git SHA."
}

variable "dns_zone_name" {
  type        = string
  description = "Route53 hosted zone (e.g. agent.staging.example.com). Empty string disables Route53/ACM creation in this stack."
  default     = ""
}

variable "subdomain" {
  type    = string
  default = "agent"
}

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/20"
}

variable "task_cpu" {
  type    = number
  default = 512
}

variable "task_memory" {
  type    = number
  default = 1024
}

variable "service_min_tasks" {
  type    = number
  default = 1
}

variable "service_max_tasks" {
  type    = number
  default = 4
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "monthly_budget_usd" {
  type    = number
  default = 200
}

variable "patient_resolver_url" {
  type        = string
  description = "Internal Patients API URL for resolve_patient_uuid."
  default     = "https://staging.cardiacsense-cloud.com/app/patient/get-patient"
}

variable "patient_resolver_token_secret_name" {
  type        = string
  description = "Secrets Manager secret id/ARN name for bearer token (not the value)."
  default     = "INTERNAL_TOKEN"
}

variable "athena_max_scan_gb_default" {
  type        = number
  description = "Default max estimated Athena scan size in GB before BLOCKED."
  default     = 1.0
}

variable "event_sessions_table" {
  type        = string
  description = "Fully qualified Athena table for session/event analytics (if used)."
  default     = "migrated_data.event_sessions"
}
