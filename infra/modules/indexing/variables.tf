variable "name_prefix" {
  description = "Resource name prefix (e.g. claude-aws-agent-staging)."
  type        = string
}

variable "app_events_bucket" {
  description = "Source bucket holding rearrangement / post-computation files."
  type        = string
  default     = "735555370207-app-events"
}

variable "rollup_bucket" {
  description = "Output bucket for parquet rollup datasets (the agent's own output bucket is fine)."
  type        = string
}

variable "athena_results_bucket" {
  description = "Athena workgroup result location bucket — Lambda writes its CTAS output through here."
  type        = string
}

variable "athena_workgroup" {
  description = "Athena workgroup the Lambda submits queries against."
  type        = string
  default     = "primary"
}

variable "agent_glue_database" {
  description = "Glue database that owns the agent's own indexed tables (patient_daily, sleep_flow_rearrangement_idx, ...)."
  type        = string
  default     = "bedrock_agent"
}

variable "schedule_expression" {
  description = "EventBridge cron for the daily refresh Lambda. Default 02:00 UTC."
  type        = string
  default     = "cron(0 2 * * ? *)"
}

variable "tags" {
  description = "Tags applied to created resources."
  type        = map(string)
  default     = {}
}
