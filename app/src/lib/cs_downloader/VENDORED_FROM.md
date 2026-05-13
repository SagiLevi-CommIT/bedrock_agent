# Vendored from CardiacSense-s3-downloader-tool

- Source repo: `C:\Users\SagiLevi\Documents\Git\CardiacSense-s3-downloader-tool`
- Source commit: `31fcc29085cd7d93f098063418d96699990e9ef8`
- Vendored on: 2026-05-02
- Vendored by: Phase 1D of the bedrock_agent deep-knowledge upgrade.

## What was copied

| File in source | File here | Notes |
|---|---|---|
| `core/time_utils.py` | `time_utils.py` | unchanged |
| `core/probe.py` | `probe.py` | only `from config import ...` → `from .config import ...` |
| `core/boundary.py` | `boundary.py` | only `from config import ...` → `from .config import ...` |
| `core/s3_client.py` | `s3_client.py` | only `from config import ...` → `from .config import ...` |
| `core/gap_detector.py` | `gap_detector.py` | only `from config import ...` → `from .config import ...` |
| `core/downloader.py` | `downloader.py` | only `from config import ...` → `from .config import ...` |
| `config.py` (top-level) | `config.py` | **stripped**: kept FlowConfig, GeneralConfig, AppConfig dataclasses + `default_flows()`; removed JSON-disk loading, credential management, environment switching. Added per-flow defaults for all 8 flows (the original only had rt_flow + sleep_flow). |

`core/fetcher.py` and `core/visualizer.py` were intentionally NOT copied — they
pull in heavier dependencies and the bedrock_agent tools implement only the
lighter-weight workflow (list → probe → merge).

## Re-vendoring

When the source repo changes meaningfully, re-vendor by:
1. Bump source commit SHA above.
2. Re-run the import-rewrite step (replace `from config import` → `from .config import`).
3. Re-add any new flow entries to `default_flows()` if the source added them.
4. Run integration tests against staging to confirm parity.
