# Working in this repo

## What this repo is
CardiacSense data platform on AWS (`eu-central-1`, staging only). **As of the MCP
migration (2026-06-11) this repo is primarily the Terraform/infra home** — the
Bedrock chat agent (`app/`, `ui/`) is superseded by a cloud-hosted **MCP server**
and **Claude Desktop** as the client. See `docs/MCP_MIGRATION.md`.

- **MCP server** (the capability layer): lives in the tool repo
  `CardiacSense-s3-downloader-tool/mcp_server/` (official `mcp` SDK / FastMCP,
  Streamable HTTP), folded into the **tool-api** ECS task. 28 tools = 20
  deterministic (`tool_api.services`) + 8 ad-hoc (Athena/Glue/S3/playbooks).
  Public HTTPS via **CloudFront** (`infra/modules/cloudfront`, gated `enable_mcp`)
  → ALB → tool-api. Auth = static bearer (Phase 1; OAuth/Cognito = Phase 2).
- **Deterministic Tool API**: `infra/modules/tool_api/` (gated `enable_tool_api`),
  the same ECS task — keeps `/v1/*` + `/tool-api/*` + `/health`.
- **Legacy (being torn down)**: the Bedrock Converse agent — `app/` (39 tools),
  `ui/`, `module.ecs`, sessions/cost tables, bedrock IAM, rollup Lambda. Removal
  follows the safe order in `docs/MCP_MIGRATION.md`; shared infra is preserved.

## Hard constraints
- **Never touch the production AWS account.** Every `aws ...` or Terraform call
  must target the staging account using profile **`cardiac-sense-staging`**
  (see `DEPLOY.md` for exceptions / legacy profile note).
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
- **Tool implementations:** ported from `claude_aws_agent/tools/` into
  `app/src/tools/`. Function bodies are kept; the MCP wrapper is replaced by a
  Converse-compatible registry (`REGISTRY` + `import_all()`).
- **Workflow / system prompt:** `prompts/system_prompt.md`, sourced from
  `claude_aws_agent/SKILL.md` lineage.
- **Knowledge:** `knowledge/` (playbooks, schemas, operator notes).
- **Cost tracker:** `app/src/tracker.py`, ported from `tools/execution_tracker.py`
  and extended with `record_bedrock(...)`.

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
  set the previous SHA in **local** `terraform.tfvars` (`image_tag`) and
  `terraform apply` (that file is gitignored — copy from `terraform.tfvars.example`).

## When something is unclear
Read the plan first: `C:\Users\SagiLevi\.claude\plans\you-are-now-taking-cheerful-hennessy.md`.
