# Key Relationships & Identifiers

## Primary Identifiers

| Identifier | Type | Where Used | Example |
|-----------|------|------------|---------|
| `patient` | UUID string | `migrated_data.*` tables | `40f2e337-3f7b-4e38-b886-daf27bf4bf16` |
| `patient_id` | integer | `eventdata.events` | `1000` |
| `session` | string | All `migrated_data` tables | Unique per recording |
| `watch_id` | string | `default.rt_flow_metadata` only | Physical device ID |
| `date` | string or date | Partition key where available | `2026-03-24` |
| `sampling_time` | timestamp or bigint | Timeseries tables | See per-table type |
| `file_type` | string | Most tables | `rt_flow`, `ar_flow`, `sleep_flow` |
| `environment` | string | `migrated_data.*` | `staging`, `production` |
| `segment_id` | string | `processed`, `curated` | ECG segment ID |

## Cross-Table Joins

### Session-Based Joins (most common)

`session` is the primary join key across `migrated_data` tables:

```
pc_results_part.session ↔ timeseries.session ↔ pc_timeseries.session ↔ metadata.session ↔ processed.session
```

Example — session results + device metadata:
```sql
SELECT p.patient, p.hr, p.spo2, p.stress_index, m.hardware_version, m.record_length
FROM migrated_data.pc_results_part p
JOIN migrated_data.metadata m ON p.session = m.session
WHERE p.date = '2026-03-24'
LIMIT 50
```

**Warning:** `metadata` is NOT partitioned. Joining it adds a full scan of metadata. Use sparingly.

### Patient-Based Aggregation

Use `patient` to aggregate across sessions:
```sql
SELECT patient, COUNT(DISTINCT session) as sessions, AVG(hr) as avg_hr
FROM migrated_data.pc_results_part
WHERE date >= date '2026-03-01'
GROUP BY patient
```

### Timeseries → Results Correlation

Raw signals live in `timeseries` (per-sample). Aggregated outcomes live in `pc_results_part` (per-session). Connect via `session` + `patient`:

```sql
-- Get raw HR samples for a session known to have high stress
SELECT t.sampling_time, t.hr_ecg, t.sp_o2
FROM migrated_data.timeseries t
WHERE t.date = '2026-03-24'
  AND t.session = '<session_id_from_pc_results>'
ORDER BY t.sampling_time
LIMIT 100
```

### Events → Patient Mapping

**WARNING:** `eventdata.events.patient_id` is an integer, while `migrated_data.*.patient` is a UUID. No direct join exists. You must query them separately.

### Metadata → Device Info

Only `default.rt_flow_metadata` has `watch_id` and `advertised_watch_id`. To correlate device → session, join on overlapping `time_init`/`time_end` ranges (approximate — no direct foreign key).

## Table Relationship Map

```
migrated_data.pc_results_part ──session──┐
migrated_data.timeseries ──session──┤
migrated_data.pc_timeseries ──session──┼── migrated_data.metadata (expensive join)
migrated_data.processed ──session──┤
migrated_data.curated ──session──┘

eventdata.events ──(patient_id: int)──✕── NO JOIN to UUID tables

default.rt_flow_metadata ──(watch_id, time overlap)── approximate correlation only
```

## Date & Time

### Date Filtering on Partitioned Tables
```sql
-- Specific date
WHERE date = '2026-03-24'

-- Yesterday
WHERE date = date_format(current_date - interval '1' day, '%Y-%m-%d')

-- Last 7 days
WHERE date >= date_format(current_date - interval '7' day, '%Y-%m-%d')

-- Last 30 days
WHERE date >= date_format(current_date - interval '30' day, '%Y-%m-%d')
```

### Converting Epochs (cardiacsense.rt_flow)
```sql
SELECT from_unixtime(sampling_time / 1000) as readable_time
FROM cardiacsense.rt_flow
WHERE date = '2026-03-24'  -- WARNING: date is NOT a partition here, still full scan
```

## S3 → Table Mapping

| Table | S3 Location |
|-------|------------|
| `migrated_data.timeseries` | `s3://735555370207-migrated--data/time-series-data/` |
| `migrated_data.pc_timeseries` | `s3://735555370207-migrated--data/pc-timeseries/` |
| `migrated_data.pc_results*` | `s3://735555370207-migrated--data/pc-results/` |
| `migrated_data.metadata` | `s3://735555370207-migrated--data/meta-data/` |
| `migrated_data.processed*` | `s3://735555370207-migrated--data/processed-data/` |
| `migrated_data.curated` | `s3://735555370207-datasets-versioning/` |
| `cardiacsense.rt_flow` | `s3://735555370207-app-events/rearrangement/rt_flow/` |
| `cardiacsense.rt_flow_post` | `s3://735555370207-app-events/post-computation-layer/rt_flow/` |
| `eventdata.events` | `s3://735555370207-app-events/processed/` |
