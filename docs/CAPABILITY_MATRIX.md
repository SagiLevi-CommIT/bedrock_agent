# Capability Matrix & Efficiency Review

> Snapshot 2026-06-10, after the pre-deployment review pass. "Prod-ready" reflects
> what works **in the currently deployed agent** vs what awaits the gated tool-api
> deployment. Costs assume Athena $5/TB, S3 LIST ~$0.005/1k requests. Native-tool
> cost profiles come from a code audit (file:line in the audit reports); migrated
> numbers from live staging validation.

Legend — **Ready**: ✅ deployed & working today · 🟡 code-complete + live-validated,
needs tool-api deployment (`enable_tool_api`) · 🔴 blocked externally.

| # | Capability | Route today (deployed) | Optimal route (after review) | Data sources | Runtime | AWS cost / call | Ready |
|---|---|---|---|---|---|---|---|
| 1 | Resolve patient id→UUID | `resolve_patient_uuid` (native) | same (tool-api `resolve_patient_context` adds provenance) | Patients API + DynamoDB cache | <0.5 s (cache <10 ms) | ~$0 | ✅ |
| 2 | Latest data date / recency | `latest_data_date_for_patient` | same | Athena `pc_timeseries` MAX(date) | 5–15 s | ~$0.01 | ✅ |
| 3 | Data availability (which days) | `list_patient_files` (S3 LIST) | **`check_data_availability`** (migrated, Israel-local days) | migrated `timeseries` via tool-api | 3–5 s | ~$0.002 | 🟡 (✅ fallback) |
| 4 | Coverage / missing data | `coverage_report_from_athena` (user SQL, up to GBs) | **`get_data_coverage`** (probe-free proven coverage) | migrated discovery | 3–6 s | ~$0.002 | 🟡 (✅ fallback) |
| 5 | File discovery for a window | `find_rt_flow_files_in_window` (LIST + O(log N) probes) | **`get_data_coverage`** / tool-api list (exact keys, 0 probes) | migrated `"$path"` epoch linkage | 3–5 s | ~$0.002 | 🟡 (✅ fallback) |
| 6 | Data-quality summary | (compose 3–5 native calls) | **`summarize_available_files`** (one discovery) | migrated discovery | 3–6 s | ~$0.002 | 🟡 |
| 7 | Compare two nights | (no single tool — manual) | **`compare_sessions`** (two discoveries + deltas) | migrated discovery ×2 | 6–12 s | ~$0.004 | 🟡 |
| 8 | Session inventory (counts/lengths/firmware) | ad-hoc Athena (often misrouted to frozen tables) | **Athena on `metadata`** (LIVE; `time_init`/`time_end`/`record_length`; 181 patients/230k sessions) | `migrated_data.metadata` (~105 MB total) | 3–6 s | **~$0.0005** | ✅ (playbook added) |
| 9 | Arrhythmia event search | `search_files_with_arrhythmia_events` | same (tool-api `find_arrhythmia_events` = same engine + episodes) | Athena `pc_timeseries` + S3 LIST | 15–60 s | $0.05–0.10 | ✅ / 🟡 |
| 10 | Fetch/merge → CSV link (explicit) | `merge_patient_window` — **downloads + pandas-merges INSIDE the agent container** (4 h sleep / 24 h cap) | **`fetch_data` job** (server-side merge → presigned link) | S3 objects → artifacts | 5–30 s / minutes (job) | $0.01–0.10 | ✅ / 🟡 |
| 11 | Presign a known object | `presign_s3_object` | same | S3 | <0.5 s | ~$0 | ✅ |
| 12 | Visualize sleep flow | — none deployed — | **`generate_visualization` job** → hosted viewer + size-capped standalone | S3 → viewer artifacts | minutes (async) | $0.01–0.10 + storage | 🟡 |
| 13 | Visualize rt / single file | — none — | core `run_visualize(rt_single)` exists but **no tool-api job type yet** (gap, backlog) | S3 single file | ~1 min | ~$0.01 | ❌ gap |
| 14 | Cardiolys arrhythmia analysis | — none — | `submit_cardiolys_analysis` job (consent-gated, provenance-separated) | rt_flow CSV → vendor API | ~minutes (≤300 s vendor) | vendor + ~$0.01 | 🔴 secret+legal |
| 15 | Catalog / schema Q&A | Glue tools (`describe_table`…) | same (free) | Glue | <1 s | $0 | ✅ |
| 16 | Ad-hoc analytics (HR/SpO2 trends) | `run_athena_query` + scan-guard | same (LIVE tables; bound `date`; junk 2000-01-01 partition exists) | `pc_timeseries`/`timeseries` | 10–60 s | $0.05–1.00 | ✅ |
| 17 | Usage summary (files/bytes per day) | `patient_usage_summary` (parallel S3 LIST) | same — **byte sizes only exist in S3 LIST** (migrated has no sizes) | S3 LIST ×8 flows | 0.5–1.5 s | ~$0 | ✅ |
| 18 | Upload recency ("last upload") | `find_patient_last_upload` | same — S3 LastModified **is** the upload truth | S3 LIST | 0.5–1.5 s | ~$0 | ✅ |
| 19 | Job status / polling | — | `get_job_status` (+ emits artifact buttons) | tool-api job store | <0.5 s | $0 | 🟡 |
| 20 | Knowledge / playbooks | `list_playbooks`/`get_playbook`/skills | same (+ new `migrated_first`) | local files | <0.1 s | $0 | ✅ |
| 21 | Manual escape hatch (tool UI deep link) | — | `open_tool_ui` action (deep-linked params) | /tool-ui | n/a | $0 | ❌ tool-ui not built |

## Efficiency review notes (why each route is/was chosen)

**3–7 (the migrated-first wins).** Live-validated: 7-day sleep_flow discovery =
**0 S3 calls / ~4.5 s / ~$0.002** via migrated vs **1,052 S3 calls / ~15 s** via
LIST+probe. The blocker (patient_id→UUID) is solved three independent, mutually
agreeing ways (Patients API, DynamoDB cache, migrated epoch-linkage). Routing
fixed this pass: prompt Quick recipes + new `migrated_first` playbook now prefer
the tool-api inspect tools with an explicit native-tool fallback rule when
`TOOL_API_BASE_URL` is unset. *Caveat:* calling 2–3 inspect tools for the same
patient/range repeats the discovery (no cache yet — documented, acceptable at
~$0.002 each; request-scoped memoization is a later optimization).

**8 (new intelligence).** The live scan proved `metadata` is minutes-fresh
(MAX(time_init)= today 14:51), tiny (≈105 MB total → ~$0.0005 full scan), and has
session time windows + firmware. This replaces misrouted frozen-table queries and
expensive per-file probing for "how many sessions / how long / what firmware".

**10 (fetch).** `merge_patient_window` is correct but runs pandas merges **inside
the agent container** (memory + latency risk; capped windows). The `fetch_data`
job moves that server-side with a presigned result. Kept native as the explicit
fallback; prompt updated to prefer the job when configured.

**12 (visualize).** Validated end-to-end on real data (604 MB data.bin). New
size guard (`TOOL_API_STANDALONE_MAX_MB`, default 200) drops oversized standalone
files — the 818 MB single-file artifact observed in validation must never be
presigned; the hosted Range-served viewer is the path for large recordings
(requires the `/artifacts` hosting decision before deploy).

**13 (gap).** rt_flow single-file visualization exists in `core.service`
(`run_visualize` mode `rt_single`, used by CLI/GUI) but was not exposed as a
tool-api job type. Backlog item — small handler + schema addition.

**16 (ad-hoc Athena).** Optimal as-is *because* of the guardrails: scan estimator
+ heavy-scan confirmation + auto-LIMIT + partition rules in prompt. New gotcha
documented: both LIVE tables carry a junk `date=2000-01-01` partition — always
bound date filters.

**17–18 (still S3-native, deliberately).** Byte sizes and upload timestamps only
exist in S3 LIST metadata; migrated_data cannot answer them. These were reviewed
and kept — documented as optimal.

## Permissions / secrets by capability group

| Group | Needs |
|---|---|
| 1, 9 (identity-dependent) | `secretsmanager:GetSecretValue` INTERNAL_TOKEN; DynamoDB patient-id-map RW; Patients API reachability |
| 2, 8, 16 (Athena) | Athena Start/Get; Glue Get*; S3 results-bucket RW |
| 3–7, 12, 19 (tool-api) | agent: `TOOL_API_BASE_URL` (+bearer); tool-api task role: S3 data read-only, artifacts-prefix write, Athena/Glue read, patient-id-map RW, INTERNAL_TOKEN |
| 10–11 (S3) | S3 data read; output-bucket write (merge); presign = caller's own creds |
| 14 (Cardiolys) | **`claude-aws-agent-staging-cardiolyse` secret (MISSING)** + legal clearance + consent |
