# GrowthLab

A staged Customer Intelligence & Causal Decision Science portfolio project.

**Current stage: Phase 1 — data acquisition and quality audit completed.**

The first planned module predicts whether a customer purchases in the next
30 days using their first seven observed days of activity. The prediction is
made at the end of those seven days. A separate causal inference and uplift
modeling module is a later project stage; it has not been implemented.

Completed: all five official monthly files acquired and verified locally;
memory-bounded DuckDB audit; customer-window feasibility counts; synthetic
boundary and safety tests. No customer feature pipeline, model, API, dashboard,
or cloud resources have been built. The causal module remains deferred.

Read [the Phase 1 findings](docs/phase1_report.md) for actual statistics,
data-quality decisions, eligibility, and the evaluation proposal. The
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

Acquisition uses the free public Kaggle API sequentially, checks disk space,
verifies ZIP CRCs, records hashes, and skips checksum-verified existing CSVs.
It refuses to overwrite unmanaged or changed existing files. No Kaggle token
is needed for this verified source. The audit writes ignored local Parquet and
DuckDB files plus a small aggregate JSON report in `docs/phase1/`.

Next: review the duplicate, price, logging-gap, and cohort decisions in the
Phase 1 report before authorizing a customer feature pipeline or modeling.
