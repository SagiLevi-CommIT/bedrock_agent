variable "name_prefix" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "public_subnet_ids" {
  type = list(string)
}

variable "container_port" {
  type    = number
  default = 8000
}

variable "certificate_arn" {
  type        = string
  description = "ACM cert ARN. Empty string = HTTP-only listener (acceptable for v1 staging behind WAF)."
  default     = ""
}
