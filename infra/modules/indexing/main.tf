terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

# ───────────────────────────────────────────────────────────────────────
# Glue database for the agent's own indexed tables. Separate from
# `cardiacsense` and `migrated_data` so IAM stays clean.
# ───────────────────────────────────────────────────────────────────────
resource "aws_glue_catalog_database" "agent" {
  name        = var.agent_glue_database
  description = "Bedrock-agent-owned tables: cross-cutting rollups + missing flow indexes."
}

# ───────────────────────────────────────────────────────────────────────
# Sleep_flow rearrangement index — fills the biggest gap in Athena.
#
# Uses partition projection on patient_id + dt (date-from-filename) so we
# don't need a Glue crawler. The actual S3 path layout is flat:
#   rearrangement/sleep_flow/sleep_flow_{patient_id}_{epoch_ms}.csv
# Partition projection here is purely a query-pruning hint — the model
# emits WHERE clauses on dt and patient_id, and Athena uses those to scope
# the LIST. Since the files are NOT physically partitioned by dt, queries
# without dt filtering still scan the full prefix.
#
# Pragmatic note: we register sleep_flow as a CSV table with the same 38-ish
# columns as cardiacsense.rt_flow. The actual sleep_flow CSVs do NOT contain
# ECG columns; those will read as NULL/empty. This is acceptable for an
# index — the agent uses the table to count files, group by date, and pull
# representative samples; for full-fidelity sleep signal access, the agent
# uses S3 download + parse via merge_patient_window.
# ───────────────────────────────────────────────────────────────────────
resource "aws_glue_catalog_table" "sleep_flow_rearrangement_idx" {
  database_name = aws_glue_catalog_database.agent.name
  name          = "sleep_flow_rearrangement_idx"
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    EXTERNAL                  = "TRUE"
    "skip.header.line.count"  = "1"
    "classification"          = "csv"
    "csv.delim"               = ","
    "areColumnsQuoted"        = "false"
  }

  storage_descriptor {
    location      = "s3://${var.app_events_bucket}/rearrangement/sleep_flow/"
    input_format  = "org.apache.hadoop.mapred.TextInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.serde2.lazy.LazySimpleSerDe"
      parameters = {
        "field.delim"      = ","
        "serialization.format" = ","
      }
    }

    # Subset of columns that exist in sleep_flow files. The intersection with
    # cardiacsense.rt_flow's 38-col layout is an approximation; the agent
    # should DESCRIBE the table, not SELECT *.
    columns {
      name = "sampling_time"
      type = "bigint"
    }
    columns {
      name = "ppg"
      type = "double"
    }
    columns {
      name = "ppg_peak"
      type = "double"
    }
    columns {
      name = "hr_ppg"
      type = "double"
    }
    columns {
      name = "artifact"
      type = "double"
    }
    columns {
      name = "red"
      type = "double"
    }
    columns {
      name = "infra_red"
      type = "double"
    }
    columns {
      name = "acc_x"
      type = "double"
    }
    columns {
      name = "acc_y"
      type = "double"
    }
    columns {
      name = "acc_z"
      type = "double"
    }
    columns {
      name = "sp_o2"
      type = "double"
    }
    columns {
      name = "respiration_rate"
      type = "double"
    }
    columns {
      name = "tightnes"
      type = "double"
    }
  }

}

# ───────────────────────────────────────────────────────────────────────
# patient_daily rollup table.
#
# Per-patient-per-day-per-flow pre-aggregations. Lambda populates this once
# a day for the prior day (and a one-shot backfill on first deploy). Schema
# is wide enough to answer: file count, total bytes, total recording
# minutes, avg HR, avg SpO2, ECG-quality fraction.
# ───────────────────────────────────────────────────────────────────────
resource "aws_glue_catalog_table" "patient_daily" {
  database_name = aws_glue_catalog_database.agent.name
  name          = "patient_daily"
  table_type    = "EXTERNAL_TABLE"

  parameters = {
    EXTERNAL                       = "TRUE"
    "classification"               = "parquet"
    "projection.enabled"           = "true"
    "projection.dt.type"           = "date"
    "projection.dt.format"         = "yyyy-MM-dd"
    "projection.dt.range"          = "2024-01-01,NOW"
    "projection.dt.interval"       = "1"
    "projection.dt.interval.unit"  = "DAYS"
    "storage.location.template"    = "s3://${var.rollup_bucket}/rollup/patient_daily/dt=$${dt}/"
  }

  storage_descriptor {
    location      = "s3://${var.rollup_bucket}/rollup/patient_daily/"
    input_format  = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"

    ser_de_info {
      serialization_library = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
    }

    columns {
      name    = "patient_id"
      type    = "int"
      comment = "Bare integer patient id (matches S3 filenames). UUID mapping not stored here."
    }
    columns {
      name = "patient_uuid"
      type = "string"
      comment = "UUID for this patient if known via metadata join; nullable."
    }
    columns {
      name = "flow"
      type = "string"
      comment = "rt_flow / sleep_flow / ar_flow / af_ppg_flow / arrythmia_flow / algos_flow / plate_flow / tachycardia_flow"
    }
    columns {
      name = "stage"
      type = "string"
      comment = "rearrangement | post_computation | migrated"
    }
    columns {
      name = "file_count"
      type = "int"
    }
    columns {
      name = "total_bytes"
      type = "bigint"
    }
    columns {
      name = "min_sampling_time"
      type = "timestamp"
      comment = "Earliest filename-derived recording start in this day."
    }
    columns {
      name = "max_sampling_time"
      type = "timestamp"
      comment = "Latest filename-derived recording start in this day."
    }
    columns {
      name = "total_duration_min"
      type = "double"
      comment = "Estimated total recording minutes (file_count * flow chunk heuristic)."
    }
    columns {
      name = "avg_hr"
      type = "double"
    }
    columns {
      name = "avg_spo2"
      type = "double"
    }
    columns {
      name = "ecg_quality_pct"
      type = "double"
      comment = "Fraction of timeseries rows in the day where qulity_ecg signal was usable. NULL for sleep_flow."
    }
    columns {
      name = "af_event_count"
      type = "int"
      comment = "Count of crlyse_annotation != NSR events in the day."
    }
    columns {
      name = "computed_at"
      type = "timestamp"
    }
  }

  partition_keys {
    name    = "dt"
    type    = "date"
    comment = "ISO date the rollup row covers."
  }

}
