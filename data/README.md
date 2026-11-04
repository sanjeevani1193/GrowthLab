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
