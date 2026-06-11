variable "name_prefix" {
  type = string
}

variable "region" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "ecs_security_group_id" {
  type = string
}

variable "target_group_arn" {
  type = string
}

variable "image_repository_url" {
  type    = string
  default = ""
}

variable "image_tag" {
  type    = string
  default = ""
}

variable "container_port" {
  type    = number
  default = 8000
}

variable "task_cpu" {
  type    = number
  default = 512
}

variable "task_memory" {
  type    = number
  default = 1024
}

variable "min_tasks" {
  type    = number
  default = 1
}

variable "max_tasks" {
  type    = number
  default = 4
}

variable "create_service" {
  type        = bool
  default     = true
  description = "Create the agent ECS service/taskdef/autoscaling. false keeps only the shared cluster (Bedrock teardown)."
}

variable "exec_role_arn" {
  type    = string
  default = ""
}

variable "task_role_arn" {
  type    = string
  default = ""
}

variable "log_group_name" {
  type = string
}

variable "env" {
  type        = map(string)
  description = "Environment variables baked into the task definition (non-secret)."
  default     = {}
}
