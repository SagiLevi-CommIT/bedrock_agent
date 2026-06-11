terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

# Phase-1 public HTTPS entry for the MCP server WITHOUT owning DNS: CloudFront
# gives a stable *.cloudfront.net hostname with a valid managed TLS cert. Origin
# is the existing ALB over HTTP; CloudFront adds a secret X-Origin-Verify header
# that the WAF requires, so the ALB only honours CloudFront-originated requests
# (the office-IP WAF allowlist would otherwise block Claude Desktop's dynamic IPs).
# The real auth is the MCP bearer; this header just gates the public ALB path.
# Phase 2 can swap the cloudfront_default_certificate for the company domain + ACM.

resource "random_password" "origin_verify" {
  length  = 40
  special = false
}

# AWS-managed policy IDs (global, stable):
#   CachingDisabled            = 4135ea2d-6df8-44a3-9df3-4b5a84be39ad
#   AllViewerExceptHostHeader  = b689b0a8-53d0-40ab-baf2-68738e2966ac (forwards Authorization, not Host)
locals {
  cache_policy_disabled      = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
  origin_req_all_except_host = "b689b0a8-53d0-40ab-baf2-68738e2966ac"
  origin_id                  = "alb-origin"
}

resource "aws_cloudfront_distribution" "this" {
  enabled      = true
  comment      = "${var.name_prefix} MCP HTTPS entry (origin = ALB)"
  price_class  = "PriceClass_100"
  http_version = "http2and3"

  origin {
    domain_name = var.alb_dns_name
    origin_id   = local.origin_id

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "http-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 60
      origin_keepalive_timeout = 60
    }

    custom_header {
      name  = "X-Origin-Verify"
      value = random_password.origin_verify.result
    }
  }

  default_cache_behavior {
    target_origin_id         = local.origin_id
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = local.cache_policy_disabled
    origin_request_policy_id = local.origin_req_all_except_host
    compress                 = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }
}
