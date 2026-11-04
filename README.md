# GrowthLab

A staged Customer Intelligence & Causal Decision Science portfolio project.

**Current stage: Phase 2 — customer feature engineering completed; ready for review.**

The first planned module predicts whether a customer purchases in the next
30 days using their first seven observed days of activity. The prediction is
made at the end of those seven days. A separate causal inference and uplift
modeling module is a later project stage; it has not been implemented.

Completed: all five official monthly files acquired and audited; reviewed
cleaning/split policies; a bounded DuckDB feature build with 12 predictors and
independent raw-history verification. No models, API, dashboard, or cloud
resources have been built. The causal module remains deferred.

Read [the Phase 2 report](docs/phase2_feature_engineering.md) for the final
training-data construction and checks, and the
[Phase 1.5 design](docs/phase1_5_design_decisions.md) for the approved rationale.
The [Phase 1 findings](docs/phase1_report.md) document the raw-data audit. The
[Phase 0 report](docs/phase0_feasibility.md) is retained as historical planning.

## Data and attribution

Source: Michael Kechinov's
[eCommerce Events History in Cosmetics Shop on Kaggle](https://www.kaggle.com/datasets/mkechinov/ecommerce-events-history-in-cosmetics-shop),
provided by [REES46 Marketing Platform](https://rees46.com), whose
[dataset catalog](https://rees46.com/en/datasets) identifies the Cosmetics data.
The publisher permits free use with links to Kaggle and REES46. Kaggle labels
the license “Data files © Original Authors”; this is not a CC0 declaration.
Raw data stays outside Git. See [data handling](data/README.md).

## Local setup

Python 3.11 or newer; DuckDB is pinned in `pyproject.toml`. Verified locally
with Python 3.14.7 and DuckDB 2.0.0.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python -m unittest discover -s tests -v
```

To reproduce acquisition and the audit from the repository root:

```sh
growthlab-acquire
growthlab-audit --memory 1GB --coverage-end '2020-03-01 00:00:00'
```

Build the approved feature data from the existing verified local files:

```sh
PYTHONPATH=src .venv/bin/python -m growthlab.features
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

The feature build writes only ignored local datasets under
`data/features/phase2/` plus a small aggregate summary in `docs/phase2/`.
The customer master has 1,256,629 rows. Primary train/validation/test have
87,760 / 53,089 / 51,444 rows and 3,814 / 1,150 / 547 positive labels.
Model inputs must use the explicit 12-column allowlist in
`docs/phase2_specification.json`; customer IDs, labels and QA fields are excluded.

Acquisition uses the free public Kaggle API sequentially, checks disk space,
verifies ZIP CRCs, records hashes, and skips checksum-verified existing CSVs.
It refuses to overwrite unmanaged or changed existing files. No Kaggle token
is needed for this verified source. The audit writes ignored local Parquet and
DuckDB files plus a small aggregate JSON report in `docs/phase1/`.

Next: review the Phase 2 datasets and checks before authorizing predictive
model development. No model training or tuning has been performed.
