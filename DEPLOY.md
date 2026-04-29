# Deployment runbook (staging)

Live URL (HTTP, IP-allowlisted by WAF — only `199.203.119.181/32` reaches the
ALB):

> http://claude-aws-agent-staging-alb-346464057.eu-central-1.elb.amazonaws.com

Open that URL in a browser to use the chat UI. The same host serves `/api/*`
for programmatic access; both share the WAF + ALB.

Account `735555370207` / region `eu-central-1`.

## Quick checks

```bash
ALB="http://claude-aws-agent-staging-alb-346464057.eu-central-1.elb.amazonaws.com"

# UI
curl -I "$ALB/"
# 200 text/html (Vite-built SPA)

# API
curl "$ALB/api/health"
# {"status":"ok","region":"eu-central-1","model":"mistral.devstral-2-123b","tools":7}

curl -X POST "$ALB/api/chat" -H "Content-Type: application/json" \
  -d '{"prompt":"List the Glue databases."}'
# returns {session_id, text, tool_trace[], usage, iterations, stop_reason, latency_ms}
```

## UI

Vite + React + TypeScript + Tailwind 4 SPA in `ui/`, built at image-build time
and copied into `/app/ui_dist`. FastAPI serves `/`, `/assets/*`, and any
unknown path as `index.html` (SPA fallback). Session id is preserved across
turns; tool calls collapse into a per-turn debug section.

Local dev:

```bash
cd app && uvicorn src.main:app --reload --port 8000   # backend
cd ui  && npm install && npm run dev                  # SPA on :5173, /api → :8000
```

## Re-deploying the app image

No local Docker is required — builds run in **AWS CodeBuild**.

```bash
git commit ...                        # land your change
bash scripts/build_and_push.sh        # zips repo, uploads to S3, runs CodeBuild
                                      # → echoes the new image_tag (8-char SHA)
# then update infra/envs/staging/terraform.tfvars: image_tag = "<sha>"
cd infra/envs/staging
terraform apply
```

Rolling back is the same flow with a previous SHA. Image tags are immutable;
ECR keeps the last 20.

## Bedrock model — and the SCP problem

> **The org SCP `arn:aws:organizations::071204572266:policy/.../p-lwuwinuh`
> currently denies `bedrock:InvokeModel` on every `anthropic.*` foundation
> model in this account.** Verified 2026-04-29 against the EU geo profile,
> the Global profile, and direct foundation-model ARNs for Sonnet 4.5,
> Haiku 4.5, and Sonnet 4.

We selected this Bedrock model for the live container:

```
mistral.devstral-2-123b   (eu-central-1, in-region, no SCP block)
```

**The whole codebase is set up to swap back to Claude with a single
`terraform.tfvars` change** (the IAM grant already covers `anthropic.*`):

1. Ask AWS Org admin to update the SCP to allow `bedrock:InvokeModel` on
   `arn:aws:bedrock:*::foundation-model/anthropic.*` for account
   `735555370207` in `eu-central-1` (and any EU region the cross-region
   inference profile may route to).
2. In `infra/envs/staging/main.tf`, swap the env values back:
   ```hcl
   BEDROCK_MODEL_ID      = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
   BEDROCK_FAST_MODEL_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
   ```
3. `terraform apply`. The ECS service auto-rolls onto the new task definition.

The IAM allow-list under `module.iam` already permits Anthropic, Mistral,
Amazon, Cohere, OpenAI-OSS, Qwen, and ZAI providers — switching providers is
purely an env-var change.

## Tools live today (7)

`check_aws_connection`, `list_databases`, `list_tables`, `describe_table`,
`search_tables`, `run_athena_query`, `explore_s3`.

Add more by porting from `claude_aws_agent/tools/` into `app/src/tools/`;
the `@tool` decorator + `import_all()` in `app/src/tools/__init__.py` picks
them up at startup.

## Outputs of the staging stack

```
alb_dns_name              claude-aws-agent-staging-alb-346464057.eu-central-1.elb.amazonaws.com
ecr_repository_url        735555370207.dkr.ecr.eu-central-1.amazonaws.com/claude-aws-agent-staging-backend
ecs_cluster_name          claude-aws-agent-staging-cluster
ecs_service_name          claude-aws-agent-staging-svc
log_group_name            /ecs/claude-aws-agent-staging
sessions_table_name       claude-aws-agent-staging-sessions
cost_table_name           claude-aws-agent-staging-cost
output_bucket_name        claude-aws-agent-staging-output-735555370207
athena_results_bucket     claude-aws-agent-staging-athena-results-735555370207
codebuild_project_name    claude-aws-agent-staging-image-build
task_role_arn             arn:aws:iam::735555370207:role/claude-aws-agent-staging-task-role
```

## CloudWatch Logs Insights queries

The logger emits structured JSON so Insights "fields" works directly.

```sql
-- All chat completions in the last hour, sorted by latency
fields @timestamp, request_id, session_id, latency_ms, input_tokens, output_tokens, iterations, tools_called
| filter logger = "agent.cost" and msg = "chat_complete"
| sort latency_ms desc
| limit 50

-- Tool error rate
fields @timestamp, _name, ok, latency_ms
| filter logger = "agent.tool_trace"
| stats count() as calls, sum(ok=0) as errors by _name

-- Token cost rollup
fields input_tokens, output_tokens
| filter logger = "agent.cost" and msg = "chat_complete"
| stats sum(input_tokens) as in_total, sum(output_tokens) as out_total
```

## Known follow-ups

- **SCP** (P0): get Anthropic models unblocked — see above.
- **Auth** (P1): add ALB OIDC + Microsoft Entra when more than the office IP
  needs access.
- **HTTPS** (P1): create an ACM cert + Route53 record, set
  `module.alb.certificate_arn` to switch the listener to TLS 1.3.
- **Tools** (P2): port the remaining 11 tools from `claude_aws_agent/tools/`
  (`s3_search`, `s3_download`, `s3_knowledge`, `catalog_lookup`,
  `athena_views`, `learning`, `export`, `build_manifest`, `generate_report`,
  `get_session_summary`, `check_aws_connection` is already done).
- **Knowledge bake** (P2): bake the 15 `knowledge/*` files from
  `claude_aws_agent` into the prompt with `cache_control: ephemeral` for
  Bedrock prompt caching once Claude is back.
- **Production env** (P3): create `infra/envs/prod/` mirroring staging with
  larger sizing, real auth, and read-only IAM until verified.
