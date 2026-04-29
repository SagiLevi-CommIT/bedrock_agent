variable "name_prefix" {
  type = string
}

variable "aws_region" {
  type = string
}

variable "ecr_repository_arn" {
  type = string
}

variable "ecr_repository_url" {
  type = string
}

variable "ecr_registry" {
  type        = string
  description = "ECR registry hostname (account.dkr.ecr.region.amazonaws.com)"
}

variable "source_bucket_name" {
  type = string
}

variable "source_bucket_arn" {
  type = string
}

variable "passrole_arns" {
  type        = list(string)
  description = "Roles CodeBuild can pass (e.g. ECS exec/task roles). Used when CodeBuild updates ECS service."
  default     = []
}
