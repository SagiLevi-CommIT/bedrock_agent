# Column Profiles & Plausible Value Ranges

For each column the agent often filters or aggregates on, this file lists:

- **Type** (from Glue catalog, verified 2026-05-02)
- **Plausible range** — biologically/operationally reasonable values
- **Sentinel / null markers** — common "this means missing"
- **Notes** — gotchas

The numeric ranges are physiological priors and conservative table maxima
based on the watch hardware spec. They are **not** statistical distributions
from live data — those will be added in Phase 1H profiling.

---

## `migrated_data.pc_results_part` (date-partitioned)

| Column | Type | Plausible range | Sentinel | Notes |
|---|---|---|---|---|
| `file_type` | string | {`rt_flow`, `sleep_flow`, `ar_flow`, `af_ppg_flow`, `arrythmia_flow`, `algos_flow`, `tachycardia_flow`, `plate_flow`} | NULL | Always filter on this when the question is flow-specific |
| `patient` | string (UUID) | 36-char UUID | NULL | Lower-case hex, hyphens at positions 8/13/18/23 |
| `session` | string | UUID-like | NULL | Primary join key |
| `hr` | float | 30 – 220 bpm | NULL or 0 | Rest 50-90; sport up to 200; <30 or >220 = error |
| `spo2` | float | 70 – 100 % | NULL or 0 | <90 = clinically low; <70 = sensor error |
| `pi` | float | 0.02 – 20 % | NULL | Perfusion index, watch-dependent |
| `pwv` | float | 4 – 12 m/s | NULL | Pulse wave velocity, age-dependent |
| `sdnn` | float | 10 – 200 ms | NULL | HRV, lower = stressed |
| `rmssd` | float | 10 – 100 ms | NULL | HRV time-domain |
| `qt_interval` | float | 300 – 500 ms | NULL | <300 = error; >500 = LQT alert |
| `qrs_duration` | float | 60 – 140 ms | NULL | >120 = wide QRS, possible BBB |
| `pr_interval` | float | 100 – 300 ms | NULL | >200 = first-degree AV block |
| `qtc` | float | 350 – 470 ms | NULL | Bazett-corrected QT |
| `af` | int | 0 or 1 | NULL | Atrial fibrillation flag (1 = AF detected in session) |
| `stress_index` | float | 30 – 1000+ | NULL | Baevsky index |
| `heart_biological_age` | string | "30Y", "45Y" | NULL | String-formatted years; parse with regex |
| `gender` | string | "M", "F", "U" | NULL | Verify casing — sometimes lowercase |
| `age` | int | 0 – 120 | NULL | |
| `weight` | float | 30 – 200 kg | NULL or 0 | |
| `height` | float | 100 – 220 cm | NULL or 0 | |
| `carsiolyse_version` | string | semver-like | NULL | Used to bucket "old algorithm" vs "new algorithm" cohorts |

---

## `migrated_data.timeseries` (date-partitioned, Parquet)

All sample-level values; expect huge row counts even per session.

| Column | Type | Plausible range | Sentinel | Notes |
|---|---|---|---|---|
| `file_type` | string | (see above) | NULL | Required filter |
| `patient` | string (UUID) | UUID | NULL | |
| `session` | string | UUID-like | NULL | |
| `sampling_time` | timestamp | 2020-01-01 onwards | NULL | UTC |
| `ppg` | int | -2^15 .. 2^15 | NULL | Raw ADC value |
| `ecg` | int | -2^15 .. 2^15 | NULL | Raw ADC |
| `hr_ppg` | double | 30 – 220 | NULL or 0 | Per-sample HR estimate from PPG |
| `hr_ecg` | double | 30 – 220 | NULL or 0 | Per-sample HR from ECG |
| `sp_o2` | int | 70 – 100 | 0 or NULL | Note: `sp_o2` (underscore) here, vs `spo2` in pc_results_part |
| `qulity_ecg` | int | 0 / 1 / small enum | NULL | **Integer enum, NOT a string flag.** Misspelled column name |
| `tightnes` | double | 0.0 – 1.0 | NULL | 0 = loose (PPG unreliable), 1 = tight |
| `tightnes_level` | int | 0 / 1 / 2 / 3 | NULL | Discrete level |
| `lead_state` | int | 0 / 1 | NULL | 0 = lead off, 1 = good contact |
| `artifact` | int | 0 / 1 / small enum | NULL | Per-sample artifact flag |
| `artifact_flag` | int | 0 / 1 | NULL | Quality-aggregated artifact |
| `low_snr` | int | 0 / 1 | NULL | Low SNR flag |
| `ppg_af` | int | 0 / 1 | NULL | PPG-derived AF episode flag |
| `ecg_afib_episode` | int | 0 / 1 | NULL | ECG-derived AFib flag |
| `acc_x` `acc_y` `acc_z` | int | -2^15 .. 2^15 | NULL | Accelerometer raw |
| `respiration_rate` | int | 8 – 30 brpm | 0 or NULL | |
| `bbb` | double | 0.0 – 1.0 | NULL | Bundle branch block proxy |

---

## `migrated_data.pc_timeseries` (date-partitioned, Parquet — Cardiolyse-enriched)

| Column | Type | Plausible range | Sentinel | Notes |
|---|---|---|---|---|
| `sampling_time` | timestamp | as above | NULL | |
| `ppg`, `ecg` | double | normalized | NULL | Processed (not raw int) |
| `hr_ppg`, `hr_ecg` | double | 30 – 220 | NULL | |
| `perfusion_index` | double | 0.02 – 20 | NULL | |
| `stroke_volume` | double | 30 – 100+ mL | NULL | |
| `ptt` | double | 100 – 400 ms | NULL | |
| `ptt_ecg2ir` | double | 100 – 400 ms | NULL | |
| `pwv_ecg2ir` | double | 4 – 12 m/s | NULL | |
| `pwvc_ecg2ir` | double | 4 – 12 m/s | NULL | Corrected |
| `pertrubations` | int | 0 – many | NULL | |
| `` `crlyse-hr` `` | double | 30 – 220 | NULL | **Hyphenated — backticks required** |
| `` `crlyse-annotation` `` | string | enum: NSR / AF / VT / unknown | "" or NULL | **Hyphenated** |
| `` `crlyse-rythem_events` `` | string | event codes | "" or NULL | **Hyphenated** (note "rythem" misspelling carries through) |

---

## `migrated_data.metadata` (NOT partitioned — every query is a full scan)

| Column | Type | Plausible range | Notes |
|---|---|---|---|
| `file_type` | string | (see above) | |
| `patient` | string (UUID) | UUID | |
| `session` | string | UUID-like | |
| `hardware_version` | string | semver-like | |
| `fe_version`, `be_version` | string | semver-like | Firmware versions — bucket cohorts here |
| `time_init`, `time_end` | timestamp | UTC | Session boundaries |
| `record_length` | int | seconds (0 – 86400) | |
| `looseness` | float | 0.0 – 1.0 | Inverse of `tightnes` |
| `snr` | float | 0 – 30+ dB | Higher = better |
| `pertrubations` | float | 0+ | |

---

## `cardiacsense.rt_flow` (raw rearrangement, no partition, LazySimpleSerDe)

| Column | Type | Notes |
|---|---|---|
| `sampling_time` | bigint | **Epoch milliseconds** (e.g. `1733268398123`). Convert with `from_unixtime(sampling_time / 1000)`. |
| `date` | string | Regular column, **NOT a partition key** — filtering by date doesn't reduce scan |
| `qulity_ecg` | string | **String here**, unlike `migrated_data.timeseries` where it's int |
| (others) | (see schemas.md) | |

---

## `cardiacsense.rt_flow_post` (post-comp, no partition, OpenCSVSerde — all string)

All 23 columns are typed `string`. Cast in queries:

```sql
-- Get HR distribution from post-computation layer
SELECT CAST(crlyse_hr AS DOUBLE) AS hr
FROM cardiacsense.rt_flow_post
WHERE crlyse_hr <> ''
```

| Column | Native semantic type | Notes |
|---|---|---|
| `sampling_time` | epoch_ms (bigint) | Cast: `CAST(sampling_time AS BIGINT)` |
| `crlyse_hr` | double (bpm) | Underscore version (vs hyphenated in pc_timeseries) |
| `crlyse_annotation` | string enum | NSR / AF / VT / etc. |
| `crlyse_rythem_events` | string | event sequence |
| `perfusion_index`, `stroke_volume`, `ptt`, `pwv_ecg2ir`, `pwvc_ecg2ir`, `ptt_ecg2ir` | double | Cast on use |
| `pertrubations` | int | Cast on use |
| `sp_o2` | int (%) | Cast on use |
| `date` | date string | Regular column, not partition |

---

## `default.rt_flow_metadata` (rearrangement metadata, no partition)

| Column | Type | Notes |
|---|---|---|
| `watch_id` | string | **Only place this exists** — no `watch_id` in `migrated_data.metadata` |
| `advertised_watch_id` | string | The advertised BLE name — sometimes differs from physical |
| `hardware_version`, `fe_version`, `be_version` | string | Firmware cohort buckets |
| `patient_yob` | string (year as string) | Cast for arithmetic |
| `time_init`, `time_end` | string (ISO-ish) | Parse with `from_iso8601_timestamp` or split |
| `record_length` | int | Seconds |

---

## TODO — populated in Phase 1H verification

- Real distribution top-10 values per `file_type` x date partition.
- Real null rates for `qulity_ecg`, `tightnes`, `lead_state`.
- Real distinct count of `fe_version` and `be_version`.
- Real range of `crlyse_hr` post 99th percentile and below 1st percentile (clip thresholds).
- Real sentinel patterns observed (e.g. `0`, `-1`, `999`).

These will be filled by running cheap partition-filtered Athena queries
during Phase 1H and appending to this file.
