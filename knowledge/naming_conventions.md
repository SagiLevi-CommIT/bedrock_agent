# S3 Filename Conventions (live-verified 2026-05-02)

This is the **authoritative reference** for parsing S3 keys in
`735555370207-app-events`. Every tool and skill that touches an S3 key MUST
agree with the patterns here.

## Universal grammar

```
{stage_prefix}/{flow_or_subtype}/{filename}
```

- `stage_prefix` ∈ {`incoming`, `rearrangement`, `post-computation-layer`,
  `processed`, `rt-sessions`, `doctor-realtime-session`, ...}
- `flow_or_subtype` ∈ {`rt_flow`, `sleep_flow`, `ar_flow`, `af_ppg_flow`,
  `arrythmia_flow`, `algos_flow`, `plate_flow`, `tachycardia_flow`} for
  `rearrangement/` and `post-computation-layer/`. The other stages do not
  split by flow.

Patient ID is always a **bare integer** (3-4 digits seen: `108`, `196`, `431`,
`737`, `1000`, `1015`, `1016`).

## Stage 2: rearrangement

Prefix: `s3://735555370207-app-events/rearrangement/{flow}/`

Three artifacts per recording (same `{patient_id}_{epoch_ms}` triple):

| Filename | Role | Contents |
|---|---|---|
| `{flow}_{patient_id}_{epoch_ms}.csv` | data | Raw signal CSV. Columns vary per flow. For `rt_flow` it has 38 columns (see `cardiacsense.rt_flow`). For `sleep_flow` it's PPG/ACC/artifact (no Glue table — schema must be inferred from the CSV header). |
| `{flow}_{patient_id}_{epoch_ms}_metadata.txt` | metadata | Watch metadata (hardware version, FE/BE versions, time_init/time_end, record_length). For `rt_flow` exposed via `default.rt_flow_metadata`. |
| `{flow}_{patient_id}_{epoch_ms}_session.tmp` | session marker | Tiny (~36 bytes). Marks completion. Ignore for queries. |

**`epoch_ms` is the start time of the recording session** — milliseconds since
epoch UTC, 13 digits. Examples:
- `rt_flow_1000_1733268398000` → 2024-12-03T23:26:38Z
- `sleep_flow_1000_1734395023557` → 2024-12-17T00:23:43Z

**The S3 `LastModified` (upload time) ≠ recording time.** Upload lag is
typically minutes but can be hours. **Always parse epoch_ms from the
filename** to get the recording start.

To get the recording **end time**, you must read the file content. The actual
end is encoded in the last `sampling_time` row of the CSV. The
`cs_downloader.probe.probe_time_range` utility returns this with one HEAD + 2
Range-GET requests (~16 KB).

## Stage 3: post-computation-layer

Prefix: `s3://735555370207-app-events/post-computation-layer/{flow}/`

**Only 3 flows have post-computation**: `rt_flow`, `arrythmia_flow`,
`plate_flow`. There is **no** post-computation for `sleep_flow`, `ar_flow`,
`af_ppg_flow`, `tachycardia_flow`, `algos_flow`.

Three artifacts per recording:

| Filename | Role | Contents |
|---|---|---|
| `{flow}_{patient_id}_{epoch_ms}.csv` | enriched timeseries | 23 columns including Cardiolyse outputs (`crlyse_hr`, `crlyse_annotation`, `crlyse_rythem_events`), `perfusion_index`, `stroke_volume`, `ptt`, `pwv_ecg2ir`. For `rt_flow` exposed via `cardiacsense.rt_flow_post`. |
| `{flow}_{patient_id}_{epoch_ms}.json` | full session summary | LARGE (12-25 MB). Per-segment metrics, annotations, raw structures. No Glue table. |
| `{flow}_{patient_id}_{epoch_ms}-avg-values.csv` | aggregates | Tiny (~1 KB). Per-session averaged values. No Glue table. |

The same `{patient_id}_{epoch_ms}` pair links a post-comp file to its
rearrangement parent.

## Stage 1: incoming (current format, 2026-05)

Prefix: `s3://735555370207-app-events/incoming/`

Pattern: `{flow}_{patient_id}_{epoch_ms}.dat.zip`

Example: `incoming/sleep_flow_110_1775241259384.dat.zip` (1.96 MB).

These are zipped binary watch uploads. The `.dat.zip` format is **not** parseable
without the binary decoder. The agent should not attempt to query these
directly. The bucket `incoming/` prefix is mostly empty; the bulk of binary
uploads live under `incoming_dat_files/`, `dat_zip/`, or
`incoming_plate_dat_files/`.

## Stage 5: processed (clinical events, legacy CSV format)

Prefix: `s3://735555370207-app-events/processed/`

Pattern: `cs_events_{patient_id}_{epoch_sec}.csv`

- `epoch_sec` is **10 digits** (seconds, not ms). Example:
  `cs_events_1000_1733266219.csv` → 2024-12-03T22:50:19Z.
- Glue tables `eventdata.events` / `events_test` are declared as Parquet but
  the actual files are CSV. **Athena queries fail with `HIVE_BAD_DATA`.**
  Document this refusal in `limitations.yaml`.

## rt-sessions and doctor-realtime-session

| Prefix | Pattern | Notes |
|---|---|---|
| `rt-sessions/` | `cs_realtime_{patient_id}_{YYYYMMDDHHMMSS}.json` | 14-digit local-format timestamp, **not epoch**. Example: `cs_realtime_1000_20241204002920.json` → 2024-12-04 00:29:20. |
| `rt-sessions-pdf/` | (PDF reports, untriaged) | |
| `doctor-realtime-session/` | `realtime-doctorId-{doctor_id}-pId-{patient_id}-{epoch_ms}.json` (also `realtime-docId-{doctor_id}-pId-{patient_id}-{epoch_ms}.json` and `{doctor_id}-{patient_id}-realtime.json`) | Three variants observed. epoch_ms is 13-digit milliseconds. |

## Empty folder-marker objects

Almost every S3 prefix contains a 0-byte object whose key ends in `/` (e.g.
`incoming/`, `rearrangement/`, `processed/plate_flow/`). Tools that LIST and
filter by extension MUST skip keys ending in `/`.

## Regex registry (canonical for `parse_app_events_key` tool)

```python
PATTERNS = [
    # Rearrangement data CSV
    (r"^rearrangement/(?P<flow>[a-z_]+_flow)/(?P=flow)_(?P<patient_id>\d+)_(?P<epoch_ms>\d{13})\.csv$",
     {"stage": "rearrangement", "role": "data"}),
    # Rearrangement metadata
    (r"^rearrangement/(?P<flow>[a-z_]+_flow)/(?P=flow)_(?P<patient_id>\d+)_(?P<epoch_ms>\d{13})_metadata\.txt$",
     {"stage": "rearrangement", "role": "metadata"}),
    # Rearrangement session marker
    (r"^rearrangement/(?P<flow>[a-z_]+_flow)/(?P=flow)_(?P<patient_id>\d+)_(?P<epoch_ms>\d{13})_session\.tmp$",
     {"stage": "rearrangement", "role": "session"}),
    # Post-computation enriched CSV
    (r"^post-computation-layer/(?P<flow>[a-z_]+_flow)/(?P=flow)_(?P<patient_id>\d+)_(?P<epoch_ms>\d{13})\.csv$",
     {"stage": "post_computation", "role": "data"}),
    # Post-computation summary JSON
    (r"^post-computation-layer/(?P<flow>[a-z_]+_flow)/(?P=flow)_(?P<patient_id>\d+)_(?P<epoch_ms>\d{13})\.json$",
     {"stage": "post_computation", "role": "summary_json"}),
    # Post-computation averaged values
    (r"^post-computation-layer/(?P<flow>[a-z_]+_flow)/(?P=flow)_(?P<patient_id>\d+)_(?P<epoch_ms>\d{13})-avg-values\.csv$",
     {"stage": "post_computation", "role": "avg_values"}),
    # Processed clinical events
    (r"^processed/cs_events_(?P<patient_id>\d+)_(?P<epoch_sec>\d{10})\.csv$",
     {"stage": "processed", "role": "events"}),
    # Incoming binary zip
    (r"^incoming/(?P<flow>[a-z_]+_flow)_(?P<patient_id>\d+)_(?P<epoch_ms>\d{13})\.dat\.zip$",
     {"stage": "incoming", "role": "binary"}),
    # Real-time session JSON (local timestamp, NOT epoch)
    (r"^rt-sessions/cs_realtime_(?P<patient_id>\d+)_(?P<local_ts>\d{14})\.json$",
     {"stage": "rt_sessions", "role": "session_json"}),
    # Doctor session JSON (3 variants)
    (r"^doctor-realtime-session/realtime-doctorId-(?P<doctor_id>\d+)-pId-(?P<patient_id>\d+)-(?P<epoch_ms>\d{13})\.json$",
     {"stage": "doctor_session", "role": "session_json"}),
    (r"^doctor-realtime-session/realtime-docId-(?P<doctor_id>\d+)-pId-(?P<patient_id>\d+)-(?P<epoch_ms>\d{13})\.json$",
     {"stage": "doctor_session", "role": "session_json"}),
    (r"^doctor-realtime-session/(?P<doctor_id>\d+)-(?P<patient_id>\d+)-realtime\.json$",
     {"stage": "doctor_session", "role": "session_json_legacy"}),
]
```

## Sort order

Within a flow, S3's lexicographic ordering of keys matches chronological
ordering of `epoch_ms` because `epoch_ms` is fixed-width 13 digits. This means
S3 `StartAfter` and prefix-narrowing work correctly:

```
rearrangement/sleep_flow/sleep_flow_1000_  ← prefix narrows to one patient
rearrangement/sleep_flow/sleep_flow_1000_1700000000000  ← StartAfter skips older files
```

For descending-time queries ("last upload"), reverse the result list after
listing — S3 doesn't support reverse-listing natively.
