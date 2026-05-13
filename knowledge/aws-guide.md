# AWS Access & Configuration Guide

## Overview

The CardiacSense data agent accesses AWS services in the **staging account**
(`735555370207`) in **`eu-central-1`** (Frankfurt). All **data** access from
analyst workstations is read-only.

For **Terraform, CodeBuild, ECS deploys, Secrets Manager, and Athena** from your
laptop, use the same **`cardiac-sense-staging`** profile documented in
`DEPLOY.md` (do not use legacy narrow profiles for those flows).

## AWS Profile Setup

### Prerequisites
1. AWS CLI v2 installed (`aws --version`)
2. AWS SSO configured for the CardiacSense staging account
3. Profile name: `cardiac-sense-staging`

### Configure the Profile

If you use AWS SSO (Identity Center):

```bash
aws configure sso
# SSO session name: cardiacsense
# SSO start URL: <your org SSO URL>
# SSO Region: eu-central-1
# Account: 735555370207
# Role: <your assigned role>
# CLI default client region: eu-central-1
# CLI default output: json
# CLI profile name: cardiac-sense-staging
```

Or manually add to `~/.aws/config`:

```ini
[profile cardiac-sense-staging]
sso_session = cardiacsense
sso_account_id = 735555370207
sso_role_name = <YourRoleName>
region = eu-central-1
output = json

[sso-session cardiacsense]
sso_start_url = <your-sso-url>
sso_region = eu-central-1
sso_registration_scopes = sso:account:access
```

### Login

```bash
aws sso login --profile cardiac-sense-staging
```

### Verify Access

```bash
aws sts get-caller-identity --profile cardiac-sense-staging
```

Expected output should show account `735555370207`.

## Environment Variables

The agent uses these environment variables (set in `.env` or shell):

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_PROFILE` | `cardiac-sense-staging` | AWS profile for all data access |
| `AWS_REGION` | `eu-central-1` | AWS region |
| `AWS_DEFAULT_REGION` | `eu-central-1` | Fallback region |

For Claude Desktop / Claude Code, the profile is picked up automatically from `~/.aws/config` if `AWS_PROFILE` is set.

## Service Access Patterns

### Athena (SQL Queries)

```bash
# Run a query
aws athena start-query-execution \
  --query-string "SELECT COUNT(*) FROM migrated_data.metadata WHERE date = '2026-03-24'" \
  --query-execution-context Database=migrated_data \
  --work-group primary \
  --profile cardiac-sense-staging

# Get results
aws athena get-query-results \
  --query-execution-id <execution-id> \
  --profile cardiac-sense-staging
```

Athena rules:
- Workgroup: `primary`
- Only SELECT, DESCRIBE, SHOW allowed
- Always include LIMIT (max 1000)
- Always filter by partition (date) on partitioned tables

### S3 (Object Storage)

```bash
# List buckets
aws s3 ls --profile cardiac-sense-staging

# List a prefix
aws s3 ls s3://735555370207-migrated--data/time-series-data/ --profile cardiac-sense-staging

# List with details
aws s3 ls s3://735555370207-app-events/rearrangement/rt_flow/ --profile cardiac-sense-staging --recursive --summarize
```

Key buckets:
- `735555370207-app-events` — raw data pipeline stages
- `735555370207-migrated--data` — final Parquet/CSV tables
- `735555370207-datasets-versioning` — ML datasets

### Glue (Data Catalog)

```bash
# List databases
aws glue get-databases --profile cardiac-sense-staging

# List tables
aws glue get-tables --database-name migrated_data --profile cardiac-sense-staging

# Describe a table
aws glue get-table --database-name migrated_data --name timeseries --profile cardiac-sense-staging
```

### QuickSight (Dashboards)

```bash
# List dashboards
aws quicksight list-dashboards --aws-account-id 735555370207 --profile cardiac-sense-staging

# List datasets
aws quicksight list-data-sets --aws-account-id 735555370207 --profile cardiac-sense-staging
```

## MCP Server Configuration

For Claude Desktop, the AWS MCP servers are configured in `claude-agent/mcp/mcp-config.json`. This provides Claude with direct tool access to Athena, S3, Glue, and QuickSight without needing to shell out to the AWS CLI.

## Troubleshooting

### "The SSO session has expired"
```bash
aws sso login --profile cardiac-sense-staging
```

### "Unable to locate credentials"
Ensure `AWS_PROFILE=cardiac-sense-staging` is set, or pass `--profile` explicitly.

### "Access Denied" on a service
Check your SSO role permissions. The agent needs read access to: Athena, S3, Glue, QuickSight, STS.

### Athena query stuck
Check the Athena workgroup `primary` in the console. Queries have a 120-second timeout built into the agent.
