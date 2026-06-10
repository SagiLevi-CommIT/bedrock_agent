# Visualizing rt_flow data

**RT-flow visualization IS supported — per file.** The earlier "only sleep_flow"
limitation was about *download+merge+visualize together*, not about rt_flow viz.

## How to visualize rt_flow

1. Find the file key first (rt_flow is event/ECG data, organized per file):
   - `find_arrhythmia_events(arrhythmia, start, end, patient_id)` → returns matching
     rt_flow `file_key`s, or
   - `get_data_coverage(patient_id, start, end, flow="rt_flow")` → file list.
2. `visualize_rt_file(file_key)` → returns a `job_id`.
3. Poll `get_job_status(job_id)` → on success a **downloadable standalone viewer
   (single HTML)** button is attached. Oversized → a note instead (shorten scope).

## sleep_flow vs rt_flow viz

| Flow | Tool | Shape |
|---|---|---|
| sleep_flow (continuous window) | `generate_visualization(patient_id, start, end)` | fetch+merge+viz over a time range |
| rt_flow (event/ECG, per file) | `visualize_rt_file(file_key)` | one file, no merge |

## What is NOT supported (by design)
- rt_flow **download + merge + visualize together** over a range. rt_flow files are
  heterogeneous (different sensors/intent), so merging them isn't meaningful. Pick a
  specific file and use `visualize_rt_file`.

## Don't
- Don't tell the user "I can only visualize sleep flow" — visualize the rt_flow
  file with `visualize_rt_file`.
- Don't write the viewer URL yourself — the download button carries the real signed
  link from `get_job_status`.
