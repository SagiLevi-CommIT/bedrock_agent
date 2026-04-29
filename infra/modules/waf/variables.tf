variable "name_prefix" {
  type = string
}

variable "alb_arn" {
  type = string
}

variable "office_cidrs" {
  type        = list(string)
  description = "Allowlisted CIDRs (office / VPN). All other source IPs are blocked."
}

variable "rate_limit_per_5min" {
  type        = number
  description = "Max requests per IP per 5 minutes. Counts only requests from allowlisted IPs that pass the prior rule."
  default     = 1000
}
