# CardiacSense Data Overview

## What Is CardiacSense?

CardiacSense is a medical-grade wearable watch that continuously records physiological signals from patients. The device captures PPG (photoplethysmography), ECG (electrocardiogram), SpO2 (blood oxygen saturation), accelerometer data, respiration rate, and other vital signs.

Data flows from watches to the cloud, where it is processed through multiple pipeline stages before landing in queryable tables.

## Environment

- **Account:** 735555370207 (staging)
- **Region:** eu-central-1 (Frankfurt)
- **Infrastructure:** AWS (S3, Glue, Athena, QuickSight)

## Data Pipeline

```
Watch → incoming/ (raw CSV events)
         → rearrangement/rt_flow/ (reorganized CSV)
            → post-computation-layer/ (enriched CSV + JSON)
               → migrated_data (Parquet tables — preferred for queries)
                  → processed (event extraction, ECG segments)
```

### Stage Details

1. **incoming/** — Raw event CSVs uploaded directly from watches. File pattern: `cs_events_{patient_id}_{epoch_sec}.csv`

2. **rearrangement/rt_flow/** — Real-time flow data reorganized into structured format. Includes metadata and session files. Pattern: `rt_flow_{patient_id}_{epoch_ms}.csv` + `_metadata.txt` + `_session.tmp`

3. **post-computation-layer/rt_flow/** — Enriched data after computation algorithms run. Adds derived metrics (perfusion index, stroke volume, PTT, PWV). Pattern: `rt_flow_{patient_id}_{epoch_ms}.csv` + `.json` + `-avg-values.csv`

4. **migrated_data** — Production-grade Parquet tables partitioned by date (and sometimes patient). This is the preferred query target — fastest and most reliable.

5. **processed** — Extracted clinical events and processed ECG segments with quality scores.

## S3 Buckets

| Bucket | Purpose |
|--------|---------|
| `735555370207-app-events` | Raw uploads, rearranged data, post-computation, processed events |
| `735555370207-migrated--data` | Final Parquet/CSV tables (timeseries, results, metadata) |
| `735555370207-datasets-versioning` | Curated/labeled ML datasets |

## Recording Types

The `file_type` field distinguishes recording modes:

| file_type | Description |
|-----------|-------------|
| `rt_flow` | Real-time flow (standard recording) |
| `ar_flow` | Arrhythmia flow |
| `sleep_flow` | Sleep monitoring session |

## Databases

| Database | Tables | Content |
|----------|--------|---------|
| `migrated_data` | 8 | Production Parquet tables — primary query target |
| `cardiacsense` | 3 | Raw/rearranged CSV data (slower, use as fallback) |
| `eventdata` | 2 | Extracted clinical events |
| `default` | 2 | Session metadata + CloudTrail logs |
