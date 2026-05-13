# Event search

Use `list_arrhythmia_labels` then `search_files_with_arrhythmia_events`.

## Parameters

- Always prefer `patient_id` (integer) so the tool can resolve UUID and list rt_flow files.
- Without `patient_id`, the UTC window must be ≤ 6 hours (cross-patient guard).
- The tool queries `migrated_data.pc_timeseries` with `date` partition bounds and filters `` `crlyse-annotation` ``.
