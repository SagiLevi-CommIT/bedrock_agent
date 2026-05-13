# Athena efficiency

Rules for keeping Athena scans cheap in CardiacSense staging.

## Partitioning

- `migrated_data.pc_results_part`, `pc_timeseries`: DATE-typed `date` partition.
  Filter with `WHERE date = DATE 'YYYY-MM-DD'` or `BETWEEN`.
- `migrated_data.timeseries`, `processed`, `processed1`: STRING-typed `date`.
  Use `WHERE date = 'YYYY-MM-DD'` (no `DATE` keyword).

## Workflow

1. Draft SQL.
2. Call `estimate_athena_scan`.
3. If above threshold, tighten partitions or ask the user.
4. Run `run_athena_query` with `confirm_heavy_scan=true` only after user confirms.

## Gotchas

- `SELECT *` on `pc_timeseries` for a full day can scan large amounts. Project columns.
- `LIKE '%foo%'` on wide string columns cannot use partitions; chunk by date first.
