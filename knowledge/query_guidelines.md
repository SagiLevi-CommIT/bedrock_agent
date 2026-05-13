# Query Guidelines — Cost-Aware Data Access

## Table Selection Decision Tree

```
What do you need?
│
├─ Aggregate vitals (HR, SpO2, HRV, AF, stress)?
│  → migrated_data.pc_results_part  (DATE partition, CSV, ~51 cols)
│    FILTER: date >= DATE 'YYYY-MM-DD'
│    FILTER: file_type = '{flow}' if specific flow needed
│
├─ Raw timeseries (PPG, ECG, accelerometer samples)?
│  → migrated_data.timeseries  (string partition, Parquet, 41 cols)
│    FILTER: date = 'YYYY-MM-DD'
│    FILTER: file_type = '{flow}' if specific flow needed
│
├─ Enriched timeseries (+ perfusion, stroke volume, Carsiolyse)?
│  → migrated_data.pc_timeseries  (DATE partition, Parquet, 25 cols)
│    FILTER: date = DATE 'YYYY-MM-DD'
│
├─ ECG segments with quality scores?
│  → migrated_data.processed  (string partition: date + patient, Parquet)
│    FILTER: date = 'YYYY-MM-DD' AND patient = 'UUID'
│
├─ Session metadata (watch, versions, timing)?
│  → migrated_data.metadata  ⚠ FULL SCAN — use LIMIT, be specific
│    Always add: LIMIT 100 (or less)
│
├─ ML/labeled data?
│  → migrated_data.curated  (session partition, Parquet)
│    FILTER: session = 'UUID'
│
├─ Clinical events?
│  → ⚠ eventdata.events is BROKEN (Parquet/CSV mismatch)
│    No safe alternative currently available
│
├─ Raw CSV rt_flow (pre-migration)?
│  → cardiacsense.rt_flow  ⚠ FULL SCAN, no partition
│    Last resort only. Prefer migrated_data.timeseries.
│
└─ Post-computation CSV (pre-migration)?
   → cardiacsense.rt_flow_post  ⚠ FULL SCAN, no partition
     Last resort only. Prefer migrated_data.pc_timeseries.
```

## Cost Profiles by Table

| Table | Format | Partition | Cost | Scan per Query | Recommendation |
|-------|--------|-----------|------|----------------|----------------|
| `pc_results_part` | CSV | `date` (DATE) | LOW | ~1 day of data | **Default for vitals** |
| `timeseries` | Parquet | `date` (string) | MEDIUM | ~1 day (Parquet efficient) | **Default for raw signals** |
| `pc_timeseries` | Parquet | `date` (DATE) | MEDIUM | ~1 day (Parquet efficient) | Good for enriched signals |
| `processed` | Parquet | `date` + `patient` | LOW | Very targeted | Good for ECG segments |
| `processed1` | Parquet | `date` + `patient` | LOW | Very targeted | Same as processed + filtered ECG |
| `curated` | Parquet | `session` | LOW | Single session | ML data only |
| `metadata` | CSV | **NONE** | **VERY HIGH** | Full table (~215K rows) | Avoid or LIMIT strictly |
| `pc_results` | CSV | **NONE** | **HIGH** | Full table | **NEVER USE** — use `pc_results_part` |
| `rt_flow` | CSV | **NONE** | **HIGH** | Full table | Last resort |
| `rt_flow_post` | CSV | **NONE** | **HIGH** | Full table | Last resort |
| `events` | Broken | N/A | **BROKEN** | N/A | Queries fail |

## Mandatory Filters

### Always Include Date Filter on Partitioned Tables

```sql
-- pc_results_part, pc_timeseries (DATE type partition)
WHERE date >= DATE '2026-03-01'

-- timeseries, processed (string type partition)
WHERE date = '2026-03-25'

-- The athena_query.py tool auto-corrects date types,
-- but writing the correct type avoids confusion.
```

### Always Include file_type When Querying Shared Tables

Tables like `timeseries` and `pc_results_part` contain multiple flow types. Without a `file_type` filter, you get mixed results:

```sql
-- Good: specific flow
WHERE date = '2026-03-25' AND file_type = 'rt_flow'

-- Bad: mixed flow types in results
WHERE date = '2026-03-25'
```

### Always LIMIT on Unpartitioned Tables

```sql
-- metadata: always limit
SELECT session, patient, hardware_version FROM migrated_data.metadata LIMIT 50

-- rt_flow: always limit
SELECT * FROM cardiacsense.rt_flow LIMIT 10
```

## Anti-Patterns (NEVER DO)

### 1. Query pc_results Instead of pc_results_part

```sql
-- WRONG: full table scan
SELECT * FROM migrated_data.pc_results WHERE date = '2026-03-25'

-- RIGHT: partitioned, fast
SELECT * FROM migrated_data.pc_results_part WHERE date = DATE '2026-03-25'
```

### 2. Query cardiacsense.rt_flow Without Understanding the Cost

```sql
-- EXPENSIVE: rt_flow has NO partition, date is a regular column
SELECT * FROM cardiacsense.rt_flow WHERE date = '2026-03-25'
-- This scans ALL data even though it looks filtered!

-- BETTER: use migrated_data.timeseries
SELECT * FROM migrated_data.timeseries WHERE date = '2026-03-25' AND file_type = 'rt_flow'
```

### 3. Join metadata Without LIMIT

```sql
-- VERY EXPENSIVE: metadata is a full scan + cross join potential
SELECT t.*, m.hardware_version
FROM migrated_data.timeseries t
JOIN migrated_data.metadata m ON t.session = m.session
WHERE t.date = '2026-03-25'

-- SAFER: get metadata separately with LIMIT
SELECT session, hardware_version, time_init, time_end
FROM migrated_data.metadata
WHERE session = 'specific-session-id'
LIMIT 10
```

### 4. Query eventdata.events

```sql
-- BROKEN: Glue says Parquet, files are CSV
SELECT * FROM eventdata.events
-- Result: HIVE_BAD_DATA: Malformed Parquet file
```

### 5. Forget Date Filter on Partitioned Table

```sql
-- EXPENSIVE: scans all 969 date partitions
SELECT COUNT(*) FROM migrated_data.timeseries WHERE patient = 'some-uuid'

-- CHEAP: scans 1 partition
SELECT COUNT(*) FROM migrated_data.timeseries WHERE date = '2026-03-25' AND patient = 'some-uuid'
```

## Safe Query Templates

### Daily Patient Count

```sql
SELECT date, COUNT(DISTINCT patient) as patients, COUNT(DISTINCT session) as sessions
FROM migrated_data.pc_results_part
WHERE date >= DATE '2026-03-20'
GROUP BY date
ORDER BY date DESC
```

### Patient Vitals Summary

```sql
SELECT session, patient, hr, spo2, resp_rate, stress_index, sdnn, rmssd, af, date
FROM migrated_data.pc_results_part
WHERE date >= DATE '2026-03-20'
  AND patient = 'UUID-HERE'
ORDER BY date DESC
LIMIT 50
```

### Sleep Sessions with Low SpO2

```sql
SELECT session, patient, spo2, hr, date
FROM migrated_data.pc_results_part
WHERE date >= DATE '2026-03-01'
  AND file_type = 'sleep_flow'
  AND spo2 < 90
ORDER BY spo2 ASC
LIMIT 100
```

### Timeseries Sample for a Session

```sql
SELECT sampling_time, ppg, ecg, hr_ppg, hr_ecg, sp_o2, tightnes
FROM migrated_data.timeseries
WHERE date = '2026-03-25'
  AND session = 'SESSION-ID-HERE'
ORDER BY sampling_time
LIMIT 1000
```

### Data Gap Detection

```sql
SELECT
  sampling_time,
  LEAD(sampling_time) OVER (ORDER BY sampling_time) AS next_sample,
  LEAD(sampling_time) OVER (ORDER BY sampling_time) - sampling_time AS gap_ms
FROM migrated_data.timeseries
WHERE date = '2026-03-25'
  AND patient = 'UUID-HERE'
  AND file_type = 'rt_flow'
ORDER BY sampling_time
LIMIT 1000
```

### ECG Quality Check

```sql
SELECT segment_id, AVG(sqi) as avg_sqi, AVG(kurtosis) as avg_kurtosis, COUNT(*) as samples
FROM migrated_data.processed
WHERE date = '2026-03-25'
  AND patient = 'UUID-HERE'
GROUP BY segment_id
ORDER BY avg_sqi DESC
LIMIT 50
```

## Date Partition Type Reference

| Table | Partition Type | Correct Filter | Auto-Corrected |
|-------|---------------|----------------|----------------|
| `pc_results_part` | DATE | `date >= DATE '2026-03-25'` | Yes |
| `pc_timeseries` | DATE | `date = DATE '2026-03-25'` | Yes |
| `timeseries` | string | `date = '2026-03-25'` | Yes |
| `processed` | string | `date = '2026-03-25'` | Yes |
| `processed1` | string | `date = '2026-03-25'` | Yes |
| `metadata` | NONE | N/A (no partition) | N/A |
| `curated` | string (session) | `session = 'UUID'` | No |

The `athena_query.py` tool auto-detects the table and rewrites date filter syntax to match the partition type. You can write either syntax and it will be corrected at execution time.

## Column Name Gotchas

| Column | Table(s) | Correct Spelling | Expected Spelling |
|--------|----------|-----------------|-------------------|
| `tightnes` | timeseries, rt_flow | `tightnes` | `tightness` |
| `qulity_ecg` | timeseries, rt_flow | `qulity_ecg` | `quality_ecg` |
| `pertrubations` | timeseries | `pertrubations` | `perturbations` |
| `rearangment_version` | timeseries | `rearangment_version` | `rearrangement_version` |
| `bp_filterred_ecg` | processed1 | `bp_filterred_ecg` | `bp_filtered_ecg` |
| `sp_o2` | timeseries, rt_flow | `sp_o2` | -- |
| `spo2` | pc_results_part | `spo2` | -- |
| `crlyse-hr` | pc_timeseries | `"crlyse-hr"` | Needs backtick quoting |
