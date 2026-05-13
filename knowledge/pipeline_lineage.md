# CardiacSense Data Pipeline Lineage

## Pipeline Overview

Data flows from wearable watches through multiple processing stages before reaching queryable production tables. Each stage transforms the data, changing its format, schema, and identifier conventions.

```
Watch Device
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  STAGE 1: incoming/                                     │
│  Bucket: 735555370207-app-events                        │
│  Format: BINARY ZIP  │  IDs: integer  │  epoch_ms       │
│  Pattern: {flow}_{patient_id}_{epoch_ms}.dat.zip        │
│                                                         │
│  As of 2026-05 the bucket holds binary watch uploads    │
│  (.dat.zip), NOT cs_events_*.csv. Most files have       │
│  already moved into incoming_dat_files/, dat_zip/, or   │
│  rearrangement/. cs_events_*.csv now lives only under   │
│  processed/ (see Stage 5).                              │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  STAGE 2: rearrangement/{flow_type}/                    │
│  Bucket: 735555370207-app-events                        │
│  Format: CSV + TXT + TMP  │  IDs: integer  │  epoch_ms  │
│  Pattern: {flow}_{patient_id}_{epoch_ms}.csv            │
│           {flow}_{patient_id}_{epoch_ms}_metadata.txt   │
│           {flow}_{patient_id}_{epoch_ms}_session.tmp    │
│                                                         │
│  Separated by flow type:                                │
│    rt_flow (19,470)  │  sleep_flow (627,297)            │
│    ar_flow (2,139)   │  af_ppg_flow (810)               │
│    tachycardia_flow (426)  │  plate_flow (1,105)        │
│    algos_flow (3)    │  arrythmia_flow (?)               │
│                                                         │
│  Glue: cardiacsense.rt_flow, default.rt_flow_metadata   │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  STAGE 3: post-computation-layer/{flow_type}/           │
│  Bucket: 735555370207-app-events                        │
│  Format: CSV + JSON  │  IDs: integer  │  epoch_ms       │
│  Pattern: {flow}_{patient_id}_{epoch_ms}.csv            │
│           {flow}_{patient_id}_{epoch_ms}.json           │
│           {flow}_{patient_id}_{epoch_ms}-avg-values.csv │
│                                                         │
│  Active flows: rt_flow (18,294), arrythmia_flow (3),    │
│                plate_flow (?)                           │
│                                                         │
│  Adds: perfusion_index, stroke_volume, ptt, pwv,        │
│        crlyse_hr, crlyse_annotation, crlyse_rythem_events│
│  (verified 2026-05-02; old `carsiolyse_*` names are     │
│  WRONG — actual columns use the `crlyse_` prefix.)      │
│                                                         │
│  Active flows (verified 2026-05-02): rt_flow,           │
│    arrythmia_flow, plate_flow. NO post-computation for  │
│    sleep_flow, ar_flow, af_ppg_flow, tachycardia_flow,  │
│    algos_flow.                                          │
│                                                         │
│  Glue: cardiacsense.rt_flow_post (rt_flow only)         │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  STAGE 4: migrated_data (Production Tables)             │
│  Bucket: 735555370207-migrated--data                    │
│  Format: Parquet/CSV  │  IDs: UUID  │  Timestamps: mixed│
│                                                         │
│  ┌─────────────────────────────────────────────────┐    │
│  │ time-series-data/  →  migrated_data.timeseries  │    │
│  │ Parquet │ date=YYYY-MM-DD/ │ 969 partitions     │    │
│  │ Partition type: STRING                          │    │
│  └─────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────┐    │
│  │ pc-timeseries/  →  migrated_data.pc_timeseries  │    │
│  │ Parquet │ date=YYYY-MM-DD/ │ 865 partitions     │    │
│  │ Partition type: DATE                            │    │
│  └─────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────┐    │
│  │ pc-results/  →  migrated_data.pc_results_part   │    │
│  │ CSV │ date=YYYY-MM-DD/ │ 865 partitions         │    │
│  │ Partition type: DATE                            │    │
│  │ ⚠ Also: pc_results (same data, NO partition)    │    │
│  └─────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────┐    │
│  │ meta-data/  →  migrated_data.metadata           │    │
│  │ CSV │ ⚠ NO PARTITION in Glue (full scan!)       │    │
│  │ S3 has date= folders but Glue ignores them      │    │
│  └─────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────┐    │
│  │ processed-data/  →  migrated_data.processed     │    │
│  │ Parquet │ date=YYYY-MM-DD/patient=UUID/         │    │
│  │ Partition type: STRING (date), STRING (patient)  │    │
│  │ Also: migrated_data.processed1 (extra columns)  │    │
│  └─────────────────────────────────────────────────┘    │
└─────────────────────────┬───────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  STAGE 5: processed/ (Clinical Events)                  │
│  Bucket: 735555370207-app-events                        │
│  Format: CSV  │  IDs: integer                           │
│  Pattern: cs_events_{patient_id}_{epoch_sec}.csv        │
│  Objects: 550,024                                       │
│                                                         │
│  ⚠ Glue catalog says Parquet but files are CSV          │
│  Glue: eventdata.events, eventdata.events_test          │
│  Queries FAIL with HIVE_BAD_DATA                        │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  ML / CURATED (separate path)                           │
│  Bucket: 735555370207-datasets-versioning               │
│  Format: Snappy Parquet  │  Partitioned: session=UUID/  │
│  Glue: migrated_data.curated                            │
│  Also: labeled_data/dataset.csv, SageMaker artifacts    │
└─────────────────────────────────────────────────────────┘
```

## Identity Transitions

A critical aspect of the pipeline is that patient identifiers change format between stages:

| Stage | ID Field | Type | Example |
|-------|----------|------|---------|
| incoming, rearrangement, post-computation | `patient_id` | integer | `1000`, `605`, `431` |
| migrated_data tables | `patient` | UUID string | `40f2e337-3f7b-4e38-b886-daf27bf4bf16` |
| eventdata.events | `patient_id` | integer | `1000` |

There is **no direct join** between integer patient IDs (pre-migration) and UUID patient IDs (post-migration). This is a known gap.

## Timestamp Transitions

| Stage | Field | Type | Notes |
|-------|-------|------|-------|
| incoming | filename | epoch seconds | `_1733266219` |
| rearrangement | `sampling_time` / filename | epoch milliseconds (bigint) | `_1733268398000` |
| post-computation | `sampling_time` / filename | epoch milliseconds (bigint) | Same as rearrangement |
| migrated_data.timeseries | `sampling_time` | timestamp | Native Athena timestamp |
| migrated_data.pc_results_part | `date` partition | DATE type | Athena DATE literal required |
| migrated_data.timeseries | `date` partition | string | String comparison |

## Flow Type Coverage by Stage

| Flow Type | Incoming | Rearrangement | Post-Computation | Migrated | Processed Events |
|-----------|----------|---------------|------------------|----------|-----------------|
| rt_flow | shared | yes (19,470) | yes (18,294) | yes (timeseries, pc_results, pc_timeseries) | yes (550K) |
| sleep_flow | shared | yes (627,297) | no | yes (via file_type filter) | -- |
| ar_flow | shared | yes (2,139) | no | yes (via file_type filter) | -- |
| af_ppg_flow | shared | yes (810) | no | unconfirmed | -- |
| tachycardia_flow | shared | yes (426) | no | unconfirmed | -- |
| plate_flow | shared | yes (1,105) | yes (?) | unconfirmed | -- |
| algos_flow | shared | yes (3) | no | no | -- |
| arrythmia_flow | shared | yes (?) | yes (3) | no | -- |

## Supporting Data Paths

| Path | Bucket | Purpose | Objects |
|------|--------|---------|---------|
| `error_events/` | app-events | Pipeline failures | 321,352 |
| `errors/` | app-events | Secondary error path | 7,070 |
| `inprocess/` | app-events | In-flight processing | 62 |
| `rt-sessions/` | app-events | Session JSON summaries | 13,010 |
| `pipeline-monitor/` | migrated--data | Pipeline health monitoring | 226,511 |
| `dat_zip/`, `incoming_dat_files/`, `incoming_dat_processed/` | app-events | Binary DAT archives | varies |
| `general_dat_files/` | app-events | Raw binary sensor data | 531 |
| `query-results/` | migrated--data | Athena output | varies |

## Key Relationships

- **Session** is the primary join key across migrated_data tables (timeseries, pc_results_part, pc_timeseries, metadata, processed)
- **Patient** (UUID) enables aggregation across sessions within migrated_data
- **file_type** discriminates recording types within shared tables (timeseries, pc_results_part)
- **date** partition is the primary cost-control filter — always include it
- **watch_id** only exists in `default.rt_flow_metadata` — no direct join to migrated_data tables (correlation by time overlap only)

## Data Quality Markers

| Indicator | Table | Column | Notes |
|-----------|-------|--------|-------|
| Signal Quality | timeseries | `tightnes` (sic) | Watch tightness 0-1 |
| ECG Quality | timeseries | `qulity_ecg` (sic) | ECG signal quality flag |
| Artifact | timeseries | `artifact` | Motion artifact indicator |
| Lead State | timeseries | `lead_state` | ECG lead contact state |
| SNR | metadata | `snr` | Signal-to-noise ratio |
| SQI | processed | `sqi` | Signal quality index per segment |
| Bogus Dates | all partitioned | `date=2000-01-01` | Malformed timestamps — filter out |
