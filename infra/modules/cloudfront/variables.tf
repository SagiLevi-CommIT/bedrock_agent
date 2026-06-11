variable "name_prefix" {
  type = string
}

variable "alb_dns_name" {
  type        = string
  description = "Origin: the existing ALB DNS name (HTTP:80)."
}
