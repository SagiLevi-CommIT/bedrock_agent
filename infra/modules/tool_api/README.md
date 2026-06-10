# Module: `tool_api` (implemented `.tf`; wired DISABLED; apply gated)

Deploys the deterministic data tool's HTTP API (`tool_api/` in the
`CardiacSense-s3-downloader-tool` repo) as a second ECS service in the **same
cluster** behind the **same** ALB/WAF/VPC (path `/tool-api/*`), reusing the
platform so we don't pay twice.

> Status: **`main.tf` / `variables.tf` / `outputs.tf` are real and pass
> `terraform validate`** (Success). The module is wired into
> `infra/envs/staging/main.tf` as `module "tool_api" { count = var.enable_tool_api ? 1 : 0 }`
> — **disabled by default**, so the live `terraform plan` is unchanged. Enabling
> needs `enable_tool_api=true` + `tool_api_image_tag`;
> `terraform apply` requires explicit approval (AWS-safety).

## What this module creates

- **ECR repo** (`<prefix>-backend`, immutable SHA tags) — the tool repo's
  `Dockerfile.api` image is pushed here (no CodeBuild pipeline yet; manual
  `docker build`/`push`, see `DEPLOY.md`).
- **Exec role** (ECR pull + logs + injecting the API token secret) and a
  **least-privilege task role**: read-only on data buckets, write only to
  `artifacts/*` in the output bucket, Athena/Glue read, RW on the shared
  patient-id-map table, `GetSecretValue` on `INTERNAL_TOKEN` (+ extras).
  **No** `s3:Delete*` on data, no `glue:Create*`, no IAM mutation.
- **API bearer token** — a generated `random_password` stored in Secrets
  Manager under a **deterministic name** (`var.api_token_secret_name`,
  staging: `claude-aws-agent-staging-tool-api-token`). Injected into the
  container as `TOOL_API_TOKEN` (the app then enforces bearer auth on
  `/v1/*`); the agent reads the same secret at runtime via its
  `TOOL_API_TOKEN_SECRET_NAME` env. The name is passed in (not exported)
  because the agent's `ecs`/`iam` modules cannot consume this module's
  outputs — `tool_api` uses the agent's cluster, so that would be a cycle.
- **Private agent→tool-api path**: Cloud Map namespace (`cs-internal`) +
  service registry (DNS `tool-api.cs-internal`) and a count-gated
  self-referencing ingress rule on the shared ECS SG. This exists because the
  **WAF default-blocks** non-office IPs — the agent task cannot call the
  public ALB. The agent's env gets
  `TOOL_API_BASE_URL=http://tool-api.cs-internal:8000` (empty while disabled →
  wrappers fail cleanly and the prompt falls back to native tools).
- **ALB target group + `/tool-api/*` listener rule** for browser/operator
  calls (WAF office-allowlist + bearer). The container gets
  `TOOL_API_ROOT_PATH=/tool-api` so the app strips the prefix (ALBs cannot).
- **ECS service** in the existing cluster + CPU autoscaling.

## Settled decisions (were plan §16)

1. **Infra ownership** — this shared stack (the tool repo ships only the image).
2. **Artifacts/viewer** — **standalone-first**: jobs publish a presigned
   single-file `index_standalone.html` (capped by `TOOL_API_STANDALONE_MAX_MB`,
   default 200). No hosted `/artifacts` Range route and no CloudFront this
   phase; the recording folder (`data.bin`) is not even uploaded.
3. **`/tool-ui` web app** — deferred; no `open_tool_ui` buttons are emitted.
4. **Jobs** — in-process v1 (state lost on task restart; acceptable for
   staging). Revisit SQS+worker on real load.
5. **`/tool-api` auth** — generated static bearer (above), Cognito/JWT later.
6. **Cardiolys** — still gated: provision `claude-aws-agent-staging-cardiolyse`
   + legal clearance before enabling the external send (code + 412 consent
   gate are already in the image).

## Validated deployment requirements (live staging, 2026-06-10)

Proven by live read-only validation (see `CardiacSense-s3-downloader-tool/docs/E2E_VALIDATION_AND_INTELLIGENCE.md`):

- **Resolver MUST be configured** or migrated discovery silently degrades to slow legacy S3 scanning. In the tool's deployed config set `patient_resolver.get_patient_url` (staging Patients API), `internal_token_secret_name=INTERNAL_TOKEN`, `patient_id_map_table=claude-aws-agent-staging-patient-id-map` (the same resolver the agent uses; both share that DynamoDB cache). Grant the task role `secretsmanager:GetSecretValue` on `INTERNAL_TOKEN` + DynamoDB RW on the map table. *Validated:* with this set, `/v1/availability` + `/v1/discover` flip to `strategy=migrated`. (The baked `config.staging.json` sets all of this, incl. `discovery.mode=auto`.)
- **`TOOL_API_ARTIFACTS_BUCKET=claude-aws-agent-staging-output-735555370207`** (exists; task-role write to `artifacts/*` only). *Validated:* upload + presigned GET returns HTTP 200.
- **Large recordings:** a full-day sleep_flow recording produced an **818 MB standalone** — the size guard (`TOOL_API_STANDALONE_MAX_MB`, default 200) drops it and the job returns a "shorten the range" note instead of a link.
- **Config footgun:** the tool's `config.json` defaults to **prod with baked keys** — the image bakes `config.staging.json` with empty keys (task role) + `account_id=735555370207`.
- **Bedrock note:** the deployed `mistral.devstral-2-123b` *does* support Converse tool-use (validated) — agent orchestration works without Claude, though Claude (SCP-gated) would be more reliable for multi-step turns.

## Apply (GATED — requires explicit approval)
See `DEPLOY.md` → "Deploying the Tool API": targeted apply for the ECR repo →
manual `docker build -f Dockerfile.api` + push → full `terraform apply` →
`aws ecs wait services-stable` → live smoke (`GET /tool-api/health`, one
`/v1/availability`). Do **not** apply without sign-off.
