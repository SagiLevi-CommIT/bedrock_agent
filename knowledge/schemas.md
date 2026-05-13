# Table Schemas (Auto-generated from catalog.json — 2026-03-24)

## Query Priority

When answering data questions, prefer tables in this order:

1. **`migrated_data.pc_results_part`** — aggregated per-session results, date-partitioned, fast (51 columns)
2. **`migrated_data.timeseries`** — full raw timeseries, date-partitioned, Parquet (41 columns)
3. **`migrated_data.pc_timeseries`** — enriched timeseries with post-computation fields (25 columns)
4. **`migrated_data.metadata`** — session metadata, device info, quality metrics (70 columns)
5. **`migrated_data.processed`** — processed ECG segments with quality scores (13 columns)
6. **`eventdata.events`** — extracted clinical events (6 columns)
7. **`cardiacsense.rt_flow_post`** — post-computation CSV (slower, 23 columns, NO partition)
8. **`cardiacsense.rt_flow`** — raw CSV (last resort, 38 columns, NO partition)

---

## Database: `migrated_data` (primary — Parquet, fast)

### `pc_results_part` ★ RECOMMENDED for aggregated metrics
Aggregated per-session computation results. **Date-partitioned** — always use this over `pc_results`.

**Format:** CSV (LazySimpleSerDe) | **Partition:** `date` (date type)
**S3:** `s3://735555370207-migrated--data/pc-results`

| Column | Type | Description |
|--------|------|-------------|
| environment | string | Environment (staging/production) |
| file_type | string | Recording type: rt_flow, ar_flow, sleep_flow |
| session | string | Recording session ID |
| patient | string | Patient UUID |
| weight | float | Patient weight |
| height | float | Patient height |
| age | int | Patient age |
| gender | string | Patient gender |
| pi | float | Perfusion index |
| pwv | float | Pulse wave velocity |
| spo2 | float | Blood oxygen saturation (SpO2) |
| hr | float | Heart rate |
| resp_rate | int | Respiration rate |
| resp_rate_time | timestamp | Respiration rate timestamp |
| af | int | Atrial fibrillation indicator |
| updated_ppg_peaks | int | Updated PPG peak count |
| computation_layer_version | string | Algorithm version |
| pr_interval | float | PR interval (ms) |
| qrs_duration | float | QRS duration (ms) |
| qt_interval | float | QT interval (ms) |
| qtc | float | Corrected QT (Bazett) |
| qtcf | float | Corrected QT (Fridericia) |
| sdnn | float | SDNN — HRV time-domain metric |
| rmssd | float | RMSSD — HRV time-domain metric |
| pnn20 | float | pNN20 — HRV metric |
| pnn50 | float | pNN50 — HRV metric |
| hf | float | High-frequency power (HRV) |
| hfn | float | Normalized HF power |
| lf | float | Low-frequency power (HRV) |
| lfn | float | Normalized LF power |
| vlf | float | Very low frequency power |
| vlf_hf | float | VLF/HF ratio |
| sdsd | float | SDSD — HRV metric |
| entropy | float | Signal entropy |
| activity_of_subcortical_centers | float | ANS subcortical activity |
| activity_of_vasomotor_centers | float | Vasomotor center activity |
| dfa | float | Detrended fluctuation analysis |
| fractal_index | float | Fractal index |
| iae | float | Index of autonomic equilibrium |
| stress_index | float | Stress index (Baevsky) |
| total_power | float | Total HRV spectral power |
| triangular_index | float | HRV triangular index |
| emotional | float | Emotional state score |
| heart_biological_age | string | Estimated heart biological age |
| heart_rhythm_disturbances | float | Rhythm disturbance score |
| myocardium | float | Myocardium health score |
| overall | float | Overall health score |
| risk_cardiovascular_events | float | CV event risk score |
| stamina | float | Stamina score |
| stress | float | Stress score |
| carsiolyse_version | string | Carsiolyse algorithm version |

**Note:** `pc_results` has the same 52 columns (with `date` as a data column instead of partition). Always use `pc_results_part` instead.

---

### `timeseries` ★ Full raw signal data
Full raw physiological timeseries. **Parquet, date-partitioned.**

**Format:** Parquet | **Partition:** `date` (string, `YYYY-MM-DD`)
**S3:** `s3://735555370207-migrated--data/time-series-data`

| Column | Type | Description |
|--------|------|-------------|
| environment | string | Environment |
| file_type | string | Recording type |
| session | string | Session ID |
| patient | string | Patient UUID |
| sampling_time | timestamp | Sample timestamp |
| ppg | int | PPG signal (raw) |
| ppg_peak | double | PPG peak detection |
| ppg_peak_type | double | PPG peak classification |
| hr_ppg | double | Heart rate from PPG |
| ecg | int | ECG signal (raw) |
| ecg_peak | double | ECG peak (R-wave) detection |
| hr_ecg | double | Heart rate from ECG |
| artifact | int | Artifact flag |
| red | int | Red LED signal |
| infra_red | int | Infrared LED signal |
| acc_x | int | Accelerometer X |
| acc_y | int | Accelerometer Y |
| acc_z | int | Accelerometer Z |
| yaw | int | Gyroscope yaw |
| pitch | int | Gyroscope pitch |
| roll | int | Gyroscope roll |
| lead_state | int | ECG lead contact (0=off, 1=on) |
| open_sensor | int | Sensor open/closed |
| sp_o2 | int | SpO2 value (note: `sp_o2` with underscore) |
| respiration_rate | int | Respiration rate |
| accelerometer_flag | int | Accelerometer quality flag |
| artifact_flag | int | Artifact quality flag |
| low_snr | int | Low SNR flag |
| find_parameters | int | Find parameters flag |
| qulity_ecg | int | ECG quality flag (note: misspelled in schema) |
| tightnes | double | Watch tightness |
| tightnes_level | int | Tightness level |
| ppg_af | int | PPG atrial fibrillation flag |
| ecg_afib_episode | int | ECG AFib episode flag |
| debug1 | int | Debug field 1 |
| debug2 | int | Debug field 2 |
| debug3 | int | Debug field 3 |
| debug4 | int | Debug field 4 |
| absolute_rest | double | Absolute rest indicator |
| resp_rate_avg | double | Running average respiration rate |
| bbb | double | Bundle branch block indicator |

---

### `pc_timeseries`
Post-computation enriched timeseries. **Parquet, date-partitioned.**

**Format:** Parquet | **Partition:** `date` (date type)
**S3:** `s3://735555370207-migrated--data/pc-timeseries`

| Column | Type | Description |
|--------|------|-------------|
| environment | string | Environment |
| file_type | string | Recording type |
| session | string | Session ID |
| patient | string | Patient UUID |
| sampling_time | timestamp | Sample timestamp |
| ppg_rawdata | int | Raw PPG data |
| ppg | double | Processed PPG |
| ppg_peak | double | PPG peak |
| ppg_peak_type | double | Peak type |
| hr_ppg | double | Heart rate from PPG |
| perfusion_index | double | Perfusion index |
| stroke_volume | double | Stroke volume |
| ecg | double | ECG signal |
| ecg_peak | double | ECG R-wave peak |
| hr_ecg | double | Heart rate from ECG |
| ptt | double | Pulse transit time |
| infra_red | double | Infrared signal |
| infra_red_peak | double | IR peak |
| ptt_ecg2ir | double | PTT from ECG to IR |
| pwv_ecg2ir | double | Pulse wave velocity ECG→IR |
| pwvc_ecg2ir | double | Corrected PWV |
| pertrubations | int | Perturbation count |
| crlyse-hr | double | Carsiolyse heart rate |
| crlyse-annotation | string | Carsiolyse rhythm annotation |
| crlyse-rythem_events | string | Carsiolyse rhythm events |

---

### `metadata`
Recording session metadata — device info, calibration, quality. **CSV, NOT partitioned — expensive to scan.**

**Format:** CSV (LazySimpleSerDe) | **Partitions:** NONE
**S3:** `s3://735555370207-migrated--data/meta-data`

| Column | Type | Description |
|--------|------|-------------|
| environment | string | Environment |
| file_type | string | Recording type |
| session | string | Session ID |
| patient | string | Patient UUID |
| hardware_version | string | Watch hardware version |
| uploader_version | string | App uploader version |
| parsed | string | Parsing flag |
| be_version | string | Backend version |
| fe_version | string | Frontend version |
| patient_yob | int | Patient year of birth |
| artcal64 | int | Artifact calibration 64 |
| artcal256 | int | Artifact calibration 256 |
| serviceprm_0 through serviceprm_31 | int | Service parameters (32 fields) |
| art_threshold | int | Artifact threshold |
| open_sensor_lod0 | int | Open sensor LOD 0 |
| open_sensor_lod1 | int | Open sensor LOD 1 |
| lead_off_lod0 | int | Lead off LOD 0 |
| lead_off_lod1 | int | Lead off LOD 1 |
| lead_on_lod0 | int | Lead on LOD 0 |
| lead_on_lod1 | int | Lead on LOD 1 |
| p1 through p4 | int | Parameters 1-4 |
| ecg_test_oks | int | ECG test passes |
| ecg_test_afs | int | ECG test AF count |
| ecg_test_fails | int | ECG test failures |
| ppg_af_episodes | int | PPG AF episode count |
| ppg_duration | int | PPG duration |
| rearangment_version | string | Rearrangement algo version |
| time_init | timestamp | Session start time |
| time_end | timestamp | Session end time |
| record_length | int | Recording length (seconds) |
| looseness | float | Watch looseness |
| accelerometers | float | Accelerometer metric |
| artifact | float | Artifact percentage |
| snr | float | Signal-to-noise ratio |
| find_parameters | float | Find parameters metric |
| pertrubations | float | Perturbation count |

**Important:** This table has 70 columns and NO partitions. Queries can be expensive. Use date-based filtering on `time_init` or join with `pc_results_part` when possible.

---

### `processed`
Processed ECG segments with quality metrics. **Parquet, dual-partitioned.**

**Format:** Parquet | **Partitions:** `date` (string), `patient` (string)
**S3:** `s3://735555370207-migrated--data/processed-data`

| Column | Type | Description |
|--------|------|-------------|
| file_type | string | Recording type |
| session | string | Session ID |
| segment_id | string | ECG segment ID |
| sampling_time | timestamp | Timestamp |
| ecg | int | ECG signal (raw int) |
| ecg_peak | double | R-wave peak detection |
| hr_ecg | double | Heart rate from ECG |
| rms | double | RMS of segment |
| sqi | double | Signal quality index |
| kurtosis | double | Kurtosis |
| skewness | double | Skewness |
| std_dev | double | Standard deviation |
| variance | double | Variance |

### `processed1`
Same as `processed` plus filtered ECG. **Same partitions.**

Additional columns: `filtered_ecg` (double), `bp_filterred_ecg` (double)

---

### `curated`
ML-labeled data segments. **Parquet, session-partitioned.**

**Format:** Parquet | **Partition:** `session` (string)
**S3:** `s3://735555370207-datasets-versioning/`

| Column | Type | Description |
|--------|------|-------------|
| segment_id | string | Segment ID |
| timestamp | string | Timestamp |
| rms | double | RMS |
| sqi | double | Signal quality index |
| kurtosis | double | Kurtosis |
| skewness | double | Skewness |
| std_dev | double | Standard deviation |
| variance | double | Variance |
| label | string | Human label |
| labeling_time | string | When labeled |

---

## Database: `cardiacsense` (raw CSV — NO PARTITIONS — expensive scans)

**WARNING:** These tables have **NO partition keys**. Every query scans the entire dataset. Only use as a last resort.

### `rt_flow`
Raw real-time flow. **CSV (LazySimpleSerDe). NO partitions.**

38 columns including: `sampling_time` (bigint epoch ms), `ppg`, `ppg_peak`, `ppg_peak_type`, `hr_ppg`, `ecg`, `ecg_peak`, `hr_ecg`, `artifact`, `red`, `infra_red`, `acc_x/y/z`, `yaw`, `pitch`, `roll`, `lead_state`, `open_sensor`, `sp_o2`, `respiration_rate`, `accelerometer_flag`, `artifact_flag`, `low_snr`, `find_parameters`, `qulity_ecg`, `tightnes`, `tightnes_level`, `ppg_af`, `ecg_afib_episode`, `debug1-4`, `absolute_rest`, `resp_rate_avg`, `bbb`, `date`

Note: `date` is a regular column here, NOT a partition key.

### `rt_flow_post`
Post-computation enriched. **CSV (OpenCSVSerde). NO partitions. All string types.**

23 columns including: `sampling_time`, `ppg_rawdata`, `ppg`, `ppg_peak`, `ppg_peak_type`, `hr_ppg`, `perfusion_index`, `stroke_volume`, `ecg`, `ecg_peak`, `hr_ecg`, `ptt`, `infra_red`, `infra_red_peak`, `ptt_ecg2ir`, `pwv_ecg2ir`, `pwvc_ecg2ir`, `pertrubations`, `crlyse_hr`, `crlyse_annotation`, `crlyse_rythem_events`, `date`, `sp_o2`

### `rt_flow_rearrangement` ⚠️ STALE VIEW — prefer `rt_flow`
Points to the **same S3 prefix** as `rt_flow` (`s3://735555370207-app-events/rearrangement/rt_flow`)
but uses OpenCSVSerde with the 23-column post-computation schema. The raw
rearrangement CSVs at that path do **not** contain those columns
(`crlyse_hr`, `perfusion_index`, etc.) — queries against this view return
empty/null for the missing columns and may parse rows incorrectly.

**Always use `cardiacsense.rt_flow`** (38 columns, typed, LazySimpleSerDe) for
queries against the rearrangement stage. Reserve `rt_flow_rearrangement` for
historical compatibility only.

---

## Database: `eventdata`

### `events`
Extracted clinical events. **Parquet. NO partitions.**

| Column | Type | Description |
|--------|------|-------------|
| patient_id | int | Patient ID (**integer**, not UUID) |
| event_type | int | Event type code |
| timestamp | timestamp | Event time |
| value | double | Event value |
| event_source | varchar(100) | Source |
| inserted_at | timestamp | Insert time |

### `events_test`
Test events. CSV. Columns: `timestamp`, `event_type`, `value`

---

## Database: `default`

### `rt_flow_metadata`
Per-recording metadata. **CSV (OpenCSVSerde). NO partitions.**

| Column | Type | Description |
|--------|------|-------------|
| hardware_version | string | Hardware version |
| uploader_version | string | Uploader version |
| parsed | string | Parsed flag |
| watch_id | string | Physical watch ID |
| advertised_watch_id | string | Advertised watch ID |
| be_version | string | Backend version |
| fe_version | string | Frontend version |
| patient_yob | string | Year of birth |
| artcal64 | string | Artifact cal 64 |
| artcal256 | string | Artifact cal 256 |
| rearangment_version | string | Rearrangement version |
| time_init | string | Session start |
| time_end | string | Session end |
| record_length | int | Duration |
| date | string | Date |

---

## Partition Summary (Critical for Cost)

| Table | Partitions | Cost Impact |
|-------|-----------|-------------|
| `migrated_data.pc_results_part` | `date` | Low — always filter by date |
| `migrated_data.timeseries` | `date` | Low — always filter by date |
| `migrated_data.pc_timeseries` | `date` | Low — always filter by date |
| `migrated_data.processed` | `date`, `patient` | Low — filter by both |
| `migrated_data.curated` | `session` | Low — filter by session |
| `migrated_data.metadata` | **NONE** | **HIGH — full scan every query** |
| `migrated_data.pc_results` | **NONE** | **HIGH — use pc_results_part instead** |
| `cardiacsense.*` | **NONE** | **VERY HIGH — CSV + full scan** |
| `eventdata.*` | **NONE** | **HIGH — full scan** |
| `default.*` | **NONE** | **HIGH — full scan** |
