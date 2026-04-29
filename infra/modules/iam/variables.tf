variable "name_prefix" {
  type = string
}

variable "bedrock_model_arns" {
  type        = list(string)
  description = "ARNs of the Bedrock inference profiles / foundation models the agent may invoke. Scope tightly."
  default = [
    "arn:aws:bedrock:eu-central-1::foundation-model/anthropic.*",
    "arn:aws:bedrock:eu-central-1:*:inference-profile/eu.anthropic.*",
  ]
}

variable "data_bucket_arns" {
  type        = list(string)
  description = "Data S3 buckets the agent may read (CardiacSense staging buckets)."
  default     = []
}

variable "athena_results_bucket_arn" {
  type        = string
  description = "Bucket where Athena writes query results."
  default     = ""
}

variable "output_bucket_arn" {
  type        = string
  description = "Bucket the agent owns for its own downloads/exports/reports."
  default     = ""
}

variable "log_group_arn" {
  type        = string
  description = "CloudWatch log group ARN; restricts logs:Put* to this group."
  default     = ""
}

variable "dynamodb_table_arns" {
  type        = list(string)
  description = "ARNs of the agent's DynamoDB tables (sessions, cost-rollup)."
  default     = []
}

variable "secret_arns" {
  type        = list(string)
  description = "Secrets Manager secrets the EXECUTION role may read (for env injection)."
  default     = []
}
