output "project_name" {
  value = aws_codebuild_project.image.name
}

output "project_arn" {
  value = aws_codebuild_project.image.arn
}
