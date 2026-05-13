# Patient lookup

- S3 filenames and many raw tables use integer `patient_id`.
- `migrated_data.*` analytics tables use UUID `patient` column.
- Call `resolve_patient_uuid(patient_id)` before Athena on migrated tables.
- Never use `LIKE '%605%'` on UUID columns.
