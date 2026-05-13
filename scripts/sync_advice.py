#!/usr/bin/env python3
"""Download agent advice markdown from S3 into knowledge/lessons/raw/ (no git commit)."""

from __future__ import annotations

import argparse
import os
from datetime import date, datetime
from pathlib import Path

import boto3


def _parse_since(s: str | None) -> date | None:
    if not s:
        return None
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> int:
    p = argparse.ArgumentParser(description="Sync advice/raw from S3 to local knowledge/lessons/raw/")
    p.add_argument("--bucket", default=os.environ.get("OUTPUT_BUCKET"), help="Agent output bucket name")
    p.add_argument("--prefix", default="advice/raw", help="S3 prefix under bucket")
    p.add_argument(
        "--dest",
        type=Path,
        default=Path("knowledge/lessons/raw"),
        help="Local destination directory (must stay under knowledge/lessons/raw)",
    )
    p.add_argument("--since", help="Only keys with date segment YYYY-MM-DD >= this (UTC)")
    p.add_argument("--profile", default=os.environ.get("AWS_PROFILE"))
    p.add_argument("--region", default=os.environ.get("AWS_REGION", "eu-central-1"))
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if not args.bucket:
        print("ERROR: pass --bucket or set OUTPUT_BUCKET")
        return 2

    dest = args.dest.resolve()
    if "lessons" not in dest.parts or "raw" not in dest.parts:
        print(f"ERROR: dest must live under .../lessons/raw, got {dest}")
        return 2

    session_kw: dict[str, str] = {"region_name": args.region}
    if args.profile:
        session_kw["profile_name"] = args.profile
    s3 = boto3.Session(**session_kw).client("s3")

    since_dt = _parse_since(args.since)
    prefix = args.prefix.strip("/") + "/"

    paginator = s3.get_paginator("list_objects_v2")
    downloaded = 0
    skipped = 0
    paths: list[Path] = []

    for page in paginator.paginate(Bucket=args.bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.endswith(".md"):
                continue
            parts = key.split("/")
            if len(parts) < 3:
                continue
            day_part = parts[-2] if parts[-1].endswith(".md") else ""
            try:
                d = datetime.strptime(day_part, "%Y-%m-%d").date()
            except ValueError:
                continue
            if since_dt is not None and d < since_dt:
                continue

            fname = parts[-1]
            local = dest / fname
            size_s3 = int(obj.get("Size", 0))
            if local.is_file() and local.stat().st_size == size_s3:
                skipped += 1
                continue

            if args.dry_run:
                print(f"DRY-RUN would download s3://{args.bucket}/{key} -> {local}")
                downloaded += 1
                paths.append(local)
                continue

            dest.mkdir(parents=True, exist_ok=True)
            tmp = local.with_suffix(local.suffix + ".tmp")
            s3.download_file(args.bucket, key, str(tmp))
            os.replace(tmp, local)
            downloaded += 1
            paths.append(local)

    print(f"downloaded={downloaded} skipped={skipped}")
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
