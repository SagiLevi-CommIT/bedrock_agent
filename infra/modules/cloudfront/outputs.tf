output "domain_name" {
  description = "Stable HTTPS hostname for the MCP endpoint (https://<domain>/mcp)."
  value       = aws_cloudfront_distribution.this.domain_name
}

output "origin_verify_secret" {
  description = "Secret value CloudFront sends as X-Origin-Verify; the WAF requires it."
  value       = random_password.origin_verify.result
  sensitive   = true
}
