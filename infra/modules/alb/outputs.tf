output "alb_arn" {
  value = aws_lb.this.arn
}

output "alb_dns_name" {
  value = aws_lb.this.dns_name
}

output "alb_zone_id" {
  value = aws_lb.this.zone_id
}

output "target_group_arn" {
  value = aws_lb_target_group.this.arn
}

output "alb_security_group_id" {
  value = aws_security_group.alb.id
}

output "ecs_security_group_id" {
  value = aws_security_group.ecs.id
}

output "active_listener_arn" {
  description = "The active forwarding listener (HTTP in v1, HTTPS once a cert is set). Used to attach path-routed rules (e.g. /tool-api/*)."
  value       = var.certificate_arn == "" ? aws_lb_listener.http[0].arn : aws_lb_listener.https[0].arn
}
