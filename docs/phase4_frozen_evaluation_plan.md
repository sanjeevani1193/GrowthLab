# Phase 4 — evaluation plan fixed before test scoring

This document is written before Phase 4 loads test labels for model assessment.
Earlier phases already inspected aggregate test counts and checked data integrity;
this is the first planned model evaluation of that reserved cohort, not a claim
that nobody previously opened the underlying file.

## Frozen models, population and chronology

- Primary ranking model: the saved Phase 3 XGBoost model, best iteration **272
  zero-based (273 trees)**. No retraining, parameter changes or early stopping
  on test. The saved Logistic Regression pipeline and training-prior dummy are
  fixed baselines. Class weighting remains absent / `scale_pos_weight=1`.
- Exactly the same twelve predictors and order in `docs/phase2_specification.json`.
  IDs, target, timestamp/split fields and QA/gap metadata are excluded.
- All feature imputation/scaling stays training-fitted: Logistic Regression's
  median price **5.635** and scaler are unchanged. XGBoost retains native NaNs;
  the existing missing-price indicator remains. Missing price is not zero-filled.
- Test membership uses prediction times **[2019-12-17 00:00:00,
  2019-12-22 00:00:00) UTC**. One row per eligible observed customer ID.
  Verify disjoint customer keys and metadata before reading test targets.
- Evaluate only after all 30-day outcome windows mature: simulated cutoff
  **2020-01-21 00:00:00 UTC**. Confirm every included outcome end is no later
  than that cutoff. Actual execution is later still.
- Underlying weights are from training only; no training+validation refit.
  Validation selection and the authorized calibration are available by the
  December 17 cutoff, before test scoring begins, under event-time/zero-latency
  assumptions. The secondary mapping below is explicitly validation-fitted;
  it is not feature preprocessing.

Exact model parameters, seeds, source/data/artifact SHA-256 values, versions and
the Phase 3 commit are captured in [the machine-readable plan](phase4/frozen_plan.json).
The finalized plan, calibration receipt and runtime artifacts must pass their
fingerprint checks before the evaluator can read test labels.

## Prespecified secondary calibration

Fit one unweighted sigmoid/Platt mapping using only the frozen XGBoost
validation probabilities and validation labels:

`q = sigmoid(a * logit(clip(p, 1e-15, 1 - 1e-15)) + b)`.

Use an unpenalized one-score Logistic Regression with intercept: `C=inf`,
`l1_ratio=0`, `solver=lbfgs`, `tol=1e-10`, `max_iter=1000`, `random_state=42`.
There are only two fitted parameters, `a` and `b`. No smoothing, class reweighting,
alternative link, grid search or test-based prior correction is permitted.
Require a converged positive validation slope; otherwise stop before test and
request review rather than silently changing the calibration method.

Record the validation source fingerprint, fit timestamp, parameters and
calibrator artifact SHA-256. No calibrated validation performance is presented
as unbiased evidence: those observations already selected the tree count and
now fit the mapping. Raw XGBoost remains the primary ranking model regardless
of the test probability-loss results. Calibration success is not assumed.

## Evaluation and contact-budget policy

Evaluate four variants: dummy, Logistic Regression, raw XGBoost and the frozen
validation-calibrated XGBoost. Generate one saved prediction set. Use identical
test customers and labels for every variant.

Report customer/positive counts and prevalence; Average Precision using
recall-increment weighting; ROC-AUC where defined; Brier score; log loss;
precision, recall, lift and actual purchasers captured in the top 10%; mean
predicted probability versus prevalence; and five-quantile-bin reliability/PR
plots. Ranking metrics and tie handling use the existing Phase 3 functions.

Top 10% means **`ceil(0.1 * N)`**, hence **5,145** of the frozen 51,444 customers.
Order rows by user ID only for reproducibility. Rank by descending score and
break exact ties using label-independent NumPy random priorities with **seed 42**.
Do not optimize a threshold, budget, tie policy or subgroup after seeing labels.
A positive sigmoid is monotonic in exact arithmetic; report whether finite
precision preserves the raw ranking. Never choose a new primary model from test.

## Uncertainty fixed in advance

Use **500 paired ordinary customer bootstrap resamples**, **seed 20261104**,
with 95% percentile intervals (2.5th and 97.5th percentiles). Each resample draws
N customer indices with replacement, sorts those indices to preserve key order,
and uses them for all four variants. Reapply the identical budget/tie rule.
Keep models and calibrator fixed; process one resample at a time on one worker.

Report intervals for AP, AUC, Brier/log loss, top-budget precision/recall/lift,
captured purchasers, mean prediction and prevalence. Prespecified paired
differences are raw-XGBoost minus Logistic Regression AP (primary contrast), AUC
and recall; and calibrated minus raw XGBoost Brier/log loss (secondary probability
contrasts). Positive ranking differences favor XGBoost; negative loss differences
favor calibration. No p-value-driven model revision or multiplicity claim.

These intervals assume independent customer sampling, conditional on this
cohort and the fitted artifacts. They do not include model-training/calibration
estimation uncertainty, repeated calendar effects, or future distribution shift.
Only five scoring dates are present, so they must not be treated as complete
deployment uncertainty. Percentile endpoints with 500 draws are approximate.

## Access and release boundary

`--prepare` writes the immutable plan first, fits the validation-only mapping,
then writes a freeze receipt binding both before test assessment. `--evaluate`
checks all fingerprints and claims an exclusive one-use local access ledger
before loading test targets. A second scoring invocation is rejected. If a run
is interrupted, do not erase the ledger silently; review the state first.

Saved-prediction verification may recompute the same metrics without new model
predictions or fitting. Models/calibrator/predictions/bootstrap draws stay in
ignored local data. Only small protocol/evaluation records and aggregate figures
are published in docs. Stop after the report; Phase 4 is not committed or pushed
until the user reviews it. No causal uplift, API, dashboard or cloud deployment.
