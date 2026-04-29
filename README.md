# bedrock_agent

AWS-hosted CardiacSense data chatbot. Replaces the local `claude_aws_agent`
(Claude Desktop / Claude Code MCP server) with a web app behind an internal URL.

- **Region:** eu-central-1 (Frankfurt) — same as the staging data.
- **Environment:** STAGING ONLY. The PROD account is never touched by this repo.
- **Auth:** v1 has no user auth; an AWS WAF IP allowlist is the only door. The
  architecture leaves a clean seam for ALB OIDC + Cognito/Entra later.
- **Backend:** FastAPI + the existing 18 boto3 tools, deployed as a single
  container on Fargate behind ALB.
- **LLM:** AWS Bedrock direct (`bedrock-runtime:Converse`) with Claude
  Sonnet 4.5 via the EU geo inference profile
  (`eu.anthropic.claude-sonnet-4-5-20250929-v1:0`).
- **IaC:** Terraform-first. CloudFormation is intentionally not used.
- **Read-only by design:** the Fargate task role has only read permissions on
  data services; write permissions are limited to the agent's own output bucket
  and DynamoDB tables.

## Why a new repo

The local `claude_aws_agent` is excellent for individual analysts but does not
scale: every analyst needs a venv, a personal AWS profile, and Claude Code
installed. This repo turns that agent into a single shared web URL while
preserving the 18 tools, the 15 knowledge files, the 6-step workflow, and the
cost-tracking patterns that already work.

## Repository layout

```
app/        FastAPI backend, Bedrock Converse loop, ported tool registry
ui/         Frontend (Streamlit or React/Vite, single page)
infra/      Terraform: envs/staging, modules/{vpc,alb,waf,ecs,...}
prompts/    System prompt + per-tool description files
knowledge/  Ported as-is from claude_aws_agent/knowledge
eval/       Validation harness + golden questions
scripts/    One-off operator scripts (seed_secrets, smoke, cost_sanity)
```

## Status

Phase 1: skeleton in progress. Plan tracked at
`C:\Users\SagiLevi\.claude\plans\you-are-now-taking-cheerful-hennessy.md`.

## Related repos

- `C:\Users\SagiLevi\Documents\Git\claude_aws_agent` — source of truth for tools,
  knowledge, and the system prompt.
- `C:\Users\SagiLevi\Documents\Git\vcomm-ai-agentcore-poc` — reference for audit
  log shape and operational patterns. **Architecture is intentionally different:**
  vcomm uses Bedrock AgentCore Runtime + Strands SDK; this repo uses direct
  Bedrock Converse with an in-process tool registry.
- `C:\Users\SagiLevi\Documents\Git\alidade\alidade-ai-agentcore-poc` — reference
  for documentation structure and the validation-harness methodology.
