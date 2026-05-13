# Flow Decision Tree — "User said X → look here"

This is the routing logic the agent should follow when a user asks about
patient data. The agent should consult this BEFORE constructing a query, to
avoid the most common mistake: scanning the wrong table.

## Step 1: Which flow does the question concern?

| User says... | Flow | Notes |
|---|---|---|
| "ECG", "rhythm", "AFib", "QT", "carsiolyse", "stroke volume", "cardiolyse" | `rt_flow` | Has both rearrangement and post-computation. Cardiolyse runs only on rt_flow. |
| "sleep", "overnight", "PPG only at night", "ACC", "snore" | `sleep_flow` | Rearrangement only. No post-computation. ~25-min chunks. |
| "arrhythmia", "AF", "AR", "trigger" (and **NOT** ECG-rhythm-events) | `ar_flow` or `arrythmia_flow` | Two distinct flows. `ar_flow` is the older "arrhythmia detection" path. `arrythmia_flow` (note the misspelling) is a separate path with rare data. Disambiguate with the user. |
| "AF detection via PPG" | `af_ppg_flow` | Triggered. Small dataset (~810 objects). |
| "tachycardia", "high HR trigger" | `tachycardia_flow` | Triggered. ~426 objects. |
| "plate", "plate device", "ECG plate" | `plate_flow` | Continuous. Has post-computation. |
| "algos", "algorithm experiment" | `algos_flow` | Tiny experimental dataset (3 objects). |

**If the user is vague**, default to:
- `rt_flow` if they mention HR, ECG, or "RT".
- `sleep_flow` if they mention nighttime / sleep.
- ASK if the wording could match multiple flows.

## Step 2: Which stage / table?

```
                                ┌── Point question ("last upload", "files in window") ──→ S3 listing tool (list_patient_files)
                                │
                                ├── Raw signal of one session (PPG/ECG sample-by-sample)
                                │      ├─ rt_flow     → cardiacsense.rt_flow              [38 cols, NO partition, full scan]
Question is per-session ─────────┤      └─ other flows → S3 file directly + parse CSV     [no Glue table]
                                │
                                ├── Cardiolyse-enriched signal of one session
                                │      └─ rt_flow only → cardiacsense.rt_flow_post        [23 cols, NO partition, full scan]
                                │
                                └── Aggregated session-level metrics
                                       ├─ HRV, HR, SpO2, stress, qt → migrated_data.pc_results_part  [date PARTITION, 51 cols, PREFER]
                                       ├─ Cardiolyse-aware timeseries → migrated_data.pc_timeseries  [date PARTITION, 25 cols, hyphenated cols]
                                       └─ Watch metadata               → migrated_data.metadata       [no partition, expensive]

                Cross-cutting question ("anomalous HR for patient over 30 days")
                                └─→ migrated_data.pc_results_part with date BETWEEN ... + GROUP BY
                                    (after Phase 1F, → bedrock_agent.patient_daily rollup)
```

## Step 3: Identifier mapping

The user's "patient ID" might be one of two things:

| Format | Example | Where used |
|---|---|---|
| Integer | `1000`, `605` | `rearrangement/`, `post-computation-layer/`, `processed/`, `default.rt_flow_metadata`, `eventdata.events*`, S3 filenames |
| UUID | `40f2e337-3f7b-4e38-b886-daf27bf4bf16` | `migrated_data.*` tables (`patient` column) |

**There is no direct join.** If the user gives an integer ID and wants
`pc_results_part` data, you must use one of:
- The `migrated_data.metadata` table to find sessions matching the integer
  (via `time_init` overlap with rearrangement filenames). Expensive — full
  scan.
- The `default.rt_flow_metadata` table (rt_flow only, integer + watch_id).
- Ask the user for the UUID directly.

## Step 4: Cost / partition rules per table

| Table | Partition required? | Scan profile if missed |
|---|---|---|
| `migrated_data.pc_results_part` | YES (`date date`) | Massive — multi-GB |
| `migrated_data.pc_timeseries` | YES (`date date`) | Massive |
| `migrated_data.timeseries` | YES (`date string`) | Massive |
| `migrated_data.processed` | YES (`date string` + `patient string`) | Massive |
| `migrated_data.processed1` | YES (`date string` + `patient string`) | Massive |
| `migrated_data.curated` | YES (`session string`) | Moderate |
| `migrated_data.metadata` | NO partition | Always full scan (~215K rows) |
| `migrated_data.pc_results` | NO partition | NEVER use — pc_results_part is the partitioned version |
| `cardiacsense.rt_flow` | NO partition | Full scan over `rearrangement/rt_flow/` |
| `cardiacsense.rt_flow_post` | NO partition | Full scan over `post-computation-layer/rt_flow/` |
| `eventdata.events*` | NO partition | Queries fail — Parquet declared but CSV in S3 |
| `default.rt_flow_metadata` | NO partition | Full scan |

**Rule:** before running any Athena query against a partitioned table, the
SQL must include the partition column in `WHERE`. The agent's
`run_athena_query` tool will warn (and may block in v1) if missed.

## Step 5: When to NOT use Athena

For these question patterns, **start with S3 / cs_downloader tools, not
Athena**:

- "When did patient X last upload?" → `find_patient_last_upload` (LIST with
  prefix narrowing).
- "How many sleep files for patient X in April?" → `list_patient_files` with
  time window.
- "Give me a download link" → `presign_s3_object`.
- "Merge patient X RT data from 14:00–16:00" → `merge_patient_window`.

Athena adds nothing for these — the answer is in the S3 keys themselves.

## Step 6: Worked examples

### "What was patient 1000's heart rate at 23:30 UTC on 2024-12-03?"
1. Flow: `rt_flow` (HR, point-in-time).
2. Stage: post-comp enriched (timeseries).
3. Best path: `migrated_data.pc_timeseries` filtered by
   `date = DATE '2024-12-03' AND patient = '<UUID>' AND sampling_time
   BETWEEN ...`. But user gave integer `1000`, not UUID. Need to map.
4. Fallback: list files in `rearrangement/rt_flow/rt_flow_1000_` matching
   the epoch_ms window, then probe one with `probe_file_time_range`, then
   download/parse the file.

### "How much sleep data did patient 500 record in April 2026?"
1. Flow: `sleep_flow`. No post-comp, no Glue.
2. Use `list_patient_files(patient_id=500, flow='sleep_flow',
   time_window=2026-04-01..2026-04-30)`.
3. Sum file durations from filename-derived start times + an end-time probe
   on the last file in each session.

### "Is the new firmware version causing unstable HR for everyone?"
1. Cross-cutting → `migrated_data.pc_results_part`.
2. Join with `migrated_data.metadata` on `session` to get `fe_version`.
3. Group by `fe_version`, compare HR distribution per version.
4. After Phase 1F, this query goes through `bedrock_agent.patient_daily`
   instead.
