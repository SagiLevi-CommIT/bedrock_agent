output "sessions_table_name" {
  value = one(aws_dynamodb_table.sessions[*].name)
}

output "sessions_table_arn" {
  value = one(aws_dynamodb_table.sessions[*].arn)
}

output "cost_table_name" {
  value = one(aws_dynamodb_table.cost[*].name)
}

output "cost_table_arn" {
  value = one(aws_dynamodb_table.cost[*].arn)
}

output "patient_id_map_table_name" {
  value = aws_dynamodb_table.patient_id_map.name
}

output "patient_id_map_table_arn" {
  value = aws_dynamodb_table.patient_id_map.arn
}

output "output_bucket_name" {
  value = aws_s3_bucket.output.id
}

output "output_bucket_arn" {
  value = aws_s3_bucket.output.arn
}

output "athena_results_bucket_name" {
  value = aws_s3_bucket.athena_results.id
}

output "athena_results_bucket_arn" {
  value = aws_s3_bucket.athena_results.arn
}

output "codebuild_source_bucket_name" {
  value = aws_s3_bucket.codebuild_source.id
}

output "codebuild_source_bucket_arn" {
  value = aws_s3_bucket.codebuild_source.arn
}
