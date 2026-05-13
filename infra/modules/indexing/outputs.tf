output "agent_glue_database_name" {
  value       = aws_glue_catalog_database.agent.name
  description = "Glue database that owns the agent's indexed tables."
}

output "patient_daily_table_name" {
  value       = aws_glue_catalog_table.patient_daily.name
  description = "patient_daily Glue table name (database is the agent_glue_database output)."
}

output "patient_daily_fqn" {
  value       = "${aws_glue_catalog_database.agent.name}.${aws_glue_catalog_table.patient_daily.name}"
  description = "Fully qualified Athena name for the rollup table."
}

output "sleep_flow_idx_table_name" {
  value       = aws_glue_catalog_table.sleep_flow_rearrangement_idx.name
  description = "Sleep-flow rearrangement index Glue table."
}

output "rollup_lambda_arn" {
  value       = aws_lambda_function.rollup.arn
  description = "ARN of the daily-refresh Lambda."
}

output "rollup_schedule_rule_arn" {
  value       = aws_cloudwatch_event_rule.rollup_daily.arn
  description = "EventBridge rule that fires the daily refresh."
}
