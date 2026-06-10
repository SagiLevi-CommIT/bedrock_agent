# Patient PDF reports (Cardiolyse) for rt_flow tests

The Cardiolyse summary **PDF** for an rt_flow recording lives in the
patient-reports S3 bucket (`735555370207-patient-reports`, staging) at
`arrythmia/<patient_id>/<Name>-<...>-<csv_epoch_ms>.pdf`. The `<csv_epoch_ms>`
matches the rt_flow CSV's filename epoch, so the tool maps test→PDF deterministically.

## Flow

1. Have the rt_flow CSV `file_key` (from `find_arrhythmia_events` /
   `get_data_coverage` with `flow="rt_flow"`).
2. `get_patient_report(file_key)` → status:
   - **ok** → a "Open PDF report" download button is attached. Say it's ready.
   - **glacier** → the PDF exists but is archived. Tell the user it needs a restore;
     if they agree, call `request_report_restore(pdf_key)` (Standard ≈ minutes,
     Bulk ≈ hours), then they re-check with `get_patient_report` later.
   - **not_found** → no report for that test; say so plainly.
   - **access_denied / not_configured / error** → report the status, don't guess.

## Don't
- Don't answer "I can't get reports" — call `get_patient_report` and report the
  real status (exists / where / needs restore / not found).
- Don't invent the PDF URL — the download button carries the real signed link.
- `request_report_restore` is **opt-in and mutating** — only after the user asks.

## Distinct from Cardiolys analysis
- **PDF report** = the pre-generated Cardiolyse summary document (this playbook).
- **Cardiolys analysis** (`submit_cardiolys_analysis`) = sending raw ECG to the
  EXTERNAL vendor for a fresh computation — requires explicit consent (`confirm_external=true`).
  Different things; don't conflate them.
