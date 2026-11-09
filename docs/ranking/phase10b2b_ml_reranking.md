# Phase 10B2B — one lightweight personalized ML reranker

Status: implementation and fixed development experiment complete, verified and
awaiting review. Evaluation date: **2026-11-09**. No final-test evaluation. This is the REES46 product-ranking
study, separate from Module 1's customer purchase classifier and RetailHero's
causal experiment. Nothing here estimates a voucher effect or online purchase gain.

## 1. Phase 10B2A preservation and unchanged retrieval

Reviewed the five approved files, ran **all 280 tests successfully**, and
reproduced every validation baseline metric **exactly**, including the complete
candidate membership hashes. Both previous module freezes, 82 recorded prior
data/artifact states, raw/cleaned data and both historical candidate databases
passed fingerprint checks. The staged allowlist contained only the five small
source, test, protocol, report and aggregate result files, with no datasets,
customer records, models, predictions, caches or credentials.

Phase 10B2A was committed and pushed as
**`e1336f37a1d233ae1cdeb3a116cd3b091f905f12`**. HEAD matched `origin/main` and Git
was clean before this phase. Earlier modules remain unchanged.

Use exactly the selected **personal history + popularity backfill, 100 products**
from [Phase 10B1](phase10b1_candidate_generation.md) and the baseline/metric
definitions from [Phase 10B2A](phase10b2a_ranking_baselines.md). Candidate sets,
eligibility, event cleaning, labels and timestamp boundaries are not changed
in response to ML results. Their full-population canonical hashes are checked.

| Role | Previous calendar month, UTC | Prediction time | Purchase labels, UTC |
| --- | --- | --- | --- |
| Training | [Oct 1, Nov 1, 2019) | Nov 1, 2019 00:00 | [Nov 1, Nov 15, 2019) |
| Validation | [Nov 1, Dec 1, 2019) | Dec 1, 2019 00:00 | [Dec 1, Dec 15, 2019) |
| Reserved final test | [Dec 1, 2019, Jan 1, 2020) | Jan 1, 2020 00:00 | **Not accessed or evaluated** |

Every interval is start-inclusive, end-exclusive. Events at prediction time
cannot be inputs; events at the label-window end cannot create positives.
First appearance is not acquisition. Eligibility still requires some historical
activity, not a future purchase. All eligible customers remain in validation
scoring, including those with no future purchases.

## 2. Frozen experiment before fitting

The [protocol](phase10b2b_protocol.json) fixes seven features, a single model
configuration, training-only sampling, score ties, evaluation, uncertainty and
selection rules. Source/protocol hashes and **both past-only feature databases**
are recorded in a local `experiment_freeze.json` before fitting labels are read.
No tuning grid, alternative real-data fit, early-stopping validation split or
post-result feature addition is used.

Primary comparison remains **macro Recall@10 and macro NDCG@10**. Prefer ML
only when both paired 95% lower bounds for ML minus recency exceed zero;
otherwise retain recency. This is a predefined validation selection rule,
not a guarantee of deployment value. No monetary/business minimum improvement
was supplied, so no such threshold is invented.

Validation is development evidence already used in earlier phases; it is not
an untouched independent final estimate. January final outcomes stay reserved.

## 3. Minimal past-only feature definitions

One training or scoring example is **(customer, prediction timestamp, candidate
product)**. Identifiers are join/sampling keys, not model predictors. All inputs
are available strictly before that snapshot from its previous calendar month.

| Exact feature | Calculation and handling |
| --- | --- |
| `product_views` | Count of cleaned `view` rows for this customer/product in the history window; 0 if unseen. |
| `product_carts` | Count of cleaned `cart` additions for this customer/product; not current cart contents; 0 if unseen. |
| `product_purchases` | Count of cleaned product-level `purchase` events for this customer/product; not order count; 0 if unseen. |
| `hours_since_product_event` | Elapsed hours from the most recent of all four historical event types to prediction time. Strictly positive for a seen pair; **NaN for unseen pairs**. |
| `product_buyers` | Distinct customers purchasing this product in that past month, across **all** historical products, not only the top-200 lookup. Repeated purchases by one user count once; absent count 0. |
| `customer_events` | Total cleaned events across all products and all four event types for the customer in the history month, including products not retrieved. |
| `from_personal_history` | 1 when the candidate has historical user/product activity, 0 for unseen popularity backfill. With this frozen retrieval these are precisely the personal versus backfill sources. |

The approved exact-nine-field deduplication remains upstream; it is not
recomputed here. Preserve purchases and activity with zero/negative prices;
there is no price/money feature. A cart removal contributes to recency and
overall activity, but is not counted as a view/cart/purchase or called a dislike.
Removal-only historical pairs have three zero type counts, finite recency and
source flag 1. Previously purchased products remain eligible.

Example (synthetic): two views, one cart, one purchase, then a removal, with
the last event twelve hours before scoring, yield type counts **2/1/1** and
recency **12 hours**. If the user has eight total historical events and the
product seven distinct buyers, the vector is **(2,1,1,12,7,8,1)**. A never-seen
backfill product has **(0,0,0,NaN,buyers,8,0)**, not an invented recent visit.

A real historical example for the shared popularity feature is October product
`5854897`: its **672 distinct past purchasers** give `product_buyers=672` for
any candidate row containing that product at the November snapshot. The user's
own counts and recency still differ; this catalog count is not a personalized
probability. No real customer history is published as a worked row.

No normalization, log transforms, fitted imputation, ID embedding, category,
brand, future catalog mapping or outcome statistics are added. Raw counts are
represented as float32 in the sampled training matrix. HistGradientBoosting
supports missing-value routing, so NaN recency does not require future-informed
imputation; see the [official classifier documentation](https://scikit-learn.org/stable/modules/generated/sklearn.ensemble.HistGradientBoostingClassifier.html).

### What the feature SQL does

`prepare_features` filters the verified cleaned monthly Parquet by explicit
history timestamps, valid keys and the four event types. It groups by customer
and product to compute the three counts, latest timestamp and all-event count.
Separate customer and product tables sum activity and count historical buyers.
Aggregating before joining avoids multiplying events in many-to-many joins.

Feature batches fetch only the current ≤1,000 customers. Timestamp checks reject
any pair outside the declared past window. Their old frozen candidate list is
generated with unchanged code and feature values are looked up afterward;
features or labels do not alter membership. Updates to November popularity at
December scoring are allowed because November is past then; fitting still uses
October features and training labels only.

## 4. What the model learns

The model is scikit-learn **HistGradientBoostingClassifier**, used as a
**pointwise scorer**. It learns to distinguish candidate rows with a subsequent
logged purchase from rows without one. A sequence of small decision trees
adjusts the prediction using patterns in these seven columns. Products with
higher scores are ordered earlier within the unchanged list.

This is **not a pairwise/listwise learning-to-rank objective**: it minimizes
weighted candidate-pair log loss, not Recall/NDCG directly. Customer activity is
constant across a user's candidates but can interact with item-level features.
Each customer has 100 potential rows, yet conditional purchaser-level ranking
metrics give equal weight to purchasers; the training/evaluation objectives
therefore differ. Most candidate pairs are nonpurchases, which can dominate
pointwise learning even when top-K ordering is the goal.

Fixed configuration:

| Parameter | Value |
| --- | --- |
| Loss | `log_loss` |
| Learning rate / iterations | **0.08 / 100** |
| Maximum leaves / maximum depth | **15 / None** (leaf limit bounds complexity) |
| Minimum samples per leaf | **50** retained examples |
| L2 regularization | **1.0** |
| Histogram bins | **63** |
| Early stopping | **False**; no internal/validation stopping choice |
| Class weights | None; explicit sampling weights used instead |
| Categorical features | None |
| Random seed | **20261109** |

One real-data model fit only. Tiny synthetic model fits in tests verify
determinism; they are not competing real-data experiments.

Preservation check before Phase 10C: the selected fitted model is available in
persistent, gitignored local storage at
`data/ranking/phase10b2b/model.joblib`. Its SHA-256 is
**`3c48c0d645a690bb603bebede3732eb664f4df7dfd8c2012909b5260f3a6cadd`**.
It is the 100-iteration model with the configuration above and in
`phase10b2b_protocol.json`; availability and checksum were verified before any
final ranking evaluation. Weights are kept out of Git. No refit is authorized
for that evaluation.

Use the model's `decision_function` **margin**, not a claim of calibrated
purchase probability. Sort by margin descending, then the frozen personalized
recency position, then product ID; do not round scores. The recency tie-break
is predeclared, so identical tree scores preserve the strong baseline order
rather than an arbitrary item order. It is part of the ML policy, not a hidden
after-the-fact blend. No probability calibration experiment is performed.

## 5. Training sampling and memory safety

The full training candidate population has **399,664×100 = 39,966,400** rows.
A label is 1 iff that candidate product is among the customer's distinct
observed purchases during November 1–14. Retain **all retrieved positives**;
products purchased outside the frozen shortlist are not injected into training.
A zero is an unobserved purchase, not explicit negative feedback or dislike.

Keep each training nonpurchase independently with probability approximately
**2%**, using SHA-256 of `growthlab-10b2b:20261109:user:product`, its first unsigned
64 bits, and threshold `floor(2^64/50)`. This is stable under input ordering and
requires no global RNG state. The integer-threshold probability differs from
0.02 by less than 1/2^64; inverse weights 50 use the stated 2% design.

Retained positives get weight **1**; retained nonpurchases get weight **50**.
For example, one retained zero represents about fifty full-population zeros
in expectation. No additional class-balancing weight is layered on top.
This is inverse-inclusion weighting: expected weighted pair loss approximates
the full training-candidate loss. The realized weighted class balance need not
equal the full population exactly. Sampling adds finite-sample variance and
may miss useful nonpurchase patterns; one seed is not evidence of robustness
across all possible training samples. No probability calibration is implied.

Feature vectors are constructed **only for retained training rows**, after the
training-only selection. A 1.5M-retained-row guard bounds the in-memory fit.
Only this small sampled float32 matrix enters the batch-only classifier; all
events remain disk-backed. No pandas frame over raw events or full candidate
rows is built. No validation customer or candidate is sampled for evaluation.

## 6. Evaluation and paired uncertainty

Score all **368,232 eligible validation customers ×100 = 36,823,200** candidates
in batches. Compare popularity, personalized recency and ML on identical
customers and list membership. All three canonical hashes must match the
pre-existing Phase 10B2A freeze. Both baseline metric dictionaries must reproduce
exactly, and candidate hits must reconcile to 17,292 /59,298.

Reuse the unchanged metric implementation at K=5,10,20:

- **Macro Recall@K:** mean fraction of purchased products recovered per
  purchasing customer; equal weight per purchaser.
- **Micro Recall@K:** total recovered purchased pairs /59,298; larger purchased
  baskets get more weight.
- **Macro NDCG@K:** binary gain, `1/log2(rank+1)` discount; ideal uses all future
  purchased products up to K, **including products outside the candidates**.
- **Candidate ceilings:** 29.16% micro, 32.37% macro; unchanged by reranking.
- No-purchase customers remain in list coverage; purchase Recall/NDCG are
  undefined for them. There are **5,693 purchasers** in the metric averages.
- All eligible customers have some personal history by the cohort definition;
  observed no-history performance is unavailable. No new cold-start cohort is
  selected based on future purchases.

For uncertainty, compute ML-minus-recency Recall and NDCG differences **for
each purchasing customer**. Draw 2,000 bootstrap samples of those 5,693 customers
with replacement, using seed **20261110** and the same sampled indices for all
six endpoints. Average the paired differences in each draw; use 2.5th and
97.5th percentiles as pointwise 95% intervals. Bootstrap draws are processed
25 at a time. No model is retrained during this calculation.

Pairing means a customer's two methods are always compared together. It
preserves the relationship between its basket and both rankings, unlike
resampling the methods independently or treating every item as an independent
customer. Recall differences are shown in **percentage points**; NDCG changes
stay on its 0–1 scale.

The intervals are conditional on this fitted model, training sample, retrieval
and one validation cohort. They do not include training-refit variance, shared
product dependence between users, calendar/season uncertainty, prior validation
exploration or online exposure bias. They are not simultaneous intervals across
all six endpoints. K=5/20 endpoints are secondary/exploratory. A positive interval
does not establish additional online purchases or financial value.

## 7. Actual results

The model and its original full validation completed. A final summary-export
error was corrected, with a no-fit verification run described below. All
numbers here are development evidence from the unchanged model, never January
final-test results. The [aggregate summary](phase10b2b_summary.json) records the
protocol, counts, metrics, intervals, artifact hashes and resource observations.

### Training population and retained sample

| Quantity | Observed value |
| --- | ---: |
| Full training customer–candidate rows | **39,966,400** |
| Positive candidate rows | **20,286** |
| Nonpurchase candidate rows | **39,946,114** |
| Full positive rate | **0.050758%** |
| Retained positive rows | **20,286** (all) |
| Retained nonpurchase rows | **799,417** |
| Total fitting rows | **819,703** |
| Retained-sample positive rate | **2.474799%** |
| Weighted total represented rows | **39,991,136** |
| Weighted positive rate | **0.050726%** |
| Training X/target/weight array bytes | **30,329,011 (~28.92MiB)** |

The weighted count differs slightly from the full count because a random 2%
sample is not exactly 2% in every finite dataset. It is not a missing-data
correction or a new population definition. The model completed **100 iterations**.
The sampled matrix has **763,177 missing recency values**, because most sampled
rows are unseen popularity-backfill pairs; NaN denotes absent historical
interaction, not an event at prediction time. This is expected under the
declared features and broad nonpurchase population.

The candidate-positive count is not all future training purchases. Of 66,018
future purchased pairs in the eligible training cohort, only 20,286 enter the
retrieved training universe. Missed products remain missed; none were injected
to make fitting or evaluation easier.

### Validation ranking comparison

All three methods use **368,232 eligible users, exactly 100 candidates each**,
with metrics averaged over the same **5,693 purchasing customers**. Micro Recall
uses the same **59,298 purchased pairs**. Recall columns are percentages;
NDCG is on the 0–1 scale.

| Ordering | K | Macro Recall@K | Micro Recall@K | Macro NDCG@K | Purchased-pair hits |
| --- | ---: | ---: | ---: | ---: | ---: |
| Popularity | 5 | 2.69% | 2.41% | 0.05868 | 1,427 |
| Popularity | 10 | 4.22% | 3.94% | 0.05624 | 2,338 |
| Popularity | 20 | 6.13% | 5.97% | 0.05927 | 3,542 |
| Personalized recency | 5 | 11.55% | 6.68% | 0.16993 | 3,964 |
| Personalized recency | 10 | **16.75%** | **11.11%** | **0.17786** | **6,587** |
| Personalized recency | 20 | 22.19% | 16.77% | 0.19368 | 9,942 |
| ML reranker | 5 | 13.00% | 8.23% | 0.21135 | 4,879 |
| ML reranker | 10 | **17.63%** | **12.60%** | **0.20650** | **7,470** |
| ML reranker | 20 | 22.21% | 17.60% | 0.21357 | 10,434 |

Candidate recall is still **17,292 /59,298 = 29.16% micro** and **32.37% macro**.
Eligible-user list coverage is **100%** for all three methods. No evaluation
candidate or customer is subsampled. The two baseline metric dictionaries
reproduce Phase 10B2A exactly, and all method membership hashes match its
pre-label full-population candidate freeze.

ML's larger NDCG gains at the top of the list indicate better placement of
relevant products near the beginning. Its nearly unchanged macro Recall@20
shows that better early ordering does not imply more products recovered at
every cutoff. NDCG can decrease between K values as the ideal denominator grows.

### Paired ML minus recency uncertainty

These are **2,000-draw paired purchaser-level, pointwise 95% percentile intervals**.
Recall differences are percentage points, not relative percentages.

| Endpoint | Observed difference | 95% interval | Interpretation for this fitted model/cohort |
| --- | ---: | ---: | --- |
| Macro Recall@5 | +1.449 pp | [+1.102, +1.787] pp | Positive secondary comparison |
| Macro NDCG@5 | +0.04142 | [+0.03606, +0.04657] | Positive secondary comparison |
| **Macro Recall@10** | **+0.882 pp** | **[+0.529, +1.214] pp** | Primary interval excludes zero |
| **Macro NDCG@10** | **+0.02864** | **[+0.02438, +0.03274]** | Primary interval excludes zero |
| Macro Recall@20 | +0.017 pp | **[−0.272, +0.308] pp** | Inconclusive; no established recall gain at K=20 |
| Macro NDCG@20 | +0.01988 | [+0.01632, +0.02333] | Positive secondary comparison |

Thus ML improves both frozen primary metrics, with positive intervals under
the stated conditional bootstrap assumptions. It is statistically convincing
**for those two purchaser-level validation comparisons**, not proof of an
online or future-cohort improvement. Secondary intervals are not jointly
corrected; the null-crossing Recall@20 result must not be described as a
demonstrated gain. No causal conclusion follows from any of these intervals.

### Magnitude, errors and preferred approach

At K=10, ML recovers **883 more observed purchased pairs** than recency,
an increase of **1.49 pp micro recall**, while mean-user recall rises only
**0.88 pp**. This is a modest measured ranking improvement, not an extra 883
people/orders or purchases caused by showing recommendations. No business
value threshold, cost or online conversion effect is known.

Specifically, **4,953** top-ten relevant pairs are recovered by both methods,
**2,517** by ML only, and **1,634** by recency only. Reporting only the 2,517
ML additions would hide displaced hits; 2,517−1,634=883 is the actual net gain.
The retrieved relevant pool contains **13,851 personal-history pairs** and
**3,441 backfill pairs**, not a universe of exclusively previously seen items.

Among purchasing users, Recall@10 improves for **957**, worsens for **598**, and
is unchanged for **4,138**. NDCG@10 improves for **1,784**, worsens for **1,197**,
and is unchanged for **2,712**. Gains are not universal; many individual lists
remain unchanged or unhelpful.

Of 59,298 relevant pairs, **42,006 are absent from the candidate set**, and a
further **9,822 retrieved pairs are outside ML's top ten**. These sum to its
**51,828 top-ten misses**. The first group is a retrieval limitation; the
second is an ordering limitation. Even perfect ordering cannot rescue the
42,006 missing products. Broad nonpurchase training dominance, sparse customer
histories, one training month, binned features and unknown exposure further
limit generalization. This experiment does not identify the cause of each
individual ranking error.

**Select the ML reranker as the preferred validation approach under the frozen
rule**, retaining personalized recency as the strong comparison/fallback.
Both primary lower bounds exceed zero. The absolute Recall@10 gain remains
modest, so retain these limitations rather than presenting complexity itself
as success. Do not change candidates, add features, tune another configuration
or inspect January outcomes in this phase.

### Export correction and verification provenance

The initial single fit and full validation succeeded, including baseline/hash
checks, paired bootstrap and saved purchaser-level metrics. Final aggregate
export then failed because the resource-size calculation used `root[path]`
instead of joining `root / path`. This was a reporting-path bug, not a change
to the model or evaluation methodology.

The exact original fit source is preserved locally and matches the original
experiment-freeze hash. A targeted resource-path regression test was added.
Source syntax-tree comparison confirms **all feature, sampling, fit, scoring,
metric and bootstrap functions are unchanged**; only export/recovery
orchestration changed. The frozen protocol is unchanged.

`--evaluate-saved` reconstructs the training sample and requires exact agreement
with the saved X/target/weight arrays (NaNs compared as equal), loads the saved
model **without fitting**, verifies its configuration, and re-evaluates every
validation candidate. Its purchaser metric vectors must equal the first
completed evaluation exactly. The saved model hash must remain unchanged.
This is a reproducibility check, not a second model or post-result tuning.

The original fit-only timing and peak RSS were not retained after the export
failure. They are **not invented or represented by the recovery measurements**.
The corrected default command records these on a fresh run; this session
preserves the one fitted model rather than fitting another for a benchmark.

The no-fit verification completed with the following **observed verification
costs**, not costs of a new fitting run:

| Component | Observed value |
| --- | ---: |
| Reconstruct/verify sampled training arrays | **93.14s** |
| Full validation scoring, metrics and paired intervals | **212.96s** |
| Total verification elapsed | **307.81s (~5.13 minutes)** |
| Verification peak process RSS | **350,732,288 bytes (~334.48MiB)** |
| Two local feature databases | **68,444,160 bytes (~65.27MiB)** |
| Sampled training X/target/weight arrays in RAM | **~28.92MiB** |

The summary correctly reports `fit_seconds: null` and
`fit_performed_this_run: false` for this recovery execution, while retaining
the original model's configuration, 100 iterations and hashes. Original
fit-only resource measurements are a reporting limitation. Main's current
default path records them on a fresh run; no second real-data model was fitted
in this session. Synthetic test fits are separate.

Each of the two DuckDB connections uses a **256MB engine limit**, one thread
and a 4GB spill cap; combined engine allowances can therefore reach 512MB.
The model/NumPy process uses additional memory, so those are not a total-RSS
limit. The measured verification RSS includes model loading and training-array
reconstruction, not the original fit peak. No peak temporary spill measurement
was taken. A 1.5M-row training-sample guard and the observed small training
arrays support memory feasibility; they are not a fabricated measurement of
the original model fit. Local free disk exceeded the 20GiB safety guard.

## 8. Reproducibility, verification and stopping point

Implementation: [`ml_reranking.py`](../../src/growthlab/ml_reranking.py).
Existing dependencies are reused; no installation or lock-file change. The
previous project-local OpenMP runtime is verified/preloaded, never downloaded.
The main fit and inference are constrained to one thread through
`threadpoolctl`; the [scikit-learn resource guide](https://scikit-learn.org/stable/computing/parallelism.html)
explains the distinction from `n_jobs`. Set CPU environment limits for a quiet,
bounded local run:

```sh
# Fresh fitting rerun only; replaces this phase's local artifacts.
mkdir -p data/ranking/phase10b2b
cp src/growthlab/ml_reranking.py data/ranking/phase10b2b/original_fit_source.py
LOKY_MAX_CPU_COUNT=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=src \
  .venv/bin/python -m growthlab.ml_reranking

# Existing frozen local model: verify/re-evaluate without fitting.
# Requires its matching experiment receipt, archived fit source and arrays.
LOKY_MAX_CPU_COUNT=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=src \
  .venv/bin/python -m growthlab.ml_reranking --evaluate-saved

LOKY_MAX_CPU_COUNT=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONPATH=src \
  .venv/bin/python -m unittest discover -s tests -v
```

Without the `LOKY_MAX_CPU_COUNT` setting, a synthetic fit initially emitted a
nonfatal physical-core detection warning in this sandbox. Explicit thread
limits were already in place; the documented CPU environment avoids that
auto-detection warning. No library, prior module or model was altered to fix it.

Only new local paths under ignored `data/ranking/phase10b2b/` hold feature
databases, the sampled training arrays, fitted model, freeze receipt and
purchaser-level metrics. Do not commit them. The aggregate summary records
their hashes for reproducibility, not their contents or customer IDs. Full
validation rankings/predictions are not exported. The model is reloaded and
checked for identical training-sample margins; an initial bounded validation
sample is scored twice to check deterministic inference.

**All 299 tests pass, no skips:** the 280 preserved tests plus **19 new tests**.
New tests cover hand-counted features and SQL boundaries, unseen/removal-only
pairs, future-event rejection, final-snapshot rejection, deterministic training
sampling, retention of every retrieved training positive, inverse weights,
unretrieved labels not injected, fitting/schema and train/validation guards,
small synthetic-fit reproducibility, identical ML candidate universes, score
ties, invalid margins, paired-bootstrap constants/zero/reproducibility, full
evaluation candidate counts and the two-primary-interval selection rule. The
resource-path regression test specifically covers the corrected export error.

An independent event-row check recomputed **67 real feature vectors across 24
historical customers** and matched counts, recency, activity and buyer totals.
A separate implementation reconstructed the entire **5,693-purchaser validation
population** directly from cleaned events, built its seven features and fixed
candidates, loaded the same saved model, and used independent native timestamp
sorts plus set/position-based metric arithmetic. All reported ranking aggregates
are checked against that reference. No customer details were exported; only
aggregate reference results were saved locally.

New review files only:

- `src/growthlab/ml_reranking.py`
- `tests/test_ml_reranking.py`
- `docs/ranking/phase10b2b_protocol.json`
- `docs/ranking/phase10b2b_summary.json`
- This report: `docs/ranking/phase10b2b_ml_reranking.md`.

Final checks passed: sampled fitting arrays reproduce exactly; repeated full
validation purchaser vectors match the original evaluation exactly; the model
file hash is unchanged; all baseline metrics and independent reference metrics
reconcile; both candidate-universe hashes, feature-layer hashes and local
artifact fingerprints match. Earlier module freezes, 82 prior data/artifact
states, raw/cleaned data, frozen retrieval databases, Phase 7 final artifacts
and Phase 8 experiment inputs/aggregates remain unchanged. The five review
files are the only untracked files, nothing is staged, and HEAD remains the
pushed Phase 10B2A commit. Models/arrays/databases and the archived fitting
source remain ignored. The only unresolved measurement limitation is the
original fit-only resource timing/peak noted above.

No January final-test outcomes, changed retrieval, hyperparameter search,
dashboard, Docker, deployment, causal module or unrelated enhancement is
included. All earlier modules stay unchanged. Phase 10B2B remains uncommitted
and unstaged for review. **Stop here.**
