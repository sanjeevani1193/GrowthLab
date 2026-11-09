# GrowthLab

A staged Customer Intelligence & Causal Decision Science portfolio project.

**Module 1 — REES46 Customer Purchase Prediction is complete through Phase 4.**
It includes acquisition/audit, reviewed cleaning policies, customer features,
chronological model comparison, validation-only calibration, and a frozen test
benchmark. The Phase 4 completion suite passed **66 tests with no skips**.

**Module 2 — RetailHero SMS experiment and uplift-policy evaluation is complete
through the final held-out evaluation (Phase 7), committed and pushed.**
It uses a separate retailer dataset and customer population from Module 1.
Campaign-effect estimates depend on an unverified randomization protocol and
treatment-propensity assumptions. The studies remain independent; their customers are never joined.

**Phases 0–10C are preserved at `cf97aca9ca95d7e5ee754dec0717dae815cf657b`.**
Experiment planning/simulations, hypothetical reward economics and final offline
product ranking are also complete. **Phase 11 Decision Studio is preserved at
`8b5b25054e66f7ea69f2778818db6ae01fca01c9`. Phase 12A local Docker packaging is
verified and approved for preservation; no public deployment has occurred.** The current
full local suite passes **344 tests with no skips** (338 existing + six packaging checks).

## GrowthLab Decision Studio

A Streamlit and Plotly interface for exploring frozen evidence and hypothetical
decisions. Seven workspaces cover Overview, Purchase Intelligence, RetailHero
Targeting, Experiment Lab, Reward Economics, Product Ranking and Methodology.

- Compare purchase models, top-decile purchaser capture and calibration.
- Inspect assumption-dependent RetailHero policies at saved 10/20/30% budgets.
- Change experiment-design assumptions; keep saved synthetic A/A and A/B results distinct.
- Calculate hypothetical reward contribution, break-even, scenarios and sensitivity.
- Compare final ranking at K=5/10/20, macro/micro recall and paired uncertainty.

Verified headlines: purchase **AUC 0.8487 / 5.92× predictive lift**; observed
RetailHero **training** SMS/control difference **+3.39 pp**, with learned targeting
superiority **not established**; synthetic **4.3% A/A false positives / 79.3% A/B
power**; final ML ranking **18.42% macro Recall@10 / 0.21625 NDCG@10**. These answer
different questions and do not establish increased real-world sales.

Run from the repository root with Python **3.12+** (tested with 3.14.7):

```sh
python3 -m venv .venv-studio
source .venv-studio/bin/activate
python -m pip install -r requirements-studio.lock
python -m streamlit run streamlit_app.py
```

Open the localhost URL printed by Streamlit. The public app uses only permitted,
committed **aggregate JSON** and pure planning/economics functions. It needs no
raw datasets, customer records, trained models, credentials or paid services.
The UI lock is separate from the research/modeling environments below.

See the [implementation and testing report](docs/decision_studio/phase11_implementation.md),
[metric/chart source map](docs/decision_studio/evidence_map.md), and
[fingerprinted evidence manifest](docs/decision_studio/evidence_manifest.json).
The 25 UI tests include all seven pages and a separate no-data-directory run.
Actual Chromium smoke checks cover desktop, mobile layouts and working controls.
Local Docker packaging is verified; no cloud deployment has been started.

## Local Docker run (Phase 12A)

On this Apple Silicon Mac, build and run the public aggregate-only app:

```sh
docker build --platform linux/arm64 -t growthlab-studio:phase12a .
docker run -d --name growthlab-phase12a --pull=never \
  --platform linux/arm64 -p 127.0.0.1:8502:8080 \
  --memory=512m --cpus=1 --pids-limit=128 \
  --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  --cap-drop=ALL --security-opt=no-new-privileges:true \
  growthlab-studio:phase12a
```

Open **http://127.0.0.1:8502**. Host port 8501 remains available for the original
Streamlit process. The image runs as UID 10001, binds internally to `0.0.0.0`,
and defaults to `PORT=8080`. To override it, pass `-e PORT=8091` and use a matching
mapping such as `-p 127.0.0.1:8503:8091`. No raw data, model or source volume is needed.

```sh
docker inspect --format '{{.State.Health.Status}}' growthlab-phase12a
docker exec growthlab-phase12a python docker/healthcheck.py
docker stop --time 10 growthlab-phase12a
docker rm growthlab-phase12a
```

The expected health endpoint is `/_stcore/health` (**HTTP 200 / `ok`**).
The verified image is **727.4 MB (~694 MiB)**; fresh HTTP readiness was **1.73 s**
with a 512 MiB limit. All seven workspaces and planning/reward interactions passed
inside the container. These are local smoke checks, not production load benchmarks.

See [Docker design, exact commands and verification](docs/deployment/phase12a_docker.md)
and the [small verification receipt](docs/deployment/phase12a_verification.json).
The build uses the existing UI pins plus Linux-required `watchdog`; the original
locks and app are unchanged. Only native Linux ARM64 was executed. Future Cloud
Run release requires a native **Linux AMD64** build/test; no emulation, external
image push or cloud resource creation was performed. Phase 12A is preserved; its verification containers have been stopped and removed.

| Additional completed study | Methodology |
| --- | --- |
| Synthetic experiment design and randomization | [Phase 8A](docs/experiments/phase8a_design.md) |
| Synthetic A/A calibration | [Phase 8B](docs/experiments/phase8b_aa_testing.md) |
| Synthetic A/B power validation | [Phase 8C](docs/experiments/phase8c_ab_testing.md) |
| Hypothetical reward economics | [Phase 9A](docs/rewards/phase9a_economics.md) |
| Hypothetical scenarios and sensitivity | [Phase 9B](docs/rewards/phase9b_scenarios.md) |
| REES46 ranking audit/design | [Phase 10A](docs/ranking/phase10a_data_design.md) |
| Candidate generation | [Phase 10B1](docs/ranking/phase10b1_candidate_generation.md) |
| Ranking baselines | [Phase 10B2A](docs/ranking/phase10b2a_ranking_baselines.md) |
| Lightweight ML reranking | [Phase 10B2B](docs/ranking/phase10b2b_ml_reranking.md) |
| Final offline ranking evaluation | [Phase 10C](docs/ranking/phase10c_final_evaluation.md) |

The following sections retain the detailed Module 1 and independent Module 2
research findings and reproduction instructions.

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
intervention-effect estimation is performed in Module 1; the RetailHero study
below is separate.

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
Phase 4 completion run passed **all 66 tests with no skips**; the current full
local suite passes **344 tests**.

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
provenance. Module 1 remains complete and unchanged; Module 2 results follow.

## Module 2 — RetailHero SMS targeting: final independent evaluation

This is a separate study of **200,039 experimental customers**, using the
[official X5 RetailHero data](https://ods.ai/competitions/x5-retailhero-uplift-modeling/data).
The source describes historical purchases before communication and a subsequent
binary purchase outcome. Attribution: X5 Retail Group / RetailHero, hosted by ODS.AI.
An explicit reuse license and assignment protocol were not found in the inspected
material; raw data remain local. These customers, features, and outcomes are not
joined to REES46, and the two studies' predictive lift/uplift metrics are not interchangeable.

Phase 5 froze treatment-stratified cohorts: **120,022 train / 40,008 validation /
40,009 final holdout**. Phase 6 built eight history-only customer features from
45,786,568 item rows and fitted fixed, modest response-propensity, S-Learner, and
T-Learner benchmarks. All profile predictors were excluded because snapshot timing
was uncertain. No model or preprocessing was refitted for final evaluation.

Before final outcome access, Phase 7 froze **S-Learner minus fixed-random targeting
at a 30% contact budget** as the primary comparison. Rankings, seeds, propensity
assumption, bootstrap rules, and memberships were unchanged. At 30%, each ranking
contacts **12,003 of 40,009 customers**.

| Final policy at 30% | Incremental purchasers per 1,000 population | 95% interval |
| --- | ---: | --- |
| Fixed-random reference | 10.20 | [3.02, 17.15] |
| Response-propensity ranking | 13.70 | [5.47, 22.40] |
| S-Learner primary challenger | 7.70 | [1.05, 15.33] |
| T-Learner secondary challenger | 10.50 | [3.22, 17.45] |

Values use inverse-propensity weighting under **assumed constant assignment
probability e=0.5**, with 500 paired, treatment-stratified customer bootstrap draws.
They are assumption-dependent estimates relative to contacting nobody, not
verified causal improvements or revenue effects.

The primary **S-minus-random difference is −2.50 per 1,000**, with 95% interval
**[−11.85, 7.45]**. S is numerically lower; superiority in either direction is
inconclusive. S-minus-response is **−6.00 [−17.33, 6.95]** per 1,000. T is
numerically above S at 30%, but their paired difference is also inconclusive.
Response has the highest 30%-budget point estimate, yet its advantage over random
is inconclusive and it was not promoted into the primary role after test access.

Validation's encouraging S-Learner ranking did not establish superiority there,
and it did not replicate as a numerical 30%-budget advantage in the final cohort.
Cautiously retain fixed-random targeting as the budget-matched reference; no
learned ranking has established an improvement. This does not prove random is
optimal or that heterogeneity is absent. The observed treated/control purchase-rate
difference is **+3.271 percentage points [2.320, 4.221]**; a positive overall
campaign association does not demonstrate useful customer-level targeting.

Limitations include unverified assignment/compliance and propensity, unknown exact
outcome horizon, proxy historical cutoff, possible interference/clustering, and
bootstrap intervals conditional on the fitted models. Secondary comparisons have
no multiplicity adjustment. No actual SMS cost, financial return, or individual
causal benefit is identified.

The final protocol and a one-use local ledger block another scoring evaluation.
Reproducibility checks use saved predictions and draws without reopening outcomes:

```sh
PYTHONPATH=src .venv/bin/python -m growthlab.retailhero.final_evaluation --verify
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

At Phase 7 completion the local suite passed **120 tests with no skips**; the
current full suite passes **344**. Raw
history, customer features, models, predictions, and bootstrap draws are ignored;
only aggregate evidence/figures, protocols, source and tests are reviewable.

| RetailHero phase | Evidence |
| --- | --- |
| [Phase 5](docs/causal/phase5_experiment_analysis.md) | Experiment audit, training-cohort effect and frozen splits |
| [Phase 6](docs/causal/phase6_uplift_modeling.md) | History features, benchmark fitting and validation-policy comparisons |
| [Phase 7 frozen protocol](docs/causal/phase7_frozen_protocol.md) | Prespecified primary comparison, controls and assumptions |
| [Phase 7 final report](docs/causal/phase7_final_evaluation.md) | Final intervals, curves, interpretation and verification |
| [Final aggregate evidence](docs/causal/phase7/final_summary.json) | Full-precision held-out estimates and provenance |

Phase 7 is preserved. The local Phase 11 Decision Studio presents these frozen
findings alongside the separate prediction, simulation, economics and ranking
workspaces; see the run instructions above. Phase 11 is visually approved and preserved with the application source and tests.
