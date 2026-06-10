# Deployment runbook (staging)

Live URL (HTTP, IP-allowlisted by WAF — office CIDRs in `terraform.tfvars`
`office_cidrs` reach the ALB):

> http://claude-aws-agent-staging-alb-346464057.eu-central-1.elb.amazonaws.com

Open that URL in a browser to use the chat UI. The same host serves `/api/*`
for programmatic access; both share the WAF + ALB.

**Account:** `735555370207`  
**Region:** `eu-central-1`  
**AWS CLI profile (operators):** `cardiac-sense-staging` — use this for Terraform,
CodeBuild, ECS, Athena, Secrets Manager, and IAM reads needed by plans.

## Current validated deployment (staging)

As of **2026-05-13** the stack was applied and smoke-tested end-to-end:

| Check | Result |
|--------|--------|
| **ECR image tag** | `6865802c` |
| **ECS task definition** | `claude-aws-agent-staging-task:22` |
| **`GET /api/health`** | `tools` **28**, model `mistral.devstral-2-123b` |
| **`GET /api/info`** | Sorted list of all **28** tool names (same registry as health) |
| **Athena scan guard** | Live: `run_athena_query` returned `BLOCKED:` when estimated scan exceeded `ATHENA_MAX_SCAN_GB_DEFAULT` without `confirm_heavy_scan=true` |
| **`record_run_advice`** | Live: wrote markdown under `s3://…/advice/raw/…` in the agent output bucket |
| **`scripts/sync_advice.py --dry-run`** | Live: listed keys under `advice/raw/` using staging credentials |

Teammates: keep **local** `infra/envs/staging/terraform.tfvars` aligned (that file is **gitignored**). Copy from `terraform.tfvars.example` and set `aws_profile` and `image_tag` after each CodeBuild. You can override profile on one shot with:

```bash
terraform apply -var="aws_profile=cardiac-sense-staging"
```

On **PowerShell**, always quote the backend file when initializing:

```powershell
terraform init -input=false "-backend-config=backend.hcl"
```

Use **`curl.exe`** (not `curl`) for quick HTTP checks so the request is not handled by `Invoke-WebRequest`.

## Quick checks

```bash
export AWS_PROFILE=cardiac-sense-staging
export AWS_DEFAULT_REGION=eu-central-1

ALB="http://claude-aws-agent-staging-alb-346464057.eu-central-1.elb.amazonaws.com"

# UI
curl.exe -I "$ALB/"
# 200 text/html (Vite-built SPA)

# API — expect tools: 39 (28 native + 11 data-tool wrappers)
curl.exe "$ALB/api/health"
# {"status":"ok","region":"eu-central-1","model":"mistral.devstral-2-123b","tools":39}

curl.exe "$ALB/api/info"
# {"service":"bedrock_agent","phase":"ui","tools":[ ... 39 sorted names ... ]}

# Tool API (only when enable_tool_api=true; bearer = the
# claude-aws-agent-staging-tool-api-token secret)
curl.exe "$ALB/tool-api/health"
# {"status":"ok","service":"tool_api", ...}

curl.exe -X POST "$ALB/api/chat" -H "Content-Type: application/json" \
  -d "{\"prompt\":\"Call check_aws_connection and reply in one sentence.\"}"
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
export AWS_PROFILE=cardiac-sense-staging   # default in scripts/build_and_push.sh
git commit ...                             # land your change
bash scripts/build_and_push.sh             # zips app+ui+prompts+knowledge+skills → S3 → CodeBuild
                                           # prints the new image_tag (8-char git SHA)

# Edit local (gitignored) infra/envs/staging/terraform.tfvars:
#   image_tag = "<sha-from-CodeBuild>"
cd infra/envs/staging
terraform init -input=false -backend-config=backend.hcl   # once per machine
terraform apply
aws ecs wait services-stable \
  --cluster claude-aws-agent-staging-cluster \
  --services claude-aws-agent-staging-svc
```

Windows **PowerShell** one-liner alternative for CodeBuild (same as `build_and_push.sh`): see
`scripts/deploy_staging.ps1` (`-AwsProfile` defaults to `cardiac-sense-staging`).

Rolling back is the same flow with a previous SHA. Image tags are immutable;
ECR keeps the last 20.

## Bedrock model — and the SCP problem

> **The org SCP `arn:aws:organizations::071204572266:policy/.../p-lwuwinuh`
> currently denies `bedrock:InvokeModel` on every `anthropic.*` foundation
> model in this account.** Verified 2026-04-29 against the EU geo profile,
> the Global profile, and direct foundation-model ARNs for Sonnet 4.5,
> Haiku 4.5, and Sonnet 4.

**Live chat model in staging** (not blocked by the SCP):

```
mistral.devstral-2-123b   (eu-central-1, in-region)
```

**The codebase is set up to swap to Claude with a `terraform.tfvars` / env
change** (the IAM grant already covers `anthropic.*`):

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
primarily an env-var change once the SCP allows it.

## Tool registry (39)

Authoritative list: **`GET /api/info`** (sorted names) or **`len(REGISTRY)`**
via **`GET /api/health`** (`tools` field). Implementations live under
`app/src/tools/` and are registered in `app/src/tools/__init__.py`.
28 native `boto3` tools + 11 `httpx` wrappers (`app/src/tools/data_tool.py`)
that call the deterministic Tool API; the wrappers fail with a clean
"not configured" error (and the prompt routes to native tools) while
`enable_tool_api=false`.

## Deploying the Tool API (second ECS service)

The deterministic data tool (`CardiacSense-s3-downloader-tool` repo) ships as
its own image and ECS service behind the same ALB (`/tool-api/*`) + a private
Cloud Map DNS (`tool-api.cs-internal:8000`) for agent→tool calls. Everything is
gated by `enable_tool_api` (default `false` ⇒ zero live resources).

```bash
# 0. One-time: create the tool ECR repo (module is count-gated, so target it)
#    Set in local terraform.tfvars first:
#      enable_tool_api    = true
#      tool_api_image_tag = "<tool-repo-short-sha>"
cd infra/envs/staging
terraform apply -target='module.tool_api[0].aws_ecr_repository.this'

# 1. Build + push the tool image (manual docker this round; no CodeBuild yet)
cd ../../../../CardiacSense-s3-downloader-tool
TAG=$(git rev-parse --short HEAD)
REPO=735555370207.dkr.ecr.eu-central-1.amazonaws.com/claude-aws-agent-staging-tool-api-backend
aws ecr get-login-password --profile cardiac-sense-staging | docker login --username AWS --password-stdin 735555370207.dkr.ecr.eu-central-1.amazonaws.com
docker build -f Dockerfile.api -t "$REPO:$TAG" .
docker push "$REPO:$TAG"

# 2. Full apply + wait (back in bedrock_agent/infra/envs/staging)
terraform apply
aws ecs wait services-stable --cluster claude-aws-agent-staging-cluster \
  --services claude-aws-agent-staging-svc claude-aws-agent-staging-tool-api-svc
```

Auth: the apply generates the bearer secret
`claude-aws-agent-staging-tool-api-token`; the tool container gets it injected
as `TOOL_API_TOKEN`, the agent reads it at runtime via
`TOOL_API_TOKEN_SECRET_NAME`. Rollback = previous SHA in `tool_api_image_tag`
(disable entirely with `enable_tool_api=false`).
Artifacts (presigned standalone viewer / CSVs) land under
`s3://claude-aws-agent-staging-output-735555370207/artifacts/<job_id>/`.

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
- **Knowledge / skills** (P2): expand curated lessons and prompt caching once
  Claude is available in-region.
- **Production env** (P3): create `infra/envs/prod/` mirroring staging with
  larger sizing, real auth, and read-only IAM until verified.

## Legacy AWS profile name (do not use for deploys)

Older copies of runbooks referenced **`cardiac-sense-staging-s3`**. That name
was tied to a **narrow IAM user** (`accessS3`) suitable for limited S3 access
only — it **cannot** run Terraform plans, CodeBuild, `secretsmanager:DescribeSecret`,
Glue catalog reads needed by apply, or ECS management. **All operator docs and
scripts in this repo now standardize on `cardiac-sense-staging`.**
