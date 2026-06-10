output "ecr_repository_url" {
  value = aws_ecr_repository.this.repository_url
}

output "service_name" {
  value = aws_ecs_service.this.name
}

output "target_group_arn" {
  value = aws_lb_target_group.this.arn
}

output "task_role_arn" {
  value = aws_iam_role.task.arn
}

output "task_role_name" {
  value = aws_iam_role.task.name
}

output "internal_base_url" {
  description = "Private (Cloud Map) base URL for agent -> tool-api calls -- no ALB/WAF in the path, no /tool-api prefix."
  value       = "http://tool-api.${var.service_discovery_namespace}:${var.container_port}"
}

output "api_token_secret_arn" {
  description = "Secrets Manager ARN of the generated /tool-api bearer token."
  value       = aws_secretsmanager_secret.api_token.arn
}

output "codebuild_project_name" {
  description = "CodeBuild project that builds the tool image from <source_bucket>/tool-api-source.zip."
  value       = aws_codebuild_project.image.name
}
