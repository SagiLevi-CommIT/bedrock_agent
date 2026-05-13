# Time window files

For rt_flow overlap with a UTC window:

1. `list_patient_files` for a coarse listing (cheap).
2. `find_rt_flow_files_in_window` for bisect + probe overlap.
3. `probe_file_time_range` or `probe_files_batch` for ad-hoc checks.
