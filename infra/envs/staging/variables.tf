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
