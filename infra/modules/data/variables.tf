variable "name_prefix" {
  type = string
}

variable "account_id" {
  type = string
}

variable "create_agent_tables" {
  type        = bool
  default     = true
  description = "Create the Bedrock-agent-only DynamoDB tables (sessions, cost). false during MCP teardown; the shared patient-id-map table is unaffected."
}
