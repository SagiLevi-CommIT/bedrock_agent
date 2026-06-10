# Patient upload / coverage timeline

For "when did patient X upload", "which days are missing", "sleep vs rt per day",
"is there enough data to visualize/report" — use **`patient_timeline(patient_id,
start, end)`**. One call covers BOTH flows from migrated_data (0 S3 probes).

## What it returns
- `days[]`: per Asia/Jerusalem calendar day, `{date, sleep_files, rt_files}`.
- `days_with_data`: how many days in range have any data.
- `per_flow.{sleep_flow,rt_flow}`: `total_files`, `is_fully_covered`, `gap_count`,
  `missing_head_s`, `missing_tail_s`, and a `coverage_report`.
- `strategy`: should be `migrated` when the resolver/migrated path is healthy.

## Answering common questions
| Question | From timeline |
|---|---|
| "When did they upload last week?" | the `days[]` that have files |
| "Which days are missing?" | days in range absent from `days[]` (or with 0 files) |
| "Sleep vs RT per day?" | `sleep_files` / `rt_files` per day |
| "Enough to visualize a night?" | a day with `sleep_files > 0` + `per_flow.sleep_flow.is_fully_covered` |
| "Any gaps?" | `per_flow.*.gap_count` + the coverage_report |

## Notes
- Days are **Israel-local** (a 23:00 UTC upload belongs to the next local day).
- For a single flow's deeper coverage, follow up with `get_data_coverage` /
  `summarize_available_files`.
- This supersedes chaining native `patient_usage_summary` + per-flow listing for
  timeline questions (those remain the fallback if the tool-api is down).
