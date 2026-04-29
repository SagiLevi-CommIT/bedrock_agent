output "task_role_arn" {
  value = aws_iam_role.task.arn
}

output "task_role_name" {
  value = aws_iam_role.task.name
}

output "exec_role_arn" {
  value = aws_iam_role.exec.arn
}

output "exec_role_name" {
  value = aws_iam_role.exec.name
}
