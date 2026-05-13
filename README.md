# bedrock_agent

AWS-hosted CardiacSense data chatbot. Replaces the local `claude_aws_agent`
(Claude Desktop / Claude Code MCP server) with a web app behind an internal URL.

- **Region:** `eu-central-1` (Frankfurt) — same as the staging data.
- **Environment:** **STAGING ONLY.** The production AWS account is never touched by this repo.
- **Auth:** v1 has no user auth; an AWS WAF IP allowlist is the only door. The
  architecture leaves a clean seam for ALB OIDC + Cognito/Entra later.
- **Backend:** FastAPI + **28** in-process `boto3` tools (see `GET /api/info` on
  the live service), deployed as a single container on Fargate behind an ALB.
- **LLM:** AWS Bedrock `bedrock-runtime:Converse`. **Staging currently runs
  `mistral.devstral-2-123b`** (in-region) because an **organization SCP blocks
  `anthropic.*` foundation models** in this account. IAM already allows
  Anthropic ARNs so switching models is an env / SCP change — see `DEPLOY.md`.
- **IaC:** Terraform-first. CloudFormation is intentionally not used.
- **Read-only by design:** the Fargate task role has only read permissions on
  data services; writes are limited to the agent output bucket, session/cost
  DynamoDB tables, and advice objects under `advice/raw/`.

## Staging status (validated)

Staging is **deployed and validated**: `/api/health` reports **`tools: 28`**,
ECS task definition **`claude-aws-agent-staging-task:22`**, ECR tag
**`6865802c`**. Operators use AWS profile **`cardiac-sense-staging`** (see
`DEPLOY.md` for curl checks, Terraform, and CodeBuild).

## Why a new repo

The local `claude_aws_agent` is excellent for individual analysts but does not
scale: every analyst needs a venv, a personal AWS profile, and Claude Code
installed. This repo turns that agent into a single shared web URL while
preserving the tool implementations, expanded `knowledge/` corpus, workflow in
`prompts/system_prompt.md`, and cost-tracking patterns.

## Repository layout

```
app/        FastAPI backend, Bedrock Converse loop, tool registry
ui/         Frontend (React/Vite SPA)
infra/      Terraform: envs/staging, modules/{vpc,alb,waf,ecs,...}
prompts/    System prompt + tool descriptions for the model
knowledge/  Data catalog notes, playbooks, query guidance
skills/     YAML skills copied into the container image
eval/       Validation harness + golden questions
scripts/    CodeBuild helper, deploy script, operator utilities
```

## Related repos

- `claude_aws_agent` — upstream source for tool logic and operational patterns.
- `vcomm-ai-agentcore-poc` — reference for audit log shape. **Architecture differs:**
  that path uses Bedrock AgentCore + Strands; this repo uses **direct Converse**
  and an in-process registry (no Strands / AgentCore runtime).
- `alidade-ai-agentcore-poc` — reference for documentation and validation style.

## Deploy / runbooks

See **`DEPLOY.md`** (ALB URL, `terraform.tfvars`, CodeBuild, ECS wait, Bedrock SCP
notes, and legacy profile explanation).
