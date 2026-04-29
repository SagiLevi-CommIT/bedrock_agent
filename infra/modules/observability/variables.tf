variable "name_prefix" {
  type = string
}

variable "project" {
  type = string
}

variable "log_retention_days" {
  type    = number
  default = 14
}

variable "alarm_email" {
  type    = string
  default = ""
}

variable "monthly_budget_usd" {
  type    = number
  default = 200
}
