# Working in this repo

## What this repo is
AWS-hosted CardiacSense data chatbot. Direct Bedrock Converse + 18 in-process
boto3 tools ported from `claude_aws_agent`. eu-central-1, staging only.

## Hard constraints
- **Never touch the production AWS account.** Every `aws ...` or Terraform call
  must target the staging account/profile (`cardiac-sense-staging-s3`).
- **Read-only data access.** The task role has no `glue:Create*`, no
  `s3:Delete*` on data buckets, no `dynamodb:DeleteTable`, and no IAM mutation.
  Writes are limited to the agent's own output S3 bucket and its DynamoDB
  tables.
- **Terraform-first.** No CloudFormation. No `aws bedrock-agentcore-control`
  CLI calls in CI. Every resource has a stable `aws_*` provider resource.
- **No Strands SDK, no Bedrock AgentCore Runtime.** This was an explicit
  architecture decision — see the plan file.
- **No Anthropic API key.** Bedrock is reached via the IAM task role only.

## Where the canonical source for each thing lives
- The 18 tool implementations: ported from
  `C:\Users\SagiLevi\Documents\Git\claude_aws_agent\tools\` into `app/src/tools/`.
  Function bodies are kept; the wrapper layer (`mcp_server.py`) is rewritten as
  a Converse-compatible tool registry.
- The 6-step workflow / system prompt: `prompts/system_prompt.md`, sourced from
  `C:\Users\SagiLevi\Documents\Git\claude_aws_agent\SKILL.md`.
- The 15 knowledge files: `knowledge/`, copied from
  `C:\Users\SagiLevi\Documents\Git\claude_aws_agent\knowledge\`.
- The cost tracker: `app/src/tracker.py`, ported from
  `tools/execution_tracker.py` and extended with `record_bedrock(...)`.

## Style and dependencies
- Python 3.12, type hints required.
- `boto3` only — do not introduce `aiobotocore`, `aws-sdk-pandas`, or any agent
  framework (Strands, LangChain, LlamaIndex). The Converse loop is hand-rolled.
- Tests use `pytest`. Mock AWS with `botocore.stub.Stubber`. Tests marked
  `@pytest.mark.integration` need real AWS credentials and are skipped in
  default `pytest`.

## Deployment
- `infra/envs/staging/` is the only deploy target.
- `terraform plan` runs on every PR; apply requires manual approval on PRs
  touching `infra/`.
- Container images are tagged with the short git SHA (no `:latest`). Rollback =
  set the previous SHA in `image_tag` and `terraform apply`.

## When something is unclear
Read the plan first: `C:\Users\SagiLevi\.claude\plans\you-are-now-taking-cheerful-hennessy.md`.
