# Schema Registry

## Purpose

The schema registry maps every known Glue table to its pipeline stage, key columns, cost profile, and optionally a full column-level schema file. It bridges the physical S3 catalog and the logical dataset families model.

## Structure

- `_index.json` — Master index of all schemas with metadata
- Individual schema files (future) — Full column definitions per table

## How It Works

### Current State (Placeholder)

Each entry in `_index.json` contains:
- **database / table** — Glue coordinates
- **stage / family** — Links to `dataset_families.json`
- **column_count** — Number of columns
- **key_columns** — Most important columns for queries
- **partition_keys** — Partition structure with types
- **cost_profile** — `low`, `medium`, `high`, `very_high`, or `broken`
- **schema_file** — `null` until full schema is extracted

### Future: Full Schema Files

When a table's full schema is extracted (via Glue `describe_table` or `DESCRIBE` in Athena), it will be saved as:

```
schema_registry/
  _index.json
  migrated_data.timeseries.json
  migrated_data.pc_results_part.json
  ...
```

Each file will contain the complete column list with types, comments, and any computed metadata.

## Adding a New Schema

1. Run `describe_table` via MCP or Glue CLI
2. Save the output as `{database}.{table}.json`
3. Update `_index.json` with `schema_file` pointing to the new file
4. Update `column_count` and `key_columns` if they changed

## Cost Profiles

| Profile | Meaning | Action |
|---------|---------|--------|
| `low` | Partitioned + Parquet, or small dataset | Safe for frequent queries |
| `medium` | Partitioned but large, or Parquet without partition | Always filter by partition |
| `high` | No partition, CSV, or large dataset | Use sparingly, always LIMIT |
| `very_high` | No partition + many columns + large row count | Avoid if possible |
| `broken` | Query will fail (format mismatch, etc.) | Do not use |

## Integration

The `tools/s3_knowledge.py` module reads this registry to provide schema-aware query recommendations. The agent consults it before building SQL to choose the right table and include required filters.
