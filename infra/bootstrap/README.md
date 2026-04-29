# Terraform bootstrap

Creates the S3 state bucket + DynamoDB lock table used by every other
Terraform stack in this repo. Run **once per AWS account**, then never touch
again unless you are decommissioning the account.

## Usage

```bash
cd infra/bootstrap
terraform init
terraform apply \
  -var="state_bucket_name=tfstate-cardiacsense-staging-<account-id>" \
  -var="aws_profile=cardiac-sense-staging-s3"
```

After apply, use the outputs to populate `infra/envs/staging/backend.hcl`.

## Why local state for this module

The bucket that stores Terraform state for everything else is itself created
here. Storing this module's own state in that bucket would be a chicken-and-egg
problem. We keep the bootstrap state file locally (committed nowhere) and
re-run the module only when the bucket / lock table needs migration.
