# MCP Migration (Phase 1) — Bedrock chat agent → AWS-hosted MCP server

**Status: Phase 1 LIVE and validated (2026-06-11).** The deterministic capability
layer is now reachable by Claude Desktop (and any MCP client) over a cloud-hosted
MCP server. The Bedrock chat agent is superseded; its teardown is a gated final step.

## What changed

| | Before | After (Phase 1) |
|---|---|---|
| Chat brain | Bedrock Converse loop (agent ECS svc) | **Claude Desktop** (client-side) |
| Capability layer | tool-api FastAPI (`/v1`) called by the agent | **same tool-api + a new MCP server** in one ECS task |
| Client transport | React UI → `/api/chat` | **MCP Streamable HTTP** at `/mcp` |
| Public entry | HTTP-only ALB (office-IP WAF) | **CloudFront HTTPS** (`*.cloudfront.net`) → ALB |
| Auth | app session | **static bearer** (Phase 2: OAuth/Cognito) |

## Architecture (live)

```
Claude Desktop ──(npx mcp-remote, Bearer)──HTTPS──▶ CloudFront (dlx14274cj8xv.cloudfront.net, valid TLS)
                                                          │  adds secret X-Origin-Verify header
                                                          ▼
                                       ALB :80 ──WAF(allow X-Origin-Verify)──▶ rule /mcp,/v1/*,/health ─▶ tool-api TG
                                                          ▼
                          tool-api ECS task = uvicorn mcp_server.asgi:app
                              • /mcp  → FastMCP Streamable HTTP (28 tools, bearer-guarded)
                              • /health, /v1/*, /tool-api/* → existing FastAPI tool-api
                              • ONE process → MCP job tools + /v1/jobs share the JobManager
                                                          ▼
                          core.service / boto3 → S3 (data) · Athena/Glue · patient-id-map · resolver (NAT) · Cardiolys (NAT) · artifacts S3
```

- **MCP server**: tool repo `mcp_server/` (official `mcp` SDK / FastMCP, `stateless_http`,
  `json_response`). 28 tools = 20 deterministic (`tool_api.services` in-process) + 8 ad-hoc
  (Athena/Glue/S3/playbooks). Zero new IAM (reuses the tool-api task role).
- **Endpoint**: `https://dlx14274cj8xv.cloudfront.net/mcp` (Terraform output `mcp_endpoint`).
- **Auth**: static bearer = the `claude-aws-agent-staging-tool-api-token` secret, validated by
  `mcp_server/auth.py`. CloudFront's `X-Origin-Verify` secret gates the public ALB at the WAF.

## Connect Claude Desktop (Phase 1)

Native custom connectors require OAuth (Phase 2). For a static bearer, use the `mcp-remote`
bridge in `%APPDATA%\Claude\claude_desktop_config.json` (needs Node/npx):

```jsonc
{
  "mcpServers": {
    "cardiacsense": {
      "command": "npx",
      "args": ["mcp-remote", "https://dlx14274cj8xv.cloudfront.net/mcp",
               "--header", "Authorization:${AUTH}"],
      "env": { "AUTH": "Bearer <claude-aws-agent-staging-tool-api-token value>" }
    }
  }
}
```
Get the token: `aws secretsmanager get-secret-value --secret-id claude-aws-agent-staging-tool-api-token --profile cardiac-sense-staging --region eu-central-1 --query SecretString --output text`.
Restart Claude Desktop; the `cardiacsense` tools appear.

## Deploy / update the MCP service

```bash
# 1. Build the tool-api+MCP image (CodeBuild; ECR Public base avoids Docker Hub 429)
cd CardiacSense-s3-downloader-tool && git rev-parse --short HEAD   # -> TAG
#    upload source.zip to the codebuild-src bucket, start tool-api-image-build with IMAGE_TAG=TAG
# 2. Point + apply (local terraform.tfvars, gitignored)
#    enable_tool_api = true ; enable_mcp = true ; tool_api_image_tag = "<TAG>"
cd bedrock_agent/infra/envs/staging
terraform plan -out=tf.plan && terraform apply tf.plan
aws ecs wait services-stable --cluster claude-aws-agent-staging-cluster --services claude-aws-agent-staging-tool-api-svc
terraform output mcp_endpoint
```
Rollback = previous `tool_api_image_tag` + apply. Disable MCP entirely = `enable_mcp=false`
(removes CloudFront + the WAF rule; tool-api `/v1` keeps working).

## Validation evidence (2026-06-11, via the MCP Python client through CloudFront)
- `GET /health` → 200, TLS verified.
- MCP initialize + `tools/list` → **28 tools**.
- `check_aws_connection` → ok (task role). `patient_timeline 739` → `strategy=migrated`, real
  per-day counts (Athena data path). `list_glue_databases` → real catalog (ad-hoc tool).
- Async job: `fetch_data` → `job_98c345371b0d` → poll showed `running` 50→100% (MCP submit/poll
  share the JobManager in the single task).

## Phase 2 (not done — additive, no redesign)
OAuth 2.1 / Cognito (federated to company SSO) + native org connector (swap `mcp_server/auth.py`
for `mcp.server.auth` TokenVerifier + RFC 9728 metadata; CloudFront/ALB/tools unchanged); the
company domain (ACM + Route53/Cloudflare) in place of the CloudFront default hostname; SQS/DynamoDB
job store to lift the single-task pin; per-user audit.

## Bedrock teardown — DONE (2026-06-11)
Applied `enable_agent=false`: **35 agent-only resources destroyed** — agent ECS service +
task def + autoscaling (cluster KEPT via `create_service` gating), agent ECR + CodeBuild +
role + log group, agent IAM task/exec roles + all policies (incl. `task_bedrock` /
`bedrock_model_arns`), indexing/rollup Lambda + EventBridge + Glue idx tables + role,
DynamoDB `…-sessions` + `…-cost` tables. The agent chat **code** (`app/`, `ui/`, agent
scripts + CI) was removed from Git (history preserves it).

**Preserved (verified untouched):** VPC/NAT, ALB (LB/listener/default-TG/ECS-SG), WAF,
CloudFront, the `tool_api` module + its ECS service/ECR/CodeBuild/IAM, data buckets,
athena-results + codebuild-src buckets, `patient-id-map`, `INTERNAL_TOKEN`, `tool-api-token`,
Cloud Map, CloudWatch log group.

**Post-teardown evidence:** `terraform plan` → "No changes"; `aws ecs list-services` → only
`claude-aws-agent-staging-tool-api-svc`; MCP `/health` via CloudFront → 200 (TLS verified).
Rollback (if ever needed): `enable_agent=true` + re-apply rebuilds the agent infra (the chat
code is in Git history); the sessions/cost tables would be recreated empty.

To gate MCP off entirely: `enable_mcp=false` (removes CloudFront + the WAF origin rule;
the tool-api `/v1` surface keeps working internally).
