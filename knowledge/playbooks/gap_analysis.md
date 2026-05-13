# Gap analysis

Use `coverage_report_from_athena` with a SELECT that returns `sampling_time` rows
for the window of interest, plus `start_utc` / `end_utc` and a `flow` name for
gap heuristics (`sleep_flow` vs `rt_flow`).
