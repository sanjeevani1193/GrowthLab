# Phase 7 frozen final-holdout evaluation protocol

Written before final-holdout outcome access. This protocol is bound by SHA-256
in `phase7/frozen_protocol.json`; the same record binds the evaluator source,
tests, prior records, raw data, feature table, and saved models. A local exclusive
access ledger permits one final outcome extraction/scoring evaluation only.

## Population and unchanged inputs

Use precisely the Phase 5 `final_test` membership: 40,009 customers, comprising
20,012 controls and 19,997 treated customers. Preserve all 120,022 training and
40,008 validation memberships. Verify no overlaps and an exact one-to-one join
to the existing Phase 6 eight-feature table. Sorted membership/treatment hashes
are frozen without reading outcomes. This is not the unlabeled competition test.

Use the existing Phase 6 trained response, S-Learner, and T-Learner models and
training constant effect. No refitting, calibration, preprocessing updates,
hyperparameter selection, new features, or threshold adjustment is allowed.
HGB histogram bins/missing handling stay as trained. Phase 6 commit:
`ce0c851d58e5c9c783ce841f61f5851bf85423b0`.

## Primary and secondary comparisons

**Primary:** contact `ceil(0.30*N)` customers; S-Learner is the prespecified uplift
challenger, fixed-random targeting is the cautious reference. The primary
estimand is S minus fixed-random incremental purchase probability, expressed
per 1,000 population customers. Its paired two-sided 95% percentile bootstrap
interval is the primary uncertainty assessment. A positive point estimate is
numerical improvement; an interval spanning zero is inconclusive. No model is
selected by comparing final-holdout scores.

**Secondary:** T-Learner, response-propensity targeting, 10% and 20% contact
budgets, and contact-all/contact-none. Report all policies at 10%, 20%, and 30%,
all same-budget pairwise differences, S versus the all/none references, and
paired curve-area comparisons. These exploratory intervals are not adjusted for
multiple comparisons and cannot replace the prespecified primary comparison.
Contact-all/none use different contact resources; they are not budget-matched.

## Unchanged targeting and statistical rules

- Contact counts: ceiling of budget times N, including the boundary customer.
- Ordering: descending score, ascending SHA-256 of
  `20261105:policy:client_id`, then ascending ID. No treatment or outcome in ties.
  Constant training-uplift scores produce the same fixed-random ranking.
- Primary propensity: **assumed constant e=0.5**, not independently verified.
- With `z=T*Y/e-(1-T)*Y/(1-e)` and `b=(1-T)*Y/(1-e)`, policy value is
  `mean(b+pi*z)` and incremental value over contact-none is `mean(pi*z)`.
  Multiply incremental value by 1,000 for population-level purchaser units.
- Gain curve `G(k/N)=sum_top_k(z)/N`; AUUC is its trapezoidal integral.
  Unnormalized Qini area is `AUUC-G(1)/2`, with no perfect-curve normalization.
- **500 paired treatment-stratified customer bootstrap draws**, seed
  **20261106**, preserving each arm's size and reselecting exact top-k within
  each draw. Fixed fitted models/scores, no refits. Two-sided 95% percentile
  intervals. Reuse Phase 6's implementation unchanged.
- Report ordinary treated/control purchase-rate difference separately, with
  Phase 5's Wilson/Newcombe interval. It is not the primary policy comparison.
- Sensitivity: unchanged illustrative e=0.45 and e=0.55 stress checks and the
  realized treatment share, known from membership before labels. Reuse each
  frozen ranking; do not select a propensity from the outcomes. These are not
  confidence bounds for propensity and do not repair confounding.
- No SMS prices, financial revenue, or profit are assumed or estimated.

## Interpretation and access controls

All causal interpretations depend on the original experiment's exchangeability,
assignment probabilities, correct treatment/outcome measurement, no selective
post-assignment filtering, and no material interference. None is established by
similar arm counts. Profile timing remains uncertain, so the Phase 6 history-only
feature set is preserved. The historical anchor is a proxy, not a proven campaign
date. Customer bootstrap intervals omit training, protocol, and clustering
uncertainty; secondary comparisons are exploratory.

Freeze and hash this document and implementation before label extraction. First
verify inputs and exact membership; claim the access ledger before parsing any
holdout target. Parse only the authorized final IDs. Apply saved models with a
fit-blocking guard. Save predictions/draws only under ignored `data/retailhero/phase7`.
Subsequent verification uses saved final predictions/draws and never calls the
outcome loader or rescores the cohort. Do not delete the ledger to evaluate again.

Based on the primary result, discuss whether evidence supports preferring S over
random at the fixed budget, conditional on assumptions. Do not promote a secondary
winner into the primary role, tune models, or choose a new budget from these
results. Preserve the final result as the independent benchmark. Update reports
and README, then stop for review without committing or starting a dashboard.
