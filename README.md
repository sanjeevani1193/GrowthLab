# GrowthLab

A staged Customer Intelligence & Causal Decision Science portfolio project.

**Current stage: Phase 3 — initial modeling completed on validation only; ready for review.**

The first planned module predicts whether a customer purchases in the next
30 days using their first seven observed days of activity. The prediction is
made at the end of those seven days. A separate causal inference and uplift
modeling module is a later project stage; it has not been implemented.

Completed: all five official monthly files acquired and audited; reviewed
cleaning/split policies; a bounded DuckDB feature build with 12 predictors;
independent raw-history verification; and Dummy, Logistic Regression and
XGBoost baselines compared on validation. No test predictions or test performance
have been computed. API, dashboard, cloud and causal modules remain deferred.

Read [the Phase 3 validation report](docs/phase3_initial_modeling.md) for model
choices, actual metrics, plots and calibration limitations. The
[Phase 2 report](docs/phase2_feature_engineering.md) describes the final
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

Core audit code requires Python 3.11+. The complete modeling environment and
full test suite were verified with Python 3.14.7 on Apple Silicon/macOS 14.5.
Modeling dependencies are optional in `pyproject.toml`; exact tested versions
are pinned in `requirements-modeling.lock`.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-modeling.lock
python -m pip install -e . --no-deps
```

If XGBoost cannot load on Apple Silicon because OpenMP is unavailable, use the
documented checksum-pinned, project-local fallback (requires Python 3.14):

```sh
PYTHONPATH=src .venv/bin/python -m growthlab.openmp_runtime
```

Then run the complete tests with
`PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`.

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

Run the three fixed baselines and validation plots:

```sh
PYTHONPATH=src .venv/bin/python -m growthlab.modeling
```

XGBoost achieved validation AP **0.1485** and top-10% recall **55.13%**, versus
Logistic Regression AP **0.1147** and recall **41.83%**. Both models overpredict
purchase probabilities on validation. See the report before interpreting the
results as probability estimates or business impact. Models and validation
predictions remain ignored under `data/models/phase3/`.

Phase 1.5 and Phase 2 are committed/pushed (`4e0dbf8`, `696feae`). Phase 3 changes
remain uncommitted for review. Next: select and freeze a final model/protocol
before explicitly authorizing a reserved test evaluation.
