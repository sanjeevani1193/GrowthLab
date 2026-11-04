# Local data

All contents of this directory except this README are ignored by Git.
Do not commit raw events, customer/session identifiers, downloaded archives,
or derived customer tables. Source metadata and sample summary statistics
live in `docs/`; the real sample itself stays local.

Phase 0 inspected a 65,536-byte prefix of the official October ZIP through an
unauthenticated HTTP range request and extracted its first 100 CSV events into
`sample/2019-Oct.head100.csv`. This is a chronological head sample, not a random
sample or a usable training dataset. It cannot establish customer outcomes,
event frequencies, or full-file quality. The rest of the archive was not read,
so archive-wide integrity has not been checked.

Future downloads belong in `raw/`; future derived data belongs in `interim/`
or `processed/`. No complete monthly file has been downloaded. Ask before large
downloads or Kaggle authentication. Never store API tokens in this repository.
