# Query Patterns & Templates

Proven SQL templates for common CardiacSense data questions. Always verify column names against `schemas.md` before using.

---

## Discovery & Schema

### List all databases
```sql
SHOW DATABASES
```

### List tables in a database
```sql
SHOW TABLES IN migrated_data
```

### Describe a table
```sql
DESCRIBE migrated_data.pc_results_part
```

### Available dates (recent)
```sql
SELECT DISTINCT date FROM migrated_data.pc_results_part ORDER BY date DESC LIMIT 30
```

---

## Patient & Session Queries

### How many patients recorded data on a given date?
```sql
SELECT COUNT(DISTINCT patient) as patient_count
FROM migrated_data.pc_results_part
WHERE date = '{{date}}'
```

### How many patients recorded data yesterday?
```sql
SELECT COUNT(DISTINCT patient) as patient_count
FROM migrated_data.pc_results_part
WHERE date = date_format(current_date - interval '1' day, '%Y-%m-%d')
```

### List patients for a date range
```sql
SELECT DISTINCT patient
FROM migrated_data.pc_results_part
WHERE date >= '{{start_date}}' AND date <= '{{end_date}}'
ORDER BY patient
LIMIT 100
```

### Sessions per patient in the last week
```sql
SELECT patient, COUNT(DISTINCT session) as session_count
FROM migrated_data.pc_results_part
WHERE date >= date_format(current_date - interval '7' day, '%Y-%m-%d')
GROUP BY patient
ORDER BY session_count DESC
LIMIT 50
```

---

## Sleep Monitoring

### How many users slept with the watch last night?
```sql
SELECT COUNT(DISTINCT patient) as user_count
FROM migrated_data.pc_results_part
WHERE date = date_format(current_date - interval '1' day, '%Y-%m-%d')
  AND file_type = 'sleep_flow'
```

### Sleep sessions with low SpO2 (last 30 days)
Ask user for threshold. Typical: <90% concerning, <95% borderline.
```sql
SELECT session, patient, spo2, hr, stress_index, date
FROM migrated_data.pc_results_part
WHERE date >= date_format(current_date - interval '30' day, '%Y-%m-%d')
  AND spo2 < {{threshold}}
  AND file_type = 'sleep_flow'
ORDER BY date DESC
LIMIT 100
```

### Average sleep session stats per patient
```sql
SELECT patient,
  COUNT(*) as sessions,
  AVG(hr) as avg_hr,
  AVG(spo2) as avg_spo2,
  AVG(stress_index) as avg_stress
FROM migrated_data.pc_results_part
WHERE date >= '{{start_date}}'
  AND file_type = 'sleep_flow'
GROUP BY patient
ORDER BY sessions DESC
LIMIT 50
```

---

## Vital Signs & Metrics

### Average heart rate for a patient on a date
```sql
SELECT
  AVG(hr_ecg) as avg_hr_ecg,
  AVG(hr_ppg) as avg_hr_ppg,
  MIN(sampling_time) as session_start,
  MAX(sampling_time) as session_end,
  COUNT(*) as samples
FROM migrated_data.timeseries
WHERE date = '{{date}}' AND patient = '{{patient_uuid}}'
  AND hr_ecg > 0
```

### Recordings where heart rate is above a threshold
```sql
SELECT session, patient, hr, spo2, stress_index, date
FROM migrated_data.pc_results_part
WHERE date >= '{{start_date}}'
  AND hr > {{threshold}}
ORDER BY hr DESC
LIMIT 100
```

### SpO2 distribution for a patient
```sql
SELECT spo2, COUNT(*) as sessions
FROM migrated_data.pc_results_part
WHERE patient = '{{patient_uuid}}'
  AND date >= '{{start_date}}'
GROUP BY spo2
ORDER BY spo2
```

### HRV metrics over time (full spectral + time domain)
```sql
SELECT date, session, hr, sdnn, rmssd, pnn50, lf, hf, lfn, hfn, stress_index, total_power
FROM migrated_data.pc_results_part
WHERE patient = '{{patient_uuid}}'
  AND date >= '{{start_date}}'
ORDER BY date
```

### Carsiolyse health scores for a patient
```sql
SELECT date, session, emotional, stress, stamina, myocardium, overall,
  heart_biological_age, risk_cardiovascular_events, heart_rhythm_disturbances
FROM migrated_data.pc_results_part
WHERE patient = '{{patient_uuid}}'
  AND date >= '{{start_date}}'
ORDER BY date
```

### ECG quality metrics
```sql
SELECT session, AVG(sqi) as avg_sqi, AVG(kurtosis) as avg_kurtosis,
  AVG(skewness) as avg_skewness, AVG(std_dev) as avg_std_dev
FROM migrated_data.processed
WHERE date = '{{date}}' AND patient = '{{patient_uuid}}'
GROUP BY session
```

---

## Data Gap Detection

### Detect sampling gaps (> 5 minutes)
```sql
SELECT
  sampling_time,
  lead(sampling_time) OVER (ORDER BY sampling_time) as next_sample,
  date_diff('second', sampling_time,
    lead(sampling_time) OVER (ORDER BY sampling_time)
  ) as gap_seconds
FROM migrated_data.timeseries
WHERE date = '{{date}}'
  AND patient = '{{patient_uuid}}'
ORDER BY sampling_time
```
Filter results where `gap_seconds > 300` (5 minutes).

### Which dates have data for a patient?
```sql
SELECT date, COUNT(*) as records, COUNT(DISTINCT session) as sessions
FROM migrated_data.pc_results_part
WHERE patient = '{{patient_uuid}}'
GROUP BY date
ORDER BY date DESC
LIMIT 30
```

---

## Aggregate & Trend Queries

### Daily patient count (last 30 days)
```sql
SELECT date, COUNT(DISTINCT patient) as patients, COUNT(DISTINCT session) as sessions
FROM migrated_data.pc_results_part
WHERE date >= date_format(current_date - interval '30' day, '%Y-%m-%d')
GROUP BY date
ORDER BY date
```

### Data volume per recording type
```sql
SELECT file_type, COUNT(DISTINCT session) as sessions, COUNT(DISTINCT patient) as patients
FROM migrated_data.pc_results_part
WHERE date >= '{{start_date}}'
GROUP BY file_type
ORDER BY sessions DESC
```

### Hardware version distribution
Use metadata carefully (no partition — full scan):
```sql
SELECT hardware_version, COUNT(DISTINCT patient) as patients, COUNT(*) as sessions
FROM migrated_data.metadata
GROUP BY hardware_version
ORDER BY patients DESC
LIMIT 20
```

---

## Advanced Patterns

### Sessions with high artifact rate
```sql
SELECT session, patient, artifact, snr, record_length
FROM migrated_data.metadata
WHERE artifact > {{threshold}}
ORDER BY artifact DESC
LIMIT 50
```

### Compare HR from PPG vs ECG
```sql
SELECT session, patient,
  AVG(hr_ppg) as avg_hr_ppg,
  AVG(hr_ecg) as avg_hr_ecg,
  ABS(AVG(hr_ppg) - AVG(hr_ecg)) as hr_diff
FROM migrated_data.timeseries
WHERE date = '{{date}}' AND patient = '{{patient_uuid}}'
  AND hr_ppg > 0 AND hr_ecg > 0
GROUP BY session, patient
```

### Atrial fibrillation episodes
```sql
SELECT date, patient, session, af, ppg_af_episodes, ecg_test_afs
FROM migrated_data.pc_results_part p
LEFT JOIN migrated_data.metadata m ON p.session = m.session
WHERE p.date >= '{{start_date}}'
  AND (p.af > 0)
ORDER BY p.date DESC
LIMIT 50
```

### Sample raw timeseries (quick look)
```sql
SELECT sampling_time, ppg, ecg, hr_ppg, hr_ecg, sp_o2, acc_x, acc_y, acc_z, lead_state
FROM migrated_data.timeseries
WHERE date = '{{date}}' AND patient = '{{patient_uuid}}'
ORDER BY sampling_time
LIMIT 20
```

---

## Template Variables

| Placeholder | Description | Example |
|------------|-------------|---------|
| `{{date}}` | Specific date | `2026-03-24` |
| `{{start_date}}` | Range start | `2026-03-01` |
| `{{end_date}}` | Range end | `2026-03-24` |
| `{{patient_uuid}}` | Patient UUID | `40f2e337-3f7b-4e38-b886-daf27bf4bf16` |
| `{{threshold}}` | Numeric threshold | `90` for HR, `90` for SpO2 |

---

## Anti-Patterns (Do NOT do these)

### Never query without date filter on partitioned tables
```sql
-- BAD: scans ALL data
SELECT * FROM migrated_data.timeseries WHERE patient = '...'

-- GOOD: scans one partition
SELECT * FROM migrated_data.timeseries WHERE date = '2026-03-24' AND patient = '...'
```

### Never use `cardiacsense.rt_flow` assuming date is a partition
```sql
-- BAD: `date` is a regular column, NOT a partition. Still full scan.
SELECT * FROM cardiacsense.rt_flow WHERE date = '2026-03-24'

-- GOOD: use the migrated version instead
SELECT * FROM migrated_data.timeseries WHERE date = '2026-03-24'
```

### Date partition types differ across tables — auto-correction handles this

The `date` partition is type `DATE` (native) on some tables and type `STRING` on others. Using the wrong syntax causes TYPE_MISMATCH errors.

**You don't need to worry about this.** The query tool (`athena_query.py`) auto-detects the target table and rewrites date filters to the correct type before execution. Just write whichever syntax is natural — it will be fixed automatically.

For reference, here are the two groups:

**DATE-type partitions** (`pc_results_part`, `pc_timeseries`):
```sql
-- These require DATE literals or date expressions:
WHERE date = DATE '2026-03-24'
WHERE date >= current_date - interval '7' day
WHERE date BETWEEN DATE '2026-03-01' AND DATE '2026-03-24'

-- String literals like '2026-03-24' are auto-converted to DATE '2026-03-24'
```

**STRING-type partitions** (`timeseries`, `processed`, `processed1`):
```sql
-- These require plain string literals or date_format():
WHERE date = '2026-03-24'
WHERE date >= date_format(current_date - interval '7' day, '%Y-%m-%d')

-- DATE literals like DATE '2026-03-24' are auto-converted to '2026-03-24'
```

**In templates below**, we use string literals and `date_format()` as the canonical form. The auto-corrector rewrites them for DATE-type tables at execution time.

### Never use `pc_results` when `pc_results_part` exists
```sql
-- BAD: no partition, full scan
SELECT * FROM migrated_data.pc_results WHERE date = '2026-03-24'

-- GOOD: partitioned, fast
SELECT * FROM migrated_data.pc_results_part WHERE date = '2026-03-24'
```
