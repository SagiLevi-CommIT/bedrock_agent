# indexing module — Glue tables + daily rollup Lambda

Provisions:

1. **Glue database `bedrock_agent`** — owns the agent's own indexed tables.
2. **`bedrock_agent.sleep_flow_rearrangement_idx`** — Glue table over
   `s3://735555370207-app-events/rearrangement/sleep_flow/` (the largest
   unindexed dataset, 627K objects). LazySimpleSerDe + CSV. Subset of
   the rt_flow column layout — sleep_flow files don't have ECG cols.
3. **`bedrock_agent.patient_daily`** — Parquet rollup partitioned by `dt`
   with partition projection. Schema: per-patient-per-flow daily
   aggregates (file_count, total_bytes, total_duration_min, avg_hr,
   avg_spo2, af_event_count, ...).
4. **`refresh_daily_rollup` Lambda** — runs once a day at 02:00 UTC,
   computes yesterday's `patient_daily` partition.
5. **EventBridge rule** + **IAM role** for the Lambda.

## Known limitations (Phase 1F initial deploy)

- The Lambda ships **without a parquet writer**. It writes a JSON payload
  to `rollup/patient_daily/dt=YYYY-MM-DD/raw_payload.json` instead. Athena
  cannot query this; it's an intermediate. To enable parquet writes:
  - Add `pyarrow` as a Lambda Layer, or
  - Convert this Lambda to a container image with pyarrow + pandas
    bundled.
- Backfill of historical partitions has not been run. The first
  Lambda invocation populates only `dt = yesterday`.
- The `sleep_flow_rearrangement_idx` table is best-effort: sleep_flow CSVs
  may have a different column order from the assumed schema. Always
  `DESCRIBE` it before relying on a column.

## Wire-up

In `infra/envs/staging/main.tf`:

```hcl
module "indexing" {
  source                = "../../modules/indexing"
  name_prefix           = "claude-aws-agent-staging"
  rollup_bucket         = module.data.output_bucket_id
  athena_results_bucket = module.data.athena_results_bucket_id
  athena_workgroup      = "primary"
  agent_glue_database   = "bedrock_agent"
  tags                  = local.tags
}
```

## Manual backfill

```bash
aws lambda invoke \
  --function-name claude-aws-agent-staging-refresh-daily-rollup \
  --payload '{"date":"2026-04-15"}' \
  --profile cardiac-sense-staging \
  out.json
```

Repeat for each historical day you want covered.
