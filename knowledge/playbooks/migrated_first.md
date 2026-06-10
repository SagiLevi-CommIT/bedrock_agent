# Migrated-first routing — when migrated_data beats S3 scanning

**Retrieval hierarchy (always, for any data-location question):**
1. migrated_data / DB mapping (patient_id↔UUID, `resolve_patient_context`)
2. indexed migrated discovery — the data-tool wrappers (`check_data_availability`,
   `get_data_coverage`, `patient_timeline`, `compare_sessions`): 0 S3 probes
3. native S3 / Athena scans — ONLY as a fallback (tool-api down, or a question
   migrated can't answer: byte sizes, raw key browsing, per-sample values)

Never bypass migrated_data when steps 1–2 can answer the question.

**Rule of thumb:** for *"does data exist / which days / where are the files / is it
complete / how many sessions / upload timeline"* questions, **migrated_data answers
in one cheap Athena query what S3 scanning needs hundreds of calls for.** Validated on staging
(2026-06-10): 7-day sleep_flow discovery = 0 S3 calls / ~4.5 s via migrated vs
1,052 S3 calls / ~15 s via legacy listing+probing.

## Route by question type

| Question | Use | Why |
|---|---|---|
| "What data exists / which days?" | `check_data_availability` | one migrated query, per-day buckets (Israel-local days) |
| "Any missing data / gaps / complete?" | `get_data_coverage` | proven per-file coverage from migrated, no probing |
| "Which files cover this window?" | `get_data_coverage` / tool-api list | exact app-events keys rebuilt via epoch linkage |
| "How many sessions / since when / firmware?" | Athena on `migrated_data.metadata` | **whole table ≈ 105 MB (~$0.0005)**; has `time_init`, `time_end`, `record_length`, `fe_version`; 181 patients / 230k sessions |
| "Compare two nights" | `compare_sessions` | two migrated discoveries + deltas |
| "Download / merge a window" | `fetch_data` (job) — NOT `merge_patient_window` | server-side; `merge_patient_window` downloads + pandas-merges *inside the agent container* |
| Upload recency, byte sizes, raw key browsing | native S3 tools (`find_patient_last_upload`, `patient_usage_summary`, `explore_s3`) | S3 LIST metadata is the source of truth for *uploads/bytes*; migrated has no byte sizes |
| Raw sample values / signals | `run_athena_query` on `timeseries` / `pc_timeseries` | per-sample data lives there, not in S3 listings |

**Fallback:** if a data-tool wrapper returns `ERROR: ... TOOL_API_BASE_URL is not
configured` (tool-api not deployed), fall back to the native tools:
`list_patient_files` (file location), `coverage_report_from_athena` (coverage),
`merge_patient_window` (merge — small windows only).

## Table freshness map (verified live 2026-06-10 via Glue partitions)

| Table | Freshness | Partitions | Use for |
|---|---|---|---|
| `timeseries` | **LIVE (partition = today)** | `date` STRING | raw signals (`ppg`,`ecg`,`sp_o2`,`respiration_rate`), file discovery via `"$path"` |
| `pc_timeseries` | **LIVE (partition = today)** | `date` DATE | HR/Cardiolyse/post-computation analytics |
| `metadata` | **LIVE (MAX(time_init) = today 14:51)** | none (~105 MB total) | session inventory: `time_init`/`time_end`/`record_length`, firmware, `patient_yob` |
| `processed` | FROZEN 2025-09-13 | `date` STRING | legacy ECG segments only |
| `processed1` | FROZEN 2025-09-05 | `date` STRING + **`patient`** | legacy; patient-partitioned (cheap pruning) but stale |
| `pc_results_part` | FROZEN 2025-07-07 | `date` DATE | explicit pre-July-2025 history only |
| `pc_results` | junk-dated writes (date=2000-01-01 as late as 2025-10) | none | **avoid** — use `pc_timeseries` |
| `curated` | ML labeling dataset | `session` | labeled ECG segments (`label`, `sqi`, `rms`) — not for discovery |

**Gotchas:**
- Both LIVE tables contain a junk `date=2000-01-01` partition — **always bound the
  date filter** (`WHERE date BETWEEN ...`), never open-ended.
- `patient` columns are **UUIDs** — resolve via `resolve_patient_context` /
  `resolve_patient_uuid` first; NEVER substring-match an integer id.
- Epoch linkage: migrated parquet filename epoch == app-events CSV filename epoch,
  e.g. `.../date=2024-12-04/rt_flow_1733268398000.parquet` ⇄
  `rearrangement/rt_flow/rt_flow_1000_1733268398000.csv` — this is how the
  data tool rebuilds exact S3 keys with zero probing.
- `metadata` (one cheap scan) also answers reverse questions: "which patients have
  rt_flow data?", "how long are patient X's sessions?", "what firmware did the
  watch run that night?".
