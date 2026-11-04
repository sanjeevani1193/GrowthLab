# Local data

All contents of this directory except this README are ignored by Git.
Do not commit raw events, customer/session identifiers, downloaded archives,
or derived customer tables. Source metadata and sample summary statistics
live in `docs/`; the real sample itself stays local.

Phase 0 inspected a 65,536-byte prefix of the official October ZIP through an
unauthenticated HTTP range request and extracted its first 100 CSV events into
`sample/2019-Oct.head100.csv`. This is a chronological head sample, not a random
sample or a usable training dataset. It cannot establish customer outcomes,
event frequencies, or full-file quality. At that stage the rest of the archive
was not read, so archive-wide integrity had not been checked.

Phase 1 acquired the five official version-6 monthly files with explicit user
approval. `raw/` holds CSVs; `archives/` holds original ZIPs; `processed/` holds
local Parquet with the original fields plus parsed audit columns; `audit/`
holds the DuckDB database, spill directory and run logs. These are all ignored.
Source URLs, sizes, SHA-256 hashes and CRC results are recorded in
`docs/phase1/acquisition.json`. Reuse verified existing files rather than
redownloading. Authentication was not needed. Never store API tokens here.

Phase 2 preserves those inputs and writes derived files to `features/phase2/`:
`cleaned/` contains exact-distinct events; `customers.parquet` contains one row
per eligible customer with twelve predictors, target and QA metadata; `primary/`
contains separate train/validation/test files. `build.duckdb`, `spill/`, logs,
`history_checks.json` and `manifest.json` are local build/verification artifacts.
All are ignored. The aggregate report/provenance is in `docs/phase2/summary.json`.
Use only the frozen feature allowlist for future modeling: keys, target, gap
flags and other QA metadata are not predictors.

Phase 3 writes models, validation-only predictions, manifests, logs and plotting
caches to `models/phase3/`, all ignored. `validation_predictions.npz` contains
customer-level validation keys/labels/probabilities and must stay local.
There are no test predictions. Small aggregate validation evidence and charts
live in `docs/phase3/`; Phase 2 feature files are unchanged. The optional native
OpenMP dependency is stored under the ignored `.venv/native/`.
