# Caveats & Edge Cases

## CRITICAL: Partition Keys

Many tables have **NO partition keys**. Queries without proper awareness of this will trigger expensive full-table scans.

| Table | Partitioned? | Safe to Query? |
|-------|-------------|----------------|
| `migrated_data.pc_results_part` | YES (`date`) | Yes — always filter by date |
| `migrated_data.timeseries` | YES (`date`) | Yes — always filter by date |
| `migrated_data.pc_timeseries` | YES (`date`) | Yes — always filter by date |
| `migrated_data.processed` | YES (`date`, `patient`) | Yes — filter by both |
| `migrated_data.curated` | YES (`session`) | Yes — filter by session |
| `migrated_data.metadata` | **NO** | Use with caution — full scan |
| `migrated_data.pc_results` | **NO** | **Never use** — use `pc_results_part` instead |
| `cardiacsense.*` | **NO** | **Avoid** — CSV + full scan = very expensive |
| `eventdata.*` | **NO** | Full scan every time |
| `default.*` | **NO** | Full scan every time |

**Important:** `cardiacsense.rt_flow` has a `date` column but it is NOT a partition key. Filtering by `WHERE date = '...'` does NOT reduce scan cost — the entire table is read regardless.

## Patient ID Format Mismatch

- **`migrated_data.*`** tables use UUID strings: `40f2e337-3f7b-4e38-b886-daf27bf4bf16`
- **`eventdata.events`** uses integer IDs: `1000`
- There is **no direct join** between UUID and integer patient IDs without an external mapping table.
- Always ask the user which format their patient ID is in.

## Column Name Inconsistencies

| What | Table A | Table B | Difference |
|------|---------|---------|------------|
| SpO2 | `timeseries.sp_o2` (int) | `pc_results_part.spo2` (float) | Different name AND type |
| Tightness | `tightnes` (misspelled in all tables) | — | Legacy typo in schema |
| ECG quality | `qulity_ecg` (misspelled in timeseries) | — | Legacy typo |
| Rearrangement | `rearangment_version` (misspelled) | — | Legacy typo |
| Crlyse HR | `crlyse-hr` (hyphen in pc_timeseries) | `crlyse_hr` (underscore in rt_flow_post) | Hyphen vs underscore |
| Perturbations | `pertrubations` (misspelled everywhere) | — | Legacy typo |

**Rule:** Always verify the exact column name for the target table before building queries. Don't assume naming is consistent.

## Date Partition Type Mismatch (CRITICAL)

The `date` partition key has **different Athena types** across tables. There is **no single syntax** that works for all tables. The agent auto-corrects this, but you should understand the rules.

### Partition types

| Table | Partition `date` type | Format |
|-------|----------------------|--------|
| `migrated_data.pc_results_part` | **DATE** (native) | CSV/LazySimpleSerDe |
| `migrated_data.pc_timeseries` | **DATE** (native) | Parquet |
| `migrated_data.timeseries` | **STRING** | Parquet |
| `migrated_data.processed` | **STRING** | Parquet |
| `migrated_data.processed1` | **STRING** | Parquet |

### For DATE-type partitions (pc_results_part, pc_timeseries)

```sql
-- CORRECT: DATE literal
WHERE date = DATE '2026-03-24'
WHERE date >= DATE '2026-03-01'
WHERE date BETWEEN DATE '2026-03-20' AND DATE '2026-03-24'

-- CORRECT: date expression (returns DATE)
WHERE date = current_date - interval '1' day
WHERE date >= current_date - interval '7' day

-- CORRECT: CAST date_format to DATE
WHERE date = CAST(date_format(current_date - interval '1' day, '%Y-%m-%d') AS DATE)

-- WRONG → TYPE_MISMATCH:
WHERE date = '2026-03-24'                    -- string vs date
WHERE date = date_format(current_date - interval '1' day, '%Y-%m-%d')  -- varchar vs date
```

### For STRING-type partitions (timeseries, processed, processed1)

```sql
-- CORRECT: string literal
WHERE date = '2026-03-24'
WHERE date >= '2026-03-01'

-- CORRECT: date_format (returns varchar)
WHERE date = date_format(current_date - interval '1' day, '%Y-%m-%d')
WHERE date >= date_format(current_date - interval '7' day, '%Y-%m-%d')

-- WRONG → TYPE_MISMATCH:
WHERE date = DATE '2026-03-24'               -- date vs string
WHERE date = current_date - interval '1' day -- date vs string
WHERE date = CAST('2026-03-24' AS DATE)      -- date vs string
```

### Auto-correction

The agent's query tool (`athena_query.py`) automatically detects which table is being queried and rewrites date filters to the correct type. For example:
- `pc_results_part WHERE date = '2026-03-24'` → auto-converts to `DATE '2026-03-24'`
- `timeseries WHERE date = DATE '2026-03-24'` → auto-removes the `DATE` keyword
- `timeseries WHERE date = current_date - interval '1' day` → auto-wraps in `date_format()`
- Queries joining both types get a warning (no auto-fix possible).

## Timestamp Format Varies

| Table | Column | Type | Notes |
|-------|--------|------|-------|
| `migrated_data.timeseries` | `sampling_time` | timestamp | Native timestamp |
| `migrated_data.metadata` | `time_init`, `time_end` | timestamp | Native timestamp |
| `migrated_data.pc_results_part` | `resp_rate_time` | timestamp | Native timestamp |
| `cardiacsense.rt_flow` | `sampling_time` | bigint | Epoch milliseconds |
| `cardiacsense.rt_flow_post` | `sampling_time` | string | Epoch as string |
| `default.rt_flow_metadata` | `time_init`, `time_end` | string | Timestamp as string |

Converting epoch ms to timestamp: `from_unixtime(sampling_time / 1000)`

## Data Quality

### Bogus Partitions
`date=2000-01-01` partitions exist in timeseries and pc_results. These are malformed/test data. Exclude them: `AND date != '2000-01-01'`

### Quality Indicators
- `sqi` — Signal Quality Index (higher = better). Filter out low SQI for reliable analysis.
- `artifact` / `artifact_flag` — Signal corruption. High artifact = low reliability.
- `tightnes` — Watch tightness. Too loose = unreliable PPG.
- `lead_state` — ECG lead contact. 0 = no contact, 1 = good contact.
- `snr` — Signal-to-noise ratio. Higher = better.
- `low_snr` — Flag for low SNR readings.
- `qulity_ecg` — ECG quality flag (misspelled in schema).

### Heart Rate Sources
Two HR columns: `hr_ppg` (optical PPG) and `hr_ecg` (ECG leads). They may differ. ECG is more accurate when `lead_state = 1`.

### Carsiolyse Computed Fields
`pc_results_part` contains ML-computed health scores from the Carsiolyse algorithm: `emotional`, `stress`, `stamina`, `myocardium`, `overall`, `heart_biological_age`, `risk_cardiovascular_events`, `heart_rhythm_disturbances`. These are derived metrics, not raw measurements.

### Sleep Data
- Sleep sessions: `file_type = 'sleep_flow'`
- Filter by `file_type`, don't assume time of day.
- Short sessions (< few minutes) may be accidental.

### Metadata Table Cost
`migrated_data.metadata` has 70 columns and NO partitions. Every query does a full scan. When possible, get session info from `pc_results_part` (which is partitioned) and only hit `metadata` for device-specific fields.

## AWS-Specific

- **Region:** `eu-central-1` (Frankfurt)
- **Account:** `735555370207` (staging)
- **Athena workgroup:** `primary`
- **Cost:** Athena charges per data scanned. Parquet + partitions = cheap. CSV + no partitions = 10-100x more expensive.
- **Read-only:** Only SELECT, DESCRIBE, SHOW allowed. All DDL/DML blocked.

## Discovered 2026-05-02 (live-verified)

### `incoming/` no longer holds `cs_events_*.csv`
The S3 prefix `s3://735555370207-app-events/incoming/` now contains a single
sample binary file (`incoming/sleep_flow_110_1775241259384.dat.zip`). The old
`cs_events_*.csv` raw format has been retired from this prefix. `cs_events_*.csv`
files exist only under `processed/` today.

### `cardiacsense.rt_flow_rearrangement` is a stale "all-string" view
Both `cardiacsense.rt_flow` (38 columns, LazySimpleSerDe, typed) and
`cardiacsense.rt_flow_rearrangement` (23 columns, OpenCSVSerde, all string) point
to the **same S3 prefix** `rearrangement/rt_flow/`. The 23-column view inherits
the post-computation column list (including `crlyse_hr`, `perfusion_index`,
etc.) which the raw rearrangement files do **not** contain. Queries against
`rt_flow_rearrangement` return mostly empty/null values for those columns.
**Always prefer `cardiacsense.rt_flow`** for raw rearrangement queries.

### Post-computation only exists for 3 flows
`s3://735555370207-app-events/post-computation-layer/` has only `rt_flow/`,
`arrythmia_flow/`, and `plate_flow/` sub-prefixes. `sleep_flow`, `ar_flow`,
`af_ppg_flow`, `tachycardia_flow`, and `algos_flow` go straight from
`rearrangement/` to migration without a post-computation stage.

### Empty folder-marker objects everywhere
Almost every S3 prefix in `735555370207-app-events` contains a 0-byte object
whose key ends in `/` (e.g., `incoming/`, `rearrangement/`, `processed/`,
`post-computation-layer/plate_flow/`). Any tool that lists objects must filter
out keys ending in `/`.

### New prefixes not in the inherited inventory
- `doctor-realtime-session/` — clinical doctor↔patient session JSONs.
  Pattern: `realtime-doctorId-{doctor_id}-pId-{patient_id}-{epoch_ms}.json` (and
  variants `realtime-docId-...` and `{doctor_id}-{patient_id}-realtime.json`).
- `interesting_files/`, `misc/`, `tmp/`, `rt-sessions-pdf/`,
  `incoming_plate_dat_files/` — present but uninspected. Treat as out-of-scope
  unless the user asks.

### `meta-data-parquet/` exists but is not in Glue
`s3://735555370207-migrated--data/meta-data-parquet/` mirrors `meta-data/` as
Parquet but is **not registered as a Glue table**. The agent's `metadata`
queries hit the CSV (no partition, expensive scan). If you need cross-cutting
metadata analytics often, prefer reading the parquet directly via S3 Select or
register the parquet as a partitioned table in Phase 1F.

### Migration pipeline state (verified 2026-05-03)

| Table | Status | Last data |
|---|---|---|
| `migrated_data.timeseries` | LIVE | 2026-05-03 (today) |
| `migrated_data.pc_timeseries` | LIVE | 2026-05-02 |
| `migrated_data.metadata` | LIVE | 2026-05-03 09:35 |
| `migrated_data.pc_results_part` | **FROZEN** | 2025-07-07 — ~10 months old |
| `migrated_data.processed` | **FROZEN** | 2025-09-13 — ~8 months old |

The Lambdas (`re-arrangement`, `computation-layer`) are alive — both ran 142
times in the last 24h. What broke is the downstream session-rollup job that
populates `pc_results_part` and `processed`. It is NOT a per-patient lag —
ALL 122 patients show the same 2025-07-07 cutoff in `pc_results_part`.

**Implication for analytics queries:** for HR / Cardiolyse / SpO2 / trends,
default to `pc_timeseries` (sample-level, LIVE) and `timeseries` (raw +
SpO2). Treat `pc_results_part` as a historical archive only, valuable for
comparing pre-2025-07-07 baselines but never for "last month" questions.

### Athena column-name reference table

| Concept | Where | Exact column name |
|---|---|---|
| Cardiolyse HR | `cardiacsense.rt_flow_post` | `crlyse_hr` (string) |
| Cardiolyse HR | `migrated_data.pc_timeseries` | `` `crlyse-hr` `` (double, **hyphenated** — backticks required) |
| Cardiolyse annotation | `cardiacsense.rt_flow_post` | `crlyse_annotation` (string) |
| Cardiolyse annotation | `migrated_data.pc_timeseries` | `` `crlyse-annotation` `` (string, **hyphenated**) |
| Cardiolyse rhythm events | `cardiacsense.rt_flow_post` | `crlyse_rythem_events` (string) |
| Cardiolyse rhythm events | `migrated_data.pc_timeseries` | `` `crlyse-rythem_events` `` (string, **hyphenated**) |
| ECG quality | `migrated_data.timeseries` | `qulity_ecg` (**int**, not string flag) |
| Tightness | `migrated_data.timeseries` | `tightnes` (double) + `tightnes_level` (int) |
| Perturbations | `migrated_data.metadata` | `pertrubations` (float) |
| Rearrangement version | `migrated_data.metadata`, `default.rt_flow_metadata` | `rearangment_version` (string) |
| Watch ID | `default.rt_flow_metadata` only | `watch_id` (string) — **does not exist in `migrated_data.metadata`** |
