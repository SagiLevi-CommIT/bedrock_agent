output "vpc_id" {
  value = module.vpc.vpc_id
}

output "private_subnet_ids" {
  value = module.vpc.private_subnet_ids
}

output "public_subnet_ids" {
  value = module.vpc.public_subnet_ids
}

output "ecr_repository_url" {
  value = var.enable_agent ? module.ecr[0].repository_url : ""
}

output "alb_dns_name" {
  value = module.alb.alb_dns_name
}

output "ecs_cluster_name" {
  value = module.ecs.cluster_name
}

output "ecs_service_name" {
  value = module.ecs.service_name
}

output "log_group_name" {
  value = module.observability.log_group_name
}

output "task_role_arn" {
  value = var.enable_agent ? module.iam[0].task_role_arn : ""
}

output "sessions_table_name" {
  value = module.data.sessions_table_name
}

output "cost_table_name" {
  value = module.data.cost_table_name
}

output "output_bucket_name" {
  value = module.data.output_bucket_name
}

output "athena_results_bucket_name" {
  value = module.data.athena_results_bucket_name
}

output "codebuild_project_name" {
  value = var.enable_agent ? module.codebuild[0].project_name : ""
}

output "codebuild_source_bucket_name" {
  value = module.data.codebuild_source_bucket_name
}

output "mcp_endpoint" {
  description = "Public MCP endpoint (Streamable HTTP) for Claude Desktop / mcp-remote."
  value       = var.enable_mcp ? "https://${module.cloudfront[0].domain_name}/mcp" : ""
}
