# Populate via -backend-config=backend.hcl on `terraform init`.
# Example backend.hcl:
#   bucket         = "tfstate-cardiacsense-staging-<account-id>"
#   key            = "envs/staging/terraform.tfstate"
#   region         = "eu-central-1"
#   dynamodb_table = "tfstate-lock"
#   encrypt        = true

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }

  backend "s3" {}
}
