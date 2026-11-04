# GrowthLab

A staged Customer Intelligence & Causal Decision Science portfolio project.

**Module 1 — REES46 Customer Purchase Prediction is complete through Phase 4.**
It includes acquisition/audit, reviewed cleaning policies, customer features,
chronological model comparison, validation-only calibration, and a frozen test
benchmark. The completed local run passes **all 66 tests with no skips**.

RetailHero, causal inference, uplift modeling, and further decision-intelligence
modules are **planned only**. They have not been implemented. No dashboard, API,
cloud deployment, or campaign-effect experiment is included.

## Business problem and prediction target

Can early shopping activity identify customers likely to purchase later?
Module 1 ranks observed customers for analysis and prioritization. It predicts
**at least one observed purchase in the 30 days after a customer's first seven
observed days of activity**.

One modeling row represents one eligible observed user ID. Define `first_seen`
globally across all five monthly files, then use:

- **Feature window:** `[first_seen, first_seen + 7 days)`.
- **Prediction time:** `first_seen + 7 days`.
- **Outcome window:** `[first_seen + 7 days, first_seen + 37 days)`.
- **Target:** `purchased_next_30d = 1` if a purchase event occurs in the outcome
  window; otherwise 0 for a complete eligible horizon.

All times are UTC; intervals are end-exclusive. First-week buyers remain
eligible, so the target includes repeat purchases. First observed does not prove
new-customer acquisition, and product purchase events are not order counts.

## Data source and attribution

Source: Michael Kechinov's
[eCommerce Events History in Cosmetics Shop](https://www.kaggle.com/datasets/mkechinov/ecommerce-events-history-in-cosmetics-shop),
provided by [REES46 Marketing Platform](https://rees46.com) and linked from the
[official REES46 dataset catalog](https://rees46.com/en/datasets).

The five version-6 monthly files cover **October 2019–February 2020**. The
publisher permits free use with links to Kaggle and REES46. Kaggle labels the
license **“Data files © Original Authors”**; this is not a CC0 declaration.
Raw data remains local and outside Git. See [data handling](data/README.md).

| Verified data fact | Value |
| --- | ---: |
| Raw events | **20,692,840 (~20.7M)** |
| Observed user IDs | 1,639,358 |
| Events after exact-row deduplication | 19,583,742 |
| Eligible customer rows with complete 37-day file coverage | **1,256,629 (~1.26M)** |
| Positive future-purchase labels among eligible rows | 23,760 |

Exact duplicates use all nine original decoded CSV fields. Raw files are
immutable; deduplication creates a separate local layer. Negative prices are
excluded from monetary summaries while their activity remains. Zeros are
retained and flagged; sessions are counted within customers. Sparse brand and
category text is deferred. The January 22 gap has explicit audit flags; the
primary evaluation calendar avoids it.

## Twelve behavioral predictors

Every predictor uses only the first seven observed days. Keys, target, future
events, timestamps, split assignments and audit flags are excluded from model
inputs through a fixed allowlist.

| Predictor | Meaning |
| --- | --- |
| `n_views_7d` | Product-view events |
| `n_carts_7d` | Cart additions |
| `n_removals_7d` | Cart removals |
| `n_purchases_7d` | Purchase events before scoring |
| `n_viewed_products_7d` | Distinct products viewed |
| `active_24h_bins_7d` | Active elapsed-day bins anchored to first appearance |
| `n_sessions_7d` | Distinct nonmissing sessions within the customer |
| `hours_since_last_event` | Recency at the fixed prediction timestamp |
| `cart_view_ratio_7d` | Cart count / view count; 0 if no views |
| `purchase_view_ratio_7d` | First-week purchase count / view count; 0 if no views |
| `median_view_price_7d` | Median finite nonnegative viewed price; includes zero |
| `view_price_unavailable_7d` | Indicator that no valid viewed price is available |

The price median remains nullable in feature data. Logistic Regression uses the
**training median 5.635**, the existing missingness indicator, and training-fitted
scaling. XGBoost uses native missing-value handling. Missing price is not treated
as an observed zero.

## Chronological evaluation

Splits use prediction time, in UTC with exclusive end dates. Customer IDs are
disjoint within this primary schedule. The model uses the small primary training
cohort; it is not trained on all 1.26M eligible rows.

| Split | Prediction interval | Customers | Positive labels |
| --- | --- | ---: | ---: |
| Train | [2019-10-08, 2019-10-13) | 87,760 | 3,814 |
| Validation | [2019-11-12, 2019-11-17) | 53,089 | 1,150 |
| Test | [2019-12-17, 2019-12-22) | 51,444 | 547 |

Training outcomes mature before November 12; validation outcomes before
December 17. All test outcomes end before January 21, 2020. Selection and early
stopping used validation only. The selected model, features, metrics, calibration
method and tie policy were frozen before test assessment. The broader schedule
is preserved for future robustness work and has not been modeled.

## Verified held-out results

All models use **51,444 test customers / 547 purchasers (1.063%)**. Top 10%
means **5,145 customers**, with a fixed label-independent seeded tie rule.
Raw XGBoost was selected before test scoring and remains the primary ranking model.

| Model | AP | ROC-AUC | Precision at 10% | Recall at 10% | Predictive lift | Purchasers captured |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Training-prior dummy | 0.0106 | 0.5000 | 1.13% | 10.60% | 1.06× | 58 |
| Logistic Regression | 0.0737 | 0.8081 | 4.72% | 44.42% | 4.44× | 243 |
| **Raw XGBoost** | **0.1025** | **0.8487** | **6.30%** | **59.23%** | **5.92×** | **324** |

Approximate 95% customer-bootstrap intervals for XGBoost are **[0.0845, 0.1263]
for AP** and **[55.35%, 63.66%] for top-10% recall**. These are conditional on
fitted models and this short cohort; they exclude some temporal and training
uncertainty. Test results were not used to revise models or select features.

### Calibration and limitations

A sigmoid fitted **only to frozen validation scores and labels** is a secondary
probability variant. It preserves XGBoost's ranking and selected customers.

| Probability metric | Raw XGBoost | Validation-calibrated XGBoost |
| --- | ---: | ---: |
| Brier score | 0.011243 | 0.010181 |
| Log loss | 0.057434 | 0.049743 |
| Mean predicted probability | 3.058% | 1.818% |
| Observed test prevalence | 1.063% | 1.063% |

Calibration reduces held-out Brier score by **9.45%** and log loss by **13.39%**,
but residual overprediction remains. It does not establish reliable deployment
probabilities. Purchase prevalence fell from 4.346% in training to 2.166% in
validation and 1.063% in test. Absolute test AP/precision declined from validation,
while AUC and top-budget recall remained strong.

Other limitations include one retailer, five months of history, short scoring
cohorts, first-observation truncation, imperfect identity/order semantics and
uncertain instrumentation. **Predictive lift measures purchaser concentration;
it does not show that targeting changes behavior or increases revenue.** No
causal inference or uplift model has been implemented.

## Reproduction and verification

The full environment was verified with **Python 3.14.7 on Apple Silicon/macOS
14.5**. Exact dependencies are pinned; processing is locally memory-bounded.
Raw events are never loaded wholesale into pandas.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-modeling.lock
python -m pip install -e . --no-deps
```

If Apple Silicon XGBoost cannot load because OpenMP is missing, the optional
checksum-pinned local installer keeps the runtime inside `.venv` and requires
Python 3.14:

```sh
PYTHONPATH=src .venv/bin/python -m growthlab.openmp_runtime
```

**Verify this completed local run without new fitting or test predictions:**

```sh
PYTHONPATH=src .venv/bin/python -m growthlab.final_evaluation --verify-saved
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

Full verification requires existing local artifacts, intentionally not shipped
in Git. Some saved-artifact tests skip when local artifacts are absent; the
completed local run passes **all 66 tests with no skips**.

**Full re-creation belongs in a separate reproduction workspace/run record.**
It requires the five official monthly files (~2.43 GB expanded) and sufficient
scratch space. Acquisition is sequential and skips verified existing files.
These commands regenerate derived evidence/models; do not run them to overwrite
the completed benchmark while reviewing it.

```sh
growthlab-acquire
growthlab-audit --memory 1GB --coverage-end '2020-03-01 00:00:00'
PYTHONPATH=src .venv/bin/python -m growthlab.design_review
PYTHONPATH=src .venv/bin/python -m growthlab.features
PYTHONPATH=src .venv/bin/python -m growthlab.modeling
```

For a separate fresh evaluation record only, archive the shipped `docs/phase4/`
reference records in that reproduction workspace before running:

```sh
PYTHONPATH=src .venv/bin/python -m growthlab.final_evaluation --prepare
PYTHONPATH=src .venv/bin/python -m growthlab.final_evaluation --evaluate
```

The original plan and local one-use access ledger intentionally prevent a
second scoring run here. Never delete this run's ledger to try alternatives
against an already evaluated test cohort. Source, data and model hashes bind
each record to its inputs; Parquet byte ordering can differ across rebuilds.

Generated data stays under gitignored `data/`: raw files, audit/cleaned Parquet,
customer tables, databases, models, calibrator, predictions and bootstrap draws.
Only source, tests, specifications, documentation, and small aggregate results
and plots are versioned. See [the data directory guide](data/README.md).

## Methodology and evidence

| Phase | Completed work |
| --- | --- |
| [Phase 0](docs/phase0_feasibility.md) | Setup, official source/schema checks and feasibility |
| [Phase 1](docs/phase1_report.md) | Acquisition and full-data quality audit |
| [Phase 1.5](docs/phase1_5_design_decisions.md) | Cleaning policies, gap investigation, split and feature design |
| [Phase 2](docs/phase2_feature_engineering.md) | Customer features, boundary tests and independent raw-history checks |
| [Phase 3](docs/phase3_initial_modeling.md) | Dummy/Logistic/XGBoost validation comparison and model selection |
| [Frozen evaluation plan](docs/phase4_frozen_evaluation_plan.md) | Prespecified configuration, calibration, metrics and uncertainty |
| [Phase 4](docs/phase4_final_evaluation.md) | Held-out benchmark, calibration, intervals and business interpretation |
| [Final aggregate evidence](docs/phase4/test_summary.json) | Full-precision metrics, checks, hashes and resources |

Reports and frozen receipts retain their original phase-time status for
provenance. This README records the current state: **Module 1 is complete**.
Further causal, uplift and decision-intelligence modules remain future work.
