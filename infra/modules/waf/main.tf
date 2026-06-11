terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

resource "aws_wafv2_ip_set" "office" {
  name               = "${var.name_prefix}-office-ips"
  description        = "Allowlisted office / VPN CIDRs for the staging agent ALB."
  scope              = "REGIONAL"
  ip_address_version = "IPV4"
  addresses          = var.office_cidrs
}

resource "aws_wafv2_web_acl" "this" {
  name        = "${var.name_prefix}-acl"
  description = "v1: IP allowlist + AWS managed rules. Phase 9 adds OIDC at ALB instead of IP."
  scope       = "REGIONAL"

  default_action {
    block {}
  }

  # Allow CloudFront-originated MCP traffic: CloudFront adds a secret
  # X-Origin-Verify header that only it knows. Evaluated FIRST (priority 0) so it
  # precedes the managed rule groups, and lets Claude Desktop's dynamic source
  # IPs through the office-IP allowlist. The real auth is still the MCP bearer.
  dynamic "rule" {
    for_each = toset(var.origin_verify_secret == "" ? [] : ["enabled"])
    content {
      name     = "allow-cloudfront-origin"
      priority = 0

      action {
        allow {}
      }

      statement {
        byte_match_statement {
          search_string         = var.origin_verify_secret
          positional_constraint = "EXACTLY"
          field_to_match {
            single_header {
              name = "x-origin-verify"
            }
          }
          text_transformation {
            priority = 0
            type     = "NONE"
          }
        }
      }

      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "${var.name_prefix}-allow-cf-origin"
        sampled_requests_enabled   = true
      }
    }
  }

  rule {
    name     = "allow-office-ips"
    priority = 1

    action {
      allow {}
    }

    statement {
      ip_set_reference_statement {
        arn = aws_wafv2_ip_set.office.arn
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-allow-office"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "rate-limit-per-ip"
    priority = 2

    action {
      block {}
    }

    statement {
      rate_based_statement {
        aggregate_key_type = "IP"
        limit              = var.rate_limit_per_5min
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-rate-limit"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "aws-managed-common"
    priority = 3

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-aws-common"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "aws-managed-known-bad-inputs"
    priority = 4

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.name_prefix}-aws-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.name_prefix}-acl"
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_association" "alb" {
  resource_arn = var.alb_arn
  web_acl_arn  = aws_wafv2_web_acl.this.arn
}
